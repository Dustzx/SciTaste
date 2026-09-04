from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from scitaste.backends.base import PreferenceRequest
from scitaste.backends.openai_compatible import (
    APIStyle,
    OpenAICompatibleBackend,
    OpenAICompatibleConfig,
    load_openai_compatible_config,
)
from scitaste.schema.actions import MetaAction, ResearchAction


class StubTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return self.response


class FlakyTransport(StubTransport):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        if not self.calls:
            self.calls.append(
                {"url": url, "headers": headers, "payload": payload, "timeout": timeout}
            )
            raise httpx.ReadTimeout("temporary timeout")
        return super().post(url, headers=headers, payload=payload, timeout=timeout)


class SequenceTransport(StubTransport):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__({})
        self.responses = responses

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return self.responses[len(self.calls) - 1]


def request() -> PreferenceRequest:
    return PreferenceRequest(
        request_id="case-live-1",
        task="experiment",
        stage="VALIDATION",
        decision_context="Choose the experiment with the highest information value.",
        candidate_actions=[
            ResearchAction(
                action_id="probe",
                type=MetaAction.PROBE,
                description="Run a falsifying probe",
            ),
            ResearchAction(
                action_id="write",
                type=MetaAction.WRITE,
                description="Write before validating",
            ),
        ],
        seed=7,
    )


def config(*, style: APIStyle = APIStyle.CHAT_COMPLETIONS) -> OpenAICompatibleConfig:
    return OpenAICompatibleConfig(
        provider="test-provider",
        base_url="https://api.example.test/v1",
        model="test-model-v1",
        api_key_env="SCITASTE_TEST_API_KEY",
        api_style=style,
        json_mode=True,
    )


def test_chat_completions_request_and_response_contract(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_TEST_API_KEY", "secret-for-test")
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"selected_action_id":"probe","rationale":"Falsifies early",'
                            '"confidence":0.86}'
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 23, "completion_tokens": 11},
        }
    )

    response = OpenAICompatibleBackend(config(), transport=transport).rank(request())

    assert response.selected_action_id == "probe"
    assert response.usage.input_tokens == 23
    assert response.usage.output_tokens == 11
    assert response.raw_response_sha256 is not None
    assert response.latency_ms is not None
    assert transport.calls[0]["url"].endswith("/chat/completions")
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer secret-for-test"
    assert "secret-for-test" not in str(transport.calls[0]["payload"])
    assert transport.calls[0]["payload"]["response_format"] == {"type": "json_object"}


def test_responses_api_request_and_response_contract(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_TEST_API_KEY", "secret-for-test")
    transport = StubTransport(
        {
            "output_text": (
                '{"selected_action_id":"probe","rationale":"Best information gain",'
                '"confidence":0.91}'
            ),
            "usage": {"input_tokens": 31, "output_tokens": 9},
        }
    )
    backend_config = config(style=APIStyle.RESPONSES).model_copy(
        update={"reasoning_effort": "medium"}
    )

    response = OpenAICompatibleBackend(backend_config, transport=transport).rank(request())

    assert response.model == "test-model-v1"
    assert transport.calls[0]["url"].endswith("/responses")
    assert transport.calls[0]["payload"]["reasoning"] == {"effort": "medium"}


def test_missing_key_fails_before_transport() -> None:
    transport = StubTransport({})

    with pytest.raises(RuntimeError, match="SCITASTE_TEST_API_KEY"):
        OpenAICompatibleBackend(config(), transport=transport).rank(request())

    assert transport.calls == []


def test_local_endpoint_can_run_without_an_api_key() -> None:
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"selected_action_id":"probe","rationale":"Local","confidence":0.6}'
                        )
                    }
                }
            ]
        }
    )
    local_config = OpenAICompatibleConfig(
        provider="local",
        base_url="http://127.0.0.1:8000/v1",
        model="local-model",
    )

    response = OpenAICompatibleBackend(local_config, transport=transport).rank(request())

    assert response.selected_action_id == "probe"
    assert "Authorization" not in transport.calls[0]["headers"]


def test_transport_error_is_retried(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_TEST_API_KEY", "secret-for-test")
    monkeypatch.setattr("scitaste.backends.openai_compatible.time.sleep", lambda _: None)
    transport = FlakyTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"selected_action_id":"probe","rationale":"Recovered",'
                            '"confidence":0.7}'
                        )
                    }
                }
            ]
        }
    )

    response = OpenAICompatibleBackend(config(), transport=transport).rank(request())

    assert response.selected_action_id == "probe"
    assert len(transport.calls) == 2


def test_provider_cannot_select_an_action_outside_candidates(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_TEST_API_KEY", "secret-for-test")
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"selected_action_id":"invented","rationale":"Invalid",'
                            '"confidence":0.8}'
                        )
                    }
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="unknown action"):
        OpenAICompatibleBackend(config(), transport=transport).rank(request())


def test_schema_violation_gets_one_bounded_repair_attempt(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_TEST_API_KEY", "secret-for-test")
    transport = SequenceTransport(
        [
            {"choices": [{"message": {"content": '{"selected_action_id":"probe"}'}}]},
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"selected_action_id":"probe","rationale":"Repaired",'
                                '"confidence":0.8}'
                            )
                        }
                    }
                ]
            },
        ]
    )

    response = OpenAICompatibleBackend(config(), transport=transport).rank(request())

    assert response.semantic_attempts == 2
    assert len(transport.calls) == 2
    assert "previous response violated" in transport.calls[1]["payload"]["messages"][-1]["content"]


def test_non_local_plain_http_endpoint_is_rejected() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        OpenAICompatibleConfig(
            provider="unsafe",
            base_url="http://api.example.test/v1",
            model="model",
            api_key_env="API_KEY",
        )


def test_config_expands_base_url_but_not_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_TEST_BASE_URL", "https://regional.example.test/v1")
    path = tmp_path / "backend.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: regional",
                "base_url: ${SCITASTE_TEST_BASE_URL}",
                "model: fixed-model",
                "api_key_env: SCITASTE_TEST_API_KEY",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_openai_compatible_config(path)

    assert loaded.base_url == "https://regional.example.test/v1"
    assert loaded.api_key_env == "SCITASTE_TEST_API_KEY"


def test_zhipu_glm53_flash_example_uses_generic_compatible_contract() -> None:
    loaded = load_openai_compatible_config("configs/backends/zhipu_glm53_flash.example.yaml")

    assert loaded.provider == "zhipu-direct"
    assert loaded.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert loaded.model == "glm-5.3-flash"
    assert loaded.api_key_env == "ZAI_API_KEY"
    assert loaded.extra_body == {"thinking": {"type": "enabled"}}
