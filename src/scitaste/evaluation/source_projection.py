"""Approval-gated projection of admitted JSON sources into model-visible evidence.

The projection is the common source representation for the raw-RAG arm and the
input from which an abstracted-Taste candidate may be produced.  This module
therefore freezes source identity and visible bytes before either treatment is
constructed; it never calls a model or authorizes an experiment.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unicodedata
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.acquisition import (
    AcquisitionReceiptInspection,
    AcquisitionRequestInspection,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.json_content_audit import JsonContentAuditReport
from scitaste.evaluation.source_admission import (
    SourceAdmissionProposal,
    SourceAdmissionReport,
    SourceAdmissionVerdict,
    load_source_admission_proposal,
)
from scitaste.evaluation.taste_corpus_pair import OutcomeInformationAvailability

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_OUTPUT_NAME = r"^[a-z][a-z0-9_]{0,99}$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576
_MAX_SOURCE_BYTES = 64 * 1_048_576
_MAX_TOTAL_PROJECTION_BYTES = 1_073_741_824
_SCALAR_TYPES = frozenset({"null", "boolean", "integer", "number", "string"})
_TREATMENT_LABELS = (
    "raw-source-rag",
    "raw_source_rag",
    "matched-abstracted-taste",
    "matched_abstracted_taste",
    "mismatched-taste",
    "mismatched_taste",
    "full-scitaste",
    "full_scitaste",
    "native-base",
    "native_base",
)


class ProjectionSemanticRole(StrEnum):
    """Scientific role of one explicitly selected source field."""

    PROBLEM_CONTEXT = "problem_context"
    ALTERNATIVE = "alternative"
    SCIENTIFIC_ACTION = "scientific_action"
    JUSTIFICATION = "justification"
    EVIDENCE = "evidence"
    LIMITATION = "limitation"
    OUTCOME = "outcome"
    SOURCE_METADATA = "source_metadata"


class SourceProjectionField(BaseModel):
    """One terminal JSON pointer admitted to the model-visible projection."""

    model_config = _CONFIG

    output_name: str = Field(pattern=_OUTPUT_NAME)
    json_pointer: str = Field(min_length=1, max_length=2_000)
    semantic_role: ProjectionSemanticRole
    required: Literal[True] = True

    @field_validator("json_pointer")
    @classmethod
    def pointer_is_canonical(cls, value: str) -> str:
        _pointer_tokens(value)
        if value == "/":
            raise ValueError("source projection cannot select the whole JSON document")
        return value


class SourceProjectionControlBinding(BaseModel):
    """Exact control artifact used to derive a projection plan."""

    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)


class SourceProjectionItemPlan(BaseModel):
    """One admitted source and its immutable raw-byte location."""

    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    source_locator: str = Field(min_length=1, max_length=2_000)
    raw_destination: str = Field(min_length=1, max_length=1_000)
    source_content_sha256: str = Field(pattern=_SHA256)
    source_size_bytes: int = Field(gt=0, le=_MAX_SOURCE_BYTES)

    @field_validator("raw_destination")
    @classmethod
    def destination_is_relative(cls, value: str) -> str:
        _validate_relative_path(value, "raw source destination")
        return value


class SourceProjectionPlan(BaseModel):
    """No-read plan fixing every byte and field that may enter a projection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    created_at: datetime
    request: SourceProjectionControlBinding
    receipt: SourceProjectionControlBinding
    content_audit_report: SourceProjectionControlBinding
    source_admission_proposal: SourceProjectionControlBinding
    source_admission_report: SourceProjectionControlBinding
    raw_source_root: str = Field(min_length=1, max_length=2_000)
    projection_output_root: str = Field(min_length=1, max_length=2_000)
    fields: tuple[SourceProjectionField, ...] = Field(min_length=1, max_length=100)
    forbidden_json_pointers: tuple[str, ...] = Field(min_length=1, max_length=500)
    forbidden_model_visible_exact_strings: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=10_000,
    )
    outcome_information_availability: OutcomeInformationAvailability
    items: tuple[SourceProjectionItemPlan, ...] = Field(min_length=1, max_length=10_000)
    maximum_projection_bytes_per_item: int = Field(gt=0, le=16 * 1_048_576)
    maximum_total_projection_bytes: int = Field(gt=0, le=_MAX_TOTAL_PROJECTION_BYTES)
    serialization: Literal["canonical-json-utf8-nfc-v1"] = "canonical-json-utf8-nfc-v1"
    external_locator_text_allowed: Literal[False] = False
    raw_rag_and_abstraction_share_projection_bytes: Literal[True] = True
    source_selection_frozen_before_projection: Literal[True] = True
    raw_source_content_read: Literal[False] = False
    projection_performed: Literal[False] = False
    authorizes_local_source_read: Literal[False] = False
    authorizes_projection_write: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def creation_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("source-projection plan timestamp must include a timezone")
        return value

    @field_validator("raw_source_root", "projection_output_root")
    @classmethod
    def roots_are_relative(cls, value: str) -> str:
        _validate_relative_path(value, "source-projection root")
        return value

    @field_validator("forbidden_json_pointers")
    @classmethod
    def forbidden_pointers_are_valid(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _pointer_tokens(value)
        return values

    @model_validator(mode="after")
    def selection_is_closed(self) -> SourceProjectionPlan:
        _require_unique((field.output_name for field in self.fields), "projection output names")
        _require_unique((field.json_pointer for field in self.fields), "projection pointers")
        _require_unique(self.forbidden_json_pointers, "forbidden projection pointers")
        _require_unique((item.item_id for item in self.items), "projection item IDs")
        _require_unique((item.source_id for item in self.items), "projection source IDs")
        if self.maximum_total_projection_bytes < self.maximum_projection_bytes_per_item:
            raise ValueError("total projection ceiling must cover at least one item")
        raw_parts = PurePosixPath(self.raw_source_root).parts
        output_parts = PurePosixPath(self.projection_output_root).parts
        common = min(len(raw_parts), len(output_parts))
        if raw_parts[:common] == output_parts[:common]:
            raise ValueError("raw source and projection output roots must not overlap")
        if any(
            _pointer_overlaps(field.json_pointer, forbidden)
            for field in self.fields
            for forbidden in self.forbidden_json_pointers
        ):
            raise ValueError("a selected projection pointer overlaps a forbidden pointer")
        if self.outcome_information_availability is OutcomeInformationAvailability.WITHHELD:
            if any(field.semantic_role is ProjectionSemanticRole.OUTCOME for field in self.fields):
                raise ValueError("withheld-outcome projection cannot select an outcome field")
        folded = [item.casefold() for item in self.forbidden_model_visible_exact_strings]
        if any(not item for item in folded) or len(folded) != len(set(folded)):
            raise ValueError("forbidden model-visible strings must be non-empty and unique")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class SourceProjectionPlanInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    plan: SourceProjectionPlan


class SourceProjectionApproval(BaseModel):
    """Exact owner authority for one local read-and-projection transaction."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    projector_id: Literal["scitaste-source-projector-v1"]
    projector_implementation_sha256: str = Field(pattern=_SHA256)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    scope: Literal["exact-admitted-local-json-field-projection-only"]
    expected_source_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    authorizes_local_source_read: Literal[True] = True
    authorizes_projection_write: Literal[True] = True
    authorizes_network_access: Literal[False] = False
    authorizes_link_resolution: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("source-projection approval timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def source_inventory_is_unique(self) -> SourceProjectionApproval:
        _require_unique(self.expected_source_ids, "approved projection source IDs")
        return self

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class SourceProjectionApprovalInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    approval: SourceProjectionApproval


class SourceProjectionItemReceipt(BaseModel):
    """Identity and parity evidence for one materialized source projection."""

    model_config = _CONFIG

    item_id: str
    source_id: str
    source_group_id: str
    source_locator: str
    source_content_sha256: str = Field(pattern=_SHA256)
    source_size_bytes: int = Field(gt=0)
    projection_path: str
    projection_sha256: str = Field(pattern=_SHA256)
    projection_size_bytes: int = Field(gt=0)
    selected_json_pointers: tuple[str, ...] = Field(min_length=1)
    raw_rag_projection_sha256: str = Field(pattern=_SHA256)
    abstraction_input_projection_sha256: str = Field(pattern=_SHA256)
    raw_rag_and_abstraction_bytes_identical: Literal[True] = True
    condition_identity_absent: Literal[True] = True
    held_out_identity_absent: Literal[True] = True
    external_locator_text_absent: Literal[True] = True

    @model_validator(mode="after")
    def treatment_inputs_share_source_bytes(self) -> SourceProjectionItemReceipt:
        expected = self.projection_sha256
        if {self.raw_rag_projection_sha256, self.abstraction_input_projection_sha256} != {expected}:
            raise ValueError("raw RAG and abstraction inputs must bind the same projection")
        return self


class SourceProjectionReceipt(BaseModel):
    """Projection receipt; tokenization and all model use remain later gates."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    plan_file_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    approval_id: str
    approval_file_sha256: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    project_id: str
    projector_id: Literal["scitaste-source-projector-v1"]
    projector_implementation_sha256: str = Field(pattern=_SHA256)
    materialized_at: datetime
    projection_output_root: str
    item_count: int = Field(gt=0)
    total_projection_bytes: int = Field(gt=0)
    outcome_information_availability: OutcomeInformationAvailability
    items: tuple[SourceProjectionItemReceipt, ...] = Field(min_length=1)
    exact_source_bytes_verified: Literal[True] = True
    exact_field_allowlist_applied: Literal[True] = True
    forbidden_fields_excluded: Literal[True] = True
    treatment_source_parity_verified: Literal[True] = True
    ready_for_tokenization: Literal[True] = True
    tokenization_performed: Literal[False] = False
    ready_for_abstraction_resource_proposal: Literal[False] = False
    source_files_modified: Literal[False] = False
    network_access_performed: Literal[False] = False
    linked_assets_resolved: Literal[False] = False
    model_calls_performed: Literal[False] = False
    human_review_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @field_validator("materialized_at")
    @classmethod
    def materialization_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("source-projection materialization timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def receipt_matches_items(self) -> SourceProjectionReceipt:
        if self.item_count != len(self.items):
            raise ValueError("source-projection receipt item count differs")
        if self.total_projection_bytes != sum(item.projection_size_bytes for item in self.items):
            raise ValueError("source-projection receipt byte count differs")
        _require_unique((item.source_id for item in self.items), "projected source IDs")
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


def build_source_projection_plan(
    *,
    plan_id: str,
    approved_request_path: str | Path,
    receipt_path: str | Path,
    content_audit_report_path: str | Path,
    source_admission_proposal_path: str | Path,
    source_admission_report_path: str | Path,
    workspace_root: str | Path,
    projection_output_root: str,
    fields: tuple[SourceProjectionField, ...],
    forbidden_json_pointers: tuple[str, ...],
    forbidden_model_visible_exact_strings: tuple[str, ...],
    outcome_information_availability: OutcomeInformationAvailability,
    created_at: datetime,
    maximum_projection_bytes_per_item: int = 2 * 1_048_576,
    maximum_total_projection_bytes: int = 32 * 1_048_576,
) -> SourceProjectionPlan:
    """Build a complete plan from control evidence without opening source bodies."""

    root = Path(workspace_root).resolve(strict=True)
    request = load_dataset_acquisition_request(approved_request_path)
    receipt = load_dataset_acquisition_receipt(receipt_path)
    audit_path, audit_file_sha, audit = _load_audit_report(content_audit_report_path)
    admission = load_source_admission_proposal(source_admission_proposal_path)
    admission_report_path_resolved, admission_report_file_sha, admission_report = (
        _load_admission_report(source_admission_report_path)
    )
    _verify_projection_chain(request, receipt, audit, admission.proposal, admission_report)
    if not admission_report.ready_for_projection_proposal:
        raise ValueError("source-admission report is not ready for a projection proposal")
    if created_at.utcoffset() is None:
        raise ValueError("source-projection plan timestamp must include a timezone")
    _validate_relative_path(projection_output_root, "projection output root")

    request_items = {item.item_id: item for item in request.request.items}
    receipt_items = {item.item_id: item for item in receipt.receipt.items}
    audit_items = {item.item_id: item for item in audit.items}
    proposal_entries = {item.source_id: item for item in admission.proposal.entries}
    report_items = {item.source_id: item for item in admission_report.items}
    selected_source_ids = admission_report.admitted_source_ids
    if set(selected_source_ids) != {
        source_id
        for source_id, report in report_items.items()
        if report.disposition is SourceAdmissionVerdict.ADMIT
    }:
        raise ValueError("source-admission admitted ledger is inconsistent")

    plan_items: list[SourceProjectionItemPlan] = []
    for source_id in selected_source_ids:
        entry = proposal_entries.get(source_id)
        report_item = report_items.get(source_id)
        if entry is None or report_item is None:
            raise ValueError(f"admitted source {source_id!r} is absent from the frozen population")
        audited = audit_items.get(entry.item_id)
        requested = request_items.get(entry.item_id)
        received = receipt_items.get(entry.item_id)
        if audited is None or requested is None or received is None:
            raise ValueError(f"admitted source {source_id!r} is absent from the acquisition chain")
        if not (
            audited.exact_bytes_verified
            and audited.observed_sha256 == entry.source_content_sha256 == received.sha256
            and audited.observed_size_bytes == received.size_bytes
            and audited.destination == received.destination == requested.destination
        ):
            raise ValueError(f"admitted source {source_id!r} byte binding has drifted")
        observed = {item.json_pointer: item for item in audited.field_observations}
        for field in fields:
            shape = observed.get(field.json_pointer)
            if shape is None:
                raise ValueError(
                    f"projection pointer {field.json_pointer!r} is absent from {source_id!r}"
                )
            if not set(shape.observed_types).issubset(_SCALAR_TYPES):
                raise ValueError(
                    f"projection pointer {field.json_pointer!r} is not terminal scalar data"
                )
            if shape.locator_count:
                raise ValueError(
                    f"projection pointer {field.json_pointer!r} contains external locator text"
                )
        plan_items.append(
            SourceProjectionItemPlan(
                item_id=entry.item_id,
                source_id=entry.source_id,
                source_group_id=entry.isolation.source_group_id,
                source_locator=entry.locator,
                raw_destination=audited.destination,
                source_content_sha256=entry.source_content_sha256,
                source_size_bytes=audited.observed_size_bytes,
            )
        )

    observed_forbidden = {
        pointer
        for audited in audit.items
        for pointer in forbidden_json_pointers
        if pointer in {field.json_pointer for field in audited.field_observations}
    }
    if observed_forbidden != set(forbidden_json_pointers):
        missing = sorted(set(forbidden_json_pointers) - observed_forbidden)
        raise ValueError(f"forbidden projection pointers were not observed by audit: {missing}")

    forbidden_strings = tuple(
        dict.fromkeys(
            (
                *forbidden_model_visible_exact_strings,
                *admission.proposal.held_out_source_group_ids,
                *_TREATMENT_LABELS,
            )
        )
    )
    return SourceProjectionPlan(
        plan_id=plan_id,
        project_id=request.request.project_id,
        created_at=created_at,
        request=_control_binding(
            request.path,
            request.file_sha256,
            request.request.request_sha256,
            root,
        ),
        receipt=_control_binding(
            receipt.path,
            receipt.file_sha256,
            receipt.receipt.receipt_sha256,
            root,
        ),
        content_audit_report=_control_binding(
            audit_path,
            audit_file_sha,
            audit.report_sha256,
            root,
        ),
        source_admission_proposal=_control_binding(
            admission.path,
            admission.file_sha256,
            admission.proposal.proposal_sha256,
            root,
        ),
        source_admission_report=_control_binding(
            admission_report_path_resolved,
            admission_report_file_sha,
            admission_report.report_sha256,
            root,
        ),
        raw_source_root=receipt.receipt.destination_root,
        projection_output_root=projection_output_root,
        fields=fields,
        forbidden_json_pointers=forbidden_json_pointers,
        forbidden_model_visible_exact_strings=forbidden_strings,
        outcome_information_availability=outcome_information_availability,
        items=tuple(plan_items),
        maximum_projection_bytes_per_item=maximum_projection_bytes_per_item,
        maximum_total_projection_bytes=maximum_total_projection_bytes,
    )


def save_source_projection_plan(plan: SourceProjectionPlan, path: str | Path) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def load_source_projection_plan(path: str | Path) -> SourceProjectionPlanInspection:
    resolved, raw, payload = _load_json_mapping(path, "source-projection plan")
    recorded_hash = payload.pop("plan_sha256", None)
    plan = SourceProjectionPlan.model_validate(payload)
    if recorded_hash != plan.plan_sha256:
        raise ValueError("source-projection plan hash mismatch")
    return SourceProjectionPlanInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        plan=plan,
    )


def approve_source_projection(
    plan: SourceProjectionPlanInspection,
    *,
    confirmed_plan_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> SourceProjectionApproval:
    if confirmed_plan_sha256 != plan.plan.plan_sha256:
        raise ValueError("confirmed source-projection plan hash differs")
    if approved_at.utcoffset() is None:
        raise ValueError("source-projection approval timestamp must include a timezone")
    if approved_at < plan.plan.created_at:
        raise ValueError("source-projection approval cannot predate the plan")
    return SourceProjectionApproval(
        approval_id=f"{plan.plan.plan_id}-approval",
        project_id=plan.plan.project_id,
        plan_file_sha256=plan.file_sha256,
        plan_sha256=plan.plan.plan_sha256,
        projector_id="scitaste-source-projector-v1",
        projector_implementation_sha256=_module_sha256(),
        approved_by=approved_by,
        approved_at=approved_at,
        scope="exact-admitted-local-json-field-projection-only",
        expected_source_ids=tuple(item.source_id for item in plan.plan.items),
    )


def save_source_projection_approval(
    approval: SourceProjectionApproval,
    path: str | Path,
) -> Path:
    return _write_new_json(path, approval.model_dump_json(indent=2) + "\n")


def load_source_projection_approval(path: str | Path) -> SourceProjectionApprovalInspection:
    resolved, raw, payload = _load_json_mapping(path, "source-projection approval")
    recorded_hash = payload.pop("approval_sha256", None)
    approval = SourceProjectionApproval.model_validate(payload)
    if recorded_hash != approval.approval_sha256:
        raise ValueError("source-projection approval hash mismatch")
    return SourceProjectionApprovalInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval,
    )


def materialize_source_projections(
    plan: SourceProjectionPlanInspection,
    approval: SourceProjectionApprovalInspection,
    *,
    workspace_root: str | Path,
    materialized_at: datetime,
    allow_local_source_projection: bool,
) -> SourceProjectionReceipt:
    """Read and project only the exact approved sources and terminal fields."""

    if not allow_local_source_projection:
        raise ValueError("source projection requires the explicit local projection switch")
    root = Path(workspace_root).resolve(strict=True)
    spec = plan.plan
    authority = approval.approval
    _verify_projection_authority(plan, approval)
    if materialized_at.utcoffset() is None:
        raise ValueError("source-projection timestamp must include a timezone")
    if materialized_at < authority.approved_at:
        raise ValueError("source projection cannot predate its approval")
    _revalidate_control_chain(spec, root)

    raw_root = _resolve_beneath(root, spec.raw_source_root, require_exists=True)
    if raw_root is None or raw_root.is_symlink() or not raw_root.is_dir():
        raise ValueError("approved raw source root is unavailable")
    receipt = load_dataset_acquisition_receipt(
        _resolve_control_binding(spec.receipt, root, "acquisition receipt")
    )
    _verify_raw_inventory(raw_root, receipt)

    target = _resolve_beneath(root, spec.projection_output_root, require_exists=False)
    if target is None or target.exists() or target.is_symlink():
        raise FileExistsError(spec.projection_output_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    receipts: list[SourceProjectionItemReceipt] = []
    total_bytes = 0
    try:
        for item in spec.items:
            raw_path = _resolve_beneath(raw_root, item.raw_destination, require_exists=True)
            if raw_path is None or raw_path.is_symlink() or not raw_path.is_file():
                raise ValueError(f"source {item.source_id!r} is unavailable")
            raw = raw_path.read_bytes()
            if len(raw) != item.source_size_bytes:
                raise ValueError(f"source {item.source_id!r} size has drifted")
            if hashlib.sha256(raw).hexdigest() != item.source_content_sha256:
                raise ValueError(f"source {item.source_id!r} hash has drifted")
            payload = _strict_json_object(raw, item.source_id)
            fields = {
                field.output_name: {
                    "semantic_role": field.semantic_role.value,
                    "value": _normalize_json(_select_pointer(payload, field.json_pointer)),
                }
                for field in spec.fields
            }
            visible = {
                "schema_version": "1.0",
                "outcome_information_availability": (spec.outcome_information_availability.value),
                "fields": fields,
            }
            projection = _canonical_json_bytes(visible)
            if len(projection) > spec.maximum_projection_bytes_per_item:
                raise ValueError(f"source {item.source_id!r} projection exceeds its byte ceiling")
            total_bytes += len(projection)
            if total_bytes > spec.maximum_total_projection_bytes:
                raise ValueError("source projections exceed the aggregate byte ceiling")
            decoded = projection.decode("utf-8")
            _verify_visible_exclusions(decoded, spec)
            projection_name = f"{item.source_id}.json"
            projection_path = temporary / projection_name
            projection_path.write_bytes(projection)
            projection_sha = hashlib.sha256(projection).hexdigest()
            receipts.append(
                SourceProjectionItemReceipt(
                    item_id=item.item_id,
                    source_id=item.source_id,
                    source_group_id=item.source_group_id,
                    source_locator=item.source_locator,
                    source_content_sha256=item.source_content_sha256,
                    source_size_bytes=item.source_size_bytes,
                    projection_path=(
                        PurePosixPath(spec.projection_output_root) / projection_name
                    ).as_posix(),
                    projection_sha256=projection_sha,
                    projection_size_bytes=len(projection),
                    selected_json_pointers=tuple(field.json_pointer for field in spec.fields),
                    raw_rag_projection_sha256=projection_sha,
                    abstraction_input_projection_sha256=projection_sha,
                )
            )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return SourceProjectionReceipt(
        plan_id=spec.plan_id,
        plan_file_sha256=plan.file_sha256,
        plan_sha256=spec.plan_sha256,
        approval_id=authority.approval_id,
        approval_file_sha256=approval.file_sha256,
        approval_sha256=authority.approval_sha256,
        project_id=spec.project_id,
        projector_id=authority.projector_id,
        projector_implementation_sha256=authority.projector_implementation_sha256,
        materialized_at=materialized_at,
        projection_output_root=spec.projection_output_root,
        item_count=len(receipts),
        total_projection_bytes=total_bytes,
        outcome_information_availability=spec.outcome_information_availability,
        items=tuple(receipts),
    )


def save_source_projection_receipt(receipt: SourceProjectionReceipt, path: str | Path) -> Path:
    return _write_new_json(path, receipt.model_dump_json(indent=2) + "\n")


def load_source_projection_receipt(path: str | Path) -> SourceProjectionReceipt:
    _, _, payload = _load_json_mapping(path, "source-projection receipt")
    recorded_hash = payload.pop("receipt_sha256", None)
    receipt = SourceProjectionReceipt.model_validate(payload)
    if recorded_hash != receipt.receipt_sha256:
        raise ValueError("source-projection receipt hash mismatch")
    return receipt


def _verify_projection_chain(
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    audit: JsonContentAuditReport,
    proposal: SourceAdmissionProposal,
    admission: SourceAdmissionReport,
) -> None:
    if (
        not request.request.approval.approved
        or request.request.approval.request_sha256 != request.request.request_sha256
    ):
        raise ValueError("source projection requires an approved acquisition request")
    receipt_identity = (
        request.request.request_id,
        request.request.request_sha256,
        receipt.receipt.receipt_sha256,
    )
    if (
        receipt.receipt.request_id,
        receipt.receipt.request_sha256,
        receipt.receipt.receipt_sha256,
    ) != receipt_identity:
        raise ValueError("acquisition request and receipt bindings differ")
    expected = (request.request.project_id, *receipt_identity)
    if (
        audit.project_id,
        audit.request_id,
        audit.request_sha256,
        audit.receipt_sha256,
    ) != expected:
        raise ValueError("content audit is outside the acquisition chain")
    if not audit.ready_for_source_admission_proposal:
        raise ValueError("content audit did not pass")
    if (
        proposal.project_id,
        proposal.request_id,
        proposal.request_sha256,
        proposal.receipt_sha256,
        proposal.content_audit_report_sha256,
    ) != (*expected, audit.report_sha256):
        raise ValueError("source-admission proposal is outside the audit chain")
    if (
        admission.project_id,
        admission.request_id,
        admission.request_sha256,
        admission.receipt_sha256,
        admission.content_audit_report_sha256,
        admission.proposal_sha256,
    ) != (*expected, audit.report_sha256, proposal.proposal_sha256):
        raise ValueError("source-admission report is outside the proposal chain")


def _verify_projection_authority(
    plan: SourceProjectionPlanInspection,
    approval: SourceProjectionApprovalInspection,
) -> None:
    spec = plan.plan
    authority = approval.approval
    if (
        authority.project_id,
        authority.plan_file_sha256,
        authority.plan_sha256,
        authority.expected_source_ids,
    ) != (
        spec.project_id,
        plan.file_sha256,
        spec.plan_sha256,
        tuple(item.source_id for item in spec.items),
    ):
        raise ValueError("source-projection approval bindings have drifted")
    if (
        authority.projector_id != "scitaste-source-projector-v1"
        or authority.projector_implementation_sha256 != _module_sha256()
    ):
        raise ValueError("source-projection implementation has drifted")


def _revalidate_control_chain(spec: SourceProjectionPlan, root: Path) -> None:
    request_path = _resolve_control_binding(spec.request, root, "acquisition request")
    receipt_path = _resolve_control_binding(spec.receipt, root, "acquisition receipt")
    audit_path = _resolve_control_binding(spec.content_audit_report, root, "content audit")
    proposal_path = _resolve_control_binding(
        spec.source_admission_proposal,
        root,
        "source-admission proposal",
    )
    admission_path = _resolve_control_binding(
        spec.source_admission_report,
        root,
        "source-admission report",
    )
    request = load_dataset_acquisition_request(request_path)
    receipt = load_dataset_acquisition_receipt(receipt_path)
    _, _, audit = _load_audit_report(audit_path)
    proposal = load_source_admission_proposal(proposal_path)
    _, _, admission = _load_admission_report(admission_path)
    _verify_projection_chain(request, receipt, audit, proposal.proposal, admission)


def _verify_raw_inventory(
    root: Path,
    receipt: AcquisitionReceiptInspection,
) -> None:
    expected = {item.destination for item in receipt.receipt.items}
    observed_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    observed_symlinks = {path for path in root.rglob("*") if path.is_symlink()}
    if observed_files != expected or observed_symlinks:
        raise ValueError("raw acquisition inventory differs from the receipt")


def _select_pointer(value: object, pointer: str) -> object:
    current: list[object] = [value]
    for token in _pointer_tokens(pointer):
        next_values: list[object] = []
        for item in current:
            if token == "*":
                if not isinstance(item, list):
                    raise ValueError(f"JSON pointer wildcard requires an array: {pointer!r}")
                next_values.extend(item)
            else:
                if not isinstance(item, dict) or token not in item:
                    raise ValueError(f"required JSON pointer is absent: {pointer!r}")
                next_values.append(item[token])
        current = next_values
    if not current:
        raise ValueError(f"required JSON pointer selects no values: {pointer!r}")
    return current[0] if "*" not in _pointer_tokens(pointer) else current


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with '/'")
    if pointer == "/":
        return ()
    tokens: list[str] = []
    for raw in pointer[1:].split("/"):
        index = 0
        while index < len(raw):
            if raw[index] == "~":
                if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
                    raise ValueError("JSON pointer contains an invalid escape")
                index += 2
            else:
                index += 1
        token = raw.replace("~1", "/").replace("~0", "~")
        if not token:
            raise ValueError("JSON pointer cannot contain an empty token")
        tokens.append(token)
    return tuple(tokens)


def _pointer_overlaps(selected: str, forbidden: str) -> bool:
    selected_tokens = _pointer_tokens(selected)
    forbidden_tokens = _pointer_tokens(forbidden)
    limit = min(len(selected_tokens), len(forbidden_tokens))
    return all(
        left == right or left == "*" or right == "*"
        for left, right in zip(selected_tokens[:limit], forbidden_tokens[:limit], strict=True)
    )


def _normalize_json(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("projection selected a non-terminal JSON value")


def _verify_visible_exclusions(text: str, spec: SourceProjectionPlan) -> None:
    folded = text.casefold()
    for forbidden in spec.forbidden_model_visible_exact_strings:
        if forbidden.casefold() in folded:
            raise ValueError("projection contains a forbidden model-visible identity")
    if "http://" in folded or "https://" in folded:
        raise ValueError("projection contains external locator text")


def _strict_json_object(raw: bytes, source_id: str) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"source {source_id!r} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"source {source_id!r} must contain a JSON object")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _load_audit_report(path: str | Path) -> tuple[Path, str, JsonContentAuditReport]:
    resolved, raw, payload = _load_json_mapping(path, "JSON content-audit report")
    recorded_hash = payload.pop("report_sha256", None)
    report = JsonContentAuditReport.model_validate(payload)
    if recorded_hash != report.report_sha256:
        raise ValueError("JSON content-audit report hash mismatch")
    return resolved, hashlib.sha256(raw).hexdigest(), report


def _load_admission_report(path: str | Path) -> tuple[Path, str, SourceAdmissionReport]:
    resolved, raw, payload = _load_json_mapping(path, "source-admission report")
    recorded_hash = payload.pop("report_sha256", None)
    report = SourceAdmissionReport.model_validate(payload)
    if recorded_hash != report.report_sha256:
        raise ValueError("source-admission report hash mismatch")
    return resolved, hashlib.sha256(raw).hexdigest(), report


def _control_binding(
    path: Path,
    file_sha256: str,
    semantic_sha256: str,
    root: Path,
) -> SourceProjectionControlBinding:
    relative = _relative_to_root(path, root)
    return SourceProjectionControlBinding(
        path=relative.as_posix(),
        file_sha256=file_sha256,
        semantic_sha256=semantic_sha256,
    )


def _resolve_control_binding(
    binding: SourceProjectionControlBinding,
    root: Path,
    label: str,
) -> Path:
    path = _resolve_beneath(root, binding.path, require_exists=True)
    if path is None or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} control binding is unavailable")
    raw = path.read_bytes()
    if len(raw) > _MAX_CONTROL_BYTES or hashlib.sha256(raw).hexdigest() != binding.file_sha256:
        raise ValueError(f"{label} control binding has drifted")
    return path


def _relative_to_root(path: Path, root: Path) -> PurePosixPath:
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("source-projection controls must be beneath the workspace root") from exc
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("source-projection controls cannot traverse a symlink")
    return PurePosixPath(relative.as_posix())


def _resolve_beneath(root: Path, value: str, *, require_exists: bool) -> Path | None:
    try:
        _validate_relative_path(value, "workspace-relative path")
    except ValueError:
        return None
    unresolved = root / value
    cursor = root
    for part in PurePosixPath(value).parts:
        cursor /= part
        if cursor.is_symlink():
            return None
    path = unresolved.resolve(strict=require_exists)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _validate_relative_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")


def _load_json_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} must contain strict UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
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
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value).rstrip(b"\n")).hexdigest()


def _module_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _require_unique(values: object, label: str) -> None:
    observed = tuple(values)  # type: ignore[arg-type]
    if len(observed) != len(set(observed)):
        raise ValueError(f"{label} must be unique")


__all__ = [
    "ProjectionSemanticRole",
    "SourceProjectionApproval",
    "SourceProjectionApprovalInspection",
    "SourceProjectionControlBinding",
    "SourceProjectionField",
    "SourceProjectionItemPlan",
    "SourceProjectionItemReceipt",
    "SourceProjectionPlan",
    "SourceProjectionPlanInspection",
    "SourceProjectionReceipt",
    "approve_source_projection",
    "build_source_projection_plan",
    "load_source_projection_approval",
    "load_source_projection_plan",
    "load_source_projection_receipt",
    "materialize_source_projections",
    "save_source_projection_approval",
    "save_source_projection_plan",
    "save_source_projection_receipt",
]
