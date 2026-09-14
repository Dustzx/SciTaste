"""Exact-span decomposition of compound source reviews into atomic decisions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.natural_taste_review import (
    ScientificTasteSourceReviewItem,
    TasteSourceReviewRole,
    load_taste_source_review_campaign,
    load_taste_source_review_items,
)
from scitaste.taste.intrinsic import TasteTask

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_EXACT_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 16 * 1_048_576
_MAX_ARTIFACT_BYTES = 64 * 1_048_576


class TasteSourceSegmentationSampleItem(BaseModel):
    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)


class TasteSourceSegmentationSampleManifest(BaseModel):
    """Exact sample binding; retrospective pilots remain non-confirmatory."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    sample_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    selection_timing: Literal["preregistered", "retrospective-pilot-binding"]
    selection_rationale: str = Field(min_length=1, max_length=4_000)
    sampling_algorithm: str = Field(min_length=1, max_length=500)
    random_seed: int | None = None
    selection_algorithm_version: Literal["sha256-ranked-balanced-v1"] | None = None
    source_campaign_locators: dict[str, str] | None = None
    source_campaign_file_sha256s: dict[str, str] | None = None
    source_campaign_sha256s: dict[str, str] | None = None
    source_scientific_items_sha256s: dict[str, str] | None = None
    excluded_sample_locators: dict[str, str] | None = None
    excluded_sample_file_sha256s: dict[str, str] | None = None
    excluded_sample_sha256s: dict[str, str] | None = None
    per_campaign_item_counts: dict[str, int] | None = None
    items: tuple[TasteSourceSegmentationSampleItem, ...] = Field(min_length=1)
    item_count: int = Field(gt=0)
    authority: dict[str, bool]

    @model_validator(mode="after")
    def sample_is_exact_and_honest(self) -> TasteSourceSegmentationSampleManifest:
        keys = [(item.campaign_id, item.review_item_id) for item in self.items]
        if keys != sorted(set(keys)) or self.item_count != len(keys):
            raise ValueError("Segmentation sample items must be sorted, unique, and counted")
        preregistered = self.selection_timing == "preregistered"
        if self.authority.get("preregistered") != preregistered:
            raise ValueError("Segmentation sample timing differs from its authority")
        if any(
            self.authority.get(key) is not False
            for key in (
                "confirmatory_calibration_authorized",
                "scaled_execution_authorized",
                "formal_evidence_eligible",
            )
        ):
            raise ValueError("Segmentation calibration sample overclaims authority")
        prospective_fields = (
            self.selection_algorithm_version,
            self.source_campaign_locators,
            self.source_campaign_file_sha256s,
            self.source_campaign_sha256s,
            self.source_scientific_items_sha256s,
            self.excluded_sample_locators,
            self.excluded_sample_file_sha256s,
            self.excluded_sample_sha256s,
            self.per_campaign_item_counts,
        )
        if self.schema_version == "1.0":
            if any(value is not None for value in prospective_fields):
                raise ValueError("Schema 1.0 cannot carry prospective selection receipts")
            return self
        if not preregistered or self.random_seed is None or any(
            value is None for value in prospective_fields
        ):
            raise ValueError("Schema 1.1 requires a complete preregistered selection receipt")
        source_maps = (
            self.source_campaign_locators,
            self.source_campaign_file_sha256s,
            self.source_campaign_sha256s,
            self.source_scientific_items_sha256s,
            self.per_campaign_item_counts,
        )
        assert all(value is not None for value in source_maps)
        campaign_ids = set(self.source_campaign_locators or {})
        if not campaign_ids or any(set(value or {}) != campaign_ids for value in source_maps):
            raise ValueError("Prospective sample source bindings differ")
        if set(item.campaign_id for item in self.items) != campaign_ids:
            raise ValueError("Prospective sample items differ from bound campaigns")
        observed_counts: dict[str, int] = {}
        for item in self.items:
            observed_counts[item.campaign_id] = observed_counts.get(item.campaign_id, 0) + 1
        if dict(sorted(observed_counts.items())) != self.per_campaign_item_counts:
            raise ValueError("Prospective sample campaign counts are inconsistent")
        exclusion_maps = (
            self.excluded_sample_locators,
            self.excluded_sample_file_sha256s,
            self.excluded_sample_sha256s,
        )
        assert all(value is not None for value in exclusion_maps)
        exclusion_ids = set(self.excluded_sample_locators or {})
        if not exclusion_ids or any(set(value or {}) != exclusion_ids for value in exclusion_maps):
            raise ValueError("Prospective sample exclusion bindings differ")
        bound_locators = (
            *self.source_campaign_locators.values(),
            *self.excluded_sample_locators.values(),
        )
        for locator in bound_locators:
            candidate = PurePosixPath(locator)
            if (
                "\\" in locator
                or candidate.is_absolute()
                or any(part in {"", ".", ".."} for part in candidate.parts)
            ):
                raise ValueError("Prospective sample binding locator is unsafe")
        return self

    @computed_field
    @property
    def sample_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"sample_sha256"})
        if self.schema_version == "1.0":
            for field in (
                "selection_algorithm_version",
                "source_campaign_locators",
                "source_campaign_file_sha256s",
                "source_campaign_sha256s",
                "source_scientific_items_sha256s",
                "excluded_sample_locators",
                "excluded_sample_file_sha256s",
                "excluded_sample_sha256s",
                "per_campaign_item_counts",
            ):
                payload.pop(field, None)
        return _canonical_sha256(payload)


class TasteSourceSegmentationSampleInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    sample: TasteSourceSegmentationSampleManifest


class TasteSourceDecisionSegment(BaseModel):
    """One exact source span proposed to express one primary decision."""

    model_config = _EXACT_CONFIG

    segment_id: str = Field(pattern=_ID)
    ordinal: int = Field(ge=1, le=128)
    start_char: int = Field(ge=0, le=2_000_000)
    end_char: int = Field(gt=0, le=2_000_000)
    verbatim_decision_text: str = Field(min_length=1, max_length=16_000)
    primary_decision_family: TasteTask | Literal["cannot-assess"]
    atomic_decision_statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    uncertainty: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def span_is_well_formed(self) -> TasteSourceDecisionSegment:
        if self.end_char <= self.start_char:
            raise ValueError("Taste source decision segment span is empty")
        if self.end_char - self.start_char != len(self.verbatim_decision_text):
            raise ValueError("Taste source decision segment length differs from its span")
        if self.primary_decision_family == "cannot-assess" and self.uncertainty != "high":
            raise ValueError("cannot-assess decision segments require high uncertainty")
        return self


class TasteSourceSegmentedItem(BaseModel):
    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    review_item_sha256: str = Field(pattern=_SHA256)
    review_comment_sha256: str = Field(pattern=_SHA256)
    segments: tuple[TasteSourceDecisionSegment, ...] = Field(min_length=1, max_length=128)
    multiple_segments_proposed: bool
    residual_decision_bearing_text_possible: bool

    @model_validator(mode="after")
    def segments_are_ordered_and_nonoverlapping(self) -> TasteSourceSegmentedItem:
        if tuple(segment.ordinal for segment in self.segments) != tuple(
            range(1, len(self.segments) + 1)
        ):
            raise ValueError("Taste source decision segment ordinals are not contiguous")
        if any(
            first.end_char > second.start_char
            for first, second in zip(self.segments, self.segments[1:], strict=False)
        ):
            raise ValueError("Taste source decision segments overlap or are out of order")
        if len({segment.segment_id for segment in self.segments}) != len(self.segments):
            raise ValueError("Taste source decision segment IDs must be unique")
        if self.multiple_segments_proposed != (len(self.segments) > 1):
            raise ValueError("Multiple-segment status differs from segment count")
        return self


class TasteSourceDecisionSegmentationRun(BaseModel):
    """One AI segmentation proposal; it cannot label or admit an episode."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    screener_id: str = Field(pattern=_ID)
    invocation_id: str = Field(pattern=_ID)
    runtime_surface: str = Field(min_length=1, max_length=200)
    model_identifier: str = Field(min_length=1, max_length=500)
    model_revision: str | None = Field(default=None, max_length=500)
    exact_model_identity_bound: bool
    rubric_locator: str = Field(min_length=1, max_length=2_000)
    rubric_file_sha256: str = Field(pattern=_SHA256)
    task_instruction_sha256: str = Field(pattern=_SHA256)
    runtime_identity_sha256: str | None = Field(default=None, pattern=_SHA256)
    reproducibility_ready: bool
    network_isolation_verified: Literal[False] = False
    completed_at: datetime
    source_agent_output_locator: str = Field(min_length=1, max_length=2_000)
    source_agent_output_file_sha256: str = Field(pattern=_SHA256)
    sample_manifest_locator: str = Field(min_length=1, max_length=2_000)
    sample_manifest_file_sha256: str = Field(pattern=_SHA256)
    sample_sha256: str = Field(pattern=_SHA256)
    sample_selection_timing: Literal["preregistered", "retrospective-pilot-binding"]
    campaign_locators: dict[str, str] = Field(min_length=1, max_length=32)
    campaign_file_sha256s: dict[str, str] = Field(min_length=1, max_length=32)
    campaign_sha256s: dict[str, str] = Field(min_length=1, max_length=32)
    items: tuple[TasteSourceSegmentedItem, ...] = Field(min_length=1, max_length=100_000)
    source_item_count: int = Field(gt=0, le=100_000)
    proposed_atomic_decision_count: int = Field(gt=0, le=1_000_000)
    multiple_segment_item_count: int = Field(ge=0, le=100_000)
    residual_risk_item_count: int = Field(ge=0, le=100_000)
    input_scope_attested: Literal[True] = True
    blinded_to_private_item_map: Literal[True] = True
    blinded_to_population_outcomes: Literal[True] = True
    blinded_to_other_segmenters: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    source_admission_authorized: Literal[False] = False
    taste_abstraction_authorized: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False

    @model_validator(mode="after")
    def run_is_bound_and_counted(self) -> TasteSourceDecisionSegmentationRun:
        if self.completed_at.utcoffset() is None:
            raise ValueError("Taste source segmentation time must include a timezone")
        expected_reproducibility = bool(
            self.exact_model_identity_bound and self.model_revision and self.runtime_identity_sha256
        )
        if self.reproducibility_ready != expected_reproducibility:
            raise ValueError("Taste source segmentation reproducibility status is inconsistent")
        if self.task_instruction_sha256 != self.rubric_file_sha256:
            raise ValueError("Segmentation task hash differs from the bound rubric")
        for locator in (self.rubric_locator, self.sample_manifest_locator):
            candidate = PurePosixPath(locator)
            if (
                "\\" in locator
                or candidate.is_absolute()
                or any(part in {"", ".", ".."} for part in candidate.parts)
            ):
                raise ValueError("Taste source segmentation binding locator is unsafe")
        campaign_ids = set(self.campaign_locators)
        if campaign_ids != set(self.campaign_file_sha256s) or campaign_ids != set(
            self.campaign_sha256s
        ):
            raise ValueError("Taste source segmentation campaign bindings differ")
        for locator in self.campaign_locators.values():
            candidate = PurePosixPath(locator)
            if (
                "\\" in locator
                or candidate.is_absolute()
                or any(part in {"", ".", ".."} for part in candidate.parts)
            ):
                raise ValueError("Taste source segmentation campaign locator is unsafe")
        keys = [(item.campaign_id, item.review_item_id) for item in self.items]
        if len(keys) != len(set(keys)) or keys != sorted(keys):
            raise ValueError("Taste source segmentation items must be sorted and unique")
        if any(item.campaign_id not in campaign_ids for item in self.items):
            raise ValueError("Taste source segmentation item names an unbound campaign")
        counts = (
            len(self.items),
            sum(len(item.segments) for item in self.items),
            sum(item.multiple_segments_proposed for item in self.items),
            sum(item.residual_decision_bearing_text_possible for item in self.items),
        )
        recorded = (
            self.source_item_count,
            self.proposed_atomic_decision_count,
            self.multiple_segment_item_count,
            self.residual_risk_item_count,
        )
        if counts != recorded:
            raise ValueError("Taste source segmentation aggregate counts are inconsistent")
        return self

    @computed_field
    @property
    def run_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"run_sha256"}))


class TasteSourceDecisionSegmentationInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    run: TasteSourceDecisionSegmentationRun


class TasteSourceSegmentationArtifactBinding(BaseModel):
    model_config = _CONFIG

    screener_id: str = Field(pattern=_ID)
    invocation_id: str = Field(pattern=_ID)
    locator: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)
    run_sha256: str = Field(pattern=_SHA256)
    source_agent_output_locator: str = Field(min_length=1, max_length=2_000)
    source_agent_output_file_sha256: str = Field(pattern=_SHA256)
    reproducibility_ready: bool
    network_isolation_verified: bool


class TasteSourceSegmentationAgreementItem(BaseModel):
    """Conservative exact-span comparison for one source-review item."""

    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    review_item_sha256: str = Field(pattern=_SHA256)
    segmenter_a_count: int = Field(gt=0, le=128)
    segmenter_b_count: int = Field(gt=0, le=128)
    exact_span_agreement_count: int = Field(ge=0, le=128)
    exact_span_family_agreement_count: int = Field(ge=0, le=128)
    overlap_span_agreement_count: int = Field(ge=0, le=128)
    overlap_span_family_agreement_count: int = Field(ge=0, le=128)
    family_disagreement_segment_ids: tuple[str, ...]
    segmenter_a_unmatched_segment_ids: tuple[str, ...]
    segmenter_b_unmatched_segment_ids: tuple[str, ...]
    residual_decision_bearing_text_possible: bool
    blocker_codes: tuple[str, ...]
    requires_adjudication: bool
    exact_span_route_passed: bool

    @model_validator(mode="after")
    def routing_is_conservative(self) -> TasteSourceSegmentationAgreementItem:
        for values in (
            self.family_disagreement_segment_ids,
            self.segmenter_a_unmatched_segment_ids,
            self.segmenter_b_unmatched_segment_ids,
            self.blocker_codes,
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError("Segmentation agreement lists must be sorted and unique")
        if self.exact_span_family_agreement_count > self.exact_span_agreement_count:
            raise ValueError("Family agreement exceeds exact-span agreement")
        if self.exact_span_agreement_count > self.overlap_span_agreement_count:
            raise ValueError("Exact-span agreement exceeds overlap agreement")
        if self.overlap_span_family_agreement_count > self.overlap_span_agreement_count:
            raise ValueError("Overlap family agreement exceeds overlap agreement")
        expected_blockers: set[str] = set()
        if self.segmenter_a_count != self.segmenter_b_count:
            expected_blockers.add("segment-count-disagreement")
        if self.segmenter_a_unmatched_segment_ids or self.segmenter_b_unmatched_segment_ids:
            expected_blockers.add("span-boundary-disagreement")
        if self.family_disagreement_segment_ids:
            expected_blockers.add("decision-family-disagreement")
        if self.residual_decision_bearing_text_possible:
            expected_blockers.add("residual-decision-risk")
        if self.blocker_codes != tuple(sorted(expected_blockers)):
            raise ValueError("Segmentation routing blockers are inconsistent")
        ready = not expected_blockers
        if self.exact_span_route_passed != ready:
            raise ValueError("Exact-span routing status differs from blockers")
        if self.requires_adjudication == ready:
            raise ValueError("Segmentation adjudication route differs from blockers")
        return self


class TasteSourceSegmentationAgreementReport(BaseModel):
    """Dual-agent calibration that routes all non-exact cases to adjudication."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    compiled_at: datetime
    artifacts: tuple[TasteSourceSegmentationArtifactBinding, ...] = Field(
        min_length=2,
        max_length=2,
    )
    sample_manifest_locator: str = Field(min_length=1, max_length=2_000)
    sample_manifest_file_sha256: str = Field(pattern=_SHA256)
    sample_sha256: str = Field(pattern=_SHA256)
    sample_selection_timing: Literal["preregistered", "retrospective-pilot-binding"]
    items: tuple[TasteSourceSegmentationAgreementItem, ...] = Field(min_length=1)
    source_item_count: int = Field(gt=0)
    segmenter_a_decision_count: int = Field(gt=0)
    segmenter_b_decision_count: int = Field(gt=0)
    exact_span_agreement_count: int = Field(ge=0)
    exact_span_family_agreement_count: int = Field(ge=0)
    exact_span_f1_micros: int = Field(ge=0, le=1_000_000)
    overlap_iou_threshold_micros: int = Field(gt=0, le=1_000_000)
    overlap_span_agreement_count: int = Field(ge=0)
    overlap_span_family_agreement_count: int = Field(ge=0)
    overlap_span_f1_micros: int = Field(ge=0, le=1_000_000)
    overlap_matched_family_agreement_micros: int = Field(ge=0, le=1_000_000)
    exact_span_route_item_count: int = Field(ge=0)
    adjudication_item_count: int = Field(ge=0)
    blocker_item_counts: dict[str, int]
    all_items_exactly_agreed: bool
    distinct_agent_artifacts_verified: bool
    cross_output_blinding_attested: bool
    segmenter_reproducibility_ready: bool
    network_isolation_verified: bool
    scaled_execution_blocker_codes: tuple[str, ...]
    scaled_execution_authorized: bool
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    source_admission_authorized: Literal[False] = False
    taste_abstraction_authorized: Literal[False] = False
    adjudication_completed: Literal[False] = False

    @model_validator(mode="after")
    def report_is_counted(self) -> TasteSourceSegmentationAgreementReport:
        if self.compiled_at.utcoffset() is None:
            raise ValueError("Segmentation agreement time must include a timezone")
        if (
            len({item.screener_id for item in self.artifacts}) != 2
            or len({item.invocation_id for item in self.artifacts}) != 2
        ):
            raise ValueError("Segmentation comparison requires distinct agent invocations")
        if (
            len({item.source_agent_output_locator for item in self.artifacts}) != 2
            or len({item.source_agent_output_file_sha256 for item in self.artifacts}) != 2
        ):
            raise ValueError("Segmentation comparison requires distinct raw agent artifacts")
        if not self.distinct_agent_artifacts_verified:
            raise ValueError("Segmentation comparison artifact checks were not recorded")
        if not self.cross_output_blinding_attested:
            raise ValueError("Segmentation comparison lacks cross-output blinding attestation")
        keys = [(item.campaign_id, item.review_item_id) for item in self.items]
        if keys != sorted(set(keys)):
            raise ValueError("Segmentation agreement items must be sorted and unique")
        expected_counts = (
            len(self.items),
            sum(item.segmenter_a_count for item in self.items),
            sum(item.segmenter_b_count for item in self.items),
            sum(item.exact_span_agreement_count for item in self.items),
            sum(item.exact_span_family_agreement_count for item in self.items),
            sum(item.overlap_span_agreement_count for item in self.items),
            sum(item.overlap_span_family_agreement_count for item in self.items),
            sum(item.exact_span_route_passed for item in self.items),
            sum(item.requires_adjudication for item in self.items),
        )
        recorded_counts = (
            self.source_item_count,
            self.segmenter_a_decision_count,
            self.segmenter_b_decision_count,
            self.exact_span_agreement_count,
            self.exact_span_family_agreement_count,
            self.overlap_span_agreement_count,
            self.overlap_span_family_agreement_count,
            self.exact_span_route_item_count,
            self.adjudication_item_count,
        )
        if expected_counts != recorded_counts:
            raise ValueError("Segmentation agreement aggregate counts are inconsistent")
        blocker_counts: dict[str, int] = {}
        for item in self.items:
            for blocker in item.blocker_codes:
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        if self.blocker_item_counts != dict(sorted(blocker_counts.items())):
            raise ValueError("Segmentation agreement blocker counts are inconsistent")
        if self.all_items_exactly_agreed != (self.adjudication_item_count == 0):
            raise ValueError("Segmentation agreement readiness is inconsistent")
        expected_exact_f1 = _f1_micros(
            self.exact_span_agreement_count,
            self.segmenter_a_decision_count,
            self.segmenter_b_decision_count,
        )
        expected_overlap_f1 = _f1_micros(
            self.overlap_span_agreement_count,
            self.segmenter_a_decision_count,
            self.segmenter_b_decision_count,
        )
        if (self.exact_span_f1_micros, self.overlap_span_f1_micros) != (
            expected_exact_f1,
            expected_overlap_f1,
        ):
            raise ValueError("Segmentation agreement F1 values are inconsistent")
        expected_family_agreement = (self.overlap_span_family_agreement_count * 1_000_000) // max(
            1, self.overlap_span_agreement_count
        )
        if self.overlap_matched_family_agreement_micros != expected_family_agreement:
            raise ValueError("Segmentation overlap-family agreement is inconsistent")
        if self.segmenter_reproducibility_ready != all(
            artifact.reproducibility_ready for artifact in self.artifacts
        ):
            raise ValueError("Segmentation reproducibility summary is inconsistent")
        if self.network_isolation_verified != all(
            artifact.network_isolation_verified for artifact in self.artifacts
        ):
            raise ValueError("Segmentation network-isolation summary is inconsistent")
        expected_scale_blockers: set[str] = set()
        if self.sample_selection_timing != "preregistered":
            expected_scale_blockers.add("calibration-sample-not-preregistered")
        if not self.segmenter_reproducibility_ready:
            expected_scale_blockers.add("segmenter-model-runtime-unbound")
        if not self.network_isolation_verified:
            expected_scale_blockers.add("outcome-blind-network-isolation-unverified")
        if self.overlap_span_f1_micros < 800_000:
            expected_scale_blockers.add("overlap-span-agreement-below-calibration-threshold")
        if self.overlap_matched_family_agreement_micros < 800_000:
            expected_scale_blockers.add("overlap-family-agreement-below-calibration-threshold")
        if self.scaled_execution_blocker_codes != tuple(sorted(expected_scale_blockers)):
            raise ValueError("Segmentation scale blockers are inconsistent")
        if self.scaled_execution_authorized != (not expected_scale_blockers):
            raise ValueError("Segmentation scale authorization differs from blockers")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


class TasteSourceSegmentationAgreementInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: TasteSourceSegmentationAgreementReport


class TasteSourceSegmentationResolutionItem(BaseModel):
    """Final internal AI resolution for one dual-segmented source item."""

    model_config = _CONFIG

    campaign_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    review_item_sha256: str = Field(pattern=_SHA256)
    resolution_kind: Literal["exact-dual-agent-agreement", "ai-adjudicated"]
    source_blocker_codes: tuple[str, ...]
    segments: tuple[TasteSourceDecisionSegment, ...] = Field(min_length=1, max_length=128)
    residual_decision_bearing_text_possible: bool
    resolution_rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def resolution_is_ordered(self) -> TasteSourceSegmentationResolutionItem:
        if self.source_blocker_codes != tuple(sorted(set(self.source_blocker_codes))):
            raise ValueError("Segmentation resolution blockers must be sorted and unique")
        if tuple(segment.ordinal for segment in self.segments) != tuple(
            range(1, len(self.segments) + 1)
        ):
            raise ValueError("Segmentation resolution ordinals are not contiguous")
        if any(
            first.end_char > second.start_char
            for first, second in zip(self.segments, self.segments[1:], strict=False)
        ):
            raise ValueError("Segmentation resolution spans overlap or are out of order")
        if self.resolution_kind == "exact-dual-agent-agreement" and self.source_blocker_codes:
            raise ValueError("Exact segmentation agreement cannot retain source blockers")
        if self.resolution_kind == "ai-adjudicated" and not self.source_blocker_codes:
            raise ValueError("AI adjudication requires a recorded source blocker")
        return self


class TasteSourceSegmentationResolutionRun(BaseModel):
    """Agent-adjudicated atomic units for internal screening, never formal labels."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    adjudicator_id: str = Field(pattern=_ID)
    invocation_id: str = Field(pattern=_ID)
    runtime_surface: str = Field(min_length=1, max_length=200)
    model_identifier: str = Field(min_length=1, max_length=500)
    model_revision: str | None = Field(default=None, max_length=500)
    exact_model_identity_bound: bool
    rubric_locator: str = Field(min_length=1, max_length=2_000)
    rubric_file_sha256: str = Field(pattern=_SHA256)
    task_instruction_sha256: str = Field(pattern=_SHA256)
    runtime_identity_sha256: str | None = Field(default=None, pattern=_SHA256)
    reproducibility_ready: bool
    network_isolation_verified: Literal[False] = False
    completed_at: datetime
    source_agent_output_locator: str = Field(min_length=1, max_length=2_000)
    source_agent_output_file_sha256: str = Field(pattern=_SHA256)
    agreement_locator: str = Field(min_length=1, max_length=2_000)
    agreement_file_sha256: str = Field(pattern=_SHA256)
    agreement_report_sha256: str = Field(pattern=_SHA256)
    source_segmentation_artifacts: tuple[TasteSourceSegmentationArtifactBinding, ...] = Field(
        min_length=2,
        max_length=2,
    )
    items: tuple[TasteSourceSegmentationResolutionItem, ...] = Field(min_length=1)
    source_item_count: int = Field(gt=0)
    final_atomic_decision_count: int = Field(gt=0)
    exact_agreement_item_count: int = Field(ge=0)
    ai_adjudicated_item_count: int = Field(ge=0)
    residual_risk_item_count: int = Field(ge=0)
    internal_pilot_resolution_complete: bool
    chain_reproducibility_ready: bool
    internal_screening_blocker_codes: tuple[str, ...]
    internal_ai_screening_ready: bool
    diagnostic_followup_allowed: Literal[True] = True
    segmenter_outputs_read: Literal[True] = True
    blinded_to_private_item_map: Literal[True] = True
    blinded_to_population_outcomes: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    formal_evidence_eligible: Literal[False] = False
    benchmark_admission_authorized: Literal[False] = False
    source_admission_authorized: Literal[False] = False
    taste_abstraction_authorized: Literal[False] = False

    @model_validator(mode="after")
    def resolution_is_bound_and_counted(self) -> TasteSourceSegmentationResolutionRun:
        if self.completed_at.utcoffset() is None:
            raise ValueError("Segmentation resolution time must include a timezone")
        expected_reproducibility = bool(
            self.exact_model_identity_bound and self.model_revision and self.runtime_identity_sha256
        )
        if self.reproducibility_ready != expected_reproducibility:
            raise ValueError("Segmentation resolution reproducibility status is inconsistent")
        if self.task_instruction_sha256 != self.rubric_file_sha256:
            raise ValueError("Segmentation resolution task hash differs from its rubric")
        if self.adjudicator_id in {
            artifact.screener_id for artifact in self.source_segmentation_artifacts
        } or self.invocation_id in {
            artifact.invocation_id for artifact in self.source_segmentation_artifacts
        }:
            raise ValueError("Segmentation adjudicator must be distinct from both segmenters")
        if self.source_agent_output_file_sha256 in {
            artifact.source_agent_output_file_sha256
            for artifact in self.source_segmentation_artifacts
        }:
            raise ValueError("Segmentation adjudicator raw artifact is not distinct")
        keys = [(item.campaign_id, item.review_item_id) for item in self.items]
        if keys != sorted(set(keys)):
            raise ValueError("Segmentation resolution items must be sorted and unique")
        expected = (
            len(self.items),
            sum(len(item.segments) for item in self.items),
            sum(item.resolution_kind == "exact-dual-agent-agreement" for item in self.items),
            sum(item.resolution_kind == "ai-adjudicated" for item in self.items),
            sum(item.residual_decision_bearing_text_possible for item in self.items),
        )
        recorded = (
            self.source_item_count,
            self.final_atomic_decision_count,
            self.exact_agreement_item_count,
            self.ai_adjudicated_item_count,
            self.residual_risk_item_count,
        )
        if expected != recorded:
            raise ValueError("Segmentation resolution aggregate counts are inconsistent")
        pilot_complete = self.residual_risk_item_count == 0
        if self.internal_pilot_resolution_complete != pilot_complete:
            raise ValueError("Segmentation pilot completion differs from residual risk")
        chain_ready = self.reproducibility_ready and all(
            artifact.reproducibility_ready for artifact in self.source_segmentation_artifacts
        )
        if self.chain_reproducibility_ready != chain_ready:
            raise ValueError("Segmentation resolution chain reproducibility is inconsistent")
        expected_blockers: set[str] = set()
        if not pilot_complete:
            expected_blockers.add("residual-decision-risk")
        if not all(
            artifact.reproducibility_ready for artifact in self.source_segmentation_artifacts
        ):
            expected_blockers.add("segmenter-model-runtime-unbound")
        if not self.reproducibility_ready:
            expected_blockers.add("adjudicator-model-runtime-unbound")
        if not self.network_isolation_verified or not all(
            artifact.network_isolation_verified for artifact in self.source_segmentation_artifacts
        ):
            expected_blockers.add("outcome-blind-network-isolation-unverified")
        if self.internal_screening_blocker_codes != tuple(sorted(expected_blockers)):
            raise ValueError("Segmentation resolution screening blockers are inconsistent")
        if self.internal_ai_screening_ready != (not expected_blockers):
            raise ValueError("Segmentation resolution readiness differs from its blockers")
        return self

    @computed_field
    @property
    def run_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"run_sha256"}))


class TasteSourceSegmentationResolutionInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    run: TasteSourceSegmentationResolutionRun


def load_taste_source_segmentation_sample_manifest(
    path: str | Path,
) -> TasteSourceSegmentationSampleInspection:
    source = _bounded_file(Path(path), _MAX_INPUT_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Taste source segmentation sample must contain a mapping")
    return TasteSourceSegmentationSampleInspection(
        path=source,
        file_sha256=_sha256_file(source),
        sample=TasteSourceSegmentationSampleManifest.model_validate(payload),
    )


def plan_taste_source_segmentation_sample(
    *,
    sample_id: str,
    campaign_paths: tuple[str | Path, ...],
    excluded_sample_paths: tuple[str | Path, ...],
    per_campaign_item_count: int,
    random_seed: int,
    locator_root: str | Path,
) -> TasteSourceSegmentationSampleManifest:
    """Freeze an unseen balanced sample before any segmentation output exists."""

    if not campaign_paths or not excluded_sample_paths:
        raise ValueError("Prospective segmentation requires campaigns and exclusion samples")
    if per_campaign_item_count < 1 or per_campaign_item_count > 10_000:
        raise ValueError("Prospective per-campaign sample count is outside its bound")
    root = Path(locator_root).resolve(strict=True)
    exclusions = tuple(
        load_taste_source_segmentation_sample_manifest(path)
        for path in excluded_sample_paths
    )
    excluded_keys = {
        (item.campaign_id, item.review_item_id)
        for inspection in exclusions
        for item in inspection.sample.items
    }
    excluded_ids = [inspection.sample.sample_id for inspection in exclusions]
    if len(excluded_ids) != len(set(excluded_ids)):
        raise ValueError("Prospective segmentation exclusion sample IDs must be distinct")

    source_campaign_locators: dict[str, str] = {}
    source_campaign_file_sha256s: dict[str, str] = {}
    source_campaign_sha256s: dict[str, str] = {}
    source_scientific_items_sha256s: dict[str, str] = {}
    project_ids: set[str] = set()
    selected: list[TasteSourceSegmentationSampleItem] = []
    per_campaign_counts: dict[str, int] = {}
    for campaign_path in campaign_paths:
        path = _bounded_file(Path(campaign_path), _MAX_ARTIFACT_BYTES)
        campaign = load_taste_source_review_campaign(path)
        if campaign.campaign_id in source_campaign_locators:
            raise ValueError("Prospective segmentation campaign IDs must be distinct")
        loaded = load_taste_source_review_items(path, TasteSourceReviewRole.SCIENTIFIC)
        scientific_items = tuple(
            item for item in loaded if isinstance(item, ScientificTasteSourceReviewItem)
        )
        available = tuple(
            item
            for item in scientific_items
            if (campaign.campaign_id, item.review_item_id) not in excluded_keys
        )
        if len(available) < per_campaign_item_count:
            raise ValueError("Prospective segmentation campaign has too few unseen items")
        ranked = sorted(
            available,
            key=lambda item: (
                _canonical_sha256(
                    {
                        "algorithm": "sha256-ranked-balanced-v1",
                        "random_seed": random_seed,
                        "campaign_id": campaign.campaign_id,
                        "campaign_sha256": campaign.campaign_sha256,
                        "review_item_id": item.review_item_id,
                        "review_item_sha256": _canonical_sha256(item.model_dump(mode="json")),
                    }
                ),
                item.review_item_id,
            ),
        )
        selected.extend(
            TasteSourceSegmentationSampleItem(
                campaign_id=campaign.campaign_id,
                review_item_id=item.review_item_id,
            )
            for item in ranked[:per_campaign_item_count]
        )
        source_campaign_locators[campaign.campaign_id] = _relative(path, root)
        source_campaign_file_sha256s[campaign.campaign_id] = _sha256_file(path)
        source_campaign_sha256s[campaign.campaign_id] = campaign.campaign_sha256
        source_scientific_items_sha256s[campaign.campaign_id] = campaign.scientific_items.sha256
        per_campaign_counts[campaign.campaign_id] = per_campaign_item_count
        project_ids.add(campaign.project_id)
    if len(project_ids) != 1:
        raise ValueError("Prospective segmentation campaigns target different projects")

    return TasteSourceSegmentationSampleManifest(
        schema_version="1.1",
        sample_id=sample_id,
        project_id=project_ids.pop(),
        selection_timing="preregistered",
        selection_rationale=(
            "Freeze an outcome-blind, source-balanced unseen calibration sample before "
            "either segmenter receives item text; all earlier calibration items are excluded."
        ),
        sampling_algorithm=(
            "sha256-ranked-balanced-v1: rank each unseen item by the canonical SHA-256 of "
            "algorithm, seed, campaign identity, campaign hash, item ID, and item hash; "
            "take the lowest ranks independently per campaign."
        ),
        random_seed=random_seed,
        selection_algorithm_version="sha256-ranked-balanced-v1",
        source_campaign_locators=dict(sorted(source_campaign_locators.items())),
        source_campaign_file_sha256s=dict(sorted(source_campaign_file_sha256s.items())),
        source_campaign_sha256s=dict(sorted(source_campaign_sha256s.items())),
        source_scientific_items_sha256s=dict(
            sorted(source_scientific_items_sha256s.items())
        ),
        excluded_sample_locators={
            inspection.sample.sample_id: _relative(inspection.path, root)
            for inspection in sorted(exclusions, key=lambda value: value.sample.sample_id)
        },
        excluded_sample_file_sha256s={
            inspection.sample.sample_id: inspection.file_sha256
            for inspection in sorted(exclusions, key=lambda value: value.sample.sample_id)
        },
        excluded_sample_sha256s={
            inspection.sample.sample_id: inspection.sample.sample_sha256
            for inspection in sorted(exclusions, key=lambda value: value.sample.sample_id)
        },
        per_campaign_item_counts=dict(sorted(per_campaign_counts.items())),
        items=tuple(sorted(selected, key=lambda item: (item.campaign_id, item.review_item_id))),
        item_count=len(selected),
        authority={
            "preregistered": True,
            "confirmatory_calibration_authorized": False,
            "scaled_execution_authorized": False,
            "formal_evidence_eligible": False,
        },
    )


def verify_taste_source_segmentation_sample_bindings(
    path: str | Path,
    *,
    locator_root: str | Path,
) -> TasteSourceSegmentationSampleInspection:
    """Replay every schema-1.1 source, exclusion, and deterministic rank binding."""

    inspection = load_taste_source_segmentation_sample_manifest(path)
    sample = inspection.sample
    if sample.schema_version != "1.1":
        raise ValueError("Only schema-1.1 prospective samples have replayable bindings")
    root = Path(locator_root).resolve(strict=True)
    source_locators = sample.source_campaign_locators or {}
    source_file_sha256s = sample.source_campaign_file_sha256s or {}
    source_sha256s = sample.source_campaign_sha256s or {}
    scientific_sha256s = sample.source_scientific_items_sha256s or {}
    source_paths: list[Path] = []
    for campaign_id, locator in sorted(source_locators.items()):
        campaign_path = _bounded_file(root / locator, _MAX_ARTIFACT_BYTES)
        if _relative(campaign_path, root) != locator:
            raise ValueError("Prospective sample campaign locator drifted")
        if _sha256_file(campaign_path) != source_file_sha256s[campaign_id]:
            raise ValueError("Prospective sample campaign file hash drifted")
        campaign = load_taste_source_review_campaign(campaign_path)
        if (
            campaign.campaign_id != campaign_id
            or campaign.campaign_sha256 != source_sha256s[campaign_id]
            or campaign.scientific_items.sha256 != scientific_sha256s[campaign_id]
        ):
            raise ValueError("Prospective sample campaign semantic binding drifted")
        scientific_path = _bounded_file(
            campaign_path.parent / campaign.scientific_items.locator,
            _MAX_ARTIFACT_BYTES,
        )
        if _sha256_file(scientific_path) != scientific_sha256s[campaign_id]:
            raise ValueError("Prospective sample scientific-item file hash drifted")
        source_paths.append(campaign_path)

    exclusion_locators = sample.excluded_sample_locators or {}
    exclusion_file_sha256s = sample.excluded_sample_file_sha256s or {}
    exclusion_sha256s = sample.excluded_sample_sha256s or {}
    exclusion_paths: list[Path] = []
    excluded_keys: set[tuple[str, str]] = set()
    for sample_id, locator in sorted(exclusion_locators.items()):
        exclusion_path = _bounded_file(root / locator, _MAX_INPUT_BYTES)
        if _relative(exclusion_path, root) != locator:
            raise ValueError("Prospective exclusion sample locator drifted")
        excluded = load_taste_source_segmentation_sample_manifest(exclusion_path)
        if (
            excluded.sample.sample_id != sample_id
            or excluded.file_sha256 != exclusion_file_sha256s[sample_id]
            or excluded.sample.sample_sha256 != exclusion_sha256s[sample_id]
        ):
            raise ValueError("Prospective exclusion sample binding drifted")
        excluded_keys.update(
            (item.campaign_id, item.review_item_id) for item in excluded.sample.items
        )
        exclusion_paths.append(exclusion_path)
    selected_keys = {(item.campaign_id, item.review_item_id) for item in sample.items}
    if selected_keys & excluded_keys:
        raise ValueError("Prospective sample overlaps an excluded calibration sample")

    counts = set((sample.per_campaign_item_counts or {}).values())
    if len(counts) != 1:
        raise ValueError("Balanced prospective replay requires one per-campaign count")
    replayed = plan_taste_source_segmentation_sample(
        sample_id=sample.sample_id,
        campaign_paths=tuple(source_paths),
        excluded_sample_paths=tuple(exclusion_paths),
        per_campaign_item_count=counts.pop(),
        random_seed=sample.random_seed if sample.random_seed is not None else -1,
        locator_root=root,
    )
    if replayed.sample_sha256 != sample.sample_sha256:
        raise ValueError("Prospective segmentation sample does not replay exactly")
    return inspection


def save_taste_source_segmentation_sample_manifest(
    sample: TasteSourceSegmentationSampleManifest,
    path: str | Path,
) -> Path:
    """Write a new immutable YAML sample manifest atomically."""

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
                sample.model_dump(
                    mode="json",
                    exclude={"sample_sha256"},
                    exclude_none=True,
                ),
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


def normalize_taste_source_decision_segmentation(
    *,
    raw_segmentation_path: str | Path,
    campaign_paths: tuple[str | Path, ...],
    campaign_aliases: dict[str, str],
    run_id: str,
    screener_id: str,
    invocation_id: str,
    runtime_surface: str,
    model_identifier: str,
    model_revision: str | None,
    exact_model_identity_bound: bool,
    rubric_path: str | Path,
    sample_manifest_path: str | Path,
    runtime_identity_sha256: str | None,
    completed_at: datetime,
    locator_root: str | Path,
) -> TasteSourceDecisionSegmentationRun:
    """Bind model-proposed verbatim spans to immutable scientific review items."""

    root = Path(locator_root).resolve(strict=True)
    raw_path = _bounded_file(Path(raw_segmentation_path), _MAX_INPUT_BYTES)
    rubric = _bounded_file(Path(rubric_path), _MAX_INPUT_BYTES)
    sample_inspection = load_taste_source_segmentation_sample_manifest(sample_manifest_path)
    if sample_inspection.sample.schema_version == "1.1":
        sample_inspection = verify_taste_source_segmentation_sample_bindings(
            sample_manifest_path,
            locator_root=root,
        )
    sample = sample_inspection.sample
    rubric_file_sha256 = _sha256_file(rubric)
    raw = json.loads(raw_path.read_bytes())
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ValueError("Taste source segmentation must contain an items list")
    boundary = raw.get("input_boundary")
    if not isinstance(boundary, dict) or not all(
        boundary.get(key) is False
        for key in (
            "other_segmenter_outputs_read",
            "private_item_map_read",
            "population_outcomes_read",
        )
    ):
        raise ValueError("Taste source segmentation lacks a checkable blindness attestation")
    if (
        raw.get("rubric_read") is not True
        or raw.get("sample_manifest_read") is not True
        or raw.get("rubric_file_sha256") != rubric_file_sha256
        or raw.get("sample_sha256") != sample.sample_sha256
    ):
        raise ValueError("Taste source segmentation lacks exact rubric/sample attestation")

    campaigns: dict[str, tuple[Path, object, dict[str, ScientificTasteSourceReviewItem]]] = {}
    projects: set[str] = set()
    for campaign_path in campaign_paths:
        path = _bounded_file(Path(campaign_path), _MAX_ARTIFACT_BYTES)
        campaign = load_taste_source_review_campaign(path)
        loaded = load_taste_source_review_items(path, TasteSourceReviewRole.SCIENTIFIC)
        scientific_items = {
            item.review_item_id: item
            for item in loaded
            if isinstance(item, ScientificTasteSourceReviewItem)
        }
        campaigns[campaign.campaign_id] = (path, campaign, scientific_items)
        projects.add(campaign.project_id)
    if sample.schema_version == "1.1":
        expected_campaigns = set(sample.source_campaign_locators or {})
        if set(campaigns) != expected_campaigns:
            raise ValueError("Segmentation campaigns differ from the prospective sample")
        for campaign_id, (path, campaign, _) in campaigns.items():
            if (
                _relative(path, root) != (sample.source_campaign_locators or {})[campaign_id]
                or _sha256_file(path)
                != (sample.source_campaign_file_sha256s or {})[campaign_id]
                or campaign.campaign_sha256
                != (sample.source_campaign_sha256s or {})[campaign_id]
            ):
                raise ValueError("Segmentation campaign differs from the prospective binding")
    if len(projects) != 1:
        raise ValueError("Taste source segmentation campaigns target different projects")
    if sample.project_id != next(iter(projects)):
        raise ValueError("Taste source segmentation sample targets a different project")
    aliases = {campaign_id: campaign_id for campaign_id in campaigns}
    aliases.update(campaign_aliases)

    items: list[TasteSourceSegmentedItem] = []
    for raw_item in raw["items"]:
        if not isinstance(raw_item, dict) or not isinstance(raw_item.get("segments"), list):
            raise ValueError("Taste source segmentation item is invalid")
        raw_campaign_id = raw_item.get("campaign_id", raw_item.get("campaign"))
        if not isinstance(raw_campaign_id, str) or raw_campaign_id not in aliases:
            raise ValueError("Taste source segmentation names an unknown campaign")
        campaign_id = aliases[raw_campaign_id]
        if campaign_id not in campaigns:
            raise ValueError("Taste source segmentation alias targets an unavailable campaign")
        review_item_id = raw_item.get("review_item_id")
        source = campaigns[campaign_id][2].get(review_item_id)
        if source is None:
            raise ValueError("Taste source segmentation item is outside its campaign")
        segments = list(
            _normalize_raw_segments(
                raw_segments=raw_item["segments"],
                campaign_id=campaign_id,
                review_item_id=review_item_id,
                review_comment=source.review_comment,
            )
        )
        items.append(
            TasteSourceSegmentedItem(
                campaign_id=campaign_id,
                review_item_id=source.review_item_id,
                review_item_sha256=_canonical_sha256(source.model_dump(mode="json")),
                review_comment_sha256=hashlib.sha256(source.review_comment.encode()).hexdigest(),
                segments=tuple(segments),
                multiple_segments_proposed=len(segments) > 1,
                residual_decision_bearing_text_possible=raw_item.get(
                    "residual_decision_bearing_text_possible"
                ),
            )
        )

    campaign_locators: dict[str, str] = {}
    campaign_file_sha256s: dict[str, str] = {}
    campaign_sha256s: dict[str, str] = {}
    for campaign_id, (path, untyped_campaign, _) in sorted(campaigns.items()):
        campaign = load_taste_source_review_campaign(path)
        assert campaign == untyped_campaign
        campaign_locators[campaign_id] = _relative(path, root)
        campaign_file_sha256s[campaign_id] = _sha256_file(path)
        campaign_sha256s[campaign_id] = campaign.campaign_sha256
    ordered_items = tuple(sorted(items, key=lambda item: (item.campaign_id, item.review_item_id)))
    if {(item.campaign_id, item.review_item_id) for item in ordered_items} != {
        (item.campaign_id, item.review_item_id) for item in sample.items
    }:
        raise ValueError("Taste source segmentation does not cover its exact sample manifest")
    return TasteSourceDecisionSegmentationRun(
        run_id=run_id,
        project_id=projects.pop(),
        screener_id=screener_id,
        invocation_id=invocation_id,
        runtime_surface=runtime_surface,
        model_identifier=model_identifier,
        model_revision=model_revision,
        exact_model_identity_bound=exact_model_identity_bound,
        rubric_locator=_relative(rubric, root),
        rubric_file_sha256=rubric_file_sha256,
        task_instruction_sha256=rubric_file_sha256,
        runtime_identity_sha256=runtime_identity_sha256,
        reproducibility_ready=bool(
            exact_model_identity_bound and model_revision and runtime_identity_sha256
        ),
        completed_at=completed_at,
        source_agent_output_locator=_relative(raw_path, root),
        source_agent_output_file_sha256=_sha256_file(raw_path),
        sample_manifest_locator=_relative(sample_inspection.path, root),
        sample_manifest_file_sha256=sample_inspection.file_sha256,
        sample_sha256=sample.sample_sha256,
        sample_selection_timing=sample.selection_timing,
        campaign_locators=campaign_locators,
        campaign_file_sha256s=campaign_file_sha256s,
        campaign_sha256s=campaign_sha256s,
        items=ordered_items,
        source_item_count=len(ordered_items),
        proposed_atomic_decision_count=sum(len(item.segments) for item in ordered_items),
        multiple_segment_item_count=sum(item.multiple_segments_proposed for item in ordered_items),
        residual_risk_item_count=sum(
            item.residual_decision_bearing_text_possible for item in ordered_items
        ),
    )


def compile_taste_source_segmentation_agreement(
    *,
    report_id: str,
    segmentation_paths: tuple[str | Path, str | Path],
    compiled_at: datetime,
    locator_root: str | Path,
) -> TasteSourceSegmentationAgreementReport:
    """Compare two segmenters; only exact span-and-family matches pass onward."""

    root = Path(locator_root).resolve(strict=True)
    inspections = tuple(
        load_taste_source_decision_segmentation_run(path) for path in segmentation_paths
    )
    first, second = (inspection.run for inspection in inspections)
    if first.project_id != second.project_id:
        raise ValueError("Segmentation runs target different projects")
    if first.screener_id == second.screener_id or first.invocation_id == second.invocation_id:
        raise ValueError("Segmentation comparison requires distinct agent invocations")
    if (
        first.source_agent_output_locator == second.source_agent_output_locator
        or first.source_agent_output_file_sha256 == second.source_agent_output_file_sha256
    ):
        raise ValueError("Segmentation comparison requires distinct raw agent artifacts")
    sample_binding = (
        first.sample_manifest_locator,
        first.sample_manifest_file_sha256,
        first.sample_sha256,
        first.sample_selection_timing,
    )
    if sample_binding != (
        second.sample_manifest_locator,
        second.sample_manifest_file_sha256,
        second.sample_sha256,
        second.sample_selection_timing,
    ):
        raise ValueError("Segmentation runs bind different source samples")
    if (
        first.rubric_locator,
        first.rubric_file_sha256,
        first.task_instruction_sha256,
    ) != (
        second.rubric_locator,
        second.rubric_file_sha256,
        second.task_instruction_sha256,
    ):
        raise ValueError("Segmentation runs bind different rubrics")
    if (
        first.campaign_locators,
        first.campaign_file_sha256s,
        first.campaign_sha256s,
    ) != (
        second.campaign_locators,
        second.campaign_file_sha256s,
        second.campaign_sha256s,
    ):
        raise ValueError("Segmentation runs bind different campaign inputs")
    if (
        first.model_identifier,
        first.model_revision,
        first.runtime_surface,
        first.runtime_identity_sha256,
        first.exact_model_identity_bound,
    ) != (
        second.model_identifier,
        second.model_revision,
        second.runtime_surface,
        second.runtime_identity_sha256,
        second.exact_model_identity_bound,
    ):
        raise ValueError("Segmentation calibration runs use different model conditions")
    first_items = {(item.campaign_id, item.review_item_id): item for item in first.items}
    second_items = {(item.campaign_id, item.review_item_id): item for item in second.items}
    if set(first_items) != set(second_items):
        raise ValueError("Segmentation runs cover different source items")

    compared: list[TasteSourceSegmentationAgreementItem] = []
    for key in sorted(first_items):
        item_a = first_items[key]
        item_b = second_items[key]
        if (
            item_a.review_item_sha256 != item_b.review_item_sha256
            or item_a.review_comment_sha256 != item_b.review_comment_sha256
        ):
            raise ValueError("Segmentation runs bind different source content")
        segments_a = {segment.segment_id: segment for segment in item_a.segments}
        segments_b = {segment.segment_id: segment for segment in item_b.segments}
        shared_ids = set(segments_a) & set(segments_b)
        overlap_pairs = _overlap_span_matches(
            tuple(segments_a.values()),
            tuple(segments_b.values()),
            iou_threshold_micros=500_000,
        )
        family_disagreements = tuple(
            sorted(
                segment_id
                for segment_id in shared_ids
                if segments_a[segment_id].primary_decision_family
                != segments_b[segment_id].primary_decision_family
            )
        )
        unmatched_a = tuple(sorted(set(segments_a) - shared_ids))
        unmatched_b = tuple(sorted(set(segments_b) - shared_ids))
        residual = bool(
            item_a.residual_decision_bearing_text_possible
            or item_b.residual_decision_bearing_text_possible
        )
        blockers: set[str] = set()
        if len(segments_a) != len(segments_b):
            blockers.add("segment-count-disagreement")
        if unmatched_a or unmatched_b:
            blockers.add("span-boundary-disagreement")
        if family_disagreements:
            blockers.add("decision-family-disagreement")
        if residual:
            blockers.add("residual-decision-risk")
        compared.append(
            TasteSourceSegmentationAgreementItem(
                campaign_id=item_a.campaign_id,
                review_item_id=item_a.review_item_id,
                review_item_sha256=item_a.review_item_sha256,
                segmenter_a_count=len(segments_a),
                segmenter_b_count=len(segments_b),
                exact_span_agreement_count=len(shared_ids),
                exact_span_family_agreement_count=(len(shared_ids) - len(family_disagreements)),
                overlap_span_agreement_count=len(overlap_pairs),
                overlap_span_family_agreement_count=sum(
                    segments_a[segment_a].primary_decision_family
                    == segments_b[segment_b].primary_decision_family
                    for segment_a, segment_b in overlap_pairs
                ),
                family_disagreement_segment_ids=family_disagreements,
                segmenter_a_unmatched_segment_ids=unmatched_a,
                segmenter_b_unmatched_segment_ids=unmatched_b,
                residual_decision_bearing_text_possible=residual,
                blocker_codes=tuple(sorted(blockers)),
                requires_adjudication=bool(blockers),
                exact_span_route_passed=not blockers,
            )
        )
    blocker_counts: dict[str, int] = {}
    for item in compared:
        for blocker in item.blocker_codes:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    artifacts = tuple(
        TasteSourceSegmentationArtifactBinding(
            screener_id=inspection.run.screener_id,
            invocation_id=inspection.run.invocation_id,
            locator=_relative(inspection.path, root),
            file_sha256=inspection.file_sha256,
            run_sha256=inspection.run.run_sha256,
            source_agent_output_locator=inspection.run.source_agent_output_locator,
            source_agent_output_file_sha256=(inspection.run.source_agent_output_file_sha256),
            reproducibility_ready=inspection.run.reproducibility_ready,
            network_isolation_verified=inspection.run.network_isolation_verified,
        )
        for inspection in inspections
    )
    count_a = sum(item.segmenter_a_count for item in compared)
    count_b = sum(item.segmenter_b_count for item in compared)
    exact_count = sum(item.exact_span_agreement_count for item in compared)
    overlap_count = sum(item.overlap_span_agreement_count for item in compared)
    overlap_family_count = sum(item.overlap_span_family_agreement_count for item in compared)
    segmenter_reproducibility_ready = all(artifact.reproducibility_ready for artifact in artifacts)
    network_isolation_verified = all(artifact.network_isolation_verified for artifact in artifacts)
    overlap_f1_micros = _f1_micros(overlap_count, count_a, count_b)
    overlap_family_agreement_micros = (overlap_family_count * 1_000_000) // max(1, overlap_count)
    scale_blockers: set[str] = set()
    if first.sample_selection_timing != "preregistered":
        scale_blockers.add("calibration-sample-not-preregistered")
    if not segmenter_reproducibility_ready:
        scale_blockers.add("segmenter-model-runtime-unbound")
    if not network_isolation_verified:
        scale_blockers.add("outcome-blind-network-isolation-unverified")
    if overlap_f1_micros < 800_000:
        scale_blockers.add("overlap-span-agreement-below-calibration-threshold")
    if overlap_family_agreement_micros < 800_000:
        scale_blockers.add("overlap-family-agreement-below-calibration-threshold")
    return TasteSourceSegmentationAgreementReport(
        report_id=report_id,
        project_id=first.project_id,
        compiled_at=compiled_at,
        artifacts=artifacts,
        sample_manifest_locator=first.sample_manifest_locator,
        sample_manifest_file_sha256=first.sample_manifest_file_sha256,
        sample_sha256=first.sample_sha256,
        sample_selection_timing=first.sample_selection_timing,
        items=tuple(compared),
        source_item_count=len(compared),
        segmenter_a_decision_count=count_a,
        segmenter_b_decision_count=count_b,
        exact_span_agreement_count=exact_count,
        exact_span_family_agreement_count=sum(
            item.exact_span_family_agreement_count for item in compared
        ),
        exact_span_f1_micros=_f1_micros(exact_count, count_a, count_b),
        overlap_iou_threshold_micros=500_000,
        overlap_span_agreement_count=overlap_count,
        overlap_span_family_agreement_count=overlap_family_count,
        overlap_span_f1_micros=overlap_f1_micros,
        overlap_matched_family_agreement_micros=(overlap_family_agreement_micros),
        exact_span_route_item_count=sum(item.exact_span_route_passed for item in compared),
        adjudication_item_count=sum(item.requires_adjudication for item in compared),
        blocker_item_counts=dict(sorted(blocker_counts.items())),
        all_items_exactly_agreed=not blocker_counts,
        distinct_agent_artifacts_verified=True,
        cross_output_blinding_attested=True,
        segmenter_reproducibility_ready=segmenter_reproducibility_ready,
        network_isolation_verified=network_isolation_verified,
        scaled_execution_blocker_codes=tuple(sorted(scale_blockers)),
        scaled_execution_authorized=not scale_blockers,
    )


def normalize_taste_source_segmentation_resolution(
    *,
    raw_resolution_path: str | Path,
    agreement_path: str | Path,
    run_id: str,
    adjudicator_id: str,
    invocation_id: str,
    runtime_surface: str,
    model_identifier: str,
    model_revision: str | None,
    exact_model_identity_bound: bool,
    rubric_path: str | Path,
    runtime_identity_sha256: str | None,
    completed_at: datetime,
    locator_root: str | Path,
) -> TasteSourceSegmentationResolutionRun:
    """Bind one AI adjudication to its dual-agent report and immutable sources."""

    root = Path(locator_root).resolve(strict=True)
    raw_path = _bounded_file(Path(raw_resolution_path), _MAX_INPUT_BYTES)
    rubric = _bounded_file(Path(rubric_path), _MAX_INPUT_BYTES)
    rubric_file_sha256 = _sha256_file(rubric)
    raw = json.loads(raw_path.read_bytes())
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ValueError("Taste source segmentation resolution must contain an items list")
    boundary = raw.get("input_boundary")
    if not isinstance(boundary, dict) or (
        boundary.get("segmenter_outputs_read") is not True
        or boundary.get("private_item_map_read") is not False
        or boundary.get("population_outcomes_read") is not False
    ):
        raise ValueError("Taste source segmentation resolution input boundary is invalid")
    if raw.get("rubric_read") is not True or raw.get("rubric_file_sha256") != rubric_file_sha256:
        raise ValueError("Segmentation resolution lacks exact rubric attestation")

    agreement_inspection = load_taste_source_segmentation_agreement_report(agreement_path)
    agreement = agreement_inspection.report
    if raw.get("source_agreement_report_sha256") != agreement.report_sha256:
        raise ValueError("Segmentation resolution names a different agreement report")
    segmentation_inspections = tuple(
        load_taste_source_decision_segmentation_run(root / artifact.locator)
        for artifact in agreement.artifacts
    )
    for binding, inspection in zip(agreement.artifacts, segmentation_inspections, strict=True):
        if (
            binding.file_sha256 != inspection.file_sha256
            or binding.run_sha256 != inspection.run.run_sha256
        ):
            raise ValueError("Segmentation resolution source artifact drifted")
    source_run = segmentation_inspections[0].run
    scientific_items: dict[tuple[str, str], ScientificTasteSourceReviewItem] = {}
    for campaign_id, locator in source_run.campaign_locators.items():
        campaign_path = _bounded_file(root / locator, _MAX_ARTIFACT_BYTES)
        if _sha256_file(campaign_path) != source_run.campaign_file_sha256s[campaign_id]:
            raise ValueError("Segmentation resolution campaign file drifted")
        campaign = load_taste_source_review_campaign(campaign_path)
        if campaign.campaign_sha256 != source_run.campaign_sha256s[campaign_id]:
            raise ValueError("Segmentation resolution campaign content drifted")
        for item in load_taste_source_review_items(campaign_path, TasteSourceReviewRole.SCIENTIFIC):
            if isinstance(item, ScientificTasteSourceReviewItem):
                scientific_items[(campaign_id, item.review_item_id)] = item

    agreement_items = {(item.campaign_id, item.review_item_id): item for item in agreement.items}
    first_segments = {
        (item.campaign_id, item.review_item_id): {
            segment.segment_id: segment for segment in item.segments
        }
        for item in source_run.items
    }
    resolved: list[TasteSourceSegmentationResolutionItem] = []
    for raw_item in raw["items"]:
        if not isinstance(raw_item, dict) or not isinstance(raw_item.get("segments"), list):
            raise ValueError("Taste source segmentation resolution item is invalid")
        key = (raw_item.get("campaign_id"), raw_item.get("review_item_id"))
        agreement_item = agreement_items.get(key)
        source = scientific_items.get(key)
        if agreement_item is None or source is None:
            raise ValueError("Segmentation resolution item is outside the agreement set")
        if raw_item.get("source_blocker_codes") != list(agreement_item.blocker_codes):
            raise ValueError("Segmentation resolution source blockers differ")
        expected_kind = (
            "ai-adjudicated"
            if agreement_item.requires_adjudication
            else "exact-dual-agent-agreement"
        )
        if raw_item.get("resolution_kind") != expected_kind:
            raise ValueError("Segmentation resolution kind differs from agreement routing")
        segments = _normalize_raw_segments(
            raw_segments=raw_item["segments"],
            campaign_id=key[0],
            review_item_id=key[1],
            review_comment=source.review_comment,
        )
        if expected_kind == "exact-dual-agent-agreement":
            expected_segments = first_segments[key]
            actual_segments = {segment.segment_id: segment for segment in segments}
            if set(actual_segments) != set(expected_segments) or any(
                actual_segments[segment_id].primary_decision_family
                != expected_segments[segment_id].primary_decision_family
                for segment_id in actual_segments
            ):
                raise ValueError("Exact-agreement segments changed during resolution")
        resolved.append(
            TasteSourceSegmentationResolutionItem(
                campaign_id=key[0],
                review_item_id=key[1],
                review_item_sha256=_canonical_sha256(source.model_dump(mode="json")),
                resolution_kind=expected_kind,
                source_blocker_codes=agreement_item.blocker_codes,
                segments=segments,
                residual_decision_bearing_text_possible=raw_item.get(
                    "residual_decision_bearing_text_possible"
                ),
                resolution_rationale=raw_item.get("resolution_rationale"),
            )
        )
    if {(item.campaign_id, item.review_item_id) for item in resolved} != set(agreement_items):
        raise ValueError("Segmentation resolution does not cover the exact agreement set")
    ordered = tuple(sorted(resolved, key=lambda item: (item.campaign_id, item.review_item_id)))
    residual_count = sum(item.residual_decision_bearing_text_possible for item in ordered)
    adjudicator_reproducibility_ready = bool(
        exact_model_identity_bound and model_revision and runtime_identity_sha256
    )
    chain_reproducibility_ready = adjudicator_reproducibility_ready and all(
        artifact.reproducibility_ready for artifact in agreement.artifacts
    )
    screening_blockers: set[str] = set()
    if residual_count:
        screening_blockers.add("residual-decision-risk")
    if not all(artifact.reproducibility_ready for artifact in agreement.artifacts):
        screening_blockers.add("segmenter-model-runtime-unbound")
    if not adjudicator_reproducibility_ready:
        screening_blockers.add("adjudicator-model-runtime-unbound")
    if not all(artifact.network_isolation_verified for artifact in agreement.artifacts):
        screening_blockers.add("outcome-blind-network-isolation-unverified")
    return TasteSourceSegmentationResolutionRun(
        run_id=run_id,
        project_id=agreement.project_id,
        adjudicator_id=adjudicator_id,
        invocation_id=invocation_id,
        runtime_surface=runtime_surface,
        model_identifier=model_identifier,
        model_revision=model_revision,
        exact_model_identity_bound=exact_model_identity_bound,
        rubric_locator=_relative(rubric, root),
        rubric_file_sha256=rubric_file_sha256,
        task_instruction_sha256=rubric_file_sha256,
        runtime_identity_sha256=runtime_identity_sha256,
        reproducibility_ready=adjudicator_reproducibility_ready,
        completed_at=completed_at,
        source_agent_output_locator=_relative(raw_path, root),
        source_agent_output_file_sha256=_sha256_file(raw_path),
        agreement_locator=_relative(agreement_inspection.path, root),
        agreement_file_sha256=agreement_inspection.file_sha256,
        agreement_report_sha256=agreement.report_sha256,
        source_segmentation_artifacts=agreement.artifacts,
        items=ordered,
        source_item_count=len(ordered),
        final_atomic_decision_count=sum(len(item.segments) for item in ordered),
        exact_agreement_item_count=sum(
            item.resolution_kind == "exact-dual-agent-agreement" for item in ordered
        ),
        ai_adjudicated_item_count=sum(item.resolution_kind == "ai-adjudicated" for item in ordered),
        residual_risk_item_count=residual_count,
        internal_pilot_resolution_complete=residual_count == 0,
        chain_reproducibility_ready=chain_reproducibility_ready,
        internal_screening_blocker_codes=tuple(sorted(screening_blockers)),
        internal_ai_screening_ready=not screening_blockers,
    )


def save_taste_source_decision_segmentation_run(
    run: TasteSourceDecisionSegmentationRun,
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
            handle.write(run.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_taste_source_decision_segmentation_run(
    path: str | Path,
) -> TasteSourceDecisionSegmentationInspection:
    source = _bounded_file(Path(path), _MAX_ARTIFACT_BYTES)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Taste source segmentation artifact must contain a mapping")
    recorded = payload.pop("run_sha256", None)
    run = TasteSourceDecisionSegmentationRun.model_validate(payload)
    if recorded != run.run_sha256:
        raise ValueError("Taste source segmentation artifact hash mismatch")
    return TasteSourceDecisionSegmentationInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        run=run,
    )


def save_taste_source_segmentation_agreement_report(
    report: TasteSourceSegmentationAgreementReport,
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
            handle.write(report.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_taste_source_segmentation_agreement_report(
    path: str | Path,
) -> TasteSourceSegmentationAgreementInspection:
    source = _bounded_file(Path(path), _MAX_ARTIFACT_BYTES)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Taste source segmentation agreement must contain a mapping")
    recorded = payload.pop("report_sha256", None)
    report = TasteSourceSegmentationAgreementReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("Taste source segmentation agreement hash mismatch")
    return TasteSourceSegmentationAgreementInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=report,
    )


def save_taste_source_segmentation_resolution_run(
    run: TasteSourceSegmentationResolutionRun,
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
            handle.write(run.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_taste_source_segmentation_resolution_run(
    path: str | Path,
) -> TasteSourceSegmentationResolutionInspection:
    source = _bounded_file(Path(path), _MAX_ARTIFACT_BYTES)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Taste source segmentation resolution must contain a mapping")
    recorded = payload.pop("run_sha256", None)
    run = TasteSourceSegmentationResolutionRun.model_validate(payload)
    if recorded != run.run_sha256:
        raise ValueError("Taste source segmentation resolution hash mismatch")
    return TasteSourceSegmentationResolutionInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        run=run,
    )


def _normalize_raw_segments(
    *,
    raw_segments: list[object],
    campaign_id: str,
    review_item_id: str,
    review_comment: str,
) -> tuple[TasteSourceDecisionSegment, ...]:
    segments: list[TasteSourceDecisionSegment] = []
    for ordinal, raw_segment in enumerate(raw_segments, 1):
        if not isinstance(raw_segment, dict):
            raise ValueError("Taste source decision segment must be a mapping")
        verbatim = raw_segment.get("verbatim_decision_text")
        if not isinstance(verbatim, str):
            raise ValueError("Taste source decision segment lacks verbatim source text")
        raw_start = raw_segment.get("start_char")
        raw_end = raw_segment.get("end_char")
        if raw_start is None and raw_end is None:
            start = review_comment.find(verbatim)
            if start < 0 or review_comment.find(verbatim, start + 1) >= 0:
                raise ValueError("Taste source decision span must occur exactly once")
            end = start + len(verbatim)
        else:
            if (
                not isinstance(raw_start, int)
                or isinstance(raw_start, bool)
                or not isinstance(raw_end, int)
                or isinstance(raw_end, bool)
                or raw_start < 0
                or raw_end <= raw_start
                or raw_end > len(review_comment)
                or review_comment[raw_start:raw_end] != verbatim
            ):
                raise ValueError("Taste source decision offsets differ from source bytes")
            start, end = raw_start, raw_end
        segment_identity = _canonical_sha256(
            [campaign_id, review_item_id, start, end, verbatim]
        )
        segments.append(
            TasteSourceDecisionSegment(
                segment_id=f"segment-{segment_identity[:24]}",
                ordinal=ordinal,
                start_char=start,
                end_char=end,
                verbatim_decision_text=verbatim,
                primary_decision_family=raw_segment.get("primary_decision_family"),
                atomic_decision_statement=raw_segment.get("atomic_decision_statement"),
                rationale=raw_segment.get("rationale"),
                uncertainty=raw_segment.get("uncertainty"),
            )
        )
    segments.sort(key=lambda item: (item.start_char, item.end_char))
    return tuple(
        segment.model_copy(update={"ordinal": index + 1}) for index, segment in enumerate(segments)
    )


def _f1_micros(matched: int, first_count: int, second_count: int) -> int:
    denominator = first_count + second_count
    if denominator == 0:
        return 1_000_000
    return (2 * matched * 1_000_000) // denominator


def _overlap_span_matches(
    first: tuple[TasteSourceDecisionSegment, ...],
    second: tuple[TasteSourceDecisionSegment, ...],
    *,
    iou_threshold_micros: int,
) -> tuple[tuple[str, str], ...]:
    """Return a deterministic maximum-cardinality interval-IoU matching."""

    by_first = {segment.segment_id: segment for segment in first}
    by_second = {segment.segment_id: segment for segment in second}
    candidates: dict[str, tuple[str, ...]] = {}
    for first_id, first_segment in by_first.items():
        scored: list[tuple[int, str]] = []
        for second_id, second_segment in by_second.items():
            overlap = max(
                0,
                min(first_segment.end_char, second_segment.end_char)
                - max(first_segment.start_char, second_segment.start_char),
            )
            union = max(first_segment.end_char, second_segment.end_char) - min(
                first_segment.start_char, second_segment.start_char
            )
            if overlap * 1_000_000 >= union * iou_threshold_micros:
                scored.append(((overlap * 1_000_000) // union, second_id))
        candidates[first_id] = tuple(
            second_id for _, second_id in sorted(scored, key=lambda item: (-item[0], item[1]))
        )

    matched_second: dict[str, str] = {}

    def assign(first_id: str, visited: set[str]) -> bool:
        for second_id in candidates[first_id]:
            if second_id in visited:
                continue
            visited.add(second_id)
            previous = matched_second.get(second_id)
            if previous is None or assign(previous, visited):
                matched_second[second_id] = first_id
                return True
        return False

    for first_id in sorted(by_first):
        assign(first_id, set())
    return tuple(sorted((first_id, second_id) for second_id, first_id in matched_second.items()))


def _bounded_file(path: Path, maximum_bytes: int) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Taste source segmentation input must be a regular non-symlink file")
    if path.stat().st_size > maximum_bytes:
        raise ValueError("Taste source segmentation input exceeds its byte limit")
    return path.resolve(strict=True)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(
            "Taste source segmentation artifact is outside the locator root"
        ) from error


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
    "TasteSourceDecisionSegment",
    "TasteSourceDecisionSegmentationInspection",
    "TasteSourceDecisionSegmentationRun",
    "TasteSourceSegmentationAgreementInspection",
    "TasteSourceSegmentationAgreementItem",
    "TasteSourceSegmentationAgreementReport",
    "TasteSourceSegmentationArtifactBinding",
    "TasteSourceSegmentationResolutionInspection",
    "TasteSourceSegmentationResolutionItem",
    "TasteSourceSegmentationResolutionRun",
    "TasteSourceSegmentationSampleInspection",
    "TasteSourceSegmentationSampleItem",
    "TasteSourceSegmentationSampleManifest",
    "TasteSourceSegmentedItem",
    "compile_taste_source_segmentation_agreement",
    "load_taste_source_decision_segmentation_run",
    "load_taste_source_segmentation_agreement_report",
    "load_taste_source_segmentation_resolution_run",
    "load_taste_source_segmentation_sample_manifest",
    "normalize_taste_source_decision_segmentation",
    "normalize_taste_source_segmentation_resolution",
    "plan_taste_source_segmentation_sample",
    "save_taste_source_decision_segmentation_run",
    "save_taste_source_segmentation_agreement_report",
    "save_taste_source_segmentation_resolution_run",
    "save_taste_source_segmentation_sample_manifest",
    "verify_taste_source_segmentation_sample_bindings",
]
