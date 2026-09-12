"""Approval-gated, deterministic inspection of acquired JSON source records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.acquisition import (
    AcquisitionReceiptInspection,
    AcquisitionRequestInspection,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 4 * 1_048_576
_ARXIV_ID = re.compile(r"^(?:arxiv\s*:\s*)?(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)


class JsonIdentityStatus(StrEnum):
    MATCH = "match"
    ABSENT = "absent"
    MISMATCH = "mismatch"
    AMBIGUOUS = "ambiguous"


class JsonContentAuditApproval(BaseModel):
    """Owner authority for local parsing only; it cannot authorize projection or use."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    request_file_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    auditor_id: Literal["scitaste-json-content-audit-v1"]
    auditor_implementation_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["local-bounded-json-structure-and-identity-audit-only"]
    expected_item_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    maximum_json_depth: int = Field(ge=2, le=128)
    maximum_container_items: int = Field(ge=1, le=1_000_000)
    maximum_nodes_per_item: int = Field(ge=1, le=5_000_000)
    maximum_string_utf8_bytes: int = Field(ge=1, le=16 * 1_048_576)
    identity_field_names: tuple[str, ...] = Field(min_length=1, max_length=30)
    require_embedded_identity_match: bool = True
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
            raise ValueError("JSON content-audit approval timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def approval_scope_is_closed(self) -> JsonContentAuditApproval:
        if len(self.expected_item_ids) != len(set(self.expected_item_ids)):
            raise ValueError("JSON content-audit item IDs must be unique")
        normalized = tuple(_normalize_field_name(item) for item in self.identity_field_names)
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("JSON content-audit identity field names must normalize uniquely")
        return self

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class JsonContentAuditApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: JsonContentAuditApproval


class JsonFieldObservation(BaseModel):
    model_config = _CONFIG

    json_pointer: str = Field(min_length=1, max_length=2_000)
    observed_types: tuple[
        Literal["null", "boolean", "integer", "number", "string", "array", "object"], ...
    ] = Field(min_length=1, max_length=7)
    occurrences: int = Field(gt=0)
    maximum_string_utf8_bytes: int = Field(ge=0)
    locator_count: int = Field(ge=0)


class JsonIdentityObservation(BaseModel):
    model_config = _CONFIG

    json_pointer: str = Field(min_length=1, max_length=2_000)
    field_name: str = Field(min_length=1, max_length=500)
    value: str = Field(min_length=1, max_length=2_000)
    normalized_arxiv_id: str | None = Field(default=None, max_length=30)
    matches_item_id: bool


class JsonContentAuditItemReport(BaseModel):
    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    destination: str = Field(min_length=1, max_length=1_000)
    receipt_size_bytes: int = Field(gt=0)
    receipt_sha256: str = Field(pattern=_SHA256)
    observed_size_bytes: int = Field(ge=0)
    observed_sha256: str | None = Field(default=None, pattern=_SHA256)
    exact_bytes_verified: bool
    utf8_verified: bool
    json_verified: bool
    top_level_object_verified: bool
    structural_bounds_verified: bool
    identity_status: JsonIdentityStatus
    identity_observations: tuple[JsonIdentityObservation, ...]
    field_observations: tuple[JsonFieldObservation, ...]
    total_nodes: int = Field(ge=0)
    maximum_observed_depth: int = Field(ge=0)
    external_locator_count: int = Field(ge=0)
    blocker_codes: tuple[str, ...]


class JsonContentAuditReport(BaseModel):
    """Content-derived schema evidence; never a corpus admission or projection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str
    approval_sha256: str = Field(pattern=_SHA256)
    project_id: str
    request_id: str
    request_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    auditor_id: Literal["scitaste-json-content-audit-v1"]
    auditor_implementation_sha256: str = Field(pattern=_SHA256)
    audited_at: datetime
    item_count: int = Field(gt=0)
    observed_total_bytes: int = Field(ge=0)
    exact_inventory_verified: bool
    exact_bytes_verified: bool
    all_json_verified: bool
    all_structural_bounds_verified: bool
    all_embedded_identities_verified: bool
    ready_for_source_admission_proposal: bool
    items: tuple[JsonContentAuditItemReport, ...]
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
            raise ValueError("JSON content-audit timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def report_is_derived(self) -> JsonContentAuditReport:
        if self.item_count != len(self.items):
            raise ValueError("JSON content-audit item count differs from its inventory")
        if self.observed_total_bytes != sum(item.observed_size_bytes for item in self.items):
            raise ValueError("JSON content-audit byte count differs from its inventory")
        expected_ready = (
            self.exact_inventory_verified
            and self.exact_bytes_verified
            and self.all_json_verified
            and self.all_structural_bounds_verified
            and self.all_embedded_identities_verified
            and not self.blocker_codes
        )
        if self.ready_for_source_admission_proposal != expected_ready:
            raise ValueError("JSON content-audit readiness differs from its evidence")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def approve_json_content_audit(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    *,
    confirmed_request_sha256: str,
    confirmed_receipt_sha256: str,
    approved_by: str,
    approved_at: datetime,
    maximum_json_depth: int = 32,
    maximum_container_items: int = 100_000,
    maximum_nodes_per_item: int = 500_000,
    maximum_string_utf8_bytes: int = 4 * 1_048_576,
    identity_field_names: tuple[str, ...] = (
        "arxiv_id",
        "paper_arxiv_id",
        "paper_id",
    ),
) -> JsonContentAuditApproval:
    """Bind explicit local-content authority to one approved request and receipt."""

    source_request = request.request
    source_receipt = receipt.receipt
    if approved_at.utcoffset() is None:
        raise ValueError("JSON content-audit approval timestamp must include a timezone")
    if confirmed_request_sha256 != source_request.request_sha256:
        raise ValueError("confirmed request hash does not match the acquisition request")
    if confirmed_receipt_sha256 != source_receipt.receipt_sha256:
        raise ValueError("confirmed receipt hash does not match the acquisition receipt")
    if (
        not source_request.approval.approved
        or source_request.approval.request_sha256 != source_request.request_sha256
    ):
        raise ValueError("local content audit requires an explicitly approved acquisition request")
    if source_receipt.request_id != source_request.request_id:
        raise ValueError("acquisition receipt belongs to another request")
    if source_receipt.request_sha256 != source_request.request_sha256:
        raise ValueError("acquisition receipt binds another request hash")
    requested_ids = tuple(item.item_id for item in source_request.items)
    received_ids = tuple(item.item_id for item in source_receipt.items)
    if requested_ids != received_ids:
        raise ValueError("acquisition request and receipt item order or identity differs")
    if source_receipt.destination_root != source_request.destination_root:
        raise ValueError("acquisition request and receipt destination roots differ")
    if approved_at < source_receipt.acquired_at:
        raise ValueError("local content access cannot be approved before acquisition")
    if any(item.media_type != "application/json" for item in source_request.items):
        raise ValueError("JSON content audit accepts only application/json acquisition items")
    return JsonContentAuditApproval(
        approval_id=f"{source_request.request_id}-content-audit-v1",
        project_id=source_request.project_id,
        request_id=source_request.request_id,
        request_file_sha256=request.file_sha256,
        request_sha256=source_request.request_sha256,
        receipt_file_sha256=receipt.file_sha256,
        receipt_sha256=source_receipt.receipt_sha256,
        auditor_id="scitaste-json-content-audit-v1",
        auditor_implementation_sha256=_module_sha256(),
        approved_by=approved_by,
        approved_at=approved_at,
        scope="local-bounded-json-structure-and-identity-audit-only",
        expected_item_ids=requested_ids,
        maximum_json_depth=maximum_json_depth,
        maximum_container_items=maximum_container_items,
        maximum_nodes_per_item=maximum_nodes_per_item,
        maximum_string_utf8_bytes=maximum_string_utf8_bytes,
        identity_field_names=identity_field_names,
    )


def save_json_content_audit_approval(
    approval: JsonContentAuditApproval,
    path: str | Path,
) -> Path:
    return _write_new_json(path, approval.model_dump_json(indent=2) + "\n")


def load_json_content_audit_approval(path: str | Path) -> JsonContentAuditApprovalInspection:
    resolved, raw, payload = _load_json_mapping(path, "JSON content-audit approval")
    recorded_hash = payload.pop("approval_sha256", None)
    parsed = JsonContentAuditApproval.model_validate(payload)
    if recorded_hash != parsed.approval_sha256:
        raise ValueError("JSON content-audit approval hash mismatch")
    return JsonContentAuditApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=parsed,
    )


def inspect_acquired_json_content(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    approval: JsonContentAuditApprovalInspection,
    *,
    workspace_root: str | Path,
    allow_local_content_read: bool,
    audited_at: datetime,
) -> JsonContentAuditReport:
    """Read only approved local JSON bytes; never resolve links or produce projections."""

    if not allow_local_content_read:
        raise ValueError("JSON content audit requires the explicit local-content-read switch")
    root = Path(workspace_root).resolve(strict=True)
    source_request = request.request
    source_receipt = receipt.receipt
    authority = approval.approval
    _verify_authority_bindings(request, receipt, approval)
    if audited_at.utcoffset() is None:
        raise ValueError("JSON content-audit timestamp must include a timezone")
    if audited_at < authority.approved_at:
        raise ValueError("JSON content audit cannot precede its content-access approval")

    raw_root = _resolve_beneath(root, source_receipt.destination_root)
    global_blockers: list[str] = []
    inventory_verified = True
    if raw_root is None or raw_root.is_symlink() or not raw_root.is_dir():
        global_blockers.append("raw-root-unavailable")
        inventory_verified = False
    expected_paths = {item.destination for item in source_receipt.items}
    if raw_root is not None and raw_root.is_dir() and not raw_root.is_symlink():
        observed_files = {
            path.relative_to(raw_root).as_posix()
            for path in raw_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        observed_symlinks = {
            path.relative_to(raw_root).as_posix()
            for path in raw_root.rglob("*")
            if path.is_symlink()
        }
        if observed_files != expected_paths:
            global_blockers.append("raw-file-inventory-mismatch")
            inventory_verified = False
        if observed_symlinks:
            global_blockers.append("raw-symlink-forbidden")
            inventory_verified = False

    request_items = {item.item_id: item for item in source_request.items}
    reports: list[JsonContentAuditItemReport] = []
    for receipt_item in source_receipt.items:
        path = (
            _resolve_beneath(raw_root, receipt_item.destination) if raw_root is not None else None
        )
        reports.append(
            _inspect_item(
                receipt_item.item_id,
                receipt_item.destination,
                receipt_item.size_bytes,
                receipt_item.sha256,
                request_items[receipt_item.item_id].maximum_bytes,
                path,
                authority,
            )
        )

    exact_bytes = inventory_verified and all(item.exact_bytes_verified for item in reports)
    all_json = all(item.json_verified and item.top_level_object_verified for item in reports)
    all_bounds = all(item.structural_bounds_verified for item in reports)
    all_identities = all(item.identity_status is JsonIdentityStatus.MATCH for item in reports)
    if not authority.require_embedded_identity_match:
        all_identities = True
    for item in reports:
        global_blockers.extend(f"{item.item_id}:{code}" for code in item.blocker_codes)
    blocker_codes = tuple(sorted(set(global_blockers)))
    ready = exact_bytes and all_json and all_bounds and all_identities and not blocker_codes
    return JsonContentAuditReport(
        approval_id=authority.approval_id,
        approval_sha256=authority.approval_sha256,
        project_id=authority.project_id,
        request_id=authority.request_id,
        request_sha256=authority.request_sha256,
        receipt_sha256=authority.receipt_sha256,
        auditor_id=authority.auditor_id,
        auditor_implementation_sha256=authority.auditor_implementation_sha256,
        audited_at=audited_at,
        item_count=len(reports),
        observed_total_bytes=sum(item.observed_size_bytes for item in reports),
        exact_inventory_verified=inventory_verified,
        exact_bytes_verified=exact_bytes,
        all_json_verified=all_json,
        all_structural_bounds_verified=all_bounds,
        all_embedded_identities_verified=all_identities,
        ready_for_source_admission_proposal=ready,
        items=tuple(reports),
        blocker_codes=blocker_codes,
    )


def save_json_content_audit_report(report: JsonContentAuditReport, path: str | Path) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def _verify_authority_bindings(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    approval: JsonContentAuditApprovalInspection,
) -> None:
    source_request = request.request
    source_receipt = receipt.receipt
    authority = approval.approval
    expected = {
        "request_id": source_request.request_id,
        "request_file_sha256": request.file_sha256,
        "request_sha256": source_request.request_sha256,
        "receipt_file_sha256": receipt.file_sha256,
        "receipt_sha256": source_receipt.receipt_sha256,
        "project_id": source_request.project_id,
    }
    observed = {name: getattr(authority, name) for name in expected}
    if observed != expected:
        raise ValueError("JSON content-audit approval bindings have drifted")
    if (
        authority.auditor_id != "scitaste-json-content-audit-v1"
        or authority.auditor_implementation_sha256 != _module_sha256()
    ):
        raise ValueError("JSON content-audit implementation has drifted")
    if tuple(item.item_id for item in source_request.items) != authority.expected_item_ids:
        raise ValueError("JSON content-audit approved item inventory has drifted")
    if tuple(item.item_id for item in source_receipt.items) != authority.expected_item_ids:
        raise ValueError("JSON content-audit receipt inventory has drifted")
    if (
        not source_request.approval.approved
        or source_request.approval.request_sha256 != source_request.request_sha256
        or source_receipt.request_id != source_request.request_id
        or source_receipt.request_sha256 != source_request.request_sha256
        or source_receipt.destination_root != source_request.destination_root
    ):
        raise ValueError("JSON content-audit acquisition chain is invalid")
    if any(item.media_type != "application/json" for item in source_request.items):
        raise ValueError("JSON content audit accepts only application/json acquisition items")


def _inspect_item(
    item_id: str,
    destination: str,
    expected_size: int,
    expected_sha256: str,
    maximum_bytes: int,
    path: Path | None,
    approval: JsonContentAuditApproval,
) -> JsonContentAuditItemReport:
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
    utf8_verified = decoded is not None
    payload = None
    duplicate_free = True
    if decoded is not None:
        try:
            payload = json.loads(
                decoded,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_nonfinite,
            )
        except DuplicateJsonKeyError:
            duplicate_free = False
            blockers.append("duplicate-json-key")
        except (json.JSONDecodeError, RecursionError, ValueError):
            blockers.append("json-invalid")
    json_verified = payload is not None and duplicate_free
    top_level = isinstance(payload, dict)
    if json_verified and not top_level:
        blockers.append("top-level-not-object")

    shapes: dict[str, _MutableShape] = defaultdict(_MutableShape)
    identities: list[JsonIdentityObservation] = []
    state = _WalkState()
    bounded = False
    if top_level:
        try:
            _walk_json(
                payload,
                pointer="/",
                depth=0,
                field_name=None,
                item_id=item_id,
                approval=approval,
                shapes=shapes,
                identities=identities,
                state=state,
            )
            bounded = True
        except JsonStructuralLimitError as exc:
            blockers.append(exc.code)

    matching = [item for item in identities if item.matches_item_id]
    nonmatching = [item for item in identities if not item.matches_item_id]
    identity_status = (
        JsonIdentityStatus.MATCH
        if matching and not nonmatching
        else (
            JsonIdentityStatus.ABSENT
            if not identities
            else (JsonIdentityStatus.MISMATCH if not matching else JsonIdentityStatus.AMBIGUOUS)
        )
    )
    if approval.require_embedded_identity_match and identity_status is not JsonIdentityStatus.MATCH:
        blockers.append(f"embedded-identity-{identity_status.value}")
    observations = tuple(
        JsonFieldObservation(
            json_pointer=pointer,
            observed_types=tuple(sorted(shape.types)),
            occurrences=shape.occurrences,
            maximum_string_utf8_bytes=shape.maximum_string_utf8_bytes,
            locator_count=shape.locator_count,
        )
        for pointer, shape in sorted(shapes.items())
    )
    return JsonContentAuditItemReport(
        item_id=item_id,
        destination=destination,
        receipt_size_bytes=expected_size,
        receipt_sha256=expected_sha256,
        observed_size_bytes=observed_size,
        observed_sha256=observed_sha256,
        exact_bytes_verified=exact,
        utf8_verified=utf8_verified,
        json_verified=json_verified,
        top_level_object_verified=top_level,
        structural_bounds_verified=bounded,
        identity_status=identity_status,
        identity_observations=tuple(identities),
        field_observations=observations,
        total_nodes=state.nodes,
        maximum_observed_depth=state.maximum_depth,
        external_locator_count=state.locators,
        blocker_codes=tuple(sorted(set(blockers))),
    )


class DuplicateJsonKeyError(ValueError):
    pass


class JsonStructuralLimitError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _MutableShape:
    def __init__(self) -> None:
        self.types: set[str] = set()
        self.occurrences = 0
        self.maximum_string_utf8_bytes = 0
        self.locator_count = 0


class _WalkState:
    def __init__(self) -> None:
        self.nodes = 0
        self.maximum_depth = 0
        self.locators = 0


def _walk_json(
    value: object,
    *,
    pointer: str,
    depth: int,
    field_name: str | None,
    item_id: str,
    approval: JsonContentAuditApproval,
    shapes: dict[str, _MutableShape],
    identities: list[JsonIdentityObservation],
    state: _WalkState,
) -> None:
    state.nodes += 1
    state.maximum_depth = max(state.maximum_depth, depth)
    if depth > approval.maximum_json_depth:
        raise JsonStructuralLimitError("maximum-json-depth-exceeded")
    if state.nodes > approval.maximum_nodes_per_item:
        raise JsonStructuralLimitError("maximum-json-nodes-exceeded")
    kind = _json_type(value)
    shape = shapes[pointer]
    shape.types.add(kind)
    shape.occurrences += 1
    if isinstance(value, str):
        length = len(value.encode("utf-8"))
        shape.maximum_string_utf8_bytes = max(shape.maximum_string_utf8_bytes, length)
        if length > approval.maximum_string_utf8_bytes:
            raise JsonStructuralLimitError("maximum-json-string-bytes-exceeded")
        if _is_external_locator(value):
            shape.locator_count += 1
            state.locators += 1
        if field_name is not None and _normalize_field_name(field_name) in {
            _normalize_field_name(item) for item in approval.identity_field_names
        }:
            match = _ARXIV_ID.fullmatch(value.strip())
            normalized = match.group(1) if match else None
            identities.append(
                JsonIdentityObservation(
                    json_pointer=pointer,
                    field_name=field_name,
                    value=value[:2_000],
                    normalized_arxiv_id=normalized,
                    matches_item_id=normalized == item_id,
                )
            )
        return
    if isinstance(value, dict):
        if len(value) > approval.maximum_container_items:
            raise JsonStructuralLimitError("maximum-json-container-items-exceeded")
        for key, child in value.items():
            if len(key.encode("utf-8")) > approval.maximum_string_utf8_bytes:
                raise JsonStructuralLimitError("maximum-json-key-bytes-exceeded")
            child_pointer = _join_pointer(pointer, _escape_pointer(key))
            if len(child_pointer) > 2_000:
                raise JsonStructuralLimitError("maximum-json-pointer-length-exceeded")
            _walk_json(
                child,
                pointer=child_pointer,
                depth=depth + 1,
                field_name=key,
                item_id=item_id,
                approval=approval,
                shapes=shapes,
                identities=identities,
                state=state,
            )
    elif isinstance(value, list):
        if len(value) > approval.maximum_container_items:
            raise JsonStructuralLimitError("maximum-json-container-items-exceeded")
        for child in value:
            _walk_json(
                child,
                pointer=_join_pointer(pointer, "*"),
                depth=depth + 1,
                field_name=field_name,
                item_id=item_id,
                approval=approval,
                shapes=shapes,
                identities=identities,
                state=state,
            )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _json_type(value: object) -> str:
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
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _is_external_locator(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _join_pointer(parent: str, child: str) -> str:
    return f"/{child}" if parent == "/" else f"{parent}/{child}"


def _escape_pointer(value: str) -> str:
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
        payload = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError, ValueError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, raw, payload


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
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise FileExistsError(target) from exc
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
    "JsonContentAuditApproval",
    "JsonContentAuditApprovalInspection",
    "JsonContentAuditItemReport",
    "JsonContentAuditReport",
    "JsonFieldObservation",
    "JsonIdentityObservation",
    "JsonIdentityStatus",
    "approve_json_content_audit",
    "inspect_acquired_json_content",
    "load_json_content_audit_approval",
    "save_json_content_audit_approval",
    "save_json_content_audit_report",
]
