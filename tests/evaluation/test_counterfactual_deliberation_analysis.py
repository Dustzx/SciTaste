from __future__ import annotations

import math

from scitaste.evaluation.counterfactual_deliberation_analysis import (
    _bounded_utility_values,
    _is_diagnostic_action_contrast,
)
from scitaste.evaluation.counterfactual_deliberation_policy import (
    CounterfactualDeliberationTarget,
)
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualBranchOutcome,
    CounterfactualResearchAction,
)


def test_raw_lower_rmsle_is_converted_to_bounded_higher_is_better_utility() -> None:
    outcomes = (
        _outcome(CounterfactualResearchAction.EXPERIMENT, value=0.0, observed=True),
        _outcome(CounterfactualResearchAction.PROBE, value=1.0, observed=True),
        _outcome(CounterfactualResearchAction.STOP, value=10.0, observed=False),
    )
    target = CounterfactualDeliberationTarget.model_construct(
        objective_values={item.action.value: item.objective_value for item in outcomes},
        objective_observed={item.action.value: item.objective_observed for item in outcomes},
    )
    result = CounterfactualActionSetResult.model_construct(
        outcomes=outcomes,
        primary_metric="rmsle",
        metric_transform="identity",
        metric_direction="lower",
    )

    utilities = _bounded_utility_values(target, result)

    assert utilities == {
        "EXPERIMENT": 1.0,
        "PROBE": math.exp(-1.0),
        "STOP": 0.0,
    }


def test_action_contrast_rejects_broad_ties_and_missing_branch_outcomes() -> None:
    values = {
        "ANALYZE": 1.0,
        "EXPERIMENT": 1.0,
        "PILOT": 1.0,
        "PIVOT": 1.0,
        "PROBE": 1.0,
        "REFINE": 1.0,
        "STOP": 0.0,
    }
    broad_tie = CounterfactualDeliberationTarget.model_construct(
        objective_values=values,
        objective_observed={action: True for action in values},
        objective_preferred_actions=tuple(action for action in values if action != "STOP"),
    )
    missing = CounterfactualDeliberationTarget.model_construct(
        objective_values=values,
        objective_observed={
            action: action not in {"REFINE", "STOP"} for action in values
        },
        objective_preferred_actions=("ANALYZE",),
    )

    assert not _is_diagnostic_action_contrast(broad_tie, values)
    assert not _is_diagnostic_action_contrast(missing, values)


def test_action_contrast_accepts_selective_observed_utility_difference() -> None:
    values = {
        "ANALYZE": 0.9,
        "EXPERIMENT": 0.7,
        "PILOT": 0.5,
        "PIVOT": 0.4,
        "PROBE": 0.3,
        "REFINE": 0.2,
        "STOP": 0.1,
    }
    target = CounterfactualDeliberationTarget.model_construct(
        objective_values=values,
        objective_observed={action: action != "STOP" for action in values},
        objective_preferred_actions=("ANALYZE",),
    )

    assert _is_diagnostic_action_contrast(target, values)


def _outcome(
    action: CounterfactualResearchAction,
    *,
    value: float,
    observed: bool,
) -> CounterfactualBranchOutcome:
    return CounterfactualBranchOutcome(
        action=action,
        intervention_sha256="0" * 64,
        receipt_sha256="1" * 64,
        status="completed" if observed else "agent_failure",
        objective_value=value,
        objective_observed=observed,
    )
