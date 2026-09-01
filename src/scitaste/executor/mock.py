"""Deterministic executor for offline tests and control-loop demonstrations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState

MockHandler = Callable[[ResearchState, ResearchAction], ExecutionResult]


class MockExecutor:
    def __init__(
        self,
        *,
        seed: int = 0,
        handlers: dict[MetaAction, MockHandler] | None = None,
    ) -> None:
        self.seed = seed
        self.handlers = handlers or {}
        self.calls: list[str] = []

    def execute(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        self.calls.append(action.action_id)
        if handler := self.handlers.get(action.type):
            return handler(state, action)
        if action.parameters.get("force_failure"):
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                executor="mock",
                error=str(action.parameters.get("force_failure")),
            )
        observation = str(
            action.parameters.get(
                "observation",
                f"Deterministic mock observation {self._token(action.action_id)}",
            )
        )
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED,
            executor="mock",
            observations=[observation],
            cost=dict(action.expected_cost),
            data={
                "action_type": action.type.value,
                "observation": observation,
                "seed": self.seed,
            },
        )

    def search(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def probe(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def implement(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def run_experiment(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def analyze(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def write(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def generate_figure(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return self.execute(state, action)

    def _token(self, action_id: str) -> str:
        return hashlib.sha256(f"{self.seed}:{action_id}".encode()).hexdigest()[:10]
