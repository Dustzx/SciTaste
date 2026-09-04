"""Provider-neutral contracts for bounded semantic model nodes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
    model_validator,
)

from scitaste.backends.base import Usage
from scitaste.schema.actions import MetaAction, ResearchAction


class ToolCallProposal(BaseModel):
    """A non-executable request for a deterministic caller to evaluate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ModelCostProvenance(BaseModel):
    """Auditable USD rates used to derive one provider response cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Literal["USD"] = "USD"
    input_usd_per_million_tokens: float = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million_tokens: float = Field(ge=0, allow_inf_nan=False)
    captured_at: datetime
    source: str = Field(min_length=1)

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class NodeContext(BaseModel):
    """Bounded projection of state made visible to one semantic node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    state_snapshot_id: str = Field(min_length=1)
    cumulative_api_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    candidate_actions: list[ResearchAction] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("claim_ids", "evidence_ids", "section_ids")
    @classmethod
    def references_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("context references must be unique")
        return sorted(values)

    @model_validator(mode="after")
    def candidate_action_ids_are_unique(self) -> NodeContext:
        action_ids = [action.action_id for action in self.candidate_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("context candidate action ids must be unique")
        return self


class NodePolicy(BaseModel):
    """Deterministic authority boundary for one model-node invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    enabled: bool = False
    allowed_node_names: list[str] = Field(default_factory=list)
    expected_backend: str = Field(min_length=1)
    expected_model: str = Field(min_length=1)
    allowed_tool_names: list[str] = Field(default_factory=list)
    allowed_action_types: list[MetaAction] = Field(default_factory=list)
    max_request_bytes: int = Field(default=100_000, ge=1)
    max_input_tokens: int = Field(default=20_000, ge=0)
    max_output_tokens: int = Field(default=4_000, ge=0)
    max_total_tokens: int = Field(default=24_000, ge=0)
    max_api_cost_usd: float = Field(default=0.15, ge=0, allow_inf_nan=False)
    max_latency_ms: float = Field(default=180_000, ge=0, allow_inf_nan=False)
    require_cost_telemetry: Literal[True] = True
    ambiguity_margin_max: float = Field(default=0.05, ge=0, allow_inf_nan=False)

    @field_validator("allowed_node_names", "allowed_tool_names")
    @classmethod
    def string_allowlists_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("policy allowlists must not contain duplicates")
        return sorted(values)

    @field_validator("allowed_action_types")
    @classmethod
    def action_allowlist_is_unique(cls, values: list[MetaAction]) -> list[MetaAction]:
        if len(values) != len(set(values)):
            raise ValueError("allowed_action_types must not contain duplicates")
        return sorted(values, key=lambda item: item.value)

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class StructuredModelRequest(BaseModel):
    """Complete, fingerprinted structured-generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    node_name: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    state_snapshot_id: str = Field(min_length=1)
    expected_backend: str = Field(min_length=1)
    expected_model: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_instruction: str = Field(min_length=1)
    input_payload: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    seed: int = 0
    prompt_version: str = Field(min_length=1)

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class StructuredModelResponse(BaseModel):
    """Parsed provider response plus mandatory reproducibility telemetry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_payload: JsonValue
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    raw_response: str | None = None
    raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    usage: Usage
    cost_provenance: ModelCostProvenance | None = None
    tool_calls: list[ToolCallProposal] = Field(default_factory=list)
    cached: bool = False

    @model_validator(mode="after")
    def raw_response_hash_matches(self) -> StructuredModelResponse:
        if self.raw_response is not None:
            observed = hashlib.sha256(self.raw_response.encode()).hexdigest()
            if observed != self.raw_response_sha256:
                raise ValueError("raw_response_sha256 does not match raw_response")
        return self


class NodeResultStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


ProposalT = TypeVar("ProposalT", bound=BaseModel)


class NodeResult(BaseModel, Generic[ProposalT]):
    """Auditable advice; never an execution authorization or state transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    node_name: str
    policy_id: str
    status: NodeResultStatus
    request: StructuredModelRequest
    response: StructuredModelResponse
    proposal: ProposalT | None = None
    untrusted_proposal: ProposalT | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    advisory_only: Literal[True] = True
    executable: Literal[False] = False

    @model_validator(mode="after")
    def status_matches_payload(self) -> NodeResult[ProposalT]:
        if self.status == NodeResultStatus.ACCEPTED:
            if (
                self.proposal is None
                or self.untrusted_proposal is not None
                or self.rejection_reasons
            ):
                raise ValueError("accepted node results require one clean proposal")
        else:
            if self.proposal is not None:
                raise ValueError("rejected node results cannot expose a trusted proposal")
            if not self.rejection_reasons:
                raise ValueError("rejected node results require at least one reason")
        return self
