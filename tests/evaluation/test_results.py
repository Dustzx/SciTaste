from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.cli import main
from scitaste.evaluation import (
    AnalysisContract,
    ApiModelResource,
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
    ScientificLaneRole,
    SystemRole,
    compile_evaluation_cell_plan,
    inspect_evaluation_results,
    prepare_project_evaluation_result,
    publish_project_evaluation_result,
)
from scitaste.generative_ui import (
    ProjectProgressQuery,
    TrustedComponent,
    WorkspaceSurfaceFactory,
)
from scitaste.lifecycle import assess_project_lifecycle
from scitaste.project import (
    PaperManifest,
    ProjectEvaluationArtifact,
    ProjectEvaluationBundle,
    ProjectManifest,
    ProjectRun,
    ProjectRuntime,
)
from scitaste.project.models import content_sha256
from scitaste.review import (
    ReviewerIdentity,
    ReviewFeedback,
    VenueCriterionAssessment,
    VenueReviewReport,
    build_project_evaluation_closure_proofs,
    import_venue_review_report,
    inspect_project_evaluation_evidence,
    prepare_project_evaluation_evidence,
    prepare_project_review_routing,
    prepare_venue_review,
    publish_project_evaluation_evidence,
    publish_project_review_routing,
)
from scitaste.state.research_state import ResearchState
from scitaste.writing import materialize_paper_scientific_evidence

SHA = "a" * 64


def _analysis() -> AnalysisContract:
    return AnalysisContract(
        primary_outcome="Condition-blinded final research preference.",
        estimand="Mean paired SciTaste advantage over each external method.",
        analysis_unit="held-out task and seed trajectory",
        aggregation_method="paired mean by task and seed",
        uncertainty_method="task-clustered confidence interval",
        power_analysis_ref="evidence/power.json",
        power_analysis_sha256=SHA,
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


def _systems() -> tuple[PrelaunchSystem, ...]:
    return (
        PrelaunchSystem(
            system_id="scitaste-native",
            role=SystemRole.SCITASTE,
            implementation_ref="git://scitaste@0123456789abcdef",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
        ),
        PrelaunchSystem(
            system_id="direct-agent",
            role=SystemRole.CONTROL,
            implementation_ref="scitaste://direct-agent-v1",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
            adapter_preflight_ref="evidence/direct.json",
            adapter_preflight_sha256=SHA,
        ),
        *(
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
        ),
    )


def _common_manifest_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "test-v1",
        "scientific_question": "Does scientific taste improve held-out research outcomes?",
        "claim_allowed": "The frozen comparison supports only its preregistered population.",
        "claim_forbidden": "The study does not establish universal research superiority.",
        "source_commit": "0" * 40,
        "resource_corpus_sha256": SHA,
        "systems": _systems(),
        "tasks": (
            PrelaunchTask(
                task_id="heldout-task",
                benchmark_resource_id="benchmark-a",
                split="source-disjoint-test",
                selected_asset_manifest="evidence/task.json",
                asset_manifest_sha256=SHA,
                license_status=ReadinessStatus.VERIFIED,
                asset_status=ReadinessStatus.VERIFIED,
                held_out=True,
                source_group_disjoint=True,
            ),
        ),
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
            output_root="outputs/projects/result-project/runs/formal",
            archive_root="outputs/archive/result-project",
            maximum_output_bytes=1_000_000_000,
            retain_raw_provider_responses=True,
            retain_failed_runs=True,
            secrets_forbidden=True,
        ),
        "analysis": _analysis(),
        "integrity": _integrity(),
        "stop_rules": ("Stop before a cell exceeds its exact resource ceiling.",),
        "approval": PrelaunchApproval(),
    }


def _formal_manifest() -> ExperimentPrelaunchManifest:
    payload = _common_manifest_payload()
    lane = ExecutionLane(
        lane_id="api-headline",
        kind=ExecutionLaneKind.API_ONLY,
        scientific_role=ScientificLaneRole.MATCHED_BACKBONE,
        system_ids=tuple(item.system_id for item in _systems()),
        task_ids=("heldout-task",),
        seeds=(7,),
        repetitions=1,
        planned_cells=4,
        api_model=ApiModelResource(
            provider_id="provider",
            endpoint="https://api.example.test/v1",
            interface="openai-chat-completions",
            model_id="frontier-model",
            model_revision="frontier-model-2026-09-11",
            rolling_alias=False,
            identity_source_url="https://example.test/model",
            identity_status=ReadinessStatus.VERIFIED,
            api_key_env="PROVIDER_API_KEY",
            max_input_tokens_per_call=10_000,
            max_output_tokens_per_call=4_000,
            max_requests=10,
            max_total_tokens=100_000,
            max_cost=20,
            pricing=ProviderPricing(
                currency="USD",
                as_of="2026-09-11",
                input_cache_hit_per_million=0.1,
                input_cache_miss_per_million=1,
                output_per_million=2,
                status=ReadinessStatus.VERIFIED,
                source_url="https://example.test/pricing",
            ),
        ),
    )
    payload.update(
        {
            "manifest_id": "formal-result-test",
            "protocol_id": "formal-result-test",
            "study_scope": "formal",
            "lanes": (lane,),
            "launch_order": (lane.lane_id,),
        }
    )
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-11T00:00:00Z",
    )
    return ExperimentPrelaunchManifest.model_validate(payload)


def _best_native_formal_manifest() -> ExperimentPrelaunchManifest:
    payload = _formal_manifest().model_dump(mode="json")
    payload.update(
        {
            "schema_version": "1.2",
            "primary_endpoint": "blinded_package_preference",
            "automated_judge_role": "secondary_diagnostic",
            "approval": {"approved": False},
        }
    )
    for task in payload["tasks"]:
        task["signal_kind"] = "research_package_review"
    lane = payload["lanes"][0]
    api_model = lane.pop("api_model")
    lane.update(
        {
            "scientific_role": "best_native_system",
            "comparison_regime": "best_native",
            "model_effects_confounded": True,
            "comparison_claim_boundary": (
                "This estimates native package performance with model effects confounded; "
                "it cannot establish the causal effect of the SciTaste scaffold."
            ),
            "system_api_models": [
                {"system_id": system_id, "api_model": api_model} for system_id in lane["system_ids"]
            ],
        }
    )
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = {
        "approved": True,
        "approved_proposal_sha256": draft.proposal_sha256,
        "approved_by": "project-owner",
        "approved_at": "2026-09-11T00:00:00Z",
    }
    return ExperimentPrelaunchManifest.model_validate(payload)


def _gpu_manifest() -> ExperimentPrelaunchManifest:
    payload = _common_manifest_payload()
    systems = (
        PrelaunchSystem(
            system_id="scitaste-native",
            role=SystemRole.SCITASTE,
            implementation_ref="git://scitaste@0123456789abcdef",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
        ),
        PrelaunchSystem(
            system_id="taste-ablation",
            role=SystemRole.ABLATION,
            implementation_ref="git://scitaste@0123456789abcdef#no-taste",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
        ),
    )
    lane = ExecutionLane(
        lane_id="gpu-robustness",
        kind=ExecutionLaneKind.GPU,
        scientific_role=ScientificLaneRole.SMALL_MODEL_ROBUSTNESS,
        system_ids=tuple(item.system_id for item in systems),
        task_ids=("heldout-task",),
        seeds=(7,),
        repetitions=1,
        planned_cells=2,
        gpu_resource=GpuModelResource(
            host_alias="3090-2",
            device_count=8,
            device_name="NVIDIA GeForce RTX 3090",
            minimum_memory_mb_per_device=24_000,
            checkpoint_id="qwen3-vl-2b-instruct",
            checkpoint_source_path="/weights/Qwen3-VL-2B-Instruct",
            checkpoint_sha256=SHA,
            checkpoint_bytes=4_000_000_000,
            license_identifier="Apache-2.0",
            local_preflight_status=ReadinessStatus.VERIFIED,
            remote_inventory_status=ReadinessStatus.VERIFIED,
            remote_inventory_ref="inventory/3090-2.yaml",
            remote_inventory_sha256=SHA,
            remote_checkpoint_status=ReadinessStatus.VERIFIED,
            remote_checkpoint_attestation_ref="inventory/qwen3vl2b.yaml",
            remote_checkpoint_attestation_sha256=SHA,
            max_gpu_hours=3,
            max_storage_bytes=10_000_000_000,
            network_access=False,
        ),
    )
    payload.update(
        {
            "manifest_id": "gpu-result-test",
            "protocol_id": "gpu-result-test",
            "study_scope": "robustness",
            "systems": systems,
            "lanes": (lane,),
            "human_review": HumanReviewResource(
                required=False,
                minimum_reviewers_per_artifact=0,
                condition_blinded=False,
                conflict_check_required=False,
                recruitment_status=ReadinessStatus.PENDING,
                rubric_status=ReadinessStatus.PENDING,
                adjudication_status=ReadinessStatus.PENDING,
                maximum_reviewer_hours=0,
            ),
            "launch_order": (lane.lane_id,),
        }
    )
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-11T00:00:00Z",
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
        unproductive_experiments=1,
        total_experiments=2,
        gpu_hours_before_useful_signal=None,
        pivots=1,
        correct_pivots=1,
        evidence_sufficiency=0.8,
        reviewer_concerns_opened=2,
        reviewer_concerns_closed=2,
        total_claims=4,
        unsupported_claims=0,
    )


def _result_set(
    root: Path,
    manifest: ExperimentPrelaunchManifest,
    *,
    include_reviews: bool = True,
    synthetic_system: str | None = None,
) -> EvaluationResultSet:
    plan = compile_evaluation_cell_plan(manifest)
    results = []
    reviews = []
    for cell in plan.cells:
        result_artifact = _artifact(
            root,
            f"runs/formal/{cell.cell_id}/paper.pdf",
            f"paper for {cell.cell_id}\n",
        )
        results.append(
            EvaluationCellResult.create(
                cell_id=cell.cell_id,
                proposal_sha256=plan.proposal_sha256,
                plan_sha256=plan.plan_sha256,
                cell_sha256=content_sha256(cell),
                resource_sha256=cell.resource.resource_sha256,
                status="succeeded",
                evidence_class=("synthetic" if cell.system_id == synthetic_system else "real"),
                usage=EvaluationCellUsage(
                    request_count=2,
                    input_tokens=1_000,
                    output_tokens=500,
                    api_cost=1.5,
                    wall_time_hours=0.2,
                    experiment_count=2,
                ),
                outcome=_outcome(),
                artifacts=(result_artifact,),
            )
        )
        if include_reviews:
            attestation = _artifact(
                root,
                f"reviews/{cell.review_blind_id}/attestation.json",
                f'{{"blind_id":"{cell.review_blind_id}"}}\n',
            )
            reviews.append(
                EvaluationBlindReview.create(
                    blind_id=cell.review_blind_id,
                    source="external",
                    reviewer_identity_hashes=("1" * 64, "2" * 64),
                    rubric_id="iclr-autoresearch-v1",
                    rubric_sha256=SHA,
                    criterion_scores={"scientific_quality": 0.8, "paper_quality": 0.75},
                    final_preference_score=0.78,
                    attestation=attestation,
                )
            )

    analysis_hash = content_sha256(manifest.analysis)
    comparisons = []
    for comparator in ("method-a", "method-b"):
        artifact = _artifact(
            root,
            f"analysis/scitaste-native-vs-{comparator}.json",
            f'{{"candidate":"scitaste-native","comparator":"{comparator}"}}\n',
        )
        comparisons.append(
            EvaluationPrimaryComparison.create(
                comparison_id=f"scitaste-native-vs-{comparator}",
                analysis_contract_sha256=analysis_hash,
                candidate_system_id="scitaste-native",
                comparator_system_id=comparator,
                analysis_unit_count=20,
                favorable_direction="higher",
                minimum_effect=0.05,
                effect_estimate=0.2,
                interval_lower=0.1,
                interval_upper=0.3,
                conclusion="supports_claim",
                analysis_artifact=artifact,
            )
        )
    return EvaluationResultSet.create(
        project_id="result-project",
        evaluation_id="formal-evaluation",
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_results=tuple(results),
        blind_reviews=tuple(reviews),
        primary_comparisons=tuple(comparisons),
    )


def _publish_formal_evaluation(
    runtime: ProjectRuntime,
    manifest: ExperimentPrelaunchManifest,
) -> None:
    plan = compile_evaluation_cell_plan(manifest)
    payloads = {
        "PRELAUNCH.yaml": yaml.safe_dump(
            manifest.model_dump(mode="json"), sort_keys=False
        ).encode(),
        "RESOURCE_CORPUS.yaml": b"schema_version: 'test'\nresources: []\n",
        "GATE_REPORT.json": b"{}\n",
        "CRITIC_REPORT.json": b"{}\n",
        "CELL_PLAN.json": (plan.model_dump_json(indent=2) + "\n").encode(),
    }
    names = {
        "prelaunch_manifest": "PRELAUNCH.yaml",
        "resource_corpus": "RESOURCE_CORPUS.yaml",
        "gate_report": "GATE_REPORT.json",
        "critic_report": "CRITIC_REPORT.json",
        "cell_plan": "CELL_PLAN.json",
    }
    files = {
        label: ProjectEvaluationArtifact(
            locator=locator,
            sha256=hashlib.sha256(payloads[locator]).hexdigest(),
            size_bytes=len(payloads[locator]),
        )
        for label, locator in names.items()
    }
    payload = {
        "schema_version": "1.0",
        "project_id": "result-project",
        "evaluation_id": "formal-evaluation",
        "manifest_id": manifest.manifest_id,
        "protocol_id": manifest.protocol_id,
        "study_scope": manifest.study_scope,
        "status": "execution_authorized",
        "proposal_sha256": manifest.proposal_sha256,
        "planned_cells": len(plan.cells),
        "system_ids": [item.system_id for item in manifest.systems],
        "task_ids": [item.task_id for item in manifest.tasks],
        "lane_ids": [item.lane_id for item in manifest.lanes],
        "api_resources": ["provider/frontier-model@frontier-model-2026-09-11"],
        "gpu_resources": [],
        "ready_for_author_review": True,
        "execution_authorized": True,
        "observed_source_commit": "0" * 40,
        "source_tree_clean": True,
        "readiness_blocker_codes": [],
        "authorization_blocker_codes": [],
        "critic_blocking_codes": [],
        "cell_plan_blockers": [],
        "files": {key: value.model_dump(mode="json") for key, value in files.items()},
        "no_execution_performed": True,
    }
    payload["bundle_sha256"] = content_sha256(payload)
    bundle = ProjectEvaluationBundle.model_validate(payload)
    runtime.publish_evaluation(
        "result-project",
        bundle,
        artifact_payloads=payloads,
        expected_revision=0,
    )


def _route_result_review(
    runtime: ProjectRuntime,
    *,
    expected_revision: int,
) -> tuple[object, str]:
    source_run_id = "result-review-source"
    snapshot = runtime.begin_run(
        "result-project",
        ProjectRun(
            run_id=source_run_id,
            provider="scitaste-native",
            model="deterministic-controller",
            condition="result-review-source",
            seed=0,
            status="complete",
            evidence_scope="test-only",
            stage_path="state",
        ),
        expected_revision=expected_revision,
    )
    source_state = ResearchState(
        project_id="result-project",
        research_direction="Test formal evidence closure.",
        target_domain="autonomous research",
    )
    source_locator = f"runs/{source_run_id}/state/research_state.json"
    source_path = runtime.projects_root / "result-project" / source_locator
    source_path.write_text(source_state.model_dump_json(indent=2) + "\n", encoding="utf-8")

    paper_directory = "review-paper-v1"
    paper_root = runtime.projects_root / "result-project" / "papers" / paper_directory
    paper_root.mkdir(parents=True)
    (paper_root / "main.md").write_text("# Formal result review\n", encoding="utf-8")
    snapshot = runtime.register_paper(
        "result-project",
        PaperManifest(
            paper_id=paper_directory,
            project_id="result-project",
            title="Formal result review",
            date="2026-09-11",
            provider="scitaste-native",
            model="deterministic-writer",
            condition="review-test",
            task="formal-result",
            seed=0,
            stage=17,
            status="venue-submission-draft",
            evidence_scope="test-only",
            files={"source-markdown": "main.md"},
            venue_id="iclr-2027",
            eligible_for_submission=True,
        ),
        directory_name=paper_directory,
        expected_revision=snapshot.revision,
    )
    snapshot, packet, _round = prepare_venue_review(
        runtime,
        project_id="result-project",
        paper_directory=paper_directory,
        review_id="formal-result-review",
        round_number=1,
        review_scope="development",
        venue_taste_profile=Path("configs/writing/venues/iclr-2027/taste.yaml"),
        expected_revision=snapshot.revision,
    )
    criteria = tuple(
        VenueCriterionAssessment(
            criterion=criterion,
            assessment="partially_satisfied",
            rationale="The formal result must be routed into the research state.",
        )
        for criterion in (
            "specific_question",
            "motivation_and_literature",
            "claim_support_and_rigor",
            "significance_and_community_value",
        )
    )
    concerns = (
        ReviewFeedback(
            concern_id="missing-effectiveness",
            category="missing_evidence",
            severity="high",
            text="Add formal comparative effectiveness evidence.",
            requires_new_evidence=True,
            requires_new_experiment=True,
        ),
        ReviewFeedback(
            concern_id="missing-external-baseline",
            category="missing_baseline",
            severity="high",
            text="Add real external method comparisons.",
            requires_new_evidence=True,
            requires_new_experiment=True,
        ),
        ReviewFeedback(
            concern_id="single-task-validity",
            category="validity",
            severity="high",
            text="Demonstrate validity across multiple held-out tasks.",
            requires_new_evidence=True,
            requires_new_experiment=True,
        ),
        ReviewFeedback(
            concern_id="title-overclaim",
            category="overclaim",
            severity="high",
            text="Keep the title claim bounded by the paper evidence.",
        ),
    )
    report = VenueReviewReport.create(
        report_id="formal-result-report",
        packet_sha256=packet.packet_sha256,
        review_scope="development",
        reviewer=ReviewerIdentity(
            reviewer_id="test-reviewer",
            reviewer_kind="internal_model",
            independent=False,
            conflict_status="unverified",
            provider="scripted",
            model_name="test-reviewer",
        ),
        summary="The paper needs formal result evidence and bounded claims.",
        strengths=("The scientific question is explicit.",),
        weaknesses=("The research state does not yet bind the formal result.",),
        criteria=criteria,
        initial_recommendation="reject",
        decision_reasons=("The evidence chain is incomplete.",),
        concerns=concerns,
        confidence="high",
    )
    snapshot, _round = import_venue_review_report(
        runtime,
        project_id="result-project",
        review_id="formal-result-review",
        report=report,
        expected_revision=snapshot.revision,
    )
    routing_run_id = "formal-result-obligations"
    prepared = prepare_project_review_routing(
        runtime,
        project_id="result-project",
        review_id="formal-result-review",
        report_id="formal-result-report",
        source_state_locator=source_locator,
        run_id=routing_run_id,
        source_commit="a" * 40,
        expected_revision=snapshot.revision,
    )
    snapshot, _routing = publish_project_review_routing(
        runtime,
        prepared=prepared,
        expected_revision=snapshot.revision,
    )
    return snapshot, routing_run_id


def test_formal_real_complete_results_establish_effectiveness(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _formal_manifest()
    plan = compile_evaluation_cell_plan(manifest)
    results = _result_set(root, manifest)

    assessment = inspect_evaluation_results(
        manifest,
        plan,
        results,
        project_root=root,
        project_id="result-project",
        evaluation_id="formal-evaluation",
        execution_authorized=True,
    )

    assert assessment.status == "complete"
    assert assessment.planned_cells == 4
    assert assessment.valid_external_reviews == 4
    assert assessment.required_primary_comparisons == 2
    assert assessment.valid_primary_comparisons == 2
    assert assessment.scientific_evidence_complete is True
    assert assessment.headline_eligible is True
    assert assessment.scientific_effectiveness_established is True
    assert assessment.blocker_codes == ()


def test_synthetic_or_unreviewed_results_cannot_support_headline_claim(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _formal_manifest()
    plan = compile_evaluation_cell_plan(manifest)
    results = _result_set(
        root,
        manifest,
        include_reviews=False,
        synthetic_system="method-a",
    )

    assessment = inspect_evaluation_results(
        manifest,
        plan,
        results,
        project_root=root,
        project_id="result-project",
        evaluation_id="formal-evaluation",
        execution_authorized=True,
    )

    assert assessment.status == "complete"
    assert assessment.scientific_evidence_complete is False
    assert assessment.scientific_effectiveness_established is False
    assert any(code.startswith("review:") for code in assessment.blocker_codes)
    assert any(code.endswith("real-evidence-required") for code in assessment.blocker_codes)


def test_review_using_a_different_rubric_cannot_support_headline_claim(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _formal_manifest()
    plan = compile_evaluation_cell_plan(manifest)
    results = _result_set(root, manifest)
    first = results.blind_reviews[0]
    mismatched = EvaluationBlindReview.create(
        blind_id=first.blind_id,
        source=first.source,
        reviewer_identity_hashes=first.reviewer_identity_hashes,
        rubric_id=first.rubric_id,
        rubric_sha256="b" * 64,
        criterion_scores=first.criterion_scores,
        final_preference_score=first.final_preference_score,
        conflict=first.conflict,
        adjudicated=first.adjudicated,
        attestation=first.attestation,
    )
    result_set = EvaluationResultSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=results.proposal_sha256,
        plan_sha256=results.plan_sha256,
        cell_results=results.cell_results,
        blind_reviews=(mismatched, *results.blind_reviews[1:]),
        primary_comparisons=results.primary_comparisons,
    )

    assessment = inspect_evaluation_results(
        manifest,
        plan,
        result_set,
        project_root=root,
        project_id="result-project",
        evaluation_id="formal-evaluation",
        execution_authorized=True,
    )

    assert assessment.scientific_evidence_complete is False
    assert f"review:{first.blind_id}:rubric-mismatch" in assessment.blocker_codes


def test_result_artifact_drift_invalidates_its_cell(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _formal_manifest()
    plan = compile_evaluation_cell_plan(manifest)
    results = _result_set(root, manifest)
    first = results.cell_results[0].artifacts[0]
    (root / first.locator).write_text("drift\n", encoding="utf-8")

    assessment = inspect_evaluation_results(
        manifest,
        plan,
        results,
        project_root=root,
        project_id="result-project",
        evaluation_id="formal-evaluation",
        execution_authorized=True,
    )

    assert assessment.status == "incomplete"
    assert assessment.invalid_cells == 1
    assert assessment.scientific_evidence_complete is False


def test_complete_gpu_robustness_results_do_not_become_headline_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _gpu_manifest()
    plan = compile_evaluation_cell_plan(manifest)
    cell_results = []
    for cell in plan.cells:
        artifact = _artifact(
            root,
            f"runs/gpu/{cell.cell_id}/paper.pdf",
            f"gpu paper for {cell.cell_id}\n",
        )
        cell_results.append(
            EvaluationCellResult.create(
                cell_id=cell.cell_id,
                proposal_sha256=plan.proposal_sha256,
                plan_sha256=plan.plan_sha256,
                cell_sha256=content_sha256(cell),
                resource_sha256=cell.resource.resource_sha256,
                status="succeeded",
                evidence_class="real",
                usage=EvaluationCellUsage(
                    gpu_hours=0.5,
                    wall_time_hours=0.5,
                    experiment_count=2,
                ),
                outcome=_outcome(),
                artifacts=(artifact,),
            )
        )
    results = EvaluationResultSet.create(
        project_id="result-project",
        evaluation_id="gpu-evaluation",
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_results=tuple(cell_results),
    )

    assessment = inspect_evaluation_results(
        manifest,
        plan,
        results,
        project_root=root,
        project_id="result-project",
        evaluation_id="gpu-evaluation",
        execution_authorized=True,
    )

    assert assessment.status == "complete"
    assert assessment.succeeded_cells == 2
    assert assessment.scientific_evidence_complete is False
    assert assessment.headline_eligible is False
    assert assessment.scientific_effectiveness_established is False
    assert "headline:formal-scope-required" in assessment.blocker_codes


def test_best_native_results_cannot_become_matched_backbone_headline_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = _best_native_formal_manifest()
    plan = compile_evaluation_cell_plan(manifest)
    results = _result_set(root, manifest)

    assessment = inspect_evaluation_results(
        manifest,
        plan,
        results,
        project_root=root,
        project_id="result-project",
        evaluation_id="formal-evaluation",
        execution_authorized=True,
    )

    assert assessment.status == "complete"
    assert assessment.matched_backbone_cells == 0
    assert assessment.scientific_evidence_complete is False
    assert assessment.headline_eligible is False
    assert assessment.scientific_effectiveness_established is False
    assert "headline:matched-backbone-lane-missing" in assessment.blocker_codes


def test_result_is_registered_under_project_and_revalidated_on_open(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="result-project",
            title="Result project",
            research_direction="Verify result-to-paper evidence.",
            status="active",
        )
    )
    manifest = _formal_manifest()
    _publish_formal_evaluation(runtime, manifest)
    project_root = runtime.projects_root / "result-project"
    results = _result_set(project_root, manifest)
    result_set_path = project_root / "runs/formal/RESULT_SET.json"
    result_set_path.parent.mkdir(parents=True, exist_ok=True)
    result_set_path.write_text(results.model_dump_json(indent=2) + "\n", encoding="utf-8")

    prepared = prepare_project_evaluation_result(
        runtime,
        project_id="result-project",
        result_id="formal-result-r1",
        evaluation_id="formal-evaluation",
        result_set_path=result_set_path,
    )
    snapshot = publish_project_evaluation_result(
        runtime,
        prepared,
        expected_revision=1,
        select=True,
    )

    assert snapshot.revision == 3
    assert snapshot.manifest.current_evaluation == "formal-evaluation"
    assert snapshot.manifest.current_evaluation_result == "formal-result-r1"
    assert snapshot.manifest.evaluation_results[0].headline_eligible is True
    assert snapshot.current_evaluation_result_locator == (
        "projects/result-project/evaluation-results/formal-result-r1"
    )
    reopened = runtime.open_evaluation_result("result-project", "formal-result-r1")
    assert reopened == prepared.bundle
    lifecycle = assess_project_lifecycle(runtime, "result-project")
    assert lifecycle.current_evaluation_result_id == "formal-result-r1"
    assert lifecycle.scientific_evidence_complete is True
    assert lifecycle.scientific_effectiveness_established is True
    assert lifecycle.paper_scientific_evidence_bound is False
    assert lifecycle.top_venue_evidence_loop_complete is False
    surface = WorkspaceSurfaceFactory(runtime).build(
        ProjectProgressQuery(project_id="result-project")
    )
    progress = next(
        item
        for item in surface.renderer.components
        if item.renderer == TrustedComponent.PROJECT_PROGRESS_BOARD
    ).data
    assert progress["counts"]["evaluation_results_registered"] == 1
    assert progress["evaluation_results"][0]["headline_eligible"] is True
    assert progress["lifecycle"]["scientific_evidence_complete"] is True
    assert (
        main(
            [
                "project",
                "evaluation",
                "result-status",
                "--project-id",
                "result-project",
                "--outputs-root",
                str(runtime.outputs_root),
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["revalidated"] is True
    assert status["result"]["scientific_effectiveness_established"] is True
    result_directory = project_root / "evaluation-results/formal-result-r1"
    assert {item.name for item in result_directory.iterdir()} == {
        "RESULT.json",
        "RESULT_SET.json",
        "ASSESSMENT.json",
    }

    first = results.cell_results[0].artifacts[0]
    (project_root / first.locator).write_text("drift\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"evidence (size|hash) mismatch"):
        runtime.open_evaluation_result("result-project", "formal-result-r1")


def test_result_set_must_be_project_owned(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="result-project",
            title="Result project",
            research_direction="Reject detached outcome files.",
            status="active",
        )
    )
    manifest = _formal_manifest()
    _publish_formal_evaluation(runtime, manifest)
    project_root = runtime.projects_root / "result-project"
    results = _result_set(project_root, manifest)
    detached = tmp_path / "detached.json"
    detached.write_text(json.dumps(results.model_dump(mode="json")), encoding="utf-8")

    with pytest.raises(ValueError, match="already belong"):
        prepare_project_evaluation_result(
            runtime,
            project_id="result-project",
            result_id="detached",
            evaluation_id="formal-evaluation",
            result_set_path=detached,
        )


def test_paper_binding_reverifies_selected_result_and_every_paper_artifact(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="result-project",
            title="Result project",
            research_direction="Bind exact scientific evidence into a paper.",
            status="active",
        )
    )
    manifest = _formal_manifest()
    _publish_formal_evaluation(runtime, manifest)
    project_root = runtime.projects_root / "result-project"
    results = _result_set(project_root, manifest)
    result_set_path = project_root / "runs/formal/RESULT_SET.json"
    result_set_path.parent.mkdir(parents=True, exist_ok=True)
    result_set_path.write_text(results.model_dump_json(indent=2) + "\n", encoding="utf-8")
    prepared = prepare_project_evaluation_result(
        runtime,
        project_id="result-project",
        result_id="formal-result-r1",
        evaluation_id="formal-evaluation",
        result_set_path=result_set_path,
    )
    snapshot = publish_project_evaluation_result(
        runtime,
        prepared,
        expected_revision=1,
        select=True,
    )

    paper_root = project_root / "papers/formal-paper-v1"
    paper_root.mkdir(parents=True)
    manuscript = paper_root / "main.md"
    manuscript.write_text("# Scientific Taste\n\nRegistered formal results.\n", encoding="utf-8")
    materialized = materialize_paper_scientific_evidence(
        runtime,
        project_id="result-project",
        paper_id="formal-paper-v1",
        result_id="formal-result-r1",
        paper_root=paper_root,
        artifact_paths=(manuscript,),
    )
    paper = PaperManifest(
        paper_id="formal-paper-v1",
        project_id="result-project",
        title="Scientific Taste",
        date="2026-09-11",
        provider="scitaste-native",
        model="deterministic-writer",
        condition="formal-result-bound-paper",
        task="heldout-task",
        seed=7,
        stage=18,
        status="venue-submission-draft",
        evidence_scope="formal-matched-backbone-result",
        files={
            "source-markdown": "main.md",
            "scientific-evidence-binding": materialized.path.name,
        },
        scientific_evidence=materialized.binding,
    )
    snapshot = runtime.register_paper(
        "result-project",
        paper,
        directory_name="formal-paper-v1",
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.select_paper(
        "result-project",
        "formal-paper-v1",
        expected_revision=snapshot.revision,
        global_latest=False,
    )

    assert runtime.open_paper("result-project", "formal-paper-v1") == paper
    lifecycle = assess_project_lifecycle(runtime, "result-project")
    assert lifecycle.scientific_evidence_complete is True
    assert lifecycle.paper_scientific_evidence_bound is True
    assert lifecycle.top_venue_evidence_loop_complete is False

    manuscript.write_text("# Drifted paper\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifacts differ"):
        runtime.open_paper("result-project", "formal-paper-v1")
    assert (
        assess_project_lifecycle(
            runtime,
            "result-project",
        ).paper_scientific_evidence_bound
        is False
    )


def test_selected_formal_result_closes_only_supported_review_obligations(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="result-project",
            title="Result project",
            research_direction="Verify result-to-review evidence.",
            status="active",
        )
    )
    manifest = _formal_manifest()
    _publish_formal_evaluation(runtime, manifest)
    project_root = runtime.projects_root / "result-project"
    results = _result_set(project_root, manifest)
    result_set_path = project_root / "runs/formal/RESULT_SET.json"
    result_set_path.parent.mkdir(parents=True, exist_ok=True)
    result_set_path.write_text(results.model_dump_json(indent=2) + "\n", encoding="utf-8")
    prepared_result = prepare_project_evaluation_result(
        runtime,
        project_id="result-project",
        result_id="formal-result-r1",
        evaluation_id="formal-evaluation",
        result_set_path=result_set_path,
    )
    snapshot = publish_project_evaluation_result(
        runtime,
        prepared_result,
        expected_revision=1,
        select=True,
    )
    snapshot, routing_run_id = _route_result_review(
        runtime,
        expected_revision=snapshot.revision,
    )

    prepared = prepare_project_evaluation_evidence(
        runtime,
        project_id="result-project",
        routing_run_id=routing_run_id,
        result_id="formal-result-r1",
        run_id="formal-result-evidence-v1",
        source_commit="b" * 40,
        expected_revision=snapshot.revision,
    )

    assert {item.evidence_type for item in prepared.bundle.evidence} == {
        "comparative effectiveness experiment",
        "matched external baseline comparison",
    }
    assert set(prepared.bundle.closed_obligation_ids) == {
        "obligation-missing-effectiveness",
        "obligation-missing-external-baseline",
    }
    assert set(prepared.bundle.remaining_open_obligation_ids) == {
        "obligation-single-task-validity",
        "obligation-title-overclaim",
    }
    assert runtime.open("result-project").revision == snapshot.revision

    published, bundle = publish_project_evaluation_evidence(
        runtime,
        prepared=prepared,
        expected_revision=snapshot.revision,
    )
    assert published.revision == snapshot.revision + 2
    assert (
        inspect_project_evaluation_evidence(
            runtime,
            "result-project",
            "formal-result-evidence-v1",
        )
        == bundle
    )
    run = next(item for item in published.manifest.runs if item.run_id == bundle.run_id)
    assert run.model_calls == 0
    assert run.status == "complete-evaluation-evidence-admitted"
    proofs = build_project_evaluation_closure_proofs(
        runtime,
        "result-project",
        "formal-result-evidence-v1",
    )
    assert {item.concern_id for item in proofs} == {
        "missing-effectiveness",
        "missing-external-baseline",
    }
    assert all(item.new_evidence[0].target_claim_ids == () for item in proofs)
    assert all(item.experiments[0].experiment_id == "formal-result-r1" for item in proofs)

    admitted = project_root / "runs/formal-result-evidence-v1/review_evidence/research_state.json"
    admitted.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="admitted ResearchState"):
        inspect_project_evaluation_evidence(
            runtime,
            "result-project",
            "formal-result-evidence-v1",
        )
