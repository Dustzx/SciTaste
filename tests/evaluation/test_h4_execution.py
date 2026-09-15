import math
from pathlib import Path

import pytest

from scitaste.evaluation.campaign_execution import (
    EvaluationCampaignLaunchConfig,
    EvaluationCommandLauncher,
    EvaluationFormalPreparationBinding,
)
from scitaste.evaluation.h4_execution import (
    BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256,
    BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256,
    BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256,
    BENCHMARK_H4_ACTION_ONTOLOGY_SHA256,
    BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256,
    BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256,
    BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256,
    H4ArmRunRequest,
    H4BenchmarkResearchActionProvider,
    H4ExecutionArm,
    H4ExecutionProfile,
    H4TaskExecutionProfile,
    build_h4_benchmark_action_menu,
    load_h4_execution_profile,
    save_h4_execution_profile,
)
from scitaste.evaluation.h4_state_probe import (
    H4FrozenStateProbeContract,
    H4StateProbeReport,
    canonical_h4_state_probes,
    inspect_h4_state_probe_manipulation,
)
from scitaste.evaluation.native_benchmark_adapter import (
    NativeBenchmarkObjectiveMeasurement,
    pair_h4_objective_measurements,
)
from scitaste.evaluation.task_research_loop import (
    BenchmarkResearchIteration,
    BenchmarkResearchLoopResult,
)
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import content_sha256
from scitaste.state.research_state import ResearchStage, ResearchState, ResourceBudget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.episode_learning import (
    LifecycleTasteFeaturePosterior,
    LifecycleTastePolicyConfig,
    LifecycleTastePolicyModel,
    LifecycleTastePolicyUpdateMode,
)
from scitaste.taste.intervention import (
    TasteInterventionCondition,
    lifecycle_policy_training_corpus_sha256,
)


def _idea_binding() -> ProjectIdeaRevisionBinding:
    return ProjectIdeaRevisionBinding.create(
        project_id="scitaste-self-development",
        observed_project_revision=4,
        observed_project_snapshot_sha256="1" * 64,
        revision_id="idea-h4-v1",
        status="accepted",
        record_locator="runs/run-h4/idea/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=True,
        paper_claim_authority=True,
    )


def _policy() -> LifecycleTastePolicyModel:
    source_group = "f1000-work-" + "c" * 64
    return LifecycleTastePolicyModel.create(
        policy_id="h4-policy-v1",
        config=LifecycleTastePolicyConfig(
            policy_id="h4-policy-v1",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
        ),
        source_episode_ids=("episode-01",),
        source_episode_sha256=("4" * 64,),
        source_group_keys=(f"external:corpus:{source_group}",),
        source_group_count=1,
        source_group_ids=(source_group,),
        training_episode_ids=("episode-01",),
        training_episode_sha256=("4" * 64,),
        training_episode_count=1,
        training_source_group_keys=(f"external:corpus:{source_group}",),
        training_source_group_count=1,
        effective_training_weight=1.0,
        pairwise_comparison_count=0,
        source_review_evidence_kinds=("ai",),
        source_ai_reviewed_episode_count=1,
        source_legacy_unverified_episode_count=0,
        ai_review_contract_sha256s=("5" * 64,),
        human_validity_claim_allowed=False,
        trained_stages=("EVIDENCE",),
        trained_domain_tags=("mlrc",),
        trained_venue_tags=("iclr 2027",),
        feature_posteriors=(),
    )


def _posterior(
    feature: str,
    feature_kind: str,
    *,
    wins: float,
    losses: float,
) -> LifecycleTasteFeaturePosterior:
    alpha = 1.0 + wins
    beta = 1.0 + losses
    mean = alpha / (alpha + beta)
    probability_variance = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1.0))
    return LifecycleTasteFeaturePosterior(
        feature=feature,
        feature_kind=feature_kind,
        wins=wins,
        losses=losses,
        alpha=alpha,
        beta=beta,
        support=wins + losses,
        posterior_mean=mean,
        log_odds=math.log(mean / (1.0 - mean)),
        log_odds_variance=(probability_variance / (mean**2 * (1.0 - mean) ** 2)),
    )


def _feedback_adaptive_policy() -> LifecycleTastePolicyModel:
    base = _policy()
    actions = build_h4_benchmark_action_menu(iteration=1)
    posteriors = [
        _posterior(
            f"stage::evidence::action::{action.type.value.casefold()}",
            "stage-action",
            wins=50.0,
            losses=50.0,
        )
        for action in actions
    ]
    posteriors.extend(
        (
            _posterior(
                "decision-state::failure-count::one::action::probe",
                "decision-state-action",
                wins=100.0,
                losses=0.0,
            ),
            _posterior(
                "decision-state::score-trend::flat::action::refine",
                "decision-state-action",
                wins=90.0,
                losses=0.0,
            ),
            _posterior(
                "decision-state::score-trend::improving::action::experiment",
                "decision-state-action",
                wins=80.0,
                losses=0.0,
            ),
        )
    )
    payload = base.model_dump(
        mode="python",
        exclude={"schema_version", "feature_posteriors", "policy_sha256"},
    )
    payload["config"] = base.config
    source_groups = tuple(f"f1000-work-{index:064x}" for index in range(100))
    source_episode_ids = tuple(f"episode-{index:03d}" for index in range(100))
    source_episode_sha256 = tuple(f"{index + 1:064x}" for index in range(100))
    payload.update(
        source_episode_ids=source_episode_ids,
        source_episode_sha256=source_episode_sha256,
        source_group_keys=tuple(f"external:corpus:{group}" for group in source_groups),
        source_group_count=100,
        source_group_ids=source_groups,
        training_episode_ids=source_episode_ids,
        training_episode_sha256=source_episode_sha256,
        training_episode_count=100,
        training_source_group_keys=tuple(f"external:corpus:{group}" for group in source_groups),
        training_source_group_count=100,
        effective_training_weight=100.0,
        source_ai_reviewed_episode_count=100,
        trained_domain_tags=("mlrc-bench",),
    )
    return LifecycleTastePolicyModel.create(
        schema_version="1.5",
        **payload,
        feature_posteriors=tuple(sorted(posteriors, key=lambda item: item.feature)),
    )


def _probe_contract(policy: LifecycleTastePolicyModel) -> H4FrozenStateProbeContract:
    controller = TasteController(
        seed=7,
        mode=TasteMode.INTRINSIC,
        critics_enabled=False,
        lifecycle_policy=policy,
        lifecycle_policy_weight=0.0,
    )
    return H4FrozenStateProbeContract.create(
        contract_id="h4-policy-state-probe",
        project_id="scitaste-self-development",
        evaluation_id="h4-formal-v1",
        evaluation_bundle_sha256="1" * 64,
        plan_sha256="2" * 64,
        lifecycle_policy_sha256=policy.policy_sha256,
        policy_training_corpus_sha256=lifecycle_policy_training_corpus_sha256(policy),
        idea_scientific_contract_sha256=idea_scientific_contract_sha256(
            policy.config.idea_revision
        ),
        controller_backbone_sha256=controller.intervention_backbone_sha256,
        maximum_failed_experiments=2,
        seed=7,
        resource_budget=ResourceBudget(max_experiments=5),
        research_direction="Improve a frozen benchmark task.",
        target_domain=("mlrc-bench" if policy.schema_version == "1.5" else "mlrc"),
        target_venue="ICLR 2027",
    )


def _profile(
    *,
    policy: LifecycleTastePolicyModel | None = None,
    controller_backbone_sha256: str = "a" * 64,
) -> H4ExecutionProfile:
    policy_sha256 = "6" * 64 if policy is None else policy.policy_sha256
    training_sha256 = (
        "7" * 64 if policy is None else lifecycle_policy_training_corpus_sha256(policy)
    )
    idea_sha256 = (
        "a" * 64 if policy is None else idea_scientific_contract_sha256(policy.config.idea_revision)
    )
    precedent_group = "f1000-work-" + "d" * 64
    task = H4TaskExecutionProfile(
        benchmark_id="mlrc-bench",
        task_id="mlrc-task-01",
        task_file_sha256="1" * 64,
        task_spec_fingerprint="2" * 64,
        canonical_heldout_source_group_id="benchmark-task-" + "3" * 64,
        precedent_source_group_ids=(precedent_group,),
        protocol_authored_guidance_sha256="d" * 64,
        development_execution_profile_sha256="4" * 64,
        heldout_execution_profile_sha256="5" * 64,
        development_executor_sha256="6" * 64,
        heldout_executor_sha256="7" * 64,
        scorer_sha256="8" * 64,
        dataset_split_sha256="9" * 64,
        metric_config_sha256="a" * 64,
        baseline_score_contract_sha256="b" * 64,
        primary_metric="accuracy",
        metric_direction="higher",
        baseline_heldout_score=0.5,
        failure_directed_progress_penalty=-1.0,
    )
    policy_group = "f1000-work-" + "c" * 64
    heldout_group = task.canonical_heldout_source_group_id
    return H4ExecutionProfile.create(
        profile_id="h4-native-v1",
        project_id="scitaste-self-development",
        evaluation_id="h4-formal-v1",
        evaluation_bundle_sha256="e" * 64,
        plan_sha256="f" * 64,
        repository_commit="0" * 40,
        repository_tree_sha256="1" * 64,
        adapter_implementation_sha256=BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256,
        controller_implementation_sha256=(BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256),
        controller_backbone_sha256=controller_backbone_sha256,
        menu_builder_implementation_sha256=BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256,
        action_to_patch_adapter_sha256=BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256,
        lifecycle_policy_sha256=policy_sha256,
        policy_training_corpus_sha256=training_sha256,
        policy_reproduction_report_sha256="4" * 64,
        state_probe_contract_sha256="5" * 64,
        state_probe_report_sha256="6" * 64,
        source_identity_registry_sha256="8" * 64,
        source_partition_sha256=content_sha256(
            {
                "policy": (policy_group,),
                "guidance": (precedent_group,),
                "heldout": (heldout_group,),
            }
        ),
        idea_scientific_contract_sha256=idea_sha256,
        canonical_source_group_ids=(heldout_group, policy_group, precedent_group),
        policy_source_group_ids=(policy_group,),
        precedent_source_group_ids=(precedent_group,),
        heldout_source_group_ids=(heldout_group,),
        action_ontology_sha256=BENCHMARK_H4_ACTION_ONTOLOGY_SHA256,
        action_menu_template_sha256=BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256,
        action_eligibility_rule_sha256=BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256,
        arms=(
            H4ExecutionArm(
                condition=TasteInterventionCondition.LEARNED_POLICY_ON,
                lifecycle_policy_weight=1.0,
            ),
            H4ExecutionArm(
                condition=TasteInterventionCondition.LEARNED_POLICY_OFF,
                lifecycle_policy_weight=0.0,
            ),
        ),
        decision_provider="scitaste-native",
        decision_model="deterministic-utility-controller",
        patch_model_profile_sha256="e" * 64,
        patch_node_policy_sha256="f" * 64,
        patch_prompt_sha256="0" * 64,
        decoding_config_sha256="1" * 64,
        seed_schedule_sha256="2" * 64,
        tool_policy_sha256="3" * 64,
        repair_policy_sha256="4" * 64,
        resource_budget_sha256="5" * 64,
        maximum_patch_iterations=4,
        maximum_failed_experiments=2,
        stopping_rule_sha256="6" * 64,
        task_profiles=(task,),
        objective_outcome_contract_sha256="7" * 64,
    )


def _arm_request(
    profile: H4ExecutionProfile,
    *,
    condition: TasteInterventionCondition = TasteInterventionCondition.LEARNED_POLICY_ON,
) -> H4ArmRunRequest:
    task = profile.task_profiles[0]
    return H4ArmRunRequest.create_from_profile(
        profile,
        request_id=f"h4-arm-{condition.value}-task-01-seed-07",
        campaign_manifest_sha256="d" * 64,
        condition=condition,
        cell_id=f"cell-{condition.value}-01",
        cell_binding_sha256="a" * 64,
        condition_matrix_fingerprint="b" * 64,
        condition_guidance_sha256="c" * 64,
        task_id=task.task_id,
        seed=7,
        repetition=1,
        plan_position=(0 if condition is TasteInterventionCondition.LEARNED_POLICY_ON else 1),
        task_file_sha256=task.task_file_sha256,
        task_spec_fingerprint=task.task_spec_fingerprint,
        resource_budget_sha256=profile.resource_budget_sha256,
        prepared_workspace_receipt_sha256="a" * 64,
        initial_workspace_tree_sha256="b" * 64,
        initial_editable_surface_sha256="c" * 64,
        protected_surface_sha256="d" * 64,
        development_execution_profile_sha256=(task.development_execution_profile_sha256),
        development_prepared_record_sha256="e" * 64,
        development_resource_verification_sha256="f" * 64,
        heldout_execution_profile_sha256=task.heldout_execution_profile_sha256,
        heldout_prepared_record_sha256="0" * 64,
        heldout_resource_verification_sha256="1" * 64,
        patch_model_profile_sha256=profile.patch_model_profile_sha256,
        patch_node_policy_sha256=profile.patch_node_policy_sha256,
        patch_prompt_sha256=profile.patch_prompt_sha256,
        decoding_config_sha256=profile.decoding_config_sha256,
        patch_visible_guidance_sha256="f" * 64,
    )


def test_h4_launch_config_requires_preparation_without_changing_legacy_hash() -> None:
    launcher = EvaluationCommandLauncher(
        command=("scitaste-native-adapter",),
        timeout_seconds=60,
    )
    legacy_payload = {
        "schema_version": "1.0",
        "launchers": {"legacy-system": launcher.model_dump(mode="json")},
    }
    legacy = EvaluationCampaignLaunchConfig(
        launchers={"legacy-system": launcher},
    )
    assert legacy.config_sha256 == content_sha256(legacy_payload)
    with pytest.raises(ValueError, match="requires formal preparation"):
        EvaluationCampaignLaunchConfig(
            schema_version="1.1",
            launchers={"full-scitaste-learned-policy": launcher},
        )
    formal = EvaluationCampaignLaunchConfig(
        schema_version="1.1",
        launchers={
            "full-scitaste-learned-policy": launcher,
            "native-base-without-learned-taste": launcher,
        },
        formal_preparation=EvaluationFormalPreparationBinding(
            locator="outputs/projects/project/evaluation-preparations/PREPARATION.json",
            sha256="1" * 64,
            preparation_sha256="2" * 64,
        ),
    )
    assert formal.formal_preparation is not None


def test_h4_profile_is_exclusive_and_content_bound(tmp_path: Path) -> None:
    profile = _profile()
    path = save_h4_execution_profile(profile, tmp_path / "H4_PROFILE.json")

    assert load_h4_execution_profile(path) == profile
    assert profile.reviewer_kind == "ai"
    assert profile.not_human_review is True
    with pytest.raises(FileExistsError):
        save_h4_execution_profile(profile, path)


def test_h4_provider_gates_fixed_menu_without_policy_trace_leakage() -> None:
    policy = _policy()
    controller = TasteController(
        seed=7,
        mode=TasteMode.INTRINSIC,
        critics_enabled=False,
        lifecycle_policy=policy,
        lifecycle_policy_weight=1.0,
    )
    profile = _profile(
        policy=policy,
        controller_backbone_sha256=controller.intervention_backbone_sha256,
    )
    request = _arm_request(profile)
    provider = H4BenchmarkResearchActionProvider(
        profile,
        request,
        controller,
        current_idea_revision=_idea_binding(),
    )
    state = ResearchState(
        revision=1,
        project_id="scitaste-self-development",
        research_direction="Improve one frozen benchmark objective.",
        target_domain="mlrc",
        target_venue="ICLR 2027",
        resource_budget=ResourceBudget(max_experiments=4),
        current_stage=ResearchStage.EVIDENCE,
    )

    result = provider.decide(
        state,
        build_h4_benchmark_action_menu(iteration=1),
        loop_id="cell-h4-research",
        iteration=1,
    )

    assert result.contract.condition is TasteInterventionCondition.LEARNED_POLICY_ON
    assert result.decision.taste_intervention is not None
    assert result.policy_scores_visible_downstream is False
    assert result.downstream_action_id == result.decision.selected_action.action_id


def test_h4_arm_request_observes_profile_before_execution() -> None:
    profile = _profile()
    task = profile.task_profiles[0]
    request = H4ArmRunRequest.create_from_profile(
        profile,
        request_id="h4-arm-on-task-01-seed-07",
        campaign_manifest_sha256="d" * 64,
        condition=TasteInterventionCondition.LEARNED_POLICY_ON,
        cell_id="cell-h4-on-01",
        cell_binding_sha256="a" * 64,
        condition_matrix_fingerprint="b" * 64,
        condition_guidance_sha256="c" * 64,
        task_id=task.task_id,
        seed=7,
        repetition=1,
        plan_position=0,
        task_file_sha256=task.task_file_sha256,
        task_spec_fingerprint=task.task_spec_fingerprint,
        resource_budget_sha256=profile.resource_budget_sha256,
        prepared_workspace_receipt_sha256="a" * 64,
        initial_workspace_tree_sha256="b" * 64,
        initial_editable_surface_sha256="c" * 64,
        protected_surface_sha256="d" * 64,
        development_execution_profile_sha256=(task.development_execution_profile_sha256),
        development_prepared_record_sha256="e" * 64,
        development_resource_verification_sha256="f" * 64,
        heldout_execution_profile_sha256=task.heldout_execution_profile_sha256,
        heldout_prepared_record_sha256="0" * 64,
        heldout_resource_verification_sha256="1" * 64,
        patch_model_profile_sha256=profile.patch_model_profile_sha256,
        patch_node_policy_sha256=profile.patch_node_policy_sha256,
        patch_prompt_sha256=profile.patch_prompt_sha256,
        decoding_config_sha256=profile.decoding_config_sha256,
        patch_visible_guidance_sha256="f" * 64,
    )

    assert request.lifecycle_policy_weight == 1.0
    assert request.model_calls_before_request == 0
    assert request.benchmark_executions_before_request == 0
    assert request.editable_mutations_before_request == 0


def test_h4_arm_request_rejects_task_profile_drift() -> None:
    profile = _profile()
    task = profile.task_profiles[0]

    with pytest.raises(ValueError, match="task file"):
        H4ArmRunRequest.create_from_profile(
            profile,
            request_id="h4-arm-on-task-01-seed-07",
            campaign_manifest_sha256="d" * 64,
            condition=TasteInterventionCondition.LEARNED_POLICY_ON,
            cell_id="cell-h4-on-01",
            cell_binding_sha256="a" * 64,
            condition_matrix_fingerprint="b" * 64,
            condition_guidance_sha256="c" * 64,
            task_id=task.task_id,
            seed=7,
            repetition=1,
            plan_position=0,
            task_file_sha256="f" * 64,
            task_spec_fingerprint=task.task_spec_fingerprint,
            resource_budget_sha256=profile.resource_budget_sha256,
            prepared_workspace_receipt_sha256="a" * 64,
            initial_workspace_tree_sha256="b" * 64,
            initial_editable_surface_sha256="c" * 64,
            protected_surface_sha256="d" * 64,
            development_execution_profile_sha256=(task.development_execution_profile_sha256),
            development_prepared_record_sha256="e" * 64,
            development_resource_verification_sha256="f" * 64,
            heldout_execution_profile_sha256=task.heldout_execution_profile_sha256,
            heldout_prepared_record_sha256="0" * 64,
            heldout_resource_verification_sha256="1" * 64,
            patch_model_profile_sha256=profile.patch_model_profile_sha256,
            patch_node_policy_sha256=profile.patch_node_policy_sha256,
            patch_prompt_sha256=profile.patch_prompt_sha256,
            decoding_config_sha256=profile.decoding_config_sha256,
            patch_visible_guidance_sha256="f" * 64,
        )


def test_h4_result_closes_iteration_receipt_chain() -> None:
    arm_sha256 = "a" * 64
    baseline = BenchmarkResearchIteration.create(
        iteration=0,
        disposition="baseline",
        h4_arm_run_request_sha256=arm_sha256,
        editable_surface_after_sha256="b" * 64,
        development_receipt_sha256="c" * 64,
        score=0.1,
        best_score_after=0.1,
    )
    stopped = BenchmarkResearchIteration.create(
        iteration=1,
        disposition="stopped",
        research_state_snapshot_id="state-" + "d" * 64,
        research_action_menu_sha256="e" * 64,
        research_action_decision_sha256="f" * 64,
        taste_intervention_contract_sha256="0" * 64,
        selected_research_action_sha256="1" * 64,
        h4_arm_run_request_sha256=arm_sha256,
        previous_iteration_receipt_sha256=baseline.iteration_receipt_sha256,
        editable_surface_after_sha256="b" * 64,
        best_score_after=0.1,
    )

    result = BenchmarkResearchLoopResult.create(
        schema_version="1.1",
        loop_id="h4-chain",
        config_sha256="2" * 64,
        task_spec_fingerprint="3" * 64,
        cell_binding_sha256="4" * 64,
        condition_guidance_sha256="5" * 64,
        h4_arm_run_request_sha256=arm_sha256,
        status="stopped",
        stop_reason="taste-controller-stop",
        baseline_score=0.1,
        best_development_score=0.1,
        best_iteration=0,
        best_editable_surface_sha256="b" * 64,
        development_experiment_count=1,
        unverified_development_attempt_count=0,
        patch_proposal_count=0,
        adopted_patch_count=0,
        reverted_patch_count=0,
        failed_experiment_count=0,
        input_tokens=0,
        output_tokens=0,
        model_cost_usd=0,
        gpu_hours=0,
        iterations=(baseline, stopped),
    )

    assert result.iterations[-1].previous_iteration_receipt_sha256 == (
        result.iterations[0].iteration_receipt_sha256
    )
    assert BenchmarkResearchLoopResult.model_validate(result.model_dump(mode="json")) == result


def test_h4_failure_measurement_is_itt_bounded_and_linked() -> None:
    measurement = NativeBenchmarkObjectiveMeasurement.create(
        schema_version="1.1",
        cell_id="h4-cell",
        task_id="h4-task",
        condition_id=TasteInterventionCondition.LEARNED_POLICY_ON.value,
        outcome_status="itt_bounded_failure",
        frozen_candidate_sha256=None,
        heldout_receipt_sha256=None,
        metric_name="accuracy",
        metric_direction="higher",
        heldout_score=None,
        baseline_heldout_score=0.5,
        directed_progress=-0.5,
        h4_execution_profile_sha256="1" * 64,
        h4_arm_run_request_sha256="2" * 64,
        loop_result_sha256="3" * 64,
        terminal_evidence_sha256="3" * 64,
        lifecycle_policy_weight=1.0,
    )

    assert measurement.outcome_status == "itt_bounded_failure"
    assert measurement.directed_progress == -0.5
    assert (
        NativeBenchmarkObjectiveMeasurement.model_validate(measurement.model_dump(mode="json"))
        == measurement
    )


def test_h4_pair_keeps_bounded_failure_in_within_pair_effect() -> None:
    profile = _profile()
    on_request = _arm_request(profile)
    off_request = _arm_request(
        profile,
        condition=TasteInterventionCondition.LEARNED_POLICY_OFF,
    )

    def measurement(
        request: H4ArmRunRequest,
        directed_progress: float,
    ) -> NativeBenchmarkObjectiveMeasurement:
        return NativeBenchmarkObjectiveMeasurement.create(
            schema_version="1.1",
            cell_id=request.cell_id,
            task_id=request.task_id,
            condition_id=request.condition.value,
            outcome_status="itt_bounded_failure",
            frozen_candidate_sha256=None,
            heldout_receipt_sha256=None,
            metric_name="accuracy",
            metric_direction="higher",
            heldout_score=None,
            baseline_heldout_score=0.5,
            directed_progress=directed_progress,
            h4_execution_profile_sha256=request.profile_sha256,
            h4_arm_run_request_sha256=request.request_sha256,
            loop_result_sha256="3" * 64,
            terminal_evidence_sha256="3" * 64,
            lifecycle_policy_weight=request.lifecycle_policy_weight,
        )

    result = pair_h4_objective_measurements(
        on_request,
        measurement(on_request, -0.5),
        off_request,
        measurement(off_request, -0.25),
        pair_id="h4-task-01-seed-07",
    )

    assert result.within_pair_effect == -0.25
    assert result.execution_order == (
        TasteInterventionCondition.LEARNED_POLICY_ON,
        TasteInterventionCondition.LEARNED_POLICY_OFF,
    )
    assert result.not_human_review is True


def test_h4_pair_rejects_workspace_receipt_drift() -> None:
    profile = _profile()
    on_request = _arm_request(profile)
    off_request = _arm_request(
        profile,
        condition=TasteInterventionCondition.LEARNED_POLICY_OFF,
    )
    off_payload = off_request.model_dump(
        mode="json",
        exclude={"request_sha256", "common_arm_factors_sha256"},
    )
    off_payload["prepared_workspace_receipt_sha256"] = "e" * 64
    off_payload["common_arm_factors_sha256"] = content_sha256(
        H4ArmRunRequest.model_construct(
            request_sha256="0" * 64,
            common_arm_factors_sha256="0" * 64,
            **off_payload,
        ).common_arm_factors_payload()
    )
    drifted = H4ArmRunRequest(
        **off_payload,
        request_sha256=content_sha256(off_payload),
    )

    def measurement(request: H4ArmRunRequest) -> NativeBenchmarkObjectiveMeasurement:
        return NativeBenchmarkObjectiveMeasurement.create(
            schema_version="1.1",
            cell_id=request.cell_id,
            task_id=request.task_id,
            condition_id=request.condition.value,
            outcome_status="itt_bounded_failure",
            frozen_candidate_sha256=None,
            heldout_receipt_sha256=None,
            metric_name="accuracy",
            metric_direction="higher",
            heldout_score=None,
            baseline_heldout_score=0.5,
            directed_progress=-0.5,
            h4_execution_profile_sha256=request.profile_sha256,
            h4_arm_run_request_sha256=request.request_sha256,
            loop_result_sha256="3" * 64,
            terminal_evidence_sha256="3" * 64,
            lifecycle_policy_weight=request.lifecycle_policy_weight,
        )

    with pytest.raises(ValueError, match="outside the policy intervention"):
        pair_h4_objective_measurements(
            on_request,
            measurement(on_request),
            drifted,
            measurement(drifted),
            pair_id="h4-task-01-seed-07",
        )


def test_h4_state_probes_use_golden_contexts_and_falsify_static_policy() -> None:
    probes = canonical_h4_state_probes()
    assert [item.expected_context.model_dump(mode="json") for item in probes] == [
        {
            "remaining_experiments": "four-plus",
            "failure_count": "zero",
            "no_improvement_streak": "zero",
            "score_trend": "unknown",
            "best_vs_baseline": "equal",
        },
        {
            "remaining_experiments": "two-to-three",
            "failure_count": "one",
            "no_improvement_streak": "one",
            "score_trend": "unknown",
            "best_vs_baseline": "equal",
        },
        {
            "remaining_experiments": "two-to-three",
            "failure_count": "zero",
            "no_improvement_streak": "one",
            "score_trend": "flat",
            "best_vs_baseline": "equal",
        },
        {
            "remaining_experiments": "two-to-three",
            "failure_count": "zero",
            "no_improvement_streak": "zero",
            "score_trend": "improving",
            "best_vs_baseline": "above",
        },
        {
            "remaining_experiments": "one",
            "failure_count": "zero",
            "no_improvement_streak": "two-plus",
            "score_trend": "flat",
            "best_vs_baseline": "equal",
        },
    ]

    policy = _policy()
    contract = _probe_contract(policy)
    report = inspect_h4_state_probe_manipulation(
        contract,
        policy,
        current_idea_revision=policy.config.idea_revision,
    )

    assert report.feedback_sensitive is False
    assert report.passed is False
    forged_payload = report.model_dump(mode="json", exclude={"report_sha256"})
    forged_payload.update(
        treatment_active=True,
        feedback_sensitive=True,
        passed=True,
    )
    forged_payload["report_sha256"] = content_sha256(forged_payload)
    with pytest.raises(ValueError, match="treatment disposition"):
        H4StateProbeReport.model_validate(forged_payload)


def test_h4_state_probe_accepts_behaviorally_active_feedback_policy() -> None:
    policy = _feedback_adaptive_policy()
    report = inspect_h4_state_probe_manipulation(
        _probe_contract(policy),
        policy,
        current_idea_revision=policy.config.idea_revision,
    )

    assert policy.h4_adaptive_policy_eligible is True
    assert report.treatment_active is True
    assert report.feedback_sensitive is True
    assert report.passed is True
