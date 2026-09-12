"""Stable model-backend contract independent of any API vendor."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from scitaste.schema.actions import ResearchAction


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class PreferenceRequest(BaseModel):
    """A fixed-candidate scientific-taste judgment request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    task: str
    stage: str
    decision_context: str = Field(min_length=1)
    candidate_actions: list[ResearchAction] = Field(min_length=2)
    seed: int = 0
    prompt_version: str = "intrinsic-v1"

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PreferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    request_fingerprint: str
    selected_action_id: str
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    backend: str
    model: str
    raw_response: str | None = None
    raw_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float | None = Field(default=None, ge=0)
    semantic_attempts: int = Field(default=1, ge=1)
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False


class GeneratedCandidateProposal(BaseModel):
    """One model proposal tied to a controller-owned executable template."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    template_action_id: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=1_000)
    parameter_overrides: dict[str, Any] = Field(default_factory=dict, max_length=8)
    rationale: str = Field(min_length=1, max_length=2_000)

    @field_validator("parameter_overrides")
    @classmethod
    def overrides_are_small_canonical_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        if any(not isinstance(key, str) or not key or len(key) > 100 for key in value):
            raise ValueError("candidate override keys must be bounded non-empty strings")
        try:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("candidate overrides must be finite JSON values") from exc
        if len(encoded) > 4_096:
            raise ValueError("candidate overrides exceed the byte ceiling")
        return value


class CandidateGenerationRequest(BaseModel):
    """Generate concrete candidates inside a fixed executable template set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=300)
    task: str = Field(min_length=1, max_length=300)
    stage: str = Field(min_length=1, max_length=100)
    decision_context: str = Field(min_length=1, max_length=64_000)
    action_templates: list[ResearchAction] = Field(min_length=2, max_length=12)
    seed: int = 0
    prompt_version: str = Field(default="native-candidate-generation-v1", min_length=1)

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class CandidateGenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: list[GeneratedCandidateProposal] = Field(min_length=2, max_length=12)
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    raw_response: str | None = None
    raw_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float | None = Field(default=None, ge=0)
    semantic_attempts: int = Field(default=1, ge=1)
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False


@runtime_checkable
class PreferenceBackend(Protocol):
    name: str

    def rank(self, request: PreferenceRequest) -> PreferenceResponse: ...


@runtime_checkable
class CandidateGenerationBackend(Protocol):
    name: str

    def generate_candidates(
        self,
        request: CandidateGenerationRequest,
    ) -> CandidateGenerationResponse: ...
