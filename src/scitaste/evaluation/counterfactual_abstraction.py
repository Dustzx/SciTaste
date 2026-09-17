"""Project objective action branches into grounded Scientific Taste source records."""

from __future__ import annotations

import hashlib
import json

from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualBranchOutcome,
)
from scitaste.evaluation.interactive_research import InteractiveResearchPrefix
from scitaste.taste.semantic_models import TasteAbstractionInput


def build_counterfactual_taste_abstraction_input(
    result: CounterfactualActionSetResult,
    prefix: InteractiveResearchPrefix,
) -> TasteAbstractionInput:
    """Expose a complete, exact decision record to the grounded abstraction node."""

    if result.project_id != prefix.project_id or result.task_id != prefix.task_id:
        raise ValueError("counterfactual abstraction result and prefix target different tasks")
    if result.prefix_sha256 != prefix.prefix_sha256:
        raise ValueError("counterfactual abstraction result and prefix differ")

    preferred = _resource_aware_preferred_outcome(result)
    outcomes = sorted(result.outcomes, key=lambda item: item.action.value)
    action_names = [item.action.value for item in outcomes]
    visible_history = [
        {
            "turn": turn.turn,
            "proposal": turn.decision.proposal.model_dump(mode="json"),
            "observation": turn.observation,
        }
        for turn in prefix.turns
    ]
    objective_table = [
        {
            "action": item.action.value,
            "objective_value": item.objective_value,
            "objective_observed": item.objective_observed,
            "status": item.status,
            "additional_experiments": item.branch_experiment_count,
            "additional_tokens": item.branch_input_tokens + item.branch_output_tokens,
        }
        for item in outcomes
    ]
    evidence_status = prefix.turns[-1].decision.proposal.evidence_status
    projection = {
        "schema_version": "1.0",
        "outcome_information_availability": "available",
        "fields": {
            "research_context": {
                "semantic_roles": ["problem_context", "source_metadata"],
                "value": (
                    "Choose the next high-level research action in hidden-law discovery "
                    f"after {prefix.turn_count} observed experiment turn(s), with "
                    f"evidence_status={evidence_status}."
                ),
            },
            "visible_decision_history": {
                "semantic_roles": ["evidence", "problem_context"],
                "value": _compact(visible_history),
            },
            "decision_evidence_state": {
                "semantic_role": "evidence",
                "value": (
                    f"evidence_status={evidence_status}; "
                    f"evidence_confidence="
                    f"{prefix.turns[-1].decision.proposal.evidence_confidence:g}; "
                    f"next_experiment_value="
                    f"{prefix.turns[-1].decision.proposal.next_experiment_value:g}; "
                    f"latest_rationale={prefix.turns[-1].decision.proposal.rationale}"
                ),
            },
            "candidate_actions": {
                "semantic_role": "alternative",
                "value": ", ".join(action_names),
            },
            "resource_aware_choice": {
                "semantic_role": "scientific_action",
                "value": preferred.action.value,
            },
            "choice_justification": {
                "semantic_roles": ["scientific_action", "justification", "evidence"],
                "value": (
                    f"{preferred.action.value} is within the frozen practical-equivalence set "
                    f"at tolerance {result.practical_equivalence_tolerance:g}; among equivalent "
                    "actions it retains an observed objective when available, then minimizes "
                    "additional experiments and tokens."
                ),
            },
            "counterfactual_outcomes": {
                "semantic_roles": ["outcome", "evidence"],
                "value": _compact(objective_table),
            },
            "transfer_limitations": {
                "semantic_role": "limitation",
                "value": (
                    "This is one prefix-matched state under a common rollout. It identifies a "
                    "local preference, not a universal action rule. Transfer requires matching "
                    "the visible hypothesis, diagnostic evidence, uncertainty, remaining budget, "
                    "and known failure conditions; task identity alone is not sufficient."
                ),
            },
            "measurement_contract": {
                "semantic_roles": ["source_metadata", "outcome"],
                "value": (
                    f"metric={result.primary_metric}; source_metric={result.source_metric}; "
                    f"transform={result.metric_transform}; direction={result.metric_direction}; "
                    f"failure_value={result.failure_value:g}; result_sha256={result.result_sha256}"
                ),
            },
        },
    }
    source_projection = json.dumps(
        projection,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    suffix = result.result_sha256[:20]
    return TasteAbstractionInput(
        source_id=f"counterfactual-source-{suffix}",
        candidate_id=f"counterfactual-candidate-{suffix}",
        case_id=f"counterfactual-taste-{suffix}",
        stage="interactive-experiment",
        decision_role="next-research-action",
        source_projection=source_projection,
        source_projection_sha256=hashlib.sha256(source_projection.encode()).hexdigest(),
        domain_tags=("hidden-law-discovery", "scientific-experimentation"),
        outcome_information_availability="available",
        relation_label_hidden=True,
        held_out_task_content_excluded=True,
        source_projection_is_only_source_content=True,
    )


def _resource_aware_preferred_outcome(
    result: CounterfactualActionSetResult,
) -> CounterfactualBranchOutcome:
    preferred = [item for item in result.outcomes if item.action in result.preferred_actions]
    if not preferred:
        raise ValueError("counterfactual result has no preferred outcome")
    return min(
        preferred,
        key=lambda item: (
            not item.objective_observed,
            item.branch_experiment_count,
            item.branch_input_tokens + item.branch_output_tokens,
            item.action.value,
        ),
    )


def _compact(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = ["build_counterfactual_taste_abstraction_input"]
