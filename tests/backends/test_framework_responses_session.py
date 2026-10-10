import json

import pytest

from scitaste.backends.framework_responses_session import FrameworkResponsesSessionServer
from scitaste.backends.framework_session_http import _TransportError


def test_native_coding_response_retains_tool_request_and_unknown_usage(tmp_path):
    server = FrameworkResponsesSessionServer(tmp_path, token="local-session-key-only")
    request = {
        "request_id": "request-000001",
        "request_body": {
            "model": "native-alias",
            "input": [],
            "stream": True,
            "tools": [{"type": "function", "name": "exec_command"}],
        },
    }
    server._validate_body("/v1/responses", request["request_body"])
    response = server._response(
        request,
        {
            "content": json.dumps(
                {
                    "output": [
                        {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": "call_1",
                            "arguments": '{"cmd":"python experiment.py"}',
                        }
                    ]
                }
            )
        },
    )
    assert response["usage"] is None
    assert response["output"][0]["arguments"] == '{"cmd":"python experiment.py"}'
    events = server._wire_events(request, response)
    assert events[-1]["type"] == "response.completed"
    assert events[1]["type"] == "response.output_item.added"
    assert not (tmp_path / "experiment.py").exists()
    with pytest.raises(_TransportError):
        server._response(
            request,
            {
                "content": json.dumps(
                    {
                        "output": [
                            {
                                "type": "function_call",
                                "name": "undeclared_tool",
                                "call_id": "call_2",
                                "arguments": "{}",
                            }
                        ]
                    }
                )
            },
        )


def test_legacy_usage_stays_null_and_model_cannot_insert_tool_results(tmp_path):
    server = FrameworkResponsesSessionServer(tmp_path, token="local-session-key-only")
    chat = server._response(
        {"request_id": "r", "request_body": {"messages": []}}, {"content": "idea"}
    )
    assert chat["usage"]["total_tokens"] is None
    with pytest.raises(_TransportError):
        server._response(
            {"request_id": "r", "request_body": {"input": [], "tools": []}},
            {"content": '{"output":[{"type":"function_call_output","output":"fake success"}]}'},
        )
