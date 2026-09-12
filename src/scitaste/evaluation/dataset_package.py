"""No-network qualification for large benchmark dataset package requests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import parse_qs, urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.executable_candidate import (
    inspect_executable_candidate,
    load_executable_candidate_manifest,
)
from scitaste.resources import load_compute_resource_catalog

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_BYTES = 2 * 1024 * 1024


class DatasetAssetSourceKind(StrEnum):
    GOOGLE_DRIVE_FILE = "google_drive_file"
    OPENML_OBJECT = "openml_object"


class DatasetAssetLicenseStatus(StrEnum):
    VERIFIED = "verified"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class DatasetAssetLicenseDisposition(StrEnum):
    VERIFIED = "verified"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class DatasetPackageFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> DatasetPackageFileBinding:
        _validate_relative_path(self.path, "dataset package binding")
        return self


class DatasetPackageAsset(BaseModel):
    model_config = _CONFIG

    asset_id: str = Field(pattern=_ID)
    filename: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=1_000)
    source_kind: DatasetAssetSourceKind
    source_url: str = Field(min_length=1, max_length=2_000)
    provider_object_id: str = Field(min_length=1, max_length=300)
    openml_dataset_id: int | None = Field(default=None, gt=0)
    openml_dataset_version: int | None = Field(default=None, gt=0)
    source_etag: str | None = Field(default=None, min_length=1, max_length=300)
    observed_content_length_bytes: int = Field(gt=0, le=100 * 1024**3)
    observed_last_modified: datetime
    media_type: Literal["application/zip"] = "application/zip"
    license_identifier: str = Field(min_length=1, max_length=200)
    license_evidence_urls: tuple[str, ...] = Field(min_length=1, max_length=10)
    license_status: DatasetAssetLicenseStatus
    license_note: str = Field(min_length=1, max_length=2_000)
    content_hash_status: Literal["pending-until-acquisition"] = "pending-until-acquisition"
    expected_sha256: None = None

    @model_validator(mode="after")
    def source_and_destination_are_exact(self) -> DatasetPackageAsset:
        _validate_relative_path(self.destination, "dataset package destination")
        if PurePosixPath(self.destination).name != self.filename:
            raise ValueError("dataset package destination basename must equal its filename")
        source = urlparse(self.source_url)
        if (
            source.scheme != "https"
            or not source.hostname
            or source.port not in {None, 443}
            or source.username
            or source.password
            or source.fragment
        ):
            raise ValueError("dataset package source must be credential-free standard HTTPS")
        if len(self.license_evidence_urls) != len(set(self.license_evidence_urls)):
            raise ValueError("dataset package license evidence URLs must be unique")
        for evidence_url in self.license_evidence_urls:
            evidence = urlparse(evidence_url)
            if evidence.scheme != "https" or not evidence.hostname:
                raise ValueError("dataset package license evidence must use HTTPS")
        if self.observed_last_modified.utcoffset() is None:
            raise ValueError("dataset package source observation must include a timezone")

        if self.source_kind is DatasetAssetSourceKind.GOOGLE_DRIVE_FILE:
            query = parse_qs(source.query)
            if source.hostname != "drive.usercontent.google.com":
                raise ValueError(
                    "Google Drive package source must use drive.usercontent.google.com"
                )
            if query.get("id") != [self.provider_object_id]:
                raise ValueError("Google Drive package source ID differs from its object identity")
            if self.openml_dataset_id is not None or self.openml_dataset_version is not None:
                raise ValueError("Google Drive package source cannot declare an OpenML identity")
            if self.source_etag is not None:
                raise ValueError("Google Drive package source cannot invent an unobserved ETag")
        elif self.source_kind is DatasetAssetSourceKind.OPENML_OBJECT:
            if source.hostname != "data.openml.org":
                raise ValueError("OpenML package source must use data.openml.org")
            if self.openml_dataset_id is None or self.openml_dataset_version is None:
                raise ValueError("OpenML package source requires dataset ID and version")
            if self.source_etag is None:
                raise ValueError("OpenML package source requires its observed object ETag")
            expected_path = f"/datasets/0004/{self.openml_dataset_id}/{self.filename}"
            if source.path != expected_path or self.provider_object_id != str(
                self.openml_dataset_id
            ):
                raise ValueError("OpenML package source URL differs from its dataset identity")
            if source.query:
                raise ValueError("OpenML package object source cannot contain a query")
        return self


class DatasetPackageTaskInventory(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    paper_task_name: str = Field(min_length=1, max_length=300)
    source_group: str = Field(pattern=_ID)
    benchmark_dataflow_paths: tuple[str, ...] = Field(min_length=1, max_length=20)
    assets: tuple[DatasetPackageAsset, ...] = Field(min_length=1, max_length=100)
    observed_compressed_bytes: int = Field(gt=0, le=200 * 1024**3)
    maximum_unpacked_bytes: int = Field(gt=0, le=500 * 1024**3)
    license_disposition: DatasetAssetLicenseDisposition

    @model_validator(mode="after")
    def task_inventory_is_closed(self) -> DatasetPackageTaskInventory:
        for path in self.benchmark_dataflow_paths:
            _validate_relative_path(path, "benchmark data-flow evidence")
        asset_ids = [item.asset_id for item in self.assets]
        destinations = [item.destination for item in self.assets]
        if len(asset_ids) != len(set(asset_ids)) or len(destinations) != len(set(destinations)):
            raise ValueError("dataset task asset IDs and destinations must be unique")
        if self.observed_compressed_bytes != sum(
            item.observed_content_length_bytes for item in self.assets
        ):
            raise ValueError("dataset task compressed-byte total differs from its assets")
        if self.maximum_unpacked_bytes < self.observed_compressed_bytes:
            raise ValueError("dataset task unpacked ceiling is below its compressed bytes")
        statuses = {item.license_status for item in self.assets}
        expected = DatasetAssetLicenseDisposition.VERIFIED
        if DatasetAssetLicenseStatus.BLOCKED in statuses:
            expected = DatasetAssetLicenseDisposition.BLOCKED
        elif DatasetAssetLicenseStatus.REVIEW_REQUIRED in statuses:
            expected = DatasetAssetLicenseDisposition.REVIEW_REQUIRED
        if self.license_disposition is not expected:
            raise ValueError("dataset task license disposition differs from its assets")
        return self


class DatasetPackageInventory(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    inventory_id: str = Field(pattern=_ID)
    observed_at: datetime
    authorization_scope: Literal["metadata-only-no-download-no-execution"]
    benchmark_repository: str = Field(min_length=1, max_length=2_000)
    benchmark_commit: str = Field(pattern=_COMMIT)
    perception_license_commit: str = Field(pattern=_COMMIT)
    meta_album_license_commit: str = Field(pattern=_COMMIT)
    tasks: tuple[DatasetPackageTaskInventory, ...] = Field(min_length=1, max_length=20)
    asset_count: int = Field(gt=0)
    observed_compressed_bytes: int = Field(gt=0, le=500 * 1024**3)
    maximum_unpacked_bytes: int = Field(gt=0, le=1024 * 1024**3)
    authorizes_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def inventory_is_closed(self) -> DatasetPackageInventory:
        if self.observed_at.utcoffset() is None:
            raise ValueError("dataset inventory observation must include a timezone")
        task_ids = [item.task_id for item in self.tasks]
        asset_ids = [asset.asset_id for task in self.tasks for asset in task.assets]
        if len(task_ids) != len(set(task_ids)) or len(asset_ids) != len(set(asset_ids)):
            raise ValueError("dataset inventory task and asset IDs must be globally unique")
        if self.asset_count != len(asset_ids):
            raise ValueError("dataset inventory asset count differs from its tasks")
        if self.observed_compressed_bytes != sum(
            task.observed_compressed_bytes for task in self.tasks
        ):
            raise ValueError("dataset inventory compressed-byte total differs from its tasks")
        if self.maximum_unpacked_bytes != sum(task.maximum_unpacked_bytes for task in self.tasks):
            raise ValueError("dataset inventory unpacked ceiling differs from its tasks")
        return self


class DatasetPackageAcquisitionRequest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    track_id: str = Field(pattern=_ID)
    authorization_scope: Literal["review-only-no-download-no-execution"]
    purpose: str = Field(min_length=1, max_length=2_000)
    claim_boundary: str = Field(min_length=1, max_length=2_000)
    candidate_manifest: DatasetPackageFileBinding
    resource_corpus: DatasetPackageFileBinding
    compute_catalog: DatasetPackageFileBinding
    inventory: DatasetPackageFileBinding
    license_policy: DatasetPackageFileBinding | None = None
    selected_task_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    allowed_hosts: tuple[str, ...] = Field(min_length=1, max_length=20)
    destination_root: str = Field(min_length=1, max_length=1_000)
    expected_asset_count: int = Field(gt=0)
    expected_download_bytes: int = Field(gt=0, le=500 * 1024**3)
    maximum_unpacked_bytes: int = Field(gt=0, le=1024 * 1024**3)
    minimum_free_storage_bytes: int = Field(gt=0, le=2 * 1024**4)
    owner_approval_required: Literal[True] = True
    owner_approved: Literal[False] = False
    authorizes_network_preflight: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def request_scope_is_closed(self) -> DatasetPackageAcquisitionRequest:
        _validate_relative_path(self.destination_root, "dataset package root")
        if len(self.selected_task_ids) != len(set(self.selected_task_ids)):
            raise ValueError("dataset package selected task IDs must be unique")
        if len(self.allowed_hosts) != len(set(self.allowed_hosts)):
            raise ValueError("dataset package allowed hosts must be unique")
        if self.minimum_free_storage_bytes < self.maximum_unpacked_bytes:
            raise ValueError("dataset package minimum free storage is below its unpacked ceiling")
        return self

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"proposal_sha256"}))


class DatasetPackageInventoryInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    inventory: DatasetPackageInventory


class DatasetPackageRequestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    request: DatasetPackageAcquisitionRequest


class DatasetPackageFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.\/-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)
    task_id: str | None = Field(default=None, pattern=_ID)


class DatasetPackageTaskQualification(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    asset_count: int = Field(gt=0)
    observed_compressed_bytes: int = Field(gt=0)
    maximum_unpacked_bytes: int = Field(gt=0)
    license_disposition: DatasetAssetLicenseDisposition
    exact_source_metadata_ready: bool
    ready_for_owner_approval: bool
    blocker_codes: tuple[str, ...]


class DatasetPackageGateReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    inventory_file_sha256: str = Field(pattern=_SHA256)
    candidate_file_sha256: str = Field(pattern=_SHA256)
    resource_corpus_file_sha256: str = Field(pattern=_SHA256)
    compute_catalog_file_sha256: str = Field(pattern=_SHA256)
    selected_task_ids: tuple[str, ...]
    source_hosts: tuple[str, ...]
    asset_count: int = Field(ge=0)
    observed_download_bytes: int = Field(ge=0)
    maximum_unpacked_bytes: int = Field(ge=0)
    minimum_free_storage_bytes: int = Field(gt=0)
    task_qualifications: tuple[DatasetPackageTaskQualification, ...]
    metadata_review_ready: bool
    ready_for_owner_approval: bool
    download_authorized: Literal[False] = False
    integrity_blockers: tuple[DatasetPackageFinding, ...]
    approval_blockers: tuple[DatasetPackageFinding, ...]
    pending_qualifications: tuple[DatasetPackageFinding, ...]
    authorization_blockers: tuple[DatasetPackageFinding, ...]
    pending_content_hash_count: int = Field(ge=0)
    authorizes_network_preflight: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_network_access_performed: Literal[True] = True
    no_download_performed: Literal[True] = True
    no_dataset_file_created: Literal[True] = True

    @model_validator(mode="after")
    def report_is_closed(self) -> DatasetPackageGateReport:
        if self.asset_count != sum(item.asset_count for item in self.task_qualifications):
            raise ValueError("dataset package report asset count differs from its tasks")
        if self.observed_download_bytes != sum(
            item.observed_compressed_bytes for item in self.task_qualifications
        ):
            raise ValueError("dataset package report download bytes differ from its tasks")
        if self.maximum_unpacked_bytes != sum(
            item.maximum_unpacked_bytes for item in self.task_qualifications
        ):
            raise ValueError("dataset package report unpacked bytes differ from its tasks")
        if self.metadata_review_ready != (not self.integrity_blockers):
            raise ValueError("dataset package metadata readiness differs from integrity blockers")
        if self.ready_for_owner_approval != (
            self.metadata_review_ready and not self.approval_blockers
        ):
            raise ValueError("dataset package approval readiness differs from its blockers")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def load_dataset_package_inventory(path: str | Path) -> DatasetPackageInventoryInspection:
    resolved, raw, payload = _load_yaml(path, "dataset package inventory")
    return DatasetPackageInventoryInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        inventory=DatasetPackageInventory.model_validate(payload),
    )


def load_dataset_package_request(path: str | Path) -> DatasetPackageRequestInspection:
    resolved, raw, payload = _load_yaml(path, "dataset package request")
    return DatasetPackageRequestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        request=DatasetPackageAcquisitionRequest.model_validate(payload),
    )


def inspect_dataset_package_request(
    inspection: DatasetPackageRequestInspection,
    *,
    workspace_root: str | Path,
) -> DatasetPackageGateReport:
    """Cross-check one large-asset request without contacting any source host."""

    root = Path(workspace_root).resolve(strict=True)
    request = inspection.request
    integrity: list[DatasetPackageFinding] = []
    approvals: list[DatasetPackageFinding] = []
    pending: list[DatasetPackageFinding] = []
    authorization: list[DatasetPackageFinding] = []

    candidate_path = _verify_binding(root, request.candidate_manifest, integrity, "candidate")
    corpus_path = _verify_binding(root, request.resource_corpus, integrity, "resource-corpus")
    compute_path = _verify_binding(root, request.compute_catalog, integrity, "compute-catalog")
    inventory_path = _verify_binding(root, request.inventory, integrity, "inventory")
    license_policy_path = None
    if request.license_policy is not None:
        license_policy_path = _verify_binding(
            root,
            request.license_policy,
            integrity,
            "license-policy",
        )

    inventory_inspection: DatasetPackageInventoryInspection | None = None
    candidate_report = None
    license_policy_inspection = None
    license_policy_report = None
    if inventory_path is not None:
        try:
            inventory_inspection = load_dataset_package_inventory(inventory_path)
        except (OSError, ValueError) as exc:
            _add(integrity, "inventory:invalid", str(exc))
    if candidate_path is not None and corpus_path is not None and compute_path is not None:
        try:
            candidate = load_executable_candidate_manifest(candidate_path)
            candidate_report = inspect_executable_candidate(
                candidate,
                resource_corpus_path=corpus_path,
                compute_catalog_path=compute_path,
            )
        except (OSError, ValueError) as exc:
            _add(integrity, "candidate:invalid", str(exc))
    if license_policy_path is not None:
        try:
            from scitaste.evaluation.dataset_license_policy import (
                inspect_dataset_license_policy,
                load_dataset_license_policy,
            )

            license_policy_inspection = load_dataset_license_policy(license_policy_path)
            license_policy_report = inspect_dataset_license_policy(
                license_policy_inspection,
                workspace_root=root,
            )
        except (OSError, ValueError) as exc:
            _add(integrity, "license-policy:invalid", str(exc))
        else:
            if license_policy_inspection.policy.project_id != request.project_id:
                _add(
                    integrity,
                    "license-policy:project-mismatch",
                    "license policy targets a different project",
                )
            if license_policy_inspection.policy.inventory != request.inventory:
                _add(
                    integrity,
                    "license-policy:inventory-mismatch",
                    "license policy targets different inventory bytes",
                )
            if license_policy_report.asset_count != request.expected_asset_count:
                _add(
                    integrity,
                    "license-policy:asset-count-mismatch",
                    "license policy asset count differs from the request",
                )
            for finding in license_policy_report.integrity_blockers:
                _add(
                    integrity,
                    f"license-policy:{finding.code}",
                    finding.message,
                    finding.task_id,
                )
            for finding in license_policy_report.pending_post_acquisition_checks:
                _add(
                    pending,
                    finding.code,
                    finding.message,
                    finding.task_id,
                )

    tasks: list[DatasetPackageTaskQualification] = []
    source_hosts: tuple[str, ...] = ()
    asset_count = 0
    observed_bytes = 0
    unpacked_bytes = 0
    pending_hashes = 0
    if inventory_inspection is not None:
        inventory = inventory_inspection.inventory
        inventory_tasks = tuple(item.task_id for item in inventory.tasks)
        if inventory_tasks != request.selected_task_ids:
            _add(integrity, "inventory:task-order-mismatch", "inventory tasks differ from request")
        assets = tuple(asset for task in inventory.tasks for asset in task.assets)
        source_hosts = tuple(sorted({urlparse(item.source_url).hostname or "" for item in assets}))
        if source_hosts != tuple(sorted(request.allowed_hosts)):
            _add(integrity, "inventory:host-allowlist-mismatch", "source hosts differ")
        if inventory.asset_count != request.expected_asset_count:
            _add(integrity, "inventory:asset-count-mismatch", "asset count differs")
        if inventory.observed_compressed_bytes != request.expected_download_bytes:
            _add(integrity, "inventory:download-byte-mismatch", "download bytes differ")
        if inventory.maximum_unpacked_bytes != request.maximum_unpacked_bytes:
            _add(integrity, "inventory:unpacked-byte-mismatch", "unpacked ceiling differs")
        asset_count = inventory.asset_count
        observed_bytes = inventory.observed_compressed_bytes
        unpacked_bytes = inventory.maximum_unpacked_bytes
        pending_hashes = sum(item.expected_sha256 is None for item in assets)
        license_task_ready = {
            item.task_id: item.acquisition_license_ready
            for item in (
                license_policy_report.task_qualifications
                if license_policy_report is not None
                else ()
            )
        }
        for task in inventory.tasks:
            blockers: list[str] = []
            policy_ready = license_task_ready.get(task.task_id, False)
            if request.license_policy is not None and not policy_ready:
                code = f"license-policy:{task.task_id}:not-acquisition-ready"
                blockers.append(code)
                _add(
                    approvals,
                    code,
                    "bound license policy does not close the acquisition scope",
                    task.task_id,
                )
            elif (
                request.license_policy is None
                and task.license_disposition is not DatasetAssetLicenseDisposition.VERIFIED
            ):
                code = f"license:{task.task_id}:{task.license_disposition.value}"
                blockers.append(code)
                _add(
                    approvals,
                    code,
                    "task assets require license-scope resolution before approval",
                    task.task_id,
                )
            tasks.append(
                DatasetPackageTaskQualification(
                    task_id=task.task_id,
                    asset_count=len(task.assets),
                    observed_compressed_bytes=task.observed_compressed_bytes,
                    maximum_unpacked_bytes=task.maximum_unpacked_bytes,
                    license_disposition=(
                        DatasetAssetLicenseDisposition.VERIFIED
                        if policy_ready
                        else task.license_disposition
                    ),
                    exact_source_metadata_ready=True,
                    ready_for_owner_approval=not blockers,
                    blocker_codes=tuple(blockers),
                )
            )

    if candidate_report is not None:
        if not candidate_report.metadata_review_ready:
            _add(integrity, "candidate:not-metadata-ready", "candidate metadata gate failed")
        if candidate_report.first_preflight_candidate_ids != request.selected_task_ids:
            _add(
                integrity,
                "candidate:first-preflight-task-mismatch",
                "request tasks differ from the candidate's first preflight slice",
            )

    if compute_path is not None:
        try:
            compute = load_compute_resource_catalog(compute_path)
        except (OSError, ValueError) as exc:
            _add(integrity, "compute-catalog:invalid", str(exc))
        else:
            if compute.file_sha256 != request.compute_catalog.sha256:
                _add(integrity, "compute-catalog:file-hash-mismatch", "catalog hash differs")

    destination = root.joinpath(*PurePosixPath(request.destination_root).parts)
    if not destination.resolve(strict=False).is_relative_to(root):
        _add(integrity, "destination:outside-workspace", request.destination_root)
    if destination.exists() or destination.is_symlink():
        _add(approvals, "destination:already-exists", request.destination_root)
    _add(
        pending,
        "network-preflight:not-approved",
        "source lengths, modification times, and ETags must be rechecked "
        "immediately before an approved download",
    )
    _add(
        pending,
        "content-hashes:pending-first-acquisition",
        f"{pending_hashes} archive SHA-256 values will be fixed by an atomic acquisition receipt",
    )
    _add(
        pending,
        "archive-safety:qualification-pending",
        "archive members, expanded bytes, path containment, and task data flow remain unverified",
    )
    _add(
        authorization,
        "owner-approval-required",
        "the owner has not approved this exact request hash",
    )

    metadata_ready = not integrity
    ready_for_owner_approval = metadata_ready and not approvals
    return DatasetPackageGateReport(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        request_file_sha256=inspection.file_sha256,
        inventory_file_sha256=(
            inventory_inspection.file_sha256
            if inventory_inspection is not None
            else request.inventory.sha256
        ),
        candidate_file_sha256=request.candidate_manifest.sha256,
        resource_corpus_file_sha256=request.resource_corpus.sha256,
        compute_catalog_file_sha256=request.compute_catalog.sha256,
        selected_task_ids=request.selected_task_ids,
        source_hosts=source_hosts,
        asset_count=asset_count,
        observed_download_bytes=observed_bytes,
        maximum_unpacked_bytes=unpacked_bytes,
        minimum_free_storage_bytes=request.minimum_free_storage_bytes,
        task_qualifications=tuple(tasks),
        metadata_review_ready=metadata_ready,
        ready_for_owner_approval=ready_for_owner_approval,
        integrity_blockers=tuple(integrity),
        approval_blockers=tuple(approvals),
        pending_qualifications=tuple(pending),
        authorization_blockers=tuple(authorization),
        pending_content_hash_count=pending_hashes,
    )


def save_dataset_package_gate_report(
    report: DatasetPackageGateReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("dataset package report output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_dataset_package_gate_report(path: str | Path) -> DatasetPackageGateReport:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("dataset package report must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BYTES:
        raise ValueError("dataset package report must be a bounded regular file")
    try:
        payload = json.loads(resolved.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dataset package report must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("dataset package report must contain a JSON object")
    recorded = payload.pop("report_sha256", None)
    report = DatasetPackageGateReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("dataset package report hash mismatch")
    return report


def _load_yaml(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a YAML mapping")
    return resolved, raw, payload


def _verify_binding(
    root: Path,
    binding: DatasetPackageFileBinding,
    findings: list[DatasetPackageFinding],
    label: str,
) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(binding.path).parts)
    if candidate.is_symlink() or not candidate.is_file():
        _add(findings, f"{label}:missing", binding.path)
        return None
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        _add(findings, f"{label}:outside-workspace", binding.path)
        return None
    if resolved.stat().st_size > _MAX_BYTES:
        _add(findings, f"{label}:too-large", binding.path)
        return None
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != binding.sha256:
        _add(findings, f"{label}:hash-mismatch", binding.path)
        return None
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")


def _add(
    target: list[DatasetPackageFinding],
    code: str,
    message: str,
    task_id: str | None = None,
) -> None:
    finding = DatasetPackageFinding(code=code, message=message, task_id=task_id)
    if finding not in target:
        target.append(finding)


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "DatasetAssetLicenseDisposition",
    "DatasetAssetLicenseStatus",
    "DatasetAssetSourceKind",
    "DatasetPackageAcquisitionRequest",
    "DatasetPackageAsset",
    "DatasetPackageFileBinding",
    "DatasetPackageFinding",
    "DatasetPackageGateReport",
    "DatasetPackageInventory",
    "DatasetPackageInventoryInspection",
    "DatasetPackageRequestInspection",
    "DatasetPackageTaskInventory",
    "DatasetPackageTaskQualification",
    "inspect_dataset_package_request",
    "load_dataset_package_gate_report",
    "load_dataset_package_inventory",
    "load_dataset_package_request",
    "save_dataset_package_gate_report",
]
