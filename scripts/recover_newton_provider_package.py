"""Retain terminal external outcomes and continue only unqueried Native attempts."""

import argparse
import concurrent.futures
import json
import subprocess
from pathlib import Path

from scitaste.backends.mlagentbench import provider_ledger_accounting
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project import ProjectRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads((args.package / "PLAN.json").read_text())
    project = args.package.parent.parent
    runtime = ProjectRuntime(project.parent.parent)
    native = []
    for item in plan["runs"]:
        directory = args.package.parent / item["run_id"]
        if item["arm"] != "external":
            if not (directory / "RESULT.json").exists():
                native.append(item)
            continue
        frozen = json.loads((directory / "FROZEN_SUBMISSION.json").read_text())
        if frozen["submission"] is not None:
            raise ValueError("Submitted hypotheses need their own scoring recovery, not rerun")
        rows = [
            json.loads(line)
            for line in (directory / "tools/TOOL_TRACE.jsonl").read_text().splitlines()
        ]
        query_count = 0
        for row in rows:
            try:
                observation = json.loads(row["observation"])
                query_count += len(observation.get("results", []))
            except json.JSONDecodeError:
                pass
        result = {
            **frozen,
            "status": "terminated-without-submission",
            "tool_steps": len(rows),
            "queries_used": query_count,
            "accounting": provider_ledger_accounting(directory / "logs/provider_calls"),
            "recovery": "Retained final outcome; no research or score replay",
        }
        retain_json(directory / "RESULT.json", result)
        runtime.update_run(
            project.name,
            item["run_id"],
            status=result["status"],
            artifact=str((directory / "RESULT.json").relative_to(project)),
            expected_revision=runtime.open(project.name).revision,
        )

    def resume(item):
        index = len(list(args.package.glob(item["run_id"] + ".recovery*.log")))
        with (args.package / (item["run_id"] + f".recovery-{index}.log")).open("x") as log:
            completed = subprocess.run(
                item["command"] + ["--resume-unqueried-provider"],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        print(
            json.dumps({"run_id": item["run_id"], "returncode": completed.returncode}), flush=True
        )

    retain_json(
        args.package / "RECOVERY_PLAN.json",
        {
            "reason": "Missing accounting interface and malformed first proposals",
            "external": "Retain terminal failures; no rerun",
            "native": "Recover only before first selected/executed tool; inherit provider ledger",
            "changes": "JSON mode and at most one automatic schema repair per proposal",
            "fairness": (
                "Post-launch Native-only repair; developmental, not a matched effect estimate"
            ),
            "additional_budget": 0,
        },
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(resume, native))
    rows = []
    for item in plan["runs"]:
        path = args.package.parent / item["run_id"] / "RESULT.json"
        rows.append(
            {
                "task": item["task"],
                "arm": item["arm"],
                "result": json.loads(path.read_text()) if path.exists() else None,
            }
        )
    report_index = len(list(args.package.glob("RECOVERED_REPORT*.json")))
    retain_json(
        args.package / f"RECOVERED_REPORT-{report_index}.json",
        {
            "rows": rows,
            "formal_evidence_eligible": False,
            "original_report": "REPORT.json",
            "recovery_plan": "RECOVERY_PLAN.json",
        },
    )


if __name__ == "__main__":
    main()
