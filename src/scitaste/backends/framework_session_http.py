"""Loopback-only model transport; the upstream framework retains all control flow.

Every HTTP call is a distinct, durable request, including identical retries. A
session author supplies ``<request_id>.reply.json`` with request_id,
request_fingerprint, source="subagent-session", author_reference,
declared_model_label=null, and content. Publish replies atomically.
The optional schema_version="1.0" is envelope metadata, never model content.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite JSON number")


def _decode(raw: bytes):
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_invalid_constant
    )


def _publish(path: Path, value: dict):
    """Publish complete, immutable evidence without exposing partially written JSON."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class _TransportError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


class FrameworkSessionHTTPServer:
    """Authenticated local chat-completions endpoint with bounded session waits.

    ``base_url`` becomes available after ``start()`` or context-manager entry.
    ``max_requests`` applies to all retained requests in this directory across
    restarts. No outbound networking, provider fallback, or inferred token usage.
    """

    def __init__(
        self,
        directory: Path,
        *,
        token: str,
        max_requests: int = 100,
        wait_seconds: float = 300,
        max_body_bytes: int = 4_000_000,
        max_reply_bytes: int = 4_000_000,
        evaluator_feedback: Path | None = None,
    ):
        if not isinstance(token, str) or len(token) < 16 or not token.isascii():
            raise ValueError("A nonempty ASCII bearer token of at least 16 characters is required")
        if any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ValueError("Bearer token must contain only printable non-space ASCII")
        if (
            not math.isfinite(wait_seconds)
            or not 0 <= wait_seconds <= 86400
            or any(
                type(value) is not int or value < 1
                for value in (max_requests, max_body_bytes, max_reply_bytes)
            )
        ):
            raise ValueError("Invalid session request, byte, or wait budget")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_requests = max_requests
        self.wait_seconds = wait_seconds
        self.max_body_bytes = max_body_bytes
        self.max_reply_bytes = max_reply_bytes
        # Opt-in benchmark attachment from the trusted evaluator's private
        # service directory, never the mutable researcher workspace copy.
        self.evaluator_feedback = evaluator_feedback
        self._authorization = f"Bearer {token}".encode("ascii")
        self._stopped = threading.Event()
        self._allocation_lock = threading.Lock()
        self._server = None
        self._thread = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Session HTTP server has not started")
        return f"http://127.0.0.1:{self._server.server_port}/v1"

    def start(self) -> FrameworkSessionHTTPServer:
        if self._server is not None:
            raise RuntimeError("Session HTTP server already started")
        self._stopped.clear()
        transport = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Never log headers, credentials, prompts, or responses.

            def do_POST(self):
                request = None
                try:
                    authorization = self.headers.get("Authorization", "").encode("utf-8")
                    if not hmac.compare_digest(authorization, transport._authorization):
                        raise _TransportError(401, "authentication_required")
                    lengths = self.headers.get_all("Content-Length", [])
                    if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                        raise _TransportError(400, "content_length_required")
                    try:
                        length = int(lengths[0])
                    except ValueError:
                        raise _TransportError(400, "invalid_content_length") from None
                    if not 0 < length <= transport.max_body_bytes:
                        raise _TransportError(413, "request_body_limit")
                    self.connection.settimeout(min(10, max(1, transport.wait_seconds)))
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise _TransportError(400, "incomplete_request_body")
                    try:
                        body = _decode(raw)
                    except (ValueError, UnicodeError, RecursionError):
                        raise _TransportError(400, "invalid_request_json") from None
                    transport._validate_body(self.path, body)
                    if transport._authorization[7:] in raw:
                        raise _TransportError(400, "credential_in_request_body")
                    request = transport._allocate(raw, body)
                    reply = transport._wait_reply(request)
                    response = transport._response(request, reply)
                    transport._receipt(request, "completed", reply=reply)
                    events = transport._wire_events(request, response)
                    if events is None:
                        self._send(200, response)
                    else:
                        self._send_events(events)
                except _TransportError as error:
                    if request is not None:
                        transport._receipt(request, "failed", error=error.code)
                    self._send(
                        error.status,
                        {"error": {"message": error.code, "type": "session_transport_error"}},
                    )
                except (OSError, ValueError, RecursionError):
                    self._send(500, {"error": {"message": "session_transport_failed"}})

            def _send(self, status, payload):
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                except OSError:
                    pass  # Disconnected client; retained receipt remains authoritative.

            def _unsupported(self):
                self._send(405, {"error": {"message": "unsupported_method"}})

            def _send_events(self, events):
                encoded = "".join(
                    f"event: {event['type']}\ndata: "
                    + json.dumps(event, ensure_ascii=False)
                    + "\n\n"
                    for event in events
                ).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                except OSError:
                    pass

            do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _unsupported

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def _validate_body(self, path, body):
        if path != "/v1/chat/completions":
            raise _TransportError(404, "unsupported_route")
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("model"), str)
            or not isinstance(body.get("messages"), list)
        ):
            raise _TransportError(400, "invalid_chat_request")
        if body.get("stream") not in (None, False):
            raise _TransportError(400, "streaming_not_supported")

    def _response(self, request, reply):
        return {
            "id": request["request_id"],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "session-authored",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply["content"]},
                    "finish_reason": "stop",
                }
            ],
        }

    def _wire_events(self, request, response):
        return None

    def stop(self):
        self._stopped.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)
            self._server = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def _allocate(self, raw, body):
        with self._allocation_lock, (self.directory / ".allocation.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ids = [
                int(match.group(1))
                for path in self.directory.glob("*.request.json")
                if (match := re.fullmatch(r"request-(\d+)\.request\.json", path.name))
            ]
            if len(ids) >= self.max_requests:
                raise _TransportError(429, "session_request_budget_exhausted")
            request_id = f"request-{max(ids, default=0) + 1:06d}"
            evidence = None
            if self.evaluator_feedback is not None and self.evaluator_feedback.exists():
                path = self.evaluator_feedback
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
                    raise _TransportError(500, "invalid_evaluator_feedback")
                payload = path.read_bytes()
                try:
                    value = _decode(payload)
                except ValueError:
                    raise _TransportError(503, "evaluator_feedback_not_ready") from None
                if (
                    not isinstance(value, dict)
                    or value.get("status") not in {"completed", "failed"}
                    or value.get("arm") != "autoresearchclaw"
                ):
                    raise _TransportError(500, "invalid_evaluator_feedback")
                projection = None
                if len(payload) > 250_000:
                    from scitaste.review.evidence_projection import aggregate_confirmation_view

                    try:
                        visible = aggregate_confirmation_view(payload)
                    except (ValueError, KeyError, TypeError):
                        raise _TransportError(500, "invalid_evaluator_feedback") from None
                    if len(visible) > 250_000:
                        raise _TransportError(500, "invalid_evaluator_feedback")
                    value = _decode(visible)
                    projection = {
                        "version": "complete-aggregate-view.v1",
                        "original_utf8_bytes": len(payload),
                        "visible_utf8_bytes": len(visible),
                        "visible_sha256": hashlib.sha256(visible).hexdigest(),
                        "unit_level_display_omitted": True,
                    }
                if len(raw) + len(json.dumps(value).encode()) > self.max_body_bytes:
                    raise _TransportError(413, "request_body_limit")
                evidence = {
                    "receipt_sha256": hashlib.sha256(payload).hexdigest(),
                    "record": value,
                    "scope": "Common evaluator aggregate outcome supplied after source freeze. "
                    "No private labels, source edits, extra experiment or scientific advice. "
                    "This opt-in evidence transport does not replace native framework control.",
                    **({"projection": projection} if projection else {}),
                }
            request = {
                "schema_version": "1.0",
                "request_id": request_id,
                "request_fingerprint": hashlib.sha256(raw).hexdigest(),
                "request_body": body,
                "raw_body_utf8": raw.decode("utf-8"),
            }
            if evidence is not None:
                request["common_evaluator_feedback"] = evidence
                request["upstream_request_fingerprint"] = request["request_fingerprint"]
                request["request_fingerprint"] = hashlib.sha256(
                    raw + json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
            _publish(self.directory / f"{request_id}.request.json", request)
            return request

    def _wait_reply(self, request):
        path = self.directory / f"{request['request_id']}.reply.json"
        deadline = time.monotonic() + self.wait_seconds
        while not path.exists():
            if self._stopped.is_set():
                raise _TransportError(503, "session_transport_stopped")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _TransportError(504, "session_reply_timeout")
            self._stopped.wait(min(0.05, remaining))
        with path.open("rb") as stream:
            raw = stream.read(self.max_reply_bytes + 1)
        if len(raw) > self.max_reply_bytes:
            raise _TransportError(413, "session_reply_limit")
        # Preserve the bytes actually consumed, not a later re-read of a mutable
        # author file. Both valid and rejected UTF-8 envelopes keep this preimage.
        try:
            consumed_text = raw.decode("utf-8")
        except UnicodeError:
            raise _TransportError(422, "invalid_session_reply_json") from None
        _publish(
            self.directory / f"{request['request_id']}.consumed-reply.json",
            {
                "reply_file": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "utf8_bytes": len(raw),
                "raw_utf8": consumed_text,
            },
        )
        try:
            reply = _decode(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise _TransportError(422, "invalid_session_reply_json") from None
        fields = {
            "request_id",
            "request_fingerprint",
            "source",
            "author_reference",
            "declared_model_label",
            "content",
        }
        if isinstance(reply, dict) and reply.get("schema_version") == "1.0":
            reply = {key: value for key, value in reply.items() if key != "schema_version"}
        if (
            not isinstance(reply, dict)
            or set(reply) != fields
            or reply["request_id"] != request["request_id"]
            or reply["request_fingerprint"] != request["request_fingerprint"]
            or reply["source"] != "subagent-session"
            or reply["declared_model_label"] is not None
            or not isinstance(reply["author_reference"], str)
            or not 1 <= len(reply["author_reference"].strip()) <= 500
            or not isinstance(reply["content"], str)
        ):
            raise _TransportError(422, "invalid_or_unbound_session_reply")
        return reply

    def _receipt(self, request, status, *, reply=None, error=None):
        capture_path = self.directory / f"{request['request_id']}.consumed-reply.json"
        capture = _decode(capture_path.read_bytes()) if capture_path.exists() else None
        _publish(
            self.directory / f"{request['request_id']}.receipt.json",
            {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "request_fingerprint": request["request_fingerprint"],
                "status": status,
                "source": "subagent-session",
                "model": "session-authored",
                "author_reference": reply["author_reference"] if reply else None,
                "declared_model_label": None,
                "model_identity_verified": False,
                "actual_input_tokens": None,
                "actual_output_tokens": None,
                "session_cost_usd": None,
                "api_calls": 0,
                "error": error,
                "consumed_reply_sha256": capture["sha256"] if capture else None,
                "reply_capture": capture_path.name if capture else None,
                "reply_capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest()
                if capture
                else None,
                "usage_semantics": "unavailable; upstream parser may default missing usage to zero",
            },
        )
