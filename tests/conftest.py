from __future__ import annotations

import pytest

from scitaste.state.research_state import ResearchState, ResourceBudget


@pytest.fixture
def research_state() -> ResearchState:
    return ResearchState(
        project_id="test-project",
        research_direction="Test reliable autonomous research decisions",
        target_domain="testing",
        resource_budget=ResourceBudget(
            gpu_hours=2.0,
            max_experiments=4,
            max_wall_time_hours=3.0,
            max_api_cost_usd=1.0,
        ),
    )
