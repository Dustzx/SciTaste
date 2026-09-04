"""Validation helpers for non-executable declarative UI payloads."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Annotated, Any

from pydantic import AfterValidator, Field, JsonValue

_REMOTE_OR_ACTIVE_URI = re.compile(r"(?:https?|ftp|file|data|javascript|vbscript):", re.IGNORECASE)
_HTML_TAG = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.IGNORECASE)
_JAVASCRIPT = re.compile(
    r"(?:\b(?:document|window)\s*\.|\b(?:eval|function)\s*\(|<\s*script\b)",
    re.IGNORECASE,
)
_SHELL_META = re.compile(r"(?:&&|\|\||\$\(|`)")
_SHELL_COMMAND = re.compile(
    r"(?:^|[\s;|&])(?:sudo\s+)?"
    r"(?:bash|sh|zsh|fish|powershell|cmd(?:\.exe)?|rm|chmod|chown|curl|wget|"
    r"python(?:3(?:\.\d+)?)?|node|npm|git)\s+",
    re.IGNORECASE,
)
_TRAVERSAL = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
_WINDOWS_ABSOLUTE = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)
_DATA_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

_FORBIDDEN_KEYS = {
    "callback",
    "command",
    "endpoint",
    "executable",
    "href",
    "html",
    "inner_html",
    "javascript",
    "raw_html",
    "script",
    "shell",
    "shell_command",
    "src",
    "tool",
    "tool_name",
    "url",
}


def ensure_safe_text(value: str) -> str:
    """Reject executable, active-content, remote, or path-traversal strings."""

    if not value.strip():
        raise ValueError("text must not be blank")
    if _REMOTE_OR_ACTIVE_URI.search(value):
        raise ValueError("remote and active-content URIs are not allowed")
    if _HTML_TAG.search(value):
        raise ValueError("raw HTML is not allowed")
    if _JAVASCRIPT.search(value):
        raise ValueError("JavaScript is not allowed")
    if _SHELL_META.search(value) or _SHELL_COMMAND.search(value):
        raise ValueError("shell commands are not allowed")
    if _TRAVERSAL.search(value):
        raise ValueError("path traversal is not allowed")
    return value


def ensure_safe_locator(value: str) -> str:
    """Require a normalized project-relative artifact locator."""

    ensure_safe_text(value)
    if "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        raise ValueError("locator must be a POSIX project-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise ValueError("locator must be project-relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("locator must be normalized without traversal")
    return value


def validate_declarative_value(value: JsonValue, *, location: str = "data") -> JsonValue:
    """Recursively enforce the data-only component boundary."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if not _DATA_KEY.fullmatch(key):
                raise ValueError(f"{location} key {key!r} is not a safe declarative key")
            if normalized in _FORBIDDEN_KEYS:
                raise ValueError(f"{location} key {key!r} can carry executable content")
            if isinstance(child, str) and (
                normalized.endswith("_path") or normalized.endswith("_locator")
            ):
                ensure_safe_locator(child)
            validate_declarative_value(child, location=f"{location}.{key}")
        return value
    if isinstance(value, list):
        for index, child in enumerate(value):
            validate_declarative_value(child, location=f"{location}[{index}]")
        return value
    if isinstance(value, str):
        ensure_safe_text(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{location} contains a non-finite JSON number")
    return value


def contains_key(value: JsonValue, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in keys or contains_key(child, keys) for key, child in value.items())
    if isinstance(value, list):
        return any(contains_key(child, keys) for child in value)
    return False


SafeText = Annotated[str, Field(min_length=1, max_length=4000), AfterValidator(ensure_safe_text)]
SafeIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"),
]
ProjectIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SafeLocator = Annotated[
    str,
    Field(min_length=1, max_length=1000),
    AfterValidator(ensure_safe_locator),
]


def declarative_dict(value: dict[str, Any]) -> dict[str, JsonValue]:
    validated = validate_declarative_value(value)
    if not isinstance(validated, dict):  # pragma: no cover - signature guarantees this
        raise TypeError("component data must be an object")
    return validated
