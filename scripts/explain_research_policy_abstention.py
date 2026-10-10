"""Reproduce recorded policy assessments from frozen predecision states, without API calls."""

import argparse
import json
from pathlib import Path

from scitaste.schema.decisions import ResearchDecision
from scitaste.state.research_state import ResearchState
from scitaste.taste.decision_families import load_family_conditioned_lifecycle_taste_policy
from scitaste.taste.episode_learning import assess_lifecycle_taste_policy


def explain(run: Path, snapshots: Path, policy: Path, output: Path):
    model = load_family_conditioned_lifecycle_taste_policy(policy)
    rows = []
    for path in sorted((run / "loop").glob("decision-*.json")):
        decision = ResearchDecision.model_validate_json(path.read_bytes())
        trace = decision.lifecycle_taste_policy
        if trace is None:
            continue
        if trace.family_policy_sha256 != model.policy_sha256:
            raise ValueError("Policy differs from recorded decision")
        head = model.family_heads[trace.decision_family]
        state = ResearchState.model_validate_json(
            (snapshots / f"{decision.state_snapshot_id}.json").read_bytes()
        )
        # This is historical reproduction, not authorization to apply a policy now.
        assessment = assess_lifecycle_taste_policy(
            head,
            state=state,
            actions=tuple(decision.candidate_actions),
            current_idea_revision=head.config.idea_revision,
        )
        if assessment.assessment_sha256 != trace.assessment_sha256:
            raise ValueError("Assessment does not reproduce recorded predecision trace")
        rows.append(
            {
                "decision_id": decision.decision_id,
                "state_snapshot_id": decision.state_snapshot_id,
                "minimum_pairwise_probability": head.config.minimum_pairwise_probability,
                "minimum_feature_support": head.config.minimum_feature_support,
                "assessment": assessment.model_dump(mode="json"),
            }
        )
    result = {
        "source_run": str(run),
        "policy_sha256": model.policy_sha256,
        "historical_reproduction_only": True,
        "policy_modified": False,
        "formal_evidence_eligible": False,
        "decisions": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "snapshots", "policy", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    result = explain(**vars(parser.parse_args()))
    for row in result["decisions"]:
        assessment = row["assessment"]
        print(
            json.dumps(
                {
                    "decision_id": row["decision_id"],
                    "pairwise_probability": assessment["pairwise_probability"],
                    "required": row["minimum_pairwise_probability"],
                    "reason_codes": assessment["reason_codes"],
                }
            )
        )


if __name__ == "__main__":
    main()
