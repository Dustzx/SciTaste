"""Admit retained report delivery after a verified administrative deadline stop.

This never authorizes another research action or converts an observer receipt into
a native successful close. Pending model replies remain explicitly unconsumed.
"""

import hashlib
import json
import time
from pathlib import Path


def verified_report_stop(parent, contract, terminal):
    if terminal.get("status") != "native-workspace-observed-budget-stop":
        raise ValueError("Expected an explicit observer budget stop")
    path = (parent / terminal["observation_locator"]).resolve(strict=True)
    path.relative_to(parent / "deadline_guard")
    if hashlib.sha256(path.read_bytes()).hexdigest() != terminal["observation_sha256"]:
        raise ValueError("Observer close receipt changed")
    observation = json.loads(path.read_text())
    closed = json.loads((parent / "SESSION_CLOSED.json").read_text())
    guard = json.loads((parent / "deadline_guard/CONTRACT.json").read_text())
    contract_path = parent / "CONTRACT.json"
    source_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    envelope = contract["plan"]["resource_envelope"]
    origin = contract_path.stat().st_mtime - (contract.get("continuation") or {}).get(
        "inherited_duration_seconds", 0
    )
    ceiling = envelope["wall_seconds"] - envelope.get("native_paper_reserve_seconds", 0)
    if (
        closed != observation
        or source_hash != guard["source_contract_sha256"]
        or source_hash != observation["source_contract_sha256"]
        or guard["original_epoch_seconds"] != origin
        or guard["research_ceiling_seconds"] != ceiling
        or guard["deadline_epoch_seconds"] != origin + ceiling
        or observation["observed_epoch_seconds"] < origin + ceiling
        or observation["observed_epoch_seconds"] > time.time() + 1
        or observation["termination_cause"] != "original-research-ceiling"
        or observation["native_close_receipt"] is not False
        or observation["scientific_completion_inferred"] is not False
        or terminal["native_close_receipt"] is not False
    ):
        raise ValueError("Unverified administrative report-only stop")
    # A stale PID is not enough. Match the actual Python module and resolved
    # output argument; never inspect or emit unrelated process arguments.
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = (process / "cmdline").read_bytes().decode().split("\0")
        except (OSError, UnicodeError):
            continue
        if argv[1:3] != ["-m", "scripts.run_native_benchmark_task"]:
            continue
        if "--output" not in argv:
            continue
        target = Path(argv[argv.index("--output") + 1])
        if not target.is_absolute():
            try:
                target = (process / "cwd").resolve(strict=True) / target
            except OSError:
                raise ValueError("Cannot observe Native worker identity") from None
        if target.resolve() == parent:
            raise ValueError("Observed research worker remains live")
    return {
        "observer_receipt_sha256": terminal["observation_sha256"],
        "native_close_receipt": False,
        "report_only": True,
        "research_execution_authorized": False,
        "scientific_completion_inferred": False,
    }
