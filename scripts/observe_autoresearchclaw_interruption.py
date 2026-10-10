"""Close a proven-dead ARC launcher without pretending it produced a native receipt."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json


def observe(project, run, *, launcher_exit_code, evidence_reference):
    root, run = project.resolve(strict=True), run.resolve(strict=True)
    run.relative_to(root / "evaluations")
    if not 1 <= launcher_exit_code <= 255 or not evidence_reference.strip():
        raise ValueError("Require an observed unsuccessful launcher exit and its source")
    if (run / "SESSION_CLOSED.json").exists():
        raise ValueError("Never replace an existing framework close receipt")
    launch_path = run / "EXECUTION_CONTRACT.json"
    launch = json.loads(launch_path.read_text())
    if launch["framework"] != "AutoResearchClaw" or not launch["source_clean_at_start"]:
        raise ValueError("Not a source-bound clean ARC launch")
    # Check the actual Python module argument, not arbitrary text in a shell or
    # the observer's own command line. Do not print argv/environment credentials.
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            argv = (process / "cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        except PermissionError:
            raise ValueError("Cannot establish absence of a live ARC worker") from None
        if b"scripts.run_autoresearchclaw_session" in argv:
            raise ValueError("An ARC launcher/worker remains alive; do not seal or relaunch")
    upstream = Path("third_party/autoresearchclaw")
    pin = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(upstream), "status", "--porcelain"], text=True
    )
    if pin != launch["upstream_commit"] or dirty:
        raise ValueError("Original upstream source pin/cleanliness changed")
    now = time.time()
    elapsed = now - launch_path.stat().st_mtime
    if elapsed < 0:
        raise ValueError("Observation clock predates launch")
    evidence = {
        "source": "operator-observed-launcher-termination",
        "evidence_reference": evidence_reference,
        "launcher_exit_code": launcher_exit_code,
        "native_worker_exit_code": None,
        "termination_cause": "unknown",
        "absence_of_live_arc_process_verified": True,
        "framework_close_receipt_was_missing": True,
        "observed_epoch_seconds": now,
        "launch_sha256": hashlib.sha256(launch_path.read_bytes()).hexdigest(),
        "elapsed_semantics": (
            "Original contract timestamp through observation; includes recovery/coordination gaps, "
            "not native process duration"
        ),
        "scientific_completion_inferred": False,
        "supplier_api_calls": 0,
    }
    retain_json(run / "OBSERVED_TERMINATION.json", evidence)
    closed = {
        "return_code": launcher_exit_code,
        "wall_limit_or_interruption": True,
        "wall_seconds": elapsed,
        "retained_requests": len(list((run / "exchange").glob("*.request.json"))),
        "retained_responses": len(list((run / "exchange").glob("*.receipt.json"))),
        "supplier_api_calls": 0,
        "actual_session_tokens": None,
        "actual_session_cost_usd": None,
        "source_pin_unchanged": True,
        "close_source": evidence["source"],
        "native_close_receipt": False,
        "native_worker_exit_code": None,
        "termination_cause": "unknown",
        "elapsed_semantics": evidence["elapsed_semantics"],
        "observation_locator": "OBSERVED_TERMINATION.json",
        "observation_sha256": hashlib.sha256(
            (run / "OBSERVED_TERMINATION.json").read_bytes()
        ).hexdigest(),
    }
    retain_json(run / "SESSION_CLOSED.json", closed)
    return closed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--launcher-exit-code", type=int, required=True)
    parser.add_argument("--evidence-reference", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            observe(
                args.project,
                args.run,
                launcher_exit_code=args.launcher_exit_code,
                evidence_reference=args.evidence_reference,
            )
        )
    )


if __name__ == "__main__":
    main()
