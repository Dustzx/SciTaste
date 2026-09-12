"""Complete-population projection before benchmark task screening."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, TypeAlias
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.acquisition import (
    AcquisitionReceiptInspection,
    AcquisitionRequestInspection,
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.structured_metadata_audit import (
    StructuredMetadataAuditItemReport,
    StructuredMetadataAuditReport,
    StructuredMetadataFormat,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 4 * 1_048_576
_SCALAR_TYPES = frozenset({"null", "boolean", "integer", "number", "string"})

JsonScalar: TypeAlias = str | int | float | bool | None


class BenchmarkMetadataScope(BaseModel):
    """Frozen scientific scope that predates inspection of acquired metadata."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    scope_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    scientific_role: Literal[
        "objective-progress-task-universe-screen",
        "experiment-chain-diagnostic-task-universe-screen",
    ]
    benchmark_resource_id: str = Field(pattern=_ID)
    repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_id: str = Field(pattern=_ID)
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    reported_population: dict[str, int] | None = None
    selection_state: Literal["metadata-acquisition-proposed-subset-not-selected"]
    selection_rule: str = Field(min_length=1, max_length=4_000)
    task_config_paths: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=500)
    metadata_file: str | None = Field(default=None, min_length=1, max_length=1_000)
    required_screen_fields: tuple[str, ...] = Field(min_length=1, max_length=50)
    exclusion_codes: tuple[str, ...] = Field(min_length=1, max_length=50)
    forbidden_shortcuts: tuple[str, ...] = Field(min_length=1, max_length=50)
    authorizes_dataset_archive_download: Literal[False] = False
    authorizes_runtime_asset_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def scope_is_complete_and_preselection(self) -> BenchmarkMetadataScope:
        if (self.task_config_paths is None) == (self.metadata_file is None):
            raise ValueError("benchmark metadata scope requires exactly one source layout")
        for label, values in (
            ("required screen fields", self.required_screen_fields),
            ("exclusion codes", self.exclusion_codes),
            ("forbidden shortcuts", self.forbidden_shortcuts),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"benchmark metadata {label} must be unique")
        if self.task_config_paths is not None:
            if len(self.task_config_paths) != len(set(self.task_config_paths)):
                raise ValueError("benchmark task configuration paths must be unique")
            for locator in self.task_config_paths:
                _validate_relative_path(locator, "benchmark task configuration")
        if self.metadata_file is not None:
            _validate_relative_path(self.metadata_file, "benchmark metadata file")
        if self.reported_population is not None and any(
            not key or value <= 0 for key, value in self.reported_population.items()
        ):
            raise ValueError("reported benchmark population values must be positive")
        return self


class BenchmarkMetadataScopeInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    scope: BenchmarkMetadataScope


class StructuredMetadataAuditReportInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: StructuredMetadataAuditReport


class MetadataFieldBinding(BaseModel):
    """One scientific screen field bound only to structurally observed source fields."""

    model_config = _CONFIG

    semantic_field: str = Field(pattern=_ID)
    availability: Literal[
        "observed-source-field",
        "absent-from-audited-source",
    ] = "observed-source-field"
    source_fields: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def source_fields_match_availability(self) -> MetadataFieldBinding:
        if len(self.source_fields) != len(set(self.source_fields)):
            raise ValueError("metadata projection source fields must be unique")
        if self.source_fields != tuple(sorted(self.source_fields)):
            raise ValueError("metadata projection source fields must be sorted")
        if self.availability == "observed-source-field" and not self.source_fields:
            raise ValueError("observed metadata projection fields require source fields")
        if self.availability == "absent-from-audited-source" and self.source_fields:
            raise ValueError("absent metadata projection fields cannot name source fields")
        return self


class BenchmarkMetadataProjectionPlan(BaseModel):
    """Exact no-read plan for projecting a complete audited metadata population."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    scope_locator: str = Field(min_length=1, max_length=1_000)
    scope_file_sha256: str = Field(pattern=_SHA256)
    request_id: str = Field(pattern=_ID)
    request_locator: str = Field(min_length=1, max_length=1_000)
    request_file_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_locator: str = Field(min_length=1, max_length=1_000)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    audit_report_locator: str = Field(min_length=1, max_length=1_000)
    audit_report_file_sha256: str = Field(pattern=_SHA256)
    audit_report_sha256: str = Field(pattern=_SHA256)
    audit_plan_sha256: str = Field(pattern=_SHA256)
    projection_implementation_sha256: str = Field(pattern=_SHA256)
    media_type: StructuredMetadataFormat
    record_unit: Literal["one-record-per-acquired-item", "one-record-per-csv-row"]
    expected_source_bytes: int = Field(gt=0, le=64 * 1_048_576)
    expected_record_count: int = Field(gt=0, le=5_000_000)
    required_screen_fields: tuple[str, ...] = Field(min_length=1, max_length=50)
    field_bindings: tuple[MetadataFieldBinding, ...] = Field(min_length=1, max_length=50)
    projection_output_root: str = Field(min_length=1, max_length=1_000)
    maximum_projected_value_bytes: int = Field(gt=0, le=1_048_576)
    maximum_projection_bytes: int = Field(gt=0, le=64 * 1_048_576)
    complete_population_required: Literal[True] = True
    selection_performed: Literal[False] = False
    formal_outcomes_consulted: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    ready_for_owner_approval: Literal[True] = True
    source_content_read: Literal[False] = False
    authorizes_local_content_read: Literal[False] = False
    authorizes_network_access: Literal[False] = False
    authorizes_link_resolution: Literal[False] = False
    authorizes_task_selection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def bindings_cover_scope_exactly(self) -> BenchmarkMetadataProjectionPlan:
        semantic_fields = tuple(item.semantic_field for item in self.field_bindings)
        if len(semantic_fields) != len(set(semantic_fields)):
            raise ValueError("metadata projection semantic fields must be unique")
        if set(semantic_fields) != set(self.required_screen_fields):
            raise ValueError("metadata projection must bind every required screen field exactly")
        if tuple(sorted(self.required_screen_fields)) != self.required_screen_fields:
            raise ValueError("required metadata projection fields must be sorted")
        if tuple(sorted(semantic_fields)) != semantic_fields:
            raise ValueError("metadata projection bindings must be sorted")
        for locator in (
            self.scope_locator,
            self.request_locator,
            self.receipt_locator,
            self.audit_report_locator,
            self.projection_output_root,
        ):
            _validate_relative_path(locator, "metadata projection locator")
        if self.media_type is StructuredMetadataFormat.YAML:
            if self.record_unit != "one-record-per-acquired-item":
                raise ValueError("YAML metadata projection requires one record per item")
            if any(
                not source.startswith("/")
                for binding in self.field_bindings
                if binding.availability == "observed-source-field"
                for source in binding.source_fields
            ):
                raise ValueError("YAML metadata projection fields must be structural paths")
        elif self.record_unit != "one-record-per-csv-row":
            raise ValueError("CSV metadata projection requires one record per row")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class BenchmarkMetadataProjectionPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: BenchmarkMetadataProjectionPlan


class BenchmarkMetadataProjectionApproval(BaseModel):
    """Owner authority for one complete-population, field-limited projection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(pattern=_ID)
    plan_id: str = Field(pattern=_ID)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["complete-population-bounded-field-projection-only"]
    authorizes_local_content_read: Literal[True] = True
    authorizes_complete_population_projection: Literal[True] = True
    authorizes_network_access: Literal[False] = False
    authorizes_link_resolution: Literal[False] = False
    authorizes_task_selection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_review: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("metadata projection approval timestamp must include a timezone")
        return value

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class BenchmarkMetadataProjectionApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: BenchmarkMetadataProjectionApproval


class ProjectedMetadataField(BaseModel):
    model_config = _CONFIG

    semantic_field: str = Field(pattern=_ID)
    availability: Literal[
        "observed-source-field",
        "absent-from-audited-source",
    ]
    source_fields: tuple[str, ...] = Field(default=(), max_length=16)
    source_field_present: bool
    values: tuple[JsonScalar, ...] = Field(default=(), max_length=10_000)

    @model_validator(mode="after")
    def values_match_source_presence(self) -> ProjectedMetadataField:
        if self.source_field_present != bool(self.values):
            raise ValueError("projected metadata source presence differs from its values")
        if self.availability == "observed-source-field" and not self.source_fields:
            raise ValueError("observed projected metadata requires source fields")
        if self.availability == "absent-from-audited-source" and (
            self.source_fields or self.source_field_present
        ):
            raise ValueError("absent projected metadata cannot contain source values")
        return self


class ProjectedBenchmarkMetadataRecord(BaseModel):
    model_config = _CONFIG

    record_id: str = Field(pattern=_ID)
    source_item_id: str = Field(pattern=_ID)
    source_sha256: str = Field(pattern=_SHA256)
    row_ordinal: int | None = Field(default=None, gt=0)
    fields: tuple[ProjectedMetadataField, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def fields_are_sorted_and_unique(self) -> ProjectedBenchmarkMetadataRecord:
        names = tuple(item.semantic_field for item in self.fields)
        if names != tuple(sorted(set(names))):
            raise ValueError("projected metadata record fields must be sorted and unique")
        return self


class BenchmarkMetadataPopulation(BaseModel):
    """Complete, field-limited population; no task has yet been selected."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(pattern=_ID)
    scope_id: str = Field(pattern=_ID)
    plan_id: str = Field(pattern=_ID)
    plan_locator: str = Field(min_length=1, max_length=1_000)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approval_id: str = Field(pattern=_ID)
    approval_locator: str = Field(min_length=1, max_length=1_000)
    approval_file_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    audit_report_sha256: str = Field(pattern=_SHA256)
    request_id: str = Field(pattern=_ID)
    receipt_sha256: str = Field(pattern=_SHA256)
    projected_at: datetime
    media_type: StructuredMetadataFormat
    record_unit: Literal["one-record-per-acquired-item", "one-record-per-csv-row"]
    record_count: int = Field(gt=0, le=5_000_000)
    required_screen_fields: tuple[str, ...] = Field(min_length=1, max_length=50)
    records: tuple[ProjectedBenchmarkMetadataRecord, ...] = Field(min_length=1)
    missing_source_field_observation_count: int = Field(ge=0)
    complete_population_projected: Literal[True] = True
    ready_for_screen_decision_proposal: Literal[True] = True
    selection_performed: Literal[False] = False
    formal_outcomes_consulted: Literal[False] = False
    model_inventory_consulted: Literal[False] = False
    compute_inventory_consulted: Literal[False] = False
    source_content_read: Literal[True] = True
    source_files_modified: Literal[False] = False
    network_access_performed: Literal[False] = False
    linked_assets_resolved: Literal[False] = False
    ingestion_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_task_selection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("projected_at")
    @classmethod
    def projection_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("metadata projection timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def population_is_complete_and_consistent(self) -> BenchmarkMetadataPopulation:
        _validate_relative_path(self.plan_locator, "metadata projection plan")
        _validate_relative_path(self.approval_locator, "metadata projection approval")
        if self.record_count != len(self.records):
            raise ValueError("projected metadata population count differs")
        record_ids = tuple(item.record_id for item in self.records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("projected metadata record IDs must be unique")
        expected_fields = set(self.required_screen_fields)
        if any(
            {field.semantic_field for field in record.fields} != expected_fields
            for record in self.records
        ):
            raise ValueError("projected metadata record does not cover required fields")
        observed_missing = sum(
            not field.source_field_present for record in self.records for field in record.fields
        )
        if self.missing_source_field_observation_count != observed_missing:
            raise ValueError("projected metadata missing-field count differs")
        return self

    @computed_field
    @property
    def population_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"population_sha256"}))


class BenchmarkMetadataPopulationInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    population: BenchmarkMetadataPopulation


class BenchmarkMetadataPopulationChainInspection(BaseModel):
    """No-source-read replay of a projected population's complete control chain."""

    model_config = _CONFIG

    population: BenchmarkMetadataPopulationInspection
    plan: BenchmarkMetadataProjectionPlanInspection
    approval: BenchmarkMetadataProjectionApprovalInspection
    audit: StructuredMetadataAuditReportInspection
    projection_implementation_current: bool


def load_benchmark_metadata_scope(path: str | Path) -> BenchmarkMetadataScopeInspection:
    resolved, raw = _read_bounded_file(path, "benchmark metadata scope")
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("benchmark metadata scope must be valid UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("benchmark metadata scope must contain a YAML mapping")
    return BenchmarkMetadataScopeInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        scope=BenchmarkMetadataScope.model_validate(payload),
    )


def load_structured_metadata_audit_report(
    path: str | Path,
) -> StructuredMetadataAuditReportInspection:
    resolved, raw, payload = _load_json_mapping(path, "structured metadata audit report")
    recorded = payload.pop("report_sha256", None)
    report = StructuredMetadataAuditReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("structured metadata audit report hash mismatch")
    return StructuredMetadataAuditReportInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=report,
    )


def plan_benchmark_metadata_projection(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    audit_report: StructuredMetadataAuditReportInspection,
    scope: BenchmarkMetadataScopeInspection,
    *,
    workspace_root: str | Path,
    field_bindings: tuple[MetadataFieldBinding, ...],
    projection_output_root: str,
    maximum_projected_value_bytes: int = 65_536,
    maximum_projection_bytes: int = 32 * 1_048_576,
) -> BenchmarkMetadataProjectionPlan:
    """Plan a complete field projection without reopening acquired source bytes."""

    root = Path(workspace_root).resolve(strict=True)
    source_request = request.request
    source_receipt = receipt.receipt
    report = audit_report.report
    frozen_scope = scope.scope
    _verify_control_chain(source_request, source_receipt, report)
    if not report.ready_for_metadata_screen_proposal:
        raise ValueError("structured metadata audit is not ready for projection planning")
    if frozen_scope.project_id != source_request.project_id:
        raise ValueError("benchmark metadata scope belongs to another project")
    if frozen_scope.scope_id != source_request.selection_id:
        raise ValueError("benchmark metadata scope differs from acquisition selection")
    scope_binding = next(
        (
            item
            for item in source_request.evidence
            if item.sha256 == scope.file_sha256
            and _resolve_beneath(root, item.path) == scope.path.resolve(strict=True)
        ),
        None,
    )
    if scope_binding is None or source_request.selection_proposal_sha256 != scope.file_sha256:
        raise ValueError("benchmark metadata scope is not the acquisition's exact selection basis")
    _verify_scope_source_population(source_request, frozen_scope)
    media_types = {StructuredMetadataFormat(item.media_type) for item in source_request.items}
    if len(media_types) != 1:
        raise ValueError("one benchmark metadata projection cannot mix source formats")
    media_type = next(iter(media_types))
    if media_type is StructuredMetadataFormat.YAML:
        if frozen_scope.task_config_paths is None:
            raise ValueError("YAML benchmark scope lacks its complete task-file population")
        expected_record_count = report.item_count
        if expected_record_count != len(frozen_scope.task_config_paths):
            raise ValueError("YAML audit population differs from frozen scope")
        _validate_yaml_bindings(report.items, field_bindings)
        record_unit = "one-record-per-acquired-item"
    else:
        if frozen_scope.metadata_file is None:
            raise ValueError("CSV benchmark scope lacks its metadata table identity")
        expected_record_count = sum(item.csv_data_rows for item in report.items)
        reported = (frozen_scope.reported_population or {}).get("task_count")
        if reported is not None and expected_record_count != reported:
            raise ValueError("CSV audit row population differs from frozen scope")
        _validate_csv_bindings(report.items, field_bindings)
        record_unit = "one-record-per-csv-row"
    required = tuple(sorted(frozen_scope.required_screen_fields))
    normalized_bindings = tuple(sorted(field_bindings, key=lambda item: item.semantic_field))
    if {item.semantic_field for item in normalized_bindings} != set(required):
        raise ValueError("field bindings do not cover the frozen metadata-screen scope")
    return BenchmarkMetadataProjectionPlan(
        plan_id=f"{frozen_scope.scope_id}-complete-projection-v1",
        project_id=source_request.project_id,
        scope_id=frozen_scope.scope_id,
        scope_locator=_relative_locator(root, scope.path, "benchmark metadata scope"),
        scope_file_sha256=scope.file_sha256,
        request_id=source_request.request_id,
        request_locator=_relative_locator(root, request.path, "approved acquisition request"),
        request_file_sha256=request.file_sha256,
        request_sha256=source_request.request_sha256,
        receipt_locator=_relative_locator(root, receipt.path, "acquisition receipt"),
        receipt_file_sha256=receipt.file_sha256,
        receipt_sha256=source_receipt.receipt_sha256,
        audit_report_locator=_relative_locator(root, audit_report.path, "metadata audit report"),
        audit_report_file_sha256=audit_report.file_sha256,
        audit_report_sha256=report.report_sha256,
        audit_plan_sha256=report.plan_sha256,
        projection_implementation_sha256=_module_sha256(),
        media_type=media_type,
        record_unit=record_unit,
        expected_source_bytes=report.observed_total_bytes,
        expected_record_count=expected_record_count,
        required_screen_fields=required,
        field_bindings=normalized_bindings,
        projection_output_root=projection_output_root,
        maximum_projected_value_bytes=maximum_projected_value_bytes,
        maximum_projection_bytes=maximum_projection_bytes,
    )


def approve_benchmark_metadata_projection(
    plan: BenchmarkMetadataProjectionPlanInspection,
    *,
    confirmed_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> BenchmarkMetadataProjectionApproval:
    """Authorize only the exact complete-population projection in a current plan."""

    if plan.plan.projection_implementation_sha256 != _module_sha256():
        raise ValueError("benchmark metadata projection implementation has changed")
    if confirmed_plan_sha256 != plan.plan.plan_sha256:
        raise ValueError("confirmed benchmark metadata projection plan hash differs")
    return BenchmarkMetadataProjectionApproval(
        approval_id=f"{plan.plan.plan_id}-approval",
        plan_id=plan.plan.plan_id,
        plan_file_sha256=plan.file_sha256,
        plan_sha256=plan.plan.plan_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="complete-population-bounded-field-projection-only",
    )


def project_benchmark_metadata_population(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    audit_report: StructuredMetadataAuditReportInspection,
    scope: BenchmarkMetadataScopeInspection,
    plan: BenchmarkMetadataProjectionPlanInspection,
    approval: BenchmarkMetadataProjectionApprovalInspection,
    *,
    workspace_root: str | Path,
    allow_local_content_read: bool,
    projected_at: datetime,
) -> BenchmarkMetadataPopulation:
    """Project every audited record and only approved fields; never select tasks."""

    if not allow_local_content_read:
        raise ValueError("benchmark metadata projection requires --allow-local-content-read")
    expected = plan_benchmark_metadata_projection(
        request,
        receipt,
        audit_report,
        scope,
        workspace_root=workspace_root,
        field_bindings=plan.plan.field_bindings,
        projection_output_root=plan.plan.projection_output_root,
        maximum_projected_value_bytes=plan.plan.maximum_projected_value_bytes,
        maximum_projection_bytes=plan.plan.maximum_projection_bytes,
    )
    if expected != plan.plan:
        raise ValueError("benchmark metadata projection plan bindings have drifted")
    authority = approval.approval
    if (
        authority.plan_id != plan.plan.plan_id
        or authority.plan_file_sha256 != plan.file_sha256
        or authority.plan_sha256 != plan.plan.plan_sha256
    ):
        raise ValueError("benchmark metadata projection approval bindings have drifted")
    if projected_at.utcoffset() is None:
        raise ValueError("benchmark metadata projection timestamp must include a timezone")
    if projected_at < max(audit_report.report.audited_at, authority.approved_at):
        raise ValueError("benchmark metadata projection cannot precede audit or approval")
    root = Path(workspace_root).resolve(strict=True)
    raw_root = _resolve_beneath(root, receipt.receipt.destination_root)
    if raw_root is None or raw_root.is_symlink() or not raw_root.is_dir():
        raise ValueError("benchmark metadata acquisition root is unavailable")
    expected_paths = {item.destination for item in receipt.receipt.items}
    actual_paths = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_paths != expected_paths or any(path.is_symlink() for path in raw_root.rglob("*")):
        raise ValueError("benchmark metadata acquisition inventory has drifted")
    audit_items = {item.item_id: item for item in audit_report.report.items}
    records: list[ProjectedBenchmarkMetadataRecord] = []
    for receipt_item in receipt.receipt.items:
        audit_item = audit_items[receipt_item.item_id]
        source = _resolve_beneath(raw_root, receipt_item.destination)
        if source is None or source.is_symlink() or not source.is_file():
            raise ValueError("benchmark metadata source item is unavailable")
        raw = source.read_bytes()
        observed_sha256 = hashlib.sha256(raw).hexdigest()
        if (
            len(raw) != receipt_item.size_bytes
            or observed_sha256 != receipt_item.sha256
            or len(raw) != audit_item.observed_size_bytes
            or observed_sha256 != audit_item.observed_sha256
        ):
            raise ValueError("benchmark metadata source bytes differ from audit evidence")
        decoded = raw.decode("utf-8")
        if plan.plan.media_type is StructuredMetadataFormat.YAML:
            records.append(
                _project_yaml_record(
                    receipt_item.item_id,
                    observed_sha256,
                    decoded,
                    plan.plan.field_bindings,
                    plan.plan.maximum_projected_value_bytes,
                )
            )
        else:
            records.extend(
                _project_csv_records(
                    receipt_item.item_id,
                    observed_sha256,
                    decoded,
                    plan.plan.field_bindings,
                    plan.plan.maximum_projected_value_bytes,
                )
            )
    if len(records) != plan.plan.expected_record_count:
        raise ValueError("projected benchmark metadata population is incomplete")
    if sum(item.observed_size_bytes for item in audit_items.values()) != (
        plan.plan.expected_source_bytes
    ):
        raise ValueError("projected benchmark metadata source-byte population is incomplete")
    population = BenchmarkMetadataPopulation(
        project_id=plan.plan.project_id,
        scope_id=plan.plan.scope_id,
        plan_id=plan.plan.plan_id,
        plan_locator=_relative_locator(root, plan.path, "benchmark metadata projection plan"),
        plan_file_sha256=plan.file_sha256,
        plan_sha256=plan.plan.plan_sha256,
        approval_id=authority.approval_id,
        approval_locator=_relative_locator(
            root,
            approval.path,
            "benchmark metadata projection approval",
        ),
        approval_file_sha256=approval.file_sha256,
        approval_sha256=authority.approval_sha256,
        audit_report_sha256=audit_report.report.report_sha256,
        request_id=plan.plan.request_id,
        receipt_sha256=plan.plan.receipt_sha256,
        projected_at=projected_at,
        media_type=plan.plan.media_type,
        record_unit=plan.plan.record_unit,
        record_count=len(records),
        required_screen_fields=plan.plan.required_screen_fields,
        records=tuple(records),
        missing_source_field_observation_count=sum(
            not field.source_field_present for record in records for field in record.fields
        ),
    )
    rendered = population.model_dump_json(indent=2) + "\n"
    if len(rendered.encode("utf-8")) > plan.plan.maximum_projection_bytes:
        raise ValueError("projected benchmark metadata population exceeds output ceiling")
    return population


def save_benchmark_metadata_projection_plan(
    plan: BenchmarkMetadataProjectionPlan,
    path: str | Path,
) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def load_benchmark_metadata_projection_plan(
    path: str | Path,
) -> BenchmarkMetadataProjectionPlanInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata projection plan")
    recorded = payload.pop("plan_sha256", None)
    plan = BenchmarkMetadataProjectionPlan.model_validate(payload)
    if recorded != plan.plan_sha256:
        raise ValueError("benchmark metadata projection plan hash mismatch")
    return BenchmarkMetadataProjectionPlanInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        plan=plan,
    )


def save_benchmark_metadata_projection_approval(
    approval: BenchmarkMetadataProjectionApproval,
    path: str | Path,
) -> Path:
    return _write_new_json(path, approval.model_dump_json(indent=2) + "\n")


def load_benchmark_metadata_projection_approval(
    path: str | Path,
) -> BenchmarkMetadataProjectionApprovalInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata projection approval")
    recorded = payload.pop("approval_sha256", None)
    approval = BenchmarkMetadataProjectionApproval.model_validate(payload)
    if recorded != approval.approval_sha256:
        raise ValueError("benchmark metadata projection approval hash mismatch")
    return BenchmarkMetadataProjectionApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def save_benchmark_metadata_population(
    population: BenchmarkMetadataPopulation,
    path: str | Path,
) -> Path:
    return _write_new_json(path, population.model_dump_json(indent=2) + "\n")


def load_benchmark_metadata_population(
    path: str | Path,
) -> BenchmarkMetadataPopulationInspection:
    resolved, raw, payload = _load_json_mapping(path, "benchmark metadata population")
    recorded = payload.pop("population_sha256", None)
    population = BenchmarkMetadataPopulation.model_validate(payload)
    if recorded != population.population_sha256:
        raise ValueError("benchmark metadata population hash mismatch")
    return BenchmarkMetadataPopulationInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        population=population,
    )


def inspect_benchmark_metadata_population_chain(
    path: str | Path,
    *,
    workspace_root: str | Path,
) -> BenchmarkMetadataPopulationChainInspection:
    """Replay control artifacts for one population without reopening source metadata."""

    root = Path(workspace_root).resolve(strict=True)
    population_inspection = load_benchmark_metadata_population(path)
    population = population_inspection.population
    expected_population_path = root.joinpath(
        *PurePosixPath(
            _load_relative_path_from_root(
                root,
                population_inspection.path,
                "benchmark metadata population",
            )
        ).parts
    )
    if expected_population_path != population_inspection.path:
        raise ValueError("benchmark metadata population escaped the workspace")
    plan = load_benchmark_metadata_projection_plan(
        _contained_locator(root, population.plan_locator, "benchmark metadata projection plan")
    )
    approval = load_benchmark_metadata_projection_approval(
        _contained_locator(
            root,
            population.approval_locator,
            "benchmark metadata projection approval",
        )
    )
    if (
        plan.file_sha256 != population.plan_file_sha256
        or plan.plan.plan_id != population.plan_id
        or plan.plan.plan_sha256 != population.plan_sha256
        or approval.file_sha256 != population.approval_file_sha256
        or approval.approval.approval_id != population.approval_id
        or approval.approval.approval_sha256 != population.approval_sha256
        or approval.approval.plan_id != plan.plan.plan_id
        or approval.approval.plan_file_sha256 != plan.file_sha256
        or approval.approval.plan_sha256 != plan.plan.plan_sha256
    ):
        raise ValueError("benchmark metadata population plan or approval binding differs")
    request = load_dataset_acquisition_request(
        _contained_locator(root, plan.plan.request_locator, "approved acquisition request")
    )
    receipt = load_dataset_acquisition_receipt(
        _contained_locator(root, plan.plan.receipt_locator, "acquisition receipt")
    )
    audit = load_structured_metadata_audit_report(
        _contained_locator(root, plan.plan.audit_report_locator, "metadata audit report")
    )
    scope = load_benchmark_metadata_scope(
        _contained_locator(root, plan.plan.scope_locator, "benchmark metadata scope")
    )
    if (
        request.file_sha256 != plan.plan.request_file_sha256
        or request.request.request_sha256 != plan.plan.request_sha256
        or receipt.file_sha256 != plan.plan.receipt_file_sha256
        or receipt.receipt.receipt_sha256 != plan.plan.receipt_sha256
        or audit.file_sha256 != plan.plan.audit_report_file_sha256
        or audit.report.report_sha256 != plan.plan.audit_report_sha256
        or scope.file_sha256 != plan.plan.scope_file_sha256
    ):
        raise ValueError("benchmark metadata population control artifact differs")
    rebuilt = plan_benchmark_metadata_projection(
        request,
        receipt,
        audit,
        scope,
        workspace_root=root,
        field_bindings=plan.plan.field_bindings,
        projection_output_root=plan.plan.projection_output_root,
        maximum_projected_value_bytes=plan.plan.maximum_projected_value_bytes,
        maximum_projection_bytes=plan.plan.maximum_projection_bytes,
    )
    rebuilt_at_recorded_implementation = rebuilt.model_copy(
        update={
            "projection_implementation_sha256": plan.plan.projection_implementation_sha256,
        }
    )
    if rebuilt_at_recorded_implementation != plan.plan:
        raise ValueError("benchmark metadata population plan control chain has drifted")
    expected_output = root.joinpath(
        *PurePosixPath(plan.plan.projection_output_root).parts,
        "POPULATION.json",
    )
    if population_inspection.path != expected_output:
        raise ValueError("benchmark metadata population is outside its planned destination")
    if (
        population.project_id != plan.plan.project_id
        or population.scope_id != plan.plan.scope_id
        or population.request_id != plan.plan.request_id
        or population.receipt_sha256 != plan.plan.receipt_sha256
        or population.audit_report_sha256 != plan.plan.audit_report_sha256
        or population.media_type != plan.plan.media_type
        or population.record_unit != plan.plan.record_unit
        or population.record_count != plan.plan.expected_record_count
        or population.required_screen_fields != plan.plan.required_screen_fields
    ):
        raise ValueError("benchmark metadata population differs from its plan")
    expected_bindings = {item.semantic_field: item for item in plan.plan.field_bindings}
    if any(
        field.availability != expected_bindings[field.semantic_field].availability
        or field.source_fields != expected_bindings[field.semantic_field].source_fields
        for record in population.records
        for field in record.fields
    ):
        raise ValueError("benchmark metadata population field bindings differ from its plan")
    return BenchmarkMetadataPopulationChainInspection(
        population=population_inspection,
        plan=plan,
        approval=approval,
        audit=audit,
        projection_implementation_current=(
            plan.plan.projection_implementation_sha256 == _module_sha256()
        ),
    )


def _verify_control_chain(
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
    report: StructuredMetadataAuditReport,
) -> None:
    if (
        not request.approval.approved
        or request.approval.request_sha256 != request.request_sha256
        or receipt.request_id != request.request_id
        or receipt.request_sha256 != request.request_sha256
        or report.project_id != request.project_id
        or report.request_id != request.request_id
        or report.request_sha256 != request.request_sha256
        or report.receipt_sha256 != receipt.receipt_sha256
        or report.item_count != len(receipt.items)
    ):
        raise ValueError("benchmark metadata projection control chain is invalid")
    report_items = {item.item_id: item for item in report.items}
    request_items = {item.item_id: item for item in request.items}
    receipt_items = {item.item_id: item for item in receipt.items}
    if set(report_items) != set(receipt_items) or set(receipt_items) != set(request_items):
        raise ValueError("benchmark metadata audit and receipt inventories differ")
    for item in receipt.items:
        observed = report_items[item.item_id]
        requested = request_items[item.item_id]
        if (
            not observed.exact_bytes_verified
            or not observed.utf8_verified
            or not observed.syntax_verified
            or not observed.structural_bounds_verified
            or observed.blocker_codes
            or observed.receipt_size_bytes != item.size_bytes
            or observed.receipt_sha256 != item.sha256
            or observed.destination != item.destination
            or observed.destination != requested.destination
            or observed.media_type.value != requested.media_type
        ):
            raise ValueError("benchmark metadata audit item differs from receipt")


def _verify_scope_source_population(
    request: DatasetAcquisitionRequest,
    scope: BenchmarkMetadataScope,
) -> None:
    """Bind acquired source identities to the pre-inspection scope, not just its count."""

    if scope.task_config_paths is not None:
        matched_paths: list[str] = []
        for item in request.items:
            if item.source_revision != scope.repository_commit:
                raise ValueError("YAML acquisition revision differs from frozen scope")
            path = urlsplit(item.source_url).path
            matches = [
                expected
                for expected in scope.task_config_paths
                if path.endswith(f"/{scope.repository_commit}/{expected}")
            ]
            if len(matches) != 1:
                raise ValueError("YAML acquisition source is outside the frozen task population")
            matched_paths.append(matches[0])
        if set(matched_paths) != set(scope.task_config_paths) or len(matched_paths) != len(
            scope.task_config_paths
        ):
            raise ValueError("YAML acquisition does not cover the exact frozen task population")
        return

    if scope.metadata_file is None or len(request.items) != 1:
        raise ValueError("CSV acquisition must contain the one frozen metadata table")
    item = request.items[0]
    if item.source_revision != scope.dataset_revision or not urlsplit(
        item.source_url
    ).path.endswith(f"/{scope.dataset_revision}/{scope.metadata_file}"):
        raise ValueError("CSV acquisition source differs from the frozen metadata table")


def _validate_yaml_bindings(
    items: tuple[StructuredMetadataAuditItemReport, ...],
    bindings: tuple[MetadataFieldBinding, ...],
) -> None:
    if not items or any(item.media_type is not StructuredMetadataFormat.YAML for item in items):
        raise ValueError("YAML metadata projection requires an all-YAML audit")
    for binding in bindings:
        if binding.availability == "absent-from-audited-source":
            continue
        matches = [
            observations[path]
            for item in items
            for observations in [{field.path: field for field in item.field_observations}]
            for path in binding.source_fields
            if path in observations
        ]
        if not matches:
            raise ValueError(
                f"metadata field {binding.semantic_field!r} is absent from the YAML population"
            )
        if any(not set(match.observed_types).issubset(_SCALAR_TYPES) for match in matches):
            raise ValueError("metadata projection bindings must terminate at scalar fields")


def _validate_csv_bindings(
    items: tuple[StructuredMetadataAuditItemReport, ...],
    bindings: tuple[MetadataFieldBinding, ...],
) -> None:
    if not items or any(item.media_type is not StructuredMetadataFormat.CSV for item in items):
        raise ValueError("CSV metadata projection requires an all-CSV audit")
    for binding in bindings:
        if binding.availability == "absent-from-audited-source":
            continue
        for item in items:
            if not any(source in item.csv_header for source in binding.source_fields):
                raise ValueError(
                    f"metadata field {binding.semantic_field!r} is not observed in every CSV table"
                )


def _project_yaml_record(
    item_id: str,
    source_sha256: str,
    decoded: str,
    bindings: tuple[MetadataFieldBinding, ...],
    maximum_value_bytes: int,
) -> ProjectedBenchmarkMetadataRecord:
    payload = yaml.safe_load(decoded)
    if not isinstance(payload, dict):
        raise ValueError("audited YAML metadata no longer contains a mapping")
    fields = tuple(
        _projected_field(
            binding,
            [
                value
                for source in binding.source_fields
                for value in _resolve_structural_path(payload, source, allow_missing=True)
            ],
            maximum_value_bytes,
        )
        for binding in bindings
    )
    return ProjectedBenchmarkMetadataRecord(
        record_id=item_id,
        source_item_id=item_id,
        source_sha256=source_sha256,
        fields=fields,
    )


def _project_csv_records(
    item_id: str,
    source_sha256: str,
    decoded: str,
    bindings: tuple[MetadataFieldBinding, ...],
    maximum_value_bytes: int,
) -> tuple[ProjectedBenchmarkMetadataRecord, ...]:
    reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
    if reader.fieldnames is None:
        raise ValueError("audited CSV metadata no longer has a header")
    records: list[ProjectedBenchmarkMetadataRecord] = []
    for ordinal, row in enumerate(reader, start=1):
        fields = tuple(
            _projected_field(
                binding,
                [row[source] for source in binding.source_fields if source in row],
                maximum_value_bytes,
            )
            for binding in bindings
        )
        records.append(
            ProjectedBenchmarkMetadataRecord(
                record_id=f"{item_id}-row-{ordinal:06d}",
                source_item_id=item_id,
                source_sha256=source_sha256,
                row_ordinal=ordinal,
                fields=fields,
            )
        )
    return tuple(records)


def _projected_field(
    binding: MetadataFieldBinding,
    values: list[JsonScalar],
    maximum_value_bytes: int,
) -> ProjectedMetadataField:
    bounded = _bounded_values(values, maximum_value_bytes) if values else ()
    return ProjectedMetadataField(
        semantic_field=binding.semantic_field,
        availability=binding.availability,
        source_fields=binding.source_fields,
        source_field_present=bool(bounded),
        values=bounded,
    )


def _resolve_structural_path(
    payload: object,
    path: str,
    *,
    allow_missing: bool = False,
) -> tuple[JsonScalar, ...]:
    if not path.startswith("/") or path == "/":
        raise ValueError("metadata projection requires a non-root structural path")
    segments = tuple(_unescape_path(part) for part in path[1:].split("/"))
    current = [payload]
    for segment in segments:
        following: list[object] = []
        for value in current:
            if segment == "*" and isinstance(value, list):
                following.extend(value)
            elif segment == "*" and isinstance(value, dict):
                following.extend(value.values())
            elif isinstance(value, dict) and segment in value:
                following.append(value[segment])
        current = following
    if not current and allow_missing:
        return ()
    if not current or any(isinstance(value, (dict, list)) for value in current):
        raise ValueError("metadata projection field is missing or not scalar")
    if any(isinstance(value, float) and not math.isfinite(value) for value in current):
        raise ValueError("metadata projection forbids non-finite numeric values")
    return tuple(current)  # type: ignore[return-value]


def _bounded_values(values: list[JsonScalar], maximum_value_bytes: int) -> tuple[JsonScalar, ...]:
    if not values:
        raise ValueError("metadata projection field has no value")
    rendered = json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(rendered.encode("utf-8")) > maximum_value_bytes:
        raise ValueError("metadata projection field exceeds its value ceiling")
    return tuple(values)


def _unescape_path(value: str) -> str:
    result = value.replace("~1", "/").replace("~0", "~")
    if "~" in value.replace("~0", "").replace("~1", ""):
        raise ValueError("metadata projection path contains an invalid escape")
    return result


def _relative_locator(root: Path, path: Path, label: str) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must be inside the workspace")
    return resolved.relative_to(root).as_posix()


def _load_relative_path_from_root(root: Path, path: Path, label: str) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must be inside the workspace")
    return resolved.relative_to(root).as_posix()


def _contained_locator(root: Path, locator: str, label: str) -> Path:
    resolved = _resolve_beneath(root, locator)
    if resolved is None or resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} is unavailable or escaped the workspace")
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must be normalized and relative")


def _resolve_beneath(root: Path, locator: str) -> Path | None:
    try:
        _validate_relative_path(locator, "workspace locator")
    except ValueError:
        return None
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            return None
    resolved = current.resolve(strict=False)
    return resolved if resolved.is_relative_to(root) else None


def _read_bounded_file(path: str | Path, label: str) -> tuple[Path, bytes]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    return resolved, resolved.read_bytes()


def _load_json_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    resolved, raw = _read_bounded_file(path, label)
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, raw, payload


class DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _write_new_json(path: str | Path, text: str) -> Path:
    target = Path(path)
    if target.is_symlink() or target.exists():
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
        os.link(temporary, target)
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _module_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


__all__ = [
    "BenchmarkMetadataPopulation",
    "BenchmarkMetadataPopulationChainInspection",
    "BenchmarkMetadataPopulationInspection",
    "BenchmarkMetadataProjectionApproval",
    "BenchmarkMetadataProjectionApprovalInspection",
    "BenchmarkMetadataProjectionPlan",
    "BenchmarkMetadataProjectionPlanInspection",
    "BenchmarkMetadataScope",
    "BenchmarkMetadataScopeInspection",
    "MetadataFieldBinding",
    "ProjectedBenchmarkMetadataRecord",
    "ProjectedMetadataField",
    "StructuredMetadataAuditReportInspection",
    "approve_benchmark_metadata_projection",
    "inspect_benchmark_metadata_population_chain",
    "load_benchmark_metadata_population",
    "load_benchmark_metadata_projection_approval",
    "load_benchmark_metadata_projection_plan",
    "load_benchmark_metadata_scope",
    "load_structured_metadata_audit_report",
    "plan_benchmark_metadata_projection",
    "project_benchmark_metadata_population",
    "save_benchmark_metadata_population",
    "save_benchmark_metadata_projection_approval",
    "save_benchmark_metadata_projection_plan",
]
