"""Content-addressed project bindings for built-in read-only tool handlers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
    model_validator,
)

from scitaste.data.models import KnowledgeDocument
from scitaste.evidence.evidence_graph import EvidenceItem
from scitaste.model_nodes.tool_execution import (
    BoundEvidenceRecord,
    EvidenceInspectionHandler,
    KnowledgeQueryHandler,
    ReadOnlyToolHandler,
    RegisteredRunComparisonHandler,
)
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolProfile,
    EvidenceInspectPermission,
    KnowledgeQueryPermission,
    RegisteredRunComparePermission,
    canonical_sha256,
)
from scitaste.project.models import (
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.project.runtime import ProjectRevisionConflictError, ProjectRuntime

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_MAX_SOURCE_BYTES = 10_000_000


class ProjectToolBindingError(ValueError):
    """Raised when project-owned handler data is unsafe, stale, or inconsistent."""


class ProjectToolBindingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentAddressedRunFile(ProjectToolBindingModel):
    """One immutable file addressed relative to the selected project run."""

    locator: str
    sha256: str = Field(pattern=_SHA256_PATTERN)
    max_bytes: int = Field(default=1_000_000, ge=1, le=_MAX_SOURCE_BYTES)

    @field_validator("locator")
    @classmethod
    def locator_is_normalized(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="tool binding locator")


class KnowledgeLibraryBinding(ProjectToolBindingModel):
    library_id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN, max_length=128)]
    source: ContentAddressedRunFile


class ProjectEvidenceRecord(ProjectToolBindingModel):
    """Canonical evidence payload and optional read-only provenance projection."""

    evidence: EvidenceItem
    provenance: JsonValue | None = None

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class RegisteredRunMetricsRecord(ProjectToolBindingModel):
    run_id: str
    metrics: dict[str, float | None] = Field(min_length=1, max_length=64)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="metrics run_id")

    @field_validator("metrics", mode="before")
    @classmethod
    def raw_metrics_are_numeric(cls, value: object) -> object:
        if not isinstance(value, dict) or not value:
            raise ValueError("registered-run metrics must be a non-empty mapping")
        for name, metric in value.items():
            if (
                not isinstance(name, str)
                or not name
                or len(name) > 128
                or not all(character.isalnum() or character in "._:-" for character in name)
            ):
                raise ValueError("registered-run metric names must be safe identifiers")
            if metric is not None and (
                isinstance(metric, bool)
                or not isinstance(metric, (float, int))
                or not math.isfinite(float(metric))
            ):
                raise ValueError("registered-run metric values must be finite numbers or null")
        return value


class ProjectToolBindingSet(ProjectToolBindingModel):
    """Complete project/run identity and sources for one controlled tool profile."""

    schema_version: Literal["1.0"] = "1.0"
    binding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    knowledge_libraries: tuple[KnowledgeLibraryBinding, ...] = Field(default=(), max_length=16)
    evidence_source: ContentAddressedRunFile | None = None
    run_metrics_source: ContentAddressedRunFile | None = None
    read_only: Literal[True] = True
    network_access: Literal[False] = False
    process_launch: Literal[False] = False
    canonical_evidence_admission: Literal[False] = False

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="binding run_id")

    @model_validator(mode="after")
    def library_ids_are_unique(self) -> ProjectToolBindingSet:
        library_ids = [item.library_id for item in self.knowledge_libraries]
        if len(library_ids) != len(set(library_ids)):
            raise ValueError("knowledge binding library IDs must be unique")
        if not library_ids and self.evidence_source is None and self.run_metrics_source is None:
            raise ValueError("project tool binding set requires at least one source")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


@dataclass(frozen=True)
class VerifiedProjectToolHandlers:
    """Trusted handler registry constructed only from verified project files."""

    binding: ProjectToolBindingSet
    binding_fingerprint: str
    controlled_tool_profile_fingerprint: str
    handlers: tuple[ReadOnlyToolHandler, ...]
    source_sha256: tuple[str, ...]


def load_project_tool_handlers(
    project_runtime: ProjectRuntime,
    binding: ProjectToolBindingSet,
    controlled_profile: ControlledToolProfile,
) -> VerifiedProjectToolHandlers:
    """Construct built-in handlers after strict project and source verification."""

    try:
        binding = ProjectToolBindingSet.model_validate_json(
            binding.model_dump_json(exclude_computed_fields=True), strict=True
        )
        controlled_profile = ControlledToolProfile.model_validate_json(
            controlled_profile.model_dump_json(exclude_computed_fields=True), strict=True
        )
    except ValueError as exc:
        raise ProjectToolBindingError("invalid project tool binding input") from exc
    snapshot = project_runtime.open(binding.project_id)
    if snapshot.revision != binding.project_revision:
        raise ProjectRevisionConflictError(
            f"stale project revision {binding.project_revision}; current is {snapshot.revision}"
        )
    registered_runs = {item.run_id for item in snapshot.manifest.runs}
    if binding.run_id not in registered_runs:
        raise ProjectToolBindingError(f"unknown project run {binding.run_id!r}")
    run_root = (
        project_runtime.outputs_root / "projects" / binding.project_id / "runs" / binding.run_id
    )
    _require_safe_directory_chain(project_runtime.outputs_root, run_root)

    source_hashes: list[str] = []
    libraries: dict[str, tuple[KnowledgeDocument, ...]] = {}
    document_ids: set[str] = set()
    for library in binding.knowledge_libraries:
        raw = _read_bound_source(run_root, library.source)
        source_hashes.append(library.source.sha256)
        documents = tuple(_parse_jsonl(raw, KnowledgeDocument, source_name=library.source.locator))
        if not documents:
            raise ProjectToolBindingError("knowledge source must contain at least one record")
        ids = [document.document_id for document in documents]
        if len(ids) != len(set(ids)) or document_ids.intersection(ids):
            raise ProjectToolBindingError("knowledge document IDs must be globally unique")
        document_ids.update(ids)
        libraries[library.library_id] = documents

    evidence_records: tuple[ProjectEvidenceRecord, ...] = ()
    if binding.evidence_source is not None:
        raw = _read_bound_source(run_root, binding.evidence_source)
        source_hashes.append(binding.evidence_source.sha256)
        evidence_records = tuple(
            _parse_jsonl(
                raw,
                ProjectEvidenceRecord,
                source_name=binding.evidence_source.locator,
            )
        )
        evidence_ids = [item.evidence.evidence_id for item in evidence_records]
        if not evidence_ids:
            raise ProjectToolBindingError("evidence source must contain at least one record")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ProjectToolBindingError("evidence source contains duplicate evidence IDs")

    metric_records: tuple[RegisteredRunMetricsRecord, ...] = ()
    if binding.run_metrics_source is not None:
        raw = _read_bound_source(run_root, binding.run_metrics_source)
        source_hashes.append(binding.run_metrics_source.sha256)
        metric_records = tuple(
            _parse_jsonl(
                raw,
                RegisteredRunMetricsRecord,
                source_name=binding.run_metrics_source.locator,
            )
        )
        metric_run_ids = [item.run_id for item in metric_records]
        if not metric_run_ids:
            raise ProjectToolBindingError("run-metrics source must contain at least one record")
        if len(metric_run_ids) != len(set(metric_run_ids)):
            raise ProjectToolBindingError("run-metrics source contains duplicate run IDs")
        unknown_runs = set(metric_run_ids) - registered_runs
        if unknown_runs:
            raise ProjectToolBindingError(
                f"run-metrics source references unregistered runs: {sorted(unknown_runs)}"
            )

    handlers: list[ReadOnlyToolHandler] = []
    for permission in controlled_profile.permissions:
        if isinstance(permission, KnowledgeQueryPermission):
            unknown = set(permission.allowed_library_ids) - set(libraries)
            if unknown:
                raise ProjectToolBindingError(
                    f"controlled profile references unknown libraries: {sorted(unknown)}"
                )
            handlers.append(
                KnowledgeQueryHandler(
                    {
                        identifier: libraries[identifier]
                        for identifier in permission.allowed_library_ids
                    }
                )
            )
        elif isinstance(permission, EvidenceInspectPermission):
            records_by_id = {
                record.evidence.evidence_id: BoundEvidenceRecord(
                    evidence_id=record.evidence.evidence_id,
                    payload=record.evidence.model_dump(mode="json"),
                    provenance=record.provenance,
                )
                for record in evidence_records
            }
            unknown = set(permission.allowed_evidence_ids) - set(records_by_id)
            if unknown:
                raise ProjectToolBindingError(
                    f"controlled profile references unknown evidence: {sorted(unknown)}"
                )
            handlers.append(
                EvidenceInspectionHandler(
                    records_by_id[identifier] for identifier in permission.allowed_evidence_ids
                )
            )
        elif isinstance(permission, RegisteredRunComparePermission):
            metrics_by_run = {record.run_id: record.metrics for record in metric_records}
            unknown = set(permission.allowed_run_ids) - set(metrics_by_run)
            if unknown:
                raise ProjectToolBindingError(
                    f"controlled profile references unknown run metrics: {sorted(unknown)}"
                )
            for run_id in permission.allowed_run_ids:
                missing = set(permission.allowed_metric_names) - set(metrics_by_run[run_id])
                if missing:
                    raise ProjectToolBindingError(
                        f"run {run_id!r} lacks controlled metrics: {sorted(missing)}"
                    )
            handlers.append(
                RegisteredRunComparisonHandler(
                    {
                        identifier: metrics_by_run[identifier]
                        for identifier in permission.allowed_run_ids
                    }
                )
            )
        else:  # pragma: no cover - the strict profile union makes this unreachable
            raise ProjectToolBindingError("unsupported controlled tool permission")
    if not handlers:
        raise ProjectToolBindingError("controlled profile requires at least one handler")
    return VerifiedProjectToolHandlers(
        binding=binding,
        binding_fingerprint=binding.fingerprint,
        controlled_tool_profile_fingerprint=controlled_profile.fingerprint,
        handlers=tuple(handlers),
        source_sha256=tuple(sorted(source_hashes)),
    )


def _read_bound_source(run_root: Path, source: ContentAddressedRunFile) -> bytes:
    candidate = run_root / PurePosixPath(source.locator)
    _require_safe_file_parent(run_root, candidate.parent)
    if candidate.is_symlink():
        raise ProjectToolBindingError("project tool source is a symbolic link")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ProjectToolBindingError(
            f"missing or unsafe project tool source: {source.locator}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ProjectToolBindingError("project tool source is not a regular file")
        if before.st_size > source.max_bytes:
            raise ProjectToolBindingError("project tool source exceeds its byte ceiling")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(source.max_bytes + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(raw) > source.max_bytes:
        raise ProjectToolBindingError("project tool source exceeds its byte ceiling")
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after:
        raise ProjectToolBindingError("project tool source changed while it was read")
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != source.sha256:
        raise ProjectToolBindingError("project tool source hash drift")
    return raw


def _parse_jsonl(raw: bytes, model_type: type[BaseModel], *, source_name: str) -> list[Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectToolBindingError(f"invalid UTF-8 project tool source: {source_name}") from exc
    records: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line, object_pairs_hook=_unique_json_object)
            records.append(model_type.model_validate_json(line, strict=True))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProjectToolBindingError(
                f"invalid project tool record in {source_name} at line {line_number}"
            ) from exc
    return records


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _require_safe_file_parent(root: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ProjectToolBindingError("project tool source escapes its selected run") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise ProjectToolBindingError("project tool source contains an unsafe path component")
    try:
        parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ProjectToolBindingError("project tool source escapes its selected run") from exc


def _require_safe_directory_chain(root: Path, target: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ProjectToolBindingError("outputs root is not a safe directory")
    _require_safe_file_parent(root, target)


__all__ = [
    "ContentAddressedRunFile",
    "KnowledgeLibraryBinding",
    "ProjectEvidenceRecord",
    "ProjectToolBindingError",
    "ProjectToolBindingSet",
    "RegisteredRunMetricsRecord",
    "VerifiedProjectToolHandlers",
    "load_project_tool_handlers",
]
