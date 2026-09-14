"""Local-only structured generation for bounded model nodes."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Protocol

from scitaste.backends.base import Usage
from scitaste.backends.local_transformers import (
    LocalGeneration,
    LocalTransformersConfig,
    TransformersTextRuntime,
)
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse
from scitaste.model_nodes.openai_compatible import (
    StructuredBackendDisabledError,
    StructuredProviderResponseError,
    _parse_json_object,
    structured_model_messages,
)


class StructuredLocalGenerationRuntime(Protocol):
    """Minimal injected runtime used by the structured local backend."""

    def generate_messages(
        self,
        *,
        messages: list[dict[str, str]],
        seed: int,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> LocalGeneration: ...


class StructuredLocalTransformersBackend:
    """Run typed model-node proposals without network or provider-side tools.

    Every generation attempt is retained verbatim in ``raw_response``. If all
    bounded JSON-repair attempts fail, the backend returns an empty object so
    the model node can durably record a schema rejection instead of losing the
    generated evidence in an exception path.
    """

    def __init__(
        self,
        config: LocalTransformersConfig,
        *,
        runtime: StructuredLocalGenerationRuntime | None = None,
    ) -> None:
        values = config.model_dump(mode="python")
        self.config = LocalTransformersConfig.model_validate(values, strict=True)
        self.runtime = runtime or TransformersTextRuntime(self.config)
        self.name = self.config.provider
        self.model = self.config.model_identity

    def accept_campaign_checkpoint_verification(
        self,
        *,
        model_path: str | Path,
        checkpoint_sha256: str,
    ) -> None:
        """Delegate reuse of a campaign-scoped checkpoint verification receipt."""

        runtime = self.runtime
        if not isinstance(runtime, TransformersTextRuntime):
            raise ValueError("injected local runtimes cannot reuse campaign verification")
        runtime.accept_campaign_checkpoint_verification(
            model_path=model_path,
            checkpoint_sha256=checkpoint_sha256,
        )

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        if not self.config.execution_enabled:
            raise StructuredBackendDisabledError("local structured model backend is disabled")
        requested_output_tokens = (
            request.generation_envelope.max_output_tokens
            if request.generation_envelope is not None
            else self.config.max_new_tokens
        )
        if requested_output_tokens > self.config.max_new_tokens:
            raise StructuredBackendDisabledError(
                "profile output envelope exceeds the local generation ceiling"
            )

        messages = structured_model_messages(request)
        attempts: list[dict[str, object]] = []
        total_input_tokens = 0
        total_output_tokens = 0
        output_payload: dict[str, object] = {}
        accepted_attempt: int | None = None
        started = time.perf_counter()
        for attempt_index in range(self.config.max_retries + 1):
            generated = self.runtime.generate_messages(
                messages=messages,
                seed=request.seed,
                max_new_tokens=requested_output_tokens,
                temperature=0.0,
            )
            total_input_tokens += generated.input_tokens
            total_output_tokens += generated.output_tokens
            parse_error: str | None = None
            try:
                output_payload = _parse_json_object(generated.text)
                accepted_attempt = attempt_index
            except StructuredProviderResponseError as exc:
                parse_error = str(exc)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "text": generated.text,
                    "input_tokens": generated.input_tokens,
                    "output_tokens": generated.output_tokens,
                    "json_object_parsed": accepted_attempt == attempt_index,
                    "parse_error": parse_error,
                }
            )
            if accepted_attempt is not None:
                break
            if attempt_index < self.config.max_retries:
                messages = [
                    *messages,
                    {"role": "assistant", "content": generated.text},
                    {"role": "user", "content": _LOCAL_JSON_REPAIR_REMINDER},
                ]

        raw_response = json.dumps(
            {
                "schema_version": "1.0",
                "backend": self.name,
                "model": self.model,
                "accepted_attempt": accepted_attempt,
                "attempts": attempts,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=output_payload,
            backend=self.name,
            model=self.model,
            raw_response=raw_response,
            raw_response_sha256=hashlib.sha256(raw_response.encode()).hexdigest(),
            latency_ms=(time.perf_counter() - started) * 1000,
            usage=Usage(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=0.0,
            ),
            tool_calls=[],
            cached=False,
        )


_LOCAL_JSON_REPAIR_REMINDER = (
    "The previous response was not one valid JSON object. Return only one JSON object that "
    "validates against the output_schema already supplied. Do not add Markdown or commentary."
)


__all__ = [
    "StructuredLocalGenerationRuntime",
    "StructuredLocalTransformersBackend",
]
