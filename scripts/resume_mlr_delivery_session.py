"""Separately charged native Codex continuation after a rejected reply envelope.

The first MLR-Agent failure remains immutable. This continuation cannot refit or
replace its frozen submission, and the unchanged upstream owns paper writing.
"""

from __future__ import annotations

import argparse
import json
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
from scripts.run_mlr_agent_session import PIN, digest, isolated_command, worker

PROMPT = (
    "The previous model reply was rejected for an incorrect transport fingerprint, not a "
    "scientific failure. Resume this actual thread only to complete the pending confirmation "
    "summary in results/results.md, refresh its existing figures from retained measurements "
    "if necessary, and provide your final coding answer. The trusted confirmation feedback "
    "already exists in confirmation_feedback.json. Keep all public and confirmation outcomes, "
    "failures, nulls, limits, primary choice and frozen source unchanged. Submission is now "
    "read-only: do not refit, rerun prediction, tune, refreeze, modify scientific code or invent "
    "measurements. No new experiment or API. Do not write results/paper.md yourself: the real "
    "unchanged MLR-Agent paper writer follows your completed coding thread. The original "
    "failed assignment remains failed; this is separately charged delivery continuation."
)


def delivery_worker(thread: str) -> int:
    result = subprocess.run(
        [
            "codex",
            "exec",
            "resume",
            "-m",
            "o4-mini",
            thread,
            PROMPT,
            "-c",
            'sandbox_mode="danger-full-access"',
        ],
        cwd="/work",
        check=False,
    )
    if result.returncode:
        return result.returncode
    if not Path("/work/results/results.md").is_file():
        raise ValueError("Actual coding continuation produced no results report")
    return worker()


def frozen_files(directory: Path) -> dict[str, str]:
    paths = sorted(directory.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("A frozen submission cannot contain symbolic links")
    return {p.relative_to(directory).as_posix(): digest(p) for p in paths if p.is_file()}


def resume(args) -> int:
    original = args.original.resolve(strict=True)
    prior = json.loads((original / "RESULT.json").read_text())
    contract = json.loads((original / "CONTRACT.json").read_text())
    receipts = sorted((original / "exchange").glob("*.receipt.json"))
    bad = [
        p
        for p in receipts
        if json.loads(p.read_text()).get("error") == "invalid_or_unbound_session_reply"
    ]
    if (
        prior["status"] != "failed-or-incomplete"
        or prior["paper"] is not None
        or prior["exit_code"] != 1
        or len(bad) != 1
        or prior["accepted_replies"] + 1 != prior["model_requests"]
        or not prior.get("confirmation", {}).get("executed_frozen_source")
        or not (original / "workspace/submission/READY").is_file()
    ):
        raise ValueError("Only a confirmed, post-READY envelope failure can continue delivery")
    upstream = args.upstream.resolve(strict=True)
    overlay = args.runtime_overlay.resolve(strict=True)
    pin = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(upstream), "status", "--porcelain"], text=True
    )
    codex = Path(shutil.which("codex") or "").resolve(strict=True)
    if (
        pin != PIN
        or pin != contract["source_commit"]
        or dirty.strip()
        or digest(codex) != contract["coding_cli_sha256"]
    ):
        raise ValueError("The original clean upstream and actual CLI must remain unchanged")
    rollouts = list((original / "runtime-state/codex-state/sessions").rglob("*.jsonl"))
    sessions = []
    for path in rollouts:
        first = json.loads(path.open().readline())
        if first.get("type") == "session_meta":
            sessions.append((first["payload"]["id"], path))
    if len(sessions) != 1:
        raise ValueError("One exact original coding thread is required")
    thread, rollout = sessions[0]
    inherited = time.time() - (original / "CONTRACT.json").stat().st_mtime
    remaining = contract["wall_seconds"] - inherited
    inherited_requests = prior["model_requests"]
    prior_attempts = []
    for attempt in args.prior_delivery_attempt:
        attempt = attempt.resolve(strict=True)
        attempt_contract = json.loads((attempt / "CONTRACT.json").read_text())
        attempt_result = json.loads((attempt / "RESULT.json").read_text())
        if (
            attempt_contract["original_run"] != str(original)
            or attempt_contract["original_bindings"]["RESULT.json"]
            != digest(original / "RESULT.json")
            or attempt_result["status"] != "failed-or-incomplete"
            or not attempt_result["submission_unchanged"]
        ):
            raise ValueError("Prior delivery attempts must bind this unchanged original failure")
        inherited_requests += attempt_result["model_requests"]
        prior_attempts.append(
            {"run": str(attempt), "result_sha256": digest(attempt / "RESULT.json")}
        )
    request_budget = contract["max_requests"] - inherited_requests
    if remaining <= 0 or request_budget <= 0:
        raise ValueError("Original lifecycle envelope is exhausted; no reset")
    snapshots = {name: digest(original / name) for name in ("CONTRACT.json", "RESULT.json")}
    submission = frozen_files(original / "workspace/submission")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace, state = output / "workspace", output / "runtime-state"
    shutil.copytree(original / "workspace", workspace)
    # CLI tmp/arg0 launch links refer to an expired sandbox binary. They are
    # ephemeral, not thread history or database state, and cannot be resumed.
    shutil.copytree(original / "runtime-state", state, ignore=shutil.ignore_patterns("tmp"))
    token = secrets.token_urlsafe(32)
    started = time.monotonic()
    with FrameworkResponsesSessionServer(
        output / "exchange",
        token=token,
        max_requests=request_budget,
        wait_seconds=1800,
        max_body_bytes=8_000_000,
    ) as server:
        configuration = state / "codex-state/config.toml"
        old_config = configuration.read_text()
        lines = old_config.splitlines()
        configuration.write_text(
            "\n".join(
                f'base_url = "{server.base_url}"' if line.startswith("base_url = ") else line
                for line in lines
            )
            + "\n"
        )
        retain_json(
            output / "CONTRACT.json",
            {
                "schema_version": "1.0",
                "kind": "native-mlr-delivery-continuation",
                "original_run": str(original),
                "original_bindings": snapshots,
                "failed_receipt_sha256": digest(bad[0]),
                "original_coding_session": thread,
                "original_rollout_sha256": digest(rollout),
                "original_submission": submission,
                "source_commit": pin,
                "coding_cli_sha256": digest(codex),
                "inherited_wall_seconds": inherited,
                "wall_seconds": contract["wall_seconds"],
                "inherited_model_requests": inherited_requests,
                "prior_delivery_attempts": prior_attempts,
                "native_coding_model_alias": "o4-mini; not actual supplier backbone identity",
                "remaining_model_requests": request_budget,
                "original_failure_replaced": False,
                "scientific_reexecution_permitted": False,
                "frozen_submission_read_only": True,
                "upstream_paper_writer_unchanged": True,
                "resume_prompt": PROMPT,
                "formal_evidence_eligible": False,
            },
        )
        command = isolated_command(
            workspace,
            state,
            upstream,
            overlay,
            codex,
            token,
            server.base_url,
        )
        tail = command.index(sys.executable)
        command = [
            *command[:tail],
            "--ro-bind",
            str(workspace / "submission"),
            "/work/submission",
            sys.executable,
            "-m",
            "scripts.resume_mlr_delivery_session",
            "--worker-thread",
            thread,
        ]
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
                    {
                        "status": "launched-not-complete",
                        "output": str(output),
                        "thread": thread,
                        "remaining_wall_seconds": remaining,
                    }
                ),
                flush=True,
            )
            try:
                code = process.wait(timeout=max(1, remaining - (time.monotonic() - started)))
                stop = "native-process-returned"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                code, stop = process.returncode, "inherited-lifecycle-wall-limit"
        if snapshots != {
            name: digest(original / name) for name in snapshots
        } or submission != frozen_files(workspace / "submission"):
            raise ValueError("Original failure or frozen scientific source changed")
        paper = workspace / "results/paper.md"
        result = {
            "status": "native-paper-delivered"
            if code == 0 and paper.is_file()
            else "failed-or-incomplete",
            "exit_code": code,
            "stop_reason": stop,
            "wall_seconds": time.monotonic() - started,
            "charged_wall_seconds": inherited + time.monotonic() - started,
            "model_requests": len(list((output / "exchange").glob("*.request.json"))),
            "accepted_replies": sum(
                json.loads(p.read_text()).get("status") == "completed"
                for p in (output / "exchange").glob("*.receipt.json")
            ),
            "paper": "workspace/results/paper.md" if paper.is_file() else None,
            "original_failure_replaced": False,
            "submission_unchanged": True,
            "native_review_revision_available": False,
            "formal_evidence_eligible": False,
            "api_calls": 0,
            "actual_tokens": None,
            "cost_usd": None,
        }
        retain_json(output / "RESULT.json", result)
        print(json.dumps(result), flush=True)
        return 0 if code == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-thread")
    parser.add_argument("--prior-delivery-attempt", type=Path, action="append", default=[])
    for name in ("original", "upstream", "runtime-overlay", "output"):
        parser.add_argument("--" + name, type=Path)
    arguments = parser.parse_args()
    if arguments.worker_thread:
        raise SystemExit(delivery_worker(arguments.worker_thread))
    if any(
        getattr(arguments, name) is None
        for name in ("original", "upstream", "runtime_overlay", "output")
    ):
        parser.error("original, upstream, runtime-overlay and output required")
    raise SystemExit(resume(arguments))
