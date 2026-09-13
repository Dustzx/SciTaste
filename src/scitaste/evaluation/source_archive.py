"""Approval-gated, no-extraction qualification for pinned source archives."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.acquisition import (
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_CONTROL_BYTES = 4 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 10_000_000_000
_READ_CHUNK_BYTES = 1024 * 1024


class SourceArchiveFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> SourceArchiveFileBinding:
        _validate_relative_path(self.path, "source-archive binding")
        return self


class SourceArchivePlanItem(BaseModel):
    model_config = _CONFIG

    system_id: str = Field(pattern=_ID)
    acquisition_item_id: str = Field(pattern=_COMMIT)
    source_commit: str = Field(pattern=_COMMIT)
    archive: SourceArchiveFileBinding
    archive_size_bytes: int = Field(gt=0, le=_MAX_ARCHIVE_BYTES)
    expected_root_directory: str = Field(min_length=1, max_length=300)
    license_identifier: str = Field(min_length=1, max_length=200)
    license_file_path: str = Field(min_length=1, max_length=500)
    license_file_sha256: str = Field(pattern=_SHA256)
    maximum_members: int = Field(gt=0, le=250_000)
    maximum_expanded_bytes: int = Field(gt=0, le=20_000_000_000)
    maximum_regular_file_bytes: int = Field(gt=0, le=5_000_000_000)
    output_directory: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def item_is_closed(self) -> SourceArchivePlanItem:
        if self.acquisition_item_id != self.source_commit:
            raise ValueError("source archive item identity must equal its commit")
        if any(token in self.expected_root_directory for token in ("/", "\\")):
            raise ValueError("source archive expected root must be one directory name")
        if self.expected_root_directory in {"", ".", ".."}:
            raise ValueError("source archive expected root is invalid")
        _validate_relative_path(self.license_file_path, "source-archive license file")
        if PurePosixPath(self.license_file_path).parts[0] != self.expected_root_directory:
            raise ValueError("source archive license file must be below its expected root")
        _validate_relative_path(self.output_directory, "source-archive output")
        if self.maximum_expanded_bytes < self.archive_size_bytes:
            raise ValueError("source archive expanded ceiling is below its archive bytes")
        if self.maximum_regular_file_bytes > self.maximum_expanded_bytes:
            raise ValueError("source archive file ceiling exceeds its expanded ceiling")
        return self


class SourceArchiveQualificationPlan(BaseModel):
    """No-read plan binding exact acquired bytes to later tar qualification."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    purpose: str = Field(min_length=1, max_length=2_000)
    claim_boundary: str = Field(min_length=1, max_length=2_000)
    approved_acquisition_request: SourceArchiveFileBinding
    acquisition_request_sha256: str = Field(pattern=_SHA256)
    acquisition_receipt: SourceArchiveFileBinding
    acquisition_receipt_sha256: str = Field(pattern=_SHA256)
    items: tuple[SourceArchivePlanItem, ...] = Field(min_length=1, max_length=20)
    output_root: str = Field(min_length=1, max_length=1_000)
    maximum_total_expanded_bytes: int = Field(gt=0, le=20_000_000_000)
    owner_read_approval_required: Literal[True] = True
    authorizes_archive_read: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_installation: Literal[False] = False
    authorizes_execution: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False

    @model_validator(mode="after")
    def plan_is_closed(self) -> SourceArchiveQualificationPlan:
        _validate_relative_path(self.output_root, "source-archive output root")
        for values, label in (
            ([item.system_id for item in self.items], "system IDs"),
            ([item.acquisition_item_id for item in self.items], "acquisition item IDs"),
            ([item.archive.path for item in self.items], "archive paths"),
            ([item.output_directory for item in self.items], "output directories"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"source archive {label} must be unique")
        if self.maximum_total_expanded_bytes != sum(
            item.maximum_expanded_bytes for item in self.items
        ):
            raise ValueError("source archive total expansion ceiling differs from its items")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class SourceArchiveReadApproval(BaseModel):
    """Exact authority to inspect archive members and hash their content, but not extract."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["archive-index-and-content-hash-read-only-no-extraction"]
    authorizes_archive_read: Literal[True] = True
    authorizes_extraction: Literal[False] = False
    authorizes_installation: Literal[False] = False
    authorizes_execution: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False

    @model_validator(mode="after")
    def approval_time_is_aware(self) -> SourceArchiveReadApproval:
        if self.approved_at.utcoffset() is None:
            raise ValueError("source archive approval timestamp must include a timezone")
        return self

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class SourceArchiveFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.\/-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)
    system_id: str | None = Field(default=None, pattern=_ID)
    member_path: str | None = Field(default=None, max_length=2_000)


class SourceArchivePlanReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    system_count: int = Field(gt=0)
    archive_count: int = Field(gt=0)
    archive_bytes: int = Field(ge=0)
    maximum_total_expanded_bytes: int = Field(gt=0)
    acquisition_chain_verified: bool
    archive_byte_bindings_verified: bool
    output_root_empty: bool
    ready_for_owner_read_approval: bool
    findings: tuple[SourceArchiveFinding, ...]
    archive_content_read: Literal[False] = False
    extraction_performed: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    authorizes_archive_read: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_execution: Literal[False] = False


class SourceArchiveMemberRecord(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    kind: Literal["directory", "regular-file"]
    size_bytes: int = Field(ge=0)
    mode: int = Field(ge=0, le=0o777)
    sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def member_is_consistent(self) -> SourceArchiveMemberRecord:
        _validate_relative_path(self.path, "source archive member")
        if self.kind == "directory" and (self.size_bytes != 0 or self.sha256 is not None):
            raise ValueError("source archive directory cannot contain file evidence")
        if self.kind == "regular-file" and self.sha256 is None:
            raise ValueError("source archive regular file requires a digest")
        return self


class SourceArchiveItemQualification(BaseModel):
    model_config = _CONFIG

    system_id: str = Field(pattern=_ID)
    source_commit: str = Field(pattern=_COMMIT)
    archive: SourceArchiveFileBinding
    archive_size_bytes: int = Field(gt=0)
    expected_root_directory: str
    observed_root_directory: str | None
    member_count: int = Field(ge=0)
    regular_file_count: int = Field(ge=0)
    directory_count: int = Field(ge=0)
    expanded_bytes: int = Field(ge=0)
    tree_sha256: str | None = Field(default=None, pattern=_SHA256)
    members: tuple[SourceArchiveMemberRecord, ...]
    safe_for_extraction_proposal: bool
    findings: tuple[SourceArchiveFinding, ...]


class SourceArchiveQualificationReport(BaseModel):
    """Content-derived source tree manifest; still grants no extraction authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    qualified_at: datetime
    items: tuple[SourceArchiveItemQualification, ...]
    archive_count: int = Field(gt=0)
    archive_bytes: int = Field(gt=0)
    expanded_bytes: int = Field(ge=0)
    all_archives_safe: bool
    ready_for_extraction_proposal: bool
    archive_content_read: Literal[True] = True
    extraction_performed: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_installation: Literal[False] = False
    authorizes_execution: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False

    @model_validator(mode="after")
    def report_is_closed(self) -> SourceArchiveQualificationReport:
        if self.qualified_at.utcoffset() is None:
            raise ValueError("source archive qualification timestamp must include a timezone")
        if self.archive_count != len(self.items):
            raise ValueError("source archive report item count differs")
        if self.archive_bytes != sum(item.archive_size_bytes for item in self.items):
            raise ValueError("source archive report byte count differs")
        if self.expanded_bytes != sum(item.expanded_bytes for item in self.items):
            raise ValueError("source archive report expanded bytes differ")
        expected = all(item.safe_for_extraction_proposal for item in self.items)
        if self.all_archives_safe != expected or self.ready_for_extraction_proposal != expected:
            raise ValueError("source archive report readiness differs from item safety")
        return self


def load_source_archive_qualification_plan(
    path: str | Path,
) -> SourceArchiveQualificationPlan:
    return SourceArchiveQualificationPlan.model_validate(_load_mapping(path, "source archive plan"))


def load_source_archive_read_approval(path: str | Path) -> SourceArchiveReadApproval:
    return SourceArchiveReadApproval.model_validate(
        _load_mapping(path, "source archive read approval")
    )


def inspect_source_archive_qualification_plan(
    plan: SourceArchiveQualificationPlan,
    *,
    workspace_root: str | Path,
) -> SourceArchivePlanReport:
    """Verify receipt and archive byte identities without reading tar members."""

    root = Path(workspace_root).resolve(strict=True)
    findings: list[SourceArchiveFinding] = []
    request: DatasetAcquisitionRequest | None = None
    receipt: DatasetAcquisitionReceipt | None = None
    chain_verified = True
    try:
        request_file = _bound_file(root, plan.approved_acquisition_request)
        receipt_file = _bound_file(root, plan.acquisition_receipt)
        request = load_dataset_acquisition_request(request_file).request
        receipt = load_dataset_acquisition_receipt(receipt_file).receipt
        if (
            request.request_sha256 != plan.acquisition_request_sha256
            or request.project_id != plan.project_id
            or not request.approval.approved
            or receipt.request_sha256 != request.request_sha256
            or receipt.request_id != request.request_id
            or receipt.receipt_sha256 != plan.acquisition_receipt_sha256
            or not receipt.acquisition_complete
        ):
            raise ValueError("source archive acquisition identities differ")
    except (OSError, ValueError) as exc:
        _add(findings, "acquisition-chain-invalid", str(exc))
        chain_verified = False

    archive_bindings_verified = chain_verified
    archive_bytes = 0
    if request is not None and receipt is not None:
        request_items = {item.item_id: item for item in request.items}
        receipt_items = {item.item_id: item for item in receipt.items}
        for item in plan.items:
            requested = request_items.get(item.acquisition_item_id)
            acquired = receipt_items.get(item.acquisition_item_id)
            try:
                archive_file = _bound_file(
                    root,
                    item.archive,
                    expected_bytes=item.archive_size_bytes,
                    maximum_bytes=item.archive_size_bytes,
                )
            except (OSError, ValueError) as exc:
                _add(findings, "archive-binding-invalid", str(exc), system_id=item.system_id)
                archive_bindings_verified = False
                continue
            archive_bytes += archive_file.stat().st_size
            expected_archive_path = None
            if requested is not None:
                expected_archive_path = (
                    PurePosixPath(request.destination_root) / requested.destination
                ).as_posix()
            if (
                requested is None
                or acquired is None
                or requested.media_type != "application/gzip"
                or requested.source_revision != item.source_commit
                or requested.destination != acquired.destination
                or requested.license_identifier != item.license_identifier
                or acquired.size_bytes != item.archive_size_bytes
                or acquired.sha256 != item.archive.sha256
                or acquired.source_revision != item.source_commit
                or item.archive.path != expected_archive_path
            ):
                _add(
                    findings,
                    "archive-receipt-mismatch",
                    "plan item differs from its approved request or receipt",
                    system_id=item.system_id,
                )
                archive_bindings_verified = False

    output = root.joinpath(*PurePosixPath(plan.output_root).parts)
    output_safe = output.resolve(strict=False).is_relative_to(root)
    output_empty = output_safe and not os.path.lexists(output)
    if not output_safe:
        _add(findings, "output-outside-workspace", plan.output_root)
    elif not output_empty:
        _add(findings, "output-exists", plan.output_root)
    ready = chain_verified and archive_bindings_verified and output_empty
    return SourceArchivePlanReport(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        system_count=len({item.system_id for item in plan.items}),
        archive_count=len(plan.items),
        archive_bytes=archive_bytes,
        maximum_total_expanded_bytes=plan.maximum_total_expanded_bytes,
        acquisition_chain_verified=chain_verified,
        archive_byte_bindings_verified=archive_bindings_verified,
        output_root_empty=output_empty,
        ready_for_owner_read_approval=ready,
        findings=tuple(findings),
    )


def approve_source_archive_read(
    plan: SourceArchiveQualificationPlan,
    *,
    confirmed_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> SourceArchiveReadApproval:
    if confirmed_plan_sha256 != plan.plan_sha256:
        raise ValueError("confirmed source archive plan hash does not match")
    return SourceArchiveReadApproval(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="archive-index-and-content-hash-read-only-no-extraction",
    )


def qualify_source_archives(
    plan: SourceArchiveQualificationPlan,
    approval: SourceArchiveReadApproval,
    *,
    workspace_root: str | Path,
    allow_local_archive_read: bool,
    qualified_at: datetime,
) -> SourceArchiveQualificationReport:
    if not allow_local_archive_read:
        raise ValueError("source archive qualification requires the explicit local-read switch")
    if approval.plan_id != plan.plan_id or approval.plan_sha256 != plan.plan_sha256:
        raise ValueError("source archive read approval binds another plan")
    inspection = inspect_source_archive_qualification_plan(plan, workspace_root=workspace_root)
    if not inspection.ready_for_owner_read_approval:
        codes = ", ".join(item.code for item in inspection.findings)
        raise ValueError(f"source archive qualification plan is not ready: {codes}")
    root = Path(workspace_root).resolve(strict=True)
    items = tuple(_qualify_item(root, item) for item in plan.items)
    return SourceArchiveQualificationReport(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        approval_sha256=approval.approval_sha256,
        qualified_at=qualified_at,
        items=items,
        archive_count=len(items),
        archive_bytes=sum(item.archive_size_bytes for item in items),
        expanded_bytes=sum(item.expanded_bytes for item in items),
        all_archives_safe=all(item.safe_for_extraction_proposal for item in items),
        ready_for_extraction_proposal=all(item.safe_for_extraction_proposal for item in items),
    )


def save_source_archive_read_approval(
    approval: SourceArchiveReadApproval, path: str | Path
) -> Path:
    return _atomic_json(path, approval.model_dump(mode="json", exclude={"approval_sha256"}))


def save_source_archive_plan_report(report: SourceArchivePlanReport, path: str | Path) -> Path:
    return _atomic_json(path, report.model_dump(mode="json"))


def save_source_archive_qualification_report(
    report: SourceArchiveQualificationReport, path: str | Path
) -> Path:
    return _atomic_json(path, report.model_dump(mode="json"))


def _qualify_item(root: Path, item: SourceArchivePlanItem) -> SourceArchiveItemQualification:
    archive = _bound_file(
        root,
        item.archive,
        expected_bytes=item.archive_size_bytes,
        maximum_bytes=item.archive_size_bytes,
    )
    findings: list[SourceArchiveFinding] = []
    records: list[SourceArchiveMemberRecord] = []
    seen: set[str] = set()
    roots: set[str] = set()
    expanded = 0
    regular_files = 0
    directories = 0
    observed_members = 0
    try:
        with tarfile.open(archive, mode="r:gz") as package:
            for index, member in enumerate(package, 1):
                observed_members = index
                if index > item.maximum_members:
                    _add(
                        findings,
                        "member-count-exceeded",
                        "archive exceeds its member ceiling",
                        system_id=item.system_id,
                    )
                    break
                normalized = _member_path(member.name)
                if normalized is None:
                    _add(
                        findings,
                        "member-path-unsafe",
                        "archive member path is absolute, non-normalized, or traversing",
                        system_id=item.system_id,
                        member_path=member.name,
                    )
                    continue
                roots.add(PurePosixPath(normalized).parts[0])
                if normalized in seen:
                    _add(
                        findings,
                        "member-path-duplicate",
                        "archive contains a duplicate normalized path",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    continue
                seen.add(normalized)
                if member.mode & ~0o777:
                    _add(
                        findings,
                        "member-mode-unsafe",
                        "archive member carries permission bits outside rwx",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    continue
                if member.isdir():
                    directories += 1
                    records.append(
                        SourceArchiveMemberRecord(
                            path=normalized,
                            kind="directory",
                            size_bytes=0,
                            mode=member.mode,
                        )
                    )
                    continue
                if not member.isreg() or member.sparse is not None:
                    _add(
                        findings,
                        "member-type-unsafe",
                        "only non-sparse regular files and directories are admitted",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    continue
                if member.size < 0 or member.size > item.maximum_regular_file_bytes:
                    _add(
                        findings,
                        "member-size-exceeded",
                        "archive member exceeds its regular-file ceiling",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    continue
                expanded += member.size
                if expanded > item.maximum_expanded_bytes:
                    _add(
                        findings,
                        "expanded-bytes-exceeded",
                        "archive exceeds its expanded-byte ceiling",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    break
                source = package.extractfile(member)
                if source is None:
                    _add(
                        findings,
                        "member-content-missing",
                        "regular member has no readable body",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    continue
                digest = hashlib.sha256()
                observed = 0
                with source:
                    while chunk := source.read(_READ_CHUNK_BYTES):
                        observed += len(chunk)
                        if observed > member.size:
                            break
                        digest.update(chunk)
                if observed != member.size:
                    _add(
                        findings,
                        "member-size-mismatch",
                        "regular member body differs from its declared size",
                        system_id=item.system_id,
                        member_path=normalized,
                    )
                    continue
                regular_files += 1
                records.append(
                    SourceArchiveMemberRecord(
                        path=normalized,
                        kind="regular-file",
                        size_bytes=observed,
                        mode=member.mode,
                        sha256=digest.hexdigest(),
                    )
                )
    except (OSError, tarfile.TarError) as exc:
        _add(findings, "archive-invalid", str(exc), system_id=item.system_id)

    observed_root = next(iter(roots)) if len(roots) == 1 else None
    if roots != {item.expected_root_directory}:
        _add(
            findings,
            "archive-root-mismatch",
            "archive does not contain exactly the predeclared top-level directory",
            system_id=item.system_id,
        )
    license_records = [record for record in records if record.path == item.license_file_path]
    if (
        len(license_records) != 1
        or license_records[0].kind != "regular-file"
        or license_records[0].sha256 != item.license_file_sha256
    ):
        _add(
            findings,
            "license-file-mismatch",
            "archive license file is missing or differs from the predeclared digest",
            system_id=item.system_id,
            member_path=item.license_file_path,
        )
    safe = not findings and bool(records) and regular_files > 0
    ordered = tuple(sorted(records, key=lambda record: record.path))
    tree_sha256 = (
        _canonical_sha256([record.model_dump(mode="json") for record in ordered]) if safe else None
    )
    return SourceArchiveItemQualification(
        system_id=item.system_id,
        source_commit=item.source_commit,
        archive=item.archive,
        archive_size_bytes=item.archive_size_bytes,
        expected_root_directory=item.expected_root_directory,
        observed_root_directory=observed_root,
        member_count=observed_members,
        regular_file_count=regular_files,
        directory_count=directories,
        expanded_bytes=expanded,
        tree_sha256=tree_sha256,
        members=ordered,
        safe_for_extraction_proposal=safe,
        findings=tuple(findings),
    )


def _member_path(value: str) -> str | None:
    if "\\" in value or "//" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    normalized = path.as_posix()
    if value.rstrip("/") != normalized:
        return None
    return normalized


def _bound_file(
    root: Path,
    binding: SourceArchiveFileBinding,
    *,
    expected_bytes: int | None = None,
    maximum_bytes: int = _MAX_CONTROL_BYTES,
) -> Path:
    candidate = root.joinpath(*PurePosixPath(binding.path).parts)
    current = root
    for part in PurePosixPath(binding.path).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"source archive binding contains a symlink: {binding.path}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"source archive binding is not a regular workspace file: {binding.path}")
    size = resolved.stat().st_size
    if expected_bytes is not None and size != expected_bytes:
        raise ValueError(f"source archive binding byte count mismatch: {binding.path}")
    if size > maximum_bytes:
        raise ValueError(f"source archive binding exceeds its byte ceiling: {binding.path}")
    if _sha256_file(resolved) != binding.sha256:
        raise ValueError(f"source archive binding hash mismatch: {binding.path}")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _load_mapping(path: str | Path, label: str) -> dict[str, object]:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return payload


def _atomic_json(path: str | Path, payload: object) -> Path:
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
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _validate_relative_path(value: str, label: str) -> None:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _add(
    findings: list[SourceArchiveFinding],
    code: str,
    message: str,
    *,
    system_id: str | None = None,
    member_path: str | None = None,
) -> None:
    findings.append(
        SourceArchiveFinding(
            code=code,
            message=message,
            system_id=system_id,
            member_path=member_path,
        )
    )


__all__ = [
    "SourceArchiveFileBinding",
    "SourceArchiveFinding",
    "SourceArchiveItemQualification",
    "SourceArchiveMemberRecord",
    "SourceArchivePlanItem",
    "SourceArchivePlanReport",
    "SourceArchiveQualificationPlan",
    "SourceArchiveQualificationReport",
    "SourceArchiveReadApproval",
    "approve_source_archive_read",
    "inspect_source_archive_qualification_plan",
    "load_source_archive_qualification_plan",
    "load_source_archive_read_approval",
    "qualify_source_archives",
    "save_source_archive_plan_report",
    "save_source_archive_qualification_report",
    "save_source_archive_read_approval",
]
