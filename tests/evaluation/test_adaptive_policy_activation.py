from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.adaptive_policy_activation import (
    ActivationFileBinding,
    AdaptivePolicyActivationFinalizationResult,
    AdaptivePolicyActivationInspection,
    AdaptivePolicyActivationManifest,
    AdaptivePolicyActivationReviewResult,
    approve_adaptive_policy_activation,
    authorize_adaptive_policy_activation,
    compile_adaptive_policy_activation_no_run_plan,
    complete_adaptive_policy_activation_task,
    initialize_adaptive_policy_activation_state,
    inspect_adaptive_policy_activation,
    issue_adaptive_policy_activation_task,
    load_adaptive_policy_activation_manifest,
)
from scitaste.evaluation.interactive_development import InteractiveDevelopmentEpisodeBatch
from scitaste.evaluation.interactive_research import InteractiveResearchRunReceipt

MANIFEST = Path("configs/evaluation/taste_policy/adaptive_allocation_activation_v1.yaml")


def test_activation_manifest_closes_population_sampling_and_resource_arithmetic() -> None:
    manifest, digest = load_adaptive_policy_activation_manifest(MANIFEST)

    assert len(digest) == 64
    assert len(manifest.frozen_execution.tasks) == 9
    assert manifest.resource_ceiling.trajectory_count == 9
    assert manifest.resource_ceiling.api_calls == 81
    assert manifest.resource_ceiling.api_total_tokens == 1_080_000
    assert manifest.resource_ceiling.local_review_generations == 36
    assert manifest.review_and_admission.maximum_retries_per_generation == 0
    assert all(
        item.backend.locator.endswith("taste_review_activation_v1.yaml")
        for item in manifest.review_and_admission.attribution_primary_models
    )
    assert (
        manifest.episode_sampling.rule
        == "earliest-executed-nonterminal-decision-after-one-retained-observation"
    )
    assert manifest.authorizes_api_calls is False
    assert manifest.authorizes_gpu_work is False
    assert manifest.authorizes_benchmark_execution is False


def test_activation_inspection_fails_closed_without_bound_workspace(tmp_path: Path) -> None:
    manifest, digest = load_adaptive_policy_activation_manifest(MANIFEST)

    inspection = inspect_adaptive_policy_activation(
        manifest,
        manifest_file_sha256=digest,
        workspace_root=tmp_path,
    )
    plan = compile_adaptive_policy_activation_no_run_plan(manifest, inspection)
    state = initialize_adaptive_policy_activation_state(plan)

    assert inspection.ready_for_owner_approval is False
    assert "activation-binding-mismatch" in inspection.blocker_codes
    assert inspection.no_api_call_performed is True
    assert inspection.no_gpu_work_performed is True
    assert inspection.no_benchmark_execution_performed is True
    assert plan.ready_for_owner_approval is False
    assert plan.execution_authorized is False
    assert plan.owner_approval_required is True
    assert state.status == "awaiting-owner-approval"
    assert state.next_task_id == manifest.frozen_execution.tasks[0].task_id
    assert state.execution_authorized is False
    assert all(item.attempt_count == 0 for item in state.tasks)


def test_activation_rejects_resource_arithmetic_drift() -> None:
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    payload["resource_ceiling"]["api_calls"] -= 1

    with pytest.raises(ValidationError, match="API-call ceiling arithmetic differs"):
        AdaptivePolicyActivationManifest.model_validate(payload)


def test_activation_approval_requires_both_exact_confirmation_hashes() -> None:
    manifest, digest = load_adaptive_policy_activation_manifest(MANIFEST)
    inspection = AdaptivePolicyActivationInspection(
        campaign_id=manifest.campaign_id,
        manifest_file_sha256=digest,
        manifest_fingerprint=manifest.fingerprint,
        idea_revision_id="idea-v1",
        idea_scientific_contract_sha256="f" * 64,
        idea_scientific_contract_ready=True,
        exact_bindings_ready=True,
        predecessor_state_matches=True,
        program_and_limits_match=True,
        task_population_and_source_groups_match=True,
        checkout_matches_and_is_clean=True,
        review_runtime_and_authority_match=True,
        resource_arithmetic_closed=True,
        sampling_rule_closed=True,
        ready_for_owner_approval=True,
        blocker_codes=(),
    )
    plan = compile_adaptive_policy_activation_no_run_plan(manifest, inspection)

    with pytest.raises(ValueError, match="manifest confirmation hash mismatch"):
        approve_adaptive_policy_activation(
            manifest,
            plan,
            confirm_manifest_file_sha256="0" * 64,
            confirm_plan_sha256=plan.plan_sha256,
            approved_by="test-owner",
            approved_at=datetime.now(UTC),
        )


def test_exact_approval_authorizes_state_without_launching_work() -> None:
    manifest, digest = load_adaptive_policy_activation_manifest(MANIFEST)
    inspection = AdaptivePolicyActivationInspection(
        campaign_id=manifest.campaign_id,
        manifest_file_sha256=digest,
        manifest_fingerprint=manifest.fingerprint,
        idea_revision_id="idea-v1",
        idea_scientific_contract_sha256="f" * 64,
        idea_scientific_contract_ready=True,
        exact_bindings_ready=True,
        predecessor_state_matches=True,
        program_and_limits_match=True,
        task_population_and_source_groups_match=True,
        checkout_matches_and_is_clean=True,
        review_runtime_and_authority_match=True,
        resource_arithmetic_closed=True,
        sampling_rule_closed=True,
        ready_for_owner_approval=True,
        blocker_codes=(),
    )
    plan = compile_adaptive_policy_activation_no_run_plan(manifest, inspection)
    initial = initialize_adaptive_policy_activation_state(plan)
    approval = approve_adaptive_policy_activation(
        manifest,
        plan,
        confirm_manifest_file_sha256=digest,
        confirm_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=datetime.now(UTC),
    )

    authorized = authorize_adaptive_policy_activation(plan, approval, initial)

    assert authorized.sequence == 1
    assert authorized.status == "ready"
    assert authorized.approval_sha256 == approval.approval_sha256
    assert authorized.execution_authorized is True
    assert authorized.formal_effect_claim_authorized is False
    assert authorized.next_task_id == manifest.frozen_execution.tasks[0].task_id
    assert all(item.attempt_count == 0 for item in authorized.tasks)


def test_task_permit_retains_terminal_failure_and_advances_once() -> None:
    manifest, digest = load_adaptive_policy_activation_manifest(MANIFEST)
    inspection = AdaptivePolicyActivationInspection(
        campaign_id=manifest.campaign_id,
        manifest_file_sha256=digest,
        manifest_fingerprint=manifest.fingerprint,
        idea_revision_id="idea-v1",
        idea_scientific_contract_sha256="f" * 64,
        idea_scientific_contract_ready=True,
        exact_bindings_ready=True,
        predecessor_state_matches=True,
        program_and_limits_match=True,
        task_population_and_source_groups_match=True,
        checkout_matches_and_is_clean=True,
        review_runtime_and_authority_match=True,
        resource_arithmetic_closed=True,
        sampling_rule_closed=True,
        ready_for_owner_approval=True,
        blocker_codes=(),
    )
    plan = compile_adaptive_policy_activation_no_run_plan(manifest, inspection)
    approval = approve_adaptive_policy_activation(
        manifest,
        plan,
        confirm_manifest_file_sha256=digest,
        confirm_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=datetime.now(UTC),
    )
    authorized = authorize_adaptive_policy_activation(
        plan,
        approval,
        initialize_adaptive_policy_activation_state(plan),
    )

    permit, running = issue_adaptive_policy_activation_task(manifest, plan, approval, authorized)
    receipt = InteractiveResearchRunReceipt.create(
        project_id=manifest.project_id,
        run_id=permit.run_id,
        condition_id="development-foundation",
        task_id="newtonbench-runtime-task-id",
        environment_sha256="a" * 64,
        status="agent_failure",
        turns=(),
        experiment_count=0,
        code_call_count=0,
        input_tokens=0,
        output_tokens=0,
        api_cost_usd=None,
        terminal_error="provider returned no valid response",
    )
    batch = InteractiveDevelopmentEpisodeBatch.create(
        batch_id=f"{permit.run_id}-episodes",
        project_id=manifest.project_id,
        run_id=permit.run_id,
        task_id=receipt.task_id,
        source_group_id=permit.source_group_id,
        protocol_sha256="b" * 64,
        sampling_plan_sha256="c" * 64,
        receipt_sha256=receipt.receipt_sha256,
        items=(),
    )

    advanced = complete_adaptive_policy_activation_task(
        manifest,
        plan,
        approval,
        running,
        permit,
        receipt,
        batch,
        new_disk_bytes=1024,
    )

    assert running.status == "running"
    assert running.tasks[0].attempt_count == 1
    assert advanced.status == "ready"
    assert advanced.tasks[0].status == "retained-failure"
    assert advanced.next_task_id == manifest.frozen_execution.tasks[1].task_id
    assert advanced.completed_trajectory_count == 1
    assert advanced.consumed_api_calls == 1
    assert advanced.consumed_api_tokens == permit.maximum_api_tokens
    assert advanced.consumed_new_disk_bytes == 1024
    assert advanced.terminal_evidence[0].receipt_sha256 == receipt.receipt_sha256

    with pytest.raises(ValueError, match="active permit"):
        complete_adaptive_policy_activation_task(
            manifest,
            plan,
            approval,
            advanced,
            permit,
            receipt,
            batch,
            new_disk_bytes=1024,
        )


def test_review_result_counts_failed_generation_without_fabricating_review() -> None:
    result = AdaptivePolicyActivationReviewResult.create(
        permit_sha256="a" * 64,
        task_id="task-one",
        run_id="run-one",
        candidate_sha256="b" * 64,
        status="runtime-failure",
        local_generation_count=1,
        local_gpu_hours=0.01,
        new_disk_bytes=100,
        attribution_reviews=(),
        family_reviews=(),
        failure_reason="local generation failed before an accepted review artifact",
    )

    assert result.retry_count == 0
    assert result.replacement_performed is False
    assert result.local_generation_count == 1

    with pytest.raises(ValidationError, match="generation count differs"):
        AdaptivePolicyActivationReviewResult.create(
            permit_sha256="a" * 64,
            task_id="task-one",
            run_id="run-one",
            candidate_sha256="b" * 64,
            status="policy-eligible",
            local_generation_count=4,
            local_gpu_hours=0.01,
            new_disk_bytes=100,
            attribution_reviews=(),
            family_reviews=(),
        )


def test_finalization_keeps_insufficient_policy_separate_from_effect_claim() -> None:
    binding = ActivationFileBinding(locator="outputs/evidence.json", sha256="c" * 64)
    result = AdaptivePolicyActivationFinalizationResult.create(
        campaign_id="activation-v1",
        project_id="scitaste-self-development",
        plan_sha256="a" * 64,
        preceding_state_sha256="b" * 64,
        successor_policy_id="policy-v7",
        target_e2_manifest_id="e2-v5",
        target_e2_manifest_sha256="d" * 64,
        activation_episode_count=0,
        total_corpus_episode_count=4,
        corpus=binding,
        policy_config=binding,
        refresh_receipt=binding,
        policy=binding,
        readiness=binding,
        adaptive_family_support_sufficient=False,
        adaptive_head_ready=False,
        policy_refresh_status="insufficient-support",
        target_domain_state_probe_status="not-run-insufficient-support",
        activation_ready_for_e2_development=False,
    )

    assert result.no_model_calls_performed is True
    assert result.formal_effect_claim_established is False
