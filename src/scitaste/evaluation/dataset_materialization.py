"""Approval-gated projection of acquired archives into isolated task data views.

Acquisition proves which bytes were downloaded and archive qualification proves
that their ZIP metadata is safe to inspect.  Neither operation authorizes those
bytes to enter a benchmark workspace.  This module provides that missing,
separate transaction: an owner approves one exact archive-to-task mapping, then
the materializer publishes a development-only data tree and a held-out-only data
tree atomically.  It never installs an environment, invokes a model, uses a GPU,
or executes the benchmark.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import IO, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.dataset_package_acquisition import (
    DatasetArchiveQualificationReport,
    DatasetPackageAcquisitionReceipt,
    load_dataset_archive_qualification_report,
    load_dataset_package_receipt,
)
from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    RuntimeEvidenceBinding,
    load_benchmark_task_runtime_spec,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONFIG_BYTES = 2 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


class DatasetArchiveProjection(BaseModel):
    """One exact acquired archive projected into one non-overlapping data view."""

    model_config = _CONFIG

    asset_id: str
    split_role: Literal["development", "heldout"]
    archive_destination: str
    archive_sha256: str = Field(pattern=_SHA256)
    archive_bytes: int = Field(gt=0, le=100 * 1024**3)
    expected_member_count: int = Field(gt=0, le=250_000)
    expected_expanded_bytes: int = Field(gt=0, le=500 * 1024**3)
    layout: Literal["flat-files", "single-file"]
    target_locator: str
    member_suffix: str | None = Field(default=None, pattern=r"^\.[A-Za-z0-9]{1,16}$")
    expected_member_name: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("asset_id")
    @classmethod
    def asset_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="asset_id")

    @field_validator("archive_destination", "target_locator")
    @classmethod
    def paths_are_safe(cls, value: str, info: object) -> str:
        return _relative_locator(value, label=str(getattr(info, "field_name", "path")))

    @model_validator(mode="after")
    def layout_is_closed(self) -> DatasetArchiveProjection:
        if self.layout == "flat-files":
            if self.member_suffix is None or self.expected_member_name is not None:
                raise ValueError("flat archive projection requires only a member suffix")
        elif self.member_suffix is not None or self.expected_member_name is None:
            raise ValueError("single-file archive projection requires only an exact member name")
        if self.expected_member_name is not None:
            _relative_locator(self.expected_member_name, label="expected member name")
            if len(PurePosixPath(self.expected_member_name).parts) != 1:
                raise ValueError("single-file archive member must be flat")
            if PurePosixPath(self.target_locator).name != self.expected_member_name:
                raise ValueError("single-file target basename differs from its archive member")
        return self


class DatasetMaterializationRequest(BaseModel):
    """Review-only mapping from an acquired task package to isolated data trees."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    project_id: str
    source_task_id: str
    runtime_task_id: str
    authorization_scope: Literal["review-only-no-extraction-no-model-no-execution"] = (
        "review-only-no-extraction-no-model-no-execution"
    )
    purpose: str = Field(min_length=1, max_length=2_000)
    claim_boundary: str = Field(min_length=1, max_length=2_000)
    acquisition_receipt: RuntimeEvidenceBinding
    archive_qualification: RuntimeEvidenceBinding
    license_evidence: RuntimeEvidenceBinding
    task_runtime_spec: RuntimeEvidenceBinding
    destination_root: str
    assets: tuple[DatasetArchiveProjection, ...] = Field(min_length=2, max_length=100)
    expected_archive_bytes: int = Field(gt=0, le=500 * 1024**3)
    expected_expanded_bytes: int = Field(gt=0, le=1024 * 1024**3)
    maximum_materialized_bytes: int = Field(gt=0, le=1024 * 1024**3)
    minimum_free_storage_bytes: int = Field(gt=0, le=2 * 1024**4)
    owner_approval_required: Literal[True] = True
    owner_approved: Literal[False] = False
    authorizes_extraction: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_environment_installation: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("request_id", "source_task_id", "runtime_task_id")
    @classmethod
    def ids_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "id")))

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("destination_root")
    @classmethod
    def destination_is_safe(cls, value: str) -> str:
        return _relative_locator(value, label="dataset materialization destination")

    @model_validator(mode="after")
    def request_is_bounded_and_non_overlapping(self) -> DatasetMaterializationRequest:
        expected_suffix = f"/evaluations/materializations/{self.request_id}"
        if not self.destination_root.endswith(expected_suffix):
            raise ValueError("materialization destination must be project-owned and request-named")
        ids = [item.asset_id for item in self.assets]
        sources = [item.archive_destination for item in self.assets]
        targets = [(item.split_role, item.target_locator) for item in self.assets]
        if len(ids) != len(set(ids)) or len(sources) != len(set(sources)):
            raise ValueError("materialization assets and source archives must be unique")
        if len(targets) != len(set(targets)):
            raise ValueError("materialization view targets must be unique")
        if {item.split_role for item in self.assets} != {"development", "heldout"}:
            raise ValueError("materialization request requires development and held-out assets")
        for index, (left_role, left) in enumerate(targets):
            for right_role, right in targets[index + 1 :]:
                if left_role == right_role and (
                    _is_at_or_under(left, right) or _is_at_or_under(right, left)
                ):
                    raise ValueError("materialization targets cannot overlap within one view")
        if self.expected_archive_bytes != sum(item.archive_bytes for item in self.assets):
            raise ValueError("materialization archive-byte total differs from its assets")
        if self.expected_expanded_bytes != sum(
            item.expected_expanded_bytes for item in self.assets
        ):
            raise ValueError("materialization expanded-byte total differs from its assets")
        if self.maximum_materialized_bytes < self.expected_expanded_bytes:
            raise ValueError("materialization byte ceiling is below expected expanded bytes")
        if self.minimum_free_storage_bytes < self.maximum_materialized_bytes:
            raise ValueError("materialization free-space floor is below its byte ceiling")
        return self

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"proposal_sha256"}))


class DatasetMaterializationRequestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    request: DatasetMaterializationRequest


class DatasetMaterializationFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:.-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=2_000)
    asset_id: str | None = None


class DatasetMaterializationGateReport(BaseModel):
    """No-write inspection of the exact extraction and split-isolation proposal."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    source_task_id: str
    runtime_task_id: str
    acquisition_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    archive_qualification_sha256: str | None = Field(default=None, pattern=_SHA256)
    task_spec_fingerprint: str | None = Field(default=None, pattern=_SHA256)
    selected_asset_ids: tuple[str, ...]
    development_asset_count: int = Field(ge=0)
    heldout_asset_count: int = Field(ge=0)
    development_expanded_bytes: int = Field(ge=0)
    heldout_expanded_bytes: int = Field(ge=0)
    split_isolation_verified: bool
    ingestion_license_verified: bool
    archive_safety_verified: bool
    ready_for_owner_approval: bool
    blockers: tuple[DatasetMaterializationFinding, ...]
    extraction_performed: Literal[False] = False
    environment_installed: Literal[False] = False
    model_or_benchmark_executed: Literal[False] = False

    @computed_field
    @property
    def report_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


class DatasetMaterializationApproval(BaseModel):
    """Owner authority for local extraction only; experiment authority remains absent."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    gate_report_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["local-safe-extraction-and-split-materialization-only-no-model-no-execution"] = (
        "local-safe-extraction-and-split-materialization-only-no-model-no-execution"
    )
    source_task_id: str
    runtime_task_id: str
    destination_root: str
    selected_asset_ids: tuple[str, ...] = Field(min_length=2, max_length=100)
    expected_archive_bytes: int = Field(gt=0)
    expected_expanded_bytes: int = Field(gt=0)
    maximum_materialized_bytes: int = Field(gt=0)
    authorizes_extraction: Literal[True] = True
    authorizes_ingestion: Literal[True] = True
    authorizes_environment_installation: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def approval_is_closed(self) -> DatasetMaterializationApproval:
        if self.approved_at.utcoffset() is None:
            raise ValueError("dataset materialization approval time must include a timezone")
        if len(self.selected_asset_ids) != len(set(self.selected_asset_ids)):
            raise ValueError("dataset materialization approved asset IDs must be unique")
        _relative_locator(self.destination_root, label="approved materialization destination")
        return self

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class DatasetMaterializationApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: DatasetMaterializationApproval


class MaterializedDatasetView(BaseModel):
    model_config = _CONFIG

    split_role: Literal["development", "heldout"]
    data_locator: str
    content_sha256: str = Field(pattern=_SHA256)
    file_count: int = Field(gt=0)
    total_bytes: int = Field(gt=0)


class MaterializedDatasetArchive(BaseModel):
    model_config = _CONFIG

    asset_id: str
    split_role: Literal["development", "heldout"]
    archive_sha256: str = Field(pattern=_SHA256)
    target_locator: str
    member_count: int = Field(gt=0)
    expanded_bytes: int = Field(gt=0)
    target_content_sha256: str = Field(pattern=_SHA256)


class DatasetMaterializationReceipt(BaseModel):
    """Content identities for an atomic development/held-out data publication."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    gate_report_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    acquisition_receipt_sha256: str = Field(pattern=_SHA256)
    archive_qualification_sha256: str = Field(pattern=_SHA256)
    task_spec_fingerprint: str = Field(pattern=_SHA256)
    approved_by: str
    approved_at: datetime
    materialized_at: datetime
    destination_root: str
    archives: tuple[MaterializedDatasetArchive, ...] = Field(min_length=2, max_length=100)
    views: tuple[MaterializedDatasetView, MaterializedDatasetView]
    archive_bytes_reverified: int = Field(gt=0)
    materialized_bytes: int = Field(gt=0)
    split_isolation_verified: Literal[True] = True
    source_archives_unchanged: Literal[True] = True
    environment_installed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    benchmark_executed: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed_and_self_hashed(self) -> DatasetMaterializationReceipt:
        if self.approved_at.utcoffset() is None or self.materialized_at.utcoffset() is None:
            raise ValueError("dataset materialization times must include a timezone")
        if self.materialized_at < self.approved_at:
            raise ValueError("dataset materialization cannot precede approval")
        if {item.split_role for item in self.views} != {"development", "heldout"}:
            raise ValueError("dataset materialization receipt requires both isolated views")
        if self.materialized_bytes != sum(item.total_bytes for item in self.views):
            raise ValueError("materialization receipt byte total differs from its views")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("dataset materialization receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DatasetMaterializationReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


def load_dataset_materialization_request(
    path: str | Path,
) -> DatasetMaterializationRequestInspection:
    source, raw, payload = _load_mapping(path, "dataset materialization request", yaml_input=True)
    return DatasetMaterializationRequestInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        request=DatasetMaterializationRequest.model_validate(payload),
    )


def inspect_dataset_materialization_request(
    inspection: DatasetMaterializationRequestInspection,
    *,
    workspace_root: str | Path,
) -> DatasetMaterializationGateReport:
    """Verify the complete archive-to-split mapping without writing task data."""

    root = Path(workspace_root).resolve(strict=True)
    request = inspection.request
    blockers: list[DatasetMaterializationFinding] = []
    receipt: DatasetPackageAcquisitionReceipt | None = None
    qualification: DatasetArchiveQualificationReport | None = None
    spec: BenchmarkTaskRuntimeSpec | None = None

    receipt_path = _bound_path(root, request.acquisition_receipt, "acquisition-receipt", blockers)
    if receipt_path is not None:
        try:
            receipt = load_dataset_package_receipt(receipt_path).receipt
        except (OSError, ValueError) as exc:
            _add(blockers, "acquisition-receipt:invalid", str(exc))
    qualification_path = _bound_path(
        root, request.archive_qualification, "archive-qualification", blockers
    )
    if qualification_path is not None:
        try:
            qualification = load_dataset_archive_qualification_report(qualification_path)
        except (OSError, ValueError) as exc:
            _add(blockers, "archive-qualification:invalid", str(exc))
    spec_path = _bound_path(root, request.task_runtime_spec, "task-spec", blockers)
    if spec_path is not None:
        try:
            spec = load_benchmark_task_runtime_spec(spec_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            _add(blockers, "task-spec:invalid", str(exc))
    license_path = _bound_path(root, request.license_evidence, "license-evidence", blockers)

    license_verified = False
    if license_path is not None:
        try:
            payload = json.loads(license_path.read_bytes())
            qualifications = payload["task_qualifications"]
            match = next(
                item for item in qualifications if item["task_id"] == request.source_task_id
            )
            license_verified = match["ingestion_license_ready"] is True
        except (KeyError, StopIteration, TypeError, json.JSONDecodeError, UnicodeError) as exc:
            _add(blockers, "license-evidence:invalid-task-disposition", str(exc))
        if not license_verified:
            _add(
                blockers,
                "license-evidence:ingestion-not-ready",
                "the selected task is not licensed for local ingestion",
            )

    receipt_by_id = {}
    if receipt is not None:
        receipt_by_id = {
            item.asset_id: item for item in receipt.assets if item.task_id == request.source_task_id
        }
        selected = {item.asset_id for item in request.assets}
        if selected != set(receipt_by_id):
            _add(
                blockers,
                "acquisition-receipt:task-asset-set-mismatch",
                "the proposal must map every and only acquired asset for the selected task",
            )
        for projection in request.assets:
            acquired = receipt_by_id.get(projection.asset_id)
            if acquired is None:
                continue
            if (
                acquired.destination != projection.archive_destination
                or acquired.sha256 != projection.archive_sha256
                or acquired.size_bytes != projection.archive_bytes
            ):
                _add(
                    blockers,
                    "acquisition-receipt:asset-identity-mismatch",
                    projection.asset_id,
                    projection.asset_id,
                )

    archive_safe = False
    if qualification is not None:
        archive_safe = qualification.archive_safety_qualified
        if receipt is not None and qualification.receipt_sha256 != receipt.receipt_sha256:
            _add(
                blockers,
                "archive-qualification:receipt-mismatch",
                "archive qualification belongs to another acquisition receipt",
            )
        qualified_by_id = {item.asset_id: item for item in qualification.assets}
        for projection in request.assets:
            qualified = qualified_by_id.get(projection.asset_id)
            if qualified is None or not qualified.safe:
                _add(
                    blockers,
                    "archive-qualification:asset-not-safe",
                    projection.asset_id,
                    projection.asset_id,
                )
                continue
            if (
                qualified.destination != projection.archive_destination
                or qualified.archive_bytes != projection.archive_bytes
                or qualified.member_count != projection.expected_member_count
                or qualified.expanded_bytes != projection.expected_expanded_bytes
            ):
                _add(
                    blockers,
                    "archive-qualification:asset-mapping-mismatch",
                    projection.asset_id,
                    projection.asset_id,
                )
        if not archive_safe:
            _add(
                blockers,
                "archive-qualification:not-safe",
                "the bound archive package is not safety-qualified",
            )

    split_isolated = False
    if spec is not None:
        if (
            spec.project_id != request.project_id
            or spec.task_id != request.runtime_task_id
            or spec.license_status is not ReadinessStatus.VERIFIED
            or len(spec.dataset_directories) != 1
        ):
            _add(
                blockers,
                "task-spec:identity-or-license-mismatch",
                "runtime task identity, license, or single dataset root differs",
            )
        else:
            dataset_root = spec.dataset_directories[0]
            declared_hidden = set(spec.heldout_materialization_paths)
            mapped_hidden = {
                f"{dataset_root}/{item.target_locator}"
                for item in request.assets
                if item.split_role == "heldout"
            }
            mapped_development = {
                f"{dataset_root}/{item.target_locator}"
                for item in request.assets
                if item.split_role == "development"
            }
            split_isolated = mapped_hidden == declared_hidden and not any(
                _is_at_or_under(development, hidden) or _is_at_or_under(hidden, development)
                for development in mapped_development
                for hidden in declared_hidden
            )
            if not split_isolated:
                _add(
                    blockers,
                    "task-spec:heldout-projection-mismatch",
                    "held-out targets must exactly match the task spec and be absent "
                    "from development",
                )

    destination = root.joinpath(*PurePosixPath(request.destination_root).parts)
    if not destination.resolve(strict=False).is_relative_to(root):
        _add(blockers, "destination:outside-workspace", request.destination_root)
    if destination.exists() or destination.is_symlink():
        _add(blockers, "destination:already-exists", request.destination_root)

    development = tuple(item for item in request.assets if item.split_role == "development")
    heldout = tuple(item for item in request.assets if item.split_role == "heldout")
    return DatasetMaterializationGateReport(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        request_file_sha256=inspection.file_sha256,
        source_task_id=request.source_task_id,
        runtime_task_id=request.runtime_task_id,
        acquisition_receipt_sha256=receipt.receipt_sha256 if receipt else None,
        archive_qualification_sha256=(qualification.report_sha256 if qualification else None),
        task_spec_fingerprint=spec.fingerprint if spec else None,
        selected_asset_ids=tuple(item.asset_id for item in request.assets),
        development_asset_count=len(development),
        heldout_asset_count=len(heldout),
        development_expanded_bytes=sum(item.expected_expanded_bytes for item in development),
        heldout_expanded_bytes=sum(item.expected_expanded_bytes for item in heldout),
        split_isolation_verified=split_isolated,
        ingestion_license_verified=license_verified,
        archive_safety_verified=archive_safe,
        ready_for_owner_approval=not blockers,
        blockers=tuple(blockers),
    )


def approve_dataset_materialization(
    inspection: DatasetMaterializationRequestInspection,
    gate_report: DatasetMaterializationGateReport,
    *,
    confirmed_proposal_sha256: str,
    confirmed_gate_report_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> DatasetMaterializationApproval:
    """Create narrow extraction authority for one exact, ready mapping."""

    request = inspection.request
    if not gate_report.ready_for_owner_approval or gate_report.blockers:
        raise ValueError("dataset materialization proposal is not owner-approval-ready")
    if (
        confirmed_proposal_sha256 != request.proposal_sha256
        or confirmed_gate_report_sha256 != gate_report.report_sha256
    ):
        raise ValueError("confirmed dataset materialization hashes do not match")
    _validate_gate_binding(inspection, gate_report)
    return DatasetMaterializationApproval(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        request_file_sha256=inspection.file_sha256,
        gate_report_sha256=gate_report.report_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        source_task_id=request.source_task_id,
        runtime_task_id=request.runtime_task_id,
        destination_root=request.destination_root,
        selected_asset_ids=gate_report.selected_asset_ids,
        expected_archive_bytes=request.expected_archive_bytes,
        expected_expanded_bytes=request.expected_expanded_bytes,
        maximum_materialized_bytes=request.maximum_materialized_bytes,
    )


def save_dataset_materialization_gate_report(
    report: DatasetMaterializationGateReport,
    path: str | Path,
) -> Path:
    return _atomic_json(path, report.model_dump(mode="json"), require_absent=False)


def save_dataset_materialization_approval(
    approval: DatasetMaterializationApproval,
    path: str | Path,
) -> Path:
    return _atomic_json(path, approval.model_dump(mode="json"), require_absent=True)


def load_dataset_materialization_approval(
    path: str | Path,
) -> DatasetMaterializationApprovalInspection:
    source, raw, payload = _load_mapping(path, "dataset materialization approval")
    recorded = payload.pop("approval_sha256", None)
    approval = DatasetMaterializationApproval.model_validate(payload)
    if recorded != approval.approval_sha256:
        raise ValueError("dataset materialization approval hash mismatch")
    return DatasetMaterializationApprovalInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def materialize_dataset_views(
    inspection: DatasetMaterializationRequestInspection,
    gate_report: DatasetMaterializationGateReport,
    approval: DatasetMaterializationApproval,
    *,
    workspace_root: str | Path,
    allow_local_extraction: bool = False,
    materialized_at: datetime,
) -> DatasetMaterializationReceipt:
    """Extract and publish isolated task data views as one local transaction."""

    if not allow_local_extraction:
        raise ValueError("dataset materialization requires --allow-local-extraction")
    _validate_gate_binding(inspection, gate_report)
    _validate_approval_binding(inspection, gate_report, approval)
    request = inspection.request
    if materialized_at.utcoffset() is None:
        raise ValueError("dataset materialization time must include a timezone")
    if materialized_at < approval.approved_at:
        raise ValueError("dataset materialization cannot precede approval")

    root = Path(workspace_root).resolve(strict=True)
    receipt_path = _require_bound_path(root, request.acquisition_receipt)
    qualification_path = _require_bound_path(root, request.archive_qualification)
    acquired = load_dataset_package_receipt(receipt_path).receipt
    qualification = load_dataset_archive_qualification_report(qualification_path)
    if not qualification.archive_safety_qualified:
        raise ValueError("dataset archives are no longer safety-qualified")
    receipt_by_id = {item.asset_id: item for item in acquired.assets}

    destination = root.joinpath(*PurePosixPath(request.destination_root).parts)
    if not destination.resolve(strict=False).is_relative_to(root):
        raise ValueError("dataset materialization destination escaped the workspace")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < request.minimum_free_storage_bytes:
        raise ValueError("dataset materialization free-space floor is not met")

    raw_root = root.joinpath(*PurePosixPath(acquired.destination_root).parts).resolve(strict=True)
    if not raw_root.is_relative_to(root) or raw_root.is_symlink() or not raw_root.is_dir():
        raise ValueError("dataset materialization source root is unavailable or unsafe")
    staging = Path(tempfile.mkdtemp(prefix=f".{request.request_id}.", dir=destination.parent))
    try:
        for role in ("development", "heldout"):
            (staging / role / "data").mkdir(parents=True)
        archive_results: list[MaterializedDatasetArchive] = []
        archive_bytes = 0
        materialized_bytes = 0
        for projection in request.assets:
            acquired_asset = receipt_by_id[projection.asset_id]
            archive = raw_root.joinpath(*PurePosixPath(acquired_asset.destination).parts).resolve(
                strict=True
            )
            if (
                not archive.is_relative_to(raw_root)
                or archive.is_symlink()
                or not archive.is_file()
            ):
                raise ValueError(f"materialization archive is unsafe: {projection.asset_id}")
            observed_bytes, observed_sha256 = _hash_file(archive)
            if (
                observed_bytes != projection.archive_bytes
                or observed_sha256 != projection.archive_sha256
            ):
                raise ValueError(f"materialization archive drift: {projection.asset_id}")
            archive_bytes += observed_bytes
            view_root = staging / projection.split_role / "data"
            count, expanded = _extract_projection(archive, view_root, projection)
            if (
                count != projection.expected_member_count
                or expanded != projection.expected_expanded_bytes
            ):
                raise ValueError(f"materialized archive size drift: {projection.asset_id}")
            materialized_bytes += expanded
            if materialized_bytes > request.maximum_materialized_bytes:
                raise ValueError("materialized task data exceeded its byte ceiling")
            target = view_root.joinpath(*PurePosixPath(projection.target_locator).parts)
            target_hash, _, _ = _native_dataset_tree_hash(target)
            archive_results.append(
                MaterializedDatasetArchive(
                    asset_id=projection.asset_id,
                    split_role=projection.split_role,
                    archive_sha256=observed_sha256,
                    target_locator=projection.target_locator,
                    member_count=count,
                    expanded_bytes=expanded,
                    target_content_sha256=target_hash,
                )
            )
        if archive_bytes != request.expected_archive_bytes:
            raise ValueError("reverified archive bytes differ from the request")
        if materialized_bytes != request.expected_expanded_bytes:
            raise ValueError("materialized bytes differ from the request")

        views: list[MaterializedDatasetView] = []
        for role in ("development", "heldout"):
            view = staging / role / "data"
            digest, count, total = _native_dataset_tree_hash(view)
            views.append(
                MaterializedDatasetView(
                    split_role=role,
                    data_locator=f"{role}/data",
                    content_sha256=digest,
                    file_count=count,
                    total_bytes=total,
                )
            )
            _make_read_only(view)
        receipt = DatasetMaterializationReceipt.create(
            request_id=request.request_id,
            proposal_sha256=request.proposal_sha256,
            request_file_sha256=inspection.file_sha256,
            gate_report_sha256=gate_report.report_sha256,
            approval_sha256=approval.approval_sha256,
            acquisition_receipt_sha256=acquired.receipt_sha256,
            archive_qualification_sha256=qualification.report_sha256,
            task_spec_fingerprint=gate_report.task_spec_fingerprint,
            approved_by=approval.approved_by,
            approved_at=approval.approved_at,
            materialized_at=materialized_at,
            destination_root=request.destination_root,
            archives=tuple(archive_results),
            views=tuple(views),
            archive_bytes_reverified=archive_bytes,
            materialized_bytes=materialized_bytes,
        )
        _atomic_json(
            staging / "RECEIPT.json",
            receipt.model_dump(mode="json"),
            require_absent=True,
        )
        with _materialization_publish_lock(destination.parent):
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(destination)
            os.rename(staging, destination)
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_dataset_materialization_receipt(path: str | Path) -> DatasetMaterializationReceipt:
    _source, _raw, payload = _load_mapping(path, "dataset materialization receipt")
    return DatasetMaterializationReceipt.model_validate(payload)


def _validate_gate_binding(
    inspection: DatasetMaterializationRequestInspection,
    gate: DatasetMaterializationGateReport,
) -> None:
    request = inspection.request
    expected = {
        "request_id": request.request_id,
        "proposal_sha256": request.proposal_sha256,
        "request_file_sha256": inspection.file_sha256,
        "source_task_id": request.source_task_id,
        "runtime_task_id": request.runtime_task_id,
        "selected_asset_ids": tuple(item.asset_id for item in request.assets),
    }
    observed = gate.model_dump(mode="python")
    for field, value in expected.items():
        if observed[field] != value:
            raise ValueError(f"dataset materialization gate differs at {field}")


def _validate_approval_binding(
    inspection: DatasetMaterializationRequestInspection,
    gate: DatasetMaterializationGateReport,
    approval: DatasetMaterializationApproval,
) -> None:
    request = inspection.request
    if not gate.ready_for_owner_approval or gate.blockers:
        raise ValueError("dataset materialization gate is not ready")
    expected = {
        "request_id": request.request_id,
        "proposal_sha256": request.proposal_sha256,
        "request_file_sha256": inspection.file_sha256,
        "gate_report_sha256": gate.report_sha256,
        "source_task_id": request.source_task_id,
        "runtime_task_id": request.runtime_task_id,
        "destination_root": request.destination_root,
        "selected_asset_ids": gate.selected_asset_ids,
        "expected_archive_bytes": request.expected_archive_bytes,
        "expected_expanded_bytes": request.expected_expanded_bytes,
        "maximum_materialized_bytes": request.maximum_materialized_bytes,
    }
    observed = approval.model_dump(mode="python")
    for field, value in expected.items():
        if observed[field] != value:
            raise ValueError(f"dataset materialization approval differs at {field}")


def _extract_projection(
    archive_path: Path,
    view_root: Path,
    projection: DatasetArchiveProjection,
) -> tuple[int, int]:
    target = view_root.joinpath(*PurePosixPath(projection.target_locator).parts)
    if not target.resolve(strict=False).is_relative_to(view_root):
        raise ValueError("dataset projection target escaped its view")
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    if projection.layout == "flat-files":
        target.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    expanded = 0
    names: set[str] = set()
    with zipfile.ZipFile(archive_path, "r", allowZip64=True) as archive:
        infos = archive.infolist()
        if len(infos) != projection.expected_member_count:
            raise ValueError("dataset archive member count drift")
        for info in infos:
            member = _safe_regular_member(info)
            if member in names:
                raise ValueError("dataset archive contains a duplicate member")
            names.add(member)
            if projection.layout == "flat-files":
                if len(PurePosixPath(member).parts) != 1 or not member.endswith(
                    projection.member_suffix or ""
                ):
                    raise ValueError("dataset feature archive layout differs from its proposal")
                output = target / member
            else:
                if member != projection.expected_member_name:
                    raise ValueError("dataset single-file archive member differs from its proposal")
                output = target
            descriptor = os.open(
                output,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o400,
            )
            written = 0
            try:
                with archive.open(info, "r") as source, os.fdopen(descriptor, "wb") as sink:
                    while chunk := source.read(_CHUNK_BYTES):
                        written += len(chunk)
                        expanded += len(chunk)
                        if (
                            written > info.file_size
                            or expanded > projection.expected_expanded_bytes
                        ):
                            raise ValueError("dataset archive exceeded its expanded-byte authority")
                        sink.write(chunk)
                    sink.flush()
                    os.fsync(sink.fileno())
            except BaseException:
                output.unlink(missing_ok=True)
                raise
            if written != info.file_size:
                raise ValueError("dataset archive member size changed while extracted")
            count += 1
    return count, expanded


def _safe_regular_member(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.is_dir() or name.endswith("/"):
        raise ValueError("dataset projection forbids directory archive members")
    if not name or "\\" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("dataset archive member path is unsafe")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or (path.parts and ":" in path.parts[0])
        or info.flag_bits & 0x1
        or ((info.external_attr >> 16) & 0o170000) == stat.S_IFLNK
    ):
        raise ValueError("dataset archive member path or type is unsafe")
    return path.as_posix()


def _native_dataset_tree_hash(path: Path) -> tuple[str, int, int]:
    source = path.resolve(strict=True)
    files = [source] if source.is_file() else sorted(source.rglob("*"))
    entries: list[dict[str, object]] = []
    total = 0
    for item in files:
        if item.is_symlink():
            raise ValueError("materialized dataset view contains a symlink")
        if item.is_dir():
            continue
        if not item.is_file():
            raise ValueError("materialized dataset view contains a special file")
        relative = item.name if source.is_file() else item.relative_to(source).as_posix()
        size, digest = _hash_file(item)
        total += size
        entries.append({"path": relative, "size": size, "sha256": digest})
    if not entries:
        raise ValueError("materialized dataset view is empty")
    if source.is_file():
        digest = str(entries[0]["sha256"])
    else:
        digest = content_sha256({"schema_version": "1.0", "entries": entries})
    return digest, len(entries), total


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            path.chmod(0o444)
        elif path.is_dir():
            path.chmod(0o555)
    root.chmod(0o555)


def _bound_path(
    root: Path,
    binding: RuntimeEvidenceBinding,
    label: str,
    blockers: list[DatasetMaterializationFinding],
) -> Path | None:
    path = root.joinpath(*PurePosixPath(binding.locator).parts)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        _add(blockers, f"{label}:unavailable", binding.locator)
        return None
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != binding.file_sha256:
        _add(blockers, f"{label}:hash-mismatch", binding.locator)
        return None
    if binding.semantic_sha256 is not None:
        try:
            payload = json.loads(raw)
            observed = payload[binding.semantic_field]
        except (KeyError, TypeError, json.JSONDecodeError, UnicodeError):
            _add(blockers, f"{label}:semantic-invalid", binding.locator)
            return None
        if observed != binding.semantic_sha256:
            _add(blockers, f"{label}:semantic-hash-mismatch", binding.locator)
            return None
    return path.resolve(strict=True)


def _require_bound_path(root: Path, binding: RuntimeEvidenceBinding) -> Path:
    blockers: list[DatasetMaterializationFinding] = []
    path = _bound_path(root, binding, "evidence", blockers)
    if path is None:
        raise ValueError(blockers[0].code)
    return path


def _load_mapping(
    path: str | Path,
    label: str,
    *,
    yaml_input: bool = False,
) -> tuple[Path, bytes, dict[str, object]]:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = source.read_bytes()
    try:
        payload = yaml.safe_load(raw) if yaml_input else json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return source.resolve(strict=True), raw, payload


def _atomic_json(path: str | Path, payload: object, *, require_absent: bool) -> Path:
    target = Path(path)
    if target.is_symlink() or (require_absent and target.exists()):
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        if require_absent:
            os.link(temporary, target)
            temporary.unlink()
        else:
            os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


@contextmanager
def _materialization_publish_lock(parent: Path) -> Iterator[None]:
    """Serialize the final no-overwrite publication for one materialization root."""

    import fcntl

    lock_path = parent / ".dataset-materialization.lock"
    handle: IO[str] = lock_path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _hash_file(path: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _relative_locator(value: str, *, label: str) -> str:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")
    return value


def _is_at_or_under(path: str, root: str) -> bool:
    candidate = PurePosixPath(path)
    base = PurePosixPath(root)
    return candidate == base or base in candidate.parents


def _add(
    findings: list[DatasetMaterializationFinding],
    code: str,
    message: str,
    asset_id: str | None = None,
) -> None:
    finding = DatasetMaterializationFinding(code=code, message=message, asset_id=asset_id)
    if finding not in findings:
        findings.append(finding)


__all__ = [
    "DatasetArchiveProjection",
    "DatasetMaterializationApproval",
    "DatasetMaterializationApprovalInspection",
    "DatasetMaterializationFinding",
    "DatasetMaterializationGateReport",
    "DatasetMaterializationReceipt",
    "DatasetMaterializationRequest",
    "DatasetMaterializationRequestInspection",
    "MaterializedDatasetArchive",
    "MaterializedDatasetView",
    "approve_dataset_materialization",
    "inspect_dataset_materialization_request",
    "load_dataset_materialization_approval",
    "load_dataset_materialization_receipt",
    "load_dataset_materialization_request",
    "materialize_dataset_views",
    "save_dataset_materialization_approval",
    "save_dataset_materialization_gate_report",
]
