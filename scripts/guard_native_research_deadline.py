"""Enforce the original research allocation across offline session-resume gaps.

This administrative supervisor never executes research or fabricates a native
completion. A stopped worker gets an explicitly observer-authored failure receipt.
"""

import argparse
import json
import os
import signal
import time
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json


def workers(run):
    found = []
    for entry in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = entry.read_bytes().decode().split("\0")
        except FileNotFoundError:
            continue
        # Match the actual Python invocation, not a shell/timeout containing it.
        if argv[1:3] != ["-m", "scripts.run_native_benchmark_task"]:
            continue
        if "--output" not in argv:
            raise ValueError("Native worker has no identifiable output")
        path = Path(argv[argv.index("--output") + 1])
        if not path.is_absolute():
            path = (entry.parent / "cwd").resolve(strict=True) / path
        if path.resolve() == run:
            found.append(int(entry.parent.name))
    if len(found) > 1:
        raise ValueError("Multiple workers own this run; do not signal ambiguously")
    return found


def descendants(pid):
    parents = {}
    for entry in Path("/proc").glob("[0-9]*/stat"):
        try:
            # The command name can contain spaces and parentheses.
            tail = entry.read_text().rsplit(")", 1)[1].split()
            parents[int(entry.parent.name)] = int(tail[1])
        except FileNotFoundError:
            continue
    owned, frontier = [], [pid]
    while frontier:
        children = [child for child, parent in parents.items() if parent in frontier]
        owned.extend(children)
        frontier = children
    return owned


def run_guard(project, run):
    project, run = project.resolve(strict=True), run.resolve(strict=True)
    run.relative_to(project / "evaluations")
    path = run / "CONTRACT.json"
    launch = json.loads(path.read_text())
    if launch.get("controller_owner") != "scitaste-native":
        raise ValueError("Require an actual source-bound Native run")
    budget = launch["plan"]["resource_envelope"]
    inherited = (launch.get("continuation") or {}).get("inherited_duration_seconds", 0)
    origin = path.stat().st_mtime - inherited
    ceiling = budget["wall_seconds"] - budget.get("native_paper_reserve_seconds", 0)
    if not 0 < ceiling <= budget["wall_seconds"] or time.time() < origin:
        raise ValueError("Invalid original research ceiling or clock")
    receipt_dir = run / "deadline_guard"
    receipt_dir.mkdir(exist_ok=False)
    binding = digest(path)
    retain_json(
        receipt_dir / "CONTRACT.json",
        {
            "source_contract_sha256": binding,
            "original_epoch_seconds": origin,
            "research_ceiling_seconds": ceiling,
            "deadline_epoch_seconds": origin + ceiling,
            "native_source_edited": False,
            "research_budget_reset": False,
            "scope": "Administrative deadline supervision; not a scientific action",
        },
    )
    workers(run)  # Resolve ownership before accepting the supervision contract.
    while not (run / "RESULT.json").exists() and time.time() < origin + ceiling:
        time.sleep(min(1, max(0, origin + ceiling - time.time())))
    if digest(path) != binding:
        raise ValueError("Run contract changed; do not signal or seal it")
    if (run / "RESULT.json").exists():
        retain_json(
            receipt_dir / "RESULT.json",
            {
                "status": "native-already-closed",
                "native_result_sha256": digest(run / "RESULT.json"),
            },
        )
        return 0
    owners = workers(run)
    signaled = []
    for pid in owners:
        # Descendants belong to this verified worker, never another project.
        for target in [*reversed(descendants(pid)), pid]:
            try:
                os.kill(target, signal.SIGTERM)
                signaled.append(target)
            except ProcessLookupError:
                pass
    stop_deadline = time.monotonic() + 15
    while workers(run) and time.monotonic() < stop_deadline:
        time.sleep(0.2)
    if workers(run):
        raise ValueError("Worker remains alive; preserve an unsealed observation")
    observed = {
        "close_source": "operator-observed-original-research-deadline",
        "native_close_receipt": False,
        "source_contract_sha256": binding,
        "observed_epoch_seconds": time.time(),
        "elapsed_seconds_since_original_launch": time.time() - origin,
        "signal": "SIGTERM",
        "signaled_owned_processes": signaled,
        "termination_cause": "original-research-ceiling" if owners else "worker-absent-at-ceiling",
        "scientific_completion_inferred": False,
        "actual_session_tokens": None,
        "actual_session_cost_usd": None,
    }
    retain_json(receipt_dir / "RESULT.json", observed)
    if not (run / "RESULT.json").exists():
        retain_json(
            run / "RESULT.json",
            {
                "status": "native-workspace-observed-budget-stop",
                "duration_seconds": max(0, time.time() - path.stat().st_mtime),
                "duration_semantics": (
                    "Observer wall time including offline resume gaps, not native process duration"
                ),
                "controller_owner": "scitaste-native",
                "whole_project_lifecycle_complete": False,
                "report_exists": (run / "workspace/report/report.md").is_file(),
                "close_source": observed["close_source"],
                "native_close_receipt": False,
                "observation_locator": "deadline_guard/RESULT.json",
                "observation_sha256": digest(receipt_dir / "RESULT.json"),
                "formal_evidence_eligible": False,
            },
        )
    retain_json(run / "SESSION_CLOSED.json", observed)
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run_guard(args.project, args.run))


if __name__ == "__main__":
    main()
