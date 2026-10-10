#!/usr/bin/env python3
"""Summarize actual upstream-agent evidence without promoting it to a formal comparison."""

import argparse
import json
from pathlib import Path

from scripts.run_mlrc_native_development_loop import _sha256, write_new


def summarize(output: Path):
    contract = json.loads((output / "CONTRACT.json").read_text())
    native = contract["role"] == "native-shared-tools-development"
    terminal = json.loads((output / "RESULT.json").read_text())
    trace_path = output / "tools/TOOL_TRACE.jsonl"
    trace = (
        [json.loads(line) for line in trace_path.read_text().splitlines()]
        if trace_path.exists()
        else []
    )
    result_path = output / "EXECUTION_RESULT.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    final_path = output / "tools/AGENT_FINAL.json"
    final = json.loads(final_path.read_text()) if final_path.exists() else None
    calls = sorted((output / "logs/provider_calls").glob("*.json"))
    observed_cost = 0.0
    unresolved_reservation = 0.0
    models = set()
    for path in calls:
        completion = path.with_suffix(".completion")
        if completion.exists():
            row = json.loads(completion.read_text())
            observed_cost += row["observed_usage_ceiling_usd"]
            models.add(row.get("served_model"))
        else:
            unresolved_reservation += json.loads(path.read_text())["liability_usd"]
    continuation = contract.get("continuation") or {}
    source_cost = continuation.get("imported_api_cost_ceiling_usd", 0.0)
    actions = [row["action"]["name"] for row in trace]
    measured = result["data"].get("primary_value") if result else None
    succeeded = result is not None and result["status"] == "SUCCEEDED"
    experiment_indices = [
        index
        for index, row in enumerate(trace)
        if row["action"]["name"] == "Run Experiment"
        and row["observation"].startswith("{")
        and json.loads(row["observation"]) == result
    ]
    loop_complete = bool(
        succeeded
        and final is not None
        and experiment_indices
        and any(
            row["action"]["name"] == "Write File"
            and row["observation"]
            == "Candidate source updated; no experiment has been run by this write."
            for row in trace[: experiment_indices[0]]
        )
        and len(trace) > experiment_indices[-1] + 1
        and actions[-1] == "Final Answer"
        and trace[-1]["observation"].startswith("Final answer recorded")
    )
    summary = {
        "status": terminal["status"],
        "agent_return_reason": terminal.get("reason", terminal["status"]),
        "upstream_revision": contract.get("upstream_revision"),
        "upstream_agent_sha256": contract.get("upstream_agent_sha256"),
        "tool_actions": actions,
        "measured_score": measured,
        "experiment_status": result["status"] if result else "not-requested",
        "execution_result_sha256": _sha256(result_path) if result else None,
        "agent_final_claim": final,
        "agent_claim_is_measurement": False,
        "development_edit_experiment_feedback_loop_completed": loop_complete,
        "new_api_cost_ceiling_usd": round(observed_cost, 9),
        "imported_api_cost_ceiling_usd": source_cost,
        "unresolved_api_reservations_usd": round(unresolved_reservation, 9),
        "total_known_api_cost_ceiling_usd": round(source_cost + observed_cost, 9),
        "new_served_models": sorted(str(model) for model in models),
        "formal_evidence_eligible": False,
        "matched_native_comparison": False,
        "whole_idea_to_paper_loop": False,
        "continuation": continuation or None,
    }
    path = output / "DEVELOPMENT_SUMMARY.json"
    if path.exists():
        if json.loads(path.read_text()) != summary:
            raise ValueError("existing summary differs; preserve it and investigate source changes")
    else:
        write_new(path, summary)
    report = output / "REPORT.md"
    if not report.exists():
        identity = "SciTaste Native Base" if native else "Upstream MLAgentBench"
        selection = (
            "The actual SciTaste controller selected each proposed tool action. "
            if native
            else "The actual pinned upstream ResearchAgent chose the actions. "
        )
        with report.open("x") as stream:
            stream.write(
                f"# {identity} — restricted-tools development\n\n"
                f"Agent status: {summary['status']}. "
                f"Experiment status: {summary['experiment_status']}.\n\n"
                f"Official measured score: {measured}. "
                f"Edit → experiment → feedback → final-answer loop completed: {loop_complete}.\n\n"
                f"Actions: {' → '.join(actions)}.\n\n"
                f"Known API liability ceiling including imported calls: "
                f"{summary['total_known_api_cost_ceiling_usd']} USD; unresolved reservations: "
                f"{summary['unresolved_api_reservations_usd']} USD. "
                "These are conservative accounting values, not provider invoices.\n\n"
                + selection
                + "Its tools were "
                "adapted to candidate-only file access and a fixed isolated experiment. "
                "This is not the stock tool environment or a matched Native comparison. "
                "The task is consumed development data. No whole idea-to-paper, formal "
                "benchmark performance or Taste benefit is established here.\n\n"
                "Exact agent claims are kept separately from measured executor evidence in "
                "DEVELOPMENT_SUMMARY.json; the source trajectory and any manual continuation "
                "are bound by CONTRACT.json.\n"
            )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(summarize(parser.parse_args().output), indent=2))
