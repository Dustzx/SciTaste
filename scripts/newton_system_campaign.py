"""Freeze and summarize a complete, explicitly development-only system comparison."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json

ARMS = ("external", "native", "taste")
TASKS = {
    "coulomb": "development_task_coulomb_v1.json",
    "underdamped": "development_task_underdamped_v1.json",
}


def freeze(project, output):
    output.resolve().relative_to((project / "evaluations").resolve())
    output.mkdir()
    tasks = []
    for name, filename in TASKS.items():
        path = Path("configs/evaluation/newtonbench") / filename
        raw = path.read_bytes()
        tasks.append(
            {
                "name": name,
                "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "identity": json.loads(raw),
            }
        )
    retain_json(
        output / "PLAN.json",
        {
            "schema_version": "1.0",
            "project_id": project.name,
            "purpose": (
                "Complete reviewed-experience to measured research-system development comparison"
            ),
            "tasks": tasks,
            "arms": list(ARMS),
            "limits": {
                "max_turns": 8,
                "max_queries": 24,
                "max_batch": 6,
                "max_session_requests": 32,
            },
            "run_ids": {
                f"{task}-{arm}": f"newton-complete-package-20260929-{task}-{arm}"
                for task in TASKS
                for arm in ARMS
            },
            "formal_evidence_eligible": False,
            "provider_api_calls_authorized": False,
            "gpu_execution_authorized": False,
            "scope": (
                "Previously used development families; no held-out claim or repeated Fourier task"
            ),
            "model_control": (
                "Separate context per system responder; declared session model, unmeasured tokens"
            ),
            "source_control": "Freeze accepted reviewed library before starting the Taste arm",
            "analysis": (
                "Report all planned arms including failures, exact scores, queries "
                "and source hashes; "
                "no superiority test"
            ),
            "fallback": (
                "If review rejects the candidate, record Taste unavailable "
                "instead of relabeling Native"
            ),
        },
    )


def summarize(project, output):
    plan = json.loads((output / "PLAN.json").read_text())
    rows, artifacts = [], {}
    contracts = {}
    for key, run_id in plan["run_ids"].items():
        directory = project / "evaluations" / run_id
        row = {
            "task": key.split("-")[0],
            "system": key.split("-")[1],
            "run_id": run_id,
            "status": "missing",
            "symbolic_accuracy": None,
            "rmsle": None,
            "queries": None,
            "tool_steps": None,
            "session_responses": None,
            "taste_consultations": 0,
            "verified_deliberations": 0,
            "fallbacks": 0,
            "selected_precedents": 0,
            "applicable_assessments": 0,
            "inapplicable_assessments": 0,
            "tool_errors": 0,
            "error": None,
        }
        result = directory / "RESULT.json"
        if result.exists():
            raw = result.read_bytes()
            data = json.loads(raw)
            row.update(
                status=data["status"],
                queries=data.get("queries_used"),
                tool_steps=data.get("tool_steps"),
                session_responses=data.get("accounting", {}).get("session_responses"),
                error=data.get("error"),
            )
            row.update(
                {
                    name: data.get("objective", {}).get("metrics", {}).get(name)
                    for name in ("symbolic_accuracy", "rmsle")
                }
            )
            artifacts[str(result.relative_to(project))] = hashlib.sha256(raw).hexdigest()
        if (directory / "CONTRACT.json").exists():
            contracts[key] = json.loads((directory / "CONTRACT.json").read_text())
        for path in (directory / "taste_deliberation").glob("[0-9]*.json"):
            record = json.loads(path.read_text())
            row["taste_consultations"] += 1
            row["verified_deliberations"] += int(record.get("reason") == "verified-deliberation")
            row["fallbacks"] += int(record.get("intrinsic_fallback", False))
            proposal = (record.get("runtime_receipt", {}).get("result") or {}).get("proposal") or {}
            row["selected_precedents"] += len(proposal.get("selected_case_ids", []))
            for assessment in proposal.get("assessments", []):
                row["applicable_assessments"] += int(assessment.get("verdict") == "applicable")
                row["inapplicable_assessments"] += int(assessment.get("verdict") == "inapplicable")
        trace = directory / "tools/TOOL_TRACE.jsonl"
        if trace.exists():
            row["tool_errors"] = sum(
                str(json.loads(line).get("observation", "")).startswith("Tool error:")
                for line in trace.read_text().splitlines()
                if line.strip()
            )
        rows.append(row)
    comparability = {}
    for task in TASKS:
        bound = [contracts.get(f"{task}-{arm}") for arm in ARMS]
        comparability[task] = {"all_contracts_present": all(bound)}
        if all(bound):
            for field in (
                "task_sha256",
                "tool_interface_sha256",
                "limits",
                "benchmark_commit",
                "max_session_requests",
            ):
                comparability[task][field] = all(item[field] == bound[0][field] for item in bound)
    report = {
        "rows": rows,
        "comparability": comparability,
        "source_artifacts": artifacts,
        "all_scored": all(row["status"] == "scored-development-run" for row in rows),
        "formal_evidence_eligible": False,
        "scientific_superiority_established": False,
        "caveats": [
            "Two development families are not a formal benchmark sample",
            "Consultation/accepted deliberation counts do not establish beneficial transfer",
            "Tokens and session cost unknown; no provider-diversity or matched-token claim",
            "External method is shared-tool-adapted upstream MLAgentBench ResearchAgent",
            (
                "Responders retained context across their arm's nodes/tasks; "
                "not stateless API isolation"
            ),
            (
                "Taste responder saw experience context even when "
                "explicit precedent selection abstained"
            ),
            "External runs received operator formatting assistance after retained tool errors",
            "Independent judge saw condition names in paths; not fully condition-blinded",
        ],
    }
    retain_json(output / "REPORT.json", report)
    with (output / "RESULTS.csv").open("x") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "summarize"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    (freeze if args.action == "freeze" else summarize)(args.project, args.output)


if __name__ == "__main__":
    main()
