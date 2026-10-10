"""Explicit report-only disposition of a failed, stopped session execution.

Unconsumed requests remain unconsumed. This receipt neither reopens research
nor changes the original terminal result or its scientific completion status.
"""

import json
import time
from pathlib import Path

from scitaste.executor.native_session_checkpoint import digest, workspace_hashes
from scitaste.model_nodes.session_exchange import load_retained_request, retain_json


def _inventory(parent, contract, terminal):
    if (
        contract.get("controller_owner") != "scitaste-native"
        or contract.get("model_source") != "assistant-session"
        or terminal.get("status") != "native-workspace-interrupted"
        or not (parent / "workspace/report/report.md").is_file()
    ):
        raise ValueError("Only retained reports from interrupted Native sessions are eligible")
    # A terminal file alone does not prove the tool/controller has stopped.
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = (process / "cmdline").read_bytes().decode().split("\0")
            cwd = (process / "cwd").resolve(strict=True)
        except (OSError, UnicodeError):
            continue
        if cwd.is_relative_to(parent / "workspace"):
            raise ValueError("A process still owns the research workspace")
        if (
            argv[1:3]
            not in (
                ["-m", "scripts.run_native_benchmark_task"],
                ["-m", "scitaste.executor.native_workspace"],
            )
            or "--output" not in argv
        ):
            continue
        target = Path(argv[argv.index("--output") + 1])
        if (target if target.is_absolute() else cwd / target).resolve() == parent:
            raise ValueError("The original Native controller is still live")
    exchange = Path(contract["session_exchange"]).resolve(strict=True)
    exchange.relative_to(parent)
    pending, consumed = [], {}
    for path in sorted(exchange.glob("*.request.json")):
        request = load_retained_request(path)
        response = exchange / (request.fingerprint + ".response.json")
        if response.is_file():
            if json.loads(response.read_text())["request_fingerprint"] != request.fingerprint:
                raise ValueError("Consumed response binding changed")
            consumed[response.relative_to(parent).as_posix()] = digest(response)
        else:
            pending.append(
                {
                    "request": path.relative_to(parent).as_posix(),
                    "request_sha256": digest(path),
                    "reply_consumed": False,
                }
            )
    return {
        "source_contract_sha256": digest(parent / "CONTRACT.json"),
        "source_result_sha256": digest(parent / "RESULT.json"),
        "trajectory_sha256": digest(parent / "loop/TRAJECTORY.jsonl"),
        "workspace_files": workspace_hashes(parent),
        "unconsumed_requests": pending,
        "consumed_responses": consumed,
    }


def close_for_report(project: Path, parent: Path, *, reason: str):
    parent = parent.resolve(strict=True)
    parent.relative_to(project.resolve(strict=True))
    if not reason.strip():
        raise ValueError("An explicit disposition reason is required")
    contract = json.loads((parent / "CONTRACT.json").read_text())
    terminal = json.loads((parent / "RESULT.json").read_text())
    record = {
        **_inventory(parent, contract, terminal),
        "status": "interrupted-session-retained-report-only",
        "reason": reason,
        "observed_epoch_seconds": time.time(),
        "observer_authored": True,
        "report_only": True,
        "research_execution_authorized": False,
        "scientific_completion_inferred": False,
        "source_failure_preserved": True,
        "budget_reset": False,
        "responses_written": 0,
    }
    retain_json(parent / "REPORT_ONLY_SESSION_CLOSURE.json", record)
    return record


def verified_terminal_report_closure(parent, contract, terminal):
    path = parent / "REPORT_ONLY_SESSION_CLOSURE.json"
    record = json.loads(path.read_text())
    expected = _inventory(parent, contract, terminal)
    if (
        any(record.get(key) != value for key, value in expected.items())
        or record.get("status") != "interrupted-session-retained-report-only"
        or record.get("observer_authored") is not True
        or record.get("report_only") is not True
        or record.get("source_failure_preserved") is not True
        or record.get("research_execution_authorized") is not False
        or record.get("scientific_completion_inferred") is not False
        or record.get("budget_reset") is not False
        or record.get("responses_written") != 0
        or not 0 < record.get("observed_epoch_seconds", 0) <= time.time() + 1
    ):
        raise ValueError("Report-only terminal disposition changed or exceeds its authority")
    return {
        "closure_sha256": digest(path),
        "source_failure_preserved": True,
        "report_only": True,
        "research_execution_authorized": False,
        "scientific_completion_inferred": False,
    }
