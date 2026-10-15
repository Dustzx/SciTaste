"""Execute pinned MLR-Agent and real Codex CLI with local session model responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from scitaste.backends.framework_responses_session import FrameworkResponsesSessionServer
from scitaste.model_nodes.session_exchange import retain_json

REPOSITORY = Path(__file__).resolve().parents[1]
PIN = "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker() -> int:
    from run_mlr_agent import run_mlr_agent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_mlr_agent(
        model_name="o4-mini-2025-04-16",
        lit_engine_name="o4-mini-2025-04-16",
        coding_agent="codex",
        task_path="/work",
    )
    retain_json(
        Path("/work/UPSTREAM_FINISHED.json"),
        {
            "native_pipeline_returned": True,
            "paper_present": Path("/work/results/paper.md").is_file(),
            "review_revision_owned_by_upstream": False,
        },
    )
    return 0


def isolated_command(workspace, state, upstream, overlay, codex, token, base_url):
    command = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/home",
        "--dir",
        "/local",
    ]
    for location in (
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
        "/etc/ssl",
        "/etc/fonts",
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/passwd",
        "/etc/group",
        "/etc/texmf",
        "/var/lib/texmf",
    ):
        if Path(location).exists():
            command += ["--ro-bind", location, location]
    for path in (Path(sys.prefix), REPOSITORY / "src", REPOSITORY / "scripts", upstream):
        command += ["--ro-bind", str(path), str(path)]
    command += [
        "--ro-bind",
        str(overlay),
        "/runtime-deps",
        "--ro-bind",
        str(codex),
        "/runtime-codex/codex",
        "--ro-bind",
        str(state / "bin"),
        "/launcher-bin",
        "--bind",
        str(state / "codex-state"),
        "/local/.codex",
        "--bind",
        str(workspace),
        "/work",
        "--chdir",
        "/work",
    ]
    # No user home/config/credentials or other tasks are mounted. Never change
    # HOME/CODEX_HOME: default OS home lookup resolves inside the isolated mount.
    environment = {
        "PATH": f"/launcher-bin:{Path(sys.executable).parent}:/usr/bin:/bin",
        "PYTHONPATH": f"/runtime-deps:{REPOSITORY}:{REPOSITORY / 'src'}:{upstream}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "OPENAI_API_KEY": token,
        "OPENAI_BASE_URL": base_url,
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "PIP_NO_INDEX": "1",
        "LANG": "C.UTF-8",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "XDG_CACHE_HOME": "/tmp/cache",
    }
    for name, value in environment.items():
        command += ["--setenv", name, value]
    return [*command, sys.executable, "-m", "scripts.run_mlr_agent_session", "--worker"]


def launch(args) -> int:
    source = args.upstream.resolve(strict=True)
    pin = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True)
    if pin != PIN or dirty.strip():
        raise ValueError("MLR-Agent requires its exact clean source pin")
    codex = Path(shutil.which("codex") or "").resolve(strict=True)
    version = subprocess.check_output([str(codex), "--version"], text=True).strip()
    continuation = None
    if args.resume_from:
        original = args.resume_from.resolve(strict=True)
        prior = json.loads((original / "RESULT.json").read_text())
        old = json.loads((original / "CONTRACT.json").read_text())
        if (
            prior["status"] != "failed-or-incomplete"
            or prior["exit_code"] != 1
            or prior["model_requests"] != 0
            or prior["accepted_replies"] != 0
            or list((original / "exchange").glob("*.request.json"))
            or "ModuleNotFoundError" not in (original / "native.log").read_text()
            or set(p.name for p in (original / "workspace").iterdir()) != {"task.md", "data"}
            or old["source_commit"] != pin
            or old["coding_cli_sha256"] != digest(codex)
            or old["task_sha256"] != digest(args.task.resolve(strict=True))
            or old["wall_seconds"] != args.wall_seconds
            or old["max_requests"] != args.max_requests
            or args.assets is None
            or old["public_assets"] != {p.name: digest(p) for p in args.assets.iterdir()}
        ):
            raise ValueError("Only a source/asset-identical pre-first-response dependency recovery")
        args.inherited_wall_seconds = time.time() - (original / "CONTRACT.json").stat().st_mtime
        if not 0 <= args.inherited_wall_seconds < args.wall_seconds:
            raise ValueError("Original lifecycle deadline expired")
        continuation = {
            "original_run": str(original),
            "original_contract_sha256": digest(original / "CONTRACT.json"),
            "original_failure_sha256": digest(original / "RESULT.json"),
            "original_failure_log_sha256": digest(original / "native.log"),
            "failure_before_first_model_response": True,
            "scientific_program_replayed_or_repaired": False,
            "original_failure_retained": True,
            "lifecycle_budget_reset": False,
            "runtime_dependency_recovery": True,
            "runtime_overlay": str(args.runtime_overlay.resolve(strict=True)),
        }
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "workspace"
    workspace.mkdir()
    shutil.copy2(args.task.resolve(strict=True), workspace / "task.md")
    if args.assets:
        # The caller must provide a public-only frozen directory, never a pack
        # containing private labels or raw archives. Hash every offered byte.
        assets = args.assets.resolve(strict=True)
        files = list(assets.iterdir())
        if any(not p.is_file() or p.is_symlink() for p in files):
            raise ValueError("Public assets must be an explicit flat regular-file export")
        (workspace / "data").mkdir()
        for path in files:
            shutil.copy2(path, workspace / "data" / path.name)
    state = output / "runtime-state"
    (state / "codex-state").mkdir(parents=True)
    (state / "bin").mkdir()
    wrapper = state / "bin/codex"
    wrapper.write_text('#!/bin/sh\nexec /runtime-codex/codex "$@" --skip-git-repo-check --json\n')
    wrapper.chmod(0o700)
    token = secrets.token_urlsafe(32)
    origin = time.monotonic()
    with FrameworkResponsesSessionServer(
        output / "exchange",
        token=token,
        max_requests=args.max_requests,
        wait_seconds=1800,
        max_body_bytes=8_000_000,
    ) as server:
        (state / "codex-state/config.toml").write_text(
            'model_provider = "session"\nweb_search = "disabled"\n'
            'approval_policy = "never"\n'
            "model_auto_compact_token_limit = 200000\n"
            "[features]\nresponses_websockets = false\nresponses_websockets_v2 = false\n"
            '[model_providers.session]\nname = "Local session transport"\n'
            f'base_url = "{server.base_url}"\nenv_key = "OPENAI_API_KEY"\n'
            'wire_api = "responses"\nrequest_max_retries = 0\nstream_max_retries = 0\n'
            "stream_idle_timeout_ms = 1800000\n"
        )
        contract = {
            "schema_version": "1.0",
            "framework": "mlr-agent",
            "source_commit": pin,
            "source_tree_clean": True,
            "source_files": {
                p.relative_to(source).as_posix(): digest(p) for p in source.rglob("*.py")
            },
            "coding_cli_version": version,
            "coding_cli_sha256": digest(codex),
            "task_sha256": digest(workspace / "task.md"),
            "public_assets": {p.name: digest(p) for p in (workspace / "data").iterdir()}
            if args.assets
            else {},
            "wall_seconds": args.wall_seconds,
            "inherited_wall_seconds": args.inherited_wall_seconds,
            "max_requests": args.max_requests,
            "model_provenance": "subagent-session; actual provider identity/usage unverified",
            "native_model_aliases": ["o4-mini-2025-04-16", "o4-mini"],
            "model_alias_is_not_backbone_identity": True,
            "native_sequence_unchanged": True,
            "coding_cli_is_real": True,
            "native_review_revision_available": False,
            "literature_configuration": "native ordinary text model, not provider web-search model",
            "nullable_usage_compatibility": "unknown usage fields null for native legacy SDK",
            "gpu_enabled": False,
            "formal_evidence_eligible": False,
        }
        if continuation:
            contract["continuation"] = continuation
        retain_json(output / "CONTRACT.json", contract)
        command = isolated_command(
            workspace,
            state,
            source,
            args.runtime_overlay.resolve(strict=True),
            codex,
            token,
            server.base_url,
        )
        with (output / "native.log").open("x") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
            )
            print(
                json.dumps(
                    {"output": str(output), "pid": process.pid, "status": "launched-not-complete"}
                ),
                flush=True,
            )
            try:
                code = process.wait(
                    timeout=max(
                        1,
                        args.wall_seconds
                        - args.inherited_wall_seconds
                        - (time.monotonic() - origin),
                    )
                )
                stop = "native-process-returned"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                code, stop = process.returncode, "lifecycle-wall-limit"
        paper = workspace / "results/paper.md"
        confirmation = workspace / "confirmation_feedback.json"
        result = {
            "status": "native-paper-delivered"
            if code == 0 and paper.is_file()
            else "failed-or-incomplete",
            "exit_code": code,
            "stop_reason": stop,
            "wall_seconds": round(time.monotonic() - origin, 6),
            "charged_wall_seconds": round(
                time.monotonic() - origin + args.inherited_wall_seconds, 6
            ),
            "model_requests": len(list((output / "exchange").glob("*.request.json"))),
            "accepted_replies": sum(
                json.loads(path.read_text()).get("status") == "completed"
                for path in (output / "exchange").glob("*.receipt.json")
            ),
            "paper": str(paper.relative_to(output)) if paper.is_file() else None,
            "confirmation": json.loads(confirmation.read_text())
            if confirmation.is_file()
            else None,
            "native_review_revision_available": False,
            "formal_evidence_eligible": False,
            "api_calls": 0,
            "actual_tokens": None,
            "cost_usd": None,
        }
        retain_json(output / "RESULT.json", result)
        print(json.dumps(result), flush=True)
        return 0 if code == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--runtime-overlay", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--wall-seconds", type=int, default=14400)
    parser.add_argument("--max-requests", type=int, default=80)
    parser.add_argument("--inherited-wall-seconds", type=float, default=0)
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Explicit unchanged-asset recovery of a dependency failure before any model request",
    )
    args = parser.parse_args()
    if args.worker:
        return worker()
    if any(getattr(args, key) is None for key in ("upstream", "task", "runtime_overlay", "output")):
        parser.error("upstream, task, runtime-overlay and output are required")
    if not 0 < args.wall_seconds <= 86400 or not 0 < args.max_requests <= 1000:
        parser.error("Invalid development lifecycle envelope")
    if not math.isfinite(args.inherited_wall_seconds) or not (
        0 <= args.inherited_wall_seconds < args.wall_seconds
    ):
        parser.error("Inherited wall cost must be finite and within the lifecycle envelope")
    return launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
