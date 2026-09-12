"""Auditable research decision records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from scitaste.schema.actions import ResearchAction


def utc_now() -> datetime:
    return datetime.now(UTC)


class ModelDecisionUsage(BaseModel):
    """Bounded provider usage copied into the durable decision record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class ModelDecisionTrace(BaseModel):
    """Content identity for one model-backed fixed-candidate selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1)
    decision_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_action_ids: tuple[str, ...] = Field(min_length=1)
    candidate_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    selected_action_id: str = Field(min_length=1)
    response_raw_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float | None = Field(default=None, ge=0)
    semantic_attempts: int = Field(default=1, ge=1)
    usage: ModelDecisionUsage = Field(default_factory=ModelDecisionUsage)
    cached: bool = False

    @model_validator(mode="after")
    def selection_belongs_to_closed_candidates(self) -> ModelDecisionTrace:
        if len(set(self.candidate_action_ids)) != len(self.candidate_action_ids):
            raise ValueError("model decision candidate action IDs must be unique")
        if self.selected_action_id not in self.candidate_action_ids:
            raise ValueError("model decision selected action must be a candidate")
        return self


class ModelCandidateGenerationTrace(BaseModel):
    """Content identity for one model-backed candidate concretization call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1)
    decision_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_action_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    template_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_candidate_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    admitted_candidate_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_override_keys: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    proposal_rationales: dict[str, str] = Field(default_factory=dict)
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    response_raw_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float | None = Field(default=None, ge=0)
    semantic_attempts: int = Field(default=1, ge=1)
    usage: ModelDecisionUsage = Field(default_factory=ModelDecisionUsage)
    cached: bool = False

    @model_validator(mode="after")
    def admitted_candidates_preserve_template_identity(self) -> ModelCandidateGenerationTrace:
        if len(set(self.template_action_ids)) != len(self.template_action_ids):
            raise ValueError("candidate-generation template action IDs must be unique")
        if self.admitted_candidate_ids != self.template_action_ids:
            raise ValueError(
                "candidate generation must preserve template action identity and order"
            )
        if set(self.parameter_override_keys) - set(self.admitted_candidate_ids):
            raise ValueError("candidate override trace references an unknown admitted action")
        if set(self.proposal_rationales) != set(self.admitted_candidate_ids):
            raise ValueError("candidate-generation rationale coverage must be exact")
        return self


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
    model_candidate_generation: ModelCandidateGenerationTrace | None = None
    model_decision: ModelDecisionTrace | None = None
    executor_result_id: str | None = None
    actual_outcome: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def omit_absent_model_trace(self, handler: Any) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        if self.model_candidate_generation is None:
            payload.pop("model_candidate_generation", None)
        if self.model_decision is None:
            payload.pop("model_decision", None)
        return payload

    @model_validator(mode="after")
    def selected_action_was_a_candidate(self) -> ResearchDecision:
        candidate_ids = {action.action_id for action in self.candidate_actions}
        if self.selected_action.action_id not in candidate_ids:
            raise ValueError("selected_action must belong to candidate_actions")
        if (
            self.model_decision is not None
            and self.model_decision.selected_action_id != self.selected_action.action_id
        ):
            raise ValueError("model decision and selected action must agree")
        if self.model_candidate_generation is not None and not set(
            self.model_candidate_generation.admitted_candidate_ids
        ).issubset(candidate_ids):
            raise ValueError("model-generated candidates must belong to candidate_actions")
        return self
