"""Observe an interrupted pre-tool session wait, preserving its original budget.

This creates a checkpoint only when no worker/tool or uncommitted decision exists.
It neither executes an action nor declares native scientific completion.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from scitaste.executor.native_session_checkpoint import history, save_wait
from scitaste.model_nodes.session_exchange import load_retained_request, retain_json


def recover(project: Path, run: Path, request_path: Path, *, reason: str) -> dict:
    root, run, request_path = (
        project.resolve(strict=True),
        run.resolve(strict=True),
        request_path.resolve(strict=True),
    )
    run.relative_to(root)
    request_path.relative_to(run / "exchange")
    if any((run / name).exists() for name in ("RESULT.json", "SESSION_PENDING.json")):
        raise ValueError("Use an existing close/checkpoint; never replace it")
    contract_path = run / "CONTRACT.json"
    contract = json.loads(contract_path.read_text())
    request = load_retained_request(request_path)
    if (
        contract.get("controller_owner") != "scitaste-native"
        or contract.get("model_source") != "assistant-session"
        or request.expected_backend != "assistant-session"
        or request.node_name
        not in {"native-action-proposal", "native-action-preference", "research-tool-taste"}
    ):
        raise ValueError("Not a recognized Native pre-tool session request")
    consumed = request_path.with_name(request_path.name.replace(".request.json", ".response.json"))
    if consumed.exists():
        raise ValueError("The requested response was already consumed")
    package = Path(__file__).resolve().parent.parent / "src/scitaste"
    for name, expected in contract["source_sha256"].items():
        source = (package / name).resolve(strict=True)
        source.relative_to(package.resolve())
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Consumed Native source changed; do not create a new checkpoint")
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = (process / "cmdline").read_bytes().decode().split("\0")
            cwd = (process / "cwd").resolve(strict=True)
        except (OSError, UnicodeError):
            continue
        if cwd.is_relative_to(run / "workspace"):
            raise ValueError("A process still owns the research workspace")
        if (
            argv[1:3]
            not in (
                ["-m", "scitaste.executor.native_workspace"],
                ["-m", "scripts.run_native_benchmark_task"],
            )
            or "--output" not in argv
        ):
            continue
        target = Path(argv[argv.index("--output") + 1])
        if (target if target.is_absolute() else cwd / target).resolve() == run:
            raise ValueError("The original Native worker is still live")
    elapsed = time.time() - contract_path.stat().st_mtime
    envelope = contract["plan"]["resource_envelope"]
    if elapsed >= envelope["wall_seconds"] - envelope.get("native_paper_reserve_seconds", 0):
        raise ValueError("Original research ceiling exhausted; use report-only closure")
    # Existing checkpoint logic additionally rejects any unmatched decision/action.
    save_wait(run, request=request_path, elapsed=elapsed)
    record = {
        "status": "observer-restored-pre-tool-session-checkpoint",
        "reason": reason,
        "source_contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "request": request_path.relative_to(root).as_posix(),
        "request_fingerprint": request.fingerprint,
        "committed_actions": len(history(run)),
        "elapsed_seconds_from_original_launch": elapsed,
        "budget_reset": False,
        "research_actions_executed": 0,
        "scientific_completion_inferred": False,
        "observer_authored": True,
    }
    retain_json(run / "OBSERVED_WAIT_RECOVERY.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.project, args.run, args.request, reason=args.reason)))


if __name__ == "__main__":
    main()
