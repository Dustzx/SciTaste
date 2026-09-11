from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    AnalysisContract,
    ApiModelResource,
    AutomatedJudgeRole,
    EvaluationCriticDomain,
    EvaluationCriticSuite,
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
    SystemRole,
    TaskSignalKind,
    inspect_prelaunch_manifest,
    load_external_resource_corpus,
    load_prelaunch_manifest,
)
from scitaste.evaluation.resources import ResourceGateStatus

CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v2.yaml")
V41_MANIFEST_PATH = Path("configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml")
CURRENT_CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v3.yaml")
PACKAGE_CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v4.yaml")
PACKAGE_MANIFEST_PATH = Path("configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v4.yaml")
OFFICIAL_CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v5.yaml")
OFFICIAL_MANIFEST_PATH = Path("configs/evaluation/prelaunch/deepseek_v4flash_package_pilot_v5.yaml")
GPU_INVENTORY_PATH = Path("docs/research/data/gpu_host_3090_2_inventory_v1.yaml")
CURRENT_MANIFEST_PATHS = (
    Path("configs/evaluation/prelaunch/deepseek_v41flash_pilot_v3.yaml"),
    Path("configs/evaluation/prelaunch/zhipu_glm53flash_pilot_v2.yaml"),
    Path("configs/evaluation/prelaunch/qwen3vl2b_8x3090_robustness_v2.yaml"),
)
HASH = "a" * 64
COMMIT = "b" * 40


def _admitted_corpus():
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    admitted = {"mlr-bench", "mlr-agent", "ai-scientist-v2"}
    resources = []
    for resource in corpus.resources:
        if resource.resource_id not in admitted:
            resources.append(resource)
            continue
        gates = {
            name: decision.model_copy(
                update={
                    "status": (
                        ResourceGateStatus.NOT_APPLICABLE
                        if decision.status is ResourceGateStatus.NOT_APPLICABLE
                        else ResourceGateStatus.VERIFIED
                    )
                }
            )
            for name, decision in resource.gates.items()
        }
        resources.append(resource.model_copy(update={"gates": gates}))
    return corpus.model_copy(update={"resources": tuple(resources)})


def _manifest(*, approval: PrelaunchApproval | None = None):
    corpus = _admitted_corpus()
    return ExperimentPrelaunchManifest(
        manifest_id="deepseek-pilot-v1",
        protocol_id="formal-v3-prepilot",
        protocol_version="1.0",
        study_scope="pilot",
        scientific_question="Does explicit taste improve a held-out research trajectory?",
        claim_allowed="Pilot feasibility only.",
        claim_forbidden="No comparative effectiveness claim.",
        source_commit=COMMIT,
        resource_corpus_sha256=corpus.semantic_sha256,
        systems=(
            PrelaunchSystem(
                system_id="scitaste-native",
                role=SystemRole.SCITASTE,
                implementation_ref=f"scitaste@{COMMIT}",
                availability=ReadinessStatus.VERIFIED,
                real_implementation=True,
            ),
            PrelaunchSystem(
                system_id="mlr-agent",
                role=SystemRole.METHOD_COMPARATOR,
                implementation_ref="mlr-agent@f728d571a992d71c8b526eeb4d9ab6bb5c8cc824",
                external_resource_id="mlr-agent",
                availability=ReadinessStatus.VERIFIED,
                real_implementation=True,
            ),
        ),
        tasks=(
            PrelaunchTask(
                task_id="mlr-heldout-001",
                benchmark_resource_id="mlr-bench",
                split="pilot-source-disjoint",
                selected_asset_manifest="assets/mlr-heldout-001.json",
                asset_manifest_sha256=HASH,
                license_status=ReadinessStatus.VERIFIED,
                asset_status=ReadinessStatus.VERIFIED,
                held_out=True,
                source_group_disjoint=True,
            ),
        ),
        lanes=(
            ExecutionLane(
                lane_id="deepseek-api",
                kind=ExecutionLaneKind.API_ONLY,
                scientific_role=ScientificLaneRole.MATCHED_BACKBONE,
                system_ids=("scitaste-native", "mlr-agent"),
                task_ids=("mlr-heldout-001",),
                seeds=(7,),
                planned_cells=2,
                api_model=ApiModelResource(
                    provider_id="deepseek",
                    endpoint="https://api.deepseek.com/chat/completions",
                    interface="openai-chat-completions",
                    model_id="deepseek-v4-flash",
                    model_revision="DeepSeek-V4-Flash-0731",
                    rolling_alias=True,
                    identity_source_url="https://api-docs.deepseek.com/",
                    identity_status=ReadinessStatus.VERIFIED,
                    api_key_env="DEEPSEEK_API_KEY",
                    max_input_tokens_per_call=100_000,
                    max_output_tokens_per_call=16_384,
                    max_requests=100,
                    max_total_tokens=1_000_000,
                    max_cost=10,
                    pricing=ProviderPricing(
                        currency="USD",
                        as_of=date(2026, 9, 10),
                        source_url="https://api-docs.deepseek.com/quick_start/pricing",
                        input_cache_hit_per_million=0.0028,
                        input_cache_miss_per_million=0.14,
                        output_per_million=0.28,
                        status=ReadinessStatus.VERIFIED,
                    ),
                ),
            ),
        ),
        human_review=HumanReviewResource(
            required=True,
            minimum_reviewers_per_artifact=2,
            condition_blinded=True,
            conflict_check_required=True,
            recruitment_status=ReadinessStatus.VERIFIED,
            rubric_status=ReadinessStatus.VERIFIED,
            adjudication_status=ReadinessStatus.VERIFIED,
            maximum_reviewer_hours=8,
        ),
        retention=RetentionContract(
            output_root="outputs/projects/scitaste-eval-formal-v3-prepilot",
            archive_root="archives/scitaste-eval-formal-v3-prepilot",
            maximum_output_bytes=10_000_000_000,
            retain_raw_provider_responses=True,
        ),
        launch_order=("deepseek-api",),
        stop_rules=("Stop on provider model drift.",),
        approval=approval or PrelaunchApproval(),
    )


def test_complete_manifest_is_ready_but_not_authorized() -> None:
    report = inspect_prelaunch_manifest(
        _manifest(),
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    assert report.ready_for_author_approval is True
    assert report.execution_authorized is False
    assert report.planned_cells == 2
    assert [item.code for item in report.authorization_blockers] == ["author_approval_required"]


def test_exact_hash_approval_authorizes_only_ready_manifest() -> None:
    proposal = _manifest()
    approved = _manifest(
        approval=PrelaunchApproval(
            approved=True,
            approved_proposal_sha256=proposal.proposal_sha256,
            approved_by="project-owner",
            approved_at="2026-09-10T12:00:00+08:00",
        )
    )

    report = inspect_prelaunch_manifest(
        approved,
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    assert report.execution_authorized is True
    changed = approved.model_copy(update={"protocol_version": "1.1"})
    drift = inspect_prelaunch_manifest(
        changed,
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )
    assert drift.execution_authorized is False
    assert "approval_hash_mismatch" in {item.code for item in drift.authorization_blockers}


def test_pending_assets_and_gpu_or_api_identity_fail_closed() -> None:
    manifest = _manifest()
    task = manifest.tasks[0].model_copy(update={"asset_status": ReadinessStatus.PENDING})
    api = manifest.lanes[0].api_model.model_copy(
        update={"identity_status": ReadinessStatus.BLOCKED}
    )
    lane = manifest.lanes[0].model_copy(update={"api_model": api})
    blocked = manifest.model_copy(update={"tasks": (task,), "lanes": (lane,)})

    report = inspect_prelaunch_manifest(
        blocked,
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    codes = {item.code for item in report.blockers}
    assert "task_assets_pending:mlr-heldout-001" in codes
    assert "api_identity_blocked:deepseek-api" in codes
    assert report.ready_for_author_approval is False


def test_gpu_critic_revalidates_content_bound_inventory_semantics() -> None:
    manifest = _manifest()
    inventory_sha256 = hashlib.sha256(GPU_INVENTORY_PATH.read_bytes()).hexdigest()
    gpu = GpuModelResource(
        host_alias="3090-2",
        device_count=7,
        device_name="NVIDIA GeForce RTX 3090",
        minimum_memory_mb_per_device=24_000,
        checkpoint_id="qwen3-vl-2b-instruct",
        checkpoint_source_path="/media/weights/Qwen3-VL-2B-Instruct",
        checkpoint_sha256=(
            "8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1"
        ),
        checkpoint_bytes=4_266_653_057,
        license_identifier="Apache-2.0",
        local_preflight_status=ReadinessStatus.VERIFIED,
        remote_inventory_status=ReadinessStatus.VERIFIED,
        remote_inventory_ref=GPU_INVENTORY_PATH.as_posix(),
        remote_inventory_sha256=inventory_sha256,
        remote_checkpoint_status=ReadinessStatus.PENDING,
        max_gpu_hours=1,
        max_storage_bytes=10_000_000_000,
    )
    lane = manifest.lanes[0].model_copy(
        update={"kind": ExecutionLaneKind.GPU, "api_model": None, "gpu_resource": gpu}
    )
    gpu_manifest = manifest.model_copy(update={"lanes": (lane,)})
    gate = inspect_prelaunch_manifest(
        gpu_manifest,
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    review = EvaluationCriticSuite().review(
        gpu_manifest,
        _admitted_corpus(),
        gate,
        evidence_root=Path("."),
    )
    finding = next(
        item for item in review.findings if item.domain is EvaluationCriticDomain.RESOURCES
    )

    assert "gpu_inventory_device_count_mismatch" in finding.message


def test_source_identity_and_cleanliness_are_observed_not_declared() -> None:
    manifest = _manifest()

    unobserved = inspect_prelaunch_manifest(manifest, _admitted_corpus())
    wrong = inspect_prelaunch_manifest(
        manifest,
        _admitted_corpus(),
        observed_source_commit="c" * 40,
        source_tree_clean=False,
    )

    assert {item.code for item in unobserved.blockers} >= {
        "source_commit_unobserved",
        "source_tree_unobserved",
    }
    assert {item.code for item in wrong.blockers} >= {
        "source_commit_mismatch",
        "source_tree_dirty",
    }


def test_method_and_benchmark_resources_cannot_be_swapped() -> None:
    manifest = _manifest()
    wrong = manifest.systems[1].model_copy(update={"external_resource_id": "mlr-bench"})
    report = inspect_prelaunch_manifest(
        manifest.model_copy(update={"systems": (manifest.systems[0], wrong)}),
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    assert any(
        "wrong_resource_kind:comparison_system_requires_system" in item.code
        for item in report.blockers
    )


def test_provider_alternatives_require_separate_manifests() -> None:
    manifest = _manifest()
    second_api = manifest.lanes[0].api_model.model_copy(update={"provider_id": "zhipu"})
    second_lane = manifest.lanes[0].model_copy(
        update={"lane_id": "zhipu-api", "api_model": second_api}
    )
    payload = manifest.model_dump(mode="json")
    payload["lanes"] = [
        manifest.lanes[0].model_dump(mode="json"),
        second_lane.model_dump(mode="json"),
    ]
    payload["launch_order"] = ["deepseek-api", "zhipu-api"]

    with pytest.raises(ValidationError, match="separate prelaunch manifests"):
        ExperimentPrelaunchManifest.model_validate(payload)


def _v11_manifest(*, endpoint: ScientificEndpointKind) -> ExperimentPrelaunchManifest:
    source = _manifest()
    task_signal = (
        TaskSignalKind.OBJECTIVE_SCORE
        if endpoint is ScientificEndpointKind.OBJECTIVE_PROGRESS
        else TaskSignalKind.RESEARCH_PACKAGE_REVIEW
    )
    return ExperimentPrelaunchManifest.model_validate(
        {
            **source.model_dump(mode="json"),
            "schema_version": "1.1",
            "primary_endpoint": endpoint.value,
            "automated_judge_role": AutomatedJudgeRole.SECONDARY_DIAGNOSTIC.value,
            "tasks": [
                {
                    **task.model_dump(mode="json"),
                    "signal_kind": task_signal.value,
                }
                for task in source.tasks
            ],
            "analysis": AnalysisContract(
                primary_outcome="A structurally matched primary endpoint.",
                estimand="A paired task-level contrast.",
                analysis_unit="One task-by-seed block.",
                aggregation_method="Average tasks equally.",
                uncertainty_method="Task-stratified paired bootstrap.",
            ).model_dump(mode="json"),
            "integrity": IntegrityContract(
                preregistration_ref="protocol.md",
                preregistration_sha256=HASH,
                task_freeze_ref="protocol.md",
                task_freeze_sha256=HASH,
                failure_policy_ref="protocol.md",
                failure_policy_sha256=HASH,
                repair_policy_ref="protocol.md",
                repair_policy_sha256=HASH,
                leakage_audit_ref="protocol.md",
                leakage_audit_sha256=HASH,
            ).model_dump(mode="json"),
        }
    )


def test_v11_machine_checks_objective_and_research_package_endpoints() -> None:
    objective = _v11_manifest(endpoint=ScientificEndpointKind.OBJECTIVE_PROGRESS)
    package = _v11_manifest(endpoint=ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE)

    assert objective.tasks[0].signal_kind is TaskSignalKind.OBJECTIVE_SCORE
    assert package.tasks[0].signal_kind is TaskSignalKind.RESEARCH_PACKAGE_REVIEW

    payload = package.model_dump(mode="json")
    payload["primary_endpoint"] = ScientificEndpointKind.OBJECTIVE_PROGRESS.value
    with pytest.raises(ValidationError, match="objective or mixed task signals"):
        ExperimentPrelaunchManifest.model_validate(payload)


def test_v11_blinded_package_endpoint_requires_humans_as_primary_judges() -> None:
    manifest = _v11_manifest(endpoint=ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE)
    payload = manifest.model_dump(mode="json")
    payload["human_review"] = {
        **payload["human_review"],
        "required": False,
        "minimum_reviewers_per_artifact": 0,
        "condition_blinded": False,
        "conflict_check_required": False,
    }
    with pytest.raises(ValidationError, match="independent human review"):
        ExperimentPrelaunchManifest.model_validate(payload)

    payload = manifest.model_dump(mode="json")
    payload["automated_judge_role"] = AutomatedJudgeRole.CALIBRATED_PRIMARY.value
    with pytest.raises(ValidationError, match="cannot replace"):
        ExperimentPrelaunchManifest.model_validate(payload)


def test_loader_preserves_bytes_and_rejects_symlink(tmp_path: Path) -> None:
    manifest = _manifest()
    path = tmp_path / "manifest.yaml"
    import yaml

    path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    loaded = load_prelaunch_manifest(path)
    link = tmp_path / "link.yaml"
    link.symlink_to(path)

    assert loaded.manifest.proposal_sha256 == manifest.proposal_sha256
    assert len(loaded.file_sha256) == 64
    with pytest.raises(ValueError, match="must not be a symlink"):
        load_prelaunch_manifest(link)


def test_repository_v41_proposal_preserves_new_identity_as_a_new_protocol() -> None:
    inspection = load_prelaunch_manifest(V41_MANIFEST_PATH)
    manifest = inspection.manifest
    model = manifest.lanes[0].api_model

    assert manifest.protocol_id == "formal-v4-prepilot"
    assert model is not None
    assert model.model_id == "deepseek-flash"
    assert model.model_revision == "DeepSeek-V4.1-Flash"
    assert model.pricing.input_cache_miss_per_million == 0.3
    assert model.pricing.output_per_million == 1.2
    assert len(manifest.tasks) == 10
    assert manifest.lanes[0].planned_cells == 50
    assert manifest.lanes[0].api_model.max_total_tokens == 15_000_000
    assert manifest.approval.approved is False


def test_current_proposals_bind_analysis_integrity_and_keep_execution_closed() -> None:
    corpus = load_external_resource_corpus(CURRENT_CORPUS_PATH).corpus
    expected_cells = {
        "deepseek-v41flash-pilot-v3": 100,
        "zhipu-glm53flash-pilot-v2": 100,
        "qwen3vl2b-8x3090-robustness-v2": 24,
    }

    for path in CURRENT_MANIFEST_PATHS:
        manifest = load_prelaunch_manifest(path).manifest
        gate = inspect_prelaunch_manifest(
            manifest,
            corpus,
            observed_source_commit=manifest.source_commit,
            source_tree_clean=True,
        )
        review = EvaluationCriticSuite().review(manifest, corpus, gate, evidence_root=".")

        assert gate.planned_cells == expected_cells[manifest.manifest_id]
        assert manifest.analysis is not None
        assert manifest.integrity is not None
        assert manifest.approval.approved is False
        assert gate.execution_authorized is False
        assert review.authorizes_execution is False
        assert "statistics:content_bound_analysis" not in review.blocking_codes
        assert "statistics:independent_replication" not in review.blocking_codes
        assert "integrity:frozen_temporal_integrity" not in review.blocking_codes


def test_current_api_headline_set_uses_accepted_methods_not_preprint_substitutes() -> None:
    accepted = {"mlr-agent", "agent-laboratory", "ai-researcher"}
    for path in CURRENT_MANIFEST_PATHS[:2]:
        manifest = load_prelaunch_manifest(path).manifest
        systems = {system.system_id for system in manifest.systems}

        assert systems == {"scitaste-native", "direct-agent", *accepted}
        assert systems.isdisjoint({"ai-scientist-v2", "autoresearchclaw"})
        assert sum(system.role is SystemRole.METHOD_COMPARATOR for system in manifest.systems) == 3


def test_package_preference_proposal_cannot_be_relabelled_as_objective_progress() -> None:
    manifest = load_prelaunch_manifest(OFFICIAL_MANIFEST_PATH).manifest
    corpus = load_external_resource_corpus(OFFICIAL_CORPUS_PATH).corpus
    gate = inspect_prelaunch_manifest(
        manifest,
        corpus,
        observed_source_commit=manifest.source_commit,
        source_tree_clean=True,
    )
    review = EvaluationCriticSuite().review(manifest, corpus, gate, evidence_root=".")

    assert manifest.schema_version == "1.1"
    assert manifest.primary_endpoint is ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE
    assert manifest.automated_judge_role is AutomatedJudgeRole.SECONDARY_DIAGNOSTIC
    assert all(
        task.signal_kind is TaskSignalKind.RESEARCH_PACKAGE_REVIEW for task in manifest.tasks
    )
    assert "objective progress" not in manifest.analysis.primary_outcome.lower()
    assert {system.system_id for system in manifest.systems} == {
        "scitaste-native",
        "direct-agent",
        "mlr-agent",
        "agent-laboratory",
        "tiny-scientist",
    }
    assert gate.planned_cells == 100
    assert gate.ready_for_author_approval is False
    assert gate.execution_authorized is False
    assert review.authorizes_execution is False
    assert any(
        "tiny-scientist:blocked_gate:code_license" in blocker.code for blocker in gate.blockers
    )


def test_official_deepseek_proposal_uses_documented_callable_identity_and_prices() -> None:
    manifest = load_prelaunch_manifest(OFFICIAL_MANIFEST_PATH).manifest
    model = manifest.lanes[0].api_model

    assert manifest.protocol_id == "formal-v5-package-prepilot"
    assert model is not None
    assert model.model_id == "deepseek-v4-flash"
    assert model.model_revision == "DeepSeek-V4-Flash-0731"
    assert model.pricing.input_cache_hit_per_million == 0.0028
    assert model.pricing.input_cache_miss_per_million == 0.14
    assert model.pricing.output_per_million == 0.28
    assert model.max_cost == 20.0
    assert manifest.approval.approved is False


def test_critics_expose_all_five_domains_without_authorizing_execution() -> None:
    manifest = _manifest()
    gate = inspect_prelaunch_manifest(
        manifest,
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    review = EvaluationCriticSuite().review(manifest, _admitted_corpus(), gate)

    assert {finding.domain for finding in review.findings} == set(EvaluationCriticDomain)
    assert review.ready_for_author_review is False
    assert review.authorizes_execution is False
    assert review.no_execution_performed is True
    assert set(review.blocking_codes) >= {
        "baseline_applicability:real_matched_comparators",
        "statistics:content_bound_analysis",
        "statistics:independent_replication",
        "integrity:frozen_temporal_integrity",
    }


def test_complete_critic_contract_is_review_ready_but_still_not_authority(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    artifact_bytes = b"content-bound prelaunch evidence\n"
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    artifact_paths = (
        "assets/mlr-heldout-001.json",
        "assets/mlr-heldout-002.json",
        "adapters/mlr-agent.json",
        "adapters/direct-agent.json",
        "adapters/ai-scientist-v2.json",
        "protocol/preregistration.md",
        "protocol/tasks.json",
        "protocol/failures.md",
        "protocol/repairs.md",
        "protocol/leakage.json",
        "protocol/judges.md",
    )
    for relative in artifact_paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact_bytes)
    mlr_agent = manifest.systems[1].model_copy(
        update={
            "adapter_preflight_ref": "adapters/mlr-agent.json",
            "adapter_preflight_sha256": artifact_sha256,
        }
    )
    direct = PrelaunchSystem(
        system_id="direct-agent",
        role=SystemRole.CONTROL,
        implementation_ref=f"scitaste-direct@{COMMIT}",
        availability=ReadinessStatus.VERIFIED,
        real_implementation=True,
        adapter_preflight_ref="adapters/direct-agent.json",
        adapter_preflight_sha256=artifact_sha256,
    )
    ai_scientist = PrelaunchSystem(
        system_id="ai-scientist-v2",
        role=SystemRole.METHOD_COMPARATOR,
        implementation_ref="ai-scientist-v2@96bd51617cfdbb494a9fc283af00fe090edfae48",
        external_resource_id="ai-scientist-v2",
        availability=ReadinessStatus.VERIFIED,
        real_implementation=True,
        adapter_preflight_ref="adapters/ai-scientist-v2.json",
        adapter_preflight_sha256=artifact_sha256,
    )
    first_task = manifest.tasks[0].model_copy(update={"asset_manifest_sha256": artifact_sha256})
    second_task = manifest.tasks[0].model_copy(
        update={
            "task_id": "mlr-heldout-002",
            "selected_asset_manifest": "assets/mlr-heldout-002.json",
            "asset_manifest_sha256": artifact_sha256,
        }
    )
    lane = manifest.lanes[0].model_copy(
        update={
            "system_ids": (
                "scitaste-native",
                "direct-agent",
                "mlr-agent",
                "ai-scientist-v2",
            ),
            "task_ids": ("mlr-heldout-001", "mlr-heldout-002"),
            "seeds": (7, 19),
            "planned_cells": 16,
        }
    )
    complete = manifest.model_copy(
        update={
            "systems": (manifest.systems[0], direct, mlr_agent, ai_scientist),
            "tasks": (first_task, second_task),
            "lanes": (lane,),
            "analysis": AnalysisContract(
                primary_outcome="Blinded evidence-bearing package quality.",
                estimand="Mean within-task Full SciTaste minus comparator difference.",
                analysis_unit="task-system-seed trajectory",
                aggregation_method="Hierarchical task-stratified mean difference.",
                uncertainty_method="Task-clustered bootstrap confidence interval.",
            ),
            "integrity": IntegrityContract(
                preregistration_ref="protocol/preregistration.md",
                preregistration_sha256=artifact_sha256,
                task_freeze_ref="protocol/tasks.json",
                task_freeze_sha256=artifact_sha256,
                failure_policy_ref="protocol/failures.md",
                failure_policy_sha256=artifact_sha256,
                repair_policy_ref="protocol/repairs.md",
                repair_policy_sha256=artifact_sha256,
                leakage_audit_ref="protocol/leakage.json",
                leakage_audit_sha256=artifact_sha256,
                judge_protocol_ref="protocol/judges.md",
                judge_protocol_sha256=artifact_sha256,
            ),
        }
    )
    gate = inspect_prelaunch_manifest(
        complete,
        _admitted_corpus(),
        observed_source_commit=COMMIT,
        source_tree_clean=True,
    )

    review = EvaluationCriticSuite().review(
        complete,
        _admitted_corpus(),
        gate,
        evidence_root=tmp_path,
    )

    assert gate.ready_for_author_approval is True
    assert gate.execution_authorized is False
    assert review.ready_for_author_review is True
    assert review.blocking_codes == ()
    assert review.authorizes_execution is False
