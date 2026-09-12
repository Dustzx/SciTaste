from __future__ import annotations

import pytest

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import TasteController
from scitaste.taste.critics import StageTasteCriticSuite, TasteCriticDimension


def _state() -> ResearchState:
    return ResearchState(
        project_id="taste-critic-test",
        research_direction="Test scientific decision control",
        target_domain="testing",
    )


def test_stage_critics_expose_wrong_level_readiness_and_diagnosticity() -> None:
    state = _state()
    actions = (
        ResearchAction(
            action_id="probe",
            type=MetaAction.PROBE,
            description="Run a diagnostic probe",
            expected_value={"information_gain": 0.25},
        ),
        ResearchAction(
            action_id="commit",
            type=MetaAction.FORMULATE_PROBLEM,
            description="Commit before observing the system",
            expected_value={"information_gain": 1.0, "problem_validity": 1.0},
        ),
        ResearchAction(
            action_id="write",
            type=MetaAction.WRITE,
            description="Write before evidence exists",
        ),
    )

    findings = StageTasteCriticSuite().review(state, actions)

    assert {item.dimension for item in findings} >= {
        TasteCriticDimension.WRONG_LEVEL,
        TasteCriticDimension.READINESS,
        TasteCriticDimension.DIAGNOSTICITY,
    }
    assert {item.action_id for item in findings} >= {"commit", "write"}
    assert all(item.score_adjustment < 0 for item in findings)


def test_critics_change_selection_without_becoming_an_integrity_gate() -> None:
    state = _state()
    actions = [
        ResearchAction(
            action_id="probe",
            type=MetaAction.PROBE,
            description="Run a diagnostic probe",
            expected_value={"information_gain": 0.25},
        ),
        ResearchAction(
            action_id="commit",
            type=MetaAction.FORMULATE_PROBLEM,
            description="Commit before observing the system",
            expected_value={"information_gain": 1.0, "problem_validity": 1.0},
        ),
    ]

    control = TasteController(seed=7, critics_enabled=False).decide(
        state=state,
        candidate_actions=actions,
    )
    treated = TasteController(seed=7, critics_enabled=True).decide(
        state=state,
        candidate_actions=actions,
    )

    assert control.selected_action.action_id == "commit"
    assert treated.selected_action.action_id == "probe"
    assert treated.candidate_scores["commit"] is not None
    assert "diagnosticity:premature-commitment" in treated.rationale


def test_disabled_critics_reject_a_hidden_custom_suite() -> None:
    with pytest.raises(ValueError, match="requires critics_enabled"):
        TasteController(
            critics_enabled=False,
            critic_suite=StageTasteCriticSuite(),
        )
