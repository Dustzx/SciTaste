"""Summarize immutable attempt outcomes without selecting favorable-only evidence."""

import json
import math
from collections import Counter
from pathlib import Path


def deliberation_summary(output: Path) -> dict:
    """Report recorded online behavior, never substitute post-hoc repaired responses."""
    reasons = Counter()
    invocations = Counter()
    for path in sorted((output / "taste_deliberation").glob("*.json")):
        record = json.loads(path.read_text())
        reasons[record.get("reason", "unknown")] += 1
        receipt = record.get("runtime_receipt")
        if receipt:
            invocations[receipt["outcome"]] += 1
    traces = []
    recommendation_choices = Counter()
    for path in sorted((output / "loop").glob("decision-*.json")):
        decision = json.loads(path.read_text())
        trace = decision.get("taste_deliberation")
        if trace:
            traces.append(trace)
            if trace.get("abstained") is False and trace.get("selected_case_ids"):
                recommended = trace.get("recommended_action_id")
                selected = (decision.get("selected_action") or {}).get("action_id")
                recommendation_choices[
                    "unresolved"
                    if not recommended or not selected
                    else "agreed"
                    if recommended == selected
                    else "disagreed"
                ] += 1
    summary = {
        "reason_counts": dict(reasons),
        "invocation_outcomes": dict(invocations),
        "controller_decisions_with_deliberation": len(traces),
        "controller_decisions_with_selected_precedents": sum(
            bool(trace.get("selected_case_ids")) and trace.get("abstained") is False
            for trace in traces
        ),
        "controller_abstentions": sum(trace.get("abstained") is True for trace in traces),
        "recommendation_choice_counts": dict(recommendation_choices),
        "recommendation_agreement_is_causal_effect": False,
        "scientific_benefit_demonstrated": False,
        "posthoc_validation_counted_as_online": False,
    }
    intentionally_disabled = reasons["taste-action-selection-disabled"]
    if intentionally_disabled:
        summary["intentional_intrinsic_selection_count"] = intentionally_disabled
        summary["selection_disabled_is_abstention_or_runtime_failure"] = False
    return summary


def summarize(output: Path):
    contract = json.loads((output / "CONTRACT.json").read_text())
    terminal = json.loads((output / "RESULT.json").read_text())
    task = contract["task"]
    attempts = []
    known_seconds = 0.0
    best_score = task.get("baseline_score")
    best_identity = "original-baseline" if best_score is not None else None
    for path in sorted((output / "tools/experiments").glob("attempt-*")):
        reservation = json.loads((path / "RESERVATION.json").read_text())
        result_path = path / "RESULT.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        value = result["data"].get("primary_value") if result else None
        seconds = result["cost"].get("wall_time_hours", 0) * 3600 if result else None
        if seconds is not None:
            known_seconds += seconds
        if (
            result
            and result["status"] == "SUCCEEDED"
            and type(value) in (int, float)
            and math.isfinite(value)
        ):
            improved = best_score is None or (
                value > best_score
                if task["objective_direction"] == "maximize"
                else value < best_score
            )
            if improved:
                best_score, best_identity = value, path.name
        attempts.append(
            {
                "attempt": path.name,
                "candidate_identity": reservation["candidate_identity"],
                "candidate_snapshot": str((path / "candidate").relative_to(output)),
                "status": result["status"] if result else "unresolved",
                "primary_value": value,
                "execution_seconds": seconds,
                "cost_complete": bool(result and result["data"].get("cost_complete") is True),
            }
        )
    taste = deliberation_summary(output)
    summary = {
        "status": terminal["status"],
        "attempts": attempts,
        "best_observed_identity": best_identity,
        "best_observed_value": best_score,
        "baseline_score": task.get("baseline_score"),
        "known_execution_seconds": known_seconds,
        "cost_complete": all(item["cost_complete"] for item in attempts),
        "api_cost_ceiling_usd": terminal.get("api_cost_ceiling_usd"),
        "formal_evidence_eligible": False,
        "taste_augmented": taste["controller_decisions_with_selected_precedents"] > 0,
        "grounded_deliberation": taste,
        "learned_allocation_policy_enabled": terminal.get(
            "learned_allocation_policy_enabled", False
        ),
        "learned_policy_scope": contract.get("learned_policy_scope"),
        "full_scitaste": False,
        "whole_idea_to_paper_loop": False,
        "multi_attempt_execution_observed": sum(item["status"] == "SUCCEEDED" for item in attempts)
        >= 2,
    }
    with (output / "ITERATIVE_SUMMARY.json").open("x") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
    return summary
