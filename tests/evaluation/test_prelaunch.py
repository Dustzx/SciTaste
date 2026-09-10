from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    ApiModelResource,
    ExecutionLane,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    HumanReviewResource,
    PrelaunchApproval,
    PrelaunchSystem,
    PrelaunchTask,
    ProviderPricing,
    ReadinessStatus,
    RetentionContract,
    ScientificLaneRole,
    SystemRole,
    inspect_prelaunch_manifest,
    load_external_resource_corpus,
    load_prelaunch_manifest,
)
from scitaste.evaluation.resources import ResourceGateStatus

CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v2.yaml")
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
