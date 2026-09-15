"""Frozen prospective calibration inspection and outcome-field-blind request packs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

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
    ApiIdentityMode,
    load_api_identity_protocol,
)
from scitaste.evaluation.natural_taste_review import (
    ScientificTasteSourceReviewItem,
    TasteSourceReviewRole,
    load_taste_source_review_items,
)
from scitaste.evaluation.taste_source_segmentation import (
    TasteSourceSegmentationSampleManifest,
    verify_taste_source_segmentation_sample_bindings,
)
from scitaste.resources import ApiModelDefinition

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_CONFIG_BYTES = 2 * 1_048_576
_MAX_CAMPAIGN_BYTES = 64 * 1_048_576


class SegmentationProtocolFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> SegmentationProtocolFileBinding:
        _safe_locator(self.locator)
        return self


class SegmentationPostAuditGateRubric(BaseModel):
    """Machine-readable AI-only veto gate; never a human validity instrument."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    gate_id: str = Field(pattern=_ID)
    role_id: Literal["ai-d-content-integrity", "ai-e-protocol-authority"]
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    decision_mode: Literal["veto-only"] = "veto-only"
    check_ids: tuple[str, ...] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=4_000)
    input_boundary: dict[str, tuple[str, ...]]
    checks: tuple[str, ...] | None = None
    inventory_rules: tuple[str, ...] | None = None
    output_contract: dict[str, JsonValue]
    authority: dict[str, bool]

    @model_validator(mode="after")
    def gate_is_ai_only_and_veto_only(self) -> SegmentationPostAuditGateRubric:
        if self.check_ids != tuple(dict.fromkeys(self.check_ids)):
            raise ValueError("Segmentation post-audit check IDs must be unique and ordered")
        required = (
            {
                "complete-item-inventory",
                "common-omission",
                "residual-self-report",
                "false-positive-decision",
                "atomic-trigger-and-context",
                "decision-family",
            }
            if self.role_id == "ai-d-content-integrity"
            else {
                "receipt-binding",
                "raw-byte-replay",
                "range-reconstruction",
                "source-group-independence",
                "claim-authority",
                "rolling-alias-identity-boundary",
            }
        )
        if set(self.check_ids) != required:
            raise ValueError("Segmentation post-audit gate check catalog drifted")
        if set(self.input_boundary) != {"allowed", "forbidden"} or not all(
            self.input_boundary[key] for key in ("allowed", "forbidden")
        ):
            raise ValueError("Segmentation post-audit input boundary is incomplete")
        if self.authority.get("may_veto_calibration") is not True or any(
            self.authority.get(key) is not False
            for key in (
                "human_agreement_claim_allowed",
                "benchmark_admission_authorized",
                "formal_evidence_eligible",
            )
        ):
            raise ValueError("Segmentation post-audit gate overclaims authority")
        if self.role_id == "ai-d-content-integrity":
            if (
                self.inventory_rules is None
                or self.checks is not None
                or self.authority.get("inventory_is_gold_label") is not False
            ):
                raise ValueError("AI-D must use a sealed non-gold inventory")
        elif (
            self.checks is None
            or self.inventory_rules is not None
            or self.authority.get("may_override_deterministic_failure") is not False
        ):
            raise ValueError("AI-E cannot override deterministic replay failures")
        return self


class SegmentationPostAuditGateInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    gate: SegmentationPostAuditGateRubric


class SegmentationProtocolSampleBinding(SegmentationProtocolFileBinding):
    sample_sha256: str = Field(pattern=_SHA256)
    item_count: int = Field(gt=0, le=100_000)
    prior_items_excluded: int = Field(gt=0, le=100_000)
    source_balanced: Literal[True] = True
    prior_source_groups_excluded: int | None = Field(default=None, ge=1, le=100_000)
    source_group_disjoint: bool | None = None
    maximum_items_per_source_group: int | None = Field(default=None, ge=1, le=1)
    per_campaign_eligible_source_group_counts: dict[str, int] | None = None
    per_campaign_sampling_fraction_micros: dict[str, int] | None = None
    uncertainty_estimand: Literal[
        "descriptive-calibration-superpopulation-work-model"
    ] | None = None


class SegmentationFreezeSampleBinding(SegmentationProtocolFileBinding):
    sample_sha256: str = Field(pattern=_SHA256)


class SegmentationProtocolPanel(BaseModel):
    model_config = _CONFIG

    segmenter_count: Literal[2] = 2
    adjudicator_count: Literal[1] = 1
    same_model_condition_for_segmenters: Literal[True] = True
    distinct_invocations_required: Literal[True] = True
    cross_output_blinding_required: Literal[True] = True
    adjudicator_must_not_be_a_segmenter_invocation: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    human_review_claim_allowed: Literal[False] = False


class SegmentationProtocolModelCondition(BaseModel):
    model_config = _CONFIG

    state: Literal["selected-for-calibration-not-yet-authenticated"]
    provider_id: str = Field(pattern=_ID)
    resource_id: str = Field(pattern=_ID)
    resource_locator: str = Field(min_length=1, max_length=2_000)
    resource_file_sha256: str = Field(pattern=_SHA256)
    requested_model_id: str = Field(min_length=1, max_length=500)
    identity_mode: Literal["temporal_window_only"]
    identity_protocol_locator: str = Field(min_length=1, max_length=2_000)
    identity_protocol_file_sha256: str = Field(pattern=_SHA256)
    returned_model_allowlist: tuple[str, ...] = Field(min_length=1, max_length=8)
    maximum_window_hours: int = Field(gt=0, le=24)
    start_and_end_sentinels_required: Literal[True] = True
    exact_runtime_receipt_required: Literal[True] = True
    fallback_model_allowed: Literal[False] = False
    identity_claim_scope: Literal[
        "provider-reported-rolling-alias-envelope-continuity-only"
    ] | None = None
    backend_revision_identified: bool | None = None

    @model_validator(mode="after")
    def identities_are_safe(self) -> SegmentationProtocolModelCondition:
        _safe_locator(self.resource_locator)
        _safe_locator(self.identity_protocol_locator)
        if self.requested_model_id not in self.returned_model_allowlist:
            raise ValueError("Requested segmentation model is outside its allowlist")
        return self


class SegmentationProtocolGeneration(BaseModel):
    model_config = _CONFIG

    response_format: Literal["json_object"] = "json_object"
    thinking: Literal["enabled"] = "enabled"
    reasoning_effort: Literal["low"] = "low"
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    maximum_output_tokens_per_call: int = Field(gt=0, le=128_000)
    items_per_shard: int = Field(gt=0, le=1_000)
    segmenter_shards: int = Field(gt=0, le=1_000)
    segmenter_total_requests: int = Field(gt=0, le=10_000)
    maximum_adjudication_shards: int = Field(ge=0, le=1_000)
    identity_sentinel_requests: Literal[2] = 2
    maximum_total_requests: int = Field(gt=0, le=10_000)
    retry_count: Literal[0] = 0

    @model_validator(mode="after")
    def request_formula_is_exact(self) -> SegmentationProtocolGeneration:
        if self.segmenter_total_requests != 2 * self.segmenter_shards:
            raise ValueError("Segmentation request count differs from its two segmenters")
        expected_total = (
            self.segmenter_total_requests
            + self.maximum_adjudication_shards
            + self.identity_sentinel_requests
        )
        if self.maximum_total_requests != expected_total:
            raise ValueError("Segmentation maximum request count is inconsistent")
        return self


class SegmentationProtocolSpanReconstruction(BaseModel):
    """Precommitted one-character typography repair, never fuzzy alignment."""

    model_config = _CONFIG

    provider_text_role: Literal["candidate-locator-not-source-of-record"]
    locator_algorithm: Literal["unicode-typography-normalized-unique-match-v1"]
    allowed_codepoint_map: Literal["2018,2019->0027;201C,201D->0022;00A0->0020"]
    unique_normalized_match_required: Literal[True] = True
    reconstructed_text_source: Literal["original-review-comment-slice"]
    fuzzy_matching_allowed: Literal[False] = False
    insertion_or_deletion_allowed: Literal[False] = False


class SegmentationProtocolEvidenceUnitSelection(BaseModel):
    """Deterministic source anchors selected by ID, never copied by the model."""

    model_config = _CONFIG

    unitizer_algorithm: Literal["unicode-word-punctuation-v1"]
    token_pattern: Literal[r"\w+|[^\w\s]"]
    unit_id_format: Literal["u%04d"]
    unit_text_source: Literal["original-review-comment"]
    source_offsets_exposed_to_provider: Literal[False] = False
    model_returns_source_span_field: Literal[False] = Field(
        default=False,
        validation_alias=AliasChoices(
            "model_returns_source_span_field",
            "model_returns_source_text",
        ),
    )
    reconstructed_text_source: Literal["original-review-comment-slice"]
    unique_text_match_required: Literal[False] = False
    normalization_allowed: Literal[False] = False
    fuzzy_matching_allowed: Literal[False] = False
    insertion_or_deletion_repair_allowed: Literal[False] = False
    overlapping_ranges_allowed: Literal[False] = False
    system_instruction_sha256: str | None = Field(default=None, pattern=_SHA256)
    output_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    range_contract: Literal["trigger-plus-shared-context-v1"] | None = None
    zero_decision_allowed: bool | None = None
    maximum_context_ranges_per_decision: int | None = Field(default=None, ge=0, le=8)
    trigger_ranges_overlapping_allowed: bool | None = None
    context_ranges_may_overlap_across_decisions: bool | None = None
    context_may_overlap_another_decision_trigger: bool | None = None


class SegmentationProtocolInputFirewall(BaseModel):
    model_config = _CONFIG

    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    request_payload_must_be_persisted_before_provider_contact: Literal[True] = True
    no_provider_tools_exposed: Literal[True] = True
    structured_source_identity_fields_withheld: Literal[True] = Field(
        default=True,
        validation_alias=AliasChoices(
            "structured_source_identity_fields_withheld",
            "explicit_source_identity_withheld",
        ),
    )
    explicit_outcome_fields_withheld: Literal[True] = True
    parametric_source_recognition_ruled_out: Literal[False] = False
    boundary_statement: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def firewall_is_closed(self) -> SegmentationProtocolInputFirewall:
        legacy_allowed = {
            "frozen segmentation or adjudication rubric",
            "assigned scientific item abstract",
            "assigned scientific item review comment",
            "opaque campaign and review item identifiers",
        }
        segmenter_allowed = {
            "frozen segmentation rubric",
            "assigned scientific item abstract",
            "assigned scientific item review comment",
            "opaque campaign and review item identifiers",
        }
        anchored_segmenter_allowed = segmenter_allowed | {
            "deterministic source evidence-unit table"
        }
        required_forbidden = {
            "private item map",
            "publisher or source identity",
            "recommendation",
            "author response",
            "later revision",
            "population outcome",
            "another segmenter output",
            "arbitrary tools",
            "web search",
        }
        if set(self.allowed) not in (
            legacy_allowed,
            segmenter_allowed,
            anchored_segmenter_allowed,
        ):
            raise ValueError("Segmentation input allowlist drifted")
        if not required_forbidden.issubset(self.forbidden):
            raise ValueError("Segmentation input firewall is incomplete")
        if len(self.allowed) != len(set(self.allowed)) or len(self.forbidden) != len(
            set(self.forbidden)
        ):
            raise ValueError("Segmentation firewall entries must be unique")
        return self


class SegmentationProtocolAdjudicationInputFirewall(BaseModel):
    """Distinct disputed-only boundary for the third AI adjudicator."""

    model_config = _CONFIG

    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    disputed_items_only: Literal[True] = True
    exact_agreement_items_copied_deterministically: Literal[True] = True
    candidate_order_anonymized_and_hash_randomized: Literal[True] = True
    no_provider_tools_exposed: Literal[True] = True
    structured_source_identity_fields_withheld: Literal[True] = Field(
        default=True,
        validation_alias=AliasChoices(
            "structured_source_identity_fields_withheld",
            "explicit_source_identity_withheld",
        ),
    )
    explicit_outcome_fields_withheld: Literal[True] = True
    parametric_source_recognition_ruled_out: Literal[False] = False
    boundary_statement: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def adjudication_firewall_is_closed(
        self,
    ) -> SegmentationProtocolAdjudicationInputFirewall:
        required_allowed = {
            "frozen adjudication rubric",
            "assigned disputed item abstract and review comment",
            "typed agreement blockers",
            "two anonymous segmenter candidates in hash-randomized order",
            "opaque campaign and review item identifiers",
        }
        anchored_required_allowed = required_allowed | {
            "deterministic source evidence-unit table"
        }
        required_forbidden = {
            "private item map",
            "publisher or source identity",
            "recommendation",
            "author response",
            "later revision",
            "population outcome",
            "non-disputed items",
            "segmenter slot identities",
            "arbitrary tools",
            "web search",
        }
        if set(self.allowed) not in (required_allowed, anchored_required_allowed):
            raise ValueError("Segmentation adjudication input allowlist drifted")
        if not required_forbidden.issubset(self.forbidden):
            raise ValueError("Segmentation adjudication input firewall is incomplete")
        if len(self.allowed) != len(set(self.allowed)) or len(self.forbidden) != len(
            set(self.forbidden)
        ):
            raise ValueError("Segmentation adjudication firewall entries must be unique")
        return self


class SegmentationProtocolMetrics(BaseModel):
    model_config = _CONFIG

    exact_span_f1: dict[str, JsonValue]
    overlap_span_f1: dict[str, JsonValue]
    overlap_matched_family_agreement: dict[str, JsonValue]
    adjudication_item_rate: dict[str, JsonValue]
    residual_risk_item_rate_after_adjudication: dict[str, JsonValue]
    decision_presence_agreement: dict[str, JsonValue] | None = None
    exact_trigger_context_set_agreement: dict[str, JsonValue] | None = None
    source_group_uncertainty: dict[str, JsonValue] | None = None
    thresholds_frozen_before_execution: Literal[True] = True

    @model_validator(mode="after")
    def engineering_gate_is_fixed(self) -> SegmentationProtocolMetrics:
        if self.exact_span_f1 != {
            "role": "conservative-routing-diagnostic",
            "threshold": None,
        }:
            raise ValueError("Exact-span metric must remain diagnostic")
        if self.overlap_span_f1 != {
            "matching": "deterministic-maximum-cardinality-interval-iou",
            "iou_threshold": 0.5,
            "pass_threshold": 0.8,
        }:
            raise ValueError("Prospective overlap metric drifted")
        if self.overlap_matched_family_agreement != {"pass_threshold": 0.8}:
            raise ValueError("Prospective family metric drifted")
        if self.adjudication_item_rate != {"pass_threshold_maximum": 0.5}:
            raise ValueError("Prospective adjudication-rate metric drifted")
        if self.residual_risk_item_rate_after_adjudication != {"pass_threshold_maximum": 0.0}:
            raise ValueError("Prospective residual-risk metric drifted")
        if self.decision_presence_agreement is not None and self.decision_presence_agreement != {
            "role": "reported-primary-diagnostic",
            "pass_threshold": 0.8,
        }:
            raise ValueError("Decision-presence agreement metric drifted")
        if (
            self.exact_trigger_context_set_agreement is not None
            and self.exact_trigger_context_set_agreement
            != {"role": "reported-diagnostic", "threshold": None}
        ):
            raise ValueError("Trigger-context agreement metric drifted")
        if self.source_group_uncertainty is not None and self.source_group_uncertainty != {
            "unit": "source_group_id",
            "estimator": "campaign-stratified-source-group-bootstrap-v1",
            "estimand": "descriptive-calibration-superpopulation-work-model",
            "scale_gate_role": "diagnostic-only",
            "campaign_weighting": "equal-by-design",
            "confidence_level": 0.95,
            "replicates": 10000,
            "random_seed": 2026091506,
        }:
            raise ValueError("Source-group uncertainty protocol drifted")
        return self


class SegmentationProtocolBudget(BaseModel):
    model_config = _CONFIG

    maximum_provider_requests: int = Field(gt=0)
    maximum_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)
    maximum_api_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    price_unknown_action: Literal["require-cost-receipt-before-first-task-call"]


class SegmentationProtocolFailurePolicy(BaseModel):
    model_config = _CONFIG

    malformed_or_truncated_output: Literal["fail-run-no-retry"]
    missing_usage_or_request_identity: Literal["fail-run-no-retry"]
    returned_model_outside_allowlist: Literal["close-window-and-fail"]
    input_firewall_violation: Literal["invalidate-run"]
    threshold_failure: Literal["revise-rubric-and-freeze-new-protocol-version"]
    same_sample_recalibration_allowed: Literal[False] = False


class SegmentationProtocolAuthority(BaseModel):
    model_config = _CONFIG

    sample_preregistered: Literal[True] = True
    protocol_preregistered: Literal[False] = False
    api_calls_authorized: Literal[False] = False
    calibration_execution_authorized: Literal[False] = False
    scaled_execution_authorized: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False


class SegmentationProtocolScaleGate(BaseModel):
    model_config = _CONFIG

    target_population_item_count: Literal[273] = 273
    calibration_must_pass_all_frozen_metrics: Literal[True] = True
    authenticated_model_window_required: Literal[True] = True
    runtime_identity_required: Literal[True] = True
    input_firewall_receipt_required: Literal[True] = True
    raw_requests_and_responses_required: Literal[True] = True
    scale_requires_separate_content_addressed_execution_manifest: Literal[True] = Field(
        default=True,
        alias="scale_requires_separate_content-addressed_execution_manifest",
    )
    calibration_only_no_direct_scale: bool | None = None
    independent_source_group_validation_required: bool | None = None
    new_source_groups_required_for_validation: bool | None = None


class TasteSourceSegmentationProspectiveProtocol(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"] = "1.0"
    protocol_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    protocol_created_at: datetime
    protocol_status: Literal["candidate-awaiting-git-freeze-receipt"]
    purpose: str = Field(min_length=1, max_length=4_000)
    claim_boundary: str = Field(min_length=1, max_length=4_000)
    sample: SegmentationProtocolSampleBinding
    segmentation_rubric: SegmentationProtocolFileBinding
    adjudication_rubric: SegmentationProtocolFileBinding
    integrity_gate: SegmentationProtocolFileBinding | None = None
    authority_gate: SegmentationProtocolFileBinding | None = None
    panel: SegmentationProtocolPanel
    model_condition: SegmentationProtocolModelCondition
    generation: SegmentationProtocolGeneration
    span_reconstruction: SegmentationProtocolSpanReconstruction | None = None
    evidence_unit_selection: SegmentationProtocolEvidenceUnitSelection | None = None
    consumed_sample_registry: SegmentationProtocolFileBinding | None = None
    input_firewall: SegmentationProtocolInputFirewall
    adjudication_input_firewall: SegmentationProtocolAdjudicationInputFirewall | None = None
    metrics: SegmentationProtocolMetrics
    failure_policy: SegmentationProtocolFailurePolicy
    budget: SegmentationProtocolBudget
    scale_gate: SegmentationProtocolScaleGate
    authority: SegmentationProtocolAuthority
    next_gate: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def protocol_is_no_run(self) -> TasteSourceSegmentationProspectiveProtocol:
        if self.protocol_created_at.utcoffset() is None:
            raise ValueError("Segmentation protocol creation time must include a timezone")
        planned_sample_count = self.generation.items_per_shard * self.generation.segmenter_shards
        if self.sample.item_count != planned_sample_count:
            raise ValueError("Segmentation sample does not fit its exact shard plan")
        task_output_ceiling = (
            self.generation.segmenter_total_requests + self.generation.maximum_adjudication_shards
        ) * self.generation.maximum_output_tokens_per_call
        if self.budget.maximum_provider_requests != self.generation.maximum_total_requests:
            raise ValueError("Segmentation request budget differs from the generation plan")
        if self.budget.maximum_output_tokens < task_output_ceiling:
            raise ValueError("Segmentation output-token budget cannot cover the planned calls")
        if self.schema_version == "1.0" and self.adjudication_input_firewall is not None:
            raise ValueError("Schema 1.0 cannot carry a separate adjudication firewall")
        if self.schema_version in {"1.1", "1.2", "1.3", "1.4", "1.5"} and (
            self.adjudication_input_firewall is None
        ):
            raise ValueError("Schema 1.1+ requires a separate adjudication firewall")
        if (self.schema_version == "1.2") != (self.span_reconstruction is not None):
            raise ValueError("Schema 1.2 uniquely requires bounded span reconstruction")
        if (self.schema_version in {"1.3", "1.4", "1.5"}) != (
            self.evidence_unit_selection is not None
        ):
            raise ValueError("Schema 1.3+ requires evidence-unit selection")
        if (self.schema_version in {"1.2", "1.3", "1.4", "1.5"}) != (
            self.consumed_sample_registry is not None
        ):
            raise ValueError("Schema 1.2+ requires a consumed-sample registry")
        if self.span_reconstruction is not None and self.evidence_unit_selection is not None:
            raise ValueError("Text reconstruction and evidence-unit selection are exclusive")
        expected_rubric_scope = (
            "frozen segmentation or adjudication rubric"
            if self.schema_version == "1.0"
            else "frozen segmentation rubric"
        )
        if expected_rubric_scope not in self.input_firewall.allowed:
            raise ValueError("Segmentation firewall rubric scope differs from schema version")
        segmenter_has_anchor_scope = "deterministic source evidence-unit table" in (
            self.input_firewall.allowed
        )
        adjudicator_has_anchor_scope = "deterministic source evidence-unit table" in (
            self.adjudication_input_firewall.allowed
            if self.adjudication_input_firewall is not None
            else ()
        )
        expected_anchor_scope = self.schema_version in {"1.3", "1.4", "1.5"}
        if (
            segmenter_has_anchor_scope != expected_anchor_scope
            or adjudicator_has_anchor_scope != expected_anchor_scope
        ):
            raise ValueError("Segmentation firewall evidence-unit scope differs from schema")
        if self.evidence_unit_selection is not None:
            pins = (
                self.evidence_unit_selection.system_instruction_sha256,
                self.evidence_unit_selection.output_contract_sha256,
            )
            if (
                self.schema_version in {"1.4", "1.5"}
                and not all(item is not None for item in pins)
            ) or (
                self.schema_version not in {"1.4", "1.5"}
                and any(item is not None for item in pins)
            ):
                raise ValueError("Schema 1.4+ requires anchored request-contract pins")
        if self.schema_version == "1.5":
            assert self.evidence_unit_selection is not None
            evidence = self.evidence_unit_selection
            if (
                evidence.range_contract != "trigger-plus-shared-context-v1"
                or evidence.zero_decision_allowed is not True
                or evidence.maximum_context_ranges_per_decision != 8
                or evidence.trigger_ranges_overlapping_allowed is not False
                or evidence.context_ranges_may_overlap_across_decisions is not True
                or evidence.context_may_overlap_another_decision_trigger is not True
            ):
                raise ValueError("Schema 1.5 trigger/context evidence contract is incomplete")
            if (
                self.sample.source_group_disjoint is not True
                or self.sample.maximum_items_per_source_group != 1
                or self.sample.prior_source_groups_excluded is None
                or self.sample.per_campaign_eligible_source_group_counts is None
                or self.sample.per_campaign_sampling_fraction_micros is None
                or self.sample.uncertainty_estimand
                != "descriptive-calibration-superpopulation-work-model"
            ):
                raise ValueError("Schema 1.5 requires source-group-disjoint sample binding")
            if any(
                value is None
                for value in (
                    self.metrics.decision_presence_agreement,
                    self.metrics.exact_trigger_context_set_agreement,
                    self.metrics.source_group_uncertainty,
                )
            ):
                raise ValueError("Schema 1.5 requires presence, context, and group metrics")
            if self.integrity_gate is None or self.authority_gate is None:
                raise ValueError("Schema 1.5 requires frozen AI-D and AI-E veto gates")
            if (
                self.model_condition.identity_claim_scope
                != "provider-reported-rolling-alias-envelope-continuity-only"
                or self.model_condition.backend_revision_identified is not False
            ):
                raise ValueError("Schema 1.5 overclaims rolling-alias model identity")
            if (
                self.scale_gate.calibration_only_no_direct_scale is not True
                or self.scale_gate.independent_source_group_validation_required is not True
                or self.scale_gate.new_source_groups_required_for_validation is not True
            ):
                raise ValueError("Schema 1.5 cannot authorize scale from calibration alone")
        elif self.integrity_gate is not None or self.authority_gate is not None:
            raise ValueError("Only schema 1.5 carries post-calibration AI veto gates")
        return self


class SegmentationFreezeGit(BaseModel):
    model_config = _CONFIG

    repository: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    commit: str = Field(pattern=_COMMIT)
    worktree_clean_at_commit: Literal[True] = True


class SegmentationFreezeBindingSet(BaseModel):
    model_config = _CONFIG

    protocol: SegmentationProtocolFileBinding
    sample: SegmentationFreezeSampleBinding
    segmentation_rubric: SegmentationProtocolFileBinding
    adjudication_rubric: SegmentationProtocolFileBinding
    integrity_gate: SegmentationProtocolFileBinding | None = None
    authority_gate: SegmentationProtocolFileBinding | None = None
    provider_resource: SegmentationProtocolFileBinding
    identity_policy: SegmentationProtocolFileBinding
    consumed_sample_registry: SegmentationProtocolFileBinding | None = None


class SegmentationFreezeImplementation(BaseModel):
    model_config = _CONFIG

    segmentation_module: SegmentationProtocolFileBinding
    cli: SegmentationProtocolFileBinding
    protocol_module: SegmentationProtocolFileBinding | None = None
    execution_module: SegmentationProtocolFileBinding | None = None


class SegmentationFreezeAttestation(BaseModel):
    model_config = _CONFIG

    first_provider_request_performed_before_freeze: Literal[False] = False
    task_or_sample_content_sent_before_freeze: Literal[False] = False
    source_records_manually_inspected_for_selection: Literal[False] = False
    sample_replay_verified: Literal[True] = True
    retrospective_sample_overlap_count: Literal[0] = 0
    item_count: int = Field(gt=0)
    creates_immutable_protocol_version: Literal[True] = True
    protocol_change_requires_new_version: Literal[True] = True


class SegmentationFreezeAuthority(BaseModel):
    model_config = _CONFIG

    protocol_preregistered_by_external_receipt: Literal[True] = True
    authorizes_provider_contact: Literal[False] = False
    authorizes_calibration_execution: Literal[False] = False
    authorizes_scaled_execution: Literal[False] = False
    authorizes_benchmark_admission: Literal[False] = False
    formal_evidence_eligible: Literal[False] = False


class TasteSourceSegmentationFreezeReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"] = "1.0"
    freeze_receipt_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    frozen_at: datetime
    git: SegmentationFreezeGit
    bindings: SegmentationFreezeBindingSet
    implementation: SegmentationFreezeImplementation
    freeze_attestation: SegmentationFreezeAttestation
    authority: SegmentationFreezeAuthority
    next_gate: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def freeze_is_timestamped(self) -> TasteSourceSegmentationFreezeReceipt:
        if self.frozen_at.utcoffset() is None:
            raise ValueError("Segmentation freeze time must include a timezone")
        extended = (
            self.implementation.protocol_module,
            self.implementation.execution_module,
        )
        if self.schema_version == "1.0" and any(item is not None for item in extended):
            raise ValueError("Schema 1.0 cannot bind prospective execution modules")
        if self.schema_version in {"1.1", "1.2", "1.3", "1.4", "1.5"} and any(
            item is None for item in extended
        ):
            raise ValueError("Schema 1.1+ must bind protocol and execution modules")
        if (self.schema_version in {"1.2", "1.3", "1.4", "1.5"}) != (
            self.bindings.consumed_sample_registry is not None
        ):
            raise ValueError("Schema 1.2+ binds the consumed-sample registry")
        if (self.bindings.integrity_gate is None) != (
            self.bindings.authority_gate is None
        ):
            raise ValueError("Segmentation freeze must bind both AI veto gates")
        veto_gates_bound = (
            self.bindings.integrity_gate is not None
            and self.bindings.authority_gate is not None
        )
        if (self.schema_version == "1.5") != veto_gates_bound:
            raise ValueError("Segmentation freeze AI veto-gate bindings differ from schema")
        return self


class TasteSourceSegmentationProtocolInspection(BaseModel):
    model_config = _CONFIG

    protocol_path: Path
    protocol_file_sha256: str = Field(pattern=_SHA256)
    freeze_receipt_path: Path
    freeze_receipt_file_sha256: str = Field(pattern=_SHA256)
    protocol: TasteSourceSegmentationProspectiveProtocol
    freeze_receipt: TasteSourceSegmentationFreezeReceipt
    sample: TasteSourceSegmentationSampleManifest
    git_commit_verified: Literal[True] = True
    artifact_bindings_verified: Literal[True] = True
    sample_replay_verified: Literal[True] = True
    protocol_frozen_before_provider_contact: Literal[True] = True
    provider_contact_authorized: Literal[False] = False
    calibration_execution_authorized: Literal[False] = False


class TasteSourceSegmentationValidationReserveAudit(BaseModel):
    """Fail-closed reserve for an equally sized independent validation cohort."""

    model_config = _CONFIG

    policy_id: Literal["matched-calibration-size-per-campaign-v1"] = (
        "matched-calibration-size-per-campaign-v1"
    )
    selected_source_group_counts: dict[str, int]
    eligible_source_group_counts: dict[str, int]
    remaining_source_group_counts: dict[str, int]
    required_validation_source_group_counts: dict[str, int]
    ready_for_provider_contact: bool
    blocker_codes: tuple[str, ...]


def assess_taste_source_segmentation_validation_reserve(
    protocol: TasteSourceSegmentationProspectiveProtocol,
    sample: TasteSourceSegmentationSampleManifest,
) -> TasteSourceSegmentationValidationReserveAudit:
    """Require every campaign to retain a calibration-sized unseen validation cohort."""

    selected = dict(sample.per_campaign_source_group_counts or {})
    eligible = dict(protocol.sample.per_campaign_eligible_source_group_counts or {})
    campaigns = sorted(set(selected) | set(eligible))
    remaining = {
        campaign_id: eligible.get(campaign_id, 0) - selected.get(campaign_id, 0)
        for campaign_id in campaigns
    }
    required = {campaign_id: selected.get(campaign_id, 0) for campaign_id in campaigns}
    blockers = tuple(
        f"{campaign_id}:independent-validation-source-group-reserve-below-calibration-size"
        for campaign_id in campaigns
        if remaining[campaign_id] < required[campaign_id]
    )
    return TasteSourceSegmentationValidationReserveAudit(
        selected_source_group_counts=selected,
        eligible_source_group_counts=eligible,
        remaining_source_group_counts=remaining,
        required_validation_source_group_counts=required,
        ready_for_provider_contact=not blockers,
        blocker_codes=blockers,
    )


class TasteSourceEvidenceUnit(BaseModel):
    model_config = _CONFIG

    unit_id: str = Field(pattern=r"^u[0-9]{4}$")
    surface: str = Field(min_length=1, max_length=8_000)


def taste_source_comment_unit_offsets(
    review_comment: str,
) -> tuple[tuple[str, str, int, int], ...]:
    """Return the one authoritative unit-ID/surface/offset mapping."""

    matches = tuple(re.finditer(r"\w+|[^\w\s]", review_comment, flags=re.UNICODE))
    if not matches:
        raise ValueError("Taste source comment has no evidence units")
    if len(matches) > 9_999:
        raise ValueError("Taste source comment exceeds evidence-unit capacity")
    return tuple(
        (f"u{ordinal:04d}", match.group(), match.start(), match.end())
        for ordinal, match in enumerate(matches, 1)
    )


def unitize_taste_source_comment(review_comment: str) -> tuple[TasteSourceEvidenceUnit, ...]:
    """Create provider-visible word/punctuation anchors without exposing offsets."""

    return tuple(
        TasteSourceEvidenceUnit(unit_id=unit_id, surface=surface)
        for unit_id, surface, _, _ in taste_source_comment_unit_offsets(review_comment)
    )


def taste_source_evidence_unit_table_sha256(review_comment: str) -> str:
    """Bind the source bytes, unitizer version, unit IDs, and visible surfaces."""

    units = unitize_taste_source_comment(review_comment)
    return _canonical_sha256(
        {
            "algorithm": "unicode-word-punctuation-v1",
            "review_comment_sha256": hashlib.sha256(review_comment.encode()).hexdigest(),
            "evidence_units": [item.model_dump(mode="json") for item in units],
        }
    )


class TasteSourceSegmentationRequestItem(BaseModel):
    model_config = _CONFIG

    campaign_token: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    reviewed_abstract: str = Field(min_length=1, max_length=8_000)
    review_comment: str = Field(min_length=1, max_length=8_000)
    evidence_units: tuple[TasteSourceEvidenceUnit, ...] | None = None
    evidence_unit_table_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def evidence_units_are_exact(self) -> TasteSourceSegmentationRequestItem:
        if (self.evidence_units is None) != (self.evidence_unit_table_sha256 is None):
            raise ValueError("Segmentation evidence-unit table binding is incomplete")
        if self.evidence_units is None:
            return self
        expected = unitize_taste_source_comment(self.review_comment)
        if self.evidence_units != expected:
            raise ValueError("Segmentation evidence-unit table differs from source bytes")
        observed_hash = taste_source_evidence_unit_table_sha256(self.review_comment)
        if self.evidence_unit_table_sha256 != observed_hash:
            raise ValueError("Segmentation evidence-unit table hash drifted")
        return self


class TasteSourceSegmentationRequestPacket(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    packet_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    protocol_id: str = Field(pattern=_ID)
    sample_sha256: str = Field(pattern=_SHA256)
    sample_manifest_file_sha256: str = Field(pattern=_SHA256)
    rubric_file_sha256: str = Field(pattern=_SHA256)
    segmenter_slot: Literal["segmenter-a", "segmenter-b"]
    shard_index: int = Field(ge=1)
    shard_count: int = Field(ge=1)
    requested_provider: str = Field(pattern=_ID)
    requested_model: str = Field(min_length=1)
    system_instruction: str = Field(min_length=1, max_length=8_000)
    rubric: dict[str, JsonValue]
    items: tuple[TasteSourceSegmentationRequestItem, ...] = Field(min_length=1)
    output_contract: dict[str, JsonValue]
    structured_source_identity_fields_withheld: Literal[True] = True
    explicit_outcome_fields_withheld: Literal[True] = True
    other_segmenter_output_absent: Literal[True] = True
    provider_tools_allowed: Literal[False] = False
    provider_contact_performed: Literal[False] = False

    @model_validator(mode="after")
    def packet_is_scoped(self) -> TasteSourceSegmentationRequestPacket:
        if self.shard_index > self.shard_count:
            raise ValueError("Segmentation request shard index exceeds its count")
        keys = [(item.campaign_token, item.review_item_id) for item in self.items]
        if keys != sorted(set(keys)):
            raise ValueError("Segmentation request items must be sorted and unique")
        anchored = all(item.evidence_units is not None for item in self.items)
        if any(item.evidence_units is not None for item in self.items) != anchored:
            raise ValueError("Segmentation request packet mixes anchored and legacy items")
        if (self.schema_version in {"1.1", "1.2"}) != anchored:
            raise ValueError("Segmentation request packet schema differs from anchor mode")
        return self

    @computed_field
    @property
    def packet_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"packet_sha256"})
        if self.schema_version == "1.0":
            for item in payload["items"]:
                item.pop("evidence_units", None)
                item.pop("evidence_unit_table_sha256", None)
        return _canonical_sha256(payload)


class TasteSourceSegmentationRequestBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)
    packet_sha256: str = Field(pattern=_SHA256)
    segmenter_slot: Literal["segmenter-a", "segmenter-b"]
    shard_index: int = Field(ge=1)
    item_count: int = Field(gt=0)


class TasteSourceSegmentationRequestPack(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    pack_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    created_at: datetime
    protocol_file_sha256: str = Field(pattern=_SHA256)
    freeze_receipt_file_sha256: str = Field(pattern=_SHA256)
    sample_sha256: str = Field(pattern=_SHA256)
    requests: tuple[TasteSourceSegmentationRequestBinding, ...] = Field(min_length=1)
    unique_item_count: int = Field(gt=0)
    segmenter_count: Literal[2] = 2
    request_count: int = Field(gt=0)
    input_field_names: tuple[str, ...]
    forbidden_source_field_names: tuple[str, ...]
    all_request_payloads_persisted: Literal[True] = True
    provider_contact_performed: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def pack_is_closed(self) -> TasteSourceSegmentationRequestPack:
        if self.created_at.utcoffset() is None:
            raise ValueError("Segmentation request-pack time must include a timezone")
        if self.request_count != len(self.requests):
            raise ValueError("Segmentation request-pack count is inconsistent")
        if len({(item.segmenter_slot, item.shard_index) for item in self.requests}) != len(
            self.requests
        ):
            raise ValueError("Segmentation request packets must be unique")
        if sum(item.item_count for item in self.requests) != 2 * self.unique_item_count:
            raise ValueError("Segmentation request-pack item coverage is inconsistent")
        legacy_fields = (
            "campaign_token",
            "review_item_id",
            "reviewed_abstract",
            "review_comment",
        )
        anchored_fields = (
            *legacy_fields,
            "evidence_units",
            "evidence_unit_table_sha256",
        )
        expected_fields = (
            anchored_fields if self.schema_version in {"1.1", "1.2"} else legacy_fields
        )
        if self.input_field_names != expected_fields:
            raise ValueError("Segmentation request-pack input fields drifted")
        required_forbidden = {
            "article_title",
            "author_response",
            "later_revision",
            "observed_recommendation",
            "publisher_subject",
            "source_identity",
        }
        if not required_forbidden.issubset(self.forbidden_source_field_names):
            raise ValueError("Segmentation request-pack forbidden fields are incomplete")
        return self

    @computed_field
    @property
    def pack_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"pack_sha256"}))


def load_segmentation_post_audit_gate(
    path: str | Path,
) -> SegmentationPostAuditGateInspection:
    source = _bounded_file(Path(path), _MAX_CONFIG_BYTES)
    return SegmentationPostAuditGateInspection(
        path=source,
        file_sha256=_sha256_file(source),
        gate=SegmentationPostAuditGateRubric.model_validate(_yaml_mapping(source)),
    )


def inspect_taste_source_segmentation_protocol(
    *,
    protocol_path: str | Path,
    freeze_receipt_path: str | Path,
    locator_root: str | Path,
) -> TasteSourceSegmentationProtocolInspection:
    """Verify the no-run protocol, external freeze, Git snapshot, and sample replay."""

    root = Path(locator_root).resolve(strict=True)
    protocol_source = _bounded_file(Path(protocol_path), _MAX_CONFIG_BYTES)
    freeze_source = _bounded_file(Path(freeze_receipt_path), _MAX_CONFIG_BYTES)
    protocol = TasteSourceSegmentationProspectiveProtocol.model_validate(
        _yaml_mapping(protocol_source)
    )
    freeze = TasteSourceSegmentationFreezeReceipt.model_validate(_yaml_mapping(freeze_source))
    if protocol.project_id != freeze.project_id:
        raise ValueError("Segmentation protocol and freeze target different projects")
    if protocol.schema_version != freeze.schema_version:
        raise ValueError("Segmentation protocol and freeze schema versions differ")
    if freeze.frozen_at < protocol.protocol_created_at:
        raise ValueError("Segmentation freeze predates its protocol")
    if freeze.freeze_attestation.item_count != protocol.sample.item_count:
        raise ValueError("Segmentation freeze item count differs from the protocol")

    expected_bindings = {
        "protocol": (protocol_source, freeze.bindings.protocol),
        "sample": (root / protocol.sample.locator, freeze.bindings.sample),
        "segmentation_rubric": (
            root / protocol.segmentation_rubric.locator,
            freeze.bindings.segmentation_rubric,
        ),
        "adjudication_rubric": (
            root / protocol.adjudication_rubric.locator,
            freeze.bindings.adjudication_rubric,
        ),
        "provider_resource": (
            root / protocol.model_condition.resource_locator,
            freeze.bindings.provider_resource,
        ),
        "identity_policy": (
            root / protocol.model_condition.identity_protocol_locator,
            freeze.bindings.identity_policy,
        ),
    }
    if protocol.consumed_sample_registry is not None:
        expected_bindings["consumed_sample_registry"] = (
            root / protocol.consumed_sample_registry.locator,
            freeze.bindings.consumed_sample_registry,
        )
    if protocol.integrity_gate is not None and protocol.authority_gate is not None:
        expected_bindings["integrity_gate"] = (
            root / protocol.integrity_gate.locator,
            freeze.bindings.integrity_gate,
        )
        expected_bindings["authority_gate"] = (
            root / protocol.authority_gate.locator,
            freeze.bindings.authority_gate,
        )
    for binding_name, (candidate_path, binding) in expected_bindings.items():
        source = _bounded_file(Path(candidate_path), _MAX_CONFIG_BYTES)
        expected_locator = _relative(source, root)
        if binding.locator != expected_locator or _sha256_file(source) != binding.file_sha256:
            raise ValueError(f"Segmentation freeze {binding_name} binding drifted")

    if (
        freeze.bindings.protocol.file_sha256 != _sha256_file(protocol_source)
        or freeze.bindings.sample.file_sha256 != protocol.sample.file_sha256
        or freeze.bindings.sample.sample_sha256 != protocol.sample.sample_sha256
        or freeze.bindings.segmentation_rubric != protocol.segmentation_rubric
        or freeze.bindings.adjudication_rubric != protocol.adjudication_rubric
        or freeze.bindings.provider_resource.file_sha256
        != protocol.model_condition.resource_file_sha256
        or freeze.bindings.identity_policy.file_sha256
        != protocol.model_condition.identity_protocol_file_sha256
        or freeze.bindings.consumed_sample_registry != protocol.consumed_sample_registry
        or freeze.bindings.integrity_gate != protocol.integrity_gate
        or freeze.bindings.authority_gate != protocol.authority_gate
    ):
        raise ValueError("Segmentation freeze and protocol content bindings differ")

    resource_payload = _yaml_mapping(root / protocol.model_condition.resource_locator)
    resource = ApiModelDefinition.model_validate(resource_payload.get("resource"))
    if (
        resource.resource_id != protocol.model_condition.resource_id
        or resource.provider_id != protocol.model_condition.provider_id
        or resource.model_id != protocol.model_condition.requested_model_id
        or not resource.rolling_alias
    ):
        raise ValueError("Segmentation provider resource differs from its model condition")
    identity = load_api_identity_protocol(root / protocol.model_condition.identity_protocol_locator)
    if identity.file_sha256 != protocol.model_condition.identity_protocol_file_sha256:
        raise ValueError("Segmentation identity-policy file hash drifted")
    identity_policy = identity.protocol.policy(protocol.model_condition.resource_id)
    if (
        identity_policy.identity_mode is not ApiIdentityMode.TEMPORAL_WINDOW_ONLY
        or identity_policy.maximum_formal_window_hours
        != protocol.model_condition.maximum_window_hours
        or identity_policy.allowed_returned_model_ids
        != protocol.model_condition.returned_model_allowlist
    ):
        raise ValueError("Segmentation identity policy differs from its model condition")

    sample_inspection = verify_taste_source_segmentation_sample_bindings(
        root / protocol.sample.locator,
        locator_root=root,
    )
    if (
        sample_inspection.file_sha256 != protocol.sample.file_sha256
        or sample_inspection.sample.sample_sha256 != protocol.sample.sample_sha256
        or sample_inspection.sample.item_count != protocol.sample.item_count
    ):
        raise ValueError("Segmentation protocol sample binding drifted")
    if protocol.schema_version == "1.5" and (
        sample_inspection.sample.schema_version != "1.2"
        or sample_inspection.sample.source_group_disjoint_from_exclusions is not True
        or sample_inspection.sample.maximum_items_per_source_group != 1
        or sample_inspection.sample.source_group_ids_exposed_to_provider is not False
        or protocol.sample.per_campaign_eligible_source_group_counts
        != sample_inspection.sample.per_campaign_eligible_source_group_counts
        or protocol.sample.per_campaign_sampling_fraction_micros
        != sample_inspection.sample.per_campaign_sampling_fraction_micros
        or protocol.sample.uncertainty_estimand
        != sample_inspection.sample.uncertainty_estimand
        or protocol.sample.prior_source_groups_excluded
        != sum(
            (sample_inspection.sample.per_campaign_excluded_source_group_counts or {}).values()
        )
    ):
        raise ValueError("Schema 1.5 protocol lacks a source-group-disjoint sample")
    if protocol.schema_version == "1.5":
        reserve = assess_taste_source_segmentation_validation_reserve(
            protocol,
            sample_inspection.sample,
        )
        if (
            protocol.scale_gate.new_source_groups_required_for_validation is True
            and not reserve.ready_for_provider_contact
        ):
            raise ValueError(
                "Segmentation calibration would consume its independent validation "
                f"source-group reserve: {', '.join(reserve.blocker_codes)}"
            )
        assert protocol.integrity_gate is not None
        assert protocol.authority_gate is not None
        integrity_gate = load_segmentation_post_audit_gate(
            root / protocol.integrity_gate.locator
        )
        authority_gate = load_segmentation_post_audit_gate(
            root / protocol.authority_gate.locator
        )
        if (
            integrity_gate.file_sha256 != protocol.integrity_gate.file_sha256
            or authority_gate.file_sha256 != protocol.authority_gate.file_sha256
            or integrity_gate.gate.role_id != "ai-d-content-integrity"
            or authority_gate.gate.role_id != "ai-e-protocol-authority"
        ):
            raise ValueError("Schema 1.5 post-audit gate semantics drifted")
    if protocol.consumed_sample_registry is not None:
        consumed_payload = _yaml_mapping(root / protocol.consumed_sample_registry.locator)
        consumed = consumed_payload.get("consumed_samples")
        if not isinstance(consumed, list) or any(not isinstance(item, dict) for item in consumed):
            raise ValueError("Segmentation consumed-sample registry is invalid")
        consumed_hashes = {item.get("sample_sha256") for item in consumed}
        if protocol.sample.sample_sha256 in consumed_hashes:
            raise ValueError("Segmentation protocol attempts to reuse a consumed sample")

    _verify_git_commit(root, freeze.git.commit)
    implementation_bindings = [
        freeze.implementation.segmentation_module,
        freeze.implementation.cli,
    ]
    if freeze.implementation.protocol_module is not None:
        implementation_bindings.append(freeze.implementation.protocol_module)
    if freeze.implementation.execution_module is not None:
        implementation_bindings.append(freeze.implementation.execution_module)
    for binding in (
        freeze.bindings.protocol,
        freeze.bindings.sample,
        freeze.bindings.segmentation_rubric,
        freeze.bindings.adjudication_rubric,
        freeze.bindings.provider_resource,
        freeze.bindings.identity_policy,
        *(
            (freeze.bindings.integrity_gate, freeze.bindings.authority_gate)
            if freeze.bindings.integrity_gate is not None
            and freeze.bindings.authority_gate is not None
            else ()
        ),
        *(
            (freeze.bindings.consumed_sample_registry,)
            if freeze.bindings.consumed_sample_registry is not None
            else ()
        ),
        *implementation_bindings,
    ):
        if _git_blob_sha256(root, freeze.git.commit, binding.locator) != binding.file_sha256:
            raise ValueError("Segmentation freeze implementation Git blob drifted")
    return TasteSourceSegmentationProtocolInspection(
        protocol_path=protocol_source,
        protocol_file_sha256=_sha256_file(protocol_source),
        freeze_receipt_path=freeze_source,
        freeze_receipt_file_sha256=_sha256_file(freeze_source),
        protocol=protocol,
        freeze_receipt=freeze,
        sample=sample_inspection.sample,
    )


def prepare_taste_source_segmentation_request_pack(
    *,
    pack_id: str,
    protocol_path: str | Path,
    freeze_receipt_path: str | Path,
    locator_root: str | Path,
    output_dir: str | Path,
    created_at: datetime,
) -> tuple[Path, TasteSourceSegmentationRequestPack]:
    """Persist every allowed model input byte without contacting the provider."""

    inspection = inspect_taste_source_segmentation_protocol(
        protocol_path=protocol_path,
        freeze_receipt_path=freeze_receipt_path,
        locator_root=locator_root,
    )
    root = Path(locator_root).resolve(strict=True)
    protocol = inspection.protocol
    sample = inspection.sample
    if created_at.utcoffset() is None:
        raise ValueError("Segmentation request-pack time must include a timezone")
    if getattr(protocol, "schema_version", "1.0") in {"1.3", "1.4", "1.5"} and (
        created_at < inspection.freeze_receipt.frozen_at
        or created_at > datetime.now().astimezone()
    ):
        raise ValueError("Segmentation request-pack time is outside its observable freeze window")
    selected_keys = {(item.campaign_id, item.review_item_id) for item in sample.items}
    campaign_tokens = {
        campaign_id: segmentation_campaign_token(pack_id, campaign_id)
        for campaign_id in sample.source_campaign_locators or {}
    }
    items_by_campaign: dict[str, list[TasteSourceSegmentationRequestItem]] = {}
    observed_keys: set[tuple[str, str]] = set()
    for campaign_id, locator in sorted((sample.source_campaign_locators or {}).items()):
        campaign_items = load_taste_source_review_items(
            root / locator,
            TasteSourceReviewRole.SCIENTIFIC,
        )
        selected_source_items = [
            item
            for item in campaign_items
            if isinstance(item, ScientificTasteSourceReviewItem)
            and (campaign_id, item.review_item_id) in selected_keys
        ]
        observed_keys.update((campaign_id, item.review_item_id) for item in selected_source_items)
        selected = []
        for item in selected_source_items:
            units = (
                unitize_taste_source_comment(item.review_comment)
                if getattr(protocol, "evidence_unit_selection", None) is not None
                else None
            )
            unit_hash = (
                taste_source_evidence_unit_table_sha256(item.review_comment)
                if units is not None
                else None
            )
            selected.append(
                TasteSourceSegmentationRequestItem(
                    campaign_token=campaign_tokens[campaign_id],
                    review_item_id=item.review_item_id,
                    reviewed_abstract=item.reviewed_abstract,
                    review_comment=item.review_comment,
                    evidence_units=units,
                    evidence_unit_table_sha256=unit_hash,
                )
            )
        items_by_campaign[campaign_id] = sorted(selected, key=lambda item: item.review_item_id)
    if observed_keys != selected_keys:
        raise ValueError("Segmentation request pack does not resolve its exact sample")

    shard_count = protocol.generation.segmenter_shards
    items_per_source_shard = protocol.generation.items_per_shard // len(items_by_campaign)
    if items_per_source_shard * len(
        items_by_campaign
    ) != protocol.generation.items_per_shard or any(
        len(items) != shard_count * items_per_source_shard for items in items_by_campaign.values()
    ):
        raise ValueError("Segmentation sample cannot satisfy the source-balanced shard plan")
    rubric_payload = _yaml_mapping(root / protocol.segmentation_rubric.locator)
    anchored = getattr(protocol, "evidence_unit_selection", None) is not None
    nested_anchor_contract = getattr(protocol, "schema_version", "1.0") == "1.5"
    reported_text_field = (
        None
        if anchored
        else (
            "reported_decision_text"
            if getattr(protocol, "span_reconstruction", None) is not None
            else "verbatim_decision_text"
        )
    )
    required_segment_fields = [
        *(
            ("trigger_range", "context_ranges")
            if nested_anchor_contract
            else ("start_unit_id", "end_unit_id")
        ),
        "primary_decision_family",
        "atomic_decision_statement",
        "rationale",
        "uncertainty",
    ] if anchored else [
        str(reported_text_field),
        "primary_decision_family",
        "atomic_decision_statement",
        "rationale",
        "uncertainty",
    ]
    segment_properties: dict[str, JsonValue] = {
        "primary_decision_family": {
            "enum": [
                "idea",
                "experiment",
                "evidence",
                "writing",
                "review",
                "visual",
                "cannot-assess",
            ]
        },
        "atomic_decision_statement": {"type": "string", "minLength": 1},
        "rationale": {"type": "string", "minLength": 1},
        "uncertainty": {"enum": ["low", "medium", "high"]},
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
                "minItems": protocol.generation.items_per_shard,
                "maxItems": protocol.generation.items_per_shard,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "campaign_token",
                        "review_item_id",
                        "segments",
                        *(["no_decision_rationale"] if nested_anchor_contract else []),
                        "residual_decision_bearing_text_possible",
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
                    },
                    **(
                        {
                            "allOf": [
                                {
                                    "if": {"properties": {"segments": {"maxItems": 0}}},
                                    "then": {
                                        "properties": {
                                            "no_decision_rationale": {"type": "string"}
                                        }
                                    },
                                    "else": {
                                        "properties": {
                                            "no_decision_rationale": {"type": "null"}
                                        }
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
        "item_rule": (
            "Return every assigned campaign_token and review_item_id exactly once. "
            + (
                (
                    "For every atomic decision, select a minimal trigger_range and zero or "
                    "more context_ranges from the supplied evidence_units. Trigger ranges "
                    "must be ordered and non-overlapping; context may be shared across "
                    "decisions. Return an empty segments list plus a no-decision rationale "
                    "when no actionable decision is present. "
                    if nested_anchor_contract
                    else "Select start_unit_id and end_unit_id from the supplied deterministic "
                    "evidence_units. "
                )
                + "Never return or reconstruct source text; the runner copies exact source "
                "slices from the selected anchors. "
                if anchored
                else
                "Return reported_decision_text as an exact locator candidate; the runner "
                "may repair only the frozen one-character typography map and will copy "
                "the final source-of-record span from review_comment. "
                if getattr(protocol, "span_reconstruction", None) is not None
                else "Copy each verbatim_decision_text exactly from review_comment. "
            )
            + "Emit one primary family per atomic decision."
        ),
    }
    packets: list[TasteSourceSegmentationRequestPacket] = []
    campaign_ids = sorted(items_by_campaign)
    for slot in ("segmenter-a", "segmenter-b"):
        for shard_index in range(shard_count):
            shard_items: list[TasteSourceSegmentationRequestItem] = []
            start = shard_index * items_per_source_shard
            end = start + items_per_source_shard
            for campaign_id in campaign_ids:
                shard_items.extend(items_by_campaign[campaign_id][start:end])
            packet_id = f"{pack_id}-{slot}-shard-{shard_index + 1:02d}"
            packets.append(
                TasteSourceSegmentationRequestPacket(
                    schema_version=(
                        "1.2" if nested_anchor_contract else "1.1" if anchored else "1.0"
                    ),
                    packet_id=packet_id,
                    project_id=protocol.project_id,
                    protocol_id=protocol.protocol_id,
                    sample_sha256=sample.sample_sha256,
                    sample_manifest_file_sha256=protocol.sample.file_sha256,
                    rubric_file_sha256=protocol.segmentation_rubric.file_sha256,
                    segmenter_slot=slot,
                    shard_index=shard_index + 1,
                    shard_count=shard_count,
                    requested_provider=protocol.model_condition.provider_id,
                    requested_model=protocol.model_condition.requested_model_id,
                    system_instruction=(
                        "Segment only the supplied review comments under the bound rubric. "
                        "Do not infer hidden source or outcome fields, use tools, browse, or "
                        "read another segmenter's output. "
                        + (
                            (
                                "Select a minimal trigger range plus only necessary context "
                                "ranges using supplied evidence-unit IDs; allow zero decisions "
                                "with a rationale. "
                                if nested_anchor_contract
                                else "Select only supplied evidence-unit IDs; "
                            )
                            + "Do not return a dedicated source-span transcription field. "
                            if anchored
                            else ""
                        )
                        + "Return one JSON object only."
                    ),
                    rubric=rubric_payload,
                    items=tuple(
                        sorted(
                            shard_items,
                            key=lambda item: (item.campaign_token, item.review_item_id),
                        )
                    ),
                    output_contract=output_contract,
                )
            )

    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        request_dir = staging / "requests"
        request_dir.mkdir()
        bindings: list[TasteSourceSegmentationRequestBinding] = []
        for packet in packets:
            packet_path = request_dir / f"{packet.packet_id}.json"
            _atomic_json(packet_path, packet.model_dump(mode="json", exclude_none=True))
            bindings.append(
                TasteSourceSegmentationRequestBinding(
                    locator=packet_path.relative_to(staging).as_posix(),
                    file_sha256=_sha256_file(packet_path),
                    packet_sha256=packet.packet_sha256,
                    segmenter_slot=packet.segmenter_slot,
                    shard_index=packet.shard_index,
                    item_count=len(packet.items),
                )
            )
        pack = TasteSourceSegmentationRequestPack(
            schema_version=(
                "1.2" if nested_anchor_contract else "1.1" if anchored else "1.0"
            ),
            pack_id=pack_id,
            project_id=protocol.project_id,
            created_at=created_at,
            protocol_file_sha256=inspection.protocol_file_sha256,
            freeze_receipt_file_sha256=inspection.freeze_receipt_file_sha256,
            sample_sha256=sample.sample_sha256,
            requests=tuple(bindings),
            unique_item_count=sample.item_count,
            request_count=len(bindings),
            input_field_names=(
                "campaign_token",
                "review_item_id",
                "reviewed_abstract",
                "review_comment",
                *(("evidence_units", "evidence_unit_table_sha256") if anchored else ()),
            ),
            forbidden_source_field_names=(
                "article_title",
                "author_response",
                "later_revision",
                "observed_recommendation",
                "publisher_subject",
                "source_identity",
            ),
        )
        _atomic_json(staging / "REQUEST_PACK.json", pack.model_dump(mode="json"))
        os.rename(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target, pack


def load_taste_source_segmentation_request_packet(
    path: str | Path,
) -> TasteSourceSegmentationRequestPacket:
    """Load one immutable packet and verify its semantic self-hash."""

    source = _bounded_file(Path(path), _MAX_CAMPAIGN_BYTES)
    payload = json.loads(source.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("Segmentation request packet must contain a mapping")
    recorded = payload.pop("packet_sha256", None)
    packet = TasteSourceSegmentationRequestPacket.model_validate(payload)
    if recorded != packet.packet_sha256:
        raise ValueError("Segmentation request packet hash mismatch")
    return packet


def load_taste_source_segmentation_request_pack(
    path: str | Path,
) -> TasteSourceSegmentationRequestPack:
    """Load a pack and verify every packet, binding, and dual-slot item copy."""

    source = _bounded_file(Path(path), _MAX_CAMPAIGN_BYTES)
    payload = json.loads(source.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("Segmentation request pack must contain a mapping")
    recorded = payload.pop("pack_sha256", None)
    pack = TasteSourceSegmentationRequestPack.model_validate(payload)
    if recorded != pack.pack_sha256:
        raise ValueError("Segmentation request-pack hash mismatch")
    pack_root = source.parent
    packets: dict[tuple[str, int], TasteSourceSegmentationRequestPacket] = {}
    for binding in pack.requests:
        locator = _safe_locator(binding.locator)
        packet_path = _bounded_file(pack_root / locator, _MAX_CAMPAIGN_BYTES)
        try:
            packet_path.relative_to(pack_root)
        except ValueError as error:  # pragma: no cover - defended by safe locator
            raise ValueError("Segmentation request packet escapes its pack") from error
        packet = load_taste_source_segmentation_request_packet(packet_path)
        if (
            _sha256_file(packet_path) != binding.file_sha256
            or packet.packet_sha256 != binding.packet_sha256
            or packet.segmenter_slot != binding.segmenter_slot
            or packet.shard_index != binding.shard_index
            or len(packet.items) != binding.item_count
            or packet.project_id != pack.project_id
            or packet.sample_sha256 != pack.sample_sha256
            or packet.schema_version != pack.schema_version
        ):
            raise ValueError("Segmentation request packet binding drifted")
        packets[(packet.segmenter_slot, packet.shard_index)] = packet
    shard_ids = sorted({shard for _, shard in packets})
    for shard_id in shard_ids:
        first = packets.get(("segmenter-a", shard_id))
        second = packets.get(("segmenter-b", shard_id))
        if first is None or second is None or first.items != second.items:
            raise ValueError("Segmentation dual slots do not bind identical shard inputs")
    unique_keys = {
        (item.campaign_token, item.review_item_id)
        for (slot, _), packet in packets.items()
        if slot == "segmenter-a"
        for item in packet.items
    }
    if len(unique_keys) != pack.unique_item_count:
        raise ValueError("Segmentation request pack unique item count drifted")
    return pack


def segmentation_campaign_token(pack_id: str, campaign_id: str) -> str:
    """Derive a stable packet-local token without serializing the source name."""

    digest = _canonical_sha256(
        {
            "domain": "scitaste-segmentation-campaign-token-v1",
            "pack_id": pack_id,
            "campaign_id": campaign_id,
        }
    )
    return f"source-{digest[:24]}"


def _verify_git_commit(root: Path, commit: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise ValueError("Segmentation freeze Git commit is unavailable")


def _git_blob_sha256(root: Path, commit: str, locator: str) -> str:
    _safe_locator(locator)
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{locator}"],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise ValueError("Segmentation freeze Git blob is unavailable")
    return hashlib.sha256(result.stdout).hexdigest()


def _yaml_mapping(path: Path) -> dict[str, JsonValue]:
    source = _bounded_file(path, _MAX_CONFIG_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Segmentation protocol input must contain a mapping")
    return payload


def _bounded_file(path: Path, maximum_bytes: int) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Segmentation protocol input must be a regular non-symlink file")
    if path.stat().st_size > maximum_bytes:
        raise ValueError("Segmentation protocol input exceeds its byte limit")
    return path.resolve(strict=True)


def _safe_locator(locator: str) -> PurePosixPath:
    candidate = PurePosixPath(locator)
    if (
        "\\" in locator
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Segmentation protocol locator is unsafe")
    return candidate


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("Segmentation protocol artifact is outside its root") from error


def _atomic_json(path: Path, payload: object) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
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
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = [
    "SegmentationProtocolAdjudicationInputFirewall",
    "SegmentationProtocolSpanReconstruction",
    "TasteSourceSegmentationFreezeReceipt",
    "TasteSourceSegmentationProspectiveProtocol",
    "TasteSourceSegmentationProtocolInspection",
    "TasteSourceSegmentationRequestItem",
    "TasteSourceSegmentationRequestPack",
    "TasteSourceSegmentationRequestPacket",
    "TasteSourceSegmentationValidationReserveAudit",
    "assess_taste_source_segmentation_validation_reserve",
    "inspect_taste_source_segmentation_protocol",
    "load_taste_source_segmentation_request_pack",
    "load_taste_source_segmentation_request_packet",
    "prepare_taste_source_segmentation_request_pack",
    "segmentation_campaign_token",
]
