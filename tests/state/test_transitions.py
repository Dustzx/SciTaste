from __future__ import annotations

import pytest

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ProjectStatus, ResearchStage, ResearchState
from scitaste.state.transitions import TransitionError, apply_transition


def make_decision(state: ResearchState, action_type: MetaAction, suffix: str) -> ResearchDecision:
    action = ResearchAction(
        action_id=f"action-{suffix}",
        type=action_type,
        description=f"Apply {action_type.value}",
    )
    return ResearchDecision(
        decision_id=f"decision-{suffix}",
        stage=state.current_stage.value,
        state_snapshot_id=snapshot_id(state),
        candidate_actions=[action],
        selected_action=action,
        rationale="Test transition",
        confidence=0.8,
    )


def test_probe_and_pivot_are_nonlinear_and_audited(research_state: ResearchState) -> None:
    after_probe = apply_transition(
        research_state,
        make_decision(research_state, MetaAction.PROBE, "probe"),
    )
    after_pivot = apply_transition(
        after_probe,
        make_decision(after_probe, MetaAction.PIVOT, "pivot"),
    )

    assert research_state.revision == 0
    assert after_probe.current_stage == ResearchStage.DISCOVERY
    assert after_pivot.current_stage == ResearchStage.PROBLEM_FORMULATION
    assert [item.action_type for item in after_pivot.transition_history] == [
        MetaAction.PROBE,
        MetaAction.PIVOT,
    ]
    assert after_pivot.revision == 2
    assert len(after_pivot.decision_history) == 2


def test_stop_completes_and_prevents_more_transitions(research_state: ResearchState) -> None:
    completed = apply_transition(
        research_state,
        make_decision(research_state, MetaAction.STOP, "stop"),
    )

    assert completed.current_stage == ResearchStage.COMPLETE
    assert completed.status == ProjectStatus.COMPLETED
    with pytest.raises(TransitionError, match="completed"):
        apply_transition(completed, make_decision(completed, MetaAction.SEARCH, "late"))


def test_rejects_stale_and_duplicate_decisions(research_state: ResearchState) -> None:
    decision = make_decision(research_state, MetaAction.IDEATE, "idea")
    updated = apply_transition(research_state, decision)

    with pytest.raises(TransitionError, match="already applied"):
        apply_transition(
            updated.model_copy(update={"current_stage": ResearchStage.DISCOVERY}), decision
        )

    stale = make_decision(research_state, MetaAction.PROBE, "stale")
    with pytest.raises(TransitionError, match="does not match"):
        apply_transition(updated, stale)


def test_rejects_decision_for_an_old_snapshot(research_state: ResearchState) -> None:
    stale = make_decision(research_state, MetaAction.PROBE, "old-snapshot")
    changed = research_state.model_copy(update={"revision": 1})

    with pytest.raises(TransitionError, match="current state snapshot"):
        apply_transition(changed, stale)
