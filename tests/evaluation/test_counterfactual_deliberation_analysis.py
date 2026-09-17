from __future__ import annotations

import math

from scitaste.evaluation.counterfactual_deliberation_analysis import (
    _bounded_utility_values,
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
