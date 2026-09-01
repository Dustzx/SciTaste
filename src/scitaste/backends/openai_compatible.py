"""Minimal live backend for OpenAI-compatible Chat Completions or Responses APIs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from scitaste.backends.base import PreferenceRequest, PreferenceResponse, Usage


class APIStyle(StrEnum):
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


class OpenAICompatibleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    base_url: str
    model: str
    api_key_env: str | None = None
    api_style: APIStyle = APIStyle.CHAT_COMPLETIONS
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    reasoning_effort: str | None = None
    json_mode: bool = False
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def endpoint_is_safe(cls, value: str) -> str:
        parsed = urlparse(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
            raise ValueError("base_url must use HTTPS except for localhost")
        return value.rstrip("/")


class HTTPTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]: ...


class HttpxTransport:
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("provider response root must be an object")
        return data


class OpenAICompatibleBackend:
    """Rank fixed candidates while keeping keys, URLs, and models in config."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or HttpxTransport()
        self.name = config.provider

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        api_key = os.getenv(self.config.api_key_env) if self.config.api_key_env else None
        if self.config.api_key_env and not api_key:
            raise RuntimeError(f"missing API key environment variable {self.config.api_key_env}")
        prompt = _preference_prompt(request)
        payload = self._payload(prompt)
        endpoint = (
            f"{self.config.base_url}/responses"
            if self.config.api_style == APIStyle.RESPONSES
            else f"{self.config.base_url}/chat/completions"
        )
        headers = {"Content-Type": "application/json", **self.config.extra_headers}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        started = time.perf_counter()
        semantic_attempts = 0
        while True:
            semantic_attempts += 1
            data = self._post_with_retry(endpoint, headers, payload)
            raw_text = _response_text(data, self.config.api_style)
            try:
                parsed = _parse_json_object(raw_text)
                break
            except ValueError:
                if semantic_attempts > self.config.max_retries:
                    raise
                payload = _add_format_repair(payload, self.config.api_style)
        latency_ms = (time.perf_counter() - started) * 1000
        selected_action_id = str(parsed["selected_action_id"])
        candidate_ids = {action.action_id for action in request.candidate_actions}
        if selected_action_id not in candidate_ids:
            raise ValueError(f"provider selected unknown action {selected_action_id!r}")
        usage_data = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        input_tokens = usage_data.get("input_tokens", usage_data.get("prompt_tokens", 0))
        output_tokens = usage_data.get("output_tokens", usage_data.get("completion_tokens", 0))
        return PreferenceResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            selected_action_id=selected_action_id,
            rationale=str(parsed["rationale"]),
            confidence=float(parsed["confidence"]),
            backend=self.name,
            model=self.config.model,
            raw_response=raw_text,
            raw_response_sha256=hashlib.sha256(raw_text.encode()).hexdigest(),
            latency_ms=latency_ms,
            semantic_attempts=semantic_attempts,
            usage=Usage(input_tokens=int(input_tokens), output_tokens=int(output_tokens)),
        )

    def _post_with_retry(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        for attempt in range(self.config.max_retries + 1):
            try:
                return self.transport.post(
                    endpoint,
                    headers=headers,
                    payload=payload,
                    timeout=self.config.timeout_seconds,
                )
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not retryable or attempt == self.config.max_retries:
                    raise
            except httpx.TransportError:
                if attempt == self.config.max_retries:
                    raise
            time.sleep(min(2**attempt, 8))
        raise RuntimeError("unreachable retry state")  # pragma: no cover

    def _payload(self, prompt: str) -> dict[str, Any]:
        if self.config.api_style == APIStyle.RESPONSES:
            payload: dict[str, Any] = {
                "model": self.config.model,
                "instructions": _SYSTEM_PROMPT,
                "input": prompt,
            }
            if self.config.reasoning_effort:
                payload["reasoning"] = {"effort": self.config.reasoning_effort}
        else:
            payload = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
            if self.config.json_mode:
                payload["response_format"] = {"type": "json_object"}
        payload.update(self.config.extra_body)
        return payload


def load_openai_compatible_config(path: str | Path) -> OpenAICompatibleConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    expanded = _expand_environment(raw)
    return OpenAICompatibleConfig.model_validate(expanded)


_SYSTEM_PROMPT = (
    "You judge scientific research decisions. Select exactly one supplied action based on "
    "rigor, information value, evidence, feasibility, and current resource constraints. "
    "Return only a JSON object with selected_action_id, rationale, and confidence (0 to 1)."
)


def _preference_prompt(request: PreferenceRequest) -> str:
    candidates = [
        {
            "action_id": action.action_id,
            "type": action.type.value,
            "description": action.description,
            "expected_cost": action.expected_cost,
        }
        for action in request.candidate_actions
    ]
    return json.dumps(
        {
            "task": request.task,
            "stage": request.stage,
            "decision_context": request.decision_context,
            "candidate_actions": candidates,
        },
        ensure_ascii=False,
    )


def _response_text(data: dict[str, Any], style: APIStyle) -> str:
    if style == APIStyle.CHAT_COMPLETIONS:
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("invalid Chat Completions response") from exc
    if isinstance(data.get("output_text"), str):
        return str(data["output_text"])
    try:
        for item in data["output"]:
            for content in item.get("content", []):
                if isinstance(content.get("text"), str):
                    return str(content["text"])
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid Responses API response") from exc
    raise ValueError("Responses API response has no text output")


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("model did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    required = {"selected_action_id", "rationale", "confidence"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"model response is missing: {', '.join(sorted(missing))}")
    return value


def _add_format_repair(payload: dict[str, Any], style: APIStyle) -> dict[str, Any]:
    repaired = dict(payload)
    reminder = (
        "Your previous response violated the required schema. Return exactly one JSON object "
        "containing all three keys: selected_action_id (string), rationale (non-empty string), "
        "and confidence (number from 0 to 1)."
    )
    if style == APIStyle.RESPONSES:
        repaired["input"] = f"{payload['input']}\n\n{reminder}"
    else:
        repaired["messages"] = [*payload["messages"], {"role": "user", "content": reminder}]
    return repaired


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value
