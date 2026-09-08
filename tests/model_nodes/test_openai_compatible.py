from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from scitaste.model_nodes import (
    ModelCostProvenance,
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    RecordingStructuredBackend,
    ReplayStructuredBackend,
    ReviewSemanticInput,
    ReviewSemanticNode,
    StructuredBackendDisabledError,
    StructuredHTTPResponse,
    StructuredModelRequest,
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
    StructuredProviderResponseError,
    load_structured_openai_compatible_config,
)
from scitaste.schema.actions import MetaAction


class StubTransport:
    def __init__(self, *items: StructuredHTTPResponse | Exception) -> None:
        self.items = list(items)
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> StructuredHTTPResponse:
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def pricing(**updates: object) -> ModelCostProvenance:
    values: dict[str, object] = {
        "currency": "USD",
        "input_usd_per_million_tokens": 0.25,
        "output_usd_per_million_tokens": 0.50,
        "captured_at": datetime(2026, 9, 5, 8, 0, tzinfo=UTC),
        "source": "https://billing.example.test/model-price-snapshot",
    }
    values.update(updates)
    return ModelCostProvenance.model_validate(values)


def config(**updates: object) -> StructuredOpenAICompatibleConfig:
    values: dict[str, object] = {
        "provider": "test-provider",
        "base_url": "https://api.example.test/v1",
        "model": "test-model-v1",
        "api_key_env": "SCITASTE_STRUCTURED_TEST_KEY",
        "live_enabled": True,
        "timeout_seconds": 30,
        "max_retries": 0,
        "max_output_tokens": 512,
        "pricing_confirmed": True,
        "pricing": pricing(),
        "extra_headers": {"X-Test-Condition": "structured"},
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    values.update(updates)
    return StructuredOpenAICompatibleConfig.model_validate(values)


def request() -> StructuredModelRequest:
    return StructuredModelRequest(
        request_id="structured-live-1",
        node_name="review-semantic",
        stage="REVIEW",
        state_snapshot_id="snapshot-1",
        expected_backend="test-provider",
        expected_model="test-model-v1",
        policy_id="policy-live-1",
        policy_fingerprint="1" * 64,
        system_instruction="Parse the review and return bounded advice only.",
        input_payload={
            "context": {"claim_ids": ["claim-1"]},
            "input": {"review_text": "Clarify the method."},
        },
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        seed=7,
        prompt_version="review-semantic-v1",
    )


def http_response(data: dict[str, Any], *, raw_body: str | None = None) -> StructuredHTTPResponse:
    return StructuredHTTPResponse(
        data=data,
        raw_body=raw_body or json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    )


def provider_data(
    content: str = '{"summary":"One concern."}',
    *,
    model: object = "test-model-v1",
    usage: object = None,
    finish_reason: str = "stop",
    tool_calls: object = None,
) -> dict[str, Any]:
    message: dict[str, object] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    data: dict[str, Any] = {
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }
    if model is not None:
        data["model"] = model
    return data


def test_chat_payload_identity_pricing_and_raw_response(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    content = '```json\n{"summary":"Bounded semantic result."}\n```'
    data = provider_data(
        content,
        model="provider-model-revision-20260905",
        usage={"prompt_tokens": 1_000_000, "completion_tokens": 2_000_000},
    )
    raw_body = json.dumps(data, ensure_ascii=False, indent=2)
    transport = StubTransport(http_response(data, raw_body=raw_body))

    response = StructuredOpenAICompatibleBackend(config(), transport=transport).complete(request())

    assert response.request_id == request().request_id
    assert response.request_fingerprint == request().fingerprint
    assert response.output_payload == {"summary": "Bounded semantic result."}
    assert response.backend == "test-provider"
    assert response.model == "provider-model-revision-20260905"
    assert response.raw_response == raw_body
    assert response.raw_response_sha256 == hashlib.sha256(raw_body.encode()).hexdigest()
    assert response.usage.input_tokens == 1_000_000
    assert response.usage.output_tokens == 2_000_000
    assert response.usage.cost_usd == pytest.approx(1.25)
    assert response.cost_provenance == pricing()
    assert response.cached is False

    call = transport.calls[0]
    assert call["url"] == "https://api.example.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret-for-test"
    assert call["headers"]["X-Test-Condition"] == "structured"
    assert "secret-for-test" not in json.dumps(call["payload"])
    assert call["payload"]["model"] == "test-model-v1"
    assert call["payload"]["seed"] == 7
    assert call["payload"]["stream"] is False
    assert call["payload"]["max_tokens"] == 512
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert call["payload"]["thinking"] == {"type": "enabled"}
    assert call["payload"]["messages"][0] == {
        "role": "system",
        "content": request().system_instruction,
    }
    prompt = json.loads(call["payload"]["messages"][1]["content"])
    assert prompt["input_payload"] == request().input_payload
    assert prompt["output_schema"] == request().output_schema
    assert prompt["request_identity"] == {
        "schema_version": "1.0",
        "request_id": "structured-live-1",
        "request_fingerprint": request().fingerprint,
        "node_name": "review-semantic",
        "stage": "REVIEW",
        "state_snapshot_id": "snapshot-1",
        "expected_backend": "test-provider",
        "expected_model": "test-model-v1",
        "policy_id": "policy-live-1",
        "policy_fingerprint": "1" * 64,
        "prompt_version": "review-semantic-v1",
        "seed": 7,
    }


def test_missing_key_and_disabled_config_fail_before_transport(monkeypatch) -> None:
    monkeypatch.delenv("SCITASTE_STRUCTURED_TEST_KEY", raising=False)
    transport = StubTransport(http_response(provider_data()))
    with pytest.raises(RuntimeError, match="SCITASTE_STRUCTURED_TEST_KEY"):
        StructuredOpenAICompatibleBackend(config(), transport=transport).complete(request())
    assert transport.calls == []

    disabled = config(live_enabled=False, pricing_confirmed=False, pricing=None)
    with pytest.raises(StructuredBackendDisabledError, match="disabled"):
        StructuredOpenAICompatibleBackend(disabled, transport=transport).complete(request())
    assert transport.calls == []


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 13, "completion_tokens": 8},
        {"input_tokens": 13, "output_tokens": 8},
        {
            "prompt_tokens": 13,
            "input_tokens": 13,
            "completion_tokens": 8,
            "output_tokens": 8,
        },
    ],
)
def test_token_usage_aliases_are_explicit(monkeypatch, usage: dict[str, int]) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    backend = StructuredOpenAICompatibleBackend(
        config(), transport=StubTransport(http_response(provider_data(model=None, usage=usage)))
    )

    response = backend.complete(request())

    assert response.model == "test-model-v1"
    assert response.usage.input_tokens == 13
    assert response.usage.output_tokens == 8
    expected = (13 * 0.25 + 8 * 0.50) / 1_000_000
    assert response.usage.cost_usd == pytest.approx(expected)


def test_prompt_cache_usage_applies_the_explicit_cache_rate(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    backend = StructuredOpenAICompatibleBackend(
        config(
            pricing=pricing(cached_input_usd_per_million_tokens=0.10),
        ),
        transport=StubTransport(
            http_response(
                provider_data(
                    usage={
                        "prompt_tokens": 13,
                        "completion_tokens": 8,
                        "prompt_tokens_details": {"cached_tokens": 3},
                    }
                )
            )
        ),
    )

    response = backend.complete(request())

    assert response.prompt_cache_input_tokens == 3
    expected = (10 * 0.25 + 3 * 0.10 + 8 * 0.50) / 1_000_000
    assert response.usage.cost_usd == pytest.approx(expected)


@pytest.mark.parametrize(
    ("details", "message"),
    [
        ("invalid", "must be an object"),
        ({"cached_tokens": -1}, "non-negative integer"),
        ({"cached_tokens": 14}, "exceed total input tokens"),
    ],
)
def test_invalid_prompt_cache_usage_fails_closed(
    monkeypatch, details: object, message: str
) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    backend = StructuredOpenAICompatibleBackend(
        config(),
        transport=StubTransport(
            http_response(
                provider_data(
                    usage={
                        "prompt_tokens": 13,
                        "completion_tokens": 8,
                        "prompt_tokens_details": details,
                    }
                )
            )
        ),
    )

    with pytest.raises(StructuredProviderResponseError, match=message):
        backend.complete(request())


@pytest.mark.parametrize(
    ("usage", "message"),
    [
        (None, "missing token usage"),
        ({"prompt_tokens": 1}, "missing output tokens"),
        ({"prompt_tokens": 1, "completion_tokens": "2"}, "non-negative integers"),
        (
            {"prompt_tokens": 1, "input_tokens": 2, "completion_tokens": 3},
            "conflicting input token aliases",
        ),
    ],
)
def test_missing_or_invalid_usage_fails_closed(monkeypatch, usage: object, message: str) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    data = provider_data()
    if usage is None:
        data.pop("usage")
    else:
        data["usage"] = usage
    backend = StructuredOpenAICompatibleBackend(
        config(), transport=StubTransport(http_response(data))
    )

    with pytest.raises(StructuredProviderResponseError, match=message):
        backend.complete(request())


def test_provider_model_drift_is_preserved_for_policy_rejection(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    review_payload = {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "clarity",
                "severity": "medium",
                "target_claim_ids": ["claim-1"],
                "target_section": "method",
                "text": "Clarify the method boundary.",
                "requires_new_evidence": False,
                "requires_new_experiment": False,
                "required_evidence_types": [],
                "proposed_action_type": "CLARIFY_EXISTING_TEXT",
            }
        ],
        "summary": "One clarity concern.",
        "confidence": 0.9,
    }
    data = provider_data(json.dumps(review_payload), model="silent-fallback-model")
    backend = StructuredOpenAICompatibleBackend(
        config(), transport=StubTransport(http_response(data))
    )
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(review_text="Clarify the method."),
        context=NodeContext(
            project_id="project-1",
            stage="REVIEW",
            state_snapshot_id="snapshot-1",
            cumulative_api_cost_usd=0,
            claim_ids=["claim-1"],
            section_ids=["method"],
        ),
        backend=backend,
        policy=NodePolicy(
            policy_id="policy-live",
            enabled=True,
            allowed_node_names=["review-semantic"],
            expected_backend="test-provider",
            expected_model="test-model-v1",
            allowed_action_types=[MetaAction.CLARIFY_EXISTING_TEXT],
        ),
        request_id="review-live-drift",
        seed=7,
    )

    assert result.status == NodeResultStatus.REJECTED
    assert result.response.model == "silent-fallback-model"
    assert "response model differs from pinned model" in result.rejection_reasons


@pytest.mark.parametrize(
    ("content", "finish_reason", "message"),
    [
        ("not JSON", "stop", "one valid JSON object"),
        ("[]", "stop", "must be an object"),
        ('{"ok":true} trailing', "stop", "one valid JSON object"),
        ('{"value":NaN}', "stop", "one valid JSON object"),
        ('{"ok":true}', "length", "non-final finish_reason"),
    ],
)
def test_malformed_model_response_fails_without_semantic_retry(
    monkeypatch, content: str, finish_reason: str, message: str
) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    transport = StubTransport(
        http_response(provider_data(content, finish_reason=finish_reason)),
        http_response(provider_data()),
    )
    backend = StructuredOpenAICompatibleBackend(
        config(max_retries=2),
        transport=transport,
    )

    with pytest.raises(StructuredProviderResponseError, match=message):
        backend.complete(request())
    assert len(transport.calls) == 1


def test_function_tool_calls_become_non_executable_proposals(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    tool_calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "search",
                "arguments": '{"query":"bounded model nodes","limit":3}',
            },
        }
    ]
    backend = StructuredOpenAICompatibleBackend(
        config(),
        transport=StubTransport(
            http_response(provider_data("{}", finish_reason="tool_calls", tool_calls=tool_calls))
        ),
    )

    response = backend.complete(request())

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {
        "query": "bounded model nodes",
        "limit": 3,
    }


@pytest.mark.parametrize(
    "tool_call",
    [
        {"id": "call-1", "type": "mcp", "mcp": {"name": "unknown"}},
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "search", "arguments": "not JSON"},
        },
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "search", "arguments": "[]"},
        },
    ],
)
def test_unknown_or_malformed_tool_calls_fail_closed(monkeypatch, tool_call: object) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    data = provider_data("{}", finish_reason="tool_calls", tool_calls=[tool_call])
    backend = StructuredOpenAICompatibleBackend(
        config(), transport=StubTransport(http_response(data))
    )

    with pytest.raises(StructuredProviderResponseError, match="tool_calls"):
        backend.complete(request())


def test_transport_retries_only_transient_failures(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    monkeypatch.setattr("scitaste.model_nodes.openai_compatible.time.sleep", lambda _: None)
    http_request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    server_response = httpx.Response(503, request=http_request)
    transient_status = httpx.HTTPStatusError(
        "temporary",
        request=http_request,
        response=server_response,
    )
    transport = StubTransport(
        httpx.ReadTimeout("temporary timeout"),
        transient_status,
        http_response(provider_data()),
    )
    backend = StructuredOpenAICompatibleBackend(
        config(max_retries=2),
        transport=transport,
    )

    assert backend.complete(request()).output_payload == {"summary": "One concern."}
    assert len(transport.calls) == 3

    client_response = httpx.Response(400, request=http_request)
    client_status = httpx.HTTPStatusError(
        "bad request",
        request=http_request,
        response=client_response,
    )
    transport = StubTransport(client_status, http_response(provider_data()))
    backend = StructuredOpenAICompatibleBackend(
        config(max_retries=2),
        transport=transport,
    )
    with pytest.raises(httpx.HTTPStatusError):
        backend.complete(request())
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"input_usd_per_million_tokens": float("inf")},
        {"output_usd_per_million_tokens": float("nan")},
        {"captured_at": datetime(2026, 9, 5, 8, 0)},
    ],
)
def test_pricing_requires_finite_rates_and_timezone_provenance(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        pricing(**updates)


def test_live_configuration_requires_confirmed_pricing() -> None:
    with pytest.raises(ValidationError, match="confirmed pricing"):
        config(pricing_confirmed=False, pricing=None)
    with pytest.raises(ValidationError, match="explicit pricing provenance"):
        config(pricing_confirmed=True, pricing=None)
    with pytest.raises(ValidationError, match="credential headers"):
        config(extra_headers={"Authorization": "embedded-secret"})
    with pytest.raises(ValidationError, match="reserved request fields"):
        config(extra_body={"model": "silent-fallback"})
    with pytest.raises(ValidationError, match="reserved request fields"):
        config(extra_body={"tools": [{"type": "web_search"}]})


def test_unpriced_engineering_probe_is_explicit_non_retrying_and_cost_rejected(
    monkeypatch,
) -> None:
    with pytest.raises(ValidationError, match="requires live_enabled"):
        config(
            live_enabled=False,
            pricing_confirmed=False,
            pricing=None,
            unpriced_engineering_probe=True,
        )
    with pytest.raises(ValidationError, match="cannot claim pricing"):
        config(unpriced_engineering_probe=True)
    with pytest.raises(ValidationError, match="prohibit retries"):
        config(
            pricing_confirmed=False,
            pricing=None,
            unpriced_engineering_probe=True,
            max_retries=1,
        )

    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    payload = {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "clarity",
                "severity": "medium",
                "target_claim_ids": ["claim-1"],
                "target_section": "method",
                "text": "Clarify the intervention boundary.",
                "requires_new_evidence": False,
                "requires_new_experiment": False,
                "required_evidence_types": [],
                "proposed_action_type": "CLARIFY_EXISTING_TEXT",
            }
        ],
        "summary": "One clarity concern.",
        "confidence": 0.85,
    }
    transport = StubTransport(http_response(provider_data(json.dumps(payload))))
    backend = StructuredOpenAICompatibleBackend(
        config(
            pricing_confirmed=False,
            pricing=None,
            unpriced_engineering_probe=True,
        ),
        transport=transport,
    )
    result = ReviewSemanticNode().run(
        ReviewSemanticInput(review_text="Please clarify the method boundary."),
        context=NodeContext(
            project_id="project-1",
            stage="REVIEW",
            state_snapshot_id="snapshot-1",
            cumulative_api_cost_usd=0,
            claim_ids=["claim-1"],
            section_ids=["method"],
        ),
        backend=backend,
        policy=NodePolicy(
            policy_id="policy-live",
            enabled=True,
            allowed_node_names=["review-semantic"],
            expected_backend="test-provider",
            expected_model="test-model-v1",
            allowed_action_types=[MetaAction.CLARIFY_EXISTING_TEXT],
        ),
        request_id="unpriced-live-probe",
        seed=7,
    )

    assert result.status is NodeResultStatus.REJECTED
    assert result.response.usage.cost_usd is None
    assert result.response.cost_provenance is None
    assert "API cost telemetry is required" in result.rejection_reasons
    assert len(transport.calls) == 1


def test_mutated_nested_config_is_revalidated_before_transport(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    transport = StubTransport(http_response(provider_data()))
    backend = StructuredOpenAICompatibleBackend(config(), transport=transport)
    backend.config.extra_body["model"] = "silent-fallback"

    with pytest.raises(ValidationError, match="reserved request fields"):
        backend.complete(request())
    assert transport.calls == []


def test_zhipu_example_is_inert_and_contains_no_guessed_price() -> None:
    path = Path("configs/model_nodes/zhipu_glm53_flash.example.yaml")
    loaded = load_structured_openai_compatible_config(path)

    assert loaded.provider == "zhipu-direct"
    assert loaded.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert loaded.model == "glm-5.3-flash"
    assert loaded.api_key_env == "ZAI_API_KEY"
    assert loaded.live_enabled is False
    assert loaded.max_retries == 0
    assert loaded.pricing_confirmed is False
    assert loaded.pricing is None
    assert loaded.unpriced_engineering_probe is False


def test_live_backend_records_and_replays_without_network(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SCITASTE_STRUCTURED_TEST_KEY", "secret-for-test")
    review_payload = {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "clarity",
                "severity": "medium",
                "target_claim_ids": ["claim-1"],
                "target_section": "method",
                "text": "Clarify the intervention boundary.",
                "requires_new_evidence": False,
                "requires_new_experiment": False,
                "required_evidence_types": [],
                "proposed_action_type": "CLARIFY_EXISTING_TEXT",
            }
        ],
        "summary": "One clarity concern.",
        "confidence": 0.85,
    }
    transport = StubTransport(http_response(provider_data(json.dumps(review_payload))))
    live = StructuredOpenAICompatibleBackend(config(), transport=transport)
    recording = tmp_path / "live-structured.jsonl"
    node_input = ReviewSemanticInput(review_text="Please clarify the method boundary.")
    context = NodeContext(
        project_id="project-1",
        stage="REVIEW",
        state_snapshot_id="snapshot-1",
        cumulative_api_cost_usd=0,
        claim_ids=["claim-1"],
        section_ids=["method"],
    )
    policy = NodePolicy(
        policy_id="policy-live",
        enabled=True,
        allowed_node_names=["review-semantic"],
        expected_backend="test-provider",
        expected_model="test-model-v1",
        allowed_action_types=[MetaAction.CLARIFY_EXISTING_TEXT],
    )

    first = ReviewSemanticNode().run(
        node_input,
        context=context,
        backend=RecordingStructuredBackend(live, recording),
        policy=policy,
        request_id="review-live-record",
        seed=7,
    )
    monkeypatch.delenv("SCITASTE_STRUCTURED_TEST_KEY")
    replayed = ReviewSemanticNode().run(
        node_input,
        context=context,
        backend=ReplayStructuredBackend(recording),
        policy=policy,
        request_id="review-live-record",
        seed=7,
    )

    assert first.status == NodeResultStatus.ACCEPTED
    assert first.response.cost_provenance == pricing()
    assert replayed.status == NodeResultStatus.ACCEPTED
    assert replayed.response.cached is True
    assert replayed.response.cost_provenance == first.response.cost_provenance
    assert replayed.proposal == first.proposal
    assert len(transport.calls) == 1
