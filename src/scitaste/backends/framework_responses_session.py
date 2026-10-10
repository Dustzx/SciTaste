"""Native coding-CLI transport: session authors emit model items, not tool results."""

from __future__ import annotations

import time

from scitaste.backends.framework_session_http import (
    FrameworkSessionHTTPServer,
    _decode,
    _TransportError,
)


def _tool_names(tools):
    names = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "namespace":
            for name in _tool_names(tool.get("tools", [])):
                names.add(name)
                names.add(f"{tool.get('name')}.{name}")
        elif tool.get("type") in {"function", "custom"} and isinstance(tool.get("name"), str):
            names.add(tool["name"])
    return names


class FrameworkResponsesSessionServer(FrameworkSessionHTTPServer):
    """Responses SSE plus legacy chat on the same local, authenticated queue.

    Replies for Responses contain JSON ``{"output": [message/tool-call items]}``.
    The server never executes a tool: actual Codex owns tool dispatch, sandboxing,
    retry, code edits and commands. Unknown usage stays null, not synthetic zero.
    Native MLR's legacy SDK receives nullable usage fields solely for compatibility.
    """

    def _validate_body(self, path, body):
        if path == "/v1/chat/completions":
            return super()._validate_body(path, body)
        if path != "/v1/responses":
            raise _TransportError(404, "unsupported_route")
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("model"), str)
            or not isinstance(body.get("input"), (str, list))
            or body.get("stream") not in (None, False, True)
            or not isinstance(body.get("tools", []), list)
        ):
            raise _TransportError(400, "invalid_responses_request")
        if body.get("previous_response_id"):
            raise _TransportError(400, "stateful_response_lookup_not_supported")

    def _response(self, request, reply):
        body = request["request_body"]
        if "messages" in body:
            result = super()._response(request, reply)
            result["usage"] = {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }
            return result
        try:
            payload = _decode(reply["content"].encode())
        except (ValueError, UnicodeError):
            raise _TransportError(422, "responses_reply_requires_json_output") from None
        if not isinstance(payload, dict) or set(payload) != {"output"}:
            raise _TransportError(422, "invalid_responses_reply")
        output = payload["output"]
        if not isinstance(output, list) or not 1 <= len(output) <= 16:
            raise _TransportError(422, "invalid_responses_output_count")
        names = _tool_names(body.get("tools", []))
        call_ids = set()
        normalized = []
        for index, raw in enumerate(output):
            if not isinstance(raw, dict):
                raise _TransportError(422, "invalid_responses_output_item")
            item = dict(raw)
            kind = item.get("type")
            if kind == "message":
                if item.get("role", "assistant") != "assistant" or not isinstance(
                    item.get("content"), list
                ):
                    raise _TransportError(422, "invalid_response_message")
                content = []
                for part in item["content"]:
                    if (
                        not isinstance(part, dict)
                        or part.get("type") != "output_text"
                        or not isinstance(part.get("text"), str)
                    ):
                        raise _TransportError(422, "invalid_response_text")
                    content.append({"type": "output_text", "text": part["text"], "annotations": []})
                item.update(role="assistant", content=content)
            elif kind in {"function_call", "custom_tool_call"}:
                field = "arguments" if kind == "function_call" else "input"
                if (
                    item.get("name") not in names
                    or not isinstance(item.get(field), str)
                    or not isinstance(item.get("call_id"), str)
                    or not item["call_id"]
                    or item["call_id"] in call_ids
                ):
                    raise _TransportError(422, "unbound_response_tool_call")
                call_ids.add(item["call_id"])
                if kind == "function_call":
                    try:
                        arguments = _decode(item[field].encode())
                    except (ValueError, UnicodeError):
                        raise _TransportError(422, "invalid_tool_arguments") from None
                    if not isinstance(arguments, dict):
                        raise _TransportError(422, "invalid_tool_arguments")
            else:
                raise _TransportError(422, "model_output_not_message_or_tool_request")
            item["id"] = f"item_{request['request_id']}_{index}"
            item["status"] = "completed"
            normalized.append(item)
        return {
            "id": f"resp_{request['request_id']}",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": "session-authored",
            "output": normalized,
            "usage": None,
            "error": None,
            "incomplete_details": None,
        }

    def _wire_events(self, request, response):
        if "messages" in request["request_body"] or not request["request_body"].get("stream"):
            return None
        events = [
            {
                "type": "response.created",
                "response": {**response, "status": "in_progress", "output": []},
            }
        ]
        for index, item in enumerate(response["output"]):
            empty = dict(item)
            if item["type"] == "message":
                empty["content"] = []
            elif item["type"] == "function_call":
                empty["arguments"] = ""
            else:
                empty["input"] = ""
            empty["status"] = "in_progress"
            events.append(
                {"type": "response.output_item.added", "output_index": index, "item": empty}
            )
            if item["type"] == "message":
                for part_index, part in enumerate(item["content"]):
                    common = {
                        "item_id": item["id"],
                        "output_index": index,
                        "content_index": part_index,
                    }
                    events += [
                        {
                            "type": "response.content_part.added",
                            **common,
                            "part": {**part, "text": ""},
                        },
                        {"type": "response.output_text.delta", **common, "delta": part["text"]},
                        {"type": "response.output_text.done", **common, "text": part["text"]},
                        {"type": "response.content_part.done", **common, "part": part},
                    ]
            events.append(
                {"type": "response.output_item.done", "output_index": index, "item": item}
            )
        events.append({"type": "response.completed", "response": response})
        return [{**event, "sequence_number": number} for number, event in enumerate(events)]
