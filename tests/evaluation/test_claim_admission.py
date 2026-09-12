from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
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
    claim_analysis_input_sha256,
    compile_evaluation_cell_plan,
    inspect_evaluation_results,
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


def test_native_taste_contract_is_content_bound_and_keeps_real_failures() -> None:
    manifest = _manifest(ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL)
    plan = compile_evaluation_cell_plan(manifest)

    assert plan.schema_version == "1.2"
    assert plan.claim_estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
    assert plan.claim_lane_id == "confirmatory-lane"
    assert plan.claim_contract_sha256 == content_sha256(manifest.analysis.claim_admission)


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
