"""Loopback-only OpenAI-compatible bridge for an explicit local checkpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scitaste.backends.local_transformers import LocalGeneration

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_CHAT_PATHS = {"/chat/completions", "/v1/chat/completions"}


class LocalChatMessage(BaseModel):
    model_config = _MODEL_CONFIG

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=1_000_000)


class LocalResponseFormat(BaseModel):
    model_config = _MODEL_CONFIG

    type: Literal["text", "json_object"]


class LocalChatCompletionRequest(BaseModel):
    """The narrow Chat Completions subset consumed by the study adapter."""

    model_config = _MODEL_CONFIG

    model: str = Field(min_length=1, max_length=256)
    messages: tuple[LocalChatMessage, ...] = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    stream: Literal[False] = False
    response_format: LocalResponseFormat | None = None
    enable_thinking: Literal[False] = False

    @model_validator(mode="after")
    def one_output_limit(self) -> LocalChatCompletionRequest:
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("choose one output-token field")
        return self

    @property
    def requested_output_tokens(self) -> int:
        return self.max_tokens or self.max_completion_tokens or 512


class LocalChatServerConfig(BaseModel):
    """Fixed loopback identity and byte/token ceilings for one local bridge."""

    model_config = _MODEL_CONFIG

    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)
    model_aliases: tuple[str, ...] = Field(min_length=1, max_length=8)
    max_request_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    max_output_tokens: int = Field(default=2048, ge=1, le=8192)

    @model_validator(mode="after")
    def aliases_are_unique(self) -> LocalChatServerConfig:
        if any(not item or item != item.strip() for item in self.model_aliases):
            raise ValueError("model aliases must be non-empty canonical strings")
        if len(set(self.model_aliases)) != len(self.model_aliases):
            raise ValueError("model aliases must be unique")
        return self


@runtime_checkable
class LocalChatGenerationRuntime(Protocol):
    def generate_messages(
        self,
        *,
        messages: list[dict[str, str]],
        seed: int,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> LocalGeneration: ...


class _LocalChatHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        runtime: LocalChatGenerationRuntime,
        config: LocalChatServerConfig,
        bearer_token: str,
    ) -> None:
        self.runtime = runtime
        self.config = config
        self.expected_authorization = f"Bearer {_validate_token(bearer_token)}".encode()
        self.inference_lock = threading.Lock()
        super().__init__(address, _LocalChatRequestHandler)


class _LocalChatIPv6HTTPServer(_LocalChatHTTPServer):
    address_family = socket.AF_INET6


class _LocalChatRequestHandler(BaseHTTPRequestHandler):
    server: _LocalChatHTTPServer
    server_version = "SciTasteLocalChat/1.0"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: object) -> None:
        """Suppress prompts, paths, headers, and credentials from default logs."""

    def do_GET(self) -> None:
        self._problem(HTTPStatus.NOT_FOUND, "not_found", "resource not found")

    def do_POST(self) -> None:
        if self.path not in _CHAT_PATHS:
            self._problem(HTTPStatus.NOT_FOUND, "not_found", "resource not found")
            return
        authorizations = self.headers.get_all("Authorization", [])
        candidate = b"" if len(authorizations) != 1 else authorizations[0].encode("utf-8")
        if not hmac.compare_digest(candidate, self.server.expected_authorization):
            self._problem(HTTPStatus.UNAUTHORIZED, "unauthorized", "valid bearer required")
            return
        try:
            request = self._request()
            if request.model not in self.server.config.model_aliases:
                raise ValueError("requested model does not match the local checkpoint")
            if request.requested_output_tokens > self.server.config.max_output_tokens:
                raise ValueError("requested output exceeds the local server ceiling")
            messages = [item.model_dump(mode="json") for item in request.messages]
            if (
                request.response_format is not None
                and request.response_format.type == "json_object"
            ):
                messages = _require_json_response(messages)
            seed = request.seed if request.seed is not None else _deterministic_seed(request)
            with self.server.inference_lock:
                generated = self.server.runtime.generate_messages(
                    messages=messages,
                    seed=seed,
                    max_new_tokens=request.requested_output_tokens,
                    temperature=request.temperature,
                )
            self._completion(request, generated)
        except _RequestTooLarge:
            self._problem(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "request_too_large",
                "request exceeds the local server byte ceiling",
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
            self._problem(HTTPStatus.BAD_REQUEST, "invalid_request", "request is invalid")
        except Exception:
            self._problem(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "inference_failed",
                "local inference failed",
            )

    def _request(self) -> LocalChatCompletionRequest:
        if self.headers.get("Transfer-Encoding") is not None:
            raise ValueError("transfer encoding is unsupported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise ValueError("one content length is required")
        length = int(lengths[0])
        if length < 1:
            raise ValueError("request body is empty")
        if length > self.server.config.max_request_bytes:
            raise _RequestTooLarge
        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().casefold() != (
            "application/json"
        ):
            raise ValueError("application/json content type is required")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("request body was truncated")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        return LocalChatCompletionRequest.model_validate(payload)

    def _completion(
        self,
        request: LocalChatCompletionRequest,
        generated: LocalGeneration,
    ) -> None:
        identity = hashlib.sha256(
            f"{request.model}\0{generated.input_tokens}\0{generated.text}".encode()
        ).hexdigest()[:24]
        finish_reason = (
            "length" if generated.output_tokens >= request.requested_output_tokens else "stop"
        )
        self._json(
            HTTPStatus.OK,
            {
                "id": f"chatcmpl-local-{identity}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": generated.text},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": generated.input_tokens,
                    "completion_tokens": generated.output_tokens,
                    "total_tokens": generated.input_tokens + generated.output_tokens,
                },
            },
        )

    def _problem(self, status: HTTPStatus, code: str, message: str) -> None:
        self._json(status, {"error": {"type": code, "message": message}})

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


class _RequestTooLarge(ValueError):
    pass


@contextmanager
def local_chat_server(
    runtime: LocalChatGenerationRuntime,
    *,
    config: LocalChatServerConfig,
    bearer_token: str,
) -> Iterator[str]:
    """Serve one explicit runtime on loopback and return its versioned base URL."""

    if not isinstance(runtime, LocalChatGenerationRuntime):
        raise TypeError("runtime must implement LocalChatGenerationRuntime")
    parsed = LocalChatServerConfig.model_validate(config.model_dump(mode="json"))
    server_type = _LocalChatIPv6HTTPServer if parsed.host == "::1" else _LocalChatHTTPServer
    server = server_type(
        (parsed.host, parsed.port),
        runtime=runtime,
        config=parsed,
        bearer_token=bearer_token,
    )
    thread = threading.Thread(target=server.serve_forever, name="scitaste-local-chat", daemon=True)
    thread.start()
    bound_port = int(server.server_address[1])
    host = f"[{parsed.host}]" if ":" in parsed.host else parsed.host
    try:
        yield f"http://{host}:{bound_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _require_json_response(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    instruction = "Return valid JSON only, without Markdown fences or surrounding commentary."
    copied = [dict(item) for item in messages]
    if copied and copied[0]["role"] == "system":
        copied[0]["content"] = f"{instruction}\n\n{copied[0]['content']}"
    else:
        copied.insert(0, {"role": "system", "content": instruction})
    return copied


def _deterministic_seed(request: LocalChatCompletionRequest) -> int:
    payload = request.model_dump(mode="json", exclude={"seed"})
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return int(hashlib.sha256(canonical.encode()).hexdigest()[:8], 16)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _validate_token(token: str) -> str:
    if not isinstance(token, str) or token != token.strip() or len(token) < 24 or len(token) > 512:
        raise ValueError("local bearer token must contain 24 to 512 canonical characters")
    if any(ord(character) < 33 or ord(character) == 127 for character in token):
        raise ValueError("local bearer token contains invalid characters")
    return token


__all__ = [
    "LocalChatCompletionRequest",
    "LocalChatGenerationRuntime",
    "LocalChatMessage",
    "LocalChatServerConfig",
    "local_chat_server",
]
