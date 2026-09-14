from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scitaste.project import ProjectIdeaRevisionBinding
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.taste import (
    TasteEpisodePartition,
    TasteEpisodeSourceRelationship,
    TasteTrajectoryAssignmentTiming,
    TasteTrajectoryFollowup,
    TasteTrajectorySamplingPlan,
    reconstruct_taste_trajectory,
)


def _idea(*, revision_id: str = "taste-policy-candidate-01"):
    return ProjectIdeaRevisionBinding.create(
        project_id="trajectory-project",
        observed_project_revision=2,
        observed_project_snapshot_sha256="1" * 64,
        revision_id=revision_id,
        status="candidate",
        record_locator="runs/idea/idea_refinement/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=False,
        paper_claim_authority=False,
    )


def _plan(*, timing: TasteTrajectoryAssignmentTiming) -> TasteTrajectorySamplingPlan:
    return TasteTrajectorySamplingPlan.create(
        plan_id=f"trajectory-plan-{timing.value}",
        project_id="trajectory-project",
        observed_project_revision=3,
        observed_project_snapshot_sha256="4" * 64,
        idea_revision=_idea(),
        source_project_id="trajectory-project",
        source_run_id="source-run-01",
        source_relationship=TasteEpisodeSourceRelationship.SELF_PROJECT,
        source_group_id="source-run-01",
        dataset_partition=TasteEpisodePartition.DEVELOPMENT,
        assignment_timing=timing,
        decision_log_locator="stage/decisions.jsonl",
        state_snapshot_root_locator="stage",
        frozen_at=datetime(2026, 9, 14, tzinfo=UTC),
        source_absent_when_frozen=timing is TasteTrajectoryAssignmentTiming.PROSPECTIVE,
    )


def _source(
    root: Path,
    research_state,
    *,
    alternative_count: int = 2,
    save_state: bool = True,
) -> None:
    state = research_state.model_copy(update={"project_id": "trajectory-project"})
    state_id = StateStore(root / "stage").save(state) if save_state else "state-" + "5" * 64
    actions = [
        ResearchAction(
            action_id="probe-boundary",
            type=MetaAction.PROBE,
            description="Probe a decision-reversing uncertainty.",
        )
    ]
    if alternative_count == 2:
        actions.append(
            ResearchAction(
                action_id="scale-now",
                type=MetaAction.ADVANCE,
                description="Scale the current method immediately.",
            )
        )
    decision = ResearchDecision(
        decision_id="decision-01",
        timestamp=datetime(2026, 9, 14, 1, tzinfo=UTC),
        stage="DISCOVERY",
        state_snapshot_id=state_id,
        candidate_actions=actions,
        selected_action=actions[0],
        rationale="The probe can reverse the next decision.",
        confidence=0.8,
        executor_result_id="result-01",
        actual_outcome={"status": "SUCCEEDED", "observation": "probe executed"},
    )
    DecisionLogger(root / "stage" / "decisions.jsonl").append(decision)


def test_prospective_reconstruction_preserves_executor_outcome_without_label(
    tmp_path: Path,
    research_state,
) -> None:
    _source(tmp_path, research_state)

    inventory = reconstruct_taste_trajectory(
        _plan(timing=TasteTrajectoryAssignmentTiming.PROSPECTIVE),
        source_root=tmp_path,
        current_idea_revision=_idea(),
    )

    seed = inventory.decisions[0]
    assert inventory.foundation_eligible_count == 1
    assert inventory.scientific_outcome_labels_created is False
    assert inventory.policy_training_authorized is False
    assert seed.executor_status == "SUCCEEDED"
    assert seed.executor_outcome_sha256 is not None
    assert seed.delayed_scientific_outcome_bound is False
    assert seed.followup is TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME


def test_retrospective_source_is_audit_only_even_with_complete_execution(
    tmp_path: Path,
    research_state,
) -> None:
    _source(tmp_path, research_state)

    inventory = reconstruct_taste_trajectory(
        _plan(timing=TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT),
        source_root=tmp_path,
        current_idea_revision=_idea(),
    )

    assert inventory.foundation_eligible_count == 0
    assert inventory.decisions[0].followup is TasteTrajectoryFollowup.RETROSPECTIVE_AUDIT_ONLY
    assert inventory.decisions[0].finding_codes == ("retrospective-development-audit",)


def test_single_action_and_missing_state_remain_visible_but_ineligible(
    tmp_path: Path,
    research_state,
) -> None:
    _source(tmp_path, research_state, alternative_count=1, save_state=False)

    inventory = reconstruct_taste_trajectory(
        _plan(timing=TasteTrajectoryAssignmentTiming.PROSPECTIVE),
        source_root=tmp_path,
        current_idea_revision=_idea(),
    )

    assert inventory.multi_alternative_count == 0
    assert inventory.state_verified_count == 0
    assert inventory.foundation_eligible_count == 0
    assert inventory.decisions[0].followup is TasteTrajectoryFollowup.STATE_UNAVAILABLE
    assert set(inventory.decisions[0].finding_codes) == {
        "state-snapshot-missing",
        "decision-has-no-recorded-alternative",
    }


def test_changed_idea_invalidates_the_sampling_plan(tmp_path: Path, research_state) -> None:
    _source(tmp_path, research_state)

    with pytest.raises(ValueError, match="stale Idea revision"):
        reconstruct_taste_trajectory(
            _plan(timing=TasteTrajectoryAssignmentTiming.PROSPECTIVE),
            source_root=tmp_path,
            current_idea_revision=_idea(revision_id="taste-policy-candidate-02"),
        )
