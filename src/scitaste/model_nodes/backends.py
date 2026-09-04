"""Offline and protocol definitions for structured model generation."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scitaste.backends.base import Usage
from scitaste.model_nodes.models import (
    StructuredModelRequest,
    StructuredModelResponse,
    ToolCallProposal,
)


@runtime_checkable
class StructuredModelBackend(Protocol):
    """A provider-neutral structured-generation boundary."""

    name: str
    model: str

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse: ...


class ScriptedStructuredReply(BaseModel):
    """Deterministic test reply with explicit resource telemetry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_payload: JsonValue
    usage: Usage = Field(default_factory=lambda: Usage(cost_usd=0.0))
    latency_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    tool_calls: list[ToolCallProposal] = Field(default_factory=list)
    response_backend: str | None = None
    response_model: str | None = None


class ScriptedStructuredBackend:
    """Return declared responses without network access or provider fallback."""

    def __init__(
        self,
        *,
        name: str,
        model: str,
        replies: dict[str, ScriptedStructuredReply],
    ) -> None:
        self.name = name
        self.model = model
        self.replies = dict(replies)
        self.calls: list[StructuredModelRequest] = []

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.calls.append(request)
        try:
            reply = self.replies[request.request_id]
        except KeyError as exc:
            raise KeyError(f"no scripted reply for request {request.request_id!r}") from exc
        raw = json.dumps(
            {
                "output_payload": reply.output_payload,
                "tool_calls": [item.model_dump(mode="json") for item in reply.tool_calls],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=reply.output_payload,
            backend=reply.response_backend or self.name,
            model=reply.response_model or self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=reply.latency_ms,
            usage=reply.usage,
            tool_calls=reply.tool_calls,
        )
