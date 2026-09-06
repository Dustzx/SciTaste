"""First-party execution boundary for SciTaste-owned workflow components."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState

NativeHandler = Callable[[ResearchState, ResearchAction], ExecutionResult]


class NativeCapability(StrEnum):
    """Auditable capability families implemented by the first-party executor."""

    RETRIEVAL = "retrieval"
    PROBING = "probing"
    EXPERIMENT = "experiment"
    ANALYSIS = "analysis"
    WRITING = "writing"
    FIGURE = "figure"
    CONTROL = "control"


_CAPABILITIES: dict[MetaAction, NativeCapability] = {
    MetaAction.SEARCH: NativeCapability.RETRIEVAL,
    MetaAction.PROBE: NativeCapability.PROBING,
    MetaAction.RE_PROBE: NativeCapability.PROBING,
    MetaAction.PILOT: NativeCapability.EXPERIMENT,
    MetaAction.EXPERIMENT: NativeCapability.EXPERIMENT,
    MetaAction.COLLECT_EVIDENCE: NativeCapability.EXPERIMENT,
    MetaAction.REPRODUCE: NativeCapability.EXPERIMENT,
    MetaAction.ADD_EXPERIMENT: NativeCapability.EXPERIMENT,
    MetaAction.ADD_BASELINE: NativeCapability.EXPERIMENT,
    MetaAction.ANALYZE: NativeCapability.ANALYSIS,
    MetaAction.ADD_ANALYSIS: NativeCapability.ANALYSIS,
    MetaAction.WRITE: NativeCapability.WRITING,
    MetaAction.BUILD_STORY: NativeCapability.WRITING,
    MetaAction.RESPOND: NativeCapability.WRITING,
    MetaAction.CLARIFY_EXISTING_TEXT: NativeCapability.WRITING,
    MetaAction.CITE_EXISTING_EVIDENCE: NativeCapability.WRITING,
    MetaAction.ACKNOWLEDGE_LIMITATION: NativeCapability.WRITING,
    MetaAction.CORRECT_ERROR: NativeCapability.WRITING,
    MetaAction.REJECT_CONCERN_WITH_EVIDENCE: NativeCapability.WRITING,
    MetaAction.DEFER_FUTURE_WORK: NativeCapability.WRITING,
    MetaAction.DESIGN_FIGURE: NativeCapability.FIGURE,
}


class SciTasteNativeExecutor:
    """Dispatch selected actions to SciTaste-owned in-process capabilities.

    The Phase 4--7 workflow components currently perform their bounded domain
    operation immediately around this execution boundary. This executor emits a
    truthful receipt for that first-party operation and never fabricates a mock
    observation. Action-specific handlers can replace a capability incrementally
    as open-ended retrieval, sandbox, and generation implementations are added.
    """

    name = "scitaste-native"

    def __init__(
        self,
        *,
        handlers: dict[MetaAction, NativeHandler] | None = None,
    ) -> None:
        self.handlers = handlers or {}
        self.calls: list[str] = []

    def execute(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        self.calls.append(action.action_id)
        if handler := self.handlers.get(action.type):
            result = handler(state, action)
            if result.action_id != action.action_id:
                raise ValueError(
                    "native handler result action_id does not match the selected action"
                )
            return result
        return self._complete(state, action, capability=_capability_for(action.type))

    def search(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.RETRIEVAL)

    def probe(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.PROBING)

    def implement(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.CONTROL)

    def run_experiment(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.EXPERIMENT)

    def analyze(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.ANALYSIS)

    def write(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.WRITING)

    def generate_figure(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self._direct(state, action, NativeCapability.FIGURE)

    def _direct(
        self,
        state: ResearchState,
        action: ResearchAction,
        capability: NativeCapability,
    ) -> ExecutionResult:
        self.calls.append(action.action_id)
        if handler := self.handlers.get(action.type):
            result = handler(state, action)
            if result.action_id != action.action_id:
                raise ValueError(
                    "native handler result action_id does not match the selected action"
                )
            return result
        return self._complete(state, action, capability=capability)

    @staticmethod
    def _complete(
        state: ResearchState,
        action: ResearchAction,
        *,
        capability: NativeCapability,
    ) -> ExecutionResult:
        raw_observation = action.parameters.get("observation")
        if raw_observation is not None and (
            not isinstance(raw_observation, str) or not raw_observation.strip()
        ):
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor=SciTasteNativeExecutor.name,
                error="native action observation must be a non-empty string",
                data={
                    "action_type": action.type.value,
                    "capability": capability.value,
                    "execution_mode": "first-party-in-process",
                    "state_revision_before": state.revision,
                },
            )
        observations = [raw_observation.strip()] if isinstance(raw_observation, str) else []
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED,
            executor=SciTasteNativeExecutor.name,
            observations=observations,
            cost=dict(action.expected_cost),
            data={
                "action_type": action.type.value,
                "capability": capability.value,
                "execution_mode": "first-party-in-process",
                "result_basis": (
                    "scenario-declared-observation"
                    if observations
                    else "workflow-component-receipt"
                ),
                "cost_basis": "action-declared",
                "state_revision_before": state.revision,
            },
        )


def build_builtin_executor(name: str, *, seed: int = 0):
    """Build a dependency-free executor used by the integrated workflow."""

    if name == SciTasteNativeExecutor.name:
        return SciTasteNativeExecutor()
    if name == "mock":
        from scitaste.executor.mock import MockExecutor

        return MockExecutor(seed=seed)
    raise ValueError(f"unsupported built-in executor {name!r}")


def _capability_for(action_type: MetaAction) -> NativeCapability:
    return _CAPABILITIES.get(action_type, NativeCapability.CONTROL)


__all__ = [
    "NativeCapability",
    "NativeHandler",
    "SciTasteNativeExecutor",
    "build_builtin_executor",
]
