from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scitaste.evaluation.adaptive_policy_activation import (
    AdaptivePolicyActivationInspection,
    approve_adaptive_policy_activation,
    authorize_adaptive_policy_activation,
    close_adaptive_policy_activation_empty_review,
    compile_adaptive_policy_activation_no_run_plan,
    complete_adaptive_policy_activation_task,
    initialize_adaptive_policy_activation_state,
    issue_adaptive_policy_activation_task,
    load_adaptive_policy_activation_manifest,
    save_adaptive_policy_activation_artifact,
)
from scitaste.evaluation.adaptive_policy_campaign import (
    AdaptivePolicyActivationAction,
    AdaptivePolicyActivationJournal,
    next_adaptive_policy_activation_action,
)
from scitaste.evaluation.interactive_development import InteractiveDevelopmentEpisodeBatch
from scitaste.evaluation.interactive_research import InteractiveResearchRunReceipt

MANIFEST = Path("configs/evaluation/taste_policy/adaptive_allocation_activation_v1.yaml")


def _authorized_campaign():
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
    state = authorize_adaptive_policy_activation(
        plan,
        approval,
        initialize_adaptive_policy_activation_state(plan),
    )
    return manifest, plan, approval, state


def test_campaign_closes_a_zero_candidate_cohort_without_review_generation() -> None:
    manifest, plan, approval, state = _authorized_campaign()

    for _ in manifest.frozen_execution.tasks:
        permit, running = issue_adaptive_policy_activation_task(manifest, plan, approval, state)
        receipt = InteractiveResearchRunReceipt.create(
            project_id=manifest.project_id,
            run_id=permit.run_id,
            condition_id="development-foundation",
            task_id=permit.task_id,
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
            task_id=permit.task_id,
            source_group_id=permit.source_group_id,
            protocol_sha256="b" * 64,
            sampling_plan_sha256="c" * 64,
            receipt_sha256=receipt.receipt_sha256,
            items=(),
        )
        state = complete_adaptive_policy_activation_task(
            manifest,
            plan,
            approval,
            running,
            permit,
            receipt,
            batch,
            new_disk_bytes=0,
        )

    assert state.status == "trajectory-complete"
    assert (
        next_adaptive_policy_activation_action(state)
        is AdaptivePolicyActivationAction.CLOSE_EMPTY_REVIEW
    )

    closed = close_adaptive_policy_activation_empty_review(manifest, plan, approval, state)

    assert closed.status == "review-complete"
    assert closed.review_evidence == ()
    assert closed.consumed_local_review_generations == 0
    assert next_adaptive_policy_activation_action(closed) is AdaptivePolicyActivationAction.FINALIZE


def test_campaign_journal_recovers_a_sealed_pending_runner_state(tmp_path: Path) -> None:
    manifest, plan, approval, state = _authorized_campaign()
    journal = AdaptivePolicyActivationJournal(tmp_path / "journal")
    journal.bootstrap(state)
    permit, running = issue_adaptive_policy_activation_task(manifest, plan, approval, state)
    journal.save_task_permit(permit)
    pending = journal.state_output_path(running.sequence, running.status)
    save_adaptive_policy_activation_artifact(running, pending)

    resumed_journal = AdaptivePolicyActivationJournal(tmp_path / "journal")
    resumed = resumed_journal.bootstrap(state)
    permit_path, recovered_permit = resumed_journal.active_task_permit(resumed)

    assert resumed == running
    assert permit_path.is_file()
    assert recovered_permit == permit
    assert not pending.exists()
    assert (
        next_adaptive_policy_activation_action(resumed)
        is AdaptivePolicyActivationAction.EXECUTE_TASK
    )
