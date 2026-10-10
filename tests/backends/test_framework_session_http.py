import hashlib
import http.client
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest

from scitaste.backends.framework_session_http import FrameworkSessionHTTPServer

TOKEN = "local-session-test-token-0123456789"
BODY = {
    "model": "native-model-label",
    "messages": [
        {"role": "system", "content": "Keep native instructions.\n  空格"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Native question\n"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA="}},
            ],
        },
    ],
    "temperature": 0.7,
    "max_tokens": 321,
    "response_format": {"type": "json_object"},
    "native_extra": {"preserve": True},
}


def _post(server, raw=None, *, token=TOKEN, path="/v1/chat/completions", method="POST"):
    url = urlsplit(server.base_url)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
    try:
        connection.request(
            method,
            path,
            body=raw if raw is not None else json.dumps(BODY),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _request(directory, number=1):
    path = directory / f"request-{number:06d}.request.json"
    deadline = time.monotonic() + 2
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    return json.loads(path.read_text())


def _reply(directory, request, **updates):
    reply = {
        "request_id": request["request_id"],
        "request_fingerprint": request["request_fingerprint"],
        "source": "subagent-session",
        "author_reference": "agent/test-model-role",
        "declared_model_label": None,
        "content": '{"native":"response\\nexact"}',
    }
    reply.update(updates)
    path = directory / f"{request['request_id']}.reply.json"
    temporary = path.with_suffix(".temporary")
    temporary.write_text(json.dumps(reply))
    temporary.rename(path)
    return reply


@pytest.mark.parametrize("versioned", [False, True])
def test_actual_http_preserves_exact_native_body_and_unknown_usage(tmp_path, capsys, versioned):
    raw = json.dumps(BODY, ensure_ascii=False, indent=3).encode()
    with FrameworkSessionHTTPServer(tmp_path, token=TOKEN, wait_seconds=2) as server:
        assert server.base_url.startswith("http://127.0.0.1:")
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_post, server, raw)
            request = _request(tmp_path)
            assert request["request_body"] == BODY
            assert request["raw_body_utf8"].encode() == raw
            assert request["request_fingerprint"] == hashlib.sha256(raw).hexdigest()
            reply = _reply(tmp_path, request, **({"schema_version": "1.0"} if versioned else {}))
            status, response = pending.result(timeout=3)
    assert status == 200
    assert response["model"] == "session-authored"
    assert response["choices"][0]["message"]["content"] == reply["content"]
    assert "usage" not in response
    receipt = json.loads((tmp_path / "request-000001.receipt.json").read_text())
    assert receipt["status"] == "completed"
    assert receipt["actual_input_tokens"] is None
    assert receipt["actual_output_tokens"] is None
    assert receipt["session_cost_usd"] is None
    assert receipt["api_calls"] == 0
    assert receipt["author_reference"] == reply["author_reference"]
    capture = json.loads((tmp_path / receipt["reply_capture"]).read_text())
    assert json.loads(capture["raw_utf8"]) == reply
    assert capture["sha256"] == hashlib.sha256(capture["raw_utf8"].encode()).hexdigest()
    assert receipt["consumed_reply_sha256"] == capture["sha256"]
    assert all(TOKEN not in path.read_text() for path in tmp_path.iterdir())
    assert capsys.readouterr().err == ""


def test_identical_concurrent_requests_and_restart_have_distinct_persistent_ids(tmp_path):
    with FrameworkSessionHTTPServer(
        tmp_path, token=TOKEN, wait_seconds=2, max_requests=3
    ) as server:
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = [executor.submit(_post, server) for _ in range(2)]
            requests = [_request(tmp_path, index) for index in (1, 2)]
            assert requests[0]["request_fingerprint"] == requests[1]["request_fingerprint"]
            assert requests[0]["request_id"] != requests[1]["request_id"]
            for request in requests:
                _reply(tmp_path, request)
            assert all(result.result(timeout=3)[0] == 200 for result in pending)
    with FrameworkSessionHTTPServer(
        tmp_path, token=TOKEN, wait_seconds=0, max_requests=3
    ) as server:
        assert _post(server)[0] == 504
        assert _request(tmp_path, 3)["request_id"] == "request-000003"
        assert _post(server)[0] == 429
    assert len(list(tmp_path.glob("*.request.json"))) == 3


def test_invalid_http_requests_do_not_create_evidence(tmp_path):
    with FrameworkSessionHTTPServer(
        tmp_path, token=TOKEN, wait_seconds=0, max_body_bytes=1024
    ) as server:
        assert _post(server, token="wrong-secret")[0] == 401
        assert _post(server, path="/v1/responses")[0] == 404
        assert _post(server, method="GET")[0] == 405
        assert _post(server, raw=b"x" * 1025)[0] == 413
        assert _post(server, raw=b'{"messages": [], "model":"a", "model":"b"}')[0] == 400
        assert _post(server, raw=b'{"messages": [], "model":"a", "x":NaN}')[0] == 400
        assert _post(server, raw=json.dumps({**BODY, "stream": True}))[0] == 400
        assert _post(server, raw=json.dumps({**BODY, "credential": TOKEN}))[0] == 400
    assert not list(tmp_path.glob("*.request.json"))


@pytest.mark.parametrize(
    "updates",
    [
        {"request_fingerprint": "0" * 64},
        {"request_id": "request-000002"},
        {"source": "assistant-session"},
        {"declared_model_label": "invented-provider-model"},
        {"schema_version": "2.0"},
        {"extra_unrecognized_field": True},
    ],
)
def test_unbound_or_false_provenance_reply_fails_closed(tmp_path, updates):
    with FrameworkSessionHTTPServer(tmp_path, token=TOKEN, wait_seconds=2) as server:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_post, server)
            _reply(tmp_path, _request(tmp_path), **updates)
            assert pending.result(timeout=3)[0] == 422
    receipt = json.loads((tmp_path / "request-000001.receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["error"] == "invalid_or_unbound_session_reply"


def test_reply_size_cap_and_stop_interrupt_wait(tmp_path):
    with FrameworkSessionHTTPServer(
        tmp_path, token=TOKEN, wait_seconds=2, max_reply_bytes=10
    ) as server:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_post, server)
            _reply(tmp_path, _request(tmp_path))
            assert pending.result(timeout=3)[0] == 413
    with FrameworkSessionHTTPServer(tmp_path, token=TOKEN, wait_seconds=60) as server:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_post, server)
            _request(tmp_path, 2)
            server.stop()
            assert pending.result(timeout=3)[0] == 503


@pytest.mark.parametrize(
    "settings",
    [
        {"token": "short"},
        {"token": TOKEN + "\n"},
        {"wait_seconds": float("inf")},
        {"max_requests": 0},
        {"max_body_bytes": -1},
        {"max_reply_bytes": 0},
    ],
)
def test_invalid_server_limits(tmp_path, settings):
    with pytest.raises(ValueError):
        FrameworkSessionHTTPServer(tmp_path, **{"token": TOKEN, **settings})
