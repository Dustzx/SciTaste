from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest

from scitaste.backends.local_chat_server import LocalChatServerConfig, local_chat_server
from scitaste.backends.local_transformers import LocalGeneration

TOKEN = "local-test-token-0123456789"


class StubChatRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_messages(
        self,
        *,
        messages: list[dict[str, str]],
        seed: int,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> LocalGeneration:
        self.calls.append(
            {
                "messages": messages,
                "seed": seed,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
            }
        )
        return LocalGeneration(text='{"answer":"bounded"}', input_tokens=21, output_tokens=7)


def _config(**updates: object) -> LocalChatServerConfig:
    values: dict[str, object] = {
        "model_aliases": ("checkpoint-revision", "Qwen/Qwen3-VL-4B-Instruct"),
        "max_output_tokens": 64,
    }
    values.update(updates)
    return LocalChatServerConfig.model_validate(values)


def _post(base_url: str, payload: dict[str, object], *, token: str = TOKEN) -> dict:
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def test_local_chat_server_returns_openai_shape_and_exact_usage() -> None:
    runtime = StubChatRuntime()
    with local_chat_server(runtime, config=_config(), bearer_token=TOKEN) as base_url:
        response = _post(
            base_url,
            {
                "model": "checkpoint-revision",
                "messages": [{"role": "user", "content": "Return an object."}],
                "temperature": 0.2,
                "max_tokens": 32,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
            },
        )

    assert response["object"] == "chat.completion"
    assert response["choices"][0]["message"]["content"] == '{"answer":"bounded"}'
    assert response["usage"] == {
        "prompt_tokens": 21,
        "completion_tokens": 7,
        "total_tokens": 28,
    }
    assert runtime.calls[0]["max_new_tokens"] == 32
    assert runtime.calls[0]["temperature"] == 0.2
    messages = runtime.calls[0]["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert "valid JSON" in messages[0]["content"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "model": "unknown-model",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 8,
        },
        {
            "model": "checkpoint-revision",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 65,
        },
        {
            "model": "checkpoint-revision",
            "messages": [{"role": "user", "content": "test"}],
            "stream": True,
        },
        {
            "model": "checkpoint-revision",
            "messages": [{"role": "tool", "content": "execute"}],
        },
    ],
)
def test_local_chat_server_rejects_unbound_or_unsupported_requests(payload) -> None:
    runtime = StubChatRuntime()
    with local_chat_server(runtime, config=_config(), bearer_token=TOKEN) as base_url:
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(base_url, payload)

    assert caught.value.code == 400
    assert runtime.calls == []


def test_local_chat_server_requires_auth_without_reflecting_token() -> None:
    runtime = StubChatRuntime()
    with local_chat_server(runtime, config=_config(), bearer_token=TOKEN) as base_url:
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(
                base_url,
                {
                    "model": "checkpoint-revision",
                    "messages": [{"role": "user", "content": "test"}],
                },
                token="wrong-token-but-still-long-enough",
            )
        body = caught.value.read().decode()

    assert caught.value.code == 401
    assert TOKEN not in body
    assert runtime.calls == []


def test_local_chat_server_rejects_duplicate_keys_and_oversized_bodies() -> None:
    runtime = StubChatRuntime()
    with local_chat_server(
        runtime,
        config=_config(max_request_bytes=1024),
        bearer_token=TOKEN,
    ) as base_url:
        target = urlsplit(base_url)
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=3)
        duplicate = (
            '{"model":"checkpoint-revision","model":"other",'
            '"messages":[{"role":"user","content":"test"}]}'
        )
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=duplicate,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
        )
        assert connection.getresponse().status == 400
        connection.close()

        oversized = "x" * 1100
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=oversized.encode(),
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        assert caught.value.code == 413

    assert runtime.calls == []


def test_local_chat_server_requires_json_content_type() -> None:
    runtime = StubChatRuntime()
    payload = json.dumps(
        {
            "model": "checkpoint-revision",
            "messages": [{"role": "user", "content": "test"}],
        }
    ).encode()
    with local_chat_server(runtime, config=_config(), bearer_token=TOKEN) as base_url:
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "text/plain",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)

    assert caught.value.code == 400
    assert runtime.calls == []


def test_local_chat_server_derives_a_repeatable_seed_when_absent() -> None:
    runtime = StubChatRuntime()
    payload = {
        "model": "checkpoint-revision",
        "messages": [{"role": "user", "content": "same request"}],
        "max_tokens": 8,
    }
    with local_chat_server(runtime, config=_config(), bearer_token=TOKEN) as base_url:
        _post(base_url, payload)
        _post(base_url, payload)

    assert runtime.calls[0]["seed"] == runtime.calls[1]["seed"]
