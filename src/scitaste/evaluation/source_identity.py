"""Canonical private source identities across acquisitions and campaigns.

Acquisition receipts identify bytes, not scientific works.  The same public work
may therefore appear in multiple receipts or review campaigns.  This module
provides stable, domain-separated source-group identities and an optional alias
registry for preserving exclusions created by older receipt-bound compilers.
Raw DOI and forum identifiers are normalized only in memory and are never stored
in the registry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256

SourceIdentityNamespace = Literal[
    "f1000-work-v1",
    "openreview-forum-v1",
    "benchmark-task-v1",
]

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_F1000_DOI = re.compile(
    r"^(?P<base>10\.12688/f1000research\.(?:[0-9]+(?:-[0-9]+)?))"
    r"(?:\.(?:v)?[1-9][0-9]*)?$",
    re.IGNORECASE,
)
_OPENREVIEW_FORUM = re.compile(r"^[A-Za-z0-9_-]{3,200}$")
_BENCHMARK_TASK = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}::[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
)
_PREFIX = {
    "f1000-work-v1": "f1000-work",
    "openreview-forum-v1": "openreview-forum",
    "benchmark-task-v1": "benchmark-task",
}
_MAX_REGISTRY_BYTES = 16 * 1_048_576


def canonical_f1000_source_group_id(doi: str) -> str:
    """Return one stable opaque identity for every version of an F1000 work."""

    return _canonical_group_id("f1000-work-v1", doi)


def canonical_openreview_source_group_id(forum_id: str) -> str:
    """Return one stable opaque identity for an OpenReview forum trajectory."""

    return _canonical_group_id("openreview-forum-v1", forum_id)


def canonical_benchmark_task_source_group_id(benchmark_id: str, task_id: str) -> str:
    """Return a stable opaque identity for one held-out benchmark task."""

    return _canonical_group_id("benchmark-task-v1", f"{benchmark_id}::{task_id}")


class CanonicalSourceIdentity(BaseModel):
    """Private alias entry without the raw public source identifier."""

    model_config = _CONFIG

    namespace: SourceIdentityNamespace
    canonical_source_group_id: str = Field(pattern=_ID)
    source_identity_sha256: str = Field(pattern=_SHA256)
    legacy_source_group_ids: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        namespace: SourceIdentityNamespace,
        source_identifier: str,
        legacy_source_group_ids: tuple[str, ...] = (),
    ) -> CanonicalSourceIdentity:
        normalized = _normalize_source_identifier(namespace, source_identifier)
        digest = _source_identity_sha256(namespace, normalized)
        canonical = f"{_PREFIX[namespace]}-{digest}"
        return cls(
            namespace=namespace,
            canonical_source_group_id=canonical,
            source_identity_sha256=digest,
            legacy_source_group_ids=tuple(sorted(set(legacy_source_group_ids))),
        )

    @model_validator(mode="after")
    def identity_and_aliases_are_closed(self) -> CanonicalSourceIdentity:
        expected = f"{_PREFIX[self.namespace]}-{self.source_identity_sha256}"
        if self.canonical_source_group_id != expected:
            raise ValueError("canonical source-group ID differs from its private identity hash")
        if self.legacy_source_group_ids != tuple(sorted(set(self.legacy_source_group_ids))):
            raise ValueError("legacy source-group aliases must be sorted and unique")
        if self.canonical_source_group_id in self.legacy_source_group_ids:
            raise ValueError("canonical source-group ID cannot also be a legacy alias")
        return self


class CanonicalSourceIdentityRegistry(BaseModel):
    """Content-addressed cross-receipt alias registry."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    registry_id: str = Field(pattern=_ID)
    entries: tuple[CanonicalSourceIdentity, ...] = Field(min_length=1, max_length=100_000)
    source_artifact_sha256s: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    raw_source_identifiers_stored: Literal[False] = False
    registry_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(
        cls,
        *,
        registry_id: str,
        entries: tuple[CanonicalSourceIdentity, ...],
        source_artifact_sha256s: tuple[str, ...],
    ) -> CanonicalSourceIdentityRegistry:
        ordered = tuple(sorted(entries, key=lambda item: item.canonical_source_group_id))
        payload = {
            "schema_version": "1.0",
            "registry_id": registry_id,
            "entries": ordered,
            "source_artifact_sha256s": tuple(sorted(set(source_artifact_sha256s))),
            "raw_source_identifiers_stored": False,
        }
        unsigned = cls.model_construct(registry_sha256="0" * 64, **payload)
        return cls(
            **payload,
            registry_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"registry_sha256"})
            ),
        )

    @model_validator(mode="after")
    def registry_is_unambiguous_and_hashed(self) -> CanonicalSourceIdentityRegistry:
        canonical = [item.canonical_source_group_id for item in self.entries]
        identities = [
            (item.namespace, item.source_identity_sha256) for item in self.entries
        ]
        if canonical != sorted(set(canonical)) or len(identities) != len(set(identities)):
            raise ValueError("canonical source identities must be sorted and unique")
        if self.source_artifact_sha256s != tuple(sorted(set(self.source_artifact_sha256s))):
            raise ValueError("source artifact hashes must be sorted and unique")
        aliases: dict[str, str] = {}
        for item in self.entries:
            for alias in item.legacy_source_group_ids:
                previous = aliases.setdefault(alias, item.canonical_source_group_id)
                if previous != item.canonical_source_group_id:
                    raise ValueError("legacy source-group alias resolves to multiple works")
        expected = content_sha256(self.model_dump(mode="json", exclude={"registry_sha256"}))
        if self.registry_sha256 != expected:
            raise ValueError("canonical source identity registry hash mismatch")
        return self

    def resolve(self, source_group_id: str, *, require_known: bool = True) -> str:
        """Resolve a canonical or legacy group ID without exposing raw identity."""

        for item in self.entries:
            if source_group_id == item.canonical_source_group_id:
                return source_group_id
            if source_group_id in item.legacy_source_group_ids:
                return item.canonical_source_group_id
        if require_known:
            raise ValueError("source-group ID is absent from the canonical identity registry")
        return source_group_id


def save_canonical_source_identity_registry(
    registry: CanonicalSourceIdentityRegistry,
    path: str | Path,
) -> Path:
    """Atomically save a private source identity registry."""

    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(registry.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_canonical_source_identity_registry(
    path: str | Path,
) -> CanonicalSourceIdentityRegistry:
    """Load and verify a bounded regular registry file."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("canonical source identity registry must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_REGISTRY_BYTES:
        raise ValueError("canonical source identity registry exceeds its size limit")
    try:
        payload = json.loads(source.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("canonical source identity registry is invalid JSON") from error
    return CanonicalSourceIdentityRegistry.model_validate(payload)


def _canonical_group_id(namespace: SourceIdentityNamespace, source_identifier: str) -> str:
    normalized = _normalize_source_identifier(namespace, source_identifier)
    digest = _source_identity_sha256(namespace, normalized)
    return f"{_PREFIX[namespace]}-{digest}"


def _source_identity_sha256(namespace: SourceIdentityNamespace, normalized: str) -> str:
    return hashlib.sha256(f"{namespace}\0{normalized}".encode()).hexdigest()


def _normalize_source_identifier(
    namespace: SourceIdentityNamespace,
    source_identifier: str,
) -> str:
    value = source_identifier.strip()
    if namespace == "f1000-work-v1":
        lowered = value.casefold()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if lowered.startswith(prefix):
                lowered = lowered[len(prefix) :].strip()
                break
        match = _F1000_DOI.fullmatch(lowered)
        if match is None:
            raise ValueError("F1000 source identity must be a supported DOI or versioned DOI")
        return match.group("base").casefold()
    if namespace == "openreview-forum-v1":
        if _OPENREVIEW_FORUM.fullmatch(value) is None:
            raise ValueError("OpenReview source identity must be one exact forum ID")
        return value
    if _BENCHMARK_TASK.fullmatch(value) is None:
        raise ValueError("benchmark source identity must be benchmark-id::task-id")
    return value.casefold()


__all__ = [
    "CanonicalSourceIdentity",
    "CanonicalSourceIdentityRegistry",
    "SourceIdentityNamespace",
    "canonical_benchmark_task_source_group_id",
    "canonical_f1000_source_group_id",
    "canonical_openreview_source_group_id",
    "load_canonical_source_identity_registry",
    "save_canonical_source_identity_registry",
]
