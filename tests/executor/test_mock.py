from __future__ import annotations

from scitaste.executor.base import ExecutionStatus, ResearchExecutor
from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def test_mock_satisfies_protocol_and_is_deterministic(research_state: ResearchState) -> None:
    action = ResearchAction(
        action_id="probe-fixed",
        type=MetaAction.PROBE,
        description="Probe",
    )
    first = MockExecutor(seed=3)
    second = MockExecutor(seed=3)

    assert isinstance(first, ResearchExecutor)
    assert (
        first.probe(research_state, action).observations
        == second.probe(research_state, action).observations
    )


def test_mock_failure_is_explicit(research_state: ResearchState) -> None:
    action = ResearchAction(
        action_id="fail",
        type=MetaAction.EXPERIMENT,
        description="Fail safely",
        parameters={"force_failure": "synthetic fault"},
    )

    result = MockExecutor().run_experiment(research_state, action)

    assert result.status == ExecutionStatus.FAILED
    assert result.error == "synthetic fault"
