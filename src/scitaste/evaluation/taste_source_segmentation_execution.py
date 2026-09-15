"""Fail-closed provider execution for prospective decision segmentation.

This layer deliberately sits outside the legacy segmentation normalizers.  A
provider returns only task outputs; a trusted runner, rather than the model,
records the input-firewall and identity evidence used to interpret them.
Loading or inspecting any object in this module performs no network action.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

import httpx
import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    model_validator,
)

from scitaste.evaluation.model_identity import (
    ApiIdentityCallReceipt,
    ApiIdentityCallRole,
    ApiIdentityProtocolInspection,
    ApiIdentityWindowAttestation,
    ApiIdentityWindowKind,
    ApiIdentityWindowReport,
    inspect_api_identity_window,
    load_api_identity_protocol,
)
from scitaste.evaluation.taste_source_segmentation import (
    TasteSourceDecisionSegmentationRun,
    TasteSourceSegmentationAgreementReport,
    TasteSourceSegmentationCampaignSnapshot,
    TasteSourceSegmentationGroupBoundarySnapshot,
    TasteSourceSegmentationGroupUncertainty,
    TasteSourceSegmentationRubricSnapshot,
    TasteSourceSegmentationSampleInspection,
    compile_taste_source_segmentation_agreement,
    normalize_taste_source_decision_segmentation,
    normalize_taste_source_segmentation_resolution,
    save_taste_source_decision_segmentation_run,
    save_taste_source_segmentation_agreement_report,
    save_taste_source_segmentation_resolution_run,
    snapshot_taste_source_segmentation_campaign,
    snapshot_taste_source_segmentation_group_boundary,
    snapshot_taste_source_segmentation_rubric,
)
from scitaste.evaluation.taste_source_segmentation_protocol import (
    TasteSourceSegmentationProspectiveProtocol,
    TasteSourceSegmentationProtocolInspection,
    TasteSourceSegmentationRequestPack,
    TasteSourceSegmentationRequestPacket,
    inspect_taste_source_segmentation_protocol,
    load_taste_source_segmentation_request_pack,
    load_taste_source_segmentation_request_packet,
    segmentation_campaign_token,
    taste_source_comment_unit_offsets,
    taste_source_evidence_unit_table_sha256,
    unitize_taste_source_comment,
)
from scitaste.project.models import content_sha256
from scitaste.resources import ApiModelDefinition

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_AUTHORIZATION_BYTES = 2 * 1_048_576
_MAX_PACKET_BYTES = 64 * 1_048_576
_MAX_RESPONSE_BYTES = 16 * 1_048_576


class SegmentationExecutionFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationExecutionFileBinding:
        _safe_locator(self.locator)
        return self


class SegmentationExecutionPackBinding(SegmentationExecutionFileBinding):
    pack_sha256: str = Field(pattern=_SHA256)


class SegmentationExecutionRunnerBinding(SegmentationExecutionFileBinding):
    git_commit: str = Field(pattern=_COMMIT)
    cli_locator: str = Field(min_length=1, max_length=2_000)
    cli_file_sha256: str = Field(pattern=_SHA256)
    runtime_modules: tuple[SegmentationExecutionFileBinding, ...] = Field(
        min_length=7, max_length=12
    )

    @model_validator(mode="after")
    def cli_locator_is_safe(self) -> SegmentationExecutionRunnerBinding:
        _safe_locator(self.cli_locator)
        required = {
            "src/scitaste/evaluation/taste_source_segmentation.py",
            "src/scitaste/evaluation/taste_source_segmentation_protocol.py",
            "src/scitaste/evaluation/taste_source_segmentation_post_audit.py",
            "src/scitaste/evaluation/model_identity.py",
            "src/scitaste/project/models.py",
            "src/scitaste/resources/__init__.py",
            "src/scitaste/resources/registry.py",
        }
        locators = {item.locator for item in self.runtime_modules}
        if locators != required or len(locators) != len(self.runtime_modules):
            raise ValueError("Segmentation runner runtime-module manifest is incomplete")
        if self.locator in locators or self.cli_locator in locators:
            raise ValueError("Segmentation runner bindings must be distinct")
        return self


class SegmentationExecutionPriceCeiling(BaseModel):
    """Point-in-time CNY estimate plus the owner's independent USD liability cap."""

    model_config = _CONFIG

    currency: Literal["CNY"] = "CNY"
    input_cache_miss_cny_per_million_tokens: float = Field(gt=0, allow_inf_nan=False)
    input_cache_hit_cny_per_million_tokens: float = Field(gt=0, allow_inf_nan=False)
    output_cny_per_million_tokens: float = Field(gt=0, allow_inf_nan=False)
    maximum_estimated_cost_cny: float = Field(gt=0, allow_inf_nan=False)
    owner_maximum_liability_usd: float = Field(gt=0, allow_inf_nan=False)
    basis: Literal["official-point-in-time-price-plus-owner-liability-ceiling"]
    pricing_source_url: str = Field(min_length=1, max_length=2_000)
    pricing_observed_at: datetime
    pricing_snapshot: SegmentationExecutionFileBinding
    observed_model_name: Literal["GLM-5.3-Flash"] = "GLM-5.3-Flash"
    cache_storage_currently_free: Literal[True] = True
    exact_provider_invoice_claimed: Literal[False] = False
    foreign_exchange_conversion_claimed: Literal[False] = False

    @model_validator(mode="after")
    def timestamp_is_aware(self) -> SegmentationExecutionPriceCeiling:
        if self.pricing_observed_at.utcoffset() is None:
            raise ValueError("Segmentation price observation time must include a timezone")
        return self


class SegmentationExecutionLimits(BaseModel):
    model_config = _CONFIG

    maximum_provider_requests: int = Field(gt=0, le=100)
    maximum_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)
    retry_count: Literal[0] = 0
    timeout_seconds_per_request: float = Field(gt=0, le=600, allow_inf_nan=False)
    maximum_raw_response_bytes: int = Field(gt=0, le=_MAX_RESPONSE_BYTES)


class SegmentationExecutionAuthority(BaseModel):
    model_config = _CONFIG

    api_calls_authorized: Literal[True] = True
    prospective_calibration_authorized: Literal[True] = True
    scaled_execution_authorized: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    formal_effectiveness_claim_authorized: Literal[False] = False
    human_review_claim_authorized: Literal[False] = False


class TasteSourceSegmentationExecutionAuthorization(BaseModel):
    """Content-addressed owner approval for exactly one calibration run."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    authorization_id: str = Field(pattern=_ID)
    run_id: str = Field(pattern=_ID)
    one_time_nonce: str = Field(pattern=_ID)
    execution_ledger_locator: str = Field(min_length=1, max_length=2_000)
    run_output_locator: str = Field(min_length=1, max_length=2_000)
    project_id: str = Field(pattern=_ID)
    authorized_by: str = Field(min_length=1, max_length=200)
    approval_origin: Literal["project-owner-conversation"]
    approval_evidence_sha256: str = Field(pattern=_SHA256)
    approval_evidence: SegmentationExecutionFileBinding
    authorized_at: datetime
    expires_at: datetime
    protocol: SegmentationExecutionFileBinding
    freeze_receipt: SegmentationExecutionFileBinding
    request_pack: SegmentationExecutionPackBinding
    routing_amendment: SegmentationExecutionFileBinding
    precontact_audit_seal: SegmentationExecutionFileBinding
    provider_resource: SegmentationExecutionFileBinding
    official_catalog_snapshot: SegmentationExecutionFileBinding
    identity_protocol: SegmentationExecutionFileBinding
    runner: SegmentationExecutionRunnerBinding
    requested_provider: str = Field(pattern=_ID)
    requested_model: str = Field(min_length=1, max_length=500)
    credential_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    execution_scope: Literal["prospective-segmentation-calibration-only"]
    price_ceiling: SegmentationExecutionPriceCeiling
    limits: SegmentationExecutionLimits
    authority: SegmentationExecutionAuthority
    authorization_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def authorization_is_closed(self) -> TasteSourceSegmentationExecutionAuthorization:
        if (
            self.authorized_at.utcoffset() is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.authorized_at
        ):
            raise ValueError("Segmentation execution authorization window is invalid")
        _safe_locator(self.execution_ledger_locator)
        _safe_locator(self.run_output_locator)
        if self.approval_evidence.file_sha256 != self.approval_evidence_sha256:
            raise ValueError("Segmentation owner-approval evidence hash differs")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"authorization_sha256"}))
        if self.authorization_sha256 != expected:
            raise ValueError("Segmentation execution authorization hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceSegmentationExecutionAuthorization:
        payload = {"schema_version": "1.0", **values}
        payload.pop("authorization_sha256", None)
        unsigned = cls.model_construct(authorization_sha256="0" * 64, **payload)
        return cls(
            **payload,
            authorization_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"authorization_sha256"})
            ),
        )


class TasteSourceSegmentationExecutionInspection(BaseModel):
    model_config = _CONFIG

    authorization_path: Path
    authorization_file_sha256: str = Field(pattern=_SHA256)
    authorization: TasteSourceSegmentationExecutionAuthorization
    protocol: TasteSourceSegmentationProtocolInspection
    request_pack: TasteSourceSegmentationRequestPack
    identity_protocol: ApiIdentityProtocolInspection
    provider_resource: ApiModelDefinition
    sample: TasteSourceSegmentationSampleInspection = Field(exclude=True)
    packets: tuple[TasteSourceSegmentationRequestPacket, ...] = Field(exclude=True)
    segmentation_rubric: TasteSourceSegmentationRubricSnapshot = Field(exclude=True)
    adjudication_rubric: TasteSourceSegmentationRubricSnapshot = Field(exclude=True)
    campaigns: tuple[TasteSourceSegmentationCampaignSnapshot, ...] = Field(exclude=True)
    group_boundary: TasteSourceSegmentationGroupBoundarySnapshot = Field(exclude=True)
    packet_count: int = Field(gt=0)
    unique_item_count: int = Field(gt=0)
    runner_git_binding_verified: Literal[True] = True
    runtime_source_tree_verified: Literal[True] = True
    payload_firewall_verified: Literal[True] = True
    routing_amendment_verified: Literal[True] = True
    precontact_audit_seal_verified: Literal[True] = True
    ai_d_inventory_replay_verified: Literal[True] = True
    ai_e_preexecution_pass_verified: Literal[True] = True
    ai_e_authority_pass_verified: Literal[True] = True
    owner_approval_receipt_verified: Literal[True] = True
    authorization_candidate_validated: Literal[True] = True
    execution_ready: Literal[False] = False
    external_action_performed: Literal[False] = False


class SegmentationProviderContextRange(BaseModel):
    model_config = _CONFIG

    verbatim_context_text: str = Field(min_length=1, max_length=16_000)
    start_char: int = Field(ge=0, exclude=True)
    end_char: int = Field(gt=0, exclude=True)

    @model_validator(mode="after")
    def internal_offsets_are_consistent(self) -> SegmentationProviderContextRange:
        if self.end_char <= self.start_char:
            raise ValueError("Segmentation context offsets are reversed")
        if self.end_char - self.start_char != len(self.verbatim_context_text):
            raise ValueError("Segmentation context offsets differ from source text")
        return self


class SegmentationProviderSegment(BaseModel):
    model_config = _CONFIG

    verbatim_decision_text: str = Field(
        min_length=1,
        max_length=16_000,
        validation_alias=AliasChoices("verbatim_decision_text", "reported_decision_text"),
    )
    primary_decision_family: Literal[
        "idea", "experiment", "evidence", "writing", "review", "visual", "cannot-assess"
    ]
    atomic_decision_statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    uncertainty: Literal["low", "medium", "high"]
    start_char: int | None = Field(default=None, ge=0, exclude=True)
    end_char: int | None = Field(default=None, gt=0, exclude=True)
    context_ranges: tuple[SegmentationProviderContextRange, ...] = Field(
        default=(), max_length=8, exclude_if=lambda value: not value
    )
    own_trigger_context_overlap_allowed: bool = Field(
        default=False,
        exclude_if=lambda value: not value,
    )

    @model_validator(mode="before")
    @classmethod
    def one_text_field_only(cls, value: object) -> object:
        if isinstance(value, dict) and {
            "verbatim_decision_text",
            "reported_decision_text",
        }.issubset(value):
            raise ValueError("Segmentation provider returned both text field variants")
        return value

    @model_validator(mode="after")
    def internal_offsets_are_consistent(self) -> SegmentationProviderSegment:
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("Segmentation provider internal offsets are incomplete")
        if self.start_char is not None and self.end_char is not None:
            if self.end_char <= self.start_char:
                raise ValueError("Segmentation provider internal offsets are reversed")
            if self.end_char - self.start_char != len(self.verbatim_decision_text):
                raise ValueError("Segmentation provider internal offsets differ from source text")
            intervals = [(item.start_char, item.end_char) for item in self.context_ranges]
            if intervals != sorted(set(intervals)):
                raise ValueError("Segmentation provider context ranges are unordered or repeated")
            if any(first[1] > second[0] for first, second in pairwise(intervals)):
                raise ValueError("Segmentation provider context ranges overlap")
            if not self.own_trigger_context_overlap_allowed and any(
                start < self.end_char and end > self.start_char for start, end in intervals
            ):
                raise ValueError("Segmentation provider context overlaps its trigger")
        return self


class SegmentationAnchoredEvidenceRange(BaseModel):
    model_config = _CONFIG

    start_unit_id: str = Field(pattern=r"^u[0-9]{4}$")
    end_unit_id: str = Field(pattern=r"^u[0-9]{4}$")


class SegmentationAnchoredProviderSegment(BaseModel):
    model_config = _CONFIG

    start_unit_id: str = Field(pattern=r"^u[0-9]{4}$")
    end_unit_id: str = Field(pattern=r"^u[0-9]{4}$")
    primary_decision_family: Literal[
        "idea", "experiment", "evidence", "writing", "review", "visual", "cannot-assess"
    ]
    atomic_decision_statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    uncertainty: Literal["low", "medium", "high"]


class SegmentationAnchoredProviderSegmentV15(BaseModel):
    model_config = _CONFIG

    trigger_range: SegmentationAnchoredEvidenceRange
    context_ranges: tuple[SegmentationAnchoredEvidenceRange, ...] = Field(max_length=8)
    primary_decision_family: Literal[
        "idea", "experiment", "evidence", "writing", "review", "visual", "cannot-assess"
    ]
    atomic_decision_statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    uncertainty: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def cannot_assess_is_uncertain(self) -> SegmentationAnchoredProviderSegmentV15:
        if self.primary_decision_family == "cannot-assess" and self.uncertainty != "high":
            raise ValueError("cannot-assess decision segments require high uncertainty")
        return self


class SegmentationAnchoredProviderItem(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    segments: tuple[SegmentationAnchoredProviderSegment, ...] = Field(min_length=1, max_length=128)
    residual_decision_bearing_text_possible: bool


class SegmentationAnchoredProviderItemV15(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    segments: tuple[SegmentationAnchoredProviderSegmentV15, ...] = Field(
        min_length=0, max_length=128
    )
    no_decision_rationale: str | None = Field(min_length=1, max_length=2_000)
    residual_decision_bearing_text_possible: bool

    @model_validator(mode="after")
    def zero_decision_rationale_is_conditional(self) -> SegmentationAnchoredProviderItemV15:
        if (not self.segments) != (self.no_decision_rationale is not None):
            raise ValueError("Exactly zero segments require exactly one no-decision rationale")
        return self


class SegmentationAnchoredProviderOutput(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationAnchoredProviderItem, ...] = Field(min_length=1)


class SegmentationAnchoredProviderOutputV15(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationAnchoredProviderItemV15, ...] = Field(min_length=1)


class SegmentationAnchoredAdjudicationProviderItem(SegmentationAnchoredProviderItem):
    resolution_rationale: str = Field(min_length=1, max_length=4_000)


class SegmentationAnchoredAdjudicationProviderOutput(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationAnchoredAdjudicationProviderItem, ...] = Field(min_length=1)


class SegmentationAnchoredAdjudicationProviderItemV15(SegmentationAnchoredProviderItemV15):
    resolution_rationale: str = Field(min_length=1, max_length=4_000)


class SegmentationAnchoredAdjudicationProviderOutputV15(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationAnchoredAdjudicationProviderItemV15, ...] = Field(min_length=1)


class SegmentationProviderItem(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    segments: tuple[SegmentationProviderSegment, ...] = Field(min_length=0, max_length=128)
    no_decision_rationale: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        exclude_if=lambda value: value is None,
    )
    residual_decision_bearing_text_possible: bool

    @model_validator(mode="after")
    def zero_decision_rationale_is_conditional(self) -> SegmentationProviderItem:
        if (not self.segments) != (self.no_decision_rationale is not None):
            raise ValueError("Exactly zero segments require exactly one no-decision rationale")
        return self


class SegmentationProviderOutput(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationProviderItem, ...] = Field(min_length=1)


class SegmentationAdjudicationProviderItem(SegmentationProviderItem):
    resolution_rationale: str = Field(min_length=1, max_length=4_000)


class SegmentationAdjudicationProviderOutput(BaseModel):
    model_config = _CONFIG

    items: tuple[SegmentationAdjudicationProviderItem, ...] = Field(min_length=1)


class SegmentationCalibrationMetrics(BaseModel):
    model_config = _CONFIG

    overlap_span_f1_micros: int = Field(ge=0, le=1_000_000)
    overlap_matched_family_agreement_micros: int = Field(ge=0, le=1_000_000)
    adjudication_item_rate_micros: int = Field(ge=0, le=1_000_000)
    residual_risk_item_rate_after_adjudication_micros: int = Field(ge=0, le=1_000_000)
    decision_presence_agreement_micros: int | None = Field(
        default=None, ge=0, le=1_000_000, exclude_if=lambda value: value is None
    )
    exact_trigger_context_set_agreement_micros: int | None = Field(
        default=None, ge=0, le=1_000_000, exclude_if=lambda value: value is None
    )
    all_frozen_thresholds_passed: bool

    @model_validator(mode="after")
    def thresholds_are_exact(self) -> SegmentationCalibrationMetrics:
        passed = (
            self.overlap_span_f1_micros >= 800_000
            and self.overlap_matched_family_agreement_micros >= 800_000
            and self.adjudication_item_rate_micros <= 500_000
            and self.residual_risk_item_rate_after_adjudication_micros == 0
            and (
                self.decision_presence_agreement_micros is None
                or self.decision_presence_agreement_micros >= 800_000
            )
        )
        if self.all_frozen_thresholds_passed != passed:
            raise ValueError("Segmentation calibration threshold summary drifted")
        return self


class SegmentationRunArtifactBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationRunArtifactBinding:
        _safe_locator(self.locator)
        return self


class TasteSourceSegmentationCalibrationReceipt(BaseModel):
    """Closed calibration evidence; it never authorizes population scale by itself."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    run_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    authorization_sha256: str = Field(pattern=_SHA256)
    protocol_file_sha256: str = Field(pattern=_SHA256)
    request_pack_sha256: str = Field(pattern=_SHA256)
    started_at: datetime
    completed_at: datetime
    provider: str = Field(pattern=_ID)
    requested_model: str = Field(min_length=1, max_length=500)
    returned_models: tuple[str, ...] = Field(min_length=1)
    identity_attestation: SegmentationRunArtifactBinding
    identity_report: ApiIdentityWindowReport
    call_receipts: tuple[SegmentationProviderCallReceipt, ...] = Field(min_length=6, max_length=100)
    segmenter_firewall_receipts: tuple[SegmentationInputFirewallReceipt, ...] = Field(
        min_length=4, max_length=96
    )
    adjudication_firewall_receipts: tuple[SegmentationAdjudicationInputFirewallReceipt, ...] = (
        Field(max_length=96)
    )
    segmenter_a: SegmentationRunArtifactBinding
    segmenter_b: SegmentationRunArtifactBinding
    agreement: SegmentationRunArtifactBinding
    resolution: SegmentationRunArtifactBinding
    metrics: SegmentationCalibrationMetrics
    group_uncertainty: TasteSourceSegmentationGroupUncertainty | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    request_count: int = Field(ge=6, le=100)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0, allow_inf_nan=False)
    provider_retry_performed: Literal[False] = False
    ai_integrity_audit_complete: Literal[False] = False
    ai_authority_audit_complete: Literal[False] = False
    scale_gate_passed: Literal[False] = False
    scaled_ai_segmentation_execution_authorized: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> TasteSourceSegmentationCalibrationReceipt:
        if (
            self.started_at.utcoffset() is None
            or self.completed_at.utcoffset() is None
            or self.completed_at < self.started_at
        ):
            raise ValueError("Segmentation calibration times are invalid")
        if self.request_count != len(self.call_receipts):
            raise ValueError("Segmentation calibration request count drifted")
        if self.input_tokens != sum(item.call.input_tokens for item in self.call_receipts):
            raise ValueError("Segmentation calibration input-token count drifted")
        if self.output_tokens != sum(item.call.output_tokens for item in self.call_receipts):
            raise ValueError("Segmentation calibration output-token count drifted")
        observed_cost = sum(item.estimated_cost_cny for item in self.call_receipts)
        if abs(self.estimated_cost_cny - observed_cost) > 1e-9:
            raise ValueError("Segmentation calibration estimated cost drifted")
        if (self.schema_version == "1.1") != (self.group_uncertainty is not None):
            raise ValueError("Segmentation calibration schema differs from group uncertainty")
        workload_calls = tuple(
            item for item in self.call_receipts if item.call.role is ApiIdentityCallRole.WORKLOAD
        )
        sentinel_calls = tuple(
            item
            for item in self.call_receipts
            if item.call.role is not ApiIdentityCallRole.WORKLOAD
        )
        if len(sentinel_calls) != 2:
            raise ValueError("Segmentation calibration requires start and end sentinels")
        if (
            tuple(item.call.sequence for item in self.call_receipts)
            != tuple(range(1, len(self.call_receipts) + 1))
            or self.call_receipts[0].call.role is not ApiIdentityCallRole.START_SENTINEL
            or self.call_receipts[-1].call.role is not ApiIdentityCallRole.END_SENTINEL
            or any(
                item.call.role is not ApiIdentityCallRole.WORKLOAD
                for item in self.call_receipts[1:-1]
            )
        ):
            raise ValueError("Segmentation calibration call topology drifted")
        workload_packet_ids = tuple(item.packet_id for item in workload_calls)
        firewall_packet_ids = tuple(
            item.packet_id
            for item in (
                *self.segmenter_firewall_receipts,
                *self.adjudication_firewall_receipts,
            )
        )
        if (
            len(workload_packet_ids) != len(set(workload_packet_ids))
            or len(firewall_packet_ids) != len(set(firewall_packet_ids))
            or set(workload_packet_ids) != set(firewall_packet_ids)
        ):
            raise ValueError("Segmentation workload firewall coverage drifted")
        workload_by_packet = {item.packet_id: item for item in workload_calls}
        if any(
            (
                workload_by_packet[item.packet_id].call.request_sha256,
                workload_by_packet[item.packet_id].packet_sha256,
                workload_by_packet[item.packet_id].call.raw_request_ref,
            )
            != (
                item.raw_request_sha256,
                item.packet_sha256,
                item.raw_request_ref,
            )
            for item in (
                *self.segmenter_firewall_receipts,
                *self.adjudication_firewall_receipts,
            )
        ):
            raise ValueError("Segmentation firewall and provider request hashes differ")
        observed_returned_models = tuple(
            dict.fromkeys(item.call.returned_model for item in self.call_receipts)
        )
        if (
            not self.identity_report.admitted
            or self.identity_report.attestation_sha256 != self.identity_attestation.semantic_sha256
            or self.identity_report.call_count != len(self.call_receipts)
            or self.identity_report.sentinel_count != len(sentinel_calls)
            or self.identity_report.returned_model_ids != observed_returned_models
            or self.returned_models != observed_returned_models
        ):
            raise ValueError("Segmentation identity report differs from call evidence")
        if self.schema_version == "1.1":
            uncertainty = self.group_uncertainty
            assert uncertainty is not None
            if (
                any(item.schema_version != "1.1" for item in self.call_receipts)
                or any(item.anchor_ranges_verified is not True for item in workload_calls)
                or any(item.anchor_ranges_verified is not None for item in sentinel_calls)
                or self.metrics.decision_presence_agreement_micros is None
                or self.metrics.exact_trigger_context_set_agreement_micros
                != (
                    uncertainty.exact_trigger_context_set_agreement.point_micros
                    if uncertainty.exact_trigger_context_set_agreement is not None
                    else None
                )
                or self.metrics.overlap_span_f1_micros
                != uncertainty.overlap_trigger_span_f1.point_micros
                or self.metrics.overlap_matched_family_agreement_micros
                != uncertainty.overlap_matched_family_agreement.point_micros
                or self.metrics.decision_presence_agreement_micros
                != uncertainty.decision_presence_agreement.point_micros
                or self.metrics.adjudication_item_rate_micros
                != uncertainty.adjudication_item_rate.point_micros
            ):
                raise ValueError("Segmentation schema-1.1 calibration evidence drifted")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("Segmentation calibration receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceSegmentationCalibrationReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class SegmentationInputFirewallReceipt(BaseModel):
    """Runner observation about bytes sent; it is not a model attestation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    packet_id: str = Field(pattern=_ID)
    packet_sha256: str = Field(pattern=_SHA256)
    raw_request_ref: str = Field(min_length=1, max_length=1_000)
    raw_request_sha256: str = Field(pattern=_SHA256)
    request_persisted_before_provider_contact: Literal[True] = True
    structured_source_identity_fields_absent: Literal[True] = True
    explicit_outcome_fields_absent: Literal[True] = True
    other_segmenter_output_absent: Literal[True] = True
    provider_tools_absent: Literal[True] = True
    outbound_endpoint_allowlisted: Literal[True] = True
    parametric_source_recognition_ruled_out: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationInputFirewallReceipt:
        _safe_locator(self.raw_request_ref)
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class SegmentationAdjudicationInputFirewallReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    packet_id: str = Field(pattern=_ID)
    packet_sha256: str = Field(pattern=_SHA256)
    raw_request_ref: str = Field(min_length=1, max_length=1_000)
    raw_request_sha256: str = Field(pattern=_SHA256)
    request_persisted_before_provider_contact: Literal[True] = True
    disputed_items_only: Literal[True] = True
    anonymous_candidate_order: Literal[True] = True
    segmenter_slot_identities_absent: Literal[True] = True
    structured_source_identity_fields_absent: Literal[True] = True
    explicit_outcome_fields_absent: Literal[True] = True
    provider_tools_absent: Literal[True] = True
    outbound_endpoint_allowlisted: Literal[True] = True
    parametric_source_recognition_ruled_out: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationAdjudicationInputFirewallReceipt:
        _safe_locator(self.raw_request_ref)
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class SegmentationSpanReconstructionReceipt(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    segment_ordinal: int = Field(ge=1, le=128)
    algorithm: Literal["unicode-typography-normalized-unique-match-v1"]
    provider_text_sha256: str = Field(pattern=_SHA256)
    source_text_sha256: str = Field(pattern=_SHA256)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    changed_codepoint_count: int = Field(gt=0)
    unique_normalized_match_verified: Literal[True] = True
    original_source_slice_restored: Literal[True] = True
    fuzzy_matching_performed: Literal[False] = False


class SegmentationEvidenceUnitSelectionReceipt(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    segment_ordinal: int = Field(ge=1, le=128)
    range_role: Literal["trigger", "context"] = Field(
        default="trigger", exclude_if=lambda value: value == "trigger"
    )
    context_ordinal: int | None = Field(
        default=None, ge=1, le=8, exclude_if=lambda value: value is None
    )
    algorithm: Literal["unicode-word-punctuation-v1"]
    start_unit_id: str = Field(pattern=r"^u[0-9]{4}$")
    end_unit_id: str = Field(pattern=r"^u[0-9]{4}$")
    source_comment_sha256: str = Field(pattern=_SHA256)
    evidence_unit_table_sha256: str = Field(pattern=_SHA256)
    source_text_sha256: str = Field(pattern=_SHA256)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    exact_source_slice_restored: Literal[True] = True
    provider_span_text_field_received: Literal[False] = False
    normalization_performed: Literal[False] = False
    fuzzy_matching_performed: Literal[False] = False

    @model_validator(mode="after")
    def role_is_consistent(self) -> SegmentationEvidenceUnitSelectionReceipt:
        if (self.range_role == "context") != (self.context_ordinal is not None):
            raise ValueError("Segmentation evidence range role differs from its ordinal")
        return self


class SegmentationEvidenceUnitItemReceipt(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    source_comment_sha256: str = Field(pattern=_SHA256)
    evidence_unit_table_sha256: str = Field(pattern=_SHA256)
    segment_count: int = Field(ge=0, le=128)
    zero_decision: bool
    no_decision_rationale_sha256: str | None = Field(default=None, pattern=_SHA256)
    residual_decision_bearing_text_possible: bool

    @model_validator(mode="after")
    def zero_decision_is_receipted(self) -> SegmentationEvidenceUnitItemReceipt:
        if self.zero_decision != (self.segment_count == 0):
            raise ValueError("Segmentation item receipt zero-decision status drifted")
        if self.zero_decision != (self.no_decision_rationale_sha256 is not None):
            raise ValueError("Segmentation item receipt lacks its no-decision rationale hash")
        return self


class SegmentationProviderTransportReceipt(BaseModel):
    """Provider envelope and billing evidence persisted before task validation."""

    model_config = _CONFIG

    sequence: int = Field(ge=1, le=100)
    role: ApiIdentityCallRole
    packet_id: str | None = Field(default=None, pattern=_ID)
    request_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    raw_request_ref: str = Field(min_length=1, max_length=1_000)
    raw_response_ref: str = Field(min_length=1, max_length=1_000)
    http_status: int = Field(ge=100, le=599)
    client_request_id: str = Field(min_length=1, max_length=64)
    echoed_request_id: str = Field(min_length=1, max_length=64)
    provider_task_id: str = Field(min_length=1, max_length=500)
    returned_model: str = Field(min_length=1, max_length=200)
    request_started_at: datetime
    response_completed_at: datetime
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0, allow_inf_nan=False)
    request_id_echo_passed: bool
    model_allowlist_passed: bool
    semantic_validation_performed: Literal[False] = False
    retry_count: Literal[0] = 0

    @model_validator(mode="after")
    def transport_is_consistent(self) -> SegmentationProviderTransportReceipt:
        if (
            self.request_started_at.utcoffset() is None
            or self.response_completed_at.utcoffset() is None
            or self.response_completed_at < self.request_started_at
        ):
            raise ValueError("Segmentation transport receipt times are invalid")
        if self.request_id_echo_passed != (self.client_request_id == self.echoed_request_id):
            raise ValueError("Segmentation transport request-ID result drifted")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("Segmentation transport cached input exceeds total input")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Segmentation transport total-token count drifted")
        _safe_locator(self.raw_request_ref)
        _safe_locator(self.raw_response_ref)
        return self


class SegmentationProviderCallReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = Field(
        default="1.0", exclude_if=lambda value: value == "1.0"
    )
    call: ApiIdentityCallReceipt
    packet_id: str | None = Field(default=None, pattern=_ID)
    packet_sha256: str | None = Field(default=None, pattern=_SHA256)
    client_request_id: str = Field(min_length=1, max_length=64)
    echoed_request_id: str = Field(min_length=1, max_length=64)
    provider_task_id: str = Field(min_length=1, max_length=500)
    raw_provider_response_sha256: str = Field(pattern=_SHA256)
    output_object_sha256: str = Field(pattern=_SHA256)
    cached_input_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0, allow_inf_nan=False)
    span_reconstruction_receipts: tuple[SegmentationSpanReconstructionReceipt, ...] = ()
    evidence_unit_selection_receipts: tuple[SegmentationEvidenceUnitSelectionReceipt, ...] = ()
    evidence_unit_item_receipts: tuple[SegmentationEvidenceUnitItemReceipt, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    assigned_item_count: int | None = Field(
        default=None, ge=1, exclude_if=lambda value: value is None
    )
    retry_count: Literal[0] = 0
    response_schema_verified: Literal[True] = True
    assigned_item_set_verified: Literal[True] = True
    verbatim_spans_verified: bool | None = Field(
        default=True, exclude_if=lambda value: value is None
    )
    anchor_ranges_verified: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    identity_sentinel_output_verified: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def role_matches_packet(self) -> SegmentationProviderCallReceipt:
        workload = self.call.role is ApiIdentityCallRole.WORKLOAD
        if workload != (self.packet_id is not None and self.packet_sha256 is not None):
            raise ValueError("Segmentation workload receipt packet binding is inconsistent")
        if self.echoed_request_id != self.client_request_id:
            raise ValueError("Segmentation provider did not echo the client request ID")
        if self.cached_input_tokens > self.call.input_tokens:
            raise ValueError("Segmentation cached input exceeds total input tokens")
        if self.total_tokens != self.call.input_tokens + self.call.output_tokens:
            raise ValueError("Segmentation provider total-token count drifted")
        if (
            self.raw_provider_response_sha256 != self.call.response_sha256
            or self.provider_task_id != self.call.provider_request_id
        ):
            raise ValueError("Segmentation provider transport bindings drifted")
        if not workload:
            if (
                self.anchor_ranges_verified is not None
                or self.assigned_item_count is not None
                or self.span_reconstruction_receipts
                or self.evidence_unit_selection_receipts
                or self.evidence_unit_item_receipts
            ):
                raise ValueError("Segmentation sentinel cannot claim source-range validation")
            if self.schema_version == "1.1" and self.identity_sentinel_output_verified is not True:
                raise ValueError("Segmentation sentinel lacks exact-output verification")
            return self
        if self.identity_sentinel_output_verified is not None:
            raise ValueError("Segmentation workload cannot claim sentinel verification")
        if self.schema_version == "1.1" and self.anchor_ranges_verified is not True:
            raise ValueError("Schema-1.1 workload lacks evidence-unit validation")
        if self.anchor_ranges_verified is True:
            if self.verbatim_spans_verified is not None or self.span_reconstruction_receipts:
                raise ValueError("Evidence-unit validation cannot claim verbatim-span validation")
            item_receipts = {
                (item.campaign_token, item.review_item_id): item
                for item in self.evidence_unit_item_receipts
            }
            if not item_receipts or len(item_receipts) != len(self.evidence_unit_item_receipts):
                raise ValueError("Segmentation anchored workload item receipts are incomplete")
            if self.assigned_item_count != len(item_receipts):
                raise ValueError("Segmentation anchored assigned-item count drifted")
            ranges_by_item: dict[
                tuple[str, str], list[SegmentationEvidenceUnitSelectionReceipt]
            ] = {key: [] for key in item_receipts}
            for receipt in self.evidence_unit_selection_receipts:
                key = (receipt.campaign_token, receipt.review_item_id)
                if key not in ranges_by_item:
                    raise ValueError("Segmentation range receipt names an unreceipted item")
                item_receipt = item_receipts[key]
                if (
                    receipt.source_comment_sha256 != item_receipt.source_comment_sha256
                    or receipt.evidence_unit_table_sha256 != item_receipt.evidence_unit_table_sha256
                ):
                    raise ValueError("Segmentation range and item receipts bind different sources")
                ranges_by_item[key].append(receipt)
            for key, item_receipt in item_receipts.items():
                ranges = ranges_by_item[key]
                triggers = [item for item in ranges if item.range_role == "trigger"]
                if [item.segment_ordinal for item in triggers] != list(
                    range(1, item_receipt.segment_count + 1)
                ):
                    raise ValueError("Segmentation trigger receipts differ from segment count")
                if item_receipt.zero_decision and ranges:
                    raise ValueError("Zero-decision item cannot carry range receipts")
                for segment_ordinal in range(1, item_receipt.segment_count + 1):
                    contexts = [
                        item
                        for item in ranges
                        if item.range_role == "context" and item.segment_ordinal == segment_ordinal
                    ]
                    if [item.context_ordinal for item in contexts] != list(
                        range(1, len(contexts) + 1)
                    ):
                        raise ValueError("Segmentation context receipt ordinals are not contiguous")
                if any(
                    item.range_role == "context"
                    and item.segment_ordinal > item_receipt.segment_count
                    for item in ranges
                ):
                    raise ValueError("Segmentation context receipt names an absent segment")
        elif (
            self.anchor_ranges_verified is not None
            or self.evidence_unit_item_receipts
            or self.assigned_item_count is not None
        ):
            raise ValueError("Legacy workload cannot carry schema-1.5 item receipts")
        elif self.verbatim_spans_verified is not True:
            raise ValueError("Legacy workload lacks verbatim-span validation")
        return self


TasteSourceSegmentationCalibrationReceipt.model_rebuild()


class SegmentationExecutionLedger(BaseModel):
    """One-time replay guard updated before and after every provider call."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    authorization_sha256: str = Field(pattern=_SHA256)
    run_id: str = Field(pattern=_ID)
    one_time_nonce: str = Field(pattern=_ID)
    status: Literal["claimed", "provider-call-pending", "failed", "complete"]
    completed_sequences: tuple[int, ...]
    pending_sequence: int | None = Field(default=None, ge=1)
    pending_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    failed_sequence: int | None = Field(default=None, ge=1)
    failed_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    failed_response_sha256: str | None = Field(default=None, pattern=_SHA256)
    failed_http_status: int | None = Field(default=None, ge=100, le=599)
    failed_raw_request_ref: str | None = Field(default=None, max_length=1_000)
    failed_raw_response_ref: str | None = Field(default=None, max_length=1_000)
    provider_call_may_have_started: bool
    updated_at: datetime

    @model_validator(mode="after")
    def state_is_consistent(self) -> SegmentationExecutionLedger:
        if self.updated_at.utcoffset() is None:
            raise ValueError("Segmentation ledger timestamp must include a timezone")
        if self.completed_sequences != tuple(range(1, len(self.completed_sequences) + 1)):
            raise ValueError("Segmentation ledger completed calls are not contiguous")
        pending = self.status == "provider-call-pending"
        has_pending_binding = (
            self.pending_sequence is not None and self.pending_request_sha256 is not None
        )
        if pending != has_pending_binding or (pending and not self.provider_call_may_have_started):
            raise ValueError("Segmentation ledger pending state is inconsistent")
        if pending and self.pending_sequence != len(self.completed_sequences) + 1:
            raise ValueError("Segmentation ledger pending sequence is not next")
        if not pending and has_pending_binding:
            raise ValueError("Segmentation ledger closed state retains pending call")
        if self.status in {"claimed", "complete"} and self.provider_call_may_have_started:
            raise ValueError("Segmentation ledger non-failure state retains call uncertainty")
        failure_fields = (
            self.failed_sequence,
            self.failed_request_sha256,
            self.failed_response_sha256,
            self.failed_http_status,
            self.failed_raw_request_ref,
            self.failed_raw_response_ref,
        )
        if self.status != "failed" and any(value is not None for value in failure_fields):
            raise ValueError("Segmentation non-failure ledger retains failure evidence")
        for locator in (self.failed_raw_request_ref, self.failed_raw_response_ref):
            if locator is not None:
                _safe_locator(locator)
        return self


class ProviderHTTPResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int = Field(ge=100, le=599)
    headers: dict[str, str]
    content: bytes = Field(max_length=_MAX_RESPONSE_BYTES)


class ExtractedProviderResponse(BaseModel):
    model_config = _CONFIG

    text: str
    returned_model: str = Field(min_length=1, max_length=200)
    client_request_id: str = Field(min_length=1, max_length=64)
    provider_task_id: str = Field(min_length=1, max_length=500)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def usage_is_consistent(self) -> ExtractedProviderResponse:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("Cached provider input exceeds prompt tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Provider total-token count is inconsistent")
        return self


class ProviderHTTPTransport(Protocol):
    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout_seconds: float,
        maximum_response_bytes: int,
    ) -> ProviderHTTPResponse: ...


class LiveProviderHTTPTransport:
    """One-attempt byte-preserving HTTP transport."""

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout_seconds: float,
        maximum_response_bytes: int,
    ) -> ProviderHTTPResponse:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
            with client.stream("POST", endpoint, headers=headers, content=content) as response:
                chunks: list[bytes] = []
                observed = 0
                for chunk in response.iter_bytes():
                    observed += len(chunk)
                    if observed > maximum_response_bytes:
                        raise ValueError("Segmentation provider response exceeds its byte ceiling")
                    chunks.append(chunk)
                return ProviderHTTPResponse(
                    status_code=response.status_code,
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    content=b"".join(chunks),
                )


def _verify_precontact_execution_gate(
    *,
    root: Path,
    authorization: TasteSourceSegmentationExecutionAuthorization,
    protocol: TasteSourceSegmentationProtocolInspection,
    request_pack: TasteSourceSegmentationRequestPack,
) -> None:
    """Replay the AI-only precontact seal as a mandatory live-execution gate."""

    amendment_path = _bound_path(root, authorization.routing_amendment)
    amendment = _yaml_mapping(amendment_path, "segmentation routing amendment")
    if (
        amendment.get("schema_version") != "1.0"
        or amendment.get("project_id") != authorization.project_id
        or amendment.get("routing_contract") != "decision-boundary-only-v2"
        or amendment.get("provider_contact_performed") is not False
        or amendment.get("sample_or_outcome_changed") is not False
        or amendment.get("base_protocol") != authorization.protocol.model_dump(mode="json")
        or amendment.get("base_freeze_receipt")
        != authorization.freeze_receipt.model_dump(mode="json")
        or amendment.get("request_pack") != authorization.request_pack.model_dump(mode="json")
        or amendment.get("adjudication_blocker_fields")
        != [
            "decision-presence",
            "segment-count",
            "trigger-boundary",
            "context-range-set",
            "primary-decision-family",
            "residual-decision-risk",
        ]
        or amendment.get("diagnostic_only_fields")
        != [
            "atomic-decision-statement",
            "rationale",
            "uncertainty",
            "no-decision-rationale",
        ]
    ):
        raise ValueError("Segmentation routing amendment is not the frozen v2 contract")
    amendment_authority = amendment.get("authority")
    if not isinstance(amendment_authority, dict) or any(
        amendment_authority.get(field) is not False
        for field in (
            "authorizes_provider_contact",
            "authorizes_calibration_execution",
            "authorizes_scaled_execution",
            "authorizes_benchmark_admission",
            "formal_evidence_eligible",
            "human_review_claim_allowed",
        )
    ):
        raise ValueError("Segmentation routing amendment overclaims authority")

    seal_path = _bound_path(root, authorization.precontact_audit_seal)
    seal = _yaml_mapping(seal_path, "segmentation precontact audit seal")
    if (
        seal.get("schema_version") != "1.0"
        or seal.get("seal_id") != "scitastebench-segmentation-precontact-audit-seal-v2"
        or seal.get("project_id") != authorization.project_id
        or seal.get("protocol") != authorization.protocol.model_dump(mode="json")
        or seal.get("freeze_receipt") != authorization.freeze_receipt.model_dump(mode="json")
        or seal.get("request_pack") != authorization.request_pack.model_dump(mode="json")
        or seal.get("routing_amendment") != authorization.routing_amendment.model_dump(mode="json")
        or seal.get("execution_runner") != authorization.runner.model_dump(mode="json")
    ):
        raise ValueError("Segmentation precontact seal differs from execution authority")

    predecessor_binding = SegmentationExecutionFileBinding.model_validate(
        seal.get("predecessor_seal")
    )
    predecessor_path = _bound_path(root, predecessor_binding)
    predecessor = _yaml_mapping(predecessor_path, "segmentation predecessor audit seal")
    _verify_predecessor_precontact_seal(
        root=root,
        predecessor=predecessor,
        authorization=authorization,
        protocol=protocol,
        request_pack=request_pack,
    )

    authority_review_binding = SegmentationExecutionFileBinding.model_validate(
        seal.get("ai_e_authority_review")
    )
    authority_review_path = _bound_path(root, authority_review_binding)
    authority_review = _yaml_mapping(authority_review_path, "segmentation AI-E authority review")
    exact_inputs = authority_review.get("exact_input_hashes")
    if (
        authority_review.get("role_id") != "ai-e-execution-authority"
        or authority_review.get("reviewer_kind") != "ai"
        or authority_review.get("not_human_review") is not True
        or authority_review.get("decision") != "pass"
        or authority_review.get("verdict") != "pass"
        or authority_review.get("blocker_codes") != []
        or authority_review.get("provider_contact_authorized") is not False
        or authority_review.get("provider_contact_performed") is not False
        or authority_review.get("external_api_calls_performed") is not False
        or authority_review.get("formal_evidence_eligible") is not False
        or authority_review.get("human_review_claim_allowed") is not False
        or not isinstance(exact_inputs, dict)
        or exact_inputs.get("predecessor_seal") != predecessor_binding.model_dump(mode="json")
        or exact_inputs.get("routing_amendment")
        != authorization.routing_amendment.model_dump(mode="json")
        or exact_inputs.get("execution_runner") != authorization.runner.model_dump(mode="json")
    ):
        raise ValueError("Segmentation AI-E authority review is not a bound pass")

    boundary = seal.get("execution_boundary")
    if (
        not isinstance(boundary, dict)
        or any(
            boundary.get(field) is not False
            for field in (
                "provider_contact_performed",
                "api_calls_authorized",
                "calibration_execution_authorized",
                "scaled_execution_authorized",
                "benchmark_admission_authorized",
                "formal_evidence_eligible",
                "human_review_claim_allowed",
            )
        )
        or boundary.get("fresh_exact_owner_authorization_required") is not True
    ):
        raise ValueError("Segmentation precontact seal execution boundary is invalid")
    scope = seal.get("required_authorization_scope")
    generation = protocol.protocol.generation
    limits = authorization.limits
    if not isinstance(scope, dict) or scope != {
        "provider": authorization.requested_provider,
        "model": authorization.requested_model,
        "unique_item_count": request_pack.unique_item_count,
        "segmenter_requests": generation.segmenter_total_requests,
        "maximum_adjudication_requests": generation.maximum_adjudication_shards,
        "identity_sentinel_requests": generation.identity_sentinel_requests,
        "maximum_provider_requests": limits.maximum_provider_requests,
        "maximum_input_tokens": limits.maximum_input_tokens,
        "maximum_output_tokens": limits.maximum_output_tokens,
        "retry_count": limits.retry_count,
        "owner_maximum_liability_usd": (authorization.price_ceiling.owner_maximum_liability_usd),
    }:
        raise ValueError("Segmentation precontact seal scope differs from authorization")


def _verify_predecessor_precontact_seal(
    *,
    root: Path,
    predecessor: dict[str, object],
    authorization: TasteSourceSegmentationExecutionAuthorization,
    protocol: TasteSourceSegmentationProtocolInspection,
    request_pack: TasteSourceSegmentationRequestPack,
) -> None:
    """Replay the original no-contact AI-D/AI-E evidence bound by seal v2."""

    if (
        predecessor.get("schema_version") != "1.0"
        or predecessor.get("seal_id") != "scitastebench-segmentation-precontact-audit-seal-v1"
        or predecessor.get("project_id") != authorization.project_id
        or predecessor.get("protocol") != authorization.protocol.model_dump(mode="json")
        or predecessor.get("freeze_receipt") != authorization.freeze_receipt.model_dump(mode="json")
        or predecessor.get("request_pack") != authorization.request_pack.model_dump(mode="json")
    ):
        raise ValueError("Segmentation predecessor seal differs from frozen inputs")

    deterministic_audit = predecessor.get("deterministic_audit_implementation")
    audit_module = next(
        (
            item
            for item in authorization.runner.runtime_modules
            if item.locator == "src/scitaste/evaluation/taste_source_segmentation_post_audit.py"
        ),
        None,
    )
    if (
        not isinstance(deterministic_audit, dict)
        or audit_module is None
        or deterministic_audit.get("locator") != audit_module.locator
        or deterministic_audit.get("file_sha256") != audit_module.file_sha256
        or not isinstance(deterministic_audit.get("git_commit"), str)
        or len(str(deterministic_audit["git_commit"])) != 40
        or not set(str(deterministic_audit["git_commit"])).issubset(set("0123456789abcdef"))
        or _git_blob_sha256(
            root,
            str(deterministic_audit["git_commit"]),
            audit_module.locator,
        )
        != audit_module.file_sha256
    ):
        raise ValueError("Segmentation sealed replay implementation drifted")

    ai_d = predecessor.get("ai_d_attempt_v2")
    if not isinstance(ai_d, dict) or (
        ai_d.get("reviewer_kind") != "ai"
        or ai_d.get("not_human_review") is not True
        or ai_d.get("verdict") != "inventory-complete"
        or ai_d.get("item_count") != request_pack.unique_item_count
        or ai_d.get("residual_risk_item_count") != 0
    ):
        raise ValueError("Segmentation AI-D precontact inventory did not pass")
    raw_binding = ai_d.get("raw_inventory")
    receipt_binding = ai_d.get("review_receipt")
    inventory_binding = ai_d.get("normalized_inventory")
    for label, binding in (
        ("AI-D raw inventory", raw_binding),
        ("AI-D review receipt", receipt_binding),
        ("AI-D normalized inventory", inventory_binding),
    ):
        if not isinstance(binding, dict) or not isinstance(binding.get("locator"), str):
            raise ValueError(f"Segmentation {label} binding is invalid")
        source = _bounded_file(root / _safe_locator(binding["locator"]), _MAX_PACKET_BYTES)
        if _sha256_file(source) != binding.get("file_sha256"):
            raise ValueError(f"Segmentation {label} file hash drifted")

    from scitaste.evaluation.taste_source_segmentation_post_audit import (
        load_taste_source_integrity_inventory,
        load_taste_source_integrity_review_receipt,
        normalize_taste_source_integrity_inventory,
    )

    assert isinstance(raw_binding, dict)
    assert isinstance(receipt_binding, dict)
    assert isinstance(inventory_binding, dict)
    raw_path = root / _safe_locator(str(raw_binding["locator"]))
    receipt_path = root / _safe_locator(str(receipt_binding["locator"]))
    inventory_path = root / _safe_locator(str(inventory_binding["locator"]))
    receipt = load_taste_source_integrity_review_receipt(receipt_path)
    inventory = load_taste_source_integrity_inventory(inventory_path)
    if (
        receipt.receipt_sha256 != receipt_binding.get("receipt_sha256")
        or inventory.inventory_sha256 != inventory_binding.get("inventory_sha256")
        or inventory.item_count != request_pack.unique_item_count
        or inventory.residual_risk_item_count != 0
        or inventory.project_id != authorization.project_id
        or inventory.request_pack.file_sha256 != authorization.request_pack.file_sha256
        or inventory.request_pack.semantic_sha256 != authorization.request_pack.pack_sha256
    ):
        raise ValueError("Segmentation AI-D sealed evidence differs from its seal")
    gate_path = root / _safe_locator(receipt.gate.locator)
    replayed = normalize_taste_source_integrity_inventory(
        raw_inventory_path=raw_path,
        request_pack_path=root / _safe_locator(authorization.request_pack.locator),
        gate_path=gate_path,
        review_receipt_path=receipt_path,
        inventory_id=inventory.inventory_id,
        locator_root=root,
    )
    if replayed != inventory:
        raise ValueError("Segmentation AI-D inventory replay differs from sealed inventory")

    ai_e = predecessor.get("ai_e_preexecution_review")
    if not isinstance(ai_e, dict):
        raise ValueError("Segmentation predecessor seal lacks AI-E review")
    ai_e_binding = SegmentationExecutionFileBinding.model_validate(ai_e.get("report"))
    ai_e_path = _bound_path(root, ai_e_binding)
    ai_e_report = _yaml_mapping(ai_e_path, "segmentation AI-E preexecution review")
    inputs = ai_e_report.get("exact_input_hashes")
    if (
        ai_e.get("reviewer_kind") != "ai"
        or ai_e.get("not_human_review") is not True
        or ai_e.get("decision") != "pass"
        or ai_e.get("blocker_codes") != []
        or ai_e_report.get("role_id") != "ai-e-protocol-authority"
        or ai_e_report.get("reviewer_kind") != "ai"
        or ai_e_report.get("not_human_review") is not True
        or ai_e_report.get("decision") != "pass"
        or ai_e_report.get("verdict") != "pass"
        or ai_e_report.get("blocker_codes") != []
        or ai_e_report.get("provider_contact_authorized") is not False
        or ai_e_report.get("provider_contact_performed") is not False
        or ai_e_report.get("external_api_calls_performed") is not False
        or not isinstance(inputs, dict)
        or inputs.get("protocol")
        != {
            **authorization.protocol.model_dump(mode="json"),
            "protocol_id": protocol.protocol.protocol_id,
            "schema_version": protocol.protocol.schema_version,
        }
        or inputs.get("freeze_receipt")
        != {
            **authorization.freeze_receipt.model_dump(mode="json"),
            "freeze_receipt_id": protocol.freeze_receipt.freeze_receipt_id,
            "schema_version": protocol.freeze_receipt.schema_version,
        }
        or inputs.get("request_pack")
        != {
            **authorization.request_pack.model_dump(mode="json"),
            "pack_id": request_pack.pack_id,
            "schema_version": request_pack.schema_version,
        }
    ):
        raise ValueError("Segmentation AI-E preexecution review is not a bound pass")


def _verify_owner_approval_receipt(
    *,
    root: Path,
    authorization: TasteSourceSegmentationExecutionAuthorization,
    protocol: TasteSourceSegmentationProtocolInspection,
    request_pack: TasteSourceSegmentationRequestPack,
) -> None:
    """Bind the procedural conversation approval to the exact live scope."""

    approval_path = _bound_path(root, authorization.approval_evidence)
    approval = _yaml_mapping(approval_path, "segmentation owner-approval receipt")
    generation = protocol.protocol.generation
    limits = authorization.limits
    expected_scope = {
        "provider": authorization.requested_provider,
        "model": authorization.requested_model,
        "unique_item_count": request_pack.unique_item_count,
        "segmenter_requests": generation.segmenter_total_requests,
        "maximum_adjudication_requests": generation.maximum_adjudication_shards,
        "identity_sentinel_requests": generation.identity_sentinel_requests,
        "maximum_provider_requests": limits.maximum_provider_requests,
        "maximum_input_tokens": limits.maximum_input_tokens,
        "maximum_output_tokens": limits.maximum_output_tokens,
        "retry_count": limits.retry_count,
        "maximum_estimated_cost_cny": (authorization.price_ceiling.maximum_estimated_cost_cny),
        "owner_maximum_liability_usd": (authorization.price_ceiling.owner_maximum_liability_usd),
    }
    authority = approval.get("authority")
    if (
        approval.get("schema_version") != "1.0"
        or approval.get("project_id") != authorization.project_id
        or approval.get("authorized_by") != authorization.authorized_by
        or approval.get("approval_origin") != authorization.approval_origin
        or approval.get("authorized_at") != authorization.authorized_at
        or approval.get("authorization_scope") != expected_scope
        or approval.get("human_identity_cryptographically_verified") is not False
        or approval.get("procedural_trust_root")
        != "project-owner-conversation-recorded-by-active-codex-session"
        or not isinstance(authority, dict)
        or authority.get("api_calls_authorized") is not True
        or authority.get("prospective_calibration_authorized") is not True
        or any(
            authority.get(field) is not False
            for field in (
                "scaled_execution_authorized",
                "benchmark_admission_authorized",
                "formal_effectiveness_claim_authorized",
                "human_review_claim_authorized",
            )
        )
    ):
        raise ValueError("Segmentation owner-approval receipt is invalid or scope-drifted")


def _yaml_mapping(path: Path, label: str) -> dict[str, object]:
    payload = yaml.safe_load(_bounded_file(path, _MAX_PACKET_BYTES).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a YAML mapping")
    return payload


def inspect_taste_source_segmentation_execution_authorization(
    *,
    authorization_path: str | Path,
    locator_root: str | Path,
    now: datetime | None = None,
) -> TasteSourceSegmentationExecutionInspection:
    """Verify exact execution authority without reading credentials or using the network."""

    root = Path(locator_root).resolve(strict=True)
    source = _bounded_file(Path(authorization_path), _MAX_AUTHORIZATION_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Segmentation execution authorization must contain a YAML mapping")
    authorization = TasteSourceSegmentationExecutionAuthorization.model_validate(payload)
    observed_now = now or datetime.now().astimezone()
    if observed_now.utcoffset() is None or not (
        authorization.authorized_at <= observed_now <= authorization.expires_at
    ):
        raise ValueError("Segmentation execution authorization is outside its validity window")

    protocol_path = _bound_path(root, authorization.protocol)
    freeze_path = _bound_path(root, authorization.freeze_receipt)
    protocol = inspect_taste_source_segmentation_protocol(
        protocol_path=protocol_path,
        freeze_receipt_path=freeze_path,
        locator_root=root,
    )
    if (
        protocol.protocol.schema_version not in {"1.1", "1.2", "1.4", "1.5"}
        or protocol.protocol.adjudication_input_firewall is None
    ):
        raise ValueError(
            "Live segmentation execution requires a separately frozen adjudication firewall"
        )
    pack_path = _bound_path(root, authorization.request_pack)
    pack = load_taste_source_segmentation_request_pack(pack_path)
    if pack.pack_sha256 != authorization.request_pack.pack_sha256:
        raise ValueError("Segmentation execution request-pack semantic hash drifted")
    if (
        pack.project_id != authorization.project_id
        or pack.protocol_file_sha256 != protocol.protocol_file_sha256
        or pack.freeze_receipt_file_sha256 != protocol.freeze_receipt_file_sha256
        or pack.sample_sha256 != protocol.sample.sample_sha256
    ):
        raise ValueError("Segmentation execution pack differs from the frozen protocol")
    expected_pack_schema = {
        "1.4": "1.1",
        "1.5": "1.2",
    }.get(protocol.protocol.schema_version, "1.0")
    if pack.schema_version != expected_pack_schema:
        raise ValueError("Segmentation execution pack anchor schema differs from protocol")
    if protocol.protocol.schema_version in {"1.4", "1.5"} and any(
        timestamp > authorization.authorized_at
        for timestamp in (
            protocol.protocol.protocol_created_at,
            protocol.freeze_receipt.frozen_at,
            pack.created_at,
        )
    ):
        raise ValueError("Segmentation execution authorization predates frozen metadata")

    resource_path = _bound_path(root, authorization.provider_resource)
    _bound_path(root, authorization.official_catalog_snapshot)
    resource_payload = yaml.safe_load(resource_path.read_text(encoding="utf-8"))
    if not isinstance(resource_payload, dict):
        raise ValueError("Segmentation provider resource must contain a YAML mapping")
    resource = ApiModelDefinition.model_validate(resource_payload.get("resource"))
    identity_path = _bound_path(root, authorization.identity_protocol)
    identity = load_api_identity_protocol(identity_path)
    condition = protocol.protocol.model_condition
    if (
        authorization.requested_provider != condition.provider_id
        or authorization.requested_model != condition.requested_model_id
        or resource.provider_id != condition.provider_id
        or resource.resource_id != condition.resource_id
        or resource.model_id != condition.requested_model_id
        or resource.credential_env != authorization.credential_env
        or identity.file_sha256 != condition.identity_protocol_file_sha256
        or resource.interface != "openai-chat-completions"
    ):
        raise ValueError("Segmentation execution provider identity drifted")
    ledger_path = (root / _safe_locator(authorization.execution_ledger_locator)).resolve()
    output_path = (root / _safe_locator(authorization.run_output_locator)).resolve()
    for candidate in (ledger_path, output_path):
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("Segmentation execution target escapes its root") from error
    if ledger_path == output_path or output_path in ledger_path.parents:
        raise ValueError("Segmentation execution output and ledger targets overlap")

    runner_path = _bound_path(root, authorization.runner)
    cli_path = _bounded_file(
        root / _safe_locator(authorization.runner.cli_locator),
        _MAX_PACKET_BYTES,
    )
    if _sha256_file(cli_path) != authorization.runner.cli_file_sha256:
        raise ValueError("Segmentation execution CLI binding drifted")
    if (
        Path(__file__).resolve() != runner_path
        or _git_blob_sha256(root, authorization.runner.git_commit, authorization.runner.locator)
        != authorization.runner.file_sha256
        or _git_blob_sha256(root, authorization.runner.git_commit, authorization.runner.cli_locator)
        != authorization.runner.cli_file_sha256
        or _sha256_file(runner_path) != authorization.runner.file_sha256
    ):
        raise ValueError("Segmentation execution runner Git binding drifted")
    for module in authorization.runner.runtime_modules:
        module_path = _bound_path(root, module)
        if (
            _git_blob_sha256(root, authorization.runner.git_commit, module.locator)
            != module.file_sha256
            or _sha256_file(module_path) != module.file_sha256
        ):
            raise ValueError("Segmentation execution runtime-module binding drifted")
    _verify_runtime_source_tree(root, authorization.runner.git_commit)

    limits = authorization.limits
    frozen_budget = protocol.protocol.budget
    _bound_path(root, authorization.price_ceiling.pricing_snapshot)
    maximum_priced_cost_cny = (
        limits.maximum_input_tokens
        * authorization.price_ceiling.input_cache_miss_cny_per_million_tokens
        + limits.maximum_output_tokens * authorization.price_ceiling.output_cny_per_million_tokens
    ) / 1_000_000
    if (
        limits.maximum_provider_requests != frozen_budget.maximum_provider_requests
        or limits.maximum_input_tokens != frozen_budget.maximum_input_tokens
        or limits.maximum_output_tokens != frozen_budget.maximum_output_tokens
        or authorization.price_ceiling.owner_maximum_liability_usd
        != frozen_budget.maximum_api_cost_usd
        or limits.retry_count != protocol.protocol.generation.retry_count
        or pack.request_count != protocol.protocol.generation.segmenter_total_requests
        or maximum_priced_cost_cny > authorization.price_ceiling.maximum_estimated_cost_cny
    ):
        raise ValueError("Segmentation execution limits exceed the frozen protocol")
    if (
        authorization.price_ceiling.pricing_source_url
        != "https://docs.bigmodel.cn/cn/guide/start/pricing"
        or authorization.price_ceiling.input_cache_miss_cny_per_million_tokens != 0.8
        or authorization.price_ceiling.input_cache_hit_cny_per_million_tokens != 0.23
        or authorization.price_ceiling.output_cny_per_million_tokens != 2.8
    ):
        raise ValueError("Segmentation execution price observation differs from its source row")
    price_age_seconds = (
        authorization.authorized_at - authorization.price_ceiling.pricing_observed_at
    ).total_seconds()
    if price_age_seconds < 0 or price_age_seconds > 24 * 3_600:
        raise ValueError("Segmentation execution price ceiling is not contemporaneous")

    _verify_precontact_execution_gate(
        root=root,
        authorization=authorization,
        protocol=protocol,
        request_pack=pack,
    )
    _verify_owner_approval_receipt(
        root=root,
        authorization=authorization,
        protocol=protocol,
        request_pack=pack,
    )

    # Freeze every externally mutable execution input in memory before any ledger
    # claim.  The live runner must not reopen ignored output/config files after this
    # point: authorization applies to these exact bytes, not merely their paths.
    segmentation_rubric = snapshot_taste_source_segmentation_rubric(
        root / _safe_locator(protocol.protocol.segmentation_rubric.locator),
        locator_root=root,
    )
    adjudication_rubric = snapshot_taste_source_segmentation_rubric(
        root / _safe_locator(protocol.protocol.adjudication_rubric.locator),
        locator_root=root,
    )
    if (
        segmentation_rubric.locator != protocol.protocol.segmentation_rubric.locator
        or segmentation_rubric.file_sha256 != protocol.protocol.segmentation_rubric.file_sha256
        or adjudication_rubric.locator != protocol.protocol.adjudication_rubric.locator
        or adjudication_rubric.file_sha256 != protocol.protocol.adjudication_rubric.file_sha256
    ):
        raise ValueError("Segmentation execution rubric snapshot drifted")

    sample_inspection = TasteSourceSegmentationSampleInspection(
        path=root / protocol.protocol.sample.locator,
        file_sha256=protocol.protocol.sample.file_sha256,
        sample=protocol.sample,
    )
    sample = sample_inspection.sample
    campaign_snapshots = tuple(
        snapshot_taste_source_segmentation_campaign(root / locator, locator_root=root)
        for locator in sorted((sample.source_campaign_locators or {}).values())
    )
    campaigns_by_id = {snapshot.campaign.campaign_id: snapshot for snapshot in campaign_snapshots}
    if len(campaigns_by_id) != len(campaign_snapshots) or set(campaigns_by_id) != set(
        sample.source_campaign_locators or {}
    ):
        raise ValueError("Segmentation execution campaign snapshot coverage drifted")
    scientific_by_campaign: dict[str, dict[str, object]] = {}
    for campaign_id, snapshot in campaigns_by_id.items():
        campaign = snapshot.campaign
        if (
            snapshot.locator != (sample.source_campaign_locators or {})[campaign_id]
            or snapshot.file_sha256 != (sample.source_campaign_file_sha256s or {})[campaign_id]
            or campaign.campaign_sha256 != (sample.source_campaign_sha256s or {})[campaign_id]
            or snapshot.scientific_items_file_sha256
            != (sample.source_scientific_items_sha256s or {})[campaign_id]
        ):
            raise ValueError("Segmentation execution campaign snapshot drifted")
        scientific_by_campaign[campaign_id] = {
            item.review_item_id: item for item in snapshot.scientific_items
        }
    group_boundary = snapshot_taste_source_segmentation_group_boundary(
        sample_inspection=sample_inspection,
        sample_manifest_locator=protocol.protocol.sample.locator,
        campaign_snapshots=campaign_snapshots,
        locator_root=root,
    )
    if group_boundary is None:
        raise ValueError("Live segmentation execution requires a group-boundary snapshot")

    pack_root = pack_path.parent
    packets = []
    for binding in pack.requests:
        packet_path = _bounded_file(pack_root / binding.locator, _MAX_PACKET_BYTES)
        if _sha256_file(packet_path) != binding.file_sha256:
            raise ValueError("Segmentation execution packet file binding drifted")
        packet = load_taste_source_segmentation_request_packet(packet_path)
        if (
            packet.packet_sha256 != binding.packet_sha256
            or packet.segmenter_slot != binding.segmenter_slot
            or packet.shard_index != binding.shard_index
            or len(packet.items) != binding.item_count
            or packet.protocol_id != protocol.protocol.protocol_id
            or packet.requested_provider != authorization.requested_provider
            or packet.requested_model != authorization.requested_model
            or packet.rubric_file_sha256 != protocol.protocol.segmentation_rubric.file_sha256
            or packet.rubric != segmentation_rubric.payload
            or packet.shard_count != protocol.protocol.generation.segmenter_shards
            or len(packet.items) != protocol.protocol.generation.items_per_shard
            or packet.provider_tools_allowed
            or packet.provider_contact_performed
        ):
            raise ValueError("Segmentation execution packet differs from the frozen plan")
        packets.append(packet)
    anchor_contract = protocol.protocol.evidence_unit_selection
    if anchor_contract is not None and protocol.protocol.schema_version in {"1.4", "1.5"}:
        assert anchor_contract.system_instruction_sha256 is not None
        assert anchor_contract.output_contract_sha256 is not None
        for packet in packets:
            if (
                hashlib.sha256(packet.system_instruction.encode()).hexdigest()
                != anchor_contract.system_instruction_sha256
                or _canonical_sha256(packet.output_contract)
                != anchor_contract.output_contract_sha256
                or any(item.evidence_units is None for item in packet.items)
            ):
                raise ValueError("Segmentation anchored request contract drifted")
    expected_pairs = {
        (slot, shard)
        for slot in ("segmenter-a", "segmenter-b")
        for shard in range(1, protocol.protocol.generation.segmenter_shards + 1)
    }
    if {(item.segmenter_slot, item.shard_index) for item in packets} != expected_pairs:
        raise ValueError("Segmentation execution packet coverage drifted")
    token_to_campaign = {
        segmentation_campaign_token(pack.pack_id, campaign_id): campaign_id
        for campaign_id in campaigns_by_id
    }
    sample_keys = {(item.campaign_id, item.review_item_id) for item in sample.items}
    observed_by_slot: dict[str, set[tuple[str, str]]] = {
        "segmenter-a": set(),
        "segmenter-b": set(),
    }
    for packet in packets:
        for item in packet.items:
            campaign_id = token_to_campaign.get(item.campaign_token)
            scientific_source = (
                scientific_by_campaign.get(campaign_id, {}).get(item.review_item_id)
                if campaign_id is not None
                else None
            )
            if (
                scientific_source is None
                or (campaign_id, item.review_item_id) not in sample_keys
                or item.reviewed_abstract != scientific_source.reviewed_abstract
                or item.review_comment != scientific_source.review_comment
            ):
                raise ValueError("Segmentation packet source differs from campaign snapshot")
            observed_by_slot[packet.segmenter_slot].add((campaign_id, item.review_item_id))
    if any(keys != sample_keys for keys in observed_by_slot.values()):
        raise ValueError("Segmentation packet sample coverage drifted")
    return TasteSourceSegmentationExecutionInspection(
        authorization_path=source,
        authorization_file_sha256=_sha256_file(source),
        authorization=authorization,
        protocol=protocol,
        request_pack=pack,
        identity_protocol=identity,
        provider_resource=resource,
        sample=sample_inspection,
        packets=tuple(packets),
        segmentation_rubric=segmentation_rubric,
        adjudication_rubric=adjudication_rubric,
        campaigns=campaign_snapshots,
        group_boundary=group_boundary,
        packet_count=len(packets),
        unique_item_count=pack.unique_item_count,
    )


def build_segmentation_provider_request(
    packet: TasteSourceSegmentationRequestPacket,
    *,
    protocol: TasteSourceSegmentationProspectiveProtocol,
) -> dict[str, JsonValue]:
    """Build the exact structured provider payload from one frozen packet."""

    user_payload = {
        "rubric": packet.rubric,
        "items": [item.model_dump(mode="json", exclude_none=True) for item in packet.items],
        "output_contract": packet.output_contract,
    }
    return {
        "model": packet.requested_model,
        "request_id": f"stseg-{packet.packet_sha256[:32]}",
        "messages": [
            {"role": "system", "content": packet.system_instruction},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": protocol.generation.thinking},
        "reasoning_effort": protocol.generation.reasoning_effort,
        "temperature": protocol.generation.temperature,
        "max_tokens": protocol.generation.maximum_output_tokens_per_call,
        "stream": False,
    }


def validate_segmentation_provider_output(
    raw_text: str,
    *,
    packet: TasteSourceSegmentationRequestPacket,
    protocol: TasteSourceSegmentationProspectiveProtocol | None = None,
) -> SegmentationProviderOutput:
    """Validate exact item coverage and verbatim spans for one provider response."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        raise ValueError("Segmentation provider output must be a bare JSON object")
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError("Segmentation provider output is not valid JSON") from error
    if protocol is not None:
        expected_packet_schema = (
            "1.2"
            if protocol.schema_version == "1.5"
            else "1.1"
            if protocol.evidence_unit_selection is not None
            else "1.0"
        )
        if packet.schema_version != expected_packet_schema:
            raise ValueError("Segmentation protocol and request-packet schemas differ")
    expected = {(item.campaign_token, item.review_item_id): item for item in packet.items}
    if protocol is not None and protocol.evidence_unit_selection is not None:
        if protocol.schema_version == "1.5":
            anchored_output_v15 = SegmentationAnchoredProviderOutputV15.model_validate(payload)
            observed_v15 = [
                (item.campaign_token, item.review_item_id) for item in anchored_output_v15.items
            ]
            if len(observed_v15) != len(set(observed_v15)) or set(observed_v15) != set(expected):
                raise ValueError("Segmentation provider output item coverage drifted")
            return _resolve_anchored_provider_output_v15(
                anchored_output_v15,
                packet=packet,
                own_trigger_context_overlap_allowed=bool(
                    protocol.evidence_unit_selection
                    and protocol.evidence_unit_selection.own_trigger_context_overlap_allowed
                ),
            )
        anchored_output = SegmentationAnchoredProviderOutput.model_validate(payload)
        observed = [(item.campaign_token, item.review_item_id) for item in anchored_output.items]
        if len(observed) != len(set(observed)) or set(observed) != set(expected):
            raise ValueError("Segmentation provider output item coverage drifted")
        return _resolve_anchored_provider_output(anchored_output, packet=packet)
    output = SegmentationProviderOutput.model_validate(payload)
    if any(not item.segments for item in output.items):
        raise ValueError("Legacy segmentation provider output requires at least one segment")
    observed = [(item.campaign_token, item.review_item_id) for item in output.items]
    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise ValueError("Segmentation provider output item coverage drifted")
    if protocol is not None and protocol.span_reconstruction is not None:
        return _reconstruct_provider_spans(output, packet=packet)
    for item in output.items:
        source = expected[(item.campaign_token, item.review_item_id)].review_comment
        intervals: list[tuple[int, int]] = []
        for segment in item.segments:
            start = source.find(segment.verbatim_decision_text)
            if start < 0 or source.find(segment.verbatim_decision_text, start + 1) >= 0:
                raise ValueError("Segmentation provider span is absent or non-unique")
            intervals.append((start, start + len(segment.verbatim_decision_text)))
        ordered = sorted(intervals)
        if any(first[1] > second[0] for first, second in pairwise(ordered)):
            raise ValueError("Segmentation provider spans overlap")
    return output


def validate_adjudication_provider_output(
    raw_text: str,
    *,
    expected_items: dict[tuple[str, str], str],
    protocol: TasteSourceSegmentationProspectiveProtocol | None = None,
) -> SegmentationAdjudicationProviderOutput:
    """Validate disputed-only adjudication coverage and exact source spans."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        raise ValueError("Segmentation adjudication output must be a bare JSON object")
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError("Segmentation adjudication output is not valid JSON") from error
    if protocol is not None and protocol.evidence_unit_selection is not None:
        if protocol.schema_version == "1.5":
            anchored_output_v15 = SegmentationAnchoredAdjudicationProviderOutputV15.model_validate(
                payload
            )
            observed_v15 = [
                (item.campaign_token, item.review_item_id) for item in anchored_output_v15.items
            ]
            if len(observed_v15) != len(set(observed_v15)) or set(observed_v15) != set(
                expected_items
            ):
                raise ValueError("Segmentation adjudication output item coverage drifted")
            return _resolve_anchored_adjudication_output_v15(
                anchored_output_v15,
                expected_items=expected_items,
                own_trigger_context_overlap_allowed=bool(
                    protocol.evidence_unit_selection
                    and protocol.evidence_unit_selection.own_trigger_context_overlap_allowed
                ),
            )
        anchored_output = SegmentationAnchoredAdjudicationProviderOutput.model_validate(payload)
        observed = [(item.campaign_token, item.review_item_id) for item in anchored_output.items]
        if len(observed) != len(set(observed)) or set(observed) != set(expected_items):
            raise ValueError("Segmentation adjudication output item coverage drifted")
        return _resolve_anchored_adjudication_output(
            anchored_output,
            expected_items=expected_items,
        )
    output = SegmentationAdjudicationProviderOutput.model_validate(payload)
    if any(not item.segments for item in output.items):
        raise ValueError("Legacy segmentation adjudication output requires at least one segment")
    observed = [(item.campaign_token, item.review_item_id) for item in output.items]
    if len(observed) != len(set(observed)) or set(observed) != set(expected_items):
        raise ValueError("Segmentation adjudication output item coverage drifted")
    if protocol is not None and protocol.span_reconstruction is not None:
        return _reconstruct_adjudication_spans(output, expected_items=expected_items)
    for item in output.items:
        source = expected_items[(item.campaign_token, item.review_item_id)]
        intervals: list[tuple[int, int]] = []
        for segment in item.segments:
            start = source.find(segment.verbatim_decision_text)
            if start < 0 or source.find(segment.verbatim_decision_text, start + 1) >= 0:
                raise ValueError("Segmentation adjudication span is absent or non-unique")
            intervals.append((start, start + len(segment.verbatim_decision_text)))
        ordered = sorted(intervals)
        if any(first[1] > second[0] for first, second in pairwise(ordered)):
            raise ValueError("Segmentation adjudication spans overlap")
    return output


def build_segmentation_adjudication_request(
    *,
    protocol: TasteSourceSegmentationProspectiveProtocol,
    rubric: dict[str, JsonValue],
    items: list[dict[str, JsonValue]],
) -> dict[str, JsonValue]:
    """Build one disputed-only adjudication payload with anonymous candidates."""

    if not items or len(items) > protocol.generation.items_per_shard:
        raise ValueError("Segmentation adjudication shard size is invalid")
    anchored = protocol.evidence_unit_selection is not None
    nested_anchor_contract = protocol.schema_version == "1.5"
    reported_text_field = (
        None
        if anchored
        else (
            "reported_decision_text"
            if protocol.span_reconstruction is not None
            else "verbatim_decision_text"
        )
    )
    required_segment_fields = (
        [
            *(
                ("trigger_range", "context_ranges")
                if nested_anchor_contract
                else ("start_unit_id", "end_unit_id")
            ),
            "primary_decision_family",
            "atomic_decision_statement",
            "rationale",
            "uncertainty",
        ]
        if anchored
        else [
            str(reported_text_field),
            "primary_decision_family",
            "atomic_decision_statement",
            "rationale",
            "uncertainty",
        ]
    )
    segment_properties: dict[str, JsonValue] = {
        "primary_decision_family": {
            "type": "string",
            "enum": [
                "idea",
                "experiment",
                "evidence",
                "writing",
                "review",
                "visual",
                "cannot-assess",
            ],
        },
        "atomic_decision_statement": {"type": "string", "minLength": 1},
        "rationale": {"type": "string", "minLength": 1},
        "uncertainty": {"type": "string", "enum": ["low", "medium", "high"]},
    }
    if anchored:
        range_contract: dict[str, JsonValue] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["start_unit_id", "end_unit_id"],
            "properties": {
                "start_unit_id": {"type": "string", "pattern": "^u[0-9]{4}$"},
                "end_unit_id": {"type": "string", "pattern": "^u[0-9]{4}$"},
            },
        }
        if nested_anchor_contract:
            segment_properties.update(
                {
                    "trigger_range": range_contract,
                    "context_ranges": {
                        "type": "array",
                        "minItems": 0,
                        "maxItems": 8,
                        "items": range_contract,
                    },
                }
            )
        else:
            segment_properties.update(
                {
                    "start_unit_id": {"type": "string", "pattern": "^u[0-9]{4}$"},
                    "end_unit_id": {"type": "string", "pattern": "^u[0-9]{4}$"},
                }
            )
    else:
        assert reported_text_field is not None
        segment_properties[reported_text_field] = {"type": "string", "minLength": 8}
    output_contract: dict[str, JsonValue] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": len(items),
                "maxItems": len(items),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "campaign_token",
                        "review_item_id",
                        "segments",
                        *(["no_decision_rationale"] if nested_anchor_contract else []),
                        "residual_decision_bearing_text_possible",
                        "resolution_rationale",
                    ],
                    "properties": {
                        "campaign_token": {"type": "string"},
                        "review_item_id": {"type": "string"},
                        "segments": {
                            "type": "array",
                            "minItems": 0 if nested_anchor_contract else 1,
                            "maxItems": 128,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": required_segment_fields,
                                "properties": segment_properties,
                            },
                        },
                        **(
                            {
                                "no_decision_rationale": {
                                    "type": ["string", "null"],
                                    "minLength": 1,
                                    "maxLength": 2000,
                                }
                            }
                            if nested_anchor_contract
                            else {}
                        ),
                        "residual_decision_bearing_text_possible": {"type": "boolean"},
                        "resolution_rationale": {"type": "string", "minLength": 1},
                    },
                    **(
                        {
                            "allOf": [
                                {
                                    "if": {"properties": {"segments": {"maxItems": 0}}},
                                    "then": {
                                        "properties": {"no_decision_rationale": {"type": "string"}}
                                    },
                                    "else": {
                                        "properties": {"no_decision_rationale": {"type": "null"}}
                                    },
                                }
                            ]
                        }
                        if nested_anchor_contract
                        else {}
                    ),
                },
            }
        },
    }
    visible = {"rubric": rubric, "items": items, "output_contract": output_contract}
    request_identity = _canonical_sha256(visible)
    return {
        "model": protocol.model_condition.requested_model_id,
        "request_id": f"stadj-{request_identity[:32]}",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Resolve only the supplied disputed decision segmentations. "
                    "Candidate labels are anonymous and their order carries no meaning. "
                    "Do not infer hidden source or outcome fields, use tools, or browse. "
                    "Return one bare JSON object only. "
                    + (
                        (
                            "Select a minimal trigger range plus only necessary context ranges "
                            "using supplied evidence-unit IDs; zero decisions are valid with a "
                            "rationale. "
                            if nested_anchor_contract
                            else "Select only supplied evidence-unit IDs. "
                        )
                        + "Return no dedicated source-span transcription field; final source "
                        "text is copied by the runner."
                        if anchored
                        else "The reported decision text is only a locator candidate; final "
                        "source text is copied by the runner."
                    )
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    visible,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": protocol.generation.thinking},
        "reasoning_effort": protocol.generation.reasoning_effort,
        "temperature": protocol.generation.temperature,
        "max_tokens": protocol.generation.maximum_output_tokens_per_call,
        "stream": False,
    }


def verify_persisted_segmentation_provider_request(
    raw: bytes,
    *,
    packet: TasteSourceSegmentationRequestPacket,
    protocol: TasteSourceSegmentationProspectiveProtocol,
    raw_request_ref: str,
) -> SegmentationInputFirewallReceipt:
    """Reparse exact outbound bytes and issue a runner-owned firewall receipt."""

    expected = build_segmentation_provider_request(packet, protocol=protocol)
    try:
        observed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Persisted segmentation request is not JSON") from error
    if observed != expected:
        raise ValueError("Persisted segmentation request differs from its frozen packet")
    content = _parse_provider_user_content(observed)
    forbidden_keys = {
        "article_title",
        "author_response",
        "later_revision",
        "observed_recommendation",
        "publisher_subject",
        "source_identity",
        "private_item_map",
        "population_outcome",
        "tools",
        "tool_choice",
    }
    if packet.schema_version in {"1.1", "1.2"}:
        forbidden_keys.update(
            {
                "start_char",
                "end_char",
                "verbatim_decision_text",
                "reported_decision_text",
                "trigger_text",
                "context_text",
            }
        )
    if (_recursive_keys(observed) | _recursive_keys(content)) & forbidden_keys:
        raise ValueError("Persisted segmentation request violates its input firewall")
    if set(observed) != {
        "max_tokens",
        "messages",
        "model",
        "request_id",
        "reasoning_effort",
        "response_format",
        "stream",
        "temperature",
        "thinking",
    }:
        raise ValueError("Persisted segmentation provider root fields drifted")
    return SegmentationInputFirewallReceipt(
        packet_id=packet.packet_id,
        packet_sha256=packet.packet_sha256,
        raw_request_ref=raw_request_ref,
        raw_request_sha256=hashlib.sha256(raw).hexdigest(),
    )


def verify_persisted_segmentation_adjudication_request(
    raw: bytes,
    *,
    expected_payload: dict[str, JsonValue],
    packet_id: str,
    packet_sha256: str,
    raw_request_ref: str,
) -> SegmentationAdjudicationInputFirewallReceipt:
    try:
        observed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Persisted segmentation adjudication request is not JSON") from error
    if observed != expected_payload:
        raise ValueError("Persisted adjudication request differs from its compiled payload")
    content = _parse_provider_user_content(observed)
    forbidden_keys = {
        "article_title",
        "author_response",
        "later_revision",
        "observed_recommendation",
        "publisher_subject",
        "source_identity",
        "private_item_map",
        "population_outcome",
        "campaign_id",
        "segmenter_slot",
        "tools",
        "tool_choice",
    }
    anchored = any(
        isinstance(item, dict) and "evidence_units" in item for item in content.get("items", [])
    )
    if anchored:
        forbidden_keys.update(
            {
                "start_char",
                "end_char",
                "verbatim_decision_text",
                "reported_decision_text",
                "trigger_text",
                "context_text",
            }
        )
    if (_recursive_keys(observed) | _recursive_keys(content)) & forbidden_keys:
        raise ValueError("Persisted adjudication request violates its input firewall")
    if set(observed) != {
        "max_tokens",
        "messages",
        "model",
        "reasoning_effort",
        "request_id",
        "response_format",
        "stream",
        "temperature",
        "thinking",
    }:
        raise ValueError("Persisted adjudication provider root fields drifted")
    visible_items = content.get("items") if isinstance(content, dict) else None
    if not isinstance(visible_items, list) or any(
        not isinstance(item, dict)
        or set(item.get("candidates", {})) != {"candidate-left", "candidate-right"}
        for item in visible_items
    ):
        raise ValueError("Persisted adjudication candidates are not anonymously paired")
    return SegmentationAdjudicationInputFirewallReceipt(
        packet_id=packet_id,
        packet_sha256=packet_sha256,
        raw_request_ref=raw_request_ref,
        raw_request_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _parse_provider_user_content(observed: object) -> dict[str, JsonValue]:
    if not isinstance(observed, dict):
        raise ValueError("Persisted provider request root must be an object")
    messages = observed.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not all(isinstance(message, dict) for message in messages)
        or set(messages[0]) != {"role", "content"}
        or set(messages[1]) != {"role", "content"}
        or messages[0]["role"] != "system"
        or messages[1]["role"] != "user"
        or not isinstance(messages[0]["content"], str)
        or not isinstance(messages[1]["content"], str)
    ):
        raise ValueError("Persisted provider request messages drifted")
    try:
        content = json.loads(messages[1]["content"])
    except json.JSONDecodeError as error:
        raise ValueError("Persisted provider user content is not JSON") from error
    if not isinstance(content, dict):
        raise ValueError("Persisted provider user content must be an object")
    return content


def extract_openai_chat_response(
    response: ProviderHTTPResponse,
) -> ExtractedProviderResponse:
    """Extract the response text and mandatory runtime identity fields."""

    if not 200 <= response.status_code < 300:
        raise ValueError(f"Segmentation provider returned HTTP {response.status_code}")
    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Segmentation provider response is not JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Segmentation provider response root must be an object")
    try:
        choices = payload["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise TypeError("exactly one choice is required")
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("index") != 0:
            raise TypeError("choice index zero is required")
        text = choice["message"]["content"]
        finish_reason = choice["finish_reason"]
        returned_model = payload["model"]
        client_request_id = payload["request_id"]
        provider_task_id = payload["id"]
        usage = payload["usage"]
        if not isinstance(usage, dict):
            raise TypeError("usage must be an object")
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        total_tokens = usage["total_tokens"]
        prompt_details = usage.get("prompt_tokens_details", {})
        if not isinstance(prompt_details, dict):
            raise TypeError("prompt token details must be an object")
        cached_input_tokens = prompt_details.get("cached_tokens", 0)
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Segmentation provider response lacks required receipt fields") from error
    if not all(
        isinstance(value, str)
        for value in (text, returned_model, client_request_id, provider_task_id)
    ):
        raise ValueError("Segmentation provider identity fields are invalid")
    if finish_reason != "stop":
        raise ValueError("Segmentation provider response did not finish normally")
    if (
        type(input_tokens) is not int
        or type(output_tokens) is not int
        or type(cached_input_tokens) is not int
        or type(total_tokens) is not int
        or min(input_tokens, cached_input_tokens, output_tokens, total_tokens) < 0
    ):
        raise ValueError("Segmentation provider usage fields are invalid")
    return ExtractedProviderResponse(
        text=text,
        returned_model=returned_model,
        client_request_id=client_request_id,
        provider_task_id=provider_task_id,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        payload=payload,
    )


def persist_exact_provider_request(path: str | Path, payload: dict[str, JsonValue]) -> bytes:
    """Persist canonical request bytes and return the same bytes for transport."""

    raw = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    _atomic_bytes(Path(path), raw)
    return raw


def run_taste_source_segmentation_calibration(
    *,
    authorization_path: str | Path,
    locator_root: str | Path,
    confirm_authorization_sha256: str,
    allow_live: bool,
    transport: ProviderHTTPTransport | None = None,
) -> TasteSourceSegmentationCalibrationReceipt:
    """Execute exactly one authorized calibration window with no retries."""

    inspection = inspect_taste_source_segmentation_execution_authorization(
        authorization_path=authorization_path,
        locator_root=locator_root,
    )
    authorization = inspection.authorization
    if not allow_live:
        raise ValueError("Live segmentation execution requires --allow-live")
    if confirm_authorization_sha256 != authorization.authorization_sha256:
        raise ValueError("Live segmentation execution confirmation hash differs")
    root = Path(locator_root).resolve(strict=True)
    output_root = (root / _safe_locator(authorization.run_output_locator)).resolve()
    ledger_path = (root / _safe_locator(authorization.execution_ledger_locator)).resolve()
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(output_root)
    active_transport = transport or LiveProviderHTTPTransport()
    protocol = inspection.protocol.protocol
    identity_protocol = inspection.identity_protocol.protocol
    provider = inspection.provider_resource
    packets = {(packet.segmenter_slot, packet.shard_index): packet for packet in inspection.packets}
    if len(packets) != len(inspection.packets):
        raise ValueError("Segmentation in-memory packet snapshot contains duplicate slots")
    token_to_campaign = _campaign_token_map(inspection)
    adjudication_rubric = inspection.adjudication_rubric.payload
    credential = os.environ.get(authorization.credential_env)
    if not credential:
        raise ValueError(f"Credential environment {authorization.credential_env} is unavailable")
    started_at = datetime.now(UTC)
    ledger = SegmentationExecutionLedger(
        authorization_sha256=authorization.authorization_sha256,
        run_id=authorization.run_id,
        one_time_nonce=authorization.one_time_nonce,
        status="claimed",
        completed_sequences=(),
        provider_call_may_have_started=False,
        updated_at=started_at,
    )
    _claim_execution_ledger(ledger_path, ledger)
    try:
        output_root.mkdir(parents=True, mode=0o700)
        os.chmod(output_root, 0o700)
    except Exception as error:
        _fail_execution_ledger(ledger_path, ledger, output_root, error)
        raise
    segmenter_outputs: dict[str, list[SegmentationProviderItem]] = {
        "segmenter-a": [],
        "segmenter-b": [],
    }
    call_receipts: list[SegmentationProviderCallReceipt] = []
    firewall_receipts: list[SegmentationInputFirewallReceipt] = []
    adjudication_firewall_receipts: list[SegmentationAdjudicationInputFirewallReceipt] = []

    def execute_call(
        *,
        role: ApiIdentityCallRole,
        payload: dict[str, JsonValue],
        packet_id: str | None = None,
        packet_sha256: str | None = None,
        packet: TasteSourceSegmentationRequestPacket | None = None,
        adjudication_expected: dict[tuple[str, str], str] | None = None,
    ) -> SegmentationProviderOutput | SegmentationAdjudicationProviderOutput | dict[str, JsonValue]:
        nonlocal ledger
        sequence = len(call_receipts) + 1
        if sequence > authorization.limits.maximum_provider_requests:
            raise ValueError("Segmentation execution request count exceeded")
        call_name = f"call-{sequence:02d}-{role.value}"
        request_path = output_root / "calls" / call_name / "request.json"
        response_path = output_root / "calls" / call_name / "response.json"
        headers_path = output_root / "calls" / call_name / "response-headers.json"
        raw_request = persist_exact_provider_request(request_path, payload)
        request_ref = _relative_to_root(request_path, root)
        if packet is not None:
            firewall_receipts.append(
                verify_persisted_segmentation_provider_request(
                    raw_request,
                    packet=packet,
                    protocol=protocol,
                    raw_request_ref=request_ref,
                )
            )
        elif adjudication_expected is not None:
            assert packet_id is not None and packet_sha256 is not None
            adjudication_firewall_receipts.append(
                verify_persisted_segmentation_adjudication_request(
                    raw_request,
                    expected_payload=payload,
                    packet_id=packet_id,
                    packet_sha256=packet_sha256,
                    raw_request_ref=request_ref,
                )
            )
        request_sha256 = hashlib.sha256(raw_request).hexdigest()
        ledger = ledger.model_copy(
            update={
                "status": "provider-call-pending",
                "pending_sequence": sequence,
                "pending_request_sha256": request_sha256,
                "provider_call_may_have_started": True,
                "updated_at": datetime.now(UTC),
            }
        )
        ledger = SegmentationExecutionLedger.model_validate(ledger)
        _replace_execution_ledger(ledger_path, ledger)
        request_started_at = datetime.now(UTC)
        response: ProviderHTTPResponse | None = None
        try:
            response = active_transport.post(
                provider.endpoint,
                headers={
                    "authorization": f"Bearer {credential}",
                    "content-type": "application/json",
                    "accept": "application/json",
                    "user-agent": "SciTaste/segmentation-calibration-v1",
                },
                content=raw_request,
                timeout_seconds=authorization.limits.timeout_seconds_per_request,
                maximum_response_bytes=authorization.limits.maximum_raw_response_bytes,
            )
            response_completed_at = datetime.now(UTC)
            _atomic_bytes(response_path, response.content)
            _write_json_new(
                headers_path,
                {
                    key: value
                    for key, value in response.headers.items()
                    if key.casefold() in {"content-type", "date", "x-request-id"}
                },
            )
            extracted = extract_openai_chat_response(response)
            policy = identity_protocol.policy(provider.resource_id)
            estimated_cost_cny = _estimate_call_cost_cny(
                input_tokens=extracted.input_tokens,
                cached_input_tokens=extracted.cached_input_tokens,
                output_tokens=extracted.output_tokens,
                price=authorization.price_ceiling,
            )
            transport_receipt = SegmentationProviderTransportReceipt(
                sequence=sequence,
                role=role,
                packet_id=packet_id,
                request_sha256=request_sha256,
                response_sha256=hashlib.sha256(response.content).hexdigest(),
                raw_request_ref=request_ref,
                raw_response_ref=_relative_to_root(response_path, root),
                http_status=response.status_code,
                client_request_id=payload["request_id"],
                echoed_request_id=extracted.client_request_id,
                provider_task_id=extracted.provider_task_id,
                returned_model=extracted.returned_model,
                request_started_at=request_started_at,
                response_completed_at=response_completed_at,
                input_tokens=extracted.input_tokens,
                cached_input_tokens=extracted.cached_input_tokens,
                output_tokens=extracted.output_tokens,
                total_tokens=extracted.total_tokens,
                estimated_cost_cny=estimated_cost_cny,
                request_id_echo_passed=(extracted.client_request_id == payload["request_id"]),
                model_allowlist_passed=(
                    extracted.returned_model in policy.allowed_returned_model_ids
                ),
            )
            _write_json_new(
                output_root / "calls" / call_name / "TRANSPORT_RECEIPT.json",
                transport_receipt.model_dump(mode="json"),
            )
            projected_input = (
                sum(item.call.input_tokens for item in call_receipts)
                + transport_receipt.input_tokens
            )
            projected_output = (
                sum(item.call.output_tokens for item in call_receipts)
                + transport_receipt.output_tokens
            )
            projected_cost = (
                sum(item.estimated_cost_cny for item in call_receipts)
                + transport_receipt.estimated_cost_cny
            )
            if (
                projected_input > authorization.limits.maximum_input_tokens
                or projected_output > authorization.limits.maximum_output_tokens
                or projected_cost > authorization.price_ceiling.maximum_estimated_cost_cny
            ):
                raise ValueError("Segmentation execution cumulative budget exceeded")
            if not transport_receipt.request_id_echo_passed:
                raise ValueError("Segmentation provider request ID echo drifted")
            if not transport_receipt.model_allowlist_passed:
                raise ValueError("Segmentation provider returned an unapproved model")
            if role is ApiIdentityCallRole.WORKLOAD and packet is not None:
                output: object = validate_segmentation_provider_output(
                    extracted.text,
                    packet=packet,
                    protocol=protocol,
                )
            elif role is ApiIdentityCallRole.WORKLOAD:
                assert adjudication_expected is not None
                output = validate_adjudication_provider_output(
                    extracted.text,
                    expected_items=adjudication_expected,
                    protocol=protocol,
                )
            else:
                output = json.loads(extracted.text)
                if output != {"sentinel": "scitaste-api-identity-v3"}:
                    raise ValueError("Segmentation identity sentinel output drifted")
            identity_call = ApiIdentityCallReceipt(
                sequence=sequence,
                role=role,
                provider_id=provider.provider_id,
                endpoint=provider.endpoint,
                interface=provider.interface,
                requested_model_id=provider.model_id,
                returned_model=extracted.returned_model,
                provider_request_id=extracted.provider_task_id,
                request_started_at_utc=request_started_at,
                response_completed_at_utc=response_completed_at,
                request_sha256=request_sha256,
                response_sha256=hashlib.sha256(response.content).hexdigest(),
                raw_request_ref=request_ref,
                raw_response_ref=_relative_to_root(response_path, root),
                http_status=response.status_code,
                input_tokens=extracted.input_tokens,
                output_tokens=extracted.output_tokens,
                sentinel_template_sha256=(
                    identity_protocol.sentinel_template_sha256
                    if role is not ApiIdentityCallRole.WORKLOAD
                    else None
                ),
                task_or_benchmark_content_present=role is ApiIdentityCallRole.WORKLOAD,
            )
            receipt = SegmentationProviderCallReceipt(
                schema_version=("1.1" if protocol.schema_version == "1.5" else "1.0"),
                call=identity_call,
                packet_id=packet_id,
                packet_sha256=packet_sha256,
                client_request_id=payload["request_id"],
                echoed_request_id=extracted.client_request_id,
                provider_task_id=extracted.provider_task_id,
                raw_provider_response_sha256=hashlib.sha256(response.content).hexdigest(),
                output_object_sha256=content_sha256(
                    output.model_dump(mode="json") if isinstance(output, BaseModel) else output
                ),
                cached_input_tokens=extracted.cached_input_tokens,
                total_tokens=extracted.total_tokens,
                estimated_cost_cny=estimated_cost_cny,
                span_reconstruction_receipts=_compile_span_reconstruction_receipts(
                    raw_text=extracted.text,
                    output=output,
                    protocol=protocol,
                    source_texts=(
                        {
                            (item.campaign_token, item.review_item_id): item.review_comment
                            for item in packet.items
                        }
                        if packet is not None
                        else adjudication_expected
                    ),
                ),
                evidence_unit_selection_receipts=(
                    _compile_evidence_unit_selection_receipts(
                        raw_text=extracted.text,
                        output=output,
                        protocol=protocol,
                        source_texts=(
                            {
                                (item.campaign_token, item.review_item_id): item.review_comment
                                for item in packet.items
                            }
                            if packet is not None
                            else adjudication_expected
                        ),
                    )
                    if protocol.evidence_unit_selection is not None
                    and role is ApiIdentityCallRole.WORKLOAD
                    else ()
                ),
                evidence_unit_item_receipts=(
                    _compile_evidence_unit_item_receipts(
                        output=output,
                        source_texts=(
                            {
                                (item.campaign_token, item.review_item_id): item.review_comment
                                for item in packet.items
                            }
                            if packet is not None
                            else adjudication_expected
                        ),
                    )
                    if protocol.schema_version == "1.5" and role is ApiIdentityCallRole.WORKLOAD
                    else ()
                ),
                assigned_item_count=(
                    len(packet.items)
                    if protocol.schema_version == "1.5"
                    and role is ApiIdentityCallRole.WORKLOAD
                    and packet is not None
                    else len(adjudication_expected or {})
                    if protocol.schema_version == "1.5" and role is ApiIdentityCallRole.WORKLOAD
                    else None
                ),
                verbatim_spans_verified=(
                    None
                    if protocol.schema_version == "1.5" or role is not ApiIdentityCallRole.WORKLOAD
                    else True
                ),
                anchor_ranges_verified=(
                    True
                    if protocol.schema_version == "1.5" and role is ApiIdentityCallRole.WORKLOAD
                    else None
                ),
                identity_sentinel_output_verified=(
                    True if role is not ApiIdentityCallRole.WORKLOAD else None
                ),
            )
            projected = [*call_receipts, receipt]
            if (
                sum(item.call.input_tokens for item in projected)
                > authorization.limits.maximum_input_tokens
                or sum(item.call.output_tokens for item in projected)
                > authorization.limits.maximum_output_tokens
                or sum(item.estimated_cost_cny for item in projected)
                > authorization.price_ceiling.maximum_estimated_cost_cny
            ):
                raise ValueError("Segmentation execution cumulative budget exceeded")
            call_receipts.append(receipt)
            _write_json_new(
                output_root / "calls" / call_name / "CALL_RECEIPT.json",
                receipt.model_dump(mode="json"),
            )
            ledger = SegmentationExecutionLedger(
                authorization_sha256=authorization.authorization_sha256,
                run_id=authorization.run_id,
                one_time_nonce=authorization.one_time_nonce,
                status="claimed",
                completed_sequences=tuple(range(1, sequence + 1)),
                provider_call_may_have_started=False,
                updated_at=datetime.now(UTC),
            )
            _replace_execution_ledger(ledger_path, ledger)
            assert isinstance(output, (BaseModel, dict))
            return output
        except Exception as error:
            _write_json_new(
                output_root / "calls" / call_name / "CALL_FAILURE_RECEIPT.json",
                {
                    "sequence": sequence,
                    "role": role.value,
                    "packet_id": packet_id,
                    "request_sha256": request_sha256,
                    "response_sha256": (
                        hashlib.sha256(response.content).hexdigest()
                        if response is not None
                        else None
                    ),
                    "http_status": response.status_code if response is not None else None,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "retry_authorized": False,
                    "reviewer_kind": "ai",
                    "not_human_review": True,
                },
            )
            _fail_execution_ledger(
                ledger_path,
                ledger,
                output_root,
                error,
                failed_sequence=sequence,
                failed_request_sha256=request_sha256,
                failed_response_sha256=(
                    hashlib.sha256(response.content).hexdigest() if response is not None else None
                ),
                failed_http_status=response.status_code if response is not None else None,
                failed_raw_request_ref=request_ref,
                failed_raw_response_ref=(
                    _relative_to_root(response_path, root) if response_path.exists() else None
                ),
            )
            raise

    try:
        sentinel_start = _build_identity_sentinel_request(
            model=provider.model_id,
            request_id=f"stsent-start-{authorization.one_time_nonce[:32]}",
            protocol=identity_protocol,
        )
        execute_call(role=ApiIdentityCallRole.START_SENTINEL, payload=sentinel_start)
        for shard_index in range(1, protocol.generation.segmenter_shards + 1):
            for slot in ("segmenter-a", "segmenter-b"):
                packet = packets[(slot, shard_index)]
                output = execute_call(
                    role=ApiIdentityCallRole.WORKLOAD,
                    payload=build_segmentation_provider_request(packet, protocol=protocol),
                    packet_id=packet.packet_id,
                    packet_sha256=packet.packet_sha256,
                    packet=packet,
                )
                assert isinstance(output, SegmentationProviderOutput)
                segmenter_outputs[slot].extend(output.items)

        raw_segmenter_paths: dict[str, Path] = {}
        for slot in ("segmenter-a", "segmenter-b"):
            raw_path = output_root / "derived" / f"{slot}-provider-output.json"
            _write_json_new(
                raw_path,
                _legacy_segmenter_payload(
                    slot=slot,
                    items=segmenter_outputs[slot],
                    token_to_campaign=token_to_campaign,
                    protocol=protocol,
                    sample_sha256=inspection.request_pack.sample_sha256,
                    authorization_sha256=authorization.authorization_sha256,
                ),
            )
            raw_segmenter_paths[slot] = raw_path
        normalized_paths: dict[str, Path] = {}
        normalized_runs: dict[str, TasteSourceDecisionSegmentationRun] = {}
        for slot in ("segmenter-a", "segmenter-b"):
            normalized = normalize_taste_source_decision_segmentation(
                raw_segmentation_path=raw_segmenter_paths[slot],
                campaign_paths=(),
                campaign_aliases=token_to_campaign,
                run_id=f"{authorization.run_id}-{slot}",
                screener_id=f"{slot}-glm53-flash",
                invocation_id=f"{authorization.run_id}-{slot}-invocation",
                runtime_surface="zhipu-direct-byte-runner-v1",
                model_identifier=provider.model_id,
                model_revision=None,
                exact_model_identity_bound=False,
                rubric_path=root / protocol.segmentation_rubric.locator,
                sample_manifest_path=root / protocol.sample.locator,
                runtime_identity_sha256=None,
                completed_at=datetime.now(UTC),
                locator_root=root,
                prevalidated_rubric_snapshot=inspection.segmentation_rubric,
                prevalidated_sample_inspection=inspection.sample,
                prevalidated_sample_manifest_locator=protocol.sample.locator,
                prevalidated_campaign_snapshots=inspection.campaigns,
            )
            normalized_path = output_root / "derived" / f"{slot}.json"
            save_taste_source_decision_segmentation_run(normalized, normalized_path)
            normalized_paths[slot] = normalized_path
            normalized_runs[slot] = normalized
        agreement = compile_taste_source_segmentation_agreement(
            report_id=f"{authorization.run_id}-agreement",
            segmentation_paths=(
                normalized_paths["segmenter-a"],
                normalized_paths["segmenter-b"],
            ),
            compiled_at=datetime.now(UTC),
            locator_root=root,
            routing_contract="decision-boundary-only-v2",
            prevalidated_group_boundary=inspection.group_boundary,
        )
        agreement_path = output_root / "derived" / "agreement.json"
        save_taste_source_segmentation_agreement_report(agreement, agreement_path)

        provider_items_a = {
            (item.campaign_token, item.review_item_id): item
            for item in segmenter_outputs["segmenter-a"]
        }
        provider_items_b = {
            (item.campaign_token, item.review_item_id): item
            for item in segmenter_outputs["segmenter-b"]
        }
        campaign_to_token = {value: key for key, value in token_to_campaign.items()}
        item_sources = _packet_item_sources(packets)
        agreement_by_shard: dict[int, list[object]] = {}
        for item in agreement.items:
            if item.requires_adjudication:
                token = campaign_to_token[item.campaign_id]
                shard = item_sources[(token, item.review_item_id)][0]
                agreement_by_shard.setdefault(shard, []).append(item)
        adjudicated: dict[tuple[str, str], SegmentationAdjudicationProviderItem] = {}
        candidate_order_records: list[dict[str, JsonValue]] = []
        for adjudication_index, shard in enumerate(sorted(agreement_by_shard), 1):
            visible_items: list[dict[str, JsonValue]] = []
            expected: dict[tuple[str, str], str] = {}
            for untyped in sorted(
                agreement_by_shard[shard],
                key=lambda value: (value.campaign_id, value.review_item_id),
            ):
                item = untyped
                token = campaign_to_token[item.campaign_id]
                key = (token, item.review_item_id)
                _, reviewed_abstract, review_comment = item_sources[key]
                left_is_a = (
                    int(
                        hashlib.sha256(
                            (authorization.one_time_nonce + token + item.review_item_id).encode()
                        ).hexdigest(),
                        16,
                    )
                    % 2
                    == 0
                )
                candidate_left = provider_items_a[key] if left_is_a else provider_items_b[key]
                candidate_right = provider_items_b[key] if left_is_a else provider_items_a[key]
                evidence_units = (
                    unitize_taste_source_comment(review_comment)
                    if protocol.evidence_unit_selection is not None
                    else None
                )
                visible_items.append(
                    {
                        "campaign_token": token,
                        "review_item_id": item.review_item_id,
                        "reviewed_abstract": reviewed_abstract,
                        "review_comment": review_comment,
                        "source_blocker_codes": list(item.blocker_codes),
                        "candidates": {
                            "candidate-left": _anonymous_candidate(
                                candidate_left,
                                nested_anchor_contract=protocol.schema_version == "1.5",
                                source=(
                                    review_comment
                                    if protocol.evidence_unit_selection is not None
                                    else None
                                ),
                            ),
                            "candidate-right": _anonymous_candidate(
                                candidate_right,
                                nested_anchor_contract=protocol.schema_version == "1.5",
                                source=(
                                    review_comment
                                    if protocol.evidence_unit_selection is not None
                                    else None
                                ),
                            ),
                        },
                        **(
                            {
                                "evidence_units": [
                                    unit.model_dump(mode="json") for unit in evidence_units or ()
                                ]
                            }
                            if evidence_units is not None
                            else {}
                        ),
                    }
                )
                expected[key] = review_comment
                candidate_order_records.append(
                    {
                        "campaign_token": token,
                        "review_item_id": item.review_item_id,
                        "candidate_left_source": "segmenter-a" if left_is_a else "segmenter-b",
                        "candidate_right_source": "segmenter-b" if left_is_a else "segmenter-a",
                    }
                )
            packet_id = f"adjudication-shard-{adjudication_index:02d}"
            packet_sha256 = _canonical_sha256({"packet_id": packet_id, "items": visible_items})
            payload = build_segmentation_adjudication_request(
                protocol=protocol,
                rubric=adjudication_rubric,
                items=visible_items,
            )
            output = execute_call(
                role=ApiIdentityCallRole.WORKLOAD,
                payload=payload,
                packet_id=packet_id,
                packet_sha256=packet_sha256,
                adjudication_expected=expected,
            )
            assert isinstance(output, SegmentationAdjudicationProviderOutput)
            for item in output.items:
                adjudicated[(item.campaign_token, item.review_item_id)] = item
        _write_json_new(
            output_root / "private" / "candidate-order.json",
            {"items": candidate_order_records},
        )

        sentinel_end = _build_identity_sentinel_request(
            model=provider.model_id,
            request_id=f"stsent-end-{authorization.one_time_nonce[:32]}",
            protocol=identity_protocol,
        )
        execute_call(role=ApiIdentityCallRole.END_SENTINEL, payload=sentinel_end)
        completed_at = datetime.now(UTC)
        attestation = ApiIdentityWindowAttestation.create(
            window_id=f"{authorization.run_id}-identity-window",
            project_id=authorization.project_id,
            protocol_id=identity_protocol.protocol_id,
            protocol_semantic_sha256=inspection.identity_protocol.semantic_sha256,
            resource_id=provider.resource_id,
            kind=ApiIdentityWindowKind.CONFORMANCE,
            opened_at_utc=started_at,
            closed_at_utc=completed_at,
            official_catalog_open_sha256=authorization.official_catalog_snapshot.file_sha256,
            official_catalog_close_sha256=authorization.official_catalog_snapshot.file_sha256,
            official_revision_at_open=None,
            official_revision_at_close=None,
            execution_approval_sha256=authorization.authorization_sha256,
            calls=tuple(item.call for item in call_receipts),
        )
        attestation_path = output_root / "identity" / "attestation.json"
        _write_json_new(attestation_path, attestation.model_dump(mode="json"))
        identity_report = inspect_api_identity_window(
            attestation,
            protocol_inspection=inspection.identity_protocol,
            resource=provider,
        )
        if not identity_report.admitted:
            raise ValueError(
                "Segmentation identity window was rejected: "
                + ",".join(identity_report.blocker_codes)
            )

        resolution_payload = _legacy_resolution_payload(
            agreement=agreement,
            segmenter_a=normalized_runs["segmenter-a"],
            campaign_to_token=campaign_to_token,
            adjudicated=adjudicated,
            rubric_file_sha256=inspection.adjudication_rubric.file_sha256,
            authorization_sha256=authorization.authorization_sha256,
        )
        raw_resolution_path = output_root / "derived" / "adjudicator-provider-output.json"
        _write_json_new(raw_resolution_path, resolution_payload)
        resolution = normalize_taste_source_segmentation_resolution(
            raw_resolution_path=raw_resolution_path,
            agreement_path=agreement_path,
            run_id=f"{authorization.run_id}-resolution",
            adjudicator_id="adjudicator-c-glm53-flash",
            invocation_id=f"{authorization.run_id}-adjudicator-c-invocation",
            runtime_surface="zhipu-direct-byte-runner-v1",
            model_identifier=provider.model_id,
            model_revision=None,
            exact_model_identity_bound=False,
            rubric_path=root / protocol.adjudication_rubric.locator,
            runtime_identity_sha256=None,
            completed_at=completed_at,
            locator_root=root,
            prevalidated_rubric_snapshot=inspection.adjudication_rubric,
            prevalidated_campaign_snapshots=inspection.campaigns,
        )
        resolution_path = output_root / "derived" / "resolution.json"
        save_taste_source_segmentation_resolution_run(resolution, resolution_path)
        item_count = agreement.source_item_count
        decision_presence_agreement_micros = (
            sum(
                (item.segmenter_a_count > 0) == (item.segmenter_b_count > 0)
                for item in agreement.items
            )
            * 1_000_000
            // item_count
        )
        exact_trigger_context_set_agreement_micros = (
            agreement.group_uncertainty.exact_trigger_context_set_agreement.point_micros
            if agreement.group_uncertainty is not None
            and agreement.group_uncertainty.exact_trigger_context_set_agreement is not None
            else None
        )
        metrics = SegmentationCalibrationMetrics(
            overlap_span_f1_micros=agreement.overlap_span_f1_micros,
            overlap_matched_family_agreement_micros=(
                agreement.overlap_matched_family_agreement_micros
            ),
            adjudication_item_rate_micros=(
                agreement.adjudication_item_count * 1_000_000 // item_count
            ),
            residual_risk_item_rate_after_adjudication_micros=(
                resolution.residual_risk_item_count * 1_000_000 // item_count
            ),
            decision_presence_agreement_micros=(
                decision_presence_agreement_micros if protocol.schema_version == "1.5" else None
            ),
            exact_trigger_context_set_agreement_micros=(exact_trigger_context_set_agreement_micros),
            all_frozen_thresholds_passed=(
                agreement.overlap_span_f1_micros >= 800_000
                and agreement.overlap_matched_family_agreement_micros >= 800_000
                and agreement.adjudication_item_count * 1_000_000 // item_count <= 500_000
                and resolution.residual_risk_item_count == 0
                and (
                    protocol.schema_version != "1.5"
                    or decision_presence_agreement_micros >= 800_000
                )
            ),
        )
        receipt = TasteSourceSegmentationCalibrationReceipt.create(
            schema_version="1.1" if protocol.schema_version == "1.5" else "1.0",
            run_id=authorization.run_id,
            project_id=authorization.project_id,
            authorization_sha256=authorization.authorization_sha256,
            protocol_file_sha256=authorization.protocol.file_sha256,
            request_pack_sha256=authorization.request_pack.pack_sha256,
            started_at=started_at,
            completed_at=completed_at,
            provider=provider.provider_id,
            requested_model=provider.model_id,
            returned_models=tuple(
                dict.fromkeys(item.call.returned_model for item in call_receipts)
            ),
            identity_attestation=_artifact_binding(
                attestation_path,
                root=root,
                semantic_sha256=attestation.attestation_sha256,
            ),
            identity_report=identity_report,
            call_receipts=tuple(call_receipts),
            segmenter_firewall_receipts=tuple(firewall_receipts),
            adjudication_firewall_receipts=tuple(adjudication_firewall_receipts),
            segmenter_a=_artifact_binding(
                normalized_paths["segmenter-a"],
                root=root,
                semantic_sha256=normalized_runs["segmenter-a"].run_sha256,
            ),
            segmenter_b=_artifact_binding(
                normalized_paths["segmenter-b"],
                root=root,
                semantic_sha256=normalized_runs["segmenter-b"].run_sha256,
            ),
            agreement=_artifact_binding(
                agreement_path,
                root=root,
                semantic_sha256=agreement.report_sha256,
            ),
            resolution=_artifact_binding(
                resolution_path,
                root=root,
                semantic_sha256=resolution.run_sha256,
            ),
            metrics=metrics,
            group_uncertainty=agreement.group_uncertainty,
            request_count=len(call_receipts),
            input_tokens=sum(item.call.input_tokens for item in call_receipts),
            output_tokens=sum(item.call.output_tokens for item in call_receipts),
            estimated_cost_cny=sum(item.estimated_cost_cny for item in call_receipts),
        )
        _write_json_new(
            output_root / "CALIBRATION_RECEIPT.json",
            receipt.model_dump(mode="json"),
        )
        ledger = SegmentationExecutionLedger(
            authorization_sha256=authorization.authorization_sha256,
            run_id=authorization.run_id,
            one_time_nonce=authorization.one_time_nonce,
            status="complete",
            completed_sequences=tuple(range(1, len(call_receipts) + 1)),
            provider_call_may_have_started=False,
            updated_at=datetime.now(UTC),
        )
        _replace_execution_ledger(ledger_path, ledger)
        return receipt
    except Exception as error:
        current = _load_execution_ledger(ledger_path)
        if current.status not in {"failed", "complete"}:
            _fail_execution_ledger(ledger_path, current, output_root, error)
        raise


def _build_identity_sentinel_request(
    *,
    model: str,
    request_id: str,
    protocol: object,
) -> dict[str, JsonValue]:
    sentinel = protocol.sentinel
    return {
        "model": model,
        "request_id": request_id,
        "messages": [
            {"role": "system", "content": sentinel.system_message},
            {"role": "user", "content": sentinel.user_message},
        ],
        "response_format": {"type": sentinel.response_format},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
        "temperature": 0.0,
        "max_tokens": sentinel.max_output_tokens,
        "stream": False,
    }


def _typography_normalize(value: str) -> str:
    return value.translate(
        {
            0x2018: 0x27,
            0x2019: 0x27,
            0x201C: 0x22,
            0x201D: 0x22,
            0x00A0: 0x20,
        }
    )


def _resolve_anchored_segments(
    segments: tuple[SegmentationAnchoredProviderSegment, ...],
    *,
    source: str,
) -> tuple[SegmentationProviderSegment, ...]:
    unit_rows = taste_source_comment_unit_offsets(source)
    units = {
        unit_id: (ordinal, start, end)
        for ordinal, (unit_id, _, start, end) in enumerate(unit_rows, 1)
    }
    resolved: list[SegmentationProviderSegment] = []
    intervals: list[tuple[int, int]] = []
    for segment in segments:
        try:
            start_ordinal, start_char, _ = units[segment.start_unit_id]
            end_ordinal, _, end_char = units[segment.end_unit_id]
        except KeyError as error:
            raise ValueError(
                "Segmentation provider selected an unknown evidence-unit ID"
            ) from error
        if end_ordinal < start_ordinal:
            raise ValueError("Segmentation provider evidence-unit range is reversed")
        intervals.append((start_char, end_char))
        resolved.append(
            SegmentationProviderSegment(
                verbatim_decision_text=source[start_char:end_char],
                primary_decision_family=segment.primary_decision_family,
                atomic_decision_statement=segment.atomic_decision_statement,
                rationale=segment.rationale,
                uncertainty=segment.uncertainty,
                start_char=start_char,
                end_char=end_char,
            )
        )
    if intervals != sorted(intervals):
        raise ValueError("Segmentation provider evidence-unit ranges are out of order")
    if any(first[1] > second[0] for first, second in pairwise(intervals)):
        raise ValueError("Segmentation provider evidence-unit ranges overlap")
    return tuple(resolved)


def _resolve_anchored_segments_v15(
    segments: tuple[SegmentationAnchoredProviderSegmentV15, ...],
    *,
    source: str,
    own_trigger_context_overlap_allowed: bool = False,
) -> tuple[SegmentationProviderSegment, ...]:
    unit_rows = taste_source_comment_unit_offsets(source)
    units = {
        unit_id: (ordinal, start, end)
        for ordinal, (unit_id, _, start, end) in enumerate(unit_rows, 1)
    }

    def resolve_range(
        selected: SegmentationAnchoredEvidenceRange,
    ) -> tuple[int, int, int, int]:
        try:
            start_ordinal, start_char, _ = units[selected.start_unit_id]
            end_ordinal, _, end_char = units[selected.end_unit_id]
        except KeyError as error:
            raise ValueError(
                "Segmentation provider selected an unknown evidence-unit ID"
            ) from error
        if end_ordinal < start_ordinal:
            raise ValueError("Segmentation provider evidence-unit range is reversed")
        return start_ordinal, end_ordinal, start_char, end_char

    resolved: list[SegmentationProviderSegment] = []
    trigger_intervals: list[tuple[int, int]] = []
    for segment in segments:
        _, _, start_char, end_char = resolve_range(segment.trigger_range)
        trigger_intervals.append((start_char, end_char))
        contexts: list[SegmentationProviderContextRange] = []
        context_intervals: list[tuple[int, int]] = []
        context_unit_intervals: list[tuple[int, int]] = []
        for context in segment.context_ranges:
            (
                context_start_ordinal,
                context_end_ordinal,
                context_start,
                context_end,
            ) = resolve_range(context)
            context_intervals.append((context_start, context_end))
            context_unit_intervals.append((context_start_ordinal, context_end_ordinal))
            contexts.append(
                SegmentationProviderContextRange(
                    verbatim_context_text=source[context_start:context_end],
                    start_char=context_start,
                    end_char=context_end,
                )
            )
        if context_intervals != sorted(set(context_intervals)):
            raise ValueError("Segmentation provider context ranges are unordered or repeated")
        if any(
            first_end + 1 >= second_start
            for (_, first_end), (second_start, _) in pairwise(context_unit_intervals)
        ):
            raise ValueError(
                "Segmentation provider context evidence-unit ranges overlap or are adjacent"
            )
        if not own_trigger_context_overlap_allowed and any(
            context_start < end_char and context_end > start_char
            for context_start, context_end in context_intervals
        ):
            raise ValueError("Segmentation provider context overlaps its decision trigger")
        resolved.append(
            SegmentationProviderSegment(
                verbatim_decision_text=source[start_char:end_char],
                primary_decision_family=segment.primary_decision_family,
                atomic_decision_statement=segment.atomic_decision_statement,
                rationale=segment.rationale,
                uncertainty=segment.uncertainty,
                start_char=start_char,
                end_char=end_char,
                context_ranges=tuple(contexts),
                own_trigger_context_overlap_allowed=(
                    own_trigger_context_overlap_allowed
                ),
            )
        )
    if trigger_intervals != sorted(trigger_intervals):
        raise ValueError("Segmentation provider trigger ranges are out of order")
    if any(first[1] > second[0] for first, second in pairwise(trigger_intervals)):
        raise ValueError("Segmentation provider trigger ranges overlap")
    return tuple(resolved)


def _resolve_anchored_provider_output(
    output: SegmentationAnchoredProviderOutput,
    *,
    packet: TasteSourceSegmentationRequestPacket,
) -> SegmentationProviderOutput:
    expected = {(item.campaign_token, item.review_item_id): item for item in packet.items}
    resolved = []
    for item in output.items:
        source_item = expected[(item.campaign_token, item.review_item_id)]
        if source_item.evidence_units is None:
            raise ValueError("Segmentation anchored output targets a legacy request item")
        resolved.append(
            SegmentationProviderItem(
                campaign_token=item.campaign_token,
                review_item_id=item.review_item_id,
                segments=_resolve_anchored_segments(
                    item.segments,
                    source=source_item.review_comment,
                ),
                residual_decision_bearing_text_possible=(
                    item.residual_decision_bearing_text_possible
                ),
            )
        )
    return SegmentationProviderOutput(items=tuple(resolved))


def _resolve_anchored_provider_output_v15(
    output: SegmentationAnchoredProviderOutputV15,
    *,
    packet: TasteSourceSegmentationRequestPacket,
    own_trigger_context_overlap_allowed: bool = False,
) -> SegmentationProviderOutput:
    expected = {(item.campaign_token, item.review_item_id): item for item in packet.items}
    resolved = []
    for item in output.items:
        source_item = expected[(item.campaign_token, item.review_item_id)]
        if source_item.evidence_units is None:
            raise ValueError("Segmentation anchored output targets a legacy request item")
        resolved.append(
            SegmentationProviderItem(
                campaign_token=item.campaign_token,
                review_item_id=item.review_item_id,
                segments=_resolve_anchored_segments_v15(
                    item.segments,
                    source=source_item.review_comment,
                    own_trigger_context_overlap_allowed=(
                        own_trigger_context_overlap_allowed
                    ),
                ),
                no_decision_rationale=item.no_decision_rationale,
                residual_decision_bearing_text_possible=(
                    item.residual_decision_bearing_text_possible
                ),
            )
        )
    return SegmentationProviderOutput(items=tuple(resolved))


def _resolve_anchored_adjudication_output(
    output: SegmentationAnchoredAdjudicationProviderOutput,
    *,
    expected_items: dict[tuple[str, str], str],
) -> SegmentationAdjudicationProviderOutput:
    resolved = []
    for item in output.items:
        source = expected_items[(item.campaign_token, item.review_item_id)]
        resolved.append(
            SegmentationAdjudicationProviderItem(
                campaign_token=item.campaign_token,
                review_item_id=item.review_item_id,
                segments=_resolve_anchored_segments(item.segments, source=source),
                residual_decision_bearing_text_possible=(
                    item.residual_decision_bearing_text_possible
                ),
                resolution_rationale=item.resolution_rationale,
            )
        )
    return SegmentationAdjudicationProviderOutput(items=tuple(resolved))


def _resolve_anchored_adjudication_output_v15(
    output: SegmentationAnchoredAdjudicationProviderOutputV15,
    *,
    expected_items: dict[tuple[str, str], str],
    own_trigger_context_overlap_allowed: bool = False,
) -> SegmentationAdjudicationProviderOutput:
    resolved = []
    for item in output.items:
        source = expected_items[(item.campaign_token, item.review_item_id)]
        resolved.append(
            SegmentationAdjudicationProviderItem(
                campaign_token=item.campaign_token,
                review_item_id=item.review_item_id,
                segments=_resolve_anchored_segments_v15(
                    item.segments,
                    source=source,
                    own_trigger_context_overlap_allowed=(
                        own_trigger_context_overlap_allowed
                    ),
                ),
                no_decision_rationale=item.no_decision_rationale,
                residual_decision_bearing_text_possible=(
                    item.residual_decision_bearing_text_possible
                ),
                resolution_rationale=item.resolution_rationale,
            )
        )
    return SegmentationAdjudicationProviderOutput(items=tuple(resolved))


def _reconstruct_segment_text(
    candidate: str,
    *,
    source: str,
) -> tuple[str, int, int]:
    normalized_candidate = _typography_normalize(candidate)
    normalized_source = _typography_normalize(source)
    start = normalized_source.find(normalized_candidate)
    if start < 0 or normalized_source.find(normalized_candidate, start + 1) >= 0:
        raise ValueError("Segmentation normalized span is absent or non-unique")
    end = start + len(candidate)
    restored = source[start:end]
    if len(restored) != len(candidate) or _typography_normalize(restored) != normalized_candidate:
        raise ValueError("Segmentation typography reconstruction changed span length")
    return restored, start, end


def _reconstruct_provider_spans(
    output: SegmentationProviderOutput,
    *,
    packet: TasteSourceSegmentationRequestPacket,
) -> SegmentationProviderOutput:
    sources = {
        (item.campaign_token, item.review_item_id): item.review_comment for item in packet.items
    }
    reconstructed = []
    for item in output.items:
        source = sources[(item.campaign_token, item.review_item_id)]
        segments = []
        intervals: list[tuple[int, int]] = []
        for segment in item.segments:
            restored, start, end = _reconstruct_segment_text(
                segment.verbatim_decision_text,
                source=source,
            )
            intervals.append((start, end))
            segments.append(segment.model_copy(update={"verbatim_decision_text": restored}))
        ordered = sorted(intervals)
        if any(first[1] > second[0] for first, second in pairwise(ordered)):
            raise ValueError("Segmentation provider spans overlap after reconstruction")
        reconstructed.append(item.model_copy(update={"segments": tuple(segments)}))
    return SegmentationProviderOutput(items=tuple(reconstructed))


def _reconstruct_adjudication_spans(
    output: SegmentationAdjudicationProviderOutput,
    *,
    expected_items: dict[tuple[str, str], str],
) -> SegmentationAdjudicationProviderOutput:
    reconstructed = []
    for item in output.items:
        source = expected_items[(item.campaign_token, item.review_item_id)]
        segments = []
        intervals: list[tuple[int, int]] = []
        for segment in item.segments:
            restored, start, end = _reconstruct_segment_text(
                segment.verbatim_decision_text,
                source=source,
            )
            intervals.append((start, end))
            segments.append(segment.model_copy(update={"verbatim_decision_text": restored}))
        ordered = sorted(intervals)
        if any(first[1] > second[0] for first, second in pairwise(ordered)):
            raise ValueError("Segmentation adjudication spans overlap after reconstruction")
        reconstructed.append(item.model_copy(update={"segments": tuple(segments)}))
    return SegmentationAdjudicationProviderOutput(items=tuple(reconstructed))


def _compile_span_reconstruction_receipts(
    *,
    raw_text: str,
    output: object,
    protocol: TasteSourceSegmentationProspectiveProtocol,
    source_texts: dict[tuple[str, str], str] | None,
) -> tuple[SegmentationSpanReconstructionReceipt, ...]:
    if protocol.evidence_unit_selection is not None:
        return ()
    if not isinstance(
        output,
        (SegmentationProviderOutput, SegmentationAdjudicationProviderOutput),
    ):
        return ()
    if source_texts is None:
        raise ValueError("Segmentation reconstruction receipt lacks source text")
    payload = json.loads(raw_text)
    raw_output = (
        SegmentationAdjudicationProviderOutput.model_validate(payload)
        if isinstance(output, SegmentationAdjudicationProviderOutput)
        else SegmentationProviderOutput.model_validate(payload)
    )
    raw_items = {(item.campaign_token, item.review_item_id): item for item in raw_output.items}
    receipts = []
    for item in output.items:
        raw_item = raw_items[(item.campaign_token, item.review_item_id)]
        if len(raw_item.segments) != len(item.segments):
            raise ValueError("Segmentation reconstruction changed segment count")
        for ordinal, (raw_segment, restored_segment) in enumerate(
            zip(raw_item.segments, item.segments, strict=True),
            1,
        ):
            raw_value = raw_segment.verbatim_decision_text
            restored = restored_segment.verbatim_decision_text
            if raw_value == restored:
                continue
            changed = sum(
                first != second for first, second in zip(raw_value, restored, strict=True)
            )
            source = source_texts[(item.campaign_token, item.review_item_id)]
            start = source.find(restored)
            if start < 0 or source.find(restored, start + 1) >= 0:
                raise ValueError("Reconstructed segmentation source slice is not unique")
            receipts.append(
                SegmentationSpanReconstructionReceipt(
                    campaign_token=item.campaign_token,
                    review_item_id=item.review_item_id,
                    segment_ordinal=ordinal,
                    algorithm="unicode-typography-normalized-unique-match-v1",
                    provider_text_sha256=hashlib.sha256(raw_value.encode()).hexdigest(),
                    source_text_sha256=hashlib.sha256(restored.encode()).hexdigest(),
                    start_char=start,
                    end_char=start + len(restored),
                    changed_codepoint_count=changed,
                )
            )
    return tuple(receipts)


def _compile_evidence_unit_selection_receipts(
    *,
    raw_text: str,
    output: object,
    protocol: TasteSourceSegmentationProspectiveProtocol,
    source_texts: dict[tuple[str, str], str] | None,
) -> tuple[SegmentationEvidenceUnitSelectionReceipt, ...]:
    if not isinstance(
        output,
        (SegmentationProviderOutput, SegmentationAdjudicationProviderOutput),
    ):
        return ()
    if source_texts is None:
        raise ValueError("Segmentation evidence-unit receipt lacks source text")
    payload = json.loads(raw_text)
    if protocol.schema_version == "1.5":
        anchored = (
            SegmentationAnchoredAdjudicationProviderOutputV15.model_validate(payload)
            if isinstance(output, SegmentationAdjudicationProviderOutput)
            else SegmentationAnchoredProviderOutputV15.model_validate(payload)
        )
    else:
        anchored = (
            SegmentationAnchoredAdjudicationProviderOutput.model_validate(payload)
            if isinstance(output, SegmentationAdjudicationProviderOutput)
            else SegmentationAnchoredProviderOutput.model_validate(payload)
        )
    anchored_items = {(item.campaign_token, item.review_item_id): item for item in anchored.items}
    receipts = []
    for item in output.items:
        key = (item.campaign_token, item.review_item_id)
        anchored_item = anchored_items[key]
        if len(anchored_item.segments) != len(item.segments):
            raise ValueError("Segmentation evidence-unit resolution changed segment count")
        source = source_texts[key]
        rows = taste_source_comment_unit_offsets(source)
        unit_map = {
            unit_id: (ordinal, start, end)
            for ordinal, (unit_id, _, start, end) in enumerate(rows, 1)
        }
        table_hash = taste_source_evidence_unit_table_sha256(source)
        for ordinal, (raw_segment, segment) in enumerate(
            zip(anchored_item.segments, item.segments, strict=True),
            1,
        ):
            trigger = (
                raw_segment.trigger_range
                if isinstance(raw_segment, SegmentationAnchoredProviderSegmentV15)
                else raw_segment
            )
            _, start, _ = unit_map[trigger.start_unit_id]
            _, _, end = unit_map[trigger.end_unit_id]
            restored = source[start:end]
            if (
                segment.verbatim_decision_text != restored
                or segment.start_char != start
                or segment.end_char != end
            ):
                raise ValueError("Segmentation evidence-unit receipt differs from source slice")
            receipts.append(
                SegmentationEvidenceUnitSelectionReceipt(
                    campaign_token=item.campaign_token,
                    review_item_id=item.review_item_id,
                    segment_ordinal=ordinal,
                    algorithm="unicode-word-punctuation-v1",
                    start_unit_id=trigger.start_unit_id,
                    end_unit_id=trigger.end_unit_id,
                    source_comment_sha256=hashlib.sha256(source.encode()).hexdigest(),
                    evidence_unit_table_sha256=table_hash,
                    source_text_sha256=hashlib.sha256(restored.encode()).hexdigest(),
                    start_char=start,
                    end_char=end,
                )
            )
            if isinstance(raw_segment, SegmentationAnchoredProviderSegmentV15):
                if len(raw_segment.context_ranges) != len(segment.context_ranges):
                    raise ValueError("Segmentation context resolution changed range count")
                for context_ordinal, (raw_context, context) in enumerate(
                    zip(raw_segment.context_ranges, segment.context_ranges, strict=True),
                    1,
                ):
                    _, context_start, _ = unit_map[raw_context.start_unit_id]
                    _, _, context_end = unit_map[raw_context.end_unit_id]
                    context_text = source[context_start:context_end]
                    if (
                        context.verbatim_context_text != context_text
                        or context.start_char != context_start
                        or context.end_char != context_end
                    ):
                        raise ValueError(
                            "Segmentation context evidence receipt differs from source slice"
                        )
                    receipts.append(
                        SegmentationEvidenceUnitSelectionReceipt(
                            campaign_token=item.campaign_token,
                            review_item_id=item.review_item_id,
                            segment_ordinal=ordinal,
                            range_role="context",
                            context_ordinal=context_ordinal,
                            algorithm="unicode-word-punctuation-v1",
                            start_unit_id=raw_context.start_unit_id,
                            end_unit_id=raw_context.end_unit_id,
                            source_comment_sha256=hashlib.sha256(source.encode()).hexdigest(),
                            evidence_unit_table_sha256=table_hash,
                            source_text_sha256=hashlib.sha256(context_text.encode()).hexdigest(),
                            start_char=context_start,
                            end_char=context_end,
                        )
                    )
    return tuple(receipts)


def _compile_evidence_unit_item_receipts(
    *,
    output: object,
    source_texts: dict[tuple[str, str], str] | None,
) -> tuple[SegmentationEvidenceUnitItemReceipt, ...]:
    if not isinstance(
        output,
        (SegmentationProviderOutput, SegmentationAdjudicationProviderOutput),
    ):
        return ()
    if source_texts is None:
        raise ValueError("Segmentation evidence-unit item receipt lacks source text")
    receipts = []
    for item in output.items:
        key = (item.campaign_token, item.review_item_id)
        source = source_texts[key]
        receipts.append(
            SegmentationEvidenceUnitItemReceipt(
                campaign_token=item.campaign_token,
                review_item_id=item.review_item_id,
                source_comment_sha256=hashlib.sha256(source.encode()).hexdigest(),
                evidence_unit_table_sha256=taste_source_evidence_unit_table_sha256(source),
                segment_count=len(item.segments),
                zero_decision=not item.segments,
                no_decision_rationale_sha256=(
                    hashlib.sha256(item.no_decision_rationale.encode()).hexdigest()
                    if item.no_decision_rationale is not None
                    else None
                ),
                residual_decision_bearing_text_possible=(
                    item.residual_decision_bearing_text_possible
                ),
            )
        )
    return tuple(receipts)


def _campaign_token_map(
    inspection: TasteSourceSegmentationExecutionInspection,
) -> dict[str, str]:
    mapping = {
        segmentation_campaign_token(
            inspection.request_pack.pack_id,
            snapshot.campaign.campaign_id,
        ): snapshot.campaign.campaign_id
        for snapshot in inspection.campaigns
    }
    observed_tokens = {
        item.campaign_token for packet in inspection.packets for item in packet.items
    }
    if set(mapping) != observed_tokens:
        raise ValueError("Segmentation campaign token map differs from the request pack")
    return mapping


def _packet_item_sources(
    packets: dict[tuple[str, int], TasteSourceSegmentationRequestPacket],
) -> dict[tuple[str, str], tuple[int, str, str]]:
    sources: dict[tuple[str, str], tuple[int, str, str]] = {}
    for (_, shard), packet in packets.items():
        for item in packet.items:
            key = (item.campaign_token, item.review_item_id)
            value = (shard, item.reviewed_abstract, item.review_comment)
            if key in sources and sources[key] != value:
                raise ValueError("Segmenter request packets expose different item content")
            sources[key] = value
    if len(sources) * 2 != sum(len(packet.items) for packet in packets.values()):
        raise ValueError("Segmenter request packet coverage is inconsistent")
    return sources


def _legacy_segmenter_payload(
    *,
    slot: str,
    items: list[SegmentationProviderItem],
    token_to_campaign: dict[str, str],
    protocol: TasteSourceSegmentationProspectiveProtocol,
    sample_sha256: str,
    authorization_sha256: str,
) -> dict[str, JsonValue]:
    normalized_items = []
    for item in sorted(items, key=lambda value: (value.campaign_token, value.review_item_id)):
        normalized_items.append(
            {
                "campaign_id": token_to_campaign[item.campaign_token],
                "review_item_id": item.review_item_id,
                "segments": [
                    _canonical_provider_segment_payload(
                        segment,
                        include_offsets=protocol.evidence_unit_selection is not None,
                    )
                    for segment in item.segments
                ],
                **(
                    {"no_decision_rationale": item.no_decision_rationale}
                    if item.no_decision_rationale is not None
                    else {}
                ),
                "residual_decision_bearing_text_possible": (
                    item.residual_decision_bearing_text_possible
                ),
            }
        )
    return {
        "rubric_read": True,
        "sample_manifest_read": True,
        "rubric_file_sha256": protocol.segmentation_rubric.file_sha256,
        "sample_sha256": sample_sha256,
        "input_boundary": {
            "other_segmenter_outputs_read": False,
            "private_item_map_read": False,
            "population_outcomes_read": False,
        },
        "runner_binding": {
            "segmenter_slot": slot,
            "authorization_sha256": authorization_sha256,
        },
        "items": normalized_items,
    }


def _anonymous_candidate(
    item: SegmentationProviderItem,
    *,
    nested_anchor_contract: bool,
    source: str | None,
) -> dict[str, JsonValue]:
    if source is not None:
        rows = taste_source_comment_unit_offsets(source)
        start_ids = {start: unit_id for unit_id, _, start, _ in rows}
        end_ids = {end: unit_id for unit_id, _, _, end in rows}
        segments: list[dict[str, JsonValue]] = []
        for segment in item.segments:
            if segment.start_char is None or segment.end_char is None:
                raise ValueError("Anchored anonymous candidate lacks deterministic offsets")
            try:
                start_unit_id = start_ids[segment.start_char]
                end_unit_id = end_ids[segment.end_char]
            except KeyError as error:
                raise ValueError(
                    "Anchored candidate offsets differ from unit boundaries"
                ) from error
            segment_payload: dict[str, JsonValue] = {
                "primary_decision_family": segment.primary_decision_family,
                "atomic_decision_statement": segment.atomic_decision_statement,
                "rationale": segment.rationale,
                "uncertainty": segment.uncertainty,
            }
            if nested_anchor_contract:
                context_payload: list[JsonValue] = []
                for context in segment.context_ranges:
                    try:
                        context_start_unit_id = start_ids[context.start_char]
                        context_end_unit_id = end_ids[context.end_char]
                    except KeyError as error:
                        raise ValueError(
                            "Anchored candidate context differs from unit boundaries"
                        ) from error
                    context_payload.append(
                        {
                            "start_unit_id": context_start_unit_id,
                            "end_unit_id": context_end_unit_id,
                        }
                    )
                segment_payload.update(
                    {
                        "trigger_range": {
                            "start_unit_id": start_unit_id,
                            "end_unit_id": end_unit_id,
                        },
                        "context_ranges": context_payload,
                    }
                )
            else:
                segment_payload.update(
                    {
                        "start_unit_id": start_unit_id,
                        "end_unit_id": end_unit_id,
                    }
                )
            segments.append(segment_payload)
        return {
            "segments": segments,
            **(
                {"no_decision_rationale": item.no_decision_rationale}
                if nested_anchor_contract
                else {}
            ),
            "residual_decision_bearing_text_possible": (
                item.residual_decision_bearing_text_possible
            ),
        }
    return {
        "segments": [segment.model_dump(mode="json") for segment in item.segments],
        **(
            {"no_decision_rationale": item.no_decision_rationale}
            if item.no_decision_rationale is not None
            else {}
        ),
        "residual_decision_bearing_text_possible": (item.residual_decision_bearing_text_possible),
    }


def _canonical_provider_segment_payload(
    segment: SegmentationProviderSegment,
    *,
    include_offsets: bool,
) -> dict[str, JsonValue]:
    payload = segment.model_dump(mode="json")
    if include_offsets:
        if segment.start_char is None or segment.end_char is None:
            raise ValueError("Anchored segmentation segment lacks deterministic offsets")
        payload["start_char"] = segment.start_char
        payload["end_char"] = segment.end_char
        if segment.context_ranges:
            payload["context_ranges"] = [
                {
                    "verbatim_context_text": context.verbatim_context_text,
                    "start_char": context.start_char,
                    "end_char": context.end_char,
                }
                for context in segment.context_ranges
            ]
    return payload


def _legacy_resolution_payload(
    *,
    agreement: TasteSourceSegmentationAgreementReport,
    segmenter_a: TasteSourceDecisionSegmentationRun,
    campaign_to_token: dict[str, str],
    adjudicated: dict[tuple[str, str], SegmentationAdjudicationProviderItem],
    rubric_file_sha256: str,
    authorization_sha256: str,
) -> dict[str, JsonValue]:
    segmenter_items = {(item.campaign_id, item.review_item_id): item for item in segmenter_a.items}
    resolved: list[dict[str, JsonValue]] = []
    for item in agreement.items:
        token = campaign_to_token[item.campaign_id]
        key = (token, item.review_item_id)
        if item.requires_adjudication:
            adjudicated_item = adjudicated.get(key)
            if adjudicated_item is None:
                raise ValueError("Segmentation resolution lacks an adjudicated disputed item")
            segments = [
                _canonical_provider_segment_payload(
                    segment,
                    include_offsets=segment.start_char is not None,
                )
                for segment in adjudicated_item.segments
            ]
            residual = adjudicated_item.residual_decision_bearing_text_possible
            no_decision_rationale = adjudicated_item.no_decision_rationale
            rationale = adjudicated_item.resolution_rationale
            resolution_kind = "ai-adjudicated"
        else:
            source = segmenter_items[(item.campaign_id, item.review_item_id)]
            segments = [
                {
                    "verbatim_decision_text": segment.verbatim_decision_text,
                    "start_char": segment.start_char,
                    "end_char": segment.end_char,
                    "primary_decision_family": str(segment.primary_decision_family),
                    "atomic_decision_statement": segment.atomic_decision_statement,
                    "rationale": segment.rationale,
                    "uncertainty": segment.uncertainty,
                    **(
                        {
                            "context_ranges": [
                                {
                                    "verbatim_context_text": context.verbatim_context_text,
                                    "start_char": context.start_char,
                                    "end_char": context.end_char,
                                }
                                for context in segment.context_ranges
                            ]
                        }
                        if segment.context_ranges
                        else {}
                    ),
                }
                for segment in source.segments
            ]
            residual = source.residual_decision_bearing_text_possible
            no_decision_rationale = source.no_decision_rationale
            if agreement.routing_contract == "decision-boundary-only-v2":
                rationale = (
                    "Copied deterministically from decision-boundary agreement; "
                    "free-text explanation differences were diagnostic only."
                )
                resolution_kind = "decision-boundary-agreement"
            else:
                rationale = "Copied deterministically from exact dual-agent agreement."
                resolution_kind = "exact-dual-agent-agreement"
        resolved.append(
            {
                "campaign_id": item.campaign_id,
                "review_item_id": item.review_item_id,
                "resolution_kind": resolution_kind,
                "source_blocker_codes": list(item.blocker_codes),
                "segments": segments,
                **(
                    {"no_decision_rationale": no_decision_rationale}
                    if no_decision_rationale is not None
                    else {}
                ),
                "residual_decision_bearing_text_possible": residual,
                "resolution_rationale": rationale,
            }
        )
    return {
        "rubric_read": True,
        "rubric_file_sha256": rubric_file_sha256,
        "source_agreement_report_sha256": agreement.report_sha256,
        "input_boundary": {
            "segmenter_outputs_read": True,
            "private_item_map_read": False,
            "population_outcomes_read": False,
        },
        "runner_binding": {"authorization_sha256": authorization_sha256},
        "items": resolved,
    }


def _estimate_call_cost_cny(
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    price: SegmentationExecutionPriceCeiling,
) -> float:
    uncached = input_tokens - cached_input_tokens
    return (
        uncached * price.input_cache_miss_cny_per_million_tokens
        + cached_input_tokens * price.input_cache_hit_cny_per_million_tokens
        + output_tokens * price.output_cny_per_million_tokens
    ) / 1_000_000


def _artifact_binding(
    path: Path,
    *,
    root: Path,
    semantic_sha256: str,
) -> SegmentationRunArtifactBinding:
    return SegmentationRunArtifactBinding(
        locator=_relative_to_root(path, root),
        file_sha256=_sha256_file(path),
        semantic_sha256=semantic_sha256,
    )


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("Segmentation artifact escapes its locator root") from error


def _write_json_new(path: Path, payload: object) -> None:
    raw = (
        json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    _atomic_bytes(path, raw)


def _claim_execution_ledger(path: Path, ledger: SegmentationExecutionLedger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (ledger.model_dump_json(indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _replace_execution_ledger(path: Path, ledger: SegmentationExecutionLedger) -> None:
    raw = (ledger.model_dump_json(indent=2) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_execution_ledger(path: Path) -> SegmentationExecutionLedger:
    payload = json.loads(_bounded_file(path, _MAX_AUTHORIZATION_BYTES).read_bytes())
    return SegmentationExecutionLedger.model_validate(payload)


def _fail_execution_ledger(
    ledger_path: Path,
    ledger: SegmentationExecutionLedger,
    output_root: Path,
    error: Exception,
    failed_sequence: int | None = None,
    failed_request_sha256: str | None = None,
    failed_response_sha256: str | None = None,
    failed_http_status: int | None = None,
    failed_raw_request_ref: str | None = None,
    failed_raw_response_ref: str | None = None,
) -> None:
    failed = SegmentationExecutionLedger(
        authorization_sha256=ledger.authorization_sha256,
        run_id=ledger.run_id,
        one_time_nonce=ledger.one_time_nonce,
        status="failed",
        completed_sequences=ledger.completed_sequences,
        failed_sequence=failed_sequence,
        failed_request_sha256=failed_request_sha256,
        failed_response_sha256=failed_response_sha256,
        failed_http_status=failed_http_status,
        failed_raw_request_ref=failed_raw_request_ref,
        failed_raw_response_ref=failed_raw_response_ref,
        provider_call_may_have_started=ledger.provider_call_may_have_started,
        updated_at=datetime.now(UTC),
    )
    _replace_execution_ledger(ledger_path, failed)
    marker = output_root / "FAILED.json"
    if output_root.is_dir() and not output_root.is_symlink() and not marker.exists():
        _write_json_new(
            marker,
            {
                "run_id": ledger.run_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "completed_sequences": list(ledger.completed_sequences),
                "provider_call_may_have_started": ledger.provider_call_may_have_started,
                "failed_sequence": failed_sequence,
                "failed_request_sha256": failed_request_sha256,
                "failed_response_sha256": failed_response_sha256,
                "failed_http_status": failed_http_status,
                "failed_raw_request_ref": failed_raw_request_ref,
                "failed_raw_response_ref": failed_raw_response_ref,
                "retry_authorized": False,
                "not_human_review": True,
            },
        )


def load_taste_source_segmentation_execution_authorization(
    path: str | Path,
) -> TasteSourceSegmentationExecutionAuthorization:
    source = _bounded_file(Path(path), _MAX_AUTHORIZATION_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Segmentation execution authorization must contain a YAML mapping")
    return TasteSourceSegmentationExecutionAuthorization.model_validate(payload)


def save_taste_source_segmentation_execution_authorization(
    authorization: TasteSourceSegmentationExecutionAuthorization,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                authorization.model_dump(mode="json"),
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _bound_path(root: Path, binding: SegmentationExecutionFileBinding) -> Path:
    path = _bounded_file(root / _safe_locator(binding.locator), _MAX_PACKET_BYTES)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("Segmentation execution binding escapes its root") from error
    if _sha256_file(path) != binding.file_sha256:
        raise ValueError("Segmentation execution file binding drifted")
    return path


def _bounded_file(path: Path, maximum_bytes: int) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Segmentation execution input must be a regular non-symlink file")
    if path.stat().st_size > maximum_bytes:
        raise ValueError("Segmentation execution input exceeds its byte ceiling")
    return path.resolve(strict=True)


def _safe_locator(locator: str) -> PurePosixPath:
    candidate = PurePosixPath(locator)
    if (
        "\\" in locator
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Segmentation execution locator is unsafe")
    return candidate


def _git_blob_sha256(root: Path, commit: str, locator: str) -> str:
    _safe_locator(locator)
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{locator}"],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise ValueError("Segmentation execution Git blob is unavailable")
    return hashlib.sha256(result.stdout).hexdigest()


def _verify_runtime_source_tree(root: Path, commit: str) -> None:
    """Require the complete loaded SciTaste source tree to equal the bound commit."""

    source_root = (root / "src/scitaste").resolve(strict=True)
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--quiet",
            "--no-ext-diff",
            commit,
            "--",
            "src/scitaste",
        ],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if tracked.returncode != 0:
        raise ValueError("Segmentation runtime source tree differs from its Git binding")
    untracked = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "src/scitaste",
        ],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if untracked.returncode != 0 or untracked.stdout.strip():
        raise ValueError("Segmentation runtime source tree contains unbound files")

    package = __import__("scitaste")
    if Path(str(package.__file__)).resolve() != source_root / "__init__.py":
        raise ValueError("Segmentation runtime loaded an unbound SciTaste package")
    loaded_modules = {
        "scitaste.evaluation.taste_source_segmentation": (
            source_root / "evaluation/taste_source_segmentation.py"
        ),
        "scitaste.evaluation.taste_source_segmentation_protocol": (
            source_root / "evaluation/taste_source_segmentation_protocol.py"
        ),
        "scitaste.evaluation.taste_source_segmentation_post_audit": (
            source_root / "evaluation/taste_source_segmentation_post_audit.py"
        ),
        "scitaste.evaluation.model_identity": (source_root / "evaluation/model_identity.py"),
        "scitaste.evaluation.natural_taste_review": (
            source_root / "evaluation/natural_taste_review.py"
        ),
        "scitaste.taste.intrinsic": source_root / "taste/intrinsic.py",
        "scitaste.project.models": source_root / "project/models.py",
        "scitaste.resources": source_root / "resources/__init__.py",
        "scitaste.resources.registry": source_root / "resources/registry.py",
    }
    for module_name, expected_path in loaded_modules.items():
        module = __import__(module_name, fromlist=["__name__"])
        if Path(str(module.__file__)).resolve() != expected_path:
            raise ValueError("Segmentation runtime loaded a module outside the bound tree")


def _atomic_bytes(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested for child in value.values() for nested in _recursive_keys(child)
        }
    if isinstance(value, list):
        return {nested for child in value for nested in _recursive_keys(child)}
    return set()


__all__ = [
    "ExtractedProviderResponse",
    "LiveProviderHTTPTransport",
    "ProviderHTTPResponse",
    "ProviderHTTPTransport",
    "SegmentationAdjudicationInputFirewallReceipt",
    "SegmentationAdjudicationProviderItem",
    "SegmentationAdjudicationProviderOutput",
    "SegmentationCalibrationMetrics",
    "SegmentationEvidenceUnitItemReceipt",
    "SegmentationEvidenceUnitSelectionReceipt",
    "SegmentationExecutionAuthority",
    "SegmentationExecutionFileBinding",
    "SegmentationExecutionLimits",
    "SegmentationExecutionPackBinding",
    "SegmentationExecutionPriceCeiling",
    "SegmentationExecutionRunnerBinding",
    "SegmentationInputFirewallReceipt",
    "SegmentationProviderCallReceipt",
    "SegmentationProviderItem",
    "SegmentationProviderOutput",
    "SegmentationProviderSegment",
    "SegmentationRunArtifactBinding",
    "SegmentationSpanReconstructionReceipt",
    "TasteSourceSegmentationCalibrationReceipt",
    "TasteSourceSegmentationExecutionAuthorization",
    "TasteSourceSegmentationExecutionInspection",
    "build_segmentation_adjudication_request",
    "build_segmentation_provider_request",
    "extract_openai_chat_response",
    "inspect_taste_source_segmentation_execution_authorization",
    "load_taste_source_segmentation_execution_authorization",
    "persist_exact_provider_request",
    "run_taste_source_segmentation_calibration",
    "save_taste_source_segmentation_execution_authorization",
    "validate_adjudication_provider_output",
    "validate_segmentation_provider_output",
    "verify_persisted_segmentation_adjudication_request",
    "verify_persisted_segmentation_provider_request",
]
