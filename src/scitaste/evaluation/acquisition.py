"""Exact, no-network dataset acquisition requests and approval gates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_REQUEST_BYTES = 2 * 1024 * 1024


class AcquisitionEvidenceBinding(BaseModel):
    model_config = _CONFIG

    evidence_id: str = Field(pattern=_ID)
    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        _validate_relative_path(value, label="acquisition evidence")
        return value


class AcquisitionItem(BaseModel):
    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    source_url: str = Field(min_length=1, max_length=2_000)
    source_revision: str = Field(pattern=_COMMIT)
    destination: str = Field(min_length=1, max_length=1_000)
    maximum_bytes: int = Field(gt=0, le=16 * 1024 * 1024)
    media_type: Literal["text/markdown", "application/json", "application/x-yaml"]
    license_identifier: str = Field(min_length=1, max_length=200)
    license_scope: str = Field(min_length=1, max_length=1_000)
    license_status: ReadinessStatus
    expected_sha256: str | None = Field(default=None, pattern=_SHA256)
    runtime_assets_included: Literal[False] = False

    @model_validator(mode="after")
    def source_and_destination_are_bounded(self) -> AcquisitionItem:
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("acquisition sources must use an HTTPS host")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("acquisition source URLs cannot contain credentials or fragments")
        if self.source_revision not in self.source_url:
            raise ValueError("acquisition source URL must contain its immutable revision")
        if self.item_id not in self.source_url:
            raise ValueError("acquisition source URL must contain its item ID")
        _validate_relative_path(self.destination, label="acquisition destination")
        return self


class AcquisitionApproval(BaseModel):
    model_config = _CONFIG

    approved: bool = False
    request_sha256: str | None = Field(default=None, pattern=_SHA256)
    approved_by: str | None = Field(default=None, max_length=200)
    approved_at: datetime | None = None
    scope: Literal["download-only-no-ingestion"] | None = None

    @model_validator(mode="after")
    def approval_is_complete_or_empty(self) -> AcquisitionApproval:
        values = (self.request_sha256, self.approved_by, self.approved_at, self.scope)
        if self.approved and not all(value is not None for value in values):
            raise ValueError("acquisition approval requires hash, owner, time, and scope")
        if not self.approved and any(value is not None for value in values):
            raise ValueError("unapproved acquisition requests cannot contain approval metadata")
        if self.approved_at is not None and self.approved_at.utcoffset() is None:
            raise ValueError("acquisition approval timestamp must include a timezone")
        return self


class DatasetAcquisitionRequest(BaseModel):
    """One fixed download allowlist; it is not a downloader or ingestion plan."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    track_id: str = Field(pattern=_ID)
    authorization_scope: Literal["download-only-no-ingestion"]
    purpose: str = Field(min_length=1, max_length=2_000)
    claim_boundary: str = Field(min_length=1, max_length=2_000)
    selection_id: str = Field(pattern=_ID)
    selection_proposal_sha256: str = Field(pattern=_SHA256)
    destination_root: str = Field(min_length=1, max_length=1_000)
    allowed_hosts: tuple[str, ...] = Field(min_length=1, max_length=20)
    items: tuple[AcquisitionItem, ...] = Field(min_length=1, max_length=500)
    maximum_total_bytes: int = Field(gt=0, le=10 * 1024 * 1024 * 1024)
    evidence: tuple[AcquisitionEvidenceBinding, ...] = Field(min_length=1, max_length=50)
    approval: AcquisitionApproval = Field(default_factory=AcquisitionApproval)
    redirects_allowed: Literal[False] = False
    overwrite_allowed: Literal[False] = False
    secrets_forbidden: Literal[True] = True
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def acquisition_scope_is_closed(self) -> DatasetAcquisitionRequest:
        _validate_relative_path(self.destination_root, label="acquisition root")
        item_ids = [item.item_id for item in self.items]
        destinations = [item.destination for item in self.items]
        evidence_ids = [item.evidence_id for item in self.evidence]
        for values, label in (
            (item_ids, "item"),
            (destinations, "destination"),
            (evidence_ids, "evidence"),
            (list(self.allowed_hosts), "host"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"acquisition {label} values must be unique")
        if self.maximum_total_bytes != sum(item.maximum_bytes for item in self.items):
            raise ValueError("maximum_total_bytes must equal the sum of item ceilings")
        allowed = set(self.allowed_hosts)
        for item in self.items:
            host = urlparse(item.source_url).hostname
            if host not in allowed:
                raise ValueError(f"acquisition source host is not allowlisted: {host}")
        return self

    @computed_field
    @property
    def request_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"approval", "request_sha256"})
        return _canonical_sha256(payload)


class AcquisitionFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.\/-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)


class AcquisitionRequestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    request: DatasetAcquisitionRequest


class AcquisitionGateReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    request_sha256: str = Field(pattern=_SHA256)
    purpose: str
    claim_boundary: str
    items: tuple[AcquisitionItem, ...]
    item_count: int = Field(gt=0)
    maximum_total_bytes: int = Field(gt=0)
    source_hosts: tuple[str, ...]
    destination_root: str
    ready_for_owner_approval: bool
    download_authorized: bool
    blockers: tuple[AcquisitionFinding, ...]
    authorization_blockers: tuple[AcquisitionFinding, ...]
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_network_access_performed: Literal[True] = True
    no_download_performed: Literal[True] = True
    no_dataset_file_created: Literal[True] = True

    @model_validator(mode="after")
    def report_is_closed(self) -> AcquisitionGateReport:
        if self.item_count != len(self.items):
            raise ValueError("acquisition report item count differs from its items")
        if self.maximum_total_bytes != sum(item.maximum_bytes for item in self.items):
            raise ValueError("acquisition report byte ceiling differs from its items")
        hosts = tuple(sorted({urlparse(item.source_url).hostname or "" for item in self.items}))
        if self.source_hosts != hosts:
            raise ValueError("acquisition report source hosts differ from its items")
        if self.ready_for_owner_approval != (not self.blockers):
            raise ValueError("acquisition report readiness differs from its blockers")
        expected_authorized = self.ready_for_owner_approval and not self.authorization_blockers
        if self.download_authorized != expected_authorized:
            raise ValueError("acquisition report authorization differs from its blockers")
        return self


def load_dataset_acquisition_request(path: str | Path) -> AcquisitionRequestInspection:
    """Load one bounded request without following a top-level symlink."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("dataset acquisition request must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_REQUEST_BYTES:
        raise ValueError("dataset acquisition request must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("dataset acquisition request must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("dataset acquisition request must contain a YAML mapping")
    return AcquisitionRequestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        request=DatasetAcquisitionRequest.model_validate(payload),
    )


def inspect_dataset_acquisition_request(
    request: DatasetAcquisitionRequest,
    *,
    workspace_root: str | Path,
) -> AcquisitionGateReport:
    """Evaluate exact download readiness without opening a network connection."""

    root = Path(workspace_root).resolve(strict=True)
    blockers: list[AcquisitionFinding] = []
    for binding in request.evidence:
        candidate = root.joinpath(*PurePosixPath(binding.path).parts)
        if candidate.is_symlink() or not candidate.is_file():
            _add(blockers, f"evidence:{binding.evidence_id}:missing", binding.path)
            continue
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            _add(blockers, f"evidence:{binding.evidence_id}:outside-root", binding.path)
            continue
        if resolved.stat().st_size > 64 * 1024 * 1024:
            _add(blockers, f"evidence:{binding.evidence_id}:too-large", binding.path)
            continue
        observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if observed != binding.sha256:
            _add(blockers, f"evidence:{binding.evidence_id}:hash-mismatch", binding.path)

    destination_root = root.joinpath(*PurePosixPath(request.destination_root).parts)
    resolved_destination = destination_root.resolve(strict=False)
    if not resolved_destination.is_relative_to(root):
        _add(blockers, "destination:outside-root", request.destination_root)
    for item in request.items:
        if item.license_status is not ReadinessStatus.VERIFIED:
            _add(
                blockers,
                f"license:{item.item_id}:{item.license_status.value}",
                f"license for {item.item_id} is {item.license_status.value}",
            )
        destination = destination_root.joinpath(*PurePosixPath(item.destination).parts)
        resolved_item = destination.resolve(strict=False)
        if not resolved_item.is_relative_to(resolved_destination):
            _add(
                blockers,
                f"destination:{item.item_id}:outside-root",
                f"destination escapes its acquisition root: {destination}",
            )
            continue
        if destination.exists() or destination.is_symlink():
            _add(
                blockers,
                f"destination:{item.item_id}:exists",
                f"destination already exists and overwrite is forbidden: {destination}",
            )

    ready = not blockers
    authorization: list[AcquisitionFinding] = []
    approval = request.approval
    if not ready:
        _add(
            authorization,
            "readiness-gates-failed",
            "request evidence, licenses, and empty destinations must pass first",
        )
    if not approval.approved:
        _add(
            authorization,
            "owner-approval-required",
            "the owner has not approved this exact download request hash",
        )
    elif approval.request_sha256 != request.request_sha256:
        _add(
            authorization,
            "approval-hash-mismatch",
            "approval targets different acquisition request bytes",
        )
    return AcquisitionGateReport(
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        purpose=request.purpose,
        claim_boundary=request.claim_boundary,
        items=request.items,
        item_count=len(request.items),
        maximum_total_bytes=request.maximum_total_bytes,
        source_hosts=tuple(
            sorted({urlparse(item.source_url).hostname or "" for item in request.items})
        ),
        destination_root=request.destination_root,
        ready_for_owner_approval=ready,
        download_authorized=ready and not authorization,
        blockers=tuple(blockers),
        authorization_blockers=tuple(authorization),
    )


def save_acquisition_gate_report(report: AcquisitionGateReport, path: str | Path) -> Path:
    """Atomically save a no-network inspection report."""

    target = Path(path)
    if target.is_symlink():
        raise ValueError("acquisition report output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(report.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _validate_relative_path(value: str, *, label: str) -> None:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _add(findings: list[AcquisitionFinding], code: str, message: str) -> None:
    findings.append(AcquisitionFinding(code=code, message=message))


__all__ = [
    "AcquisitionApproval",
    "AcquisitionEvidenceBinding",
    "AcquisitionFinding",
    "AcquisitionGateReport",
    "AcquisitionItem",
    "AcquisitionRequestInspection",
    "DatasetAcquisitionRequest",
    "inspect_dataset_acquisition_request",
    "load_dataset_acquisition_request",
    "save_acquisition_gate_report",
]
