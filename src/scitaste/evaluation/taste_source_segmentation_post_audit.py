"""AI-only post-calibration veto gates for source-review segmentation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.taste_source_segmentation import (
    TasteSourceDecisionContextSpan,
    TasteSourceDecisionSegment,
    TasteSourceSegmentationResolutionItem,
    load_taste_source_segmentation_resolution_run,
)
from scitaste.evaluation.taste_source_segmentation_execution import (
    TasteSourceSegmentationCalibrationReceipt,
)
from scitaste.evaluation.taste_source_segmentation_protocol import (
    TasteSourceSegmentationRequestItem,
    TasteSourceSegmentationRequestPack,
    load_segmentation_post_audit_gate,
    load_taste_source_segmentation_request_pack,
    load_taste_source_segmentation_request_packet,
    segmentation_campaign_token,
    taste_source_comment_unit_offsets,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_UNIT_ID = r"^u[0-9]{4}$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_BYTES = 64 * 1_048_576


class PostAuditArtifactBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> PostAuditArtifactBinding:
        _safe_locator(self.locator)
        return self


class IntegrityInventoryAnchorRange(BaseModel):
    model_config = _CONFIG

    start_unit_id: str = Field(pattern=_UNIT_ID)
    end_unit_id: str = Field(pattern=_UNIT_ID)


class IntegrityInventoryRawDecision(BaseModel):
    model_config = _CONFIG

    trigger_range: IntegrityInventoryAnchorRange
    context_ranges: tuple[IntegrityInventoryAnchorRange, ...] = Field(max_length=8)
    primary_decision_family: Literal[
        "idea", "experiment", "evidence", "writing", "review", "visual", "cannot-assess"
    ]
    atomic_decision_statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    uncertainty: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def cannot_assess_is_uncertain(self) -> IntegrityInventoryRawDecision:
        if self.primary_decision_family == "cannot-assess" and self.uncertainty != "high":
            raise ValueError("AI-D cannot-assess inventory decisions require high uncertainty")
        return self


class IntegrityInventoryRawItem(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    decisions: tuple[IntegrityInventoryRawDecision, ...] = Field(min_length=0, max_length=128)
    no_decision_rationale: str | None = Field(min_length=1, max_length=2_000)
    residual_decision_bearing_text_possible: bool

    @model_validator(mode="after")
    def zero_decision_is_explicit(self) -> IntegrityInventoryRawItem:
        if (not self.decisions) != (self.no_decision_rationale is not None):
            raise ValueError("AI-D zero-decision inventory requires exactly one rationale")
        return self


class IntegrityInventoryRawOutput(BaseModel):
    model_config = _CONFIG

    items: tuple[IntegrityInventoryRawItem, ...] = Field(min_length=1)


class TasteSourceIntegrityReviewReceipt(BaseModel):
    """AI-D's sealed declaration of the exact blind-review input boundary."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    completed_at: datetime
    gate: PostAuditArtifactBinding
    request_pack: PostAuditArtifactBinding
    raw_output: PostAuditArtifactBinding
    invocation_id: str = Field(pattern=_ID)
    runtime_surface: str = Field(min_length=1, max_length=200)
    model_identifier: str = Field(min_length=1, max_length=500)
    exact_model_identity_bound: Literal[False] = False
    assigned_unique_item_count: int = Field(gt=0)
    reviewed_unique_item_count: int = Field(gt=0)
    decision_count: int = Field(ge=0)
    final_resolution_exposed: Literal[False] = False
    calibration_metrics_exposed: Literal[False] = False
    private_source_group_map_exposed: Literal[False] = False
    population_outcomes_exposed: Literal[False] = False
    structural_serialization_correction_performed: bool
    structural_serialization_correction_note: str | None = Field(
        default=None, min_length=1, max_length=2_000
    )
    semantic_retry_performed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_agreement_claim_allowed: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False
    verdict: Literal["inventory-complete"] = "inventory-complete"
    blocker_codes: tuple[str, ...] = Field(default=(), max_length=0)

    @model_validator(mode="after")
    def receipt_is_temporal_and_distinct(self) -> TasteSourceIntegrityReviewReceipt:
        if self.completed_at.utcoffset() is None:
            raise ValueError("AI-D review-receipt time must include a timezone")
        if len({self.gate.locator, self.request_pack.locator, self.raw_output.locator}) != 3:
            raise ValueError("AI-D review-receipt artifacts must be distinct")
        if self.assigned_unique_item_count != self.reviewed_unique_item_count:
            raise ValueError("AI-D review receipt does not cover every assigned item")
        if self.structural_serialization_correction_performed != (
            self.structural_serialization_correction_note is not None
        ):
            raise ValueError("AI-D serialization correction lacks an exact note")
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class TasteSourceIntegrityInventoryItem(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    source_comment_sha256: str = Field(pattern=_SHA256)
    evidence_unit_table_sha256: str = Field(pattern=_SHA256)
    decisions: tuple[TasteSourceDecisionSegment, ...] = Field(min_length=0, max_length=128)
    no_decision_rationale: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        exclude_if=lambda value: value is None,
    )
    residual_decision_bearing_text_possible: bool

    @model_validator(mode="after")
    def inventory_is_counted(self) -> TasteSourceIntegrityInventoryItem:
        if (not self.decisions) != (self.no_decision_rationale is not None):
            raise ValueError("AI-D normalized zero-decision inventory lacks a rationale")
        if tuple(item.ordinal for item in self.decisions) != tuple(
            range(1, len(self.decisions) + 1)
        ):
            raise ValueError("AI-D inventory decision ordinals are not contiguous")
        return self


class TasteSourceIntegrityInventory(BaseModel):
    """Sealed AI-D inventory created without seeing A/B/C or final resolution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    inventory_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    completed_at: datetime
    gate: PostAuditArtifactBinding
    request_pack: PostAuditArtifactBinding
    raw_output: PostAuditArtifactBinding
    review_receipt: PostAuditArtifactBinding
    invocation_id: str = Field(pattern=_ID)
    runtime_surface: str = Field(min_length=1, max_length=200)
    model_identifier: str = Field(min_length=1, max_length=500)
    exact_model_identity_bound: Literal[False] = False
    items: tuple[TasteSourceIntegrityInventoryItem, ...] = Field(min_length=1)
    item_count: int = Field(gt=0)
    residual_risk_item_count: int = Field(ge=0)
    final_resolution_exposed: Literal[False] = False
    calibration_metrics_exposed: Literal[False] = False
    private_source_group_map_exposed: Literal[False] = False
    population_outcomes_exposed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    model_independence_claimed: Literal[False] = False
    statistical_independence_claimed: Literal[False] = False
    inventory_is_gold_label: Literal[False] = False
    human_agreement_claim_allowed: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False

    @model_validator(mode="after")
    def inventory_is_sealed_and_complete(self) -> TasteSourceIntegrityInventory:
        if self.completed_at.utcoffset() is None:
            raise ValueError("AI-D inventory completion time must include a timezone")
        keys = [(item.campaign_token, item.review_item_id) for item in self.items]
        if keys != sorted(set(keys)) or self.item_count != len(keys):
            raise ValueError("AI-D inventory item coverage is not sorted and unique")
        if self.residual_risk_item_count != sum(
            item.residual_decision_bearing_text_possible for item in self.items
        ):
            raise ValueError("AI-D inventory residual count drifted")
        return self

    @computed_field
    @property
    def inventory_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"inventory_sha256"}))


class TasteSourceIntegrityAuditItemFinding(BaseModel):
    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    inventory_decision_count: int = Field(ge=0, le=128)
    final_decision_count: int = Field(ge=0, le=128)
    blocker_codes: tuple[str, ...]

    @model_validator(mode="after")
    def blockers_are_canonical(self) -> TasteSourceIntegrityAuditItemFinding:
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("AI-D finding blockers must be sorted and unique")
        return self


class TasteSourceSegmentationIntegrityAuditReport(BaseModel):
    """Deterministic comparison of sealed AI-D inventory and final resolution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    compiled_at: datetime
    calibration_receipt: PostAuditArtifactBinding
    gate: PostAuditArtifactBinding
    inventory: PostAuditArtifactBinding
    resolution: PostAuditArtifactBinding
    invocation_id: str = Field(pattern=_ID)
    distinct_from_calibration_invocations: Literal[True] = True
    items: tuple[TasteSourceIntegrityAuditItemFinding, ...] = Field(min_length=1)
    blocker_codes: tuple[str, ...]
    decision: Literal["pass", "veto"]
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_review_claimed: Literal[False] = False
    inventory_is_gold_label: Literal[False] = False
    scaled_execution_authorized: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False

    @model_validator(mode="after")
    def decision_is_veto_only(self) -> TasteSourceSegmentationIntegrityAuditReport:
        if self.compiled_at.utcoffset() is None:
            raise ValueError("AI-D integrity audit time must include a timezone")
        keys = [(item.campaign_id, item.review_item_id) for item in self.items]
        if keys != sorted(set(keys)):
            raise ValueError("AI-D integrity findings are not sorted and unique")
        expected = tuple(sorted({code for item in self.items for code in item.blocker_codes}))
        if self.blocker_codes != expected or self.decision != ("veto" if expected else "pass"):
            raise ValueError("AI-D veto decision differs from deterministic blockers")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def normalize_taste_source_integrity_inventory(
    *,
    raw_inventory_path: str | Path,
    request_pack_path: str | Path,
    gate_path: str | Path,
    review_receipt_path: str | Path,
    inventory_id: str,
    locator_root: str | Path,
) -> TasteSourceIntegrityInventory:
    """Normalize one sealed AI-D output against exact request-pack source bytes."""

    root = Path(locator_root).resolve(strict=True)
    raw_path = _bounded_file(Path(raw_inventory_path))
    pack_path = _bounded_file(Path(request_pack_path))
    receipt_path = _bounded_file(Path(review_receipt_path))
    gate = load_segmentation_post_audit_gate(gate_path)
    if gate.gate.role_id != "ai-d-content-integrity":
        raise ValueError("AI-D inventory binds the wrong post-audit gate")
    raw = IntegrityInventoryRawOutput.model_validate(json.loads(raw_path.read_bytes()))
    pack = load_taste_source_segmentation_request_pack(pack_path)
    receipt = load_taste_source_integrity_review_receipt(receipt_path)
    expected_gate = PostAuditArtifactBinding(
        locator=_relative(gate.path, root),
        file_sha256=gate.file_sha256,
        semantic_sha256=_canonical_sha256(gate.gate.model_dump(mode="json")),
    )
    expected_pack = PostAuditArtifactBinding(
        locator=_relative(pack_path, root),
        file_sha256=_sha256_file(pack_path),
        semantic_sha256=pack.pack_sha256,
    )
    expected_raw = PostAuditArtifactBinding(
        locator=_relative(raw_path, root),
        file_sha256=_sha256_file(raw_path),
        semantic_sha256=_canonical_sha256(raw.model_dump(mode="json")),
    )
    if (
        receipt.project_id != pack.project_id
        or receipt.gate != expected_gate
        or receipt.request_pack != expected_pack
        or receipt.raw_output != expected_raw
        or receipt.assigned_unique_item_count != pack.unique_item_count
        or receipt.reviewed_unique_item_count != len(raw.items)
        or receipt.decision_count != sum(len(item.decisions) for item in raw.items)
    ):
        raise ValueError("AI-D review receipt differs from exact sealed inputs")
    request_root = pack_path.parent
    expected: dict[tuple[str, str], TasteSourceSegmentationRequestItem] = {}
    for binding in pack.requests:
        packet_path = _bounded_file(request_root / _safe_locator(binding.locator))
        if _sha256_file(packet_path) != binding.file_sha256:
            raise ValueError("AI-D input request packet file hash drifted")
        packet = load_taste_source_segmentation_request_packet(packet_path)
        if packet.packet_sha256 != binding.packet_sha256:
            raise ValueError("AI-D input request packet semantic hash drifted")
        for item in packet.items:
            key = (item.campaign_token, item.review_item_id)
            if key in expected and expected[key] != item:
                raise ValueError("AI-D sees inconsistent duplicate request items")
            expected[key] = item
    if len(expected) != pack.unique_item_count:
        raise ValueError("AI-D request-pack unique item count drifted")
    observed = {(item.campaign_token, item.review_item_id): item for item in raw.items}
    if len(observed) != len(raw.items) or set(observed) != set(expected):
        raise ValueError("AI-D inventory must cover every assigned item exactly once")

    normalized = tuple(
        _normalize_inventory_item(observed[key], expected[key]) for key in sorted(expected)
    )
    return TasteSourceIntegrityInventory(
        inventory_id=inventory_id,
        project_id=pack.project_id,
        completed_at=receipt.completed_at,
        gate=expected_gate,
        request_pack=expected_pack,
        raw_output=expected_raw,
        review_receipt=PostAuditArtifactBinding(
            locator=_relative(receipt_path, root),
            file_sha256=_sha256_file(receipt_path),
            semantic_sha256=receipt.receipt_sha256,
        ),
        invocation_id=receipt.invocation_id,
        runtime_surface=receipt.runtime_surface,
        model_identifier=receipt.model_identifier,
        items=normalized,
        item_count=len(normalized),
        residual_risk_item_count=sum(
            item.residual_decision_bearing_text_possible for item in normalized
        ),
    )


def _verify_and_replay_inventory(
    *, inventory_path: str | Path, request_pack_path: str | Path, locator_root: str | Path
) -> tuple[
    TasteSourceIntegrityInventory,
    TasteSourceSegmentationRequestPack,
    dict[tuple[str, str], TasteSourceSegmentationRequestItem],
]:
    root = Path(locator_root).resolve(strict=True)
    inventory_source = _bounded_file(Path(inventory_path))
    pack_source = _bounded_file(Path(request_pack_path))
    inventory = load_taste_source_integrity_inventory(inventory_source)
    pack = load_taste_source_segmentation_request_pack(pack_source)
    if (
        inventory.request_pack.locator != _relative(pack_source, root)
        or inventory.request_pack.file_sha256 != _sha256_file(pack_source)
        or inventory.request_pack.semantic_sha256 != pack.pack_sha256
        or inventory.project_id != pack.project_id
    ):
        raise ValueError("AI-D inventory request-pack binding drifted")
    gate_source = _resolve_locator(root, inventory.gate.locator)
    gate = load_segmentation_post_audit_gate(gate_source)
    if (
        gate.gate.role_id != "ai-d-content-integrity"
        or gate.file_sha256 != inventory.gate.file_sha256
        or _canonical_sha256(gate.gate.model_dump(mode="json")) != inventory.gate.semantic_sha256
    ):
        raise ValueError("AI-D integrity-gate binding drifted")
    raw_source = _resolve_locator(root, inventory.raw_output.locator)
    review_receipt_source = _resolve_locator(root, inventory.review_receipt.locator)
    replayed_inventory = normalize_taste_source_integrity_inventory(
        raw_inventory_path=raw_source,
        request_pack_path=pack_source,
        gate_path=gate_source,
        review_receipt_path=review_receipt_source,
        inventory_id=inventory.inventory_id,
        locator_root=root,
    )
    if replayed_inventory != inventory:
        raise ValueError("AI-D normalized inventory differs from sealed raw replay")
    request_items: dict[tuple[str, str], TasteSourceSegmentationRequestItem] = {}
    for binding in pack.requests:
        packet_source = _resolve_locator(pack_source.parent, binding.locator)
        packet = load_taste_source_segmentation_request_packet(packet_source)
        if (
            _sha256_file(packet_source) != binding.file_sha256
            or packet.packet_sha256 != binding.packet_sha256
        ):
            raise ValueError("AI-D audit request-packet binding drifted")
        for item in packet.items:
            key = (item.campaign_token, item.review_item_id)
            if key in request_items and request_items[key] != item:
                raise ValueError("AI-D audit request pack has inconsistent duplicates")
            request_items[key] = item
    return inventory, pack, request_items


def _require_inventory_precedes_calibration(
    inventory: TasteSourceIntegrityInventory, calibration_started_at: datetime
) -> None:
    if calibration_started_at.utcoffset() is None:
        raise ValueError("Segmentation calibration start time must include a timezone")
    if inventory.completed_at > calibration_started_at:
        raise ValueError("AI-D inventory was not sealed before calibration started")


def compile_taste_source_segmentation_integrity_audit(
    *,
    report_id: str,
    inventory_path: str | Path,
    calibration_receipt_path: str | Path,
    resolution_path: str | Path,
    request_pack_path: str | Path,
    compiled_at: datetime,
    locator_root: str | Path,
) -> TasteSourceSegmentationIntegrityAuditReport:
    """Compare the blind inventory to final output; every discrepancy can only veto."""

    root = Path(locator_root).resolve(strict=True)
    inventory_source = _bounded_file(Path(inventory_path))
    calibration_source = _bounded_file(Path(calibration_receipt_path))
    resolution_source = _bounded_file(Path(resolution_path))
    pack_source = _bounded_file(Path(request_pack_path))
    inventory, pack, request_items = _verify_and_replay_inventory(
        inventory_path=inventory_source,
        request_pack_path=pack_source,
        locator_root=root,
    )
    calibration = TasteSourceSegmentationCalibrationReceipt.model_validate(
        json.loads(calibration_source.read_bytes())
    )
    resolution_inspection = load_taste_source_segmentation_resolution_run(resolution_source)
    resolution = resolution_inspection.run
    if (
        calibration.request_pack_sha256 != pack.pack_sha256
        or calibration.resolution.file_sha256 != resolution_inspection.file_sha256
        or calibration.resolution.semantic_sha256 != resolution.run_sha256
        or inventory.project_id != calibration.project_id
        or inventory.project_id != resolution.project_id
    ):
        raise ValueError("AI-D audit artifact bindings drifted")
    _require_inventory_precedes_calibration(inventory, calibration.started_at)
    calibration_invocations = {
        resolution.invocation_id,
        *(item.invocation_id for item in resolution.source_segmentation_artifacts),
    }
    if inventory.invocation_id in calibration_invocations:
        raise ValueError("AI-D invocation is not distinct from A/B/C")

    inventory_by_key = {
        (item.campaign_token, item.review_item_id): item for item in inventory.items
    }
    findings = []
    observed_inventory_keys: set[tuple[str, str]] = set()
    for final_item in resolution.items:
        token = segmentation_campaign_token(pack.pack_id, final_item.campaign_id)
        key = (token, final_item.review_item_id)
        inventory_item = inventory_by_key.get(key)
        if inventory_item is None:
            raise ValueError("AI-D inventory and final resolution item sets differ")
        request_item = request_items.get(key)
        if request_item is None:
            raise ValueError("AI-D final resolution item is absent from its request pack")
        if (
            inventory_item.source_comment_sha256
            != hashlib.sha256(request_item.review_comment.encode()).hexdigest()
            or inventory_item.evidence_unit_table_sha256 != request_item.evidence_unit_table_sha256
        ):
            raise ValueError("AI-D source-item binding drifted")
        _verify_resolution_source_slices(final_item, request_item.review_comment)
        observed_inventory_keys.add(key)
        blockers: set[str] = set()
        inventory_signatures = {_decision_signature(item) for item in inventory_item.decisions}
        final_signatures = {_decision_signature(item) for item in final_item.segments}
        inventory_triggers = {
            (item.start_char, item.end_char): item for item in inventory_item.decisions
        }
        final_triggers = {(item.start_char, item.end_char): item for item in final_item.segments}
        if set(inventory_triggers) - set(final_triggers):
            blockers.add("missed-actionable-decision")
        if set(final_triggers) - set(inventory_triggers):
            blockers.add("false-positive-decision")
        if set(inventory_triggers) == set(final_triggers) and (
            inventory_signatures != final_signatures
        ):
            blockers.add("decision-family-or-context-mismatch")
        if inventory_item.residual_decision_bearing_text_possible:
            blockers.add("auditor-residual-self-report")
        if final_item.residual_decision_bearing_text_possible:
            blockers.add("final-residual-self-report")
        findings.append(
            TasteSourceIntegrityAuditItemFinding(
                campaign_id=final_item.campaign_id,
                review_item_id=final_item.review_item_id,
                inventory_decision_count=len(inventory_item.decisions),
                final_decision_count=len(final_item.segments),
                blocker_codes=tuple(sorted(blockers)),
            )
        )
    if observed_inventory_keys != set(inventory_by_key):
        raise ValueError("AI-D inventory contains items absent from final resolution")
    ordered = tuple(sorted(findings, key=lambda item: (item.campaign_id, item.review_item_id)))
    blockers = tuple(sorted({code for item in ordered for code in item.blocker_codes}))
    return TasteSourceSegmentationIntegrityAuditReport(
        report_id=report_id,
        project_id=inventory.project_id,
        compiled_at=compiled_at,
        calibration_receipt=PostAuditArtifactBinding(
            locator=_relative(calibration_source, root),
            file_sha256=_sha256_file(calibration_source),
            semantic_sha256=calibration.receipt_sha256,
        ),
        gate=inventory.gate,
        inventory=PostAuditArtifactBinding(
            locator=_relative(inventory_source, root),
            file_sha256=_sha256_file(inventory_source),
            semantic_sha256=inventory.inventory_sha256,
        ),
        resolution=PostAuditArtifactBinding(
            locator=_relative(resolution_source, root),
            file_sha256=resolution_inspection.file_sha256,
            semantic_sha256=resolution.run_sha256,
        ),
        invocation_id=inventory.invocation_id,
        items=ordered,
        blocker_codes=blockers,
        decision="veto" if blockers else "pass",
    )


def save_taste_source_integrity_inventory(
    inventory: TasteSourceIntegrityInventory, path: str | Path
) -> Path:
    return _write_json_new(Path(path), inventory.model_dump(mode="json"))


def load_taste_source_integrity_review_receipt(
    path: str | Path,
) -> TasteSourceIntegrityReviewReceipt:
    source = _bounded_file(Path(path))
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI-D review receipt must contain a mapping")
    recorded = payload.pop("receipt_sha256", None)
    receipt = TasteSourceIntegrityReviewReceipt.model_validate(payload)
    if recorded != receipt.receipt_sha256:
        raise ValueError("AI-D review-receipt semantic hash mismatch")
    return receipt


def load_taste_source_integrity_inventory(path: str | Path) -> TasteSourceIntegrityInventory:
    source = _bounded_file(Path(path))
    payload = json.loads(source.read_bytes())
    recorded = payload.pop("inventory_sha256", None)
    inventory = TasteSourceIntegrityInventory.model_validate(payload)
    if recorded != inventory.inventory_sha256:
        raise ValueError("AI-D inventory semantic hash mismatch")
    return inventory


def save_taste_source_segmentation_integrity_audit(
    report: TasteSourceSegmentationIntegrityAuditReport, path: str | Path
) -> Path:
    return _write_json_new(Path(path), report.model_dump(mode="json"))


def load_taste_source_segmentation_integrity_audit(
    path: str | Path,
) -> TasteSourceSegmentationIntegrityAuditReport:
    source = _bounded_file(Path(path))
    payload = json.loads(source.read_bytes())
    recorded = payload.pop("report_sha256", None)
    report = TasteSourceSegmentationIntegrityAuditReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("AI-D integrity-audit semantic hash mismatch")
    return report


def _normalize_inventory_item(
    raw: IntegrityInventoryRawItem,
    source_item: TasteSourceSegmentationRequestItem,
) -> TasteSourceIntegrityInventoryItem:
    rows = taste_source_comment_unit_offsets(source_item.review_comment)
    units = {
        unit_id: (ordinal, start, end) for ordinal, (unit_id, _, start, end) in enumerate(rows, 1)
    }

    def resolve(selected: IntegrityInventoryAnchorRange) -> tuple[int, int, int, int]:
        try:
            start_ordinal, start_char, _ = units[selected.start_unit_id]
            end_ordinal, _, end_char = units[selected.end_unit_id]
        except KeyError as error:
            raise ValueError("AI-D inventory selected an unknown evidence-unit ID") from error
        if end_ordinal < start_ordinal:
            raise ValueError("AI-D inventory evidence-unit range is reversed")
        return start_ordinal, end_ordinal, start_char, end_char

    decisions = []
    trigger_units = []
    for ordinal, decision in enumerate(raw.decisions, 1):
        start_unit, end_unit, start_char, end_char = resolve(decision.trigger_range)
        trigger_units.append((start_unit, end_unit))
        contexts = []
        context_units = []
        for context_ordinal, selected in enumerate(decision.context_ranges, 1):
            context_start_unit, context_end_unit, context_start, context_end = resolve(selected)
            context_units.append((context_start_unit, context_end_unit))
            identity = _canonical_sha256(
                [raw.campaign_token, raw.review_item_id, context_start, context_end]
            )
            contexts.append(
                TasteSourceDecisionContextSpan(
                    context_id=f"context-{identity[:24]}",
                    ordinal=context_ordinal,
                    start_char=context_start,
                    end_char=context_end,
                    verbatim_context_text=source_item.review_comment[context_start:context_end],
                )
            )
        if context_units != sorted(set(context_units)) or any(
            first_end + 1 >= second_start
            for (_, first_end), (second_start, _) in pairwise(context_units)
        ):
            raise ValueError("AI-D context ranges are repeated, unordered, or adjacent")
        if any(
            context_start <= end_unit and context_end >= start_unit
            for context_start, context_end in context_units
        ):
            raise ValueError("AI-D context overlaps its own trigger")
        identity = _canonical_sha256([raw.campaign_token, raw.review_item_id, start_char, end_char])
        decisions.append(
            TasteSourceDecisionSegment(
                segment_id=f"segment-{identity[:24]}",
                ordinal=ordinal,
                start_char=start_char,
                end_char=end_char,
                verbatim_decision_text=source_item.review_comment[start_char:end_char],
                primary_decision_family=decision.primary_decision_family,
                atomic_decision_statement=decision.atomic_decision_statement,
                rationale=decision.rationale,
                uncertainty=decision.uncertainty,
                context_ranges=tuple(contexts),
            )
        )
    if trigger_units != sorted(trigger_units) or any(
        first_end >= second_start for (_, first_end), (second_start, _) in pairwise(trigger_units)
    ):
        raise ValueError("AI-D trigger ranges are overlapping or unordered")
    return TasteSourceIntegrityInventoryItem(
        campaign_token=raw.campaign_token,
        review_item_id=raw.review_item_id,
        source_comment_sha256=hashlib.sha256(source_item.review_comment.encode()).hexdigest(),
        evidence_unit_table_sha256=source_item.evidence_unit_table_sha256 or "",
        decisions=tuple(decisions),
        no_decision_rationale=raw.no_decision_rationale,
        residual_decision_bearing_text_possible=(raw.residual_decision_bearing_text_possible),
    )


def _decision_signature(segment: TasteSourceDecisionSegment) -> tuple[object, ...]:
    return (
        segment.start_char,
        segment.end_char,
        str(segment.primary_decision_family),
        tuple((item.start_char, item.end_char) for item in segment.context_ranges),
    )


def _verify_resolution_source_slices(
    item: TasteSourceSegmentationResolutionItem, review_comment: str
) -> None:
    def exact(start: int, end: int, verbatim: str) -> bool:
        return 0 <= start < end <= len(review_comment) and (review_comment[start:end] == verbatim)

    for segment in item.segments:
        if not exact(segment.start_char, segment.end_char, segment.verbatim_decision_text):
            raise ValueError("Final segmentation trigger differs from request source bytes")
        if any(
            not exact(context.start_char, context.end_char, context.verbatim_context_text)
            for context in segment.context_ranges
        ):
            raise ValueError("Final segmentation context differs from request source bytes")


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _bounded_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise ValueError("Segmentation post-audit input must be a bounded regular file")
    return path.resolve(strict=True)


def _safe_locator(locator: str) -> Path:
    pure = PurePosixPath(locator)
    if "\\" in locator or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("Segmentation post-audit locator is unsafe")
    return Path(*pure.parts)


def _resolve_locator(root: Path, locator: str) -> Path:
    source = _bounded_file(root / _safe_locator(locator))
    try:
        source.relative_to(root)
    except ValueError as error:
        raise ValueError("Segmentation post-audit locator escapes its root") from error
    return source


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("Segmentation post-audit artifact is outside locator root") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_new(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(data)
    except FileExistsError as error:
        raise FileExistsError(f"Segmentation post-audit artifact already exists: {path}") from error
    return path.resolve(strict=True)


__all__ = [
    "IntegrityInventoryAnchorRange",
    "IntegrityInventoryRawDecision",
    "IntegrityInventoryRawItem",
    "IntegrityInventoryRawOutput",
    "PostAuditArtifactBinding",
    "TasteSourceIntegrityAuditItemFinding",
    "TasteSourceIntegrityInventory",
    "TasteSourceIntegrityInventoryItem",
    "TasteSourceIntegrityReviewReceipt",
    "TasteSourceSegmentationIntegrityAuditReport",
    "compile_taste_source_segmentation_integrity_audit",
    "load_taste_source_integrity_inventory",
    "load_taste_source_integrity_review_receipt",
    "load_taste_source_segmentation_integrity_audit",
    "normalize_taste_source_integrity_inventory",
    "save_taste_source_integrity_inventory",
    "save_taste_source_segmentation_integrity_audit",
]
