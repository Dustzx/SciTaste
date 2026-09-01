"""Stable model-backend contract independent of any API vendor."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, computed_field

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
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False


@runtime_checkable
class PreferenceBackend(Protocol):
    name: str

    def rank(self, request: PreferenceRequest) -> PreferenceResponse: ...
