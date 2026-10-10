"""Separate policy configuration, assessed decisions and non-abstaining advice."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.schema.decisions import ResearchDecision


def summarize_policy_use(run: Path, output: Path):
    contract = json.loads((run / "CONTRACT.json").read_text())
    expected = contract.get("learned_allocation_policy_sha256")
    decisions = []
    for path in sorted((run / "loop").glob("decision-*.json")):
        raw = path.read_bytes()
        decision = ResearchDecision.model_validate_json(raw)
        trace = decision.lifecycle_taste_policy
        if trace and trace.family_policy_sha256 != expected:
            raise ValueError("Observed policy differs from the run contract")
        decisions.append(
            {
                "decision_id": decision.decision_id,
                "source_locator": path.relative_to(run).as_posix(),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "selected_action_id": decision.selected_action.action_id,
                "selected_tool": decision.selected_action.parameters.get("tool"),
                "policy_assessed": trace is not None,
                "policy_trace": trace.model_dump(mode="json") if trace else None,
                "selected_matches_recommendation": (
                    decision.selected_action.action_id == trace.recommended_action_id
                    if trace and not trace.abstained
                    else None
                ),
            }
        )
    traces = [row["policy_trace"] for row in decisions if row["policy_trace"]]
    terminal_path = run / "RESULT.json"
    result = {
        "source_run": str(run),
        "policy_configured": expected is not None,
        "policy_sha256": expected,
        "decision_count": len(decisions),
        "policy_assessment_count": len(traces),
        "abstention_count": sum(trace["abstained"] for trace in traces),
        "recommendation_count": sum(not trace["abstained"] for trace in traces),
        "nonzero_adjustment_count": sum(
            any(value != 0 for value in trace["action_adjustments"].values()) for trace in traces
        ),
        "decisions": decisions,
        "agent_terminal_record_present": terminal_path.exists(),
        "terminal_status": json.loads(terminal_path.read_text())["status"]
        if terminal_path.exists()
        else None,
        "causal_decision_change_established": False,
        "scientific_gain_established": False,
        "formal_evidence_eligible": False,
        "interpretation": "Recommendation agreement is not a no-policy counterfactual. "
        "Configuration, assessment and non-abstention are distinct events.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize_policy_use(args.run, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "decision_count",
                    "policy_assessment_count",
                    "abstention_count",
                    "recommendation_count",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
