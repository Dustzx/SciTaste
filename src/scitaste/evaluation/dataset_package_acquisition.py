"""Approval-gated streaming acquisition and archive qualification for large datasets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.dataset_package import (
    DatasetAssetSourceKind,
    DatasetPackageAsset,
    DatasetPackageGateReport,
    DatasetPackageInventory,
    DatasetPackageRequestInspection,
    load_dataset_package_inventory,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 4 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 60.0
_ALLOWED_ZIP_MEDIA_TYPES = frozenset(
    {
        "application/zip",
        "application/octet-stream",
        "application/x-zip-compressed",
        "binary/octet-stream",
    }
)
_MAX_MEMBERS_PER_ARCHIVE = 250_000
_MAX_COMPRESSION_RATIO = 1_000.0


class DatasetPackageSink(Protocol):
    def write(self, data: bytes) -> int: ...


class DatasetPackageSourceObservation(BaseModel):
    """Response identity observed on the same connection as the streamed body."""

    model_config = _CONFIG

    final_url: str = Field(min_length=1, max_length=2_000)
    status_code: Literal[200] = 200
    content_type: str = Field(min_length=1, max_length=200)
    content_length_bytes: int = Field(gt=0, le=100 * 1024**3)
    last_modified: datetime
    etag: str | None = Field(default=None, min_length=1, max_length=300)
    content_disposition_filename: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
    )
    content_encoding: Literal["identity"] = "identity"
    redirected: Literal[False] = False

    @field_validator("last_modified")
    @classmethod
    def last_modified_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("dataset package Last-Modified must include a timezone")
        return value


DatasetPackageStreamFetcher = Callable[
    [DatasetPackageAsset, DatasetPackageSink], DatasetPackageSourceObservation
]
DatasetPackageFreeSpaceProbe = Callable[[Path], int]


class DatasetPackageApproval(BaseModel):
    """Owner authority bound to one exact, review-ready package proposal."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    inventory_file_sha256: str = Field(pattern=_SHA256)
    gate_report_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["network-preflight-and-download-only-no-extract-no-ingestion"]
    selected_task_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    source_hosts: tuple[str, ...] = Field(min_length=1, max_length=20)
    destination_root: str = Field(min_length=1, max_length=1_000)
    asset_count: int = Field(gt=0)
    expected_download_bytes: int = Field(gt=0, le=500 * 1024**3)
    maximum_unpacked_bytes: int = Field(gt=0, le=1024 * 1024**3)
    minimum_free_storage_bytes: int = Field(gt=0, le=2 * 1024**4)
    authorizes_network_preflight: Literal[True] = True
    authorizes_download: Literal[True] = True
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("dataset package approval time must include a timezone")
        return value

    @model_validator(mode="after")
    def approval_is_closed(self) -> DatasetPackageApproval:
        _validate_relative_path(self.destination_root, "dataset package approval root")
        if len(self.selected_task_ids) != len(set(self.selected_task_ids)):
            raise ValueError("dataset package approval task IDs must be unique")
        if tuple(sorted(self.source_hosts)) != self.source_hosts:
            raise ValueError("dataset package approval hosts must be sorted")
        if len(self.source_hosts) != len(set(self.source_hosts)):
            raise ValueError("dataset package approval hosts must be unique")
        if self.minimum_free_storage_bytes < self.maximum_unpacked_bytes:
            raise ValueError("dataset package approval storage floor is below unpack ceiling")
        return self

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class DatasetPackageApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: DatasetPackageApproval


class AcquiredDatasetPackageAsset(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    asset_id: str = Field(pattern=_ID)
    source_kind: DatasetAssetSourceKind
    source_url: str = Field(min_length=1, max_length=2_000)
    destination: str = Field(min_length=1, max_length=1_000)
    size_bytes: int = Field(gt=0, le=100 * 1024**3)
    sha256: str = Field(pattern=_SHA256)
    observed_content_type: str = Field(min_length=1, max_length=200)
    observed_last_modified: datetime
    observed_etag: str | None = Field(default=None, min_length=1, max_length=300)
    observed_filename: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def acquired_asset_is_exact(self) -> AcquiredDatasetPackageAsset:
        _validate_relative_path(self.destination, "acquired dataset package asset")
        if urlparse(self.source_url).scheme != "https":
            raise ValueError("acquired dataset package source must use HTTPS")
        if self.observed_last_modified.utcoffset() is None:
            raise ValueError("acquired dataset package Last-Modified must include timezone")
        return self


class DatasetPackageAcquisitionReceipt(BaseModel):
    """Self-hashed proof of one complete atomic large-package transfer."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    inventory_file_sha256: str = Field(pattern=_SHA256)
    gate_report_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    acquired_at: datetime
    approval_scope: Literal["network-preflight-and-download-only-no-extract-no-ingestion"]
    destination_root: str = Field(min_length=1, max_length=1_000)
    assets: tuple[AcquiredDatasetPackageAsset, ...] = Field(min_length=1, max_length=500)
    asset_count: int = Field(gt=0)
    total_bytes: int = Field(gt=0, le=500 * 1024**3)
    expected_download_bytes: int = Field(gt=0, le=500 * 1024**3)
    source_hosts: tuple[str, ...] = Field(min_length=1, max_length=20)
    source_identity_rechecked: Literal[True] = True
    redirects_followed: Literal[False] = False
    overwrote_existing_files: Literal[False] = False
    acquisition_complete: Literal[True] = True
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("approved_at", "acquired_at")
    @classmethod
    def receipt_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("dataset package receipt times must include a timezone")
        return value

    @model_validator(mode="after")
    def receipt_is_closed(self) -> DatasetPackageAcquisitionReceipt:
        _validate_relative_path(self.destination_root, "dataset package receipt root")
        destination = PurePosixPath(self.destination_root)
        if destination.name != "raw" or destination.parent.name != self.request_id:
            raise ValueError("dataset package receipt root must be <request-id>/raw")
        if self.acquired_at < self.approved_at:
            raise ValueError("dataset package acquisition cannot precede approval")
        if self.asset_count != len(self.assets):
            raise ValueError("dataset package receipt asset count differs from its assets")
        if self.total_bytes != sum(item.size_bytes for item in self.assets):
            raise ValueError("dataset package receipt bytes differ from its assets")
        if self.total_bytes != self.expected_download_bytes:
            raise ValueError("dataset package receipt differs from exact expected bytes")
        ids = [item.asset_id for item in self.assets]
        destinations = [item.destination for item in self.assets]
        if len(ids) != len(set(ids)) or len(destinations) != len(set(destinations)):
            raise ValueError("dataset package receipt assets and destinations must be unique")
        hosts = tuple(sorted({urlparse(item.source_url).hostname or "" for item in self.assets}))
        if self.source_hosts != hosts:
            raise ValueError("dataset package receipt hosts differ from its assets")
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class DatasetPackageReceiptInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    receipt: DatasetPackageAcquisitionReceipt


class DatasetArchiveReadApproval(BaseModel):
    """Read-only ZIP qualification authority, separate from package download."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    download_approval_sha256: str = Field(pattern=_SHA256)
    download_approval_file_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    selected_task_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    asset_count: int = Field(gt=0, le=500)
    archive_bytes: int = Field(gt=0, le=500 * 1024**3)
    maximum_unpacked_bytes: int = Field(gt=0, le=1024 * 1024**3)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["zip-central-directory-read-only-no-extraction"]
    authorizes_archive_read: Literal[True] = True
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def read_approval_is_closed(self) -> DatasetArchiveReadApproval:
        if self.approved_at.utcoffset() is None:
            raise ValueError("dataset archive read approval time must include a timezone")
        if len(self.selected_task_ids) != len(set(self.selected_task_ids)):
            raise ValueError("dataset archive read approval task IDs must be unique")
        return self

    @computed_field
    @property
    def read_approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"read_approval_sha256"}))


class DatasetArchiveReadApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: DatasetArchiveReadApproval


class DatasetArchiveFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.\/-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)
    task_id: str | None = Field(default=None, pattern=_ID)
    asset_id: str | None = Field(default=None, pattern=_ID)


class DatasetArchiveAssetQualification(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    asset_id: str = Field(pattern=_ID)
    destination: str = Field(min_length=1, max_length=1_000)
    archive_bytes: int = Field(gt=0)
    member_count: int = Field(ge=0)
    expanded_bytes: int = Field(ge=0)
    safe: bool
    blocker_codes: tuple[str, ...]


class DatasetArchiveTaskQualification(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    asset_count: int = Field(gt=0)
    member_count: int = Field(ge=0)
    expanded_bytes: int = Field(ge=0)
    maximum_unpacked_bytes: int = Field(gt=0)
    safe: bool

    @model_validator(mode="after")
    def task_bytes_fit(self) -> DatasetArchiveTaskQualification:
        if self.safe and self.expanded_bytes > self.maximum_unpacked_bytes:
            raise ValueError("safe archive task exceeds its unpacked-byte ceiling")
        return self


class DatasetArchiveQualificationReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.1"] = "1.1"
    request_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    archive_read_approval_sha256: str = Field(pattern=_SHA256)
    inventory_file_sha256: str = Field(pattern=_SHA256)
    assets: tuple[DatasetArchiveAssetQualification, ...] = Field(min_length=1, max_length=500)
    tasks: tuple[DatasetArchiveTaskQualification, ...] = Field(min_length=1, max_length=20)
    blockers: tuple[DatasetArchiveFinding, ...]
    archive_safety_qualified: bool
    all_receipt_hashes_reverified: bool
    archive_content_read: Literal[True] = True
    extraction_performed: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def qualification_is_closed(self) -> DatasetArchiveQualificationReport:
        if self.archive_safety_qualified != (
            not self.blockers
            and self.all_receipt_hashes_reverified
            and all(item.safe for item in self.assets)
            and all(item.safe for item in self.tasks)
        ):
            raise ValueError("archive safety status differs from its evidence")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def approve_dataset_package_request(
    inspection: DatasetPackageRequestInspection,
    gate_report: DatasetPackageGateReport,
    *,
    confirmed_proposal_sha256: str,
    confirmed_gate_report_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> DatasetPackageApproval:
    """Create authority for one exact ready gate without network or file transfer."""

    request = inspection.request
    if not gate_report.ready_for_owner_approval:
        codes = ", ".join(item.code for item in gate_report.approval_blockers)
        raise ValueError(f"dataset package request is not owner-approval-ready: {codes}")
    if gate_report.integrity_blockers:
        raise ValueError("dataset package request has unresolved integrity blockers")
    _validate_gate_matches_request(inspection, gate_report)
    if confirmed_proposal_sha256 != request.proposal_sha256:
        raise ValueError("confirmed dataset package proposal hash does not match")
    if confirmed_gate_report_sha256 != gate_report.report_sha256:
        raise ValueError("confirmed dataset package gate-report hash does not match")
    if gate_report.proposal_sha256 != request.proposal_sha256:
        raise ValueError("dataset package gate report targets a different proposal")
    if gate_report.request_file_sha256 != inspection.file_sha256:
        raise ValueError("dataset package gate report targets different request bytes")
    return DatasetPackageApproval(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        request_file_sha256=inspection.file_sha256,
        inventory_file_sha256=gate_report.inventory_file_sha256,
        gate_report_sha256=gate_report.report_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="network-preflight-and-download-only-no-extract-no-ingestion",
        selected_task_ids=request.selected_task_ids,
        source_hosts=tuple(sorted(request.allowed_hosts)),
        destination_root=request.destination_root,
        asset_count=request.expected_asset_count,
        expected_download_bytes=request.expected_download_bytes,
        maximum_unpacked_bytes=request.maximum_unpacked_bytes,
        minimum_free_storage_bytes=request.minimum_free_storage_bytes,
    )


def save_dataset_package_approval(approval: DatasetPackageApproval, path: str | Path) -> Path:
    return _atomic_json(path, approval.model_dump(mode="json"), require_absent=True)


def load_dataset_package_approval(path: str | Path) -> DatasetPackageApprovalInspection:
    resolved, raw, payload = _load_json(path, "dataset package approval")
    recorded = payload.pop("approval_sha256", None)
    approval = DatasetPackageApproval.model_validate(payload)
    if recorded != approval.approval_sha256:
        raise ValueError("dataset package approval hash mismatch")
    return DatasetPackageApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def materialize_dataset_package_acquisition(
    inspection: DatasetPackageRequestInspection,
    gate_report: DatasetPackageGateReport,
    approval: DatasetPackageApproval,
    *,
    workspace_root: str | Path,
    confirmed_proposal_sha256: str,
    confirmed_approval_sha256: str,
    allow_network_download: bool,
    fetcher: DatasetPackageStreamFetcher | None = None,
    free_space_probe: DatasetPackageFreeSpaceProbe | None = None,
    acquired_at: datetime | None = None,
) -> DatasetPackageAcquisitionReceipt:
    """Stream an approved package into staging and publish it as one transaction."""

    if not allow_network_download:
        raise ValueError("dataset package acquisition requires --allow-network-download")
    request = inspection.request
    _validate_package_authority(
        inspection,
        gate_report,
        approval,
        confirmed_proposal_sha256=confirmed_proposal_sha256,
        confirmed_approval_sha256=confirmed_approval_sha256,
    )
    root = Path(workspace_root).resolve(strict=True)
    inventory_path = root.joinpath(*PurePosixPath(request.inventory.path).parts)
    if not inventory_path.resolve(strict=True).is_relative_to(root):
        raise ValueError("dataset package inventory escaped its workspace")
    inventory_inspection = load_dataset_package_inventory(inventory_path)
    if inventory_inspection.file_sha256 != approval.inventory_file_sha256:
        raise ValueError("approved dataset package inventory bytes have drifted")
    inventory = inventory_inspection.inventory
    assets = _selected_assets(request.selected_task_ids, inventory)
    _validate_inventory_against_authority(inventory, assets, gate_report, approval)

    destination_relative = PurePosixPath(request.destination_root)
    if destination_relative.name != "raw" or destination_relative.parent.name != request.request_id:
        raise ValueError("dataset package destination must be <request-id>/raw")
    transaction_root = root.joinpath(*destination_relative.parent.parts)
    transaction_parent = transaction_root.parent
    _ensure_directory_chain(root, transaction_parent)
    available = (free_space_probe or _free_space_bytes)(transaction_parent)
    if available < request.minimum_free_storage_bytes:
        raise ValueError(
            "dataset package free-space floor is not met: "
            f"need {request.minimum_free_storage_bytes}, found {available}"
        )
    selected_fetcher = fetcher or _stream_https_asset
    timestamp = acquired_at or datetime.now(UTC)
    staging: Path | None = None

    with _dataset_package_lock(transaction_parent):
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
            staged_raw = staging / "raw"
            staged_raw.mkdir(mode=0o700)
            acquired: list[AcquiredDatasetPackageAsset] = []
            total_bytes = 0
            for task_id, asset in assets:
                target = staged_raw.joinpath(*PurePosixPath(asset.destination).parts)
                _ensure_directory_chain(staged_raw, target.parent)
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                writer = _BoundedHashWriter(descriptor, asset.observed_content_length_bytes)
                try:
                    observation = selected_fetcher(asset, writer)
                    writer.finish()
                except Exception:
                    writer.abort()
                    raise
                _validate_source_observation(asset, observation)
                total_bytes += writer.size_bytes
                if total_bytes > request.expected_download_bytes:
                    raise ValueError("dataset package transfer exceeded exact aggregate bytes")
                acquired.append(
                    AcquiredDatasetPackageAsset(
                        task_id=task_id,
                        asset_id=asset.asset_id,
                        source_kind=asset.source_kind,
                        source_url=asset.source_url,
                        destination=asset.destination,
                        size_bytes=writer.size_bytes,
                        sha256=writer.sha256,
                        observed_content_type=observation.content_type,
                        observed_last_modified=observation.last_modified,
                        observed_etag=observation.etag,
                        observed_filename=observation.content_disposition_filename,
                    )
                )
            if total_bytes != request.expected_download_bytes:
                raise ValueError("dataset package transfer differs from exact aggregate bytes")

            receipt = DatasetPackageAcquisitionReceipt(
                request_id=request.request_id,
                proposal_sha256=request.proposal_sha256,
                request_file_sha256=inspection.file_sha256,
                inventory_file_sha256=inventory_inspection.file_sha256,
                gate_report_sha256=gate_report.report_sha256,
                approval_sha256=approval.approval_sha256,
                approved_by=approval.approved_by,
                approved_at=approval.approved_at,
                acquired_at=timestamp,
                approval_scope=approval.scope,
                destination_root=request.destination_root,
                assets=tuple(acquired),
                asset_count=len(acquired),
                total_bytes=total_bytes,
                expected_download_bytes=request.expected_download_bytes,
                source_hosts=tuple(sorted(request.allowed_hosts)),
            )
            _write_new_bytes(
                staging / "RECEIPT.json",
                (receipt.model_dump_json(indent=2) + "\n").encode(),
            )
            _fsync_directory_tree(staging)
            if os.path.lexists(transaction_root):
                raise FileExistsError(transaction_root)
            os.rename(staging, transaction_root)
            staging = None
            _fsync_directory(transaction_parent)
            return receipt
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)


def load_dataset_package_receipt(path: str | Path) -> DatasetPackageReceiptInspection:
    resolved, raw, payload = _load_json(path, "dataset package acquisition receipt")
    recorded = payload.pop("receipt_sha256", None)
    receipt = DatasetPackageAcquisitionReceipt.model_validate(payload)
    if recorded != receipt.receipt_sha256:
        raise ValueError("dataset package acquisition receipt hash mismatch")
    return DatasetPackageReceiptInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        receipt=receipt,
    )


def approve_dataset_archive_read(
    inspection: DatasetPackageRequestInspection,
    download_approval: DatasetPackageApprovalInspection,
    receipt: DatasetPackageReceiptInspection,
    *,
    confirmed_proposal_sha256: str,
    confirmed_receipt_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> DatasetArchiveReadApproval:
    """Bind local ZIP metadata reads to one exact completed acquisition."""

    _validate_archive_read_chain(inspection, download_approval, receipt)
    request = inspection.request
    acquired = receipt.receipt
    if confirmed_proposal_sha256 != request.proposal_sha256:
        raise ValueError("confirmed dataset archive proposal hash does not match")
    if confirmed_receipt_sha256 != acquired.receipt_sha256:
        raise ValueError("confirmed dataset archive receipt hash does not match")
    if approved_at < acquired.acquired_at:
        raise ValueError("dataset archive read approval cannot precede acquisition")
    return DatasetArchiveReadApproval(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        request_file_sha256=inspection.file_sha256,
        download_approval_sha256=download_approval.approval.approval_sha256,
        download_approval_file_sha256=download_approval.file_sha256,
        receipt_sha256=acquired.receipt_sha256,
        receipt_file_sha256=receipt.file_sha256,
        selected_task_ids=request.selected_task_ids,
        asset_count=acquired.asset_count,
        archive_bytes=acquired.total_bytes,
        maximum_unpacked_bytes=request.maximum_unpacked_bytes,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="zip-central-directory-read-only-no-extraction",
    )


def save_dataset_archive_read_approval(
    approval: DatasetArchiveReadApproval,
    path: str | Path,
) -> Path:
    return _atomic_json(path, approval.model_dump(mode="json"), require_absent=True)


def load_dataset_archive_read_approval(
    path: str | Path,
) -> DatasetArchiveReadApprovalInspection:
    resolved, raw, payload = _load_json(path, "dataset archive read approval")
    recorded = payload.pop("read_approval_sha256", None)
    approval = DatasetArchiveReadApproval.model_validate(payload)
    if recorded != approval.read_approval_sha256:
        raise ValueError("dataset archive read approval hash mismatch")
    return DatasetArchiveReadApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def inspect_dataset_package_archives(
    inspection: DatasetPackageRequestInspection,
    download_approval: DatasetPackageApprovalInspection,
    receipt: DatasetPackageReceiptInspection,
    read_approval: DatasetArchiveReadApprovalInspection,
    *,
    workspace_root: str | Path,
    allow_local_archive_read: bool,
) -> DatasetArchiveQualificationReport:
    """Inspect ZIP central directories and exact local bytes without extraction."""

    if not allow_local_archive_read:
        raise ValueError("dataset archive qualification requires the explicit local-read switch")
    _validate_archive_read_chain(inspection, download_approval, receipt)
    request = inspection.request
    approval = download_approval.approval
    acquired_receipt = receipt.receipt
    local_read = read_approval.approval
    expected_read_binding = {
        "request_id": request.request_id,
        "proposal_sha256": request.proposal_sha256,
        "request_file_sha256": inspection.file_sha256,
        "download_approval_sha256": approval.approval_sha256,
        "download_approval_file_sha256": download_approval.file_sha256,
        "receipt_sha256": acquired_receipt.receipt_sha256,
        "receipt_file_sha256": receipt.file_sha256,
        "selected_task_ids": request.selected_task_ids,
        "asset_count": acquired_receipt.asset_count,
        "archive_bytes": acquired_receipt.total_bytes,
        "maximum_unpacked_bytes": request.maximum_unpacked_bytes,
    }
    observed_read_binding = local_read.model_dump(mode="python")
    for field, value in expected_read_binding.items():
        if observed_read_binding[field] != value:
            raise ValueError(f"dataset archive read approval differs at {field}")
    root = Path(workspace_root).resolve(strict=True)
    inventory_path = root.joinpath(*PurePosixPath(request.inventory.path).parts)
    if not inventory_path.resolve(strict=True).is_relative_to(root):
        raise ValueError("dataset package inventory escaped its workspace")
    inventory_inspection = load_dataset_package_inventory(inventory_path)
    if inventory_inspection.file_sha256 != acquired_receipt.inventory_file_sha256:
        raise ValueError("dataset package receipt inventory has drifted")
    inventory = inventory_inspection.inventory
    expected = _selected_assets(request.selected_task_ids, inventory)
    expected_by_id = {asset.asset_id: (task_id, asset) for task_id, asset in expected}
    receipt_by_id = {asset.asset_id: asset for asset in acquired_receipt.assets}
    if set(expected_by_id) != set(receipt_by_id):
        raise ValueError("dataset package receipt asset set differs from inventory")

    transaction_raw = root.joinpath(*PurePosixPath(acquired_receipt.destination_root).parts)
    if transaction_raw.is_symlink() or not transaction_raw.is_dir():
        raise ValueError("dataset package raw directory is missing or unsafe")
    blockers: list[DatasetArchiveFinding] = []
    asset_results: list[DatasetArchiveAssetQualification] = []
    all_hashes = True
    task_totals: dict[str, dict[str, int]] = {
        task.task_id: {"assets": 0, "members": 0, "expanded": 0}
        for task in inventory.tasks
        if task.task_id in request.selected_task_ids
    }

    for asset_id in (asset.asset_id for _, asset in expected):
        task_id, expected_asset = expected_by_id[asset_id]
        acquired = receipt_by_id[asset_id]
        path = transaction_raw.joinpath(*PurePosixPath(acquired.destination).parts)
        local_codes: list[str] = []
        archive_bytes = 0
        member_count = 0
        expanded_bytes = 0
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(transaction_raw)
        ):
            code = "archive:file-missing-or-unsafe"
            _archive_add(blockers, code, str(path), task_id, asset_id)
            local_codes.append(code)
            all_hashes = False
        else:
            archive_bytes, observed_hash = _hash_file(path)
            if archive_bytes != acquired.size_bytes or observed_hash != acquired.sha256:
                code = "archive:receipt-byte-drift"
                _archive_add(blockers, code, str(path), task_id, asset_id)
                local_codes.append(code)
                all_hashes = False
            if acquired.destination != expected_asset.destination:
                code = "archive:destination-mismatch"
                _archive_add(blockers, code, acquired.destination, task_id, asset_id)
                local_codes.append(code)
            if (
                acquired.task_id != task_id
                or acquired.source_kind is not expected_asset.source_kind
                or acquired.source_url != expected_asset.source_url
                or acquired.size_bytes != expected_asset.observed_content_length_bytes
            ):
                code = "archive:receipt-identity-mismatch"
                _archive_add(blockers, code, acquired.source_url, task_id, asset_id)
                local_codes.append(code)
            try:
                member_count, expanded_bytes, member_findings = _inspect_zip(path)
            except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
                code = "archive:invalid-zip"
                _archive_add(blockers, code, str(exc), task_id, asset_id)
                local_codes.append(code)
            else:
                for code, message in member_findings:
                    _archive_add(blockers, code, message, task_id, asset_id)
                    local_codes.append(code)
        totals = task_totals[task_id]
        totals["assets"] += 1
        totals["members"] += member_count
        totals["expanded"] += expanded_bytes
        asset_results.append(
            DatasetArchiveAssetQualification(
                task_id=task_id,
                asset_id=asset_id,
                destination=acquired.destination,
                archive_bytes=archive_bytes or acquired.size_bytes,
                member_count=member_count,
                expanded_bytes=expanded_bytes,
                safe=not local_codes,
                blocker_codes=tuple(local_codes),
            )
        )

    task_results: list[DatasetArchiveTaskQualification] = []
    task_lookup = {item.task_id: item for item in inventory.tasks}
    for task_id in request.selected_task_ids:
        totals = task_totals[task_id]
        ceiling = task_lookup[task_id].maximum_unpacked_bytes
        if totals["expanded"] > ceiling:
            _archive_add(
                blockers,
                "archive:task-expanded-byte-ceiling",
                f"expanded {totals['expanded']} bytes exceeds {ceiling}",
                task_id,
                None,
            )
        task_blocked = any(item.task_id == task_id for item in blockers)
        task_results.append(
            DatasetArchiveTaskQualification(
                task_id=task_id,
                asset_count=totals["assets"],
                member_count=totals["members"],
                expanded_bytes=totals["expanded"],
                maximum_unpacked_bytes=ceiling,
                safe=not task_blocked,
            )
        )
    qualified = not blockers and all_hashes
    return DatasetArchiveQualificationReport(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        approval_sha256=approval.approval_sha256,
        receipt_sha256=acquired_receipt.receipt_sha256,
        archive_read_approval_sha256=local_read.read_approval_sha256,
        inventory_file_sha256=inventory_inspection.file_sha256,
        assets=tuple(asset_results),
        tasks=tuple(task_results),
        blockers=tuple(blockers),
        archive_safety_qualified=qualified,
        all_receipt_hashes_reverified=all_hashes,
    )


def _validate_archive_read_chain(
    inspection: DatasetPackageRequestInspection,
    download_approval: DatasetPackageApprovalInspection,
    receipt: DatasetPackageReceiptInspection,
) -> None:
    request = inspection.request
    approval = download_approval.approval
    acquired = receipt.receipt
    if acquired.request_id != request.request_id or approval.request_id != request.request_id:
        raise ValueError("dataset package archive inputs target different requests")
    if approval.request_file_sha256 != inspection.file_sha256:
        raise ValueError("dataset package approval targets different request bytes")
    if acquired.proposal_sha256 != request.proposal_sha256:
        raise ValueError("dataset package receipt targets a different proposal")
    if acquired.approval_sha256 != approval.approval_sha256:
        raise ValueError("dataset package receipt targets a different approval")
    if acquired.request_file_sha256 != inspection.file_sha256:
        raise ValueError("dataset package receipt targets different request bytes")
    if acquired.inventory_file_sha256 != approval.inventory_file_sha256:
        raise ValueError("dataset package receipt targets a different inventory")


def save_dataset_archive_qualification_report(
    report: DatasetArchiveQualificationReport,
    path: str | Path,
) -> Path:
    return _atomic_json(path, report.model_dump(mode="json"), require_absent=False)


def load_dataset_archive_qualification_report(
    path: str | Path,
) -> DatasetArchiveQualificationReport:
    _, _, payload = _load_json(path, "dataset archive qualification report")
    recorded = payload.pop("report_sha256", None)
    report = DatasetArchiveQualificationReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("dataset archive qualification report hash mismatch")
    return report


def _validate_package_authority(
    inspection: DatasetPackageRequestInspection,
    gate: DatasetPackageGateReport,
    approval: DatasetPackageApproval,
    *,
    confirmed_proposal_sha256: str,
    confirmed_approval_sha256: str,
) -> None:
    request = inspection.request
    if not gate.ready_for_owner_approval or gate.integrity_blockers or gate.approval_blockers:
        raise ValueError("dataset package gate is not owner-approval-ready")
    _validate_gate_matches_request(inspection, gate)
    if confirmed_proposal_sha256 != request.proposal_sha256:
        raise ValueError("confirmed dataset package proposal hash does not match")
    if confirmed_approval_sha256 != approval.approval_sha256:
        raise ValueError("confirmed dataset package approval hash does not match")
    exact = {
        "request_id": request.request_id,
        "proposal_sha256": request.proposal_sha256,
        "request_file_sha256": inspection.file_sha256,
        "inventory_file_sha256": gate.inventory_file_sha256,
        "gate_report_sha256": gate.report_sha256,
        "selected_task_ids": request.selected_task_ids,
        "source_hosts": tuple(sorted(request.allowed_hosts)),
        "destination_root": request.destination_root,
        "asset_count": request.expected_asset_count,
        "expected_download_bytes": request.expected_download_bytes,
        "maximum_unpacked_bytes": request.maximum_unpacked_bytes,
        "minimum_free_storage_bytes": request.minimum_free_storage_bytes,
    }
    observed = approval.model_dump(mode="python")
    for field, value in exact.items():
        if observed[field] != value:
            raise ValueError(f"dataset package approval differs at {field}")


def _validate_gate_matches_request(
    inspection: DatasetPackageRequestInspection,
    gate: DatasetPackageGateReport,
) -> None:
    request = inspection.request
    exact = {
        "request_id": request.request_id,
        "proposal_sha256": request.proposal_sha256,
        "request_file_sha256": inspection.file_sha256,
        "candidate_file_sha256": request.candidate_manifest.sha256,
        "resource_corpus_file_sha256": request.resource_corpus.sha256,
        "compute_catalog_file_sha256": request.compute_catalog.sha256,
        "selected_task_ids": request.selected_task_ids,
        "source_hosts": tuple(sorted(request.allowed_hosts)),
        "asset_count": request.expected_asset_count,
        "observed_download_bytes": request.expected_download_bytes,
        "maximum_unpacked_bytes": request.maximum_unpacked_bytes,
        "minimum_free_storage_bytes": request.minimum_free_storage_bytes,
    }
    observed = gate.model_dump(mode="python")
    for field, value in exact.items():
        if observed[field] != value:
            raise ValueError(f"dataset package gate differs from request at {field}")


def _validate_inventory_against_authority(
    inventory: DatasetPackageInventory,
    assets: tuple[tuple[str, DatasetPackageAsset], ...],
    gate: DatasetPackageGateReport,
    approval: DatasetPackageApproval,
) -> None:
    if any(
        task.license_disposition.value != "verified" or not task.ready_for_owner_approval
        for task in gate.task_qualifications
    ):
        raise ValueError("dataset package gate contains an unresolved license disposition")
    if len(assets) != approval.asset_count or len(assets) != gate.asset_count:
        raise ValueError("dataset package inventory asset count differs from authority")
    size = sum(asset.observed_content_length_bytes for _, asset in assets)
    if size != approval.expected_download_bytes or size != gate.observed_download_bytes:
        raise ValueError("dataset package inventory bytes differ from authority")


def _selected_assets(
    selected_task_ids: tuple[str, ...],
    inventory: DatasetPackageInventory,
) -> tuple[tuple[str, DatasetPackageAsset], ...]:
    tasks = {task.task_id: task for task in inventory.tasks}
    if set(tasks) != set(selected_task_ids):
        raise ValueError("dataset package inventory task set differs from request")
    return tuple(
        (task_id, asset) for task_id in selected_task_ids for asset in tasks[task_id].assets
    )


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _stream_https_asset(
    asset: DatasetPackageAsset,
    sink: DatasetPackageSink,
) -> DatasetPackageSourceObservation:
    request = Request(
        asset.source_url,
        headers={
            "Accept": "application/zip,application/octet-stream;q=0.9",
            "Accept-Encoding": "identity",
            "User-Agent": "SciTaste-approved-package-acquisition/1.0",
        },
        method="GET",
    )
    opener = build_opener(_RejectRedirects())
    try:
        response = opener.open(request, timeout=_TIMEOUT_SECONDS)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ValueError("dataset package redirects are forbidden") from exc
        raise
    with response:
        observation = _response_observation(response, asset.source_url)
        _validate_source_observation(asset, observation)
        while chunk := response.read(_CHUNK_BYTES):
            sink.write(chunk)
    return observation


def _response_observation(response, requested_url: str) -> DatasetPackageSourceObservation:
    if getattr(response, "status", None) != 200:
        raise ValueError("dataset package source did not return HTTP 200")
    final_url = response.geturl()
    if final_url != requested_url:
        raise ValueError("dataset package redirects are forbidden")
    encoding = response.headers.get("Content-Encoding")
    if encoding is not None and encoding.strip().lower() != "identity":
        raise ValueError("dataset package source returned content encoding")
    raw_type = response.headers.get("Content-Type")
    raw_length = response.headers.get("Content-Length")
    raw_modified = response.headers.get("Last-Modified")
    if raw_type is None or raw_length is None or raw_modified is None:
        raise ValueError("dataset package source omitted required identity headers")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("dataset package source returned invalid Content-Length") from exc
    try:
        modified = parsedate_to_datetime(raw_modified)
    except (TypeError, ValueError) as exc:
        raise ValueError("dataset package source returned invalid Last-Modified") from exc
    disposition = response.headers.get("Content-Disposition")
    filename = None
    if disposition is not None:
        message = Message()
        message["Content-Disposition"] = disposition
        filename = message.get_filename()
    return DatasetPackageSourceObservation(
        final_url=final_url,
        content_type=raw_type.partition(";")[0].strip().lower(),
        content_length_bytes=length,
        last_modified=modified,
        etag=response.headers.get("ETag"),
        content_disposition_filename=filename,
    )


def _validate_source_observation(
    asset: DatasetPackageAsset,
    observation: DatasetPackageSourceObservation,
) -> None:
    if observation.final_url != asset.source_url or observation.redirected:
        raise ValueError(f"dataset package source identity drifted: {asset.asset_id}")
    if observation.content_type.lower() not in _ALLOWED_ZIP_MEDIA_TYPES:
        raise ValueError(f"dataset package media type drifted: {asset.asset_id}")
    if observation.content_length_bytes != asset.observed_content_length_bytes:
        raise ValueError(f"dataset package Content-Length drifted: {asset.asset_id}")
    # HTTP-date has one-second precision (RFC 9110), while object-store metadata
    # can expose sub-second timestamps for the same immutable object.  Compare
    # the exact UTC HTTP representation rather than treating unavailable
    # fractional digits as source drift.
    expected_http_date = asset.observed_last_modified.astimezone(UTC).replace(microsecond=0)
    observed_http_date = observation.last_modified.astimezone(UTC)
    if observed_http_date.microsecond or observed_http_date != expected_http_date:
        raise ValueError(f"dataset package Last-Modified drifted: {asset.asset_id}")
    if asset.source_kind is DatasetAssetSourceKind.GOOGLE_DRIVE_FILE:
        if observation.content_disposition_filename != asset.filename:
            raise ValueError(f"dataset package filename drifted: {asset.asset_id}")
    else:
        expected_etag = _strong_etag_opaque_value(asset.source_etag)
        observed_etag = _strong_etag_opaque_value(observation.etag)
        if expected_etag is None or observed_etag is None or observed_etag != expected_etag:
            raise ValueError(f"dataset package ETag drifted: {asset.asset_id}")


def _strong_etag_opaque_value(value: str | None) -> str | None:
    """Normalize only optional HTTP quotes; weak or malformed validators fail closed."""

    if value is None:
        return None
    candidate = value.strip()
    if not candidate or candidate[:2].casefold() == "w/":
        return None
    if candidate.startswith('"') or candidate.endswith('"'):
        if len(candidate) < 3 or not (candidate.startswith('"') and candidate.endswith('"')):
            return None
        candidate = candidate[1:-1]
    if not candidate or '"' in candidate or any(ord(character) < 33 for character in candidate):
        return None
    return candidate


class _BoundedHashWriter:
    def __init__(self, descriptor: int, expected_bytes: int) -> None:
        self._handle = os.fdopen(descriptor, "wb")
        self._expected_bytes = expected_bytes
        self._hash = hashlib.sha256()
        self.size_bytes = 0
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ValueError("dataset package stream is already closed")
        if not isinstance(data, bytes) or not data:
            raise ValueError("dataset package stream chunks must be non-empty bytes")
        if self.size_bytes + len(data) > self._expected_bytes:
            raise ValueError("dataset package stream exceeded exact asset bytes")
        written = self._handle.write(data)
        if written != len(data):
            raise OSError("dataset package stream performed a short local write")
        self._hash.update(data)
        self.size_bytes += written
        return written

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()

    def finish(self) -> None:
        if self._closed:
            return
        if self.size_bytes != self._expected_bytes:
            raise ValueError("dataset package stream ended before exact asset bytes")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._closed = True

    def abort(self) -> None:
        if not self._closed:
            self._handle.close()
            self._closed = True


def _inspect_zip(path: Path) -> tuple[int, int, tuple[tuple[str, str], ...]]:
    findings: list[tuple[str, str]] = []
    normalized_names: set[str] = set()
    expanded = 0
    with zipfile.ZipFile(path, "r", allowZip64=True) as archive:
        members = archive.infolist()
        if len(members) > _MAX_MEMBERS_PER_ARCHIVE:
            findings.append(("archive:member-count-ceiling", str(len(members))))
        for info in members:
            name = info.filename
            normalized = name[:-1] if name.endswith("/") else name
            if not normalized:
                findings.append(("archive:empty-member-name", name))
                continue
            if any(ord(character) < 32 or ord(character) == 127 for character in name):
                findings.append(("archive:control-character-path", name))
            if "\\" in name:
                findings.append(("archive:backslash-path", name))
            member_path = PurePosixPath(normalized)
            if (
                member_path.is_absolute()
                or any(part in {"", ".", ".."} for part in normalized.split("/"))
                or (member_path.parts and ":" in member_path.parts[0])
            ):
                findings.append(("archive:path-escape", name))
            canonical = member_path.as_posix()
            if canonical in normalized_names:
                findings.append(("archive:duplicate-member", canonical))
            normalized_names.add(canonical)
            if info.flag_bits & 0x1:
                findings.append(("archive:encrypted-member", name))
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                findings.append(("archive:symlink-member", name))
            expanded += info.file_size
            if info.file_size and info.compress_size == 0:
                findings.append(("archive:zero-compressed-member", name))
            elif info.compress_size:
                ratio = info.file_size / info.compress_size
                if ratio > _MAX_COMPRESSION_RATIO:
                    findings.append(("archive:compression-ratio-ceiling", name))
    return len(members), expanded, tuple(findings)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _free_space_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _load_json(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, raw, payload


def _atomic_json(path: str | Path, payload: object, *, require_absent: bool) -> Path:
    target = Path(path)
    if target.is_symlink() or (require_absent and target.exists()):
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
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
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _ensure_directory_chain(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("dataset package directory escaped its workspace") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("dataset package directory cannot contain symlinks")
        current.mkdir(exist_ok=True)
        if not current.is_dir() or not current.resolve(strict=True).is_relative_to(root):
            raise ValueError("dataset package directory escaped its workspace")


class _dataset_package_lock:
    def __init__(self, directory: Path) -> None:
        self._path = directory / ".scitaste-dataset-package.lock"
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


def _fsync_directory_tree(root: Path) -> None:
    directories = [root, *(item for item in root.rglob("*") if item.is_dir())]
    for directory in reversed(directories):
        _fsync_directory(directory)


def _validate_relative_path(value: str, label: str) -> None:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")


def _archive_add(
    findings: list[DatasetArchiveFinding],
    code: str,
    message: str,
    task_id: str | None,
    asset_id: str | None,
) -> None:
    finding = DatasetArchiveFinding(
        code=code,
        message=message,
        task_id=task_id,
        asset_id=asset_id,
    )
    if finding not in findings:
        findings.append(finding)


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "AcquiredDatasetPackageAsset",
    "DatasetArchiveAssetQualification",
    "DatasetArchiveFinding",
    "DatasetArchiveQualificationReport",
    "DatasetArchiveReadApproval",
    "DatasetArchiveReadApprovalInspection",
    "DatasetArchiveTaskQualification",
    "DatasetPackageAcquisitionReceipt",
    "DatasetPackageApproval",
    "DatasetPackageApprovalInspection",
    "DatasetPackageFreeSpaceProbe",
    "DatasetPackageReceiptInspection",
    "DatasetPackageSink",
    "DatasetPackageSourceObservation",
    "DatasetPackageStreamFetcher",
    "approve_dataset_archive_read",
    "approve_dataset_package_request",
    "inspect_dataset_package_archives",
    "load_dataset_archive_qualification_report",
    "load_dataset_archive_read_approval",
    "load_dataset_package_approval",
    "load_dataset_package_receipt",
    "materialize_dataset_package_acquisition",
    "save_dataset_archive_qualification_report",
    "save_dataset_archive_read_approval",
    "save_dataset_package_approval",
]
