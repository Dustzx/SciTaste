from __future__ import annotations

import pytest

from scitaste.executor import (
    ExecutionResult,
    ExecutionStatus,
    ResearchExecutor,
    SciTasteNativeExecutor,
    build_builtin_executor,
    require_execution_success,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def _state() -> ResearchState:
    return ResearchState(
        project_id="native-executor-test",
        research_direction="Exercise the first-party execution boundary",
        target_domain="autonomous-research",
    )


def test_native_executor_is_protocol_compatible_and_does_not_invent_observations() -> None:
    executor = SciTasteNativeExecutor()
    action = ResearchAction(
        action_id="native-control",
        type=MetaAction.FORMULATE_PROBLEM,
        description="Form a bounded problem from existing evidence",
    )

    result = executor.execute(_state(), action)

    assert isinstance(executor, ResearchExecutor)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.executor == "scitaste-native"
    assert result.observations == []
    assert result.data["capability"] == "control"
    assert result.data["result_basis"] == "workflow-component-receipt"


def test_native_executor_preserves_scenario_bound_observation_and_cost_basis() -> None:
    executor = SciTasteNativeExecutor()
    action = ResearchAction(
        action_id="native-probe",
        type=MetaAction.PROBE,
        description="Run a bounded diagnostic probe",
        parameters={"observation": "The effect persists under the matched control."},
        expected_cost={"wall_time_hours": 0.25},
    )

    result = executor.probe(_state(), action)

    assert result.observations == ["The effect persists under the matched control."]
    assert result.cost == {"wall_time_hours": 0.25}
    assert result.data["capability"] == "probing"
    assert result.data["cost_basis"] == "action-declared"


def test_native_executor_rejects_invalid_observation_without_advancing_authority() -> None:
    result = SciTasteNativeExecutor().execute(
        _state(),
        ResearchAction(
            action_id="invalid-native-probe",
            type=MetaAction.PROBE,
            description="Reject malformed action input",
            parameters={"observation": ""},
        ),
    )

    assert result.status == ExecutionStatus.FAILED
    with pytest.raises(RuntimeError, match="invalid-native-probe"):
        require_execution_success(result)


def test_native_handler_must_return_the_selected_action_identity() -> None:
    def mismatched(_state: ResearchState, _action: ResearchAction) -> ExecutionResult:
        return ExecutionResult(
            action_id="different-action",
            status=ExecutionStatus.SUCCEEDED,
            executor="fixture",
        )

    executor = SciTasteNativeExecutor(handlers={MetaAction.ANALYZE: mismatched})
    with pytest.raises(ValueError, match="does not match"):
        executor.analyze(
            _state(),
            ResearchAction(
                action_id="selected-analysis",
                type=MetaAction.ANALYZE,
                description="Analyze selected evidence",
            ),
        )


def test_builtin_executor_factory_keeps_mock_explicit() -> None:
    assert isinstance(build_builtin_executor("scitaste-native"), SciTasteNativeExecutor)
    assert build_builtin_executor("mock", seed=7).__class__.__name__ == "MockExecutor"
    with pytest.raises(ValueError, match="unsupported built-in executor"):
        build_builtin_executor("autoresearchclaw")
