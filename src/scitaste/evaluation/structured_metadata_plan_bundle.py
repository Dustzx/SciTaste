"""Project-level bundle for no-read structured-metadata audit plans."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation import structured_metadata_audit as audit_module
from scitaste.evaluation.acquisition import (
    AcquisitionReceiptInspection,
    load_dataset_acquisition_receipt,
)
from scitaste.evaluation.structured_metadata_audit import (
    StructuredMetadataAuditPlanInspection,
    StructuredMetadataFormat,
    load_structured_metadata_audit_plan,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 4 * 1_048_576


class StructuredMetadataAuditPlanBundleItem(BaseModel):
    """One exact no-read plan exposed at project scope."""

    model_config = _CONFIG

    plan_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    plan_locator: str = Field(min_length=1, max_length=1_000)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    receipt_locator: str = Field(min_length=1, max_length=1_000)
    receipt_file_sha256: str = Field(pattern=_SHA256)
    auditor_implementation_sha256: str = Field(pattern=_SHA256)
    auditor_implementation_current: bool
    expected_item_count: int = Field(gt=0, le=500)
    formats: tuple[StructuredMetadataFormat, ...] = Field(min_length=1, max_length=2)
    maximum_source_bytes_per_item: int = Field(gt=0)
    maximum_total_source_bytes: int = Field(gt=0)
    ready_for_owner_approval: bool
    source_content_read: Literal[False] = False
    owner_approval_recorded: Literal[False] = False
    authorizes_local_content_read: Literal[False] = False
    authorizes_projection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def locator_and_readiness_are_closed(self) -> StructuredMetadataAuditPlanBundleItem:
        for locator in (self.plan_locator, self.receipt_locator):
            pure = PurePosixPath(locator)
            if (
                pure.is_absolute()
                or not pure.parts
                or any(part in {"", ".", ".."} for part in pure.parts)
            ):
                raise ValueError("metadata audit plan locators must be normalized and relative")
        if self.ready_for_owner_approval != self.auditor_implementation_current:
            raise ValueError("metadata audit plan readiness differs from implementation identity")
        return self


class StructuredMetadataAuditPlanBundle(BaseModel):
    """A self-hashed project view that grants no content or execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    bundle_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    run_id: str = Field(pattern=_ID)
    plans: tuple[StructuredMetadataAuditPlanBundleItem, ...] = Field(
        min_length=1,
        max_length=50,
    )
    plan_count: int = Field(gt=0)
    expected_item_count: int = Field(gt=0)
    maximum_total_source_bytes: int = Field(gt=0)
    status: Literal["awaiting_content_read_approval", "implementation_drift"]
    next_gate: Literal[
        "approve_exact_local_structured_metadata_read",
        "regenerate_plans_against_current_auditor",
    ]
    source_content_read: Literal[False] = False
    owner_approval_recorded: Literal[False] = False
    network_access_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    authorizes_local_content_read: Literal[False] = False
    authorizes_projection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def aggregate_is_derived(self) -> StructuredMetadataAuditPlanBundle:
        if self.plan_count != len(self.plans):
            raise ValueError("metadata audit plan bundle count differs")
        if self.expected_item_count != sum(item.expected_item_count for item in self.plans):
            raise ValueError("metadata audit plan bundle item count differs")
        if self.maximum_total_source_bytes != sum(
            item.maximum_total_source_bytes for item in self.plans
        ):
            raise ValueError("metadata audit plan bundle byte ceiling differs")
        request_ids = [item.request_id for item in self.plans]
        if request_ids != sorted(set(request_ids)):
            raise ValueError("metadata audit plan bundle requests must be sorted and unique")
        ready = all(item.ready_for_owner_approval for item in self.plans)
        if self.status != ("awaiting_content_read_approval" if ready else "implementation_drift"):
            raise ValueError("metadata audit plan bundle status differs from its plans")
        expected_gate = (
            "approve_exact_local_structured_metadata_read"
            if ready
            else "regenerate_plans_against_current_auditor"
        )
        if self.next_gate != expected_gate:
            raise ValueError("metadata audit plan bundle next gate differs from its plans")
        return self

    @computed_field
    @property
    def bundle_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"bundle_sha256"}))


class StructuredMetadataAuditPlanBundleInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    bundle: StructuredMetadataAuditPlanBundle


def build_structured_metadata_audit_plan_bundle(
    *,
    project_id: str,
    run_id: str,
    project_root: str | Path,
    plan_paths: Sequence[str | Path],
    receipt_paths: Sequence[str | Path],
) -> StructuredMetadataAuditPlanBundle:
    """Bind existing no-read plans without opening their acquired source files."""

    root = Path(project_root).resolve(strict=True)
    plans = tuple(load_structured_metadata_audit_plan(path) for path in plan_paths)
    if not plans:
        raise ValueError("metadata audit plan bundle requires at least one plan")
    receipts = tuple(load_dataset_acquisition_receipt(path) for path in receipt_paths)
    receipt_by_request = {item.receipt.request_id: item for item in receipts}
    if len(receipt_by_request) != len(receipts):
        raise ValueError("metadata audit plan bundle receipts must be unique")
    if set(receipt_by_request) != {item.plan.request_id for item in plans}:
        raise ValueError("metadata audit plan bundle receipts do not cover its plans")
    items = tuple(
        sorted(
            (
                _bundle_item(
                    root,
                    project_id,
                    inspection,
                    receipt_by_request[inspection.plan.request_id],
                )
                for inspection in plans
            ),
            key=lambda item: item.request_id,
        )
    )
    ready = all(item.ready_for_owner_approval for item in items)
    return StructuredMetadataAuditPlanBundle(
        bundle_id=f"{run_id}-bundle",
        project_id=project_id,
        run_id=run_id,
        plans=items,
        plan_count=len(items),
        expected_item_count=sum(item.expected_item_count for item in items),
        maximum_total_source_bytes=sum(item.maximum_total_source_bytes for item in items),
        status=("awaiting_content_read_approval" if ready else "implementation_drift"),
        next_gate=(
            "approve_exact_local_structured_metadata_read"
            if ready
            else "regenerate_plans_against_current_auditor"
        ),
    )


def save_structured_metadata_audit_plan_bundle(
    bundle: StructuredMetadataAuditPlanBundle,
    path: str | Path,
) -> Path:
    return _write_new_json(path, bundle.model_dump_json(indent=2) + "\n")


def load_structured_metadata_audit_plan_bundle(
    path: str | Path,
    *,
    project_root: str | Path,
) -> StructuredMetadataAuditPlanBundleInspection:
    source = Path(path)
    if source.is_symlink():
        raise ValueError("metadata audit plan bundle cannot be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("metadata audit plan bundle must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise ValueError("metadata audit plan bundle must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("metadata audit plan bundle must contain a JSON object")
    recorded = payload.pop("bundle_sha256", None)
    bundle = StructuredMetadataAuditPlanBundle.model_validate(payload)
    if recorded != bundle.bundle_sha256:
        raise ValueError("metadata audit plan bundle hash mismatch")
    rebuilt = build_structured_metadata_audit_plan_bundle(
        project_id=bundle.project_id,
        run_id=bundle.run_id,
        project_root=project_root,
        plan_paths=[Path(project_root) / item.plan_locator for item in bundle.plans],
        receipt_paths=[Path(project_root) / item.receipt_locator for item in bundle.plans],
    )
    if rebuilt != bundle:
        raise ValueError("metadata audit plan bundle bindings have drifted")
    return StructuredMetadataAuditPlanBundleInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        bundle=bundle,
    )


def _bundle_item(
    root: Path,
    project_id: str,
    inspection: StructuredMetadataAuditPlanInspection,
    receipt: AcquisitionReceiptInspection,
) -> StructuredMetadataAuditPlanBundleItem:
    if inspection.plan.project_id != project_id:
        raise ValueError("metadata audit plan belongs to another project")
    resolved = inspection.path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("metadata audit plan must be inside the project root")
    locator = resolved.relative_to(root).as_posix()
    receipt_resolved = receipt.path.resolve(strict=True)
    if not receipt_resolved.is_relative_to(root):
        raise ValueError("metadata audit receipt must be inside the project root")
    if (
        receipt.receipt.request_id != inspection.plan.request_id
        or receipt.receipt.request_sha256 != inspection.plan.request_sha256
        or receipt.receipt.receipt_sha256 != inspection.plan.receipt_sha256
        or receipt.file_sha256 != inspection.plan.receipt_file_sha256
        or tuple(item.item_id for item in receipt.receipt.items)
        != inspection.plan.expected_item_ids
    ):
        raise ValueError("metadata audit plan and acquisition receipt differ")
    current_implementation = hashlib.sha256(Path(audit_module.__file__).read_bytes()).hexdigest()
    implementation_current = inspection.plan.auditor_implementation_sha256 == current_implementation
    return StructuredMetadataAuditPlanBundleItem(
        plan_id=inspection.plan.plan_id,
        request_id=inspection.plan.request_id,
        plan_locator=locator,
        plan_file_sha256=inspection.file_sha256,
        plan_sha256=inspection.plan.plan_sha256,
        request_sha256=inspection.plan.request_sha256,
        receipt_sha256=inspection.plan.receipt_sha256,
        receipt_locator=receipt_resolved.relative_to(root).as_posix(),
        receipt_file_sha256=receipt.file_sha256,
        auditor_implementation_sha256=inspection.plan.auditor_implementation_sha256,
        auditor_implementation_current=implementation_current,
        expected_item_count=len(inspection.plan.expected_item_ids),
        formats=inspection.plan.formats,
        maximum_source_bytes_per_item=inspection.plan.maximum_source_bytes_per_item,
        maximum_total_source_bytes=inspection.plan.maximum_total_source_bytes,
        ready_for_owner_approval=implementation_current,
    )


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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


__all__ = [
    "StructuredMetadataAuditPlanBundle",
    "StructuredMetadataAuditPlanBundleInspection",
    "StructuredMetadataAuditPlanBundleItem",
    "build_structured_metadata_audit_plan_bundle",
    "load_structured_metadata_audit_plan_bundle",
    "save_structured_metadata_audit_plan_bundle",
]
