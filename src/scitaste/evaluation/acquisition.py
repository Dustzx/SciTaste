"""Exact, no-network dataset acquisition requests and approval gates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_serializer,
    model_validator,
)

from scitaste.evaluation.prelaunch import ReadinessStatus

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_REVISION = r"^[A-Za-z0-9._-]{1,128}$"
_HTTP_ETAG = r"^[0-9a-f]{32}(?:-[1-9][0-9]*)?$"
_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 30.0
_MAX_TRANSACTION_BYTES = 10_000_000_000

AcquisitionFetcher = Callable[[str, int, str], bytes]


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
    source_revision: str = Field(pattern=_REVISION)
    destination: str = Field(min_length=1, max_length=1_000)
    maximum_bytes: int = Field(gt=0, le=_MAX_TRANSACTION_BYTES)
    media_type: Literal[
        "text/markdown",
        "text/plain",
        "text/csv",
        "application/json",
        "application/x-ndjson",
        "application/x-yaml",
        "application/gzip",
    ]
    license_identifier: str = Field(min_length=1, max_length=200)
    license_scope: str = Field(min_length=1, max_length=1_000)
    license_status: ReadinessStatus
    expected_sha256: str | None = Field(default=None, pattern=_SHA256)
    expected_http_etag: str | None = Field(default=None, pattern=_HTTP_ETAG)
    runtime_assets_included: Literal[False] = False

    @model_validator(mode="after")
    def source_and_destination_are_bounded(self) -> AcquisitionItem:
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("acquisition sources must use an HTTPS host")
        if parsed.port not in {None, 443}:
            raise ValueError("acquisition sources must use the standard HTTPS port")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("acquisition source URLs cannot contain credentials or fragments")
        if self.source_revision not in self.source_url:
            raise ValueError("acquisition source URL must contain its immutable revision")
        if self.item_id not in self.source_url:
            raise ValueError("acquisition source URL must contain its item ID")
        _validate_relative_path(self.destination, label="acquisition destination")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_http_etag(self, handler):  # type: ignore[no-untyped-def]
        payload = handler(self)
        if self.expected_http_etag is None:
            payload.pop("expected_http_etag", None)
        return payload


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
    maximum_total_bytes: int = Field(gt=0, le=_MAX_TRANSACTION_BYTES)
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


class AcquiredItemReceipt(BaseModel):
    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    source_url: str = Field(min_length=1, max_length=2_000)
    source_revision: str = Field(pattern=_REVISION)
    destination: str = Field(min_length=1, max_length=1_000)
    size_bytes: int = Field(gt=0, le=_MAX_TRANSACTION_BYTES)
    sha256: str = Field(pattern=_SHA256)
    expected_sha256: str | None = Field(default=None, pattern=_SHA256)
    expected_http_etag: str | None = Field(default=None, pattern=_HTTP_ETAG)

    @model_validator(mode="after")
    def item_receipt_is_bounded(self) -> AcquiredItemReceipt:
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("acquisition receipt sources must use HTTPS")
        if parsed.port not in {None, 443}:
            raise ValueError("acquisition receipt sources must use the standard HTTPS port")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("acquisition receipt sources cannot contain credentials or fragments")
        if self.source_revision not in self.source_url or self.item_id not in self.source_url:
            raise ValueError("acquisition receipt source is not pinned to its item")
        _validate_relative_path(self.destination, label="acquisition receipt destination")
        if self.expected_sha256 is not None and self.sha256 != self.expected_sha256:
            raise ValueError("acquisition receipt differs from the expected item hash")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_http_etag(self, handler):  # type: ignore[no-untyped-def]
        payload = handler(self)
        if self.expected_http_etag is None:
            payload.pop("expected_http_etag", None)
        return payload


class DatasetAcquisitionReceipt(BaseModel):
    """Self-hashed proof of one approved, atomic download-only transaction."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    request_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    acquired_at: datetime
    approval_scope: Literal["download-only-no-ingestion"]
    destination_root: str = Field(min_length=1, max_length=1_000)
    items: tuple[AcquiredItemReceipt, ...] = Field(min_length=1, max_length=500)
    item_count: int = Field(gt=0)
    total_bytes: int = Field(gt=0)
    maximum_total_bytes: int = Field(gt=0, le=_MAX_TRANSACTION_BYTES)
    source_hosts: tuple[str, ...] = Field(min_length=1, max_length=20)
    redirects_followed: Literal[False] = False
    overwrote_existing_files: Literal[False] = False
    acquisition_complete: Literal[True] = True
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @field_validator("approved_at", "acquired_at")
    @classmethod
    def receipt_times_are_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("acquisition receipt timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def receipt_is_closed_and_self_hashed(self) -> DatasetAcquisitionReceipt:
        _validate_relative_path(self.destination_root, label="acquisition receipt root")
        destination = PurePosixPath(self.destination_root)
        if destination.name != "raw" or destination.parent.name != self.request_id:
            raise ValueError("acquisition receipt root is not bound to its request ID")
        if self.acquired_at < self.approved_at:
            raise ValueError("acquisition cannot precede its approval")
        if self.item_count != len(self.items):
            raise ValueError("acquisition receipt item count differs from its items")
        if self.total_bytes != sum(item.size_bytes for item in self.items):
            raise ValueError("acquisition receipt byte total differs from its items")
        if self.total_bytes > self.maximum_total_bytes:
            raise ValueError("acquisition receipt exceeds its aggregate byte ceiling")
        item_ids = [item.item_id for item in self.items]
        destinations = [item.destination for item in self.items]
        if len(item_ids) != len(set(item_ids)) or len(destinations) != len(set(destinations)):
            raise ValueError("acquisition receipt item identities and destinations must be unique")
        hosts = tuple(sorted({urlparse(item.source_url).hostname or "" for item in self.items}))
        if self.source_hosts != hosts:
            raise ValueError("acquisition receipt source hosts differ from its items")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("acquisition receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DatasetAcquisitionReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class AcquisitionReceiptInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    receipt: DatasetAcquisitionReceipt


def approve_dataset_acquisition_request(
    request: DatasetAcquisitionRequest,
    *,
    confirmed_request_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> DatasetAcquisitionRequest:
    """Bind explicit owner approval to exact request bytes without moving data."""

    if request.approval.approved:
        raise ValueError("dataset acquisition request is already approved")
    if confirmed_request_sha256 != request.request_sha256:
        raise ValueError("confirmed acquisition request hash does not match the request")
    approval = AcquisitionApproval(
        approved=True,
        request_sha256=confirmed_request_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="download-only-no-ingestion",
    )
    return request.model_copy(update={"approval": approval})


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


def save_dataset_acquisition_request(
    request: DatasetAcquisitionRequest,
    path: str | Path,
) -> Path:
    """Save a new immutable request or approved derivative without moving data."""

    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return _atomic_text(path, rendered, require_absent=True)


def load_dataset_acquisition_receipt(path: str | Path) -> AcquisitionReceiptInspection:
    """Load and revalidate one bounded, self-hashed acquisition receipt."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("dataset acquisition receipt must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_REQUEST_BYTES:
        raise ValueError("dataset acquisition receipt must be a bounded regular file")
    raw = resolved.read_bytes()
    return AcquisitionReceiptInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        receipt=DatasetAcquisitionReceipt.model_validate_json(raw),
    )


def materialize_dataset_acquisition(
    request: DatasetAcquisitionRequest,
    *,
    workspace_root: str | Path,
    confirmed_request_sha256: str,
    allow_network_download: bool,
    fetcher: AcquisitionFetcher | None = None,
    acquired_at: datetime | None = None,
) -> DatasetAcquisitionReceipt:
    """Execute one approved download-only transaction and atomically publish its receipt."""

    if not allow_network_download:
        raise ValueError("dataset acquisition requires the explicit network-download switch")
    if confirmed_request_sha256 != request.request_sha256:
        raise ValueError("confirmed acquisition request hash does not match the request")
    report = inspect_dataset_acquisition_request(request, workspace_root=workspace_root)
    if not report.download_authorized:
        codes = ", ".join(item.code for item in report.authorization_blockers)
        raise ValueError(f"dataset acquisition is not authorized: {codes}")

    approval = request.approval
    if (
        not approval.approved
        or approval.approved_by is None
        or approval.approved_at is None
        or approval.scope != "download-only-no-ingestion"
    ):
        raise ValueError("dataset acquisition approval is incomplete")

    root = Path(workspace_root).resolve(strict=True)
    destination_relative = PurePosixPath(request.destination_root)
    if destination_relative.name != "raw" or destination_relative.parent.name != request.request_id:
        raise ValueError(
            "download destination must be <acquisition-root>/<request-id>/raw "
            "for atomic receipt binding"
        )
    transaction_relative = destination_relative.parent
    transaction_root = root.joinpath(*transaction_relative.parts)
    transaction_parent = transaction_root.parent
    _ensure_directory_chain(root, transaction_parent)
    timestamp = acquired_at or datetime.now(UTC)
    staging: Path | None = None

    with _acquisition_lock(transaction_parent):
        if os.path.lexists(transaction_root):
            raise FileExistsError(transaction_root)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{request.request_id}.",
                suffix=".staging",
                dir=transaction_parent,
            )
        )
        try:
            staged_destination = staging / "raw"
            staged_destination.mkdir()
            receipts: list[AcquiredItemReceipt] = []
            total_bytes = 0
            for item in request.items:
                staged_item = staged_destination.joinpath(*PurePosixPath(item.destination).parts)
                staged_item.parent.mkdir(parents=True, exist_ok=True)
                if fetcher is None:
                    item_bytes, observed_sha256 = _fetch_https_to_file(
                        item.source_url,
                        item.maximum_bytes,
                        item.media_type,
                        staged_item,
                        expected_http_etag=item.expected_http_etag,
                    )
                else:
                    if item.expected_http_etag is not None and item.expected_sha256 is None:
                        raise ValueError(
                            "a custom acquisition fetcher cannot attest an HTTP ETag without "
                            "an expected content hash"
                        )
                    content = fetcher(
                        item.source_url,
                        item.maximum_bytes,
                        item.media_type,
                    )
                    if not isinstance(content, bytes) or not content:
                        raise ValueError(f"acquisition item {item.item_id} returned no bytes")
                    if len(content) > item.maximum_bytes:
                        raise ValueError(
                            f"acquisition item {item.item_id} exceeded its byte ceiling"
                        )
                    item_bytes = len(content)
                    observed_sha256 = hashlib.sha256(content).hexdigest()
                    _write_new_bytes(staged_item, content)
                total_bytes += item_bytes
                if total_bytes > request.maximum_total_bytes:
                    raise ValueError("dataset acquisition exceeded its aggregate byte ceiling")
                if item.expected_sha256 is not None and observed_sha256 != item.expected_sha256:
                    raise ValueError(f"acquisition item {item.item_id} failed its expected hash")
                receipts.append(
                    AcquiredItemReceipt(
                        item_id=item.item_id,
                        source_url=item.source_url,
                        source_revision=item.source_revision,
                        destination=item.destination,
                        size_bytes=item_bytes,
                        sha256=observed_sha256,
                        expected_sha256=item.expected_sha256,
                        expected_http_etag=item.expected_http_etag,
                    )
                )

            receipt = DatasetAcquisitionReceipt.create(
                request_id=request.request_id,
                request_sha256=request.request_sha256,
                approved_by=approval.approved_by,
                approved_at=approval.approved_at,
                acquired_at=timestamp,
                approval_scope=approval.scope,
                destination_root=request.destination_root,
                items=tuple(receipts),
                item_count=len(receipts),
                total_bytes=total_bytes,
                maximum_total_bytes=request.maximum_total_bytes,
                source_hosts=report.source_hosts,
            )
            _write_new_bytes(
                staging / "RECEIPT.json",
                (receipt.model_dump_json(indent=2) + "\n").encode(),
            )
            if os.path.lexists(transaction_root):
                raise FileExistsError(transaction_root)
            os.rename(staging, transaction_root)
            staging = None
            _fsync_directory(transaction_parent)
            return receipt
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_https_bytes(
    url: str,
    maximum_bytes: int,
    expected_media_type: str,
    *,
    expected_http_etag: str | None = None,
) -> bytes:
    response = _open_https_source(
        url,
        maximum_bytes,
        expected_media_type,
        expected_http_etag=expected_http_etag,
    )
    with response:
        content = bytearray()
        while chunk := response.read(_DOWNLOAD_CHUNK_BYTES):
            content.extend(chunk)
            if len(content) > maximum_bytes:
                raise ValueError("acquisition source exceeded its byte ceiling")
    return bytes(content)


def _fetch_https_to_file(
    url: str,
    maximum_bytes: int,
    expected_media_type: str,
    target: Path,
    *,
    expected_http_etag: str | None = None,
) -> tuple[int, str]:
    """Stream one approved object to a new staging file without buffering it in RAM."""

    response = _open_https_source(
        url,
        maximum_bytes,
        expected_media_type,
        expected_http_etag=expected_http_etag,
    )
    digest = hashlib.sha256()
    size = 0
    descriptor: int | None = None
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with response, os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            while chunk := response.read(_DOWNLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("acquisition source exceeded its byte ceiling")
                digest.update(chunk)
                handle.write(chunk)
            if size == 0:
                raise ValueError("acquisition source returned no bytes")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _close_response(response)
        if descriptor is not None:
            os.close(descriptor)
        target.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def _open_https_source(
    url: str,
    maximum_bytes: int,
    expected_media_type: str,
    *,
    expected_http_etag: str | None = None,
):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("acquisition fetch requires an HTTPS source")
    request = Request(
        url,
        headers={
            "Accept": (
                "application/gzip,application/x-gzip,application/octet-stream,"
                "application/x-ndjson,application/json,text/markdown,text/plain;q=0.9"
            ),
            "Accept-Encoding": "identity",
            "User-Agent": "SciTaste-approved-acquisition/1.0",
        },
        method="GET",
    )
    opener = build_opener(_RejectRedirects())
    try:
        response = opener.open(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ValueError("acquisition redirects are forbidden") from exc
        raise
    try:
        if getattr(response, "status", None) != 200:
            raise ValueError("acquisition source did not return HTTP 200")
        if response.geturl() != url:
            raise ValueError("acquisition redirects are forbidden")
        content_encoding = response.headers.get("Content-Encoding")
        if content_encoding is not None and content_encoding.strip().lower() != "identity":
            raise ValueError("acquisition source returned an unapproved content encoding")
        declared_media_type = response.headers.get("Content-Type")
        if declared_media_type is None:
            raise ValueError("acquisition source omitted Content-Type")
        observed_media_type = declared_media_type.partition(";")[0].strip().lower()
        accepted_media_types = {
            "text/markdown": {"text/markdown", "text/plain"},
            "text/plain": {"text/plain", "application/octet-stream", "binary/octet-stream"},
            "text/csv": {"text/csv", "text/plain", "application/octet-stream"},
            # Pinned ``raw`` endpoints on Hugging Face and GitHub serve typed
            # text artifacts as ``text/plain``.  The request still binds the
            # intended semantic type and the later, separately authorized
            # content audit validates the bytes before ingestion.
            "application/json": {"application/json", "text/plain"},
            "application/x-ndjson": {
                "application/x-ndjson",
                "application/json",
                "text/plain",
                "application/octet-stream",
                "binary/octet-stream",
            },
            "application/x-yaml": {
                "application/x-yaml",
                "application/yaml",
                "text/yaml",
                "text/plain",
            },
            "application/gzip": {
                "application/gzip",
                "application/x-gzip",
                "application/x-tar",
                "application/octet-stream",
                "binary/octet-stream",
            },
        }
        if observed_media_type not in accepted_media_types.get(expected_media_type, set()):
            raise ValueError(
                "acquisition source Content-Type does not match its approved media type"
            )
        if expected_http_etag is not None:
            observed_etag = _normalize_http_etag(response.headers.get("ETag"))
            if observed_etag != expected_http_etag:
                raise ValueError("acquisition source HTTP ETag differs from its approved identity")
        declared_length = response.headers.get("Content-Length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
                if parsed_length < 0:
                    raise ValueError("negative")
                if parsed_length > maximum_bytes:
                    raise ValueError("acquisition source exceeds its declared byte ceiling")
            except ValueError as exc:
                if "exceeds" in str(exc):
                    raise
                raise ValueError("acquisition source returned an invalid Content-Length") from exc
    except BaseException:
        _close_response(response)
        raise
    return response


def _normalize_http_etag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.startswith("W/"):
        raise ValueError("acquisition source supplied a weak HTTP ETag")
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    if not normalized or not re.fullmatch(_HTTP_ETAG, normalized):
        raise ValueError("acquisition source supplied an invalid HTTP ETag")
    return normalized


def _close_response(response: object) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _atomic_text(path: str | Path, text: str, *, require_absent: bool) -> Path:
    target = Path(path)
    if target.is_symlink() or (require_absent and target.exists()):
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if require_absent:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise FileExistsError(target) from exc
            temporary.unlink()
        else:
            os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _write_new_bytes(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _ensure_directory_chain(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("acquisition transaction directory escaped its workspace") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("acquisition transaction directory cannot contain symlinks")
        current.mkdir(exist_ok=True)
        if not current.is_dir() or not current.resolve(strict=True).is_relative_to(root):
            raise ValueError("acquisition transaction directory escaped its workspace")


class _acquisition_lock:
    def __init__(self, directory: Path) -> None:
        self._path = directory / ".scitaste-acquisition.lock"
        self._descriptor: int | None = None

    def __enter__(self) -> None:
        import fcntl

        self._descriptor = os.open(
            self._path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        fcntl.flock(self._descriptor, fcntl.LOCK_EX)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        import fcntl

        if self._descriptor is None:
            return
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    "AcquiredItemReceipt",
    "AcquisitionApproval",
    "AcquisitionEvidenceBinding",
    "AcquisitionFetcher",
    "AcquisitionFinding",
    "AcquisitionGateReport",
    "AcquisitionItem",
    "AcquisitionReceiptInspection",
    "AcquisitionRequestInspection",
    "DatasetAcquisitionReceipt",
    "DatasetAcquisitionRequest",
    "approve_dataset_acquisition_request",
    "inspect_dataset_acquisition_request",
    "load_dataset_acquisition_receipt",
    "load_dataset_acquisition_request",
    "materialize_dataset_acquisition",
    "save_acquisition_gate_report",
    "save_dataset_acquisition_request",
]
