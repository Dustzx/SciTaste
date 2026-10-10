"""Consume terminal real Native outcomes; don't count program wrappers as tools."""

import argparse
import json
from collections import Counter
from pathlib import Path

from scitaste.benchmark.evidence_synthesis import binding
from scitaste.benchmark.open_research import verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def summarize(project, study):
    root = project.resolve(strict=True)
    study = study.resolve(strict=True)
    study.relative_to(root / "evaluations")
    spec = json.loads(study.read_text())
    rows, contracts = [], []
    sources = [binding(root, study)]
    for condition, assignment in spec["allocations"].items():
        campaign_path = verified_asset(root, assignment["campaign"])
        campaign = json.loads(campaign_path.read_text())
        run = root / assignment["run"]
        terminal, contract_path = run / "RESULT.json", run / "CONTRACT.json"
        # A live partial assignment may not be mistaken for its final outcome.
        if not terminal.is_file():
            raise ValueError(f"Research assignment still pending: {condition}")
        result, contract = json.loads(terminal.read_text()), json.loads(contract_path.read_text())
        if contract["plan"]["research_harness"]["sha256"] != assignment["profile_sha256"]:
            raise ValueError("Harness profile differs from the frozen assignment")
        verified_asset(root, contract["plan"]["campaign"])
        if campaign["execution_brief"]["sha256"] != spec["scientific_task_sha256"]:
            raise ValueError("Scientific question changed across conditions")
        contracts.append(campaign)
        sources.extend(
            [binding(root, campaign_path), binding(root, terminal), binding(root, contract_path)]
        )
        trajectory_path = run / "loop/TRAJECTORY.jsonl"
        trajectory = [json.loads(line) for line in trajectory_path.read_text().splitlines()]
        sources.append(binding(root, trajectory_path))
        atomic, programs, failed_programs = [], 0, 0
        for turn in trajectory:
            outcome = turn["result"]
            if turn["selected"]["parameters"]["tool"] == "Execute Program":
                programs += 1
                failed_programs += outcome["status"] == "FAILED"
                atomic.extend(outcome.get("data", {}).get("steps", []))
            else:
                atomic.append(outcome)
        # Failed guards are attempts, but not tool dispatches. Preserve both.
        dispatched = [row for row in atomic if row.get("data", {}).get("tool")]
        request_types, consumed_types = Counter(), Counter()
        for request in sorted((run / "exchange").glob("*.request.json")):
            payload = json.loads(request.read_text())
            node = payload["node_name"]
            request_types[node] += 1
            if request.with_name(request.name.replace(".request.json", ".response.json")).is_file():
                consumed_types[node] += 1
        feedback_path = run / "workspace/confirmation_feedback.json"
        feedback = json.loads(feedback_path.read_text()) if feedback_path.is_file() else {}
        scored = feedback.get("result", {})
        primary = scored.get("primary_method")
        primary_row = next((s for s in scored.get("scores", []) if s["method"] == primary), {})
        metrics = primary_row.get("metrics", {})
        report = run / "workspace/report/report.md"
        submission = run / "workspace/submission/SUBMISSION.json"
        manifest = json.loads(submission.read_text()) if submission.is_file() else {}
        if submission.is_file() and primary is not None:
            if manifest["primary_method"] != primary:
                raise ValueError("Reported primary differs from the frozen submitted procedure")
        for path in (feedback_path, report, submission):
            if path.is_file():
                sources.append(binding(root, path))
        rows.append(
            {
                "condition": condition,
                "runtime_status": result["status"],
                "confirmation_status": feedback.get("status", "missing"),
                "complete_confirmation": scored.get("primary_scores", {}).get("unseen_combinations")
                is not None,
                "primary_method": primary,
                "primary_mean_condition_rmse": scored.get("primary_scores", {}).get(
                    "unseen_combinations"
                ),
                "complete_conditions": metrics.get("conditions"),
                "primary_pearson_delta": metrics.get("mean_pearson_delta"),
                "declared_failure_fraction": metrics.get("declared_failure_fraction"),
                "predeclared_procedures": len(manifest.get("methods", [])),
                "scored_procedures": len(scored.get("scores", [])),
                "paper_exists": report.is_file(),
                "model_requests_including_recovery": sum(request_types.values()),
                "consumed_model_responses": sum(consumed_types.values()),
                "model_requests_by_node": dict(request_types),
                "consumed_responses_by_node": dict(consumed_types),
                "selected_scientific_actions": len(trajectory),
                "atomic_tool_attempts": len(atomic),
                "atomic_tool_dispatches": len(dispatched),
                "failed_atomic_tool_attempts": sum(row["status"] == "FAILED" for row in atomic),
                "composed_programs": programs,
                "failed_programs": failed_programs,
                "research_and_report_elapsed_seconds": result.get("duration_seconds"),
                "confirmation_elapsed_seconds_nested_in_research": feedback.get("elapsed_seconds"),
                "session_tokens": None,
                "session_cost_usd": None,
                "jev_model_called": False,
                "paper_scientific_support_independently_assessed": False,
                "formal_evidence_eligible": False,
            }
        )
    for key in ("researcher_assets", "native_taste", "resource_envelope", "source_brief", "pack"):
        if contracts[0][key] != contracts[1][key]:
            raise ValueError(f"Matched condition changed: {key}")
    notice = study.parent / "OPERATIONAL_NOTICE.json"
    if notice.is_file():
        sources.append(binding(root, notice))
    summary = {
        "schema_version": "1.0",
        "scope": spec["claim_scope"],
        "assigned_workers": 2,
        "independent_task_families": 1,
        "source_bindings": sources,
        "rows": rows,
        "matching_verified": ["question", "public assets", "Taste", "ceiling", "underlying tools"],
        "interpretation": (
            "Descriptive single-family harness comparison, not causal Taste or Jev effectiveness. "
            "Session model identity and tokens/cost are unverified. Model errors, supplier setup "
            "latency and tool failures remain charged; fewer selected actions do not imply "
            "fewer atomic executions, better scientific claims or universally greater efficiency."
        ),
        "formal_evidence_eligible": False,
    }
    retain_json(study.parent / "RESULTS.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.project, args.study), indent=2))


if __name__ == "__main__":
    main()
