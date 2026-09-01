from __future__ import annotations

import pytest

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.resources import ResourceBudgetExceededError, record_resource_usage
from scitaste.taste.controller import NoViableActionError, TasteController


def test_controller_uses_remaining_cumulative_budget(research_state) -> None:
    used = record_resource_usage(
        research_state,
        {"gpu_hours": 1.8, "experiments": 3.0, "wall_time_hours": 1.0},
    )
    next_experiment = ResearchAction(
        action_id="next-experiment",
        type=MetaAction.EXPERIMENT,
        description="One more expensive experiment",
        expected_cost={"gpu_hours": 0.3, "experiments": 2.0},
        expected_value={"information_gain": 1.0},
    )

    with pytest.raises(NoViableActionError, match=r"gpu_hours|experiments"):
        TasteController().decide(state=used, candidate_actions=[next_experiment])


def test_recording_cost_cannot_cross_total_budget(research_state) -> None:
    with pytest.raises(ResourceBudgetExceededError, match="gpu_hours"):
        record_resource_usage(research_state, {"gpu_hours": 2.1})
