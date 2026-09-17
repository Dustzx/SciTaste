import json

import pytest
from pydantic import ValidationError

from scitaste.evaluation.counterfactual_deliberation_confirmation import (
    CounterfactualDeliberationConfirmationProtocol,
    CounterfactualDeliberationConfirmationState,
    _confirmation_contrast,
)
from scitaste.evaluation.counterfactual_deliberation_policy import (
    CounterfactualDeliberationTarget,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualResearchAction


def _protocol_payload() -> dict[str, object]:
    studies = []
    for task_index in range(2):
        for turn in (1, 2):
            studies.append(
                {
                    "study_id": f"confirm-task-{task_index}-turn-{turn}",
                    "task_id": f"task-{task_index}",
                    "task_config": f"task-{task_index}.json",
                    "task_config_sha256": "1" * 64,
                    "prefix_turn_count": turn,
                }
            )
    return {
        "protocol_id": "confirmation-v1",
        "project_id": "test-project",
        "target_venue": "ICLR 2027",
        "frozen_implementation_commit": "1" * 40,
        "benchmark_name": "NewtonBench",
        "benchmark_repository_commit": "2" * 40,
        "benchmark_checkout": "outputs/newtonbench",
        "source_precedent_root": "outputs/precedents",
        "source_manifest_sha256": "3" * 64,
        "source_library_sha256": "4" * 64,
        "development_report": "outputs/development.json",
        "development_report_sha256": "5" * 64,
        "studies": studies,
        "forced_actions": [item.value for item in CounterfactualResearchAction],
        "selector": {
            "profile_set": "profiles.yaml",
            "profile_set_sha256": "6" * 64,
            "profile_id": "selector",
            "backend_config": "backend.yaml",
            "backend_config_sha256": "7" * 64,
            "maximum_candidate_cases": 3,
            "maximum_selected_cases": 3,
            "selection_rule": "direct-deliberated-action-v1",
        },
        "execution": {
            "limits": "limits.json",
            "limits_sha256": "8" * 64,
            "research_agent_config": "agent.yaml",
            "research_agent_config_sha256": "9" * 64,
            "terminal_judge_config": "judge.yaml",
            "terminal_judge_config_sha256": "a" * 64,
            "research_agent_policy_id": "research-agent-v1",
            "research_agent_prompt_version": "research-agent-prompt-v1",
            "terminal_judge_prompt_version": "symbolic-judge-v1",
            "research_agent_seeds": {"task-0": 10, "task-1": 11},
            "terminal_judge_seeds": {"task-0": 20, "task-1": 21},
        },
        "endpoint": {},
        "success": {
            "expected_state_count": 4,
            "expected_task_cluster_count": 2,
            "minimum_objective_observation_rate": 0.85,
            "minimum_selected_action_types": 3,
            "maximum_selected_action_share": 0.75,
            "minimum_mean_margin_over_strongest_static": 0.02,
            "require_positive_task_cluster_interval_lower_bound": True,
            "require_failure_noninferiority": True,
        },
        "resources": {
            "maximum_source_trajectories": 2,
            "maximum_branch_trajectories": 28,
            "maximum_selector_invocations": 4,
            "gpu_hours": 0,
        },
        "evidence_scope": "mechanism-confirmation-only",
    }


def test_confirmation_protocol_closes_population_and_resource_ceiling() -> None:
    protocol = CounterfactualDeliberationConfirmationProtocol.model_validate_json(
        json.dumps(_protocol_payload()), strict=True
    )

    assert len(protocol.studies) == 4
    assert set(protocol.forced_actions) == set(CounterfactualResearchAction)

    invalid = _protocol_payload()
    invalid["resources"] = {
        "maximum_source_trajectories": 2,
        "maximum_branch_trajectories": 27,
        "maximum_selector_invocations": 4,
        "gpu_hours": 0,
    }
    with pytest.raises(ValidationError, match="branch ceiling"):
        CounterfactualDeliberationConfirmationProtocol.model_validate_json(
            json.dumps(invalid), strict=True
        )


def test_confirmation_target_requires_protocol_hash() -> None:
    values = {
        "study_id": "confirm-task-0-turn-1",
        "target_case_id": "confirmation-target-0001",
        "task_cluster_id": "task-0",
        "prefix_sha256": "1" * 64,
        "result_sha256": "2" * 64,
        "excluded_same_cluster_case_ids": (),
        "eligible_cross_cluster_case_ids": ("case-a", "case-b"),
        "objective_preferred_actions": ("PILOT",),
        "objective_values": {"PILOT": 1.0, "PROBE": 0.0},
        "objective_observed": {"PILOT": True, "PROBE": True},
        "selector_input_sha256": "3" * 64,
    }

    target = CounterfactualDeliberationTarget.create(
        **values,
        development_only=False,
        confirmation_protocol_sha256="4" * 64,
    )
    assert target.development_only is False

    with pytest.raises(ValidationError, match="require a protocol hash"):
        CounterfactualDeliberationTarget.create(**values, development_only=False)


def test_confirmation_contrast_clusters_by_independent_task() -> None:
    states = []
    for task_id, selected_value in (("task-a", 0.8), ("task-b", 0.6)):
        states.append(
            CounterfactualDeliberationConfirmationState(
                study_id=f"{task_id}-turn-1",
                task_id=task_id,
                prefix_turn_count=1,
                decision_status="accepted",
                abstained=False,
                accepted_invocation_id=f"invoke-{task_id}",
                selected_action=CounterfactualResearchAction.PILOT,
                selected_value=selected_value,
                selected_objective_observed=True,
                objective_preferred_actions=(CounterfactualResearchAction.PILOT,),
                oracle_value=selected_value,
                regret=0.0,
                static_values={
                    CounterfactualResearchAction.EXPERIMENT: selected_value - 0.1,
                    CounterfactualResearchAction.PROBE: selected_value - 0.2,
                    CounterfactualResearchAction.STOP: selected_value - 0.3,
                },
                static_objective_observed={
                    CounterfactualResearchAction.EXPERIMENT: True,
                    CounterfactualResearchAction.PROBE: True,
                    CounterfactualResearchAction.STOP: True,
                },
            )
        )

    contrast = _confirmation_contrast(
        states,
        CounterfactualResearchAction.EXPERIMENT,
        0.001,
    )

    assert contrast.paired_mean_difference == pytest.approx(0.1)
    assert contrast.exhaustive_task_cluster_bootstrap_95_interval == pytest.approx(
        (0.1, 0.1)
    )
    assert contrast.practical_wins == 2
