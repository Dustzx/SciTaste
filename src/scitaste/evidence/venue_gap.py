"""Venue-aware criticism of a paper's complete scientific evidence program.

This module deliberately evaluates an evidence *portfolio*, rather than rewarding a
single attractive result.  It compares explicit claims with accepted nearest
neighbours, separates development signals from admissible evidence, and uses the
project's real venue deadline to rank the next claim-closing action.
"""

from __future__ import annotations

import os
import stat
from enum import StrEnum
from math import sqrt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.deadlines import ProjectDeadlineStatus, VenueMilestoneKind
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


class VenueGapDimension(StrEnum):
    """Distinct reviewer questions that a top-venue paper must answer."""

    INNOVATION = "innovation-relative-to-neighbours"
    CONSTRUCT_VALIDITY = "scientific-taste-construct-validity"
    MECHANISM = "mechanism-and-selectivity"
    DOWNSTREAM_CAUSAL_UTILITY = "downstream-causal-utility"
    END_TO_END = "idea-to-paper-end-to-end"
    BASELINE_STRENGTH = "strong-baseline-coverage"
    GENERALIZATION = "cross-model-and-domain-generalization"
    EXTERNAL_VALIDITY = "objective-or-external-validity"
    FAILURE_BOUNDARIES = "failure-boundaries"
    STATISTICAL_STRENGTH = "statistical-strength"
    NARRATIVE_CONTRIBUTION = "new-knowledge-and-narrative"


_REQUIRED_DIMENSIONS = frozenset(VenueGapDimension)


class AcceptedPaperKind(StrEnum):
    METHOD = "method"
    BENCHMARK = "benchmark"
    METHOD_AND_BENCHMARK = "method-and-benchmark"


class EvidenceMaturity(StrEnum):
    DEVELOPMENT_ONLY = "development-only"
    ADMITTED = "admitted"


class EvidenceDirection(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"


class VenueCriterionStatus(StrEnum):
    MISSING = "missing"
    DEVELOPMENT_ONLY = "development-only"
    PARTIAL = "partial"
    SUFFICIENT_FOR_REVIEW = "sufficient-for-review"
    CONTRADICTED = "contradicted"


class VenueGapActionKind(StrEnum):
    EXPERIMENT = "experiment"
    ANALYSIS = "analysis"
    WRITING = "writing"
    LITERATURE = "literature"


class SubmissionEvidencePosition(StrEnum):
    CONTRADICTED = "core-claim-contradicted"
    NOT_YET_COMPETITIVE = "not-yet-competitive"
    EVIDENCE_PROGRAM_COMPLETE_FOR_REVIEW = "evidence-program-complete-for-review"


class AcceptedNearestNeighbour(BaseModel):
    """A source-bound main-track paper used as a concrete comparison point."""

    model_config = _CONFIG

    paper_id: str
    title: str = Field(min_length=1, max_length=500)
    venue: str = Field(min_length=1, max_length=200)
    year: int = Field(ge=2000, le=2100)
    paper_kind: AcceptedPaperKind
    acceptance_status: Literal["accepted-main"] = "accepted-main"
    source_url: str = Field(min_length=1, max_length=2_000)
    closest_capability: str = Field(min_length=1, max_length=2_000)
    reported_evidence: tuple[str, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def neighbour_is_source_bound(self) -> AcceptedNearestNeighbour:
        validate_entry_id(self.paper_id, field_name="nearest-neighbour paper_id")
        if not self.source_url.startswith("https://"):
            raise ValueError("nearest-neighbour source_url must use HTTPS")
        return self


class VenueEvidenceSignal(BaseModel):
    """One observed result; development signals can never become headline evidence."""

    model_config = _CONFIG

    evidence_id: str
    family_id: str
    dimension: VenueGapDimension
    evidence_type: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    maturity: EvidenceMaturity
    direction: EvidenceDirection = EvidenceDirection.SUPPORTING
    headline_eligible: bool = False
    objective_measurement: bool = False
    held_out: bool = False
    model_ids: tuple[str, ...] = Field(default=(), max_length=30)
    domain_ids: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def maturity_controls_headline_role(self) -> VenueEvidenceSignal:
        validate_entry_id(self.evidence_id, field_name="venue evidence_id")
        validate_entry_id(self.family_id, field_name="venue evidence family_id")
        if self.maturity is EvidenceMaturity.DEVELOPMENT_ONLY and self.headline_eligible:
            raise ValueError("development-only evidence cannot be headline eligible")
        return self


class VenueEvidenceCriterion(BaseModel):
    """One explicit reviewer question and the evidence contract that would answer it."""

    model_config = _CONFIG

    dimension: VenueGapDimension
    claim: str = Field(min_length=1, max_length=2_000)
    requirement: str = Field(min_length=1, max_length=2_000)
    required_evidence_types: tuple[str, ...] = Field(min_length=1, max_length=20)
    nearest_neighbour_ids: tuple[str, ...] = Field(default=(), max_length=30)
    scientific_importance: float = Field(ge=0.0, le=1.0)
    reviewer_rejection_risk: float = Field(ge=0.0, le=1.0)
    candidate_action_ids: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def criterion_is_canonical(self) -> VenueEvidenceCriterion:
        if self.required_evidence_types != tuple(sorted(set(self.required_evidence_types))):
            raise ValueError("required evidence types must be sorted and unique")
        if self.nearest_neighbour_ids != tuple(sorted(set(self.nearest_neighbour_ids))):
            raise ValueError("nearest-neighbour IDs must be sorted and unique")
        if self.candidate_action_ids != tuple(sorted(set(self.candidate_action_ids))):
            raise ValueError("candidate action IDs must be sorted and unique")
        return self


class VenueGapAction(BaseModel):
    """A bounded candidate action; compilation ranks but never executes it."""

    model_config = _CONFIG

    action_id: str
    title: str = Field(min_length=1, max_length=500)
    kind: VenueGapActionKind
    closes_dimensions: tuple[VenueGapDimension, ...] = Field(min_length=1, max_length=11)
    produces_evidence_types: tuple[str, ...] = Field(min_length=1, max_length=30)
    estimated_hours: float = Field(gt=0.0, le=10_000, allow_inf_nan=False)
    expected_information_gain: float = Field(ge=0.0, le=1.0)
    feasibility: float = Field(ge=0.0, le=1.0)
    estimated_api_cost_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    estimated_gpu_hours: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def action_is_canonical(self) -> VenueGapAction:
        validate_entry_id(self.action_id, field_name="venue-gap action_id")
        if self.closes_dimensions != tuple(
            sorted(set(self.closes_dimensions), key=lambda item: item.value)
        ):
            raise ValueError("action dimensions must be sorted and unique")
        if self.produces_evidence_types != tuple(sorted(set(self.produces_evidence_types))):
            raise ValueError("action evidence types must be sorted and unique")
        return self


class VenueGapManifest(BaseModel):
    """Complete comparison-and-evidence input for one paper snapshot."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    project_id: str
    target_venue: str = Field(min_length=1, max_length=200)
    paper_title: str = Field(min_length=1, max_length=500)
    central_contribution: str = Field(min_length=1, max_length=3_000)
    nearest_neighbours: tuple[AcceptedNearestNeighbour, ...] = Field(min_length=2, max_length=30)
    criteria: tuple[VenueEvidenceCriterion, ...] = Field(min_length=11, max_length=11)
    evidence: tuple[VenueEvidenceSignal, ...] = Field(default=(), max_length=10_000)
    candidate_actions: tuple[VenueGapAction, ...] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> VenueGapManifest:
        validate_entry_id(self.manifest_id, field_name="venue-gap manifest_id")
        validate_project_id(self.project_id)
        neighbour_ids = [item.paper_id for item in self.nearest_neighbours]
        if len(neighbour_ids) != len(set(neighbour_ids)):
            raise ValueError("nearest-neighbour paper IDs must be unique")
        dimensions = [item.dimension for item in self.criteria]
        if set(dimensions) != _REQUIRED_DIMENSIONS or len(dimensions) != len(set(dimensions)):
            raise ValueError("venue-gap manifest must define every reviewer dimension exactly once")
        if tuple(dimensions) != tuple(sorted(dimensions, key=lambda item: item.value)):
            raise ValueError("venue-gap criteria must be sorted by dimension")
        action_ids = [item.action_id for item in self.candidate_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("venue-gap action IDs must be unique")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("venue-gap evidence IDs must be unique")
        known_neighbours = set(neighbour_ids)
        known_actions = set(action_ids)
        for criterion in self.criteria:
            if set(criterion.nearest_neighbour_ids) - known_neighbours:
                raise ValueError("criterion references an unknown accepted neighbour")
            if set(criterion.candidate_action_ids) - known_actions:
                raise ValueError("criterion references an unknown venue-gap action")
        return self


class VenueCriterionAssessment(BaseModel):
    model_config = _CONFIG

    dimension: VenueGapDimension
    status: VenueCriterionStatus
    claim: str
    requirement: str
    missing_evidence_types: tuple[str, ...]
    admitted_support_ids: tuple[str, ...]
    development_signal_ids: tuple[str, ...]
    development_contradiction_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    nearest_neighbour_ids: tuple[str, ...]
    reviewer_rejection_risk: float = Field(ge=0.0, le=1.0)
    diagnosis: str


class RankedVenueGapAction(BaseModel):
    model_config = _CONFIG

    action_id: str
    priority_rank: int = Field(ge=1)
    deadline_adjusted_utility: float = Field(ge=0.0, allow_inf_nan=False)
    closes_unresolved_dimensions: tuple[VenueGapDimension, ...]
    fits_before_paper_deadline: bool
    estimated_hours: float = Field(gt=0.0, allow_inf_nan=False)
    reason: str


class VenueGapAssessment(BaseModel):
    """A venue comparison, not a prediction of acceptance or oral selection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    manifest_id: str
    target_venue: str
    paper_title: str
    project_revision: int = Field(ge=0)
    project_snapshot_sha256: str
    deadline_status_sha256: str
    paper_deadline_hours_remaining: float | None
    submission_position: SubmissionEvidencePosition
    criteria: tuple[VenueCriterionAssessment, ...]
    unresolved_dimensions: tuple[VenueGapDimension, ...]
    admitted_evidence_family_count: int = Field(ge=0)
    single_result_is_insufficient: Literal[True] = True
    acceptance_prediction_made: Literal[False] = False
    oral_prediction_made: Literal[False] = False
    next_actions: tuple[RankedVenueGapAction, ...]
    strongest_rejection_reasons: tuple[str, ...]
    assessment_sha256: str

    @model_validator(mode="after")
    def assessment_hash_is_valid(self) -> VenueGapAssessment:
        expected = content_sha256(self.model_dump(mode="json", exclude={"assessment_sha256"}))
        if self.assessment_sha256 != expected:
            raise ValueError("venue-gap assessment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueGapAssessment:
        payload = {"schema_version": "1.0", **values}
        payload.pop("assessment_sha256", None)
        unsigned = cls.model_construct(assessment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            assessment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"assessment_sha256"})
            ),
        )


def assess_venue_gap(
    manifest: VenueGapManifest,
    deadline: ProjectDeadlineStatus,
) -> VenueGapAssessment:
    """Compile an evidence-bound, deadline-aware top-venue gap assessment."""

    if manifest.project_id != deadline.project_id:
        raise ValueError("venue-gap manifest and deadline status projects differ")
    if _normalize(manifest.target_venue) != _normalize(deadline.venue_id):
        raise ValueError("venue-gap target venue differs from assigned project venue")

    known_neighbours = {item.paper_id for item in manifest.nearest_neighbours}
    assessments = tuple(
        _assess_criterion(criterion, manifest.evidence, known_neighbours)
        for criterion in manifest.criteria
    )
    unresolved = tuple(
        item.dimension
        for item in assessments
        if item.status is not VenueCriterionStatus.SUFFICIENT_FOR_REVIEW
    )
    if any(item.status is VenueCriterionStatus.CONTRADICTED for item in assessments):
        position = SubmissionEvidencePosition.CONTRADICTED
    elif unresolved:
        position = SubmissionEvidencePosition.NOT_YET_COMPETITIVE
    else:
        position = SubmissionEvidencePosition.EVIDENCE_PROGRAM_COMPLETE_FOR_REVIEW

    admitted_families = {
        item.family_id
        for item in manifest.evidence
        if item.maturity is EvidenceMaturity.ADMITTED
        and item.headline_eligible
        and item.direction is EvidenceDirection.SUPPORTING
    }
    paper_hours = _paper_deadline_hours(deadline)
    ranked = _rank_actions(manifest, assessments, paper_hours)
    rejection_reasons = tuple(
        item.diagnosis
        for item in sorted(
            assessments,
            key=lambda item: (
                item.status is VenueCriterionStatus.SUFFICIENT_FOR_REVIEW,
                -item.reviewer_rejection_risk,
                item.dimension.value,
            ),
        )
        if item.status is not VenueCriterionStatus.SUFFICIENT_FOR_REVIEW
    )[:5]
    return VenueGapAssessment.create(
        project_id=manifest.project_id,
        manifest_id=manifest.manifest_id,
        target_venue=manifest.target_venue,
        paper_title=manifest.paper_title,
        project_revision=deadline.project_revision,
        project_snapshot_sha256=deadline.project_snapshot_sha256,
        deadline_status_sha256=deadline.status_sha256,
        paper_deadline_hours_remaining=paper_hours,
        submission_position=position,
        criteria=assessments,
        unresolved_dimensions=unresolved,
        admitted_evidence_family_count=len(admitted_families),
        single_result_is_insufficient=True,
        acceptance_prediction_made=False,
        oral_prediction_made=False,
        next_actions=ranked,
        strongest_rejection_reasons=rejection_reasons,
    )


def _assess_criterion(
    criterion: VenueEvidenceCriterion,
    evidence: tuple[VenueEvidenceSignal, ...],
    known_neighbours: set[str],
) -> VenueCriterionAssessment:
    related = tuple(item for item in evidence if item.dimension is criterion.dimension)
    admitted_support = tuple(
        item
        for item in related
        if item.direction is EvidenceDirection.SUPPORTING
        and item.maturity is EvidenceMaturity.ADMITTED
        and item.headline_eligible
    )
    development = tuple(
        item
        for item in related
        if item.maturity is EvidenceMaturity.DEVELOPMENT_ONLY
    )
    contradictions = tuple(
        item
        for item in related
        if item.direction is EvidenceDirection.CONTRADICTING
        and item.maturity is EvidenceMaturity.ADMITTED
        and item.headline_eligible
    )
    development_contradictions = tuple(
        item for item in development if item.direction is EvidenceDirection.CONTRADICTING
    )
    covered_types = {item.evidence_type for item in admitted_support}
    missing_types = tuple(
        item for item in criterion.required_evidence_types if item not in covered_types
    )
    neighbour_gap = (
        criterion.dimension is VenueGapDimension.INNOVATION
        and not (set(criterion.nearest_neighbour_ids) & known_neighbours)
    )

    if contradictions:
        status = VenueCriterionStatus.CONTRADICTED
        diagnosis = f"{criterion.dimension.value}: observed evidence contradicts the paper claim."
    elif not admitted_support and development:
        status = VenueCriterionStatus.DEVELOPMENT_ONLY
        diagnosis = (
            f"{criterion.dimension.value}: only development or proxy signals exist; "
            "they cannot support a paper-level claim."
        )
    elif not admitted_support:
        status = VenueCriterionStatus.MISSING
        diagnosis = (
            f"{criterion.dimension.value}: no admitted evidence supports this reviewer question."
        )
    elif missing_types or neighbour_gap or development_contradictions:
        status = VenueCriterionStatus.PARTIAL
        diagnosis = (
            f"{criterion.dimension.value}: admitted evidence exists but does not close "
            + (
                ", ".join(missing_types)
                if missing_types
                else (
                    "a conflicting development signal"
                    if development_contradictions
                    else "accepted-neighbour comparison"
                )
            )
            + "."
        )
    else:
        status = VenueCriterionStatus.SUFFICIENT_FOR_REVIEW
        diagnosis = (
            f"{criterion.dimension.value}: the declared evidence contract is covered; "
            "this is not an acceptance prediction."
        )
    return VenueCriterionAssessment(
        dimension=criterion.dimension,
        status=status,
        claim=criterion.claim,
        requirement=criterion.requirement,
        missing_evidence_types=missing_types,
        admitted_support_ids=tuple(sorted(item.evidence_id for item in admitted_support)),
        development_signal_ids=tuple(sorted(item.evidence_id for item in development)),
        development_contradiction_ids=tuple(
            sorted(item.evidence_id for item in development_contradictions)
        ),
        contradicting_evidence_ids=tuple(sorted(item.evidence_id for item in contradictions)),
        nearest_neighbour_ids=criterion.nearest_neighbour_ids,
        reviewer_rejection_risk=criterion.reviewer_rejection_risk,
        diagnosis=diagnosis,
    )


def _rank_actions(
    manifest: VenueGapManifest,
    assessments: tuple[VenueCriterionAssessment, ...],
    paper_deadline_hours: float | None,
) -> tuple[RankedVenueGapAction, ...]:
    criterion_by_dimension = {item.dimension: item for item in manifest.criteria}
    unresolved = {
        item.dimension: item
        for item in assessments
        if item.status is not VenueCriterionStatus.SUFFICIENT_FOR_REVIEW
    }
    candidates: list[tuple[VenueGapAction, tuple[VenueGapDimension, ...], float, bool]] = []
    gap_weights = {
        VenueCriterionStatus.MISSING: 1.5,
        VenueCriterionStatus.DEVELOPMENT_ONLY: 0.5,
        VenueCriterionStatus.PARTIAL: 0.75,
        VenueCriterionStatus.CONTRADICTED: 1.75,
    }
    empirical_core = {
        VenueGapDimension.CONSTRUCT_VALIDITY,
        VenueGapDimension.MECHANISM,
        VenueGapDimension.DOWNSTREAM_CAUSAL_UTILITY,
        VenueGapDimension.END_TO_END,
        VenueGapDimension.BASELINE_STRENGTH,
        VenueGapDimension.GENERALIZATION,
        VenueGapDimension.EXTERNAL_VALIDITY,
        VenueGapDimension.STATISTICAL_STRENGTH,
    }
    empirical_core_is_open = bool(empirical_core & set(unresolved))
    for action in manifest.candidate_actions:
        closes = tuple(item for item in action.closes_dimensions if item in unresolved)
        if not closes:
            continue
        gap_value = sum(
            criterion_by_dimension[item].scientific_importance
            * criterion_by_dimension[item].reviewer_rejection_risk
            * gap_weights[unresolved[item].status]
            for item in closes
        )
        utility = (
            gap_value
            * action.expected_information_gain
            * action.feasibility
            / sqrt(action.estimated_hours)
        )
        if empirical_core_is_open and action.kind in {
            VenueGapActionKind.WRITING,
            VenueGapActionKind.LITERATURE,
        }:
            utility *= 0.1
        fits = paper_deadline_hours is None or action.estimated_hours <= paper_deadline_hours
        if not fits:
            utility *= 0.05
        candidates.append((action, closes, utility, fits))
    candidates.sort(key=lambda item: (-item[2], item[0].action_id))
    return tuple(
        RankedVenueGapAction(
            action_id=action.action_id,
            priority_rank=index,
            deadline_adjusted_utility=round(utility, 8),
            closes_unresolved_dimensions=closes,
            fits_before_paper_deadline=fits,
            estimated_hours=action.estimated_hours,
            reason=(
                "highest deadline-adjusted breadth and importance of unresolved claim closure"
                if fits
                else "scientifically relevant but does not fit before the paper deadline"
            ),
        )
        for index, (action, closes, utility, fits) in enumerate(candidates, start=1)
    )


def _paper_deadline_hours(deadline: ProjectDeadlineStatus) -> float | None:
    milestone = next(
        (
            item
            for item in deadline.milestones
            if item.kind is VenueMilestoneKind.PAPER_SUBMISSION and not item.completed
        ),
        None,
    )
    if milestone is None:
        return None
    return round(max(0, milestone.seconds_remaining) / 3600.0, 4)


def load_venue_gap_manifest(path: str | Path) -> VenueGapManifest:
    source = _bounded_regular_file(path, maximum_bytes=_MAX_MANIFEST_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return VenueGapManifest.model_validate(payload)


def save_venue_gap_assessment(assessment: VenueGapAssessment, path: str | Path) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (assessment.model_dump_json(indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    return target


def _bounded_regular_file(path: str | Path, *, maximum_bytes: int) -> Path:
    source = Path(path).expanduser()
    if source.is_symlink():
        raise ValueError("venue-gap manifest cannot be a symbolic link")
    resolved = source.resolve(strict=True)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum_bytes:
        raise ValueError("venue-gap manifest must be a bounded regular file")
    return resolved


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


__all__ = [
    "AcceptedNearestNeighbour",
    "AcceptedPaperKind",
    "EvidenceDirection",
    "EvidenceMaturity",
    "RankedVenueGapAction",
    "SubmissionEvidencePosition",
    "VenueCriterionAssessment",
    "VenueCriterionStatus",
    "VenueEvidenceCriterion",
    "VenueEvidenceSignal",
    "VenueGapAction",
    "VenueGapActionKind",
    "VenueGapAssessment",
    "VenueGapDimension",
    "VenueGapManifest",
    "assess_venue_gap",
    "load_venue_gap_manifest",
    "save_venue_gap_assessment",
]
