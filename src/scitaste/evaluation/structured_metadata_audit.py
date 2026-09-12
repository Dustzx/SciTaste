"""Approval-gated structural audit for acquired YAML and CSV metadata."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from yaml.tokens import AliasToken, AnchorToken, TagToken

from scitaste.evaluation.acquisition import (
    AcquisitionReceiptInspection,
    AcquisitionRequestInspection,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 4 * 1_048_576


class StructuredMetadataFormat(StrEnum):
    YAML = "application/x-yaml"
    CSV = "text/csv"


class StructuredMetadataAuditPlan(BaseModel):
    """Exact no-content-read proposal for one acquired metadata transaction."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    request_file_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    acquired_at: datetime
    auditor_id: Literal["scitaste-structured-metadata-audit-v1"]
    auditor_implementation_sha256: str = Field(pattern=_SHA256)
    expected_item_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    formats: tuple[StructuredMetadataFormat, ...] = Field(min_length=1, max_length=2)
    maximum_source_bytes_per_item: int = Field(ge=1, le=64 * 1_048_576)
    maximum_total_source_bytes: int = Field(ge=1, le=1_024 * 1_048_576)
    maximum_structure_depth: int = Field(ge=2, le=128)
    maximum_nodes_per_item: int = Field(ge=1, le=5_000_000)
    maximum_distinct_paths: int = Field(ge=1, le=100_000)
    maximum_string_utf8_bytes: int = Field(ge=1, le=16 * 1_048_576)
    maximum_csv_rows: int = Field(ge=1, le=5_000_000)
    maximum_csv_columns: int = Field(ge=1, le=100_000)
    ready_for_owner_approval: Literal[True] = True
    source_content_read: Literal[False] = False
    authorizes_local_content_read: Literal[False] = False
    authorizes_network_access: Literal[False] = False
    authorizes_link_resolution: Literal[False] = False
    authorizes_projection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("acquired_at")
    @classmethod
    def acquisition_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("structured metadata acquisition timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def plan_inventory_is_closed(self) -> StructuredMetadataAuditPlan:
        if len(self.expected_item_ids) != len(set(self.expected_item_ids)):
            raise ValueError("structured metadata audit item IDs must be unique")
        if tuple(sorted(set(self.formats))) != self.formats:
            raise ValueError("structured metadata audit formats must be sorted and unique")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class StructuredMetadataAuditPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: StructuredMetadataAuditPlan


class StructuredMetadataAuditApproval(BaseModel):
    """Owner authority for the exact local structural read described by a plan."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(pattern=_ID)
    plan_id: str = Field(pattern=_ID)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["local-bounded-yaml-csv-structure-audit-only"]
    authorizes_local_content_read: Literal[True] = True
    authorizes_network_access: Literal[False] = False
    authorizes_link_resolution: Literal[False] = False
    authorizes_projection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_review: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("structured metadata approval timestamp must include a timezone")
        return value

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class StructuredMetadataAuditApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: StructuredMetadataAuditApproval


class StructuredFieldObservation(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    observed_types: tuple[
        Literal["null", "boolean", "integer", "number", "string", "array", "object"], ...
    ] = Field(min_length=1, max_length=7)
    occurrences: int = Field(gt=0)
    maximum_string_utf8_bytes: int = Field(ge=0)
    external_locator_count: int = Field(ge=0)


class StructuredMetadataAuditItemReport(BaseModel):
    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    destination: str = Field(min_length=1, max_length=1_000)
    media_type: StructuredMetadataFormat
    receipt_size_bytes: int = Field(gt=0)
    receipt_sha256: str = Field(pattern=_SHA256)
    observed_size_bytes: int = Field(ge=0)
    observed_sha256: str | None = Field(default=None, pattern=_SHA256)
    exact_bytes_verified: bool
    utf8_verified: bool
    syntax_verified: bool
    structural_bounds_verified: bool
    top_level_mapping_verified: bool | None = None
    field_observations: tuple[StructuredFieldObservation, ...] = ()
    total_nodes: int = Field(ge=0)
    maximum_observed_depth: int = Field(ge=0)
    csv_header: tuple[str, ...] = ()
    csv_data_rows: int = Field(ge=0)
    csv_maximum_columns: int = Field(ge=0)
    maximum_observed_string_utf8_bytes: int = Field(ge=0)
    external_locator_count: int = Field(ge=0)
    formula_like_cell_count: int = Field(ge=0)
    blocker_codes: tuple[str, ...]

    @model_validator(mode="after")
    def format_fields_are_consistent(self) -> StructuredMetadataAuditItemReport:
        if self.media_type is StructuredMetadataFormat.YAML:
            if self.top_level_mapping_verified is None or self.csv_header:
                raise ValueError("YAML audit report has inconsistent format fields")
        elif self.top_level_mapping_verified is not None or self.field_observations:
            raise ValueError("CSV audit report has inconsistent format fields")
        return self


class StructuredMetadataAuditReport(BaseModel):
    """Structural evidence only; it is not a task projection or benchmark admission."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    approval_id: str = Field(pattern=_ID)
    approval_sha256: str = Field(pattern=_SHA256)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    auditor_id: Literal["scitaste-structured-metadata-audit-v1"]
    auditor_implementation_sha256: str = Field(pattern=_SHA256)
    audited_at: datetime
    item_count: int = Field(gt=0)
    observed_total_bytes: int = Field(ge=0)
    exact_inventory_verified: bool
    exact_bytes_verified: bool
    all_utf8_verified: bool
    all_syntax_verified: bool
    all_structural_bounds_verified: bool
    ready_for_metadata_screen_proposal: bool
    items: tuple[StructuredMetadataAuditItemReport, ...]
    blocker_codes: tuple[str, ...]
    content_access_performed: Literal[True] = True
    source_files_modified: Literal[False] = False
    network_access_performed: Literal[False] = False
    linked_assets_resolved: Literal[False] = False
    projection_performed: Literal[False] = False
    ingestion_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    human_review_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_projection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("audited_at")
    @classmethod
    def audit_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("structured metadata audit timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def report_totals_are_derived(self) -> StructuredMetadataAuditReport:
        if self.item_count != len(self.items):
            raise ValueError("structured metadata audit item count differs")
        if self.observed_total_bytes != sum(item.observed_size_bytes for item in self.items):
            raise ValueError("structured metadata audit byte count differs")
        ready = (
            self.exact_inventory_verified
            and self.exact_bytes_verified
            and self.all_utf8_verified
            and self.all_syntax_verified
            and self.all_structural_bounds_verified
            and not self.blocker_codes
        )
        if self.ready_for_metadata_screen_proposal != ready:
            raise ValueError("structured metadata audit readiness differs from evidence")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def plan_structured_metadata_audit(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    *,
    maximum_source_bytes_per_item: int = 16 * 1_048_576,
    maximum_total_source_bytes: int = 64 * 1_048_576,
    maximum_structure_depth: int = 32,
    maximum_nodes_per_item: int = 500_000,
    maximum_distinct_paths: int = 10_000,
    maximum_string_utf8_bytes: int = 1_048_576,
    maximum_csv_rows: int = 1_000_000,
    maximum_csv_columns: int = 4_096,
) -> StructuredMetadataAuditPlan:
    """Build an exact approval proposal without reading acquired source bodies."""

    _verify_acquisition_chain(request, receipt)
    source_request = request.request
    if any(item.size_bytes > maximum_source_bytes_per_item for item in receipt.receipt.items):
        raise ValueError("structured metadata item exceeds the proposed local-read ceiling")
    if receipt.receipt.total_bytes > maximum_total_source_bytes:
        raise ValueError("structured metadata transaction exceeds the proposed local-read ceiling")
    formats = tuple(
        sorted({StructuredMetadataFormat(item.media_type) for item in source_request.items})
    )
    return StructuredMetadataAuditPlan(
        plan_id=f"{source_request.request_id}-metadata-content-audit-v1",
        project_id=source_request.project_id,
        request_id=source_request.request_id,
        request_file_sha256=request.file_sha256,
        request_sha256=source_request.request_sha256,
        receipt_file_sha256=receipt.file_sha256,
        receipt_sha256=receipt.receipt.receipt_sha256,
        acquired_at=receipt.receipt.acquired_at,
        auditor_id="scitaste-structured-metadata-audit-v1",
        auditor_implementation_sha256=_module_sha256(),
        expected_item_ids=tuple(item.item_id for item in source_request.items),
        formats=formats,
        maximum_source_bytes_per_item=maximum_source_bytes_per_item,
        maximum_total_source_bytes=maximum_total_source_bytes,
        maximum_structure_depth=maximum_structure_depth,
        maximum_nodes_per_item=maximum_nodes_per_item,
        maximum_distinct_paths=maximum_distinct_paths,
        maximum_string_utf8_bytes=maximum_string_utf8_bytes,
        maximum_csv_rows=maximum_csv_rows,
        maximum_csv_columns=maximum_csv_columns,
    )


def approve_structured_metadata_audit(
    plan: StructuredMetadataAuditPlanInspection,
    *,
    confirmed_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> StructuredMetadataAuditApproval:
    """Authorize only the bounded local read described by an exact plan."""

    if confirmed_plan_sha256 != plan.plan.plan_sha256:
        raise ValueError("confirmed structured metadata audit plan hash differs")
    if approved_at.utcoffset() is None:
        raise ValueError("structured metadata approval timestamp must include a timezone")
    if approved_at < plan.plan.acquired_at:
        raise ValueError("structured metadata content access cannot precede acquisition")
    return StructuredMetadataAuditApproval(
        approval_id=f"{plan.plan.plan_id}-approval",
        plan_id=plan.plan.plan_id,
        plan_file_sha256=plan.file_sha256,
        plan_sha256=plan.plan.plan_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        scope="local-bounded-yaml-csv-structure-audit-only",
    )


def inspect_acquired_structured_metadata(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    plan: StructuredMetadataAuditPlanInspection,
    approval: StructuredMetadataAuditApprovalInspection,
    *,
    workspace_root: str | Path,
    allow_local_content_read: bool,
    audited_at: datetime,
) -> StructuredMetadataAuditReport:
    """Read only the approved YAML/CSV bytes and emit structural evidence."""

    if not allow_local_content_read:
        raise ValueError("structured metadata audit requires --allow-local-content-read")
    _verify_execution_bindings(request, receipt, plan, approval)
    if audited_at.utcoffset() is None:
        raise ValueError("structured metadata audit timestamp must include a timezone")
    if audited_at < approval.approval.approved_at:
        raise ValueError("structured metadata audit cannot precede its approval")

    root = Path(workspace_root).resolve(strict=True)
    raw_root = _resolve_beneath(root, receipt.receipt.destination_root)
    blockers: list[str] = []
    inventory_verified = True
    if raw_root is None or raw_root.is_symlink() or not raw_root.is_dir():
        blockers.append("raw-root-unavailable")
        inventory_verified = False
    expected_paths = {item.destination for item in receipt.receipt.items}
    if raw_root is not None and raw_root.is_dir() and not raw_root.is_symlink():
        files = {
            path.relative_to(raw_root).as_posix()
            for path in raw_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        symlinks = {
            path.relative_to(raw_root).as_posix()
            for path in raw_root.rglob("*")
            if path.is_symlink()
        }
        if files != expected_paths:
            blockers.append("raw-file-inventory-mismatch")
            inventory_verified = False
        if symlinks:
            blockers.append("raw-symlink-forbidden")
            inventory_verified = False

    request_items = {item.item_id: item for item in request.request.items}
    reports: list[StructuredMetadataAuditItemReport] = []
    for item in receipt.receipt.items:
        path = _resolve_beneath(raw_root, item.destination) if raw_root is not None else None
        reports.append(
            _inspect_item(
                item_id=item.item_id,
                destination=item.destination,
                media_type=StructuredMetadataFormat(request_items[item.item_id].media_type),
                expected_size=item.size_bytes,
                expected_sha256=item.sha256,
                maximum_bytes=min(
                    request_items[item.item_id].maximum_bytes,
                    plan.plan.maximum_source_bytes_per_item,
                ),
                path=path,
                plan=plan.plan,
            )
        )
    for item in reports:
        blockers.extend(f"{item.item_id}:{code}" for code in item.blocker_codes)
    blocker_codes = tuple(sorted(set(blockers)))
    exact = inventory_verified and all(item.exact_bytes_verified for item in reports)
    utf8 = all(item.utf8_verified for item in reports)
    syntax = all(item.syntax_verified for item in reports)
    bounds = all(item.structural_bounds_verified for item in reports)
    return StructuredMetadataAuditReport(
        plan_id=plan.plan.plan_id,
        plan_sha256=plan.plan.plan_sha256,
        approval_id=approval.approval.approval_id,
        approval_sha256=approval.approval.approval_sha256,
        project_id=plan.plan.project_id,
        request_id=plan.plan.request_id,
        request_sha256=plan.plan.request_sha256,
        receipt_sha256=plan.plan.receipt_sha256,
        auditor_id=plan.plan.auditor_id,
        auditor_implementation_sha256=plan.plan.auditor_implementation_sha256,
        audited_at=audited_at,
        item_count=len(reports),
        observed_total_bytes=sum(item.observed_size_bytes for item in reports),
        exact_inventory_verified=inventory_verified,
        exact_bytes_verified=exact,
        all_utf8_verified=utf8,
        all_syntax_verified=syntax,
        all_structural_bounds_verified=bounds,
        ready_for_metadata_screen_proposal=(
            exact and utf8 and syntax and bounds and not blocker_codes
        ),
        items=tuple(reports),
        blocker_codes=blocker_codes,
    )


def save_structured_metadata_audit_plan(
    plan: StructuredMetadataAuditPlan,
    path: str | Path,
) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def load_structured_metadata_audit_plan(
    path: str | Path,
) -> StructuredMetadataAuditPlanInspection:
    resolved, raw, payload = _load_json_mapping(path, "structured metadata audit plan")
    recorded = payload.pop("plan_sha256", None)
    plan = StructuredMetadataAuditPlan.model_validate(payload)
    if recorded != plan.plan_sha256:
        raise ValueError("structured metadata audit plan hash mismatch")
    return StructuredMetadataAuditPlanInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        plan=plan,
    )


def save_structured_metadata_audit_approval(
    approval: StructuredMetadataAuditApproval,
    path: str | Path,
) -> Path:
    return _write_new_json(path, approval.model_dump_json(indent=2) + "\n")


def load_structured_metadata_audit_approval(
    path: str | Path,
) -> StructuredMetadataAuditApprovalInspection:
    resolved, raw, payload = _load_json_mapping(path, "structured metadata audit approval")
    recorded = payload.pop("approval_sha256", None)
    approval = StructuredMetadataAuditApproval.model_validate(payload)
    if recorded != approval.approval_sha256:
        raise ValueError("structured metadata audit approval hash mismatch")
    return StructuredMetadataAuditApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def save_structured_metadata_audit_report(
    report: StructuredMetadataAuditReport,
    path: str | Path,
) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def _verify_acquisition_chain(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
) -> None:
    source_request = request.request
    source_receipt = receipt.receipt
    if (
        not source_request.approval.approved
        or source_request.approval.request_sha256 != source_request.request_sha256
        or source_receipt.request_id != source_request.request_id
        or source_receipt.request_sha256 != source_request.request_sha256
        or source_receipt.destination_root != source_request.destination_root
    ):
        raise ValueError("structured metadata audit acquisition chain is invalid")
    requested_ids = tuple(item.item_id for item in source_request.items)
    received_ids = tuple(item.item_id for item in source_receipt.items)
    if requested_ids != received_ids:
        raise ValueError("structured metadata request and receipt inventory differs")
    allowed = {item.value for item in StructuredMetadataFormat}
    if any(item.media_type not in allowed for item in source_request.items):
        raise ValueError("structured metadata audit accepts only YAML or CSV items")


def _verify_execution_bindings(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    plan: StructuredMetadataAuditPlanInspection,
    approval: StructuredMetadataAuditApprovalInspection,
) -> None:
    _verify_acquisition_chain(request, receipt)
    expected = plan_structured_metadata_audit(
        request,
        receipt,
        maximum_source_bytes_per_item=plan.plan.maximum_source_bytes_per_item,
        maximum_total_source_bytes=plan.plan.maximum_total_source_bytes,
        maximum_structure_depth=plan.plan.maximum_structure_depth,
        maximum_nodes_per_item=plan.plan.maximum_nodes_per_item,
        maximum_distinct_paths=plan.plan.maximum_distinct_paths,
        maximum_string_utf8_bytes=plan.plan.maximum_string_utf8_bytes,
        maximum_csv_rows=plan.plan.maximum_csv_rows,
        maximum_csv_columns=plan.plan.maximum_csv_columns,
    )
    if expected != plan.plan:
        raise ValueError("structured metadata audit plan bindings have drifted")
    authority = approval.approval
    if (
        authority.plan_id != plan.plan.plan_id
        or authority.plan_file_sha256 != plan.file_sha256
        or authority.plan_sha256 != plan.plan.plan_sha256
    ):
        raise ValueError("structured metadata audit approval bindings have drifted")


def _inspect_item(
    *,
    item_id: str,
    destination: str,
    media_type: StructuredMetadataFormat,
    expected_size: int,
    expected_sha256: str,
    maximum_bytes: int,
    path: Path | None,
    plan: StructuredMetadataAuditPlan,
) -> StructuredMetadataAuditItemReport:
    blockers: list[str] = []
    content = b""
    observed_size = 0
    observed_sha256 = None
    exact = False
    if path is None or path.is_symlink() or not path.is_file():
        blockers.append("file-unavailable")
    else:
        observed_size = path.stat().st_size
        if observed_size > maximum_bytes:
            blockers.append("byte-ceiling-exceeded")
        else:
            content = path.read_bytes()
            observed_size = len(content)
            observed_sha256 = hashlib.sha256(content).hexdigest()
            exact = observed_size == expected_size and observed_sha256 == expected_sha256
            if not exact:
                blockers.append("byte-integrity-failed")
    decoded = None
    try:
        decoded = content.decode("utf-8") if exact else None
    except UnicodeDecodeError:
        blockers.append("utf8-invalid")
    if decoded is not None and "\x00" in decoded:
        blockers.append("nul-byte-forbidden")
        decoded = None

    if media_type is StructuredMetadataFormat.YAML:
        result = _inspect_yaml(decoded, plan, blockers)
    else:
        result = _inspect_csv(decoded, plan, blockers)
    return StructuredMetadataAuditItemReport(
        item_id=item_id,
        destination=destination,
        media_type=media_type,
        receipt_size_bytes=expected_size,
        receipt_sha256=expected_sha256,
        observed_size_bytes=observed_size,
        observed_sha256=observed_sha256,
        exact_bytes_verified=exact,
        utf8_verified=decoded is not None,
        blocker_codes=tuple(sorted(set(blockers))),
        **result,
    )


def _inspect_yaml(
    decoded: str | None,
    plan: StructuredMetadataAuditPlan,
    blockers: list[str],
) -> dict[str, object]:
    payload = None
    if decoded is not None:
        try:
            tokens = tuple(yaml.scan(decoded))
            if any(isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in tokens):
                blockers.append("yaml-anchor-alias-or-tag-forbidden")
            else:
                documents = list(yaml.load_all(decoded, Loader=_UniqueSafeLoader))
                if len(documents) != 1:
                    blockers.append("yaml-document-count-invalid")
                else:
                    payload = documents[0]
        except (yaml.YAMLError, ValueError, RecursionError):
            blockers.append("yaml-invalid")
    syntax = payload is not None
    top_level = isinstance(payload, dict)
    if syntax and not top_level:
        blockers.append("yaml-top-level-not-mapping")
    shapes: dict[str, _MutableShape] = defaultdict(_MutableShape)
    state = _WalkState()
    bounded = False
    if top_level:
        try:
            _walk_value(payload, path="/", depth=0, plan=plan, shapes=shapes, state=state)
            bounded = True
        except StructuralLimitError as exc:
            blockers.append(exc.code)
    observations = tuple(
        StructuredFieldObservation(
            path=path,
            observed_types=tuple(sorted(shape.types)),
            occurrences=shape.occurrences,
            maximum_string_utf8_bytes=shape.maximum_string_utf8_bytes,
            external_locator_count=shape.external_locator_count,
        )
        for path, shape in sorted(shapes.items())
    )
    return {
        "syntax_verified": syntax,
        "structural_bounds_verified": bounded,
        "top_level_mapping_verified": top_level,
        "field_observations": observations,
        "total_nodes": state.nodes,
        "maximum_observed_depth": state.maximum_depth,
        "csv_header": (),
        "csv_data_rows": 0,
        "csv_maximum_columns": 0,
        "maximum_observed_string_utf8_bytes": state.maximum_string_utf8_bytes,
        "external_locator_count": state.external_locators,
        "formula_like_cell_count": 0,
    }


def _inspect_csv(
    decoded: str | None,
    plan: StructuredMetadataAuditPlan,
    blockers: list[str],
) -> dict[str, object]:
    header: tuple[str, ...] = ()
    data_rows = 0
    maximum_columns = 0
    maximum_string = 0
    external_locators = 0
    formula_like = 0
    syntax = False
    bounded = False
    if decoded is not None:
        previous_limit = csv.field_size_limit()
        try:
            csv.field_size_limit(plan.maximum_string_utf8_bytes)
            reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
            first = next(reader, None)
            if first is None:
                blockers.append("csv-empty")
            else:
                header = tuple(first)
                maximum_columns = len(header)
                for value in header:
                    size = len(value.encode("utf-8"))
                    maximum_string = max(maximum_string, size)
                    if size > plan.maximum_string_utf8_bytes:
                        raise StructuralLimitError("maximum-csv-field-bytes-exceeded")
                if not header or any(not value.strip() for value in header):
                    blockers.append("csv-header-empty")
                normalized = tuple(value.strip().casefold() for value in header)
                if len(normalized) != len(set(normalized)):
                    blockers.append("csv-header-duplicate")
                if len(header) > plan.maximum_csv_columns:
                    blockers.append("maximum-csv-columns-exceeded")
                for row in reader:
                    data_rows += 1
                    if data_rows > plan.maximum_csv_rows:
                        raise StructuralLimitError("maximum-csv-rows-exceeded")
                    maximum_columns = max(maximum_columns, len(row))
                    if len(row) != len(header):
                        blockers.append("csv-row-width-mismatch")
                    for value in row:
                        size = len(value.encode("utf-8"))
                        maximum_string = max(maximum_string, size)
                        if size > plan.maximum_string_utf8_bytes:
                            raise StructuralLimitError("maximum-csv-field-bytes-exceeded")
                        external_locators += int(_is_external_locator(value))
                        formula_like += int(value.lstrip().startswith(("=", "+", "-", "@")))
                syntax = True
                bounded = not any(
                    code
                    in {
                        "maximum-csv-columns-exceeded",
                        "csv-row-width-mismatch",
                    }
                    for code in blockers
                )
        except csv.Error:
            blockers.append("csv-invalid")
        except StructuralLimitError as exc:
            blockers.append(exc.code)
        finally:
            csv.field_size_limit(previous_limit)
    return {
        "syntax_verified": syntax,
        "structural_bounds_verified": bounded,
        "top_level_mapping_verified": None,
        "field_observations": (),
        "total_nodes": data_rows * maximum_columns + len(header),
        "maximum_observed_depth": 1 if header else 0,
        "csv_header": header,
        "csv_data_rows": data_rows,
        "csv_maximum_columns": maximum_columns,
        "maximum_observed_string_utf8_bytes": maximum_string,
        "external_locator_count": external_locators,
        "formula_like_cell_count": formula_like,
    }


class DuplicateYamlKeyError(ValueError):
    pass


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[str, object]:
    if any(
        key_node.tag == "tag:yaml.org,2002:merge" or key_node.value == "<<"
        for key_node, _ in node.value
    ):
        raise DuplicateYamlKeyError("YAML merge keys are forbidden")
    loader.flatten_mapping(node)
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise DuplicateYamlKeyError("YAML mapping keys must be strings")
        if key in result:
            raise DuplicateYamlKeyError(key)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class StructuralLimitError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _MutableShape:
    def __init__(self) -> None:
        self.types: set[str] = set()
        self.occurrences = 0
        self.maximum_string_utf8_bytes = 0
        self.external_locator_count = 0


class _WalkState:
    def __init__(self) -> None:
        self.nodes = 0
        self.maximum_depth = 0
        self.maximum_string_utf8_bytes = 0
        self.external_locators = 0


def _walk_value(
    value: object,
    *,
    path: str,
    depth: int,
    plan: StructuredMetadataAuditPlan,
    shapes: dict[str, _MutableShape],
    state: _WalkState,
) -> None:
    state.nodes += 1
    state.maximum_depth = max(state.maximum_depth, depth)
    if state.nodes > plan.maximum_nodes_per_item:
        raise StructuralLimitError("maximum-structure-nodes-exceeded")
    if depth > plan.maximum_structure_depth:
        raise StructuralLimitError("maximum-structure-depth-exceeded")
    if path not in shapes and len(shapes) >= plan.maximum_distinct_paths:
        raise StructuralLimitError("maximum-distinct-paths-exceeded")
    shape = shapes[path]
    kind = _value_type(value)
    shape.types.add(kind)
    shape.occurrences += 1
    if isinstance(value, str):
        size = len(value.encode("utf-8"))
        shape.maximum_string_utf8_bytes = max(shape.maximum_string_utf8_bytes, size)
        state.maximum_string_utf8_bytes = max(state.maximum_string_utf8_bytes, size)
        if size > plan.maximum_string_utf8_bytes:
            raise StructuralLimitError("maximum-structure-string-bytes-exceeded")
        if _is_external_locator(value):
            shape.external_locator_count += 1
            state.external_locators += 1
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise StructuralLimitError("yaml-key-not-string")
            child_path = _join_path(path, _escape_path(key))
            if len(child_path) > 2_000:
                raise StructuralLimitError("maximum-structure-path-length-exceeded")
            _walk_value(
                child,
                path=child_path,
                depth=depth + 1,
                plan=plan,
                shapes=shapes,
                state=state,
            )
    elif isinstance(value, list):
        for child in value:
            _walk_value(
                child,
                path=_join_path(path, "*"),
                depth=depth + 1,
                plan=plan,
                shapes=shapes,
                state=state,
            )


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise StructuralLimitError(f"unsupported-yaml-type-{type(value).__name__}")


def _is_external_locator(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)


def _join_path(parent: str, child: str) -> str:
    return f"/{child}" if parent == "/" else f"{parent}/{child}"


def _escape_path(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _resolve_beneath(root: Path, locator: str) -> Path | None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            return None
    resolved = current.resolve(strict=False)
    return resolved if resolved.is_relative_to(root) else None


def _load_json_mapping(
    path: str | Path,
    label: str,
) -> tuple[Path, bytes, dict[str, object]]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError, ValueError) as exc:
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
    "StructuredFieldObservation",
    "StructuredMetadataAuditApproval",
    "StructuredMetadataAuditApprovalInspection",
    "StructuredMetadataAuditItemReport",
    "StructuredMetadataAuditPlan",
    "StructuredMetadataAuditPlanInspection",
    "StructuredMetadataAuditReport",
    "StructuredMetadataFormat",
    "approve_structured_metadata_audit",
    "inspect_acquired_structured_metadata",
    "load_structured_metadata_audit_approval",
    "load_structured_metadata_audit_plan",
    "plan_structured_metadata_audit",
    "save_structured_metadata_audit_approval",
    "save_structured_metadata_audit_plan",
    "save_structured_metadata_audit_report",
]
