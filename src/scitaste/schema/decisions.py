"""Auditable research decision records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.schema.actions import ResearchAction


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchDecision(BaseModel):
    """Controller output and the unit of future taste memory."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: str = Field(default_factory=lambda: f"dec-{uuid4().hex}")
    timestamp: datetime = Field(default_factory=utc_now)
    stage: str
    state_snapshot_id: str
    candidate_actions: list[ResearchAction] = Field(min_length=1)
    retrieved_taste_cases: list[str] = Field(default_factory=list)
    selected_action: ResearchAction
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    expected_cost: dict[str, float] = Field(default_factory=dict)
    expected_value: dict[str, float] = Field(default_factory=dict)
    candidate_scores: dict[str, float | None] = Field(default_factory=dict)
    executor_result_id: str | None = None
    actual_outcome: dict[str, Any] | None = None

    @model_validator(mode="after")
    def selected_action_was_a_candidate(self) -> ResearchDecision:
        candidate_ids = {action.action_id for action in self.candidate_actions}
        if self.selected_action.action_id not in candidate_ids:
            raise ValueError("selected_action must belong to candidate_actions")
        return self
