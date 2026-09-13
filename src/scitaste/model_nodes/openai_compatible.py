"""Live OpenAI-compatible Chat Completions backend for bounded model nodes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scitaste.backends.base import Usage
from scitaste.model_nodes.models import (
    ModelCostProvenance,
    StructuredModelRequest,
    StructuredModelResponse,
    ToolCallProposal,
)


class StructuredBackendDisabledError(RuntimeError):
    """Raised before transport access when live structured calls are disabled."""


class StructuredProviderResponseError(ValueError):
    """Raised when a provider response cannot satisfy the bounded contract."""


class StructuredHTTPResponse(BaseModel):
    """Parsed JSON plus the exact decoded HTTP response body used for its audit hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: dict[str, JsonValue]
    raw_body: str = Field(min_length=1)


@runtime_checkable
class StructuredHTTPTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, JsonValue],
        timeout: float,
    ) -> StructuredHTTPResponse: ...


class HttpxStructuredTransport:
    """Small provider-SDK-free HTTP transport."""

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, JsonValue],
        timeout: float,
    ) -> StructuredHTTPResponse:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            raw_body = response.text
        try:
            data = json.loads(raw_body, parse_constant=_reject_non_finite_json)
        except (json.JSONDecodeError, ValueError) as exc:
            raise StructuredProviderResponseError(
                "provider HTTP response is not valid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise StructuredProviderResponseError("provider response root must be an object")
        return StructuredHTTPResponse(data=data, raw_body=raw_body)


class StructuredOpenAICompatibleConfig(BaseModel):
    """Pinned endpoint, model, retry, and pricing settings for one live condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    base_url: str
    model: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    live_enabled: bool = False
    timeout_seconds: float = Field(default=180.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=0, ge=0, le=5)
    max_output_tokens: int = Field(default=4_000, ge=1)
    pricing_confirmed: bool = False
    pricing: ModelCostProvenance | None = None
    unpriced_engineering_probe: bool = False
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def endpoint_is_safe(cls, value: str) -> str:
        parsed = urlparse(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
            raise ValueError("base_url must use HTTPS except for localhost")
        if not parsed.hostname:
            raise ValueError("base_url must contain a hostname")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url cannot contain credentials, a query, or a fragment")
        return value.rstrip("/")

    @field_validator("extra_headers")
    @classmethod
    def headers_cannot_embed_credentials(cls, value: dict[str, str]) -> dict[str, str]:
        credential_headers = {"authorization", "proxy-authorization", "api-key", "x-api-key"}
        forbidden = sorted(key for key in value if key.casefold() in credential_headers)
        if forbidden:
            raise ValueError("extra_headers cannot contain credential headers")
        return value

    @field_validator("extra_body")
    @classmethod
    def extra_body_cannot_override_identity(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        reserved = {
            "model",
            "messages",
            "response_format",
            "seed",
            "stream",
            "max_tokens",
            "tools",
            "tool_choice",
        }
        forbidden = sorted(set(value) & reserved)
        if forbidden:
            raise ValueError(
                "extra_body cannot override reserved request fields: " + ", ".join(forbidden)
            )
        return value

    @model_validator(mode="after")
    def live_pricing_is_explicit(self) -> StructuredOpenAICompatibleConfig:
        if self.pricing_confirmed and self.pricing is None:
            raise ValueError("pricing_confirmed requires explicit pricing provenance")
        if self.unpriced_engineering_probe:
            if not self.live_enabled:
                raise ValueError("unpriced_engineering_probe requires live_enabled=true")
            if self.pricing_confirmed or self.pricing is not None:
                raise ValueError("unpriced engineering probes cannot claim pricing provenance")
            if self.max_retries != 0:
                raise ValueError("unpriced engineering probes prohibit retries")
        elif self.live_enabled and not self.pricing_confirmed:
            raise ValueError(
                "live_enabled requires confirmed pricing or an explicit unpriced engineering probe"
            )
        return self


class StructuredOpenAICompatibleBackend:
    """Generate typed advice without model fallback or provider-side tool execution."""

    def __init__(
        self,
        config: StructuredOpenAICompatibleConfig,
        *,
        transport: StructuredHTTPTransport | None = None,
    ) -> None:
        values = config.model_dump(mode="python")
        self.config = StructuredOpenAICompatibleConfig.model_validate(values, strict=True)
        self.transport = transport or HttpxStructuredTransport()
        self.name = self.config.provider
        self.model = self.config.model

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        config = self._config_snapshot()
        pricing = self._live_pricing(config)
        api_key = os.getenv(config.api_key_env)
        if api_key is None or not api_key.strip():
            raise RuntimeError(f"missing API key environment variable {config.api_key_env}")

        endpoint = f"{config.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            **config.extra_headers,
            "Authorization": f"Bearer {api_key.strip()}",
        }
        payload = self._payload(request, config=config)
        started = time.perf_counter()
        http_response = self._post_with_retry(endpoint, headers, payload, config=config)
        latency_ms = (time.perf_counter() - started) * 1000

        message, finish_reason = _chat_message(http_response.data)
        if finish_reason not in {"stop", "tool_calls"}:
            raise StructuredProviderResponseError(
                f"provider returned non-final finish_reason {finish_reason!r}"
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise StructuredProviderResponseError(
                "provider Chat Completions response has no text content"
            )
        output_payload = _parse_json_object(content)
        tool_calls = _tool_call_proposals(message.get("tool_calls"))
        input_tokens, output_tokens, cached_input_tokens = _token_usage(http_response.data)
        cost_usd = (
            _cost_usd(
                input_tokens,
                output_tokens,
                pricing,
                cached_input_tokens=cached_input_tokens,
            )
            if pricing is not None
            else None
        )
        provider_model = _provider_model(http_response.data, fallback=config.model)

        raw_response = http_response.raw_body
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=output_payload,
            backend=self.name,
            model=provider_model,
            raw_response=raw_response,
            raw_response_sha256=hashlib.sha256(raw_response.encode()).hexdigest(),
            latency_ms=latency_ms,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            ),
            prompt_cache_input_tokens=cached_input_tokens,
            cost_provenance=pricing,
            tool_calls=tool_calls,
            cached=False,
        )

    def _config_snapshot(self) -> StructuredOpenAICompatibleConfig:
        values = self.config.model_dump(mode="python")
        return StructuredOpenAICompatibleConfig.model_validate(values, strict=True)

    def _live_pricing(
        self,
        config: StructuredOpenAICompatibleConfig,
    ) -> ModelCostProvenance | None:
        if not config.live_enabled:
            raise StructuredBackendDisabledError("live structured model backend is disabled")
        if config.unpriced_engineering_probe:
            return None
        if not config.pricing_confirmed or config.pricing is None:
            raise StructuredBackendDisabledError(
                "live structured model backend requires confirmed pricing"
            )
        return config.pricing

    def _payload(
        self,
        request: StructuredModelRequest,
        *,
        config: StructuredOpenAICompatibleConfig,
    ) -> dict[str, JsonValue]:
        requested_output_tokens = (
            request.generation_envelope.max_output_tokens
            if request.generation_envelope is not None
            else config.max_output_tokens
        )
        if requested_output_tokens > config.max_output_tokens:
            raise StructuredBackendDisabledError(
                "profile output envelope exceeds the backend configuration ceiling"
            )
        payload: dict[str, JsonValue] = {
            "model": config.model,
            "messages": structured_model_messages(request),
            "response_format": {"type": "json_object"},
            "seed": request.seed,
            "stream": False,
            "max_tokens": requested_output_tokens,
        }
        payload.update(config.extra_body)
        return payload

    def _post_with_retry(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, JsonValue],
        *,
        config: StructuredOpenAICompatibleConfig,
    ) -> StructuredHTTPResponse:
        for attempt in range(config.max_retries + 1):
            try:
                response = self.transport.post(
                    endpoint,
                    headers=headers,
                    payload=payload,
                    timeout=config.timeout_seconds,
                )
                values = response.model_dump(mode="python")
                return StructuredHTTPResponse.model_validate(values, strict=True)
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not retryable or attempt == config.max_retries:
                    raise
            except httpx.TransportError:
                if attempt == config.max_retries:
                    raise
            time.sleep(min(2**attempt, 8))
        raise RuntimeError("unreachable retry state")  # pragma: no cover


def load_structured_openai_compatible_config(
    path: str | Path,
) -> StructuredOpenAICompatibleConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("structured model backend config root must be an object")
    return StructuredOpenAICompatibleConfig.model_validate(raw)


def structured_model_messages(request: StructuredModelRequest) -> list[dict[str, str]]:
    """Render one provider-neutral chat shared by API and local structured backends."""

    identity: dict[str, JsonValue] = {
        "schema_version": request.schema_version,
        "request_id": request.request_id,
        "request_fingerprint": request.fingerprint,
        "node_name": request.node_name,
        "stage": request.stage,
        "state_snapshot_id": request.state_snapshot_id,
        "expected_backend": request.expected_backend,
        "expected_model": request.expected_model,
        "policy_id": request.policy_id,
        "policy_fingerprint": request.policy_fingerprint,
        "prompt_version": request.prompt_version,
        "seed": request.seed,
    }
    if request.profile_id is not None:
        assert request.generation_envelope is not None
        assert request.admission_budget is not None
        assert request.cumulative_project_budget is not None
        identity["profile_id"] = request.profile_id
        identity["profile_fingerprint"] = request.profile_fingerprint
        identity["generation_envelope"] = request.generation_envelope.model_dump(mode="json")
        identity["admission_budget"] = request.admission_budget.model_dump(mode="json")
        identity["cumulative_project_budget"] = request.cumulative_project_budget.model_dump(
            mode="json"
        )
    user_content = json.dumps(
        {
            "response_contract": (
                "Return exactly one JSON object that validates against output_schema."
            ),
            "request_identity": identity,
            "input_payload": request.input_payload,
            "output_schema": request.output_schema,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return [
        {"role": "system", "content": request.system_instruction},
        {"role": "user", "content": user_content},
    ]


def _chat_message(data: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], str]:
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise StructuredProviderResponseError(
            "provider Chat Completions response must contain exactly one choice"
        )
    choice = choices[0]
    if not isinstance(choice, dict):
        raise StructuredProviderResponseError("provider Chat Completions choice must be an object")
    message = choice.get("message")
    finish_reason = choice.get("finish_reason")
    if not isinstance(message, dict) or not isinstance(finish_reason, str):
        raise StructuredProviderResponseError("invalid provider Chat Completions choice")
    return message, finish_reason


def _parse_json_object(text: str) -> dict[str, JsonValue]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        match = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL
        )
        if match is None:
            raise StructuredProviderResponseError("model returned an unterminated JSON code fence")
        cleaned = match.group(1).strip()
    try:
        value = json.loads(cleaned, parse_constant=_reject_non_finite_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise StructuredProviderResponseError("model did not return one valid JSON object") from exc
    if not isinstance(value, dict):
        raise StructuredProviderResponseError("model response JSON must be an object")
    return value


def _tool_call_proposals(value: JsonValue | None) -> list[ToolCallProposal]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StructuredProviderResponseError("provider tool_calls must be an array")
    proposals: list[ToolCallProposal] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or item.get("type") != "function":
            raise StructuredProviderResponseError(
                f"provider tool_calls[{index}] is not a supported function call"
            )
        function = item.get("function")
        if not isinstance(function, dict):
            raise StructuredProviderResponseError(
                f"provider tool_calls[{index}].function must be an object"
            )
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name.strip():
            raise StructuredProviderResponseError(
                f"provider tool_calls[{index}] has no function name"
            )
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments, parse_constant=_reject_non_finite_json)
            except (json.JSONDecodeError, ValueError) as exc:
                raise StructuredProviderResponseError(
                    f"provider tool_calls[{index}] arguments are not valid JSON"
                ) from exc
        if not isinstance(arguments, dict):
            raise StructuredProviderResponseError(
                f"provider tool_calls[{index}] arguments must be a JSON object"
            )
        proposals.append(
            ToolCallProposal.model_validate(
                {"name": name, "arguments": arguments},
                strict=True,
            )
        )
    return proposals


def _token_usage(data: dict[str, JsonValue]) -> tuple[int, int, int]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise StructuredProviderResponseError("provider response is missing token usage")
    input_tokens = _token_alias(usage, "input", ("prompt_tokens", "input_tokens"))
    output_tokens = _token_alias(usage, "output", ("completion_tokens", "output_tokens"))
    cached_input_tokens = _cached_input_tokens(usage, input_tokens=input_tokens)
    return input_tokens, output_tokens, cached_input_tokens


def _cached_input_tokens(usage: dict[str, JsonValue], *, input_tokens: int) -> int:
    observed: list[JsonValue] = []
    for name in ("prompt_tokens_details", "input_tokens_details"):
        if name not in usage:
            continue
        details = usage[name]
        if not isinstance(details, dict):
            raise StructuredProviderResponseError(f"provider usage {name} must be an object")
        if "cached_tokens" in details:
            observed.append(details["cached_tokens"])
    if not observed:
        return 0
    if any(type(value) is not int or value < 0 for value in observed):
        raise StructuredProviderResponseError(
            "provider usage cached input tokens must be a non-negative integer"
        )
    if len(set(observed)) != 1:
        raise StructuredProviderResponseError(
            "provider usage has conflicting cached input token aliases"
        )
    cached = observed[0]
    assert isinstance(cached, int)
    if cached > input_tokens:
        raise StructuredProviderResponseError(
            "provider usage cached input tokens exceed total input tokens"
        )
    return cached


def _token_alias(
    usage: dict[str, JsonValue],
    label: str,
    aliases: tuple[str, ...],
) -> int:
    observed = [usage[name] for name in aliases if name in usage]
    if not observed:
        raise StructuredProviderResponseError(f"provider usage is missing {label} tokens")
    if any(type(value) is not int or value < 0 for value in observed):
        raise StructuredProviderResponseError(
            f"provider usage {label} tokens must be non-negative integers"
        )
    if len(set(observed)) != 1:
        raise StructuredProviderResponseError(
            f"provider usage has conflicting {label} token aliases"
        )
    return observed[0]


def _provider_model(data: dict[str, JsonValue], *, fallback: str) -> str:
    if "model" not in data:
        return fallback
    model = data["model"]
    if not isinstance(model, str) or not model:
        raise StructuredProviderResponseError("provider model identity must be a non-empty string")
    return model


def _cost_usd(
    input_tokens: int,
    output_tokens: int,
    pricing: ModelCostProvenance,
    *,
    cached_input_tokens: int = 0,
) -> float:
    million = Decimal(1_000_000)
    cached_rate = pricing.cached_input_usd_per_million_tokens
    priced_cached_tokens = cached_input_tokens if cached_rate is not None else 0
    cost = (
        Decimal(input_tokens - priced_cached_tokens)
        * Decimal(str(pricing.input_usd_per_million_tokens))
        / million
        + Decimal(priced_cached_tokens)
        * Decimal(
            str(cached_rate if cached_rate is not None else pricing.input_usd_per_million_tokens)
        )
        / million
        + Decimal(output_tokens) * Decimal(str(pricing.output_usd_per_million_tokens)) / million
    )
    value = float(cost)
    if not math.isfinite(value):
        raise StructuredProviderResponseError("calculated provider cost is not finite")
    return value


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not permitted")
