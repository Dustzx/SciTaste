from __future__ import annotations

import json

import httpx
import pytest

from scitaste.generative_ui.planner_transport import BoundedPlannerHTTPTransport
from scitaste.model_nodes.openai_compatible import StructuredProviderResponseError


def _transport(content: bytes, *, headers: dict[str, str] | None = None):
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers=headers, request=request)

    return httpx.MockTransport(respond)


def _post(transport: BoundedPlannerHTTPTransport):
    return transport.post(
        "https://provider.invalid/v1/chat/completions",
        headers={"Authorization": "Bearer test-only"},
        payload={"model": "fixture"},
        timeout=1,
    )


def test_bounded_transport_returns_exact_strict_json_body() -> None:
    raw = b'{"choices":[],"usage":{"total_tokens":0}}'
    transport = BoundedPlannerHTTPTransport(
        max_response_bytes=512,
        transport=_transport(raw),
    )

    response = _post(transport)

    assert response.raw_body == raw.decode()
    assert response.data == {"choices": [], "usage": {"total_tokens": 0}}


def test_bounded_transport_rejects_declared_or_streamed_oversize_before_parse() -> None:
    declared = BoundedPlannerHTTPTransport(
        max_response_bytes=256,
        transport=_transport(b"{}", headers={"Content-Length": "257"}),
    )
    with pytest.raises(StructuredProviderResponseError, match="byte limit"):
        _post(declared)

    streamed = BoundedPlannerHTTPTransport(
        max_response_bytes=256,
        transport=_transport(b"{" + b" " * 300 + b"}", headers={"Transfer-Encoding": "chunked"}),
    )
    with pytest.raises(StructuredProviderResponseError, match="byte limit"):
        _post(streamed)


@pytest.mark.parametrize(
    "content",
    [
        b'{"duplicate":1,"duplicate":2}',
        b'{"value":NaN}',
        b"\xff",
        b"[]",
    ],
)
def test_bounded_transport_rejects_non_strict_provider_json(content: bytes) -> None:
    transport = BoundedPlannerHTTPTransport(
        max_response_bytes=512,
        transport=_transport(content),
    )

    with pytest.raises(StructuredProviderResponseError):
        _post(transport)


@pytest.mark.parametrize(
    "message_content",
    [
        '{"candidate_id":"first","candidate_id":"second"}',
        '{"value":NaN}',
        "[]",
        "```json\n{}\n```",
    ],
)
def test_bounded_transport_rejects_ambiguous_embedded_model_json(
    message_content: str,
) -> None:
    outer = (
        '{"choices":[{"finish_reason":"stop","message":{"content":'
        + json.dumps(message_content)
        + "}}]}"
    ).encode()
    transport = BoundedPlannerHTTPTransport(
        max_response_bytes=512,
        transport=_transport(outer),
    )

    with pytest.raises(StructuredProviderResponseError, match="message content"):
        _post(transport)


def test_bounded_transport_validates_limit_type_and_range() -> None:
    with pytest.raises(TypeError):
        BoundedPlannerHTTPTransport(max_response_bytes=True)
    with pytest.raises(ValueError):
        BoundedPlannerHTTPTransport(max_response_bytes=255)
    with pytest.raises(ValueError):
        BoundedPlannerHTTPTransport(max_response_bytes=1_000_001)
