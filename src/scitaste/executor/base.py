"""Framework-neutral interface for executing selected research actions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState


class ExecutionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PLANNED = "PLANNED"
    SKIPPED = "SKIPPED"


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_id: str = Field(default_factory=lambda: f"res-{uuid4().hex}")
    action_id: str
    status: ExecutionStatus
    executor: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observations: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    cost: dict[str, float] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class ResearchExecutor(Protocol):
    """The controller can depend on this protocol, never on substrate internals."""

    def execute(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def search(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def probe(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def implement(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def run_experiment(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def analyze(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def write(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...

    def generate_figure(self, state: ResearchState, action: ResearchAction) -> ExecutionResult: ...


def require_execution_success(result: ExecutionResult) -> None:
    """Prevent a failed/planned executor result from advancing canonical state."""

    if result.status != ExecutionStatus.SUCCEEDED:
        detail = f": {result.error}" if result.error else ""
        raise RuntimeError(
            f"executor {result.executor!r} returned {result.status.value} "
            f"for action {result.action_id!r}{detail}"
        )
