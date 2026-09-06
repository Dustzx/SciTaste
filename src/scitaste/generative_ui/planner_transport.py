"""Pre-read bounded HTTP transport for the optional structured UI planner."""

from __future__ import annotations

import json
from typing import Final

import httpx
from pydantic import JsonValue

from scitaste.model_nodes.openai_compatible import (
    StructuredHTTPResponse,
    StructuredProviderResponseError,
)

_MAX_CHUNK_BYTES: Final = 64 * 1024


class BoundedPlannerHTTPTransport:
    """Stream and cap decoded provider bytes before constructing a response string."""

    def __init__(
        self,
        *,
        max_response_bytes: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int):
            raise TypeError("planner response byte limit must be an integer")
        if max_response_bytes < 256 or max_response_bytes > 1_000_000:
            raise ValueError("planner response byte limit must be between 256 and 1000000")
        self.max_response_bytes = max_response_bytes
        self._transport = transport

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, JsonValue],
        timeout: float,
    ) -> StructuredHTTPResponse:
        content = bytearray()
        with httpx.Client(timeout=timeout, transport=self._transport) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                declared = response.headers.get("Content-Length")
                if declared is not None and declared.isdecimal():
                    if int(declared) > self.max_response_bytes:
                        raise StructuredProviderResponseError(
                            "provider HTTP response exceeds the planner byte limit"
                        )
                for chunk in response.iter_bytes(chunk_size=_MAX_CHUNK_BYTES):
                    if len(content) + len(chunk) > self.max_response_bytes:
                        raise StructuredProviderResponseError(
                            "provider HTTP response exceeds the planner byte limit"
                        )
                    content.extend(chunk)
        try:
            raw_body = bytes(content).decode("utf-8")
            data = json.loads(
                raw_body,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_non_finite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise StructuredProviderResponseError(
                "provider HTTP response is not strict UTF-8 JSON"
            ) from exc
        if not isinstance(data, dict):
            raise StructuredProviderResponseError("provider response root must be an object")
        _validate_embedded_json_content(data)
        return StructuredHTTPResponse(data=data, raw_body=raw_body)


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("provider JSON object keys must be unique")
        value[key] = child
    return value


def _reject_non_finite(value: str) -> JsonValue:
    raise ValueError(f"provider JSON contains non-finite value {value}")


def _validate_embedded_json_content(data: dict[str, JsonValue]) -> None:
    """Reject ambiguous JSON inside Chat Completions content before backend parsing."""

    choices = data.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(
                content,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_non_finite,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise StructuredProviderResponseError(
                "provider message content is not one strict JSON object"
            ) from exc
        if not isinstance(payload, dict):
            raise StructuredProviderResponseError(
                "provider message content must contain a JSON object"
            )


__all__ = ["BoundedPlannerHTTPTransport"]
