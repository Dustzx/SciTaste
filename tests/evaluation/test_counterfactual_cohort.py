from __future__ import annotations

from scitaste.evaluation.counterfactual_cohort import (
    CounterfactualDevelopmentCohortProtocol,
    CounterfactualTrajectoryPhase,
    summarize_counterfactual_development_cohort,
)
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualBranchOutcome,
    CounterfactualResearchAction,
)
from scitaste.project.models import content_sha256


def _result(study_id: str, prefix: str, preferred: CounterfactualResearchAction, spread: float):
    actions = (CounterfactualResearchAction.PROBE, CounterfactualResearchAction.STOP)
    outcomes = tuple(
        CounterfactualBranchOutcome(
            action=action,
            intervention_sha256=content_sha256([study_id, action.value]),
            receipt_sha256=content_sha256([study_id, action.value, "receipt"]),
            status="completed",
            objective_value=0.0 if action is preferred else spread,
            objective_observed=True,
        )
        for action in actions
    )
    payload = {
        "study_id": study_id,
        "project_id": "counterfactual-project",
        "task_id": f"task-{study_id}",
        "environment_sha256": content_sha256([study_id, "environment"]),
        "prefix_sha256": prefix,
        "primary_metric": "rmsle",
        "metric_direction": "lower",
        "failure_value": 10.0,
        "practical_equivalence_tolerance": 0.001,
        "outcomes": outcomes,
        "preferred_actions": (preferred,),
        "objective_spread": spread,
    }
    unsigned = CounterfactualActionSetResult.model_construct(
        schema_version="1.0", result_sha256="0" * 64, **payload
    )
    return CounterfactualActionSetResult(
        schema_version="1.0",
        **payload,
        result_sha256=content_sha256(
            unsigned.model_dump(mode="json", exclude={"result_sha256"})
        ),
    )


def test_development_cohort_detects_state_varying_action_value_without_admission() -> None:
    report = summarize_counterfactual_development_cohort(
        cohort_id="development-cohort",
        project_id="counterfactual-project",
        protocol=CounterfactualDevelopmentCohortProtocol(
            protocol_id="development-protocol",
            minimum_state_count=2,
            minimum_domain_count=2,
            minimum_phase_count=2,
            minimum_objective_observation_rate=1.0,
            minimum_choice_sensitive_state_count=2,
            require_complete_action_space=False,
        ),
        results=(
            _result("early", "1" * 64, CounterfactualResearchAction.PROBE, 1.0),
            _result("late", "2" * 64, CounterfactualResearchAction.STOP, 2.0),
        ),
        state_ids=("early-state", "late-state"),
        domain_ids=("gravity", "decay"),
        phases=(CounterfactualTrajectoryPhase.EARLY, CounterfactualTrajectoryPhase.LATE),
    )

    assert report.development_requirements_met
    assert report.state_selectivity_observed
    assert report.scientific_choice_sensitive_state_count == 2
    assert report.reliability_only_sensitive_state_count == 0
    assert report.objective_observation_rate == 1.0
    assert not report.headline_eligible
