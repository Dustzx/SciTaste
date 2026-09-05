"""Loopback-first HTTP receiver for the trusted generative UI application."""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit

from pydantic import ValidationError

from scitaste.generative_ui.application import GenerativeUIApplication
from scitaste.generative_ui.audit import AuditIntegrityError
from scitaste.generative_ui.factory import ProjectSurfaceChangedError, ProjectSurfaceError
from scitaste.generative_ui.interaction import (
    DuplicateEventError,
    StaleSurfaceError,
    SurfaceInteractionError,
    UnknownActionError,
)

_LOGGER = logging.getLogger(__name__)
_MAX_EVENT_BYTES = 64 * 1024
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    ),
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_PUBLIC_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


@dataclass(frozen=True)
class LocalServerConfig:
    """Validated bind configuration with explicit non-loopback acknowledgement."""

    host: str = "127.0.0.1"
    port: int = 8765
    unsafe_allow_non_loopback: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host or self.host != self.host.strip():
            raise ValueError("server host must be a non-empty canonical value")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise TypeError("server port must be an integer")
        if self.port < 0 or self.port > 65535:
            raise ValueError("server port must be between 0 and 65535")
        if not _is_loopback_host(self.host) and not self.unsafe_allow_non_loopback:
            raise ValueError("non-loopback host requires explicit unsafe exposure acknowledgement")

    @property
    def is_loopback(self) -> bool:
        return _is_loopback_host(self.host)


class BearerCredential:
    """Constant-time comparison for one memory-only bearer credential."""

    __slots__ = ("_expected",)

    def __init__(self, token: str) -> None:
        self._expected = f"Bearer {_validate_token(token)}".encode()

    def accepts(self, authorization: str | None) -> bool:
        candidate = b"" if authorization is None else authorization.encode("utf-8")
        return hmac.compare_digest(candidate, self._expected)


class GenerativeUIHTTPServer(ThreadingHTTPServer):
    """Threaded server whose receiver and credential remain server-owned."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        application: GenerativeUIApplication,
        credential: BearerCredential,
    ) -> None:
        self.application = application
        self.credential = credential
        super().__init__(server_address, GenerativeUIRequestHandler)


class _GenerativeUIIPv6HTTPServer(GenerativeUIHTTPServer):
    address_family = socket.AF_INET6


class GenerativeUIRequestHandler(BaseHTTPRequestHandler):
    """Serve fixed assets and the closed v1 JSON API."""

    server: GenerativeUIHTTPServer

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def log_message(self, format: str, *args: object) -> None:
        """Do not emit request paths or headers through the default stderr logger."""

    def _dispatch(self, method: str) -> None:
        try:
            path = _request_path(self.path)
            if method == "GET" and path in _PUBLIC_ASSETS:
                self._serve_public_asset(path)
                return
            if not path.startswith("/api/"):
                raise _HTTPProblem(HTTPStatus.NOT_FOUND, "not_found", "resource not found")
            if not self.server.credential.accepts(self.headers.get("Authorization")):
                raise _HTTPProblem(
                    HTTPStatus.UNAUTHORIZED,
                    "unauthorized",
                    "valid bearer authentication is required",
                )
            self._dispatch_api(method, path)
        except _HTTPProblem as exc:
            self._send_problem(exc)
        except DuplicateEventError:
            self._send_problem(
                _HTTPProblem(
                    HTTPStatus.CONFLICT,
                    "duplicate_event",
                    "event was already accepted",
                )
            )
        except (StaleSurfaceError, UnknownActionError, ProjectSurfaceChangedError):
            self._send_problem(
                _HTTPProblem(
                    HTTPStatus.CONFLICT,
                    "stale_surface",
                    "event does not match the current trusted surface",
                )
            )
        except SurfaceInteractionError:
            self._send_problem(
                _HTTPProblem(
                    HTTPStatus.CONFLICT,
                    "interaction_rejected",
                    "surface interaction was rejected",
                )
            )
        except FileNotFoundError:
            self._send_problem(
                _HTTPProblem(HTTPStatus.NOT_FOUND, "project_not_found", "project was not found")
            )
        except (AuditIntegrityError, ProjectSurfaceError, OSError):
            _LOGGER.exception("trusted generative UI request failed closed")
            self._send_problem(
                _HTTPProblem(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "trusted_state_unavailable",
                    "trusted project state is unavailable",
                )
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError):
            self._send_problem(
                _HTTPProblem(HTTPStatus.BAD_REQUEST, "invalid_request", "request is invalid")
            )

    def _dispatch_api(self, method: str, path: str) -> None:
        if path == "/api/v1/projects":
            if method != "GET":
                raise _method_not_allowed("GET")
            self._send_model(HTTPStatus.OK, self.server.application.discover_projects())
            return

        parts = path.strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["api", "v1", "projects"]:
            raise _HTTPProblem(HTTPStatus.NOT_FOUND, "not_found", "resource not found")
        project_id, resource = parts[3], parts[4]
        if resource == "surface":
            if method != "GET":
                raise _method_not_allowed("GET")
            self._send_model(
                HTTPStatus.OK,
                self.server.application.current_renderer(project_id),
            )
            return
        if resource == "events":
            if method != "POST":
                raise _method_not_allowed("POST")
            payload = self._read_json_object()
            receipt = self.server.application.submit_event(project_id, payload)
            self._send_model(HTTPStatus.ACCEPTED, receipt)
            return
        raise _HTTPProblem(HTTPStatus.NOT_FOUND, "not_found", "resource not found")

    def _read_json_object(self) -> dict[str, object]:
        if self.headers.get("Transfer-Encoding") is not None:
            raise _HTTPProblem(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "transfer encoding is not supported",
            )
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise _HTTPProblem(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "unsupported_media_type",
                "event requests require application/json",
            )
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdecimal():
            raise _HTTPProblem(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "a valid content length is required",
            )
        length = int(raw_length)
        if length > _MAX_EVENT_BYTES:
            raise _HTTPProblem(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "request_too_large",
                "event request is too large",
            )
        payload = json.loads(
            self.rfile.read(length).decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
        if not isinstance(payload, dict):
            raise ValueError("event request must be a JSON object")
        return payload

    def _serve_public_asset(self, path: str) -> None:
        asset_name, content_type = _PUBLIC_ASSETS[path]
        content = files("scitaste.generative_ui").joinpath("static", asset_name).read_bytes()
        self._send_bytes(HTTPStatus.OK, content, content_type)

    def _send_model(self, status: HTTPStatus, model: Any) -> None:
        payload = model.model_dump(mode="json")
        content = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self._send_bytes(status, content, "application/json; charset=utf-8")

    def _send_problem(self, problem: _HTTPProblem) -> None:
        content = json.dumps(
            {
                "error": {
                    "code": problem.code,
                    "message": problem.message,
                },
                "schema_version": "1.0",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        extra = {"WWW-Authenticate": "Bearer"} if problem.status == 401 else None
        self._send_bytes(
            problem.status,
            content,
            "application/json; charset=utf-8",
            extra_headers=extra,
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        content: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)


@dataclass(frozen=True)
class _HTTPProblem(Exception):
    status: HTTPStatus
    code: str
    message: str


def create_http_server(
    application: GenerativeUIApplication,
    *,
    credential: BearerCredential,
    config: LocalServerConfig | None = None,
) -> GenerativeUIHTTPServer:
    """Create but do not start a validated local HTTP server."""

    config = config or LocalServerConfig()
    server_type: type[GenerativeUIHTTPServer] = GenerativeUIHTTPServer
    try:
        if ipaddress.ip_address(config.host).version == 6:
            server_type = _GenerativeUIIPv6HTTPServer
    except ValueError:
        pass
    return server_type((config.host, config.port), application, credential)


def serve_local_application(
    application: GenerativeUIApplication,
    *,
    credential: BearerCredential,
    config: LocalServerConfig | None = None,
) -> None:
    """Run the receiver until interrupted, closing its listening socket on exit."""

    server = create_http_server(application, credential=credential, config=config)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _request_path(target: str) -> str:
    parsed = urlsplit(target)
    if parsed.query or parsed.fragment:
        raise _HTTPProblem(
            HTTPStatus.BAD_REQUEST,
            "query_not_allowed",
            "query strings and fragments are not accepted",
        )
    try:
        path = unquote_to_bytes(parsed.path).decode("utf-8")
    except UnicodeDecodeError:
        raise
    if not path.startswith("/") or "\x00" in path or "//" in path:
        raise ValueError("request path is not canonical")
    return path


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object keys must be unique")
        result[key] = value
    return result


def _method_not_allowed(allowed: str) -> _HTTPProblem:
    return _HTTPProblem(
        HTTPStatus.METHOD_NOT_ALLOWED,
        "method_not_allowed",
        f"method is not allowed; use {allowed}",
    )


def _validate_token(token: str) -> str:
    if not isinstance(token, str):
        raise TypeError("bearer credential must be text")
    if len(token) < 16 or len(token) > 512:
        raise ValueError("bearer credential must contain between 16 and 512 characters")
    if not token.isascii() or any(
        ord(character) < 0x21 or ord(character) > 0x7E for character in token
    ):
        raise ValueError("bearer credential must contain visible ASCII without spaces")
    return token


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
