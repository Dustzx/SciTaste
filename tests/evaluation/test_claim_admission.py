from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation import (
    AnalysisContract,
    ApiModelResource,
    AutomatedJudgeRole,
    ClaimAdmissionContract,
    ComparisonRegime,
    ConfirmatoryContrastRole,
    ConfirmatoryContrastSpec,
    ConfirmatoryEstimandKind,
    ContrastInferenceRole,
    EvaluationBlindReview,
    EvaluationCellResult,
    EvaluationCellUsage,
    EvaluationPrimaryComparison,
    EvaluationResultArtifact,
    EvaluationResultSet,
    ExecutionLane,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    GpuModelResource,
    HumanReviewResource,
    IntegrityContract,
    ObjectiveCellMeasurement,
    ObjectiveDirection,
    ObjectiveMeasurementSet,
    ObjectiveOutcomeContract,
    ObjectiveTaskScoreContract,
    PrelaunchApproval,
    PrelaunchSystem,
    PrelaunchTask,
    ProviderPricing,
    ReadinessStatus,
    RetentionContract,
    ScientificEndpointKind,
    ScientificLaneRole,
    SystemApiModelResource,
    SystemRole,
    TaskSignalKind,
    bind_objective_measurement_set,
    claim_analysis_input_sha256,
    compile_evaluation_cell_plan,
    complete_objective_result_set,
    inspect_evaluation_results,
    load_objective_outcome_contract,
    materialize_objective_analysis,
    objective_cell_population_sha256,
    save_objective_measurement_set,
    save_objective_outcome_contract,
)
from scitaste.project.models import content_sha256

SHA = "a" * 64


def _model(provider: str = "provider") -> ApiModelResource:
    return ApiModelResource(
        provider_id=provider,
        endpoint=f"https://{provider}.example.test/v1",
        interface="openai-chat-completions",
        model_id=f"{provider}-model",
        model_revision=f"{provider}-model-2026-09-12",
        rolling_alias=False,
        identity_source_url=f"https://{provider}.example.test/model",
        identity_status=ReadinessStatus.VERIFIED,
        api_key_env=f"{provider.upper().replace('-', '_')}_API_KEY",
        max_input_tokens_per_call=10_000,
        max_output_tokens_per_call=4_000,
        max_requests=10,
        max_total_tokens=100_000,
        max_cost=20,
        pricing=ProviderPricing(
            currency="USD",
            as_of="2026-09-12",
            input_cache_hit_per_million=0.1,
            input_cache_miss_per_million=1,
            output_per_million=2,
            status=ReadinessStatus.VERIFIED,
            source_url=f"https://{provider}.example.test/pricing",
        ),
    )


def _task(task_id: str) -> PrelaunchTask:
    return PrelaunchTask(
        task_id=task_id,
        benchmark_resource_id="benchmark-a",
        split="held-out-source-disjoint",
        selected_asset_manifest=f"evidence/{task_id}.json",
        asset_manifest_sha256=SHA,
        license_status=ReadinessStatus.VERIFIED,
        asset_status=ReadinessStatus.VERIFIED,
        held_out=True,
        source_group_disjoint=True,
        signal_kind=TaskSignalKind.MIXED,
    )


def _integrity() -> IntegrityContract:
    return IntegrityContract(
        preregistration_ref="evidence/preregistration.md",
        preregistration_sha256=SHA,
        task_freeze_ref="evidence/tasks.json",
        task_freeze_sha256=SHA,
        failure_policy_ref="evidence/failures.md",
        failure_policy_sha256=SHA,
        repair_policy_ref="evidence/repairs.md",
        repair_policy_sha256=SHA,
        leakage_audit_ref="evidence/leakage.json",
        leakage_audit_sha256=SHA,
        judge_protocol_ref="evidence/judge.json",
        judge_protocol_sha256=SHA,
    )


def _manifest(kind: ConfirmatoryEstimandKind) -> ExperimentPrelaunchManifest:
    candidate = PrelaunchSystem(
        system_id="scitaste-full",
        role=SystemRole.SCITASTE,
        implementation_ref="git://scitaste@0123456789abcdef",
        availability=ReadinessStatus.VERIFIED,
        real_implementation=True,
    )
    if kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL:
        comparators = (
            PrelaunchSystem(
                system_id="native-base",
                role=SystemRole.ABLATION,
                implementation_ref="git://scitaste@0123456789abcdef#base",
                availability=ReadinessStatus.VERIFIED,
                real_implementation=True,
            ),
            PrelaunchSystem(
                system_id="mismatched-taste",
                role=SystemRole.ABLATION,
                implementation_ref="git://scitaste@0123456789abcdef#mismatched-taste",
                availability=ReadinessStatus.VERIFIED,
                real_implementation=True,
            ),
        )
        roles = (
            ConfirmatoryContrastRole.NO_TASTE_CONTROL,
            ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO,
        )
        lane_role = ScientificLaneRole.MATCHED_BACKBONE
        regime = ComparisonRegime.MATCHED_BACKBONE
        confounded = False
    else:
        comparators = tuple(
            PrelaunchSystem(
                system_id=system_id,
                role=SystemRole.METHOD_COMPARATOR,
                implementation_ref=f"git://{system_id}@0123456789abcdef",
                external_resource_id=system_id,
                availability=ReadinessStatus.VERIFIED,
                real_implementation=True,
                adapter_preflight_ref=f"evidence/{system_id}.json",
                adapter_preflight_sha256=SHA,
            )
            for system_id in ("method-a", "method-b")
        )
        roles = (
            ConfirmatoryContrastRole.EXTERNAL_METHOD,
            ConfirmatoryContrastRole.EXTERNAL_METHOD,
        )
        lane_role = (
            ScientificLaneRole.MATCHED_BACKBONE
            if kind is ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY
            else ScientificLaneRole.BEST_NATIVE_SYSTEM
        )
        regime = (
            ComparisonRegime.MATCHED_BACKBONE
            if kind is ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY
            else ComparisonRegime.BEST_NATIVE
        )
        confounded = regime is ComparisonRegime.BEST_NATIVE

    systems = (candidate, *comparators)
    tasks = (_task("heldout-a"), _task("heldout-b"))
    contrasts = tuple(
        ConfirmatoryContrastSpec(
            contrast_id=f"scitaste-full-vs-{system.system_id}",
            candidate_system_id="scitaste-full",
            comparator_system_id=system.system_id,
            role=role,
            favorable_direction="higher",
            minimum_effect=0.05,
        )
        for system, role in zip(comparators, roles, strict=True)
    )
    common_model = _model()
    native_gpu = GpuModelResource(
        host_alias="3090-2",
        device_count=8,
        device_name="NVIDIA GeForce RTX 3090",
        minimum_memory_mb_per_device=24_000,
        checkpoint_id="qwen3-vl-2b-instruct",
        checkpoint_source_path="/weights/Qwen3-VL-2B-Instruct",
        checkpoint_sha256=SHA,
        checkpoint_bytes=4_266_653_057,
        license_identifier="Apache-2.0",
        local_preflight_status=ReadinessStatus.VERIFIED,
        remote_inventory_status=ReadinessStatus.VERIFIED,
        remote_inventory_ref="evidence/gpu-inventory.yaml",
        remote_inventory_sha256=SHA,
        remote_checkpoint_status=ReadinessStatus.VERIFIED,
        remote_checkpoint_attestation_ref="evidence/checkpoint.json",
        remote_checkpoint_attestation_sha256=SHA,
        max_gpu_hours=10,
        max_storage_bytes=10_000_000_000,
    )
    lane = ExecutionLane(
        lane_id="confirmatory-lane",
        kind=(
            ExecutionLaneKind.GPU
            if kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
            else ExecutionLaneKind.API_ONLY
        ),
        scientific_role=lane_role,
        comparison_regime=regime,
        model_effects_confounded=confounded,
        comparison_claim_boundary="Only the declared estimand may use this lane.",
        system_ids=tuple(item.system_id for item in systems),
        task_ids=tuple(item.task_id for item in tasks),
        seeds=(7,),
        repetitions=1,
        planned_cells=6,
        api_model=(
            common_model
            if regime is ComparisonRegime.MATCHED_BACKBONE
            and kind is not ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
            else None
        ),
        system_api_models=(
            tuple(
                SystemApiModelResource(
                    system_id=system.system_id,
                    api_model=_model(f"provider-{index}"),
                )
                for index, system in enumerate(systems, start=1)
            )
            if regime is ComparisonRegime.BEST_NATIVE
            else None
        ),
        gpu_resource=(native_gpu if kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL else None),
    )
    analysis = AnalysisContract(
        primary_outcome="Condition-blinded research outcome preference.",
        estimand="The exact preregistered paired contrast under the declared regime.",
        analysis_unit="held-out task and seed trajectory",
        aggregation_method="paired analysis with failures retained as outcomes",
        uncertainty_method="task-clustered confidence interval",
        power_analysis_ref="evidence/power.json",
        power_analysis_sha256=SHA,
        claim_admission=ClaimAdmissionContract(
            estimand_kind=kind,
            lane_id=lane.lane_id,
            candidate_system_id=candidate.system_id,
            contrasts=contrasts,
            minimum_distinct_tasks=2,
        ),
    )
    payload = {
        "schema_version": "1.3",
        "manifest_id": f"claim-{kind.value}",
        "protocol_id": f"claim-{kind.value}",
        "protocol_version": "test-v1",
        "study_scope": "formal",
        "scientific_question": "Does the preregistered effect hold?",
        "claim_allowed": "Only the machine-bound confirmatory estimand.",
        "claim_forbidden": "No result may cross its causal interpretation boundary.",
        "primary_endpoint": ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE,
        "automated_judge_role": AutomatedJudgeRole.SECONDARY_DIAGNOSTIC,
        "source_commit": "0" * 40,
        "resource_corpus_sha256": SHA,
        "systems": systems,
        "tasks": tasks,
        "lanes": (lane,),
        "human_review": HumanReviewResource(
            required=True,
            minimum_reviewers_per_artifact=2,
            condition_blinded=True,
            conflict_check_required=True,
            recruitment_status=ReadinessStatus.VERIFIED,
            rubric_status=ReadinessStatus.VERIFIED,
            adjudication_status=ReadinessStatus.VERIFIED,
            maximum_reviewer_hours=20,
        ),
        "retention": RetentionContract(
            output_root="outputs/projects/claim-test",
            archive_root="outputs/archive/claim-test",
            maximum_output_bytes=1_000_000_000,
            retain_raw_provider_responses=True,
            retain_failed_runs=True,
            secrets_forbidden=True,
        ),
        "analysis": analysis,
        "integrity": _integrity(),
        "launch_order": (lane.lane_id,),
        "stop_rules": ("Stop on identity drift; retain valid failures.",),
        "approval": PrelaunchApproval(),
    }
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-12T00:00:00Z",
    )
    return ExperimentPrelaunchManifest.model_validate(payload)


def _v14_native_manifest() -> ExperimentPrelaunchManifest:
    """Add one component-only diagnostic without changing legacy helper semantics."""

    payload = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL).model_dump(mode="json")
    payload["schema_version"] = "1.4"
    payload["manifest_id"] = "claim-native-taste-causal-v14"
    payload["protocol_id"] = "claim-native-taste-causal-v14"
    payload["protocol_version"] = "test-v1.4"
    payload["approval"] = {"approved": False}
    payload["systems"].append(
        {
            "system_id": "native-knowledge",
            "role": "ablation",
            "implementation_ref": "git://scitaste@0123456789abcdef#native-knowledge",
            "availability": "verified",
            "real_implementation": True,
        }
    )
    payload["lanes"][0]["system_ids"].append("native-knowledge")
    payload["lanes"][0]["planned_cells"] = 8
    for contrast in payload["analysis"]["claim_admission"]["contrasts"]:
        contrast["inference_role"] = ContrastInferenceRole.CONFIRMATORY
    payload["analysis"]["claim_admission"]["contrasts"].append(
        {
            "contrast_id": "scitaste-full-vs-native-knowledge",
            "candidate_system_id": "scitaste-full",
            "comparator_system_id": "native-knowledge",
            "role": ConfirmatoryContrastRole.COMPONENT_ONLY,
            "inference_role": ContrastInferenceRole.MECHANISM_DIAGNOSTIC,
            "favorable_direction": "higher",
            "minimum_effect": 0.05,
        }
    )
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-12T00:00:00Z",
    )
    return ExperimentPrelaunchManifest.model_validate(payload)


def _artifact(root: Path, locator: str, content: str) -> EvaluationResultArtifact:
    path = root / locator
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    raw = path.read_bytes()
    return EvaluationResultArtifact(
        locator=locator,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def _outcome() -> StudyOutcome:
    return StudyOutcome(
        useful_results=1,
        proposed_ideas=2,
        valid_ideas=1,
        pilots=1,
        discarded_ideas=1,
        unproductive_experiments=0,
        total_experiments=1,
        gpu_hours_before_useful_signal=None,
        pivots=1,
        correct_pivots=1,
        evidence_sufficiency=0.9,
        reviewer_concerns_opened=1,
        reviewer_concerns_closed=1,
        total_claims=2,
        unsupported_claims=0,
    )


def _result_set(
    root: Path,
    manifest: ExperimentPrelaunchManifest,
    *,
    failed_system: str | None = None,
) -> EvaluationResultSet:
    plan = compile_evaluation_cell_plan(manifest)
    results: list[EvaluationCellResult] = []
    reviews: list[EvaluationBlindReview] = []
    for cell in plan.cells:
        usage = (
            EvaluationCellUsage(
                gpu_hours=0.2,
                wall_time_hours=0.2,
                experiment_count=1,
            )
            if cell.lane_kind is ExecutionLaneKind.GPU
            else EvaluationCellUsage(
                request_count=2,
                input_tokens=1_000,
                output_tokens=500,
                api_cost=1.5,
                wall_time_hours=0.2,
                experiment_count=1,
            )
        )
        if cell.system_id == failed_system and cell.task_id == "heldout-a":
            result = EvaluationCellResult.create(
                cell_id=cell.cell_id,
                proposal_sha256=plan.proposal_sha256,
                plan_sha256=plan.plan_sha256,
                cell_sha256=content_sha256(cell),
                resource_sha256=cell.resource.resource_sha256,
                status="failed",
                evidence_class="real",
                usage=usage,
                error_code="task-failed",
            )
        else:
            result = EvaluationCellResult.create(
                cell_id=cell.cell_id,
                proposal_sha256=plan.proposal_sha256,
                plan_sha256=plan.plan_sha256,
                cell_sha256=content_sha256(cell),
                resource_sha256=cell.resource.resource_sha256,
                status="succeeded",
                evidence_class="real",
                usage=usage,
                outcome=_outcome(),
                artifacts=(
                    _artifact(
                        root,
                        f"runs/{cell.cell_id}/package.json",
                        f'{{"cell":"{cell.cell_id}"}}\n',
                    ),
                ),
            )
        results.append(result)
        reviews.append(
            EvaluationBlindReview.create(
                blind_id=cell.review_blind_id,
                source="external",
                reviewer_identity_hashes=("1" * 64, "2" * 64),
                rubric_id="claim-rubric-v1",
                rubric_sha256=SHA,
                criterion_scores={"scientific_value": 0.8},
                final_preference_score=0.8,
                attestation=_artifact(
                    root,
                    f"reviews/{cell.review_blind_id}.json",
                    f'{{"blind":"{cell.review_blind_id}"}}\n',
                ),
            )
        )

    assert manifest.analysis is not None
    assert manifest.analysis.claim_admission is not None
    claim = manifest.analysis.claim_admission
    record_map = {item.cell_id: item for item in results}
    comparisons = tuple(
        EvaluationPrimaryComparison.create(
            schema_version="1.1",
            comparison_id=spec.contrast_id,
            analysis_contract_sha256=content_sha256(manifest.analysis),
            analysis_input_sha256=claim_analysis_input_sha256(
                claim,
                spec,
                plan.cells,
                record_map,
            ),
            failure_handling=claim.failure_handling,
            candidate_system_id=spec.candidate_system_id,
            comparator_system_id=spec.comparator_system_id,
            analysis_unit_count=2,
            favorable_direction=spec.favorable_direction,
            minimum_effect=spec.minimum_effect,
            effect_estimate=0.2,
            interval_lower=0.1,
            interval_upper=0.3,
            conclusion="supports_claim",
            analysis_artifact=_artifact(
                root,
                f"analysis/{spec.contrast_id}.json",
                f'{{"contrast":"{spec.contrast_id}"}}\n',
            ),
        )
        for spec in manifest.analysis.claim_admission.contrasts
    )
    return EvaluationResultSet.create(
        project_id="claim-project",
        evaluation_id="claim-evaluation",
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_results=tuple(results),
        blind_reviews=tuple(reviews),
        primary_comparisons=comparisons,
    )


def _inspect(
    root: Path,
    manifest: ExperimentPrelaunchManifest,
    results: EvaluationResultSet,
):
    return inspect_evaluation_results(
        manifest,
        compile_evaluation_cell_plan(manifest),
        results,
        project_root=root,
        project_id="claim-project",
        evaluation_id="claim-evaluation",
        execution_authorized=True,
    )


def _replace_comparison_interval(
    results: EvaluationResultSet,
    comparison_id: str,
    *,
    interval_lower: float,
    interval_upper: float,
    conclusion: str,
) -> EvaluationResultSet:
    source = next(
        item for item in results.primary_comparisons if item.comparison_id == comparison_id
    )
    replacement = EvaluationPrimaryComparison.create(
        schema_version=source.schema_version,
        comparison_id=source.comparison_id,
        analysis_contract_sha256=source.analysis_contract_sha256,
        analysis_input_sha256=source.analysis_input_sha256,
        failure_handling=source.failure_handling,
        candidate_system_id=source.candidate_system_id,
        comparator_system_id=source.comparator_system_id,
        analysis_unit_count=source.analysis_unit_count,
        favorable_direction=source.favorable_direction,
        minimum_effect=source.minimum_effect,
        effect_estimate=(interval_lower + interval_upper) / 2,
        interval_lower=interval_lower,
        interval_upper=interval_upper,
        conclusion=conclusion,
        analysis_artifact=source.analysis_artifact,
    )
    comparisons = tuple(
        replacement if item.comparison_id == comparison_id else item
        for item in results.primary_comparisons
    )
    return EvaluationResultSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=results.proposal_sha256,
        plan_sha256=results.plan_sha256,
        cell_results=results.cell_results,
        blind_reviews=results.blind_reviews,
        primary_comparisons=comparisons,
    )


def test_native_taste_contract_is_content_bound_and_keeps_real_failures() -> None:
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    plan = compile_evaluation_cell_plan(manifest)

    assert plan.schema_version == "1.2"
    assert plan.claim_estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
    assert plan.claim_lane_id == "confirmatory-lane"
    assert plan.claim_contract_sha256 == content_sha256(manifest.analysis.claim_admission)


def test_v14_requires_explicit_scientifically_valid_inference_roles() -> None:
    manifest = _v14_native_manifest()
    claim = manifest.analysis.claim_admission
    assert claim is not None
    by_role = {item.role: item.inference_role for item in claim.contrasts}
    assert by_role[ConfirmatoryContrastRole.NO_TASTE_CONTROL] is (
        ContrastInferenceRole.CONFIRMATORY
    )
    assert by_role[ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO] is (
        ContrastInferenceRole.CONFIRMATORY
    )
    assert by_role[ConfirmatoryContrastRole.COMPONENT_ONLY] is (
        ContrastInferenceRole.MECHANISM_DIAGNOSTIC
    )

    missing = manifest.model_dump(mode="json")
    missing["approval"] = {"approved": False}
    missing["analysis"]["claim_admission"]["contrasts"][0].pop("inference_role")
    with pytest.raises(ValidationError, match="requires every contrast inference role"):
        ExperimentPrelaunchManifest.model_validate(missing)

    wrong_control = manifest.model_dump(mode="json")
    wrong_control["approval"] = {"approved": False}
    wrong_control["analysis"]["claim_admission"]["contrasts"][0]["inference_role"] = (
        ContrastInferenceRole.MECHANISM_DIAGNOSTIC
    )
    with pytest.raises(ValidationError, match="no-Taste and placebo contrasts"):
        ExperimentPrelaunchManifest.model_validate(wrong_control)

    wrong_component = manifest.model_dump(mode="json")
    wrong_component["approval"] = {"approved": False}
    component = next(
        item
        for item in wrong_component["analysis"]["claim_admission"]["contrasts"]
        if item["role"] == ConfirmatoryContrastRole.COMPONENT_ONLY
    )
    component["inference_role"] = ContrastInferenceRole.CONFIRMATORY
    with pytest.raises(ValidationError, match="component-only or component-ablation"):
        ExperimentPrelaunchManifest.model_validate(wrong_component)

    legacy = manifest.model_dump(mode="json")
    legacy["approval"] = {"approved": False}
    legacy["schema_version"] = "1.3"
    with pytest.raises(ValidationError, match=r"v1\.4 is required"):
        ExperimentPrelaunchManifest.model_validate(legacy)


def test_v14_external_claims_cannot_downgrade_a_comparator_to_diagnostic() -> None:
    payload = _manifest(ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY).model_dump(
        mode="json"
    )
    payload["schema_version"] = "1.4"
    payload["approval"] = {"approved": False}
    for contrast in payload["analysis"]["claim_admission"]["contrasts"]:
        contrast["inference_role"] = ContrastInferenceRole.CONFIRMATORY
    ExperimentPrelaunchManifest.model_validate(payload)

    payload["analysis"]["claim_admission"]["contrasts"][0]["inference_role"] = (
        ContrastInferenceRole.MECHANISM_DIAGNOSTIC
    )
    with pytest.raises(ValidationError, match="external claim contrasts must be confirmatory"):
        ExperimentPrelaunchManifest.model_validate(payload)


def test_v13_hashes_remain_stable_after_v14_extension() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = ExperimentPrelaunchManifest.model_validate(
        yaml.safe_load(
            (
                root / "configs/evaluation/prelaunch/qwen3vl2b_native_taste_causal_prepilot_v7.yaml"
            ).read_text(encoding="utf-8")
        )
    )
    assert manifest.proposal_sha256 == (
        "f7a17de63440ea89dc69932c2d4826149e3f2346300b037ebded3994e6420396"
    )
    assert manifest.analysis is not None
    assert manifest.analysis.claim_admission is not None
    assert content_sha256(manifest.analysis.claim_admission) == (
        "1ef8d14bc5e15cd1dcd9d597b953fc80fcead263ed8af5b2aad0fc7666a2dce4"
    )
    assert content_sha256(manifest.analysis) == (
        "2ca6185689231e0eea4cfafba71b8e5dc430de32a8c8c4b8cd046f77520b49c7"
    )


@pytest.mark.parametrize(
    ("interval_lower", "interval_upper", "conclusion"),
    (
        (-0.1, 0.1, "inconclusive"),
        (-0.3, -0.1, "contradicts_claim"),
    ),
)
def test_mechanism_diagnostic_need_not_support_title_claim(
    tmp_path: Path,
    interval_lower: float,
    interval_upper: float,
    conclusion: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _v14_native_manifest()
    results = _replace_comparison_interval(
        _result_set(root, manifest),
        "scitaste-full-vs-native-knowledge",
        interval_lower=interval_lower,
        interval_upper=interval_upper,
        conclusion=conclusion,
    )

    assessment = _inspect(root, manifest, results)

    assert assessment.schema_version == "1.2"
    assert assessment.confirmatory_evidence_complete is True
    assert assessment.confirmatory_conclusion_supported is True
    assert assessment.title_claim_eligible is True
    assert assessment.required_confirmatory_comparisons == 2
    assert assessment.valid_confirmatory_comparisons == 2
    assert assessment.supported_confirmatory_comparisons == 2
    assert assessment.required_diagnostic_comparisons == 1
    assert assessment.valid_diagnostic_comparisons == 1


def test_missing_mechanism_diagnostic_keeps_title_evidence_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _v14_native_manifest()
    results = _result_set(root, manifest)
    results = EvaluationResultSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=results.proposal_sha256,
        plan_sha256=results.plan_sha256,
        cell_results=results.cell_results,
        blind_reviews=results.blind_reviews,
        primary_comparisons=tuple(
            item
            for item in results.primary_comparisons
            if item.comparison_id != "scitaste-full-vs-native-knowledge"
        ),
    )

    assessment = _inspect(root, manifest, results)

    assert assessment.confirmatory_evidence_complete is False
    assert assessment.confirmatory_conclusion_supported is False
    assert assessment.title_claim_eligible is False
    assert assessment.required_diagnostic_comparisons == 1
    assert assessment.valid_diagnostic_comparisons == 0
    assert "analysis:scitaste-full-vs-native-knowledge:missing" in assessment.blocker_codes


@pytest.mark.parametrize(
    "comparison_id",
    (
        "scitaste-full-vs-native-base",
        "scitaste-full-vs-mismatched-taste",
    ),
)
def test_each_confirmatory_control_can_block_title_claim(
    tmp_path: Path,
    comparison_id: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _v14_native_manifest()
    results = _replace_comparison_interval(
        _result_set(root, manifest),
        comparison_id,
        interval_lower=-0.1,
        interval_upper=0.1,
        conclusion="inconclusive",
    )

    assessment = _inspect(root, manifest, results)

    assert assessment.confirmatory_evidence_complete is True
    assert assessment.confirmatory_conclusion_supported is False
    assert assessment.title_claim_eligible is False
    assert assessment.supported_confirmatory_comparisons == 1


def test_native_taste_result_can_close_with_preregistered_failures(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    assessment = _inspect(root, manifest, _result_set(root, manifest, failed_system="native-base"))

    assert assessment.schema_version == "1.1"
    assert assessment.status == "complete"
    assert assessment.failed_cells == 1
    assert assessment.confirmatory_evidence_complete is True
    assert assessment.confirmatory_conclusion_supported is True
    assert assessment.title_claim_eligible is True
    assert assessment.external_superiority_eligible is False
    assert assessment.descriptive_external_complete is False
    assert assessment.scientific_effectiveness_established is True
    assert not any("execution-failed" in code for code in assessment.blocker_codes)


def test_best_native_result_stays_descriptive_even_when_positive(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _manifest(ConfirmatoryEstimandKind.EXTERNAL_BEST_NATIVE)
    assessment = _inspect(root, manifest, _result_set(root, manifest))

    assert assessment.confirmatory_evidence_complete is True
    assert assessment.confirmatory_conclusion_supported is True
    assert assessment.descriptive_external_complete is True
    assert assessment.scientific_evidence_complete is False
    assert assessment.headline_eligible is False
    assert assessment.scientific_effectiveness_established is False
    assert assessment.title_claim_eligible is False
    assert assessment.external_superiority_eligible is False
    assert assessment.blocker_codes == ()


def test_matched_external_result_has_separate_superiority_semantics(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _manifest(ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY)
    assessment = _inspect(root, manifest, _result_set(root, manifest))

    assert assessment.confirmatory_evidence_complete is True
    assert assessment.external_superiority_eligible is True
    assert assessment.title_claim_eligible is False
    assert assessment.descriptive_external_complete is False
    assert assessment.scientific_evidence_complete is True
    assert assessment.scientific_effectiveness_established is True


def test_claim_contract_rejects_missing_placebo_and_old_schema() -> None:
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    payload = manifest.model_dump(mode="json")
    payload["approval"] = {"approved": False}
    payload["analysis"]["claim_admission"]["contrasts"] = payload["analysis"]["claim_admission"][
        "contrasts"
    ][:1]
    with pytest.raises(ValidationError, match="requires no-Taste and placebo"):
        ExperimentPrelaunchManifest.model_validate(payload)

    payload = manifest.model_dump(mode="json")
    payload["approval"] = {"approved": False}
    payload["schema_version"] = "1.2"
    with pytest.raises(ValidationError, match=r"v1\.3 is required"):
        ExperimentPrelaunchManifest.model_validate(payload)


def test_claim_contract_rejects_unreported_lane_comparator() -> None:
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    payload = manifest.model_dump(mode="json")
    payload["approval"] = {"approved": False}
    payload["systems"].append(
        {
            "system_id": "unreported-ablation",
            "role": "ablation",
            "implementation_ref": "git://scitaste@0123456789abcdef#unreported",
            "availability": "verified",
            "real_implementation": True,
        }
    )
    payload["lanes"][0]["system_ids"].append("unreported-ablation")
    payload["lanes"][0]["planned_cells"] = 8

    with pytest.raises(ValidationError, match="cover every non-candidate system"):
        ExperimentPrelaunchManifest.model_validate(payload)


def test_result_decision_rule_must_match_preregistration(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    results = _result_set(root, manifest)
    first = results.primary_comparisons[0]
    drifted = EvaluationPrimaryComparison.create(
        schema_version=first.schema_version,
        comparison_id=first.comparison_id,
        analysis_contract_sha256=first.analysis_contract_sha256,
        analysis_input_sha256=first.analysis_input_sha256,
        failure_handling=first.failure_handling,
        candidate_system_id=first.candidate_system_id,
        comparator_system_id=first.comparator_system_id,
        analysis_unit_count=first.analysis_unit_count,
        favorable_direction=first.favorable_direction,
        minimum_effect=0.01,
        effect_estimate=first.effect_estimate,
        interval_lower=first.interval_lower,
        interval_upper=first.interval_upper,
        conclusion=first.conclusion,
        analysis_artifact=first.analysis_artifact,
    )
    results = EvaluationResultSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=results.proposal_sha256,
        plan_sha256=results.plan_sha256,
        cell_results=results.cell_results,
        blind_reviews=results.blind_reviews,
        primary_comparisons=(drifted, *results.primary_comparisons[1:]),
    )

    assessment = _inspect(root, manifest, results)

    assert assessment.confirmatory_evidence_complete is False
    assert f"analysis:{first.comparison_id}:decision-rule-mismatch" in assessment.blocker_codes


def test_result_analysis_input_must_bind_every_failure_in_the_contrast(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    results = _result_set(root, manifest, failed_system="native-base")
    first = results.primary_comparisons[0]
    drifted = EvaluationPrimaryComparison.create(
        schema_version="1.1",
        comparison_id=first.comparison_id,
        analysis_contract_sha256=first.analysis_contract_sha256,
        analysis_input_sha256="b" * 64,
        failure_handling="include-as-outcome",
        candidate_system_id=first.candidate_system_id,
        comparator_system_id=first.comparator_system_id,
        analysis_unit_count=first.analysis_unit_count,
        favorable_direction=first.favorable_direction,
        minimum_effect=first.minimum_effect,
        effect_estimate=first.effect_estimate,
        interval_lower=first.interval_lower,
        interval_upper=first.interval_upper,
        conclusion=first.conclusion,
        analysis_artifact=first.analysis_artifact,
    )
    drifted_results = EvaluationResultSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=results.proposal_sha256,
        plan_sha256=results.plan_sha256,
        cell_results=results.cell_results,
        blind_reviews=results.blind_reviews,
        primary_comparisons=(drifted, *results.primary_comparisons[1:]),
    )

    assessment = _inspect(root, manifest, drifted_results)

    assert assessment.confirmatory_evidence_complete is False
    assert f"analysis:{first.comparison_id}:analysis-input-mismatch" in assessment.blocker_codes


def test_objective_analysis_collapses_seed_blocks_before_confirmatory_inference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    power = _artifact(root, "evidence/power.json", '{"independent_units":"tasks"}\n')
    task_contracts = []
    for task_id in ("heldout-a", "heldout-b"):
        scorer = _artifact(
            root,
            f"evidence/scorers/{task_id}.py",
            f"# frozen scorer for {task_id}\n",
        )
        task_contracts.append(
            ObjectiveTaskScoreContract(
                task_id=task_id,
                source_group_id=f"source-{task_id}",
                metric_id="normalized-objective-gain",
                metric_version="test-v1",
                direction=ObjectiveDirection.HIGHER,
                raw_minimum=0,
                raw_maximum=1,
                starting_score=0.5,
                target_score=1,
                failure_normalized_score=-1,
                scorer_artifact=scorer,
            )
        )
    objective_contract = ObjectiveOutcomeContract.create(
        contract_id="objective-test-v1",
        protocol_id="claim-native_taste_causal",
        endpoint_id="normalized-objective-gain",
        task_scores=tuple(task_contracts),
        bootstrap_resamples=1_000,
        monte_carlo_sign_flips=10_000,
    )
    contract_path = save_objective_outcome_contract(
        objective_contract, root / "evidence/objective-contract.json"
    )
    contract_inspection = load_objective_outcome_contract(contract_path)

    payload = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL).model_dump(mode="json")
    payload["approval"] = {"approved": False}
    payload["lanes"][0]["seeds"] = [7, 11]
    payload["lanes"][0]["planned_cells"] = 12
    payload["analysis"]["power_analysis_sha256"] = power.sha256
    payload["analysis"]["objective_outcome_contract_ref"] = "evidence/objective-contract.json"
    payload["analysis"]["objective_outcome_contract_sha256"] = contract_inspection.file_sha256
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-12T00:00:00Z",
    )
    manifest = ExperimentPrelaunchManifest.model_validate(payload)
    plan = compile_evaluation_cell_plan(manifest)
    result_with_manual_comparisons = _result_set(root, manifest, failed_system="native-base")
    raw_results = EvaluationResultSet.create(
        project_id=result_with_manual_comparisons.project_id,
        evaluation_id=result_with_manual_comparisons.evaluation_id,
        proposal_sha256=result_with_manual_comparisons.proposal_sha256,
        plan_sha256=result_with_manual_comparisons.plan_sha256,
        cell_results=result_with_manual_comparisons.cell_results,
        blind_reviews=result_with_manual_comparisons.blind_reviews,
        primary_comparisons=(),
    )
    records = {item.cell_id: item for item in raw_results.cell_results}
    scored = []
    for cell in plan.cells:
        if records[cell.cell_id].status == "failed":
            continue
        raw_score = 0.95 if cell.system_id == "scitaste-full" else 0.55
        score_artifact = _artifact(
            root,
            f"scores/{cell.cell_id}.json",
            f'{{"cell_id":"{cell.cell_id}","raw_score":{raw_score}}}\n',
        )
        scored.append(
            ObjectiveCellMeasurement.create(
                cell_id=cell.cell_id,
                result_record_sha256=records[cell.cell_id].record_sha256,
                metric_id="normalized-objective-gain",
                metric_version="test-v1",
                raw_score=raw_score,
                score_artifact=score_artifact,
            )
        )
    measurements = ObjectiveMeasurementSet.create(
        project_id=raw_results.project_id,
        evaluation_id=raw_results.evaluation_id,
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_result_population_sha256=objective_cell_population_sha256(raw_results),
        objective_outcome_contract_sha256=contract_inspection.file_sha256,
        measurements=tuple(scored),
    )
    measurement_path = save_objective_measurement_set(
        measurements, root / "scores/measurement-set.json"
    )
    measurement_artifact = bind_objective_measurement_set(
        measurement_path,
        project_root=root,
    )
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(exist_ok=True)
    materialized = materialize_objective_analysis(
        manifest,
        plan,
        raw_results,
        contract_inspection,
        measurements,
        measurement_artifact,
        project_root=root,
        project_id=raw_results.project_id,
        evaluation_id=raw_results.evaluation_id,
        output_path="analysis/objective-report.json",
    )

    assert len(materialized.primary_comparisons) == 2
    assert all(item.schema_version == "1.2" for item in materialized.primary_comparisons)
    assert all(item.analysis_unit_count == 2 for item in materialized.primary_comparisons)
    assert all(item.observed_block_count == 4 for item in materialized.primary_comparisons)
    assert all(item.adjusted_p_value is not None for item in materialized.primary_comparisons)
    base_contrast = next(
        item
        for item in materialized.report.comparisons
        if item.comparator_system_id == "native-base"
    )
    failed_task = next(item for item in base_contrast.task_effects if item.task_id == "heldout-a")
    assert failed_task.comparator_normalized_mean == -1

    final_results = complete_objective_result_set(raw_results, materialized)
    assessment = inspect_evaluation_results(
        manifest,
        plan,
        final_results,
        project_root=root,
        project_id=raw_results.project_id,
        evaluation_id=raw_results.evaluation_id,
        execution_authorized=True,
    )

    assert assessment.scientific_evidence_complete is True
    assert assessment.scientific_effectiveness_established is False

    first = final_results.primary_comparisons[0]
    tampered_payload = first.model_dump(mode="python", exclude={"comparison_sha256"})
    tampered_payload["raw_p_value"] = 0.9
    tampered_payload["objective_measurement_set_artifact"] = (
        first.objective_measurement_set_artifact
    )
    tampered_payload["analysis_artifact"] = first.analysis_artifact
    tampered = EvaluationPrimaryComparison.create(**tampered_payload)
    tampered_results = EvaluationResultSet.create(
        project_id=final_results.project_id,
        evaluation_id=final_results.evaluation_id,
        proposal_sha256=final_results.proposal_sha256,
        plan_sha256=final_results.plan_sha256,
        cell_results=final_results.cell_results,
        blind_reviews=final_results.blind_reviews,
        primary_comparisons=(tampered, *final_results.primary_comparisons[1:]),
    )
    tampered_assessment = inspect_evaluation_results(
        manifest,
        plan,
        tampered_results,
        project_root=root,
        project_id=raw_results.project_id,
        evaluation_id=raw_results.evaluation_id,
        execution_authorized=True,
    )
    assert (
        f"analysis:{first.comparison_id}:executable-analysis-mismatch"
        in tampered_assessment.blocker_codes
    )
