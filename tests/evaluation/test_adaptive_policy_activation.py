from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.adaptive_policy_activation import (
    AdaptivePolicyActivationInspection,
    AdaptivePolicyActivationManifest,
    approve_adaptive_policy_activation,
    compile_adaptive_policy_activation_no_run_plan,
    initialize_adaptive_policy_activation_state,
    inspect_adaptive_policy_activation,
    load_adaptive_policy_activation_manifest,
)

MANIFEST = Path("configs/evaluation/taste_policy/adaptive_allocation_activation_v1.yaml")


def test_activation_manifest_closes_population_sampling_and_resource_arithmetic() -> None:
    manifest, digest = load_adaptive_policy_activation_manifest(MANIFEST)

    assert len(digest) == 64
    assert len(manifest.frozen_execution.tasks) == 9
    assert manifest.resource_ceiling.trajectory_count == 9
    assert manifest.resource_ceiling.api_calls == 81
    assert manifest.resource_ceiling.api_total_tokens == 1_080_000
    assert manifest.resource_ceiling.local_review_generations == 36
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
        exact_bindings_ready=True,
        predecessor_state_matches=True,
        program_and_limits_match=True,
        task_population_and_source_groups_match=True,
        checkout_matches_and_is_clean=True,
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
