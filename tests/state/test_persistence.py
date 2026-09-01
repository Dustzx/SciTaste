from __future__ import annotations

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore, snapshot_id
from scitaste.state.research_state import ResearchState


def test_state_store_round_trip_and_content_addressing(
    tmp_path, research_state: ResearchState
) -> None:
    store = StateStore(tmp_path)
    first_id = store.save(research_state)
    second_id = store.save(research_state)

    assert first_id == second_id == snapshot_id(research_state)
    assert store.load() == research_state
    assert store.load(first_id) == research_state
    assert store.list_snapshots() == [first_id]


def test_decision_log_round_trip(tmp_path, research_state: ResearchState) -> None:
    action = ResearchAction(
        action_id="action-probe",
        type=MetaAction.PROBE,
        description="Probe uncertainty",
    )
    decision = ResearchDecision(
        decision_id="decision-probe",
        stage=research_state.current_stage.value,
        state_snapshot_id=snapshot_id(research_state),
        candidate_actions=[action],
        selected_action=action,
        rationale="Probe has high information value",
        confidence=0.9,
    )
    logger = DecisionLogger(tmp_path / "decisions.jsonl")
    logger.append(decision)

    assert logger.read_all() == [decision]
