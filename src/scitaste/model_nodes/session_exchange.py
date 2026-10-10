"""Input-bound session responses for real model nodes, without provider emulation."""

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scitaste.backends.base import Usage
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse


class SessionResponsePending(RuntimeError):
    """The request is retained; an external session must supply its response."""


class SessionBudgetExhausted(RuntimeError):
    """The original execution deadline expired; a response wait cannot renew it."""


def load_retained_request(path: Path) -> StructuredModelRequest:
    """Revalidate computed fingerprints instead of treating them as model inputs."""
    payload = json.loads(path.read_bytes())
    expected = payload.pop("fingerprint", None)
    request = StructuredModelRequest.model_validate(payload)
    if expected is not None and expected != request.fingerprint:
        raise ValueError("Retained model request fingerprint changed")
    return request


class SessionReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["assistant-session", "subagent-session"]
    author_reference: str = Field(min_length=1, max_length=500)
    declared_model_label: str | None = Field(default=None, max_length=200)
    output_payload: dict[str, JsonValue]

    @classmethod
    def from_proposal(
        cls,
        request: StructuredModelRequest,
        proposal: BaseModel,
        *,
        source: Literal["assistant-session", "subagent-session"],
        author_reference: str,
        declared_model_label: str | None = None,
    ) -> "SessionReply":
        """Serialize typed model advice without read-only computed receipt fields.

        Declared scientific fields remain untouched and downstream node admission
        still owns validation. This is for newly authored replies, not a repair of
        retained raw responses or a way to silently discard unknown input fields.
        """
        return cls(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            source=source,
            author_reference=author_reference,
            declared_model_label=declared_model_label,
            output_payload=proposal.model_dump(mode="json", exclude_computed_fields=True),
        )


def retain_session_pending(root: Path, request: str):
    """Append each wait and atomically advance the current pending pointer."""
    path = Path(request).resolve(strict=True)
    value = {"status": "awaiting-session-response", "request": str(path), "api_calls": 0}
    waits = root / "session_waits"
    waits.mkdir(exist_ok=True)
    retain_json(waits / path.name, value)
    with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False) as stream:
        json.dump(value, stream)
        temporary = stream.name
    os.replace(temporary, root / "SESSION_PENDING.json")


def retain_json(path: Path, value):
    """Allow exact continuation, never silently replace existing evidence."""
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        with path.open("x") as stream:
            stream.write(encoded)
    except FileExistsError:
        if json.loads(path.read_text()) != value:
            raise ValueError(f"Retained session artifact differs: {path.name}") from None


class SessionStructuredBackend:
    name = "assistant-session"
    model = "session-authored"

    session_enabled = True

    def __init__(
        self,
        directory: Path,
        *,
        wait_seconds: float = 0,
        max_requests: int = 100,
        deadline_monotonic: float | None = None,
    ):
        if wait_seconds < 0 or max_requests < 1:
            raise ValueError("Invalid session wait/request budget")
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.wait_seconds = wait_seconds
        self.max_requests = max_requests
        if deadline_monotonic is not None and not math.isfinite(deadline_monotonic):
            raise ValueError("Invalid session execution deadline")
        self.deadline_monotonic = deadline_monotonic

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        if (request.expected_backend, request.expected_model) != (self.name, self.model):
            raise ValueError("Session responses must not impersonate a provider/model")
        if self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic:
            raise SessionBudgetExhausted("No time remains for another model request")
        prefix = self.directory / request.fingerprint
        if (
            not prefix.with_suffix(".request.json").exists()
            and len(list(self.directory.glob("*.request.json"))) >= self.max_requests
        ):
            raise ValueError("Session request budget exhausted")
        retain_json(prefix.with_suffix(".request.json"), request.model_dump(mode="json"))
        reply_path = prefix.with_suffix(".reply.json")
        deadline = time.monotonic() + self.wait_seconds
        if self.deadline_monotonic is not None:
            deadline = min(deadline, self.deadline_monotonic)
        while not reply_path.exists() and time.monotonic() < deadline:
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        if self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic:
            raise SessionBudgetExhausted(str(prefix.with_suffix(".request.json")))
        if not reply_path.exists():
            raise SessionResponsePending(str(prefix.with_suffix(".request.json")))
        if reply_path.stat().st_size > 1_000_000:
            raise ValueError("Session reply exceeds one MB")
        reply = SessionReply.model_validate_json(reply_path.read_bytes())
        if reply.request_fingerprint != request.fingerprint:
            raise ValueError("Session reply refers to different inputs")
        if reply.request_id is not None and reply.request_id != request.request_id:
            raise ValueError("Session reply names a different request")
        raw = reply.model_dump_json()
        # Admission uses conservative byte bounds, NOT a fabricated tokenizer count.
        # Incremental API cost is exactly zero; session cost remains unknown below.
        bounds = Usage(
            input_tokens=len(request.model_dump_json().encode()),
            output_tokens=len(json.dumps(reply.output_payload, ensure_ascii=False).encode()),
            cost_usd=0,
        )
        response = StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=reply.output_payload,
            backend=self.name,
            model=self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=0,
            usage=bounds,
            session_provenance={
                "source": reply.source,
                "author_reference": reply.author_reference,
                "declared_model_label": reply.declared_model_label,
                "model_identity_verified": False,
                "actual_input_tokens": None,
                "actual_output_tokens": None,
                "session_cost_usd": None,
                "api_calls": 0,
                "usage_semantics": "conservative UTF-8 byte admission bounds; not actual tokens",
                "cost_semantics": "incremental API cost only; session cost unknown",
                "latency_semantics": "generation latency unavailable; no provider request",
            },
        )
        retain_json(prefix.with_suffix(".response.json"), response.model_dump(mode="json"))
        return response
