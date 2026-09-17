"""Venue-aware criticism of a paper's complete scientific evidence program.

This module deliberately evaluates an evidence *portfolio*, rather than rewarding a
single attractive result.  It compares explicit claims with accepted nearest
neighbours, separates development signals from admissible evidence, and uses the
project's real venue deadline to rank the next claim-closing action.
"""

from __future__ import annotations

import os
import re
import stat
from collections import defaultdict
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


class VenueContributionAxis(StrEnum):
    """Where a paper may make a scientifically distinct contribution."""

    PROBLEM_FORMULATION = "problem-formulation"
    TASTE_REPRESENTATION = "taste-representation"
    LEARNING_SIGNAL = "learning-signal"
    DECISION_MECHANISM = "decision-mechanism"
    CLOSED_LOOP_RESEARCH = "closed-loop-research"
    EVALUATION_CONSTRUCT = "evaluation-construct"


class VenueEvidenceComponent(StrEnum):
    """Recurring evidence components in accepted empirical papers."""

    TASK_DOMAIN_BREADTH = "task-and-domain-breadth"
    STRONG_SYSTEM_BASELINES = "strong-system-baselines"
    OBJECTIVE_HIDDEN_EVALUATION = "objective-or-hidden-evaluation"
    MECHANISM_ABLATION = "mechanism-ablation"
    HUMAN_EXPERT_VALIDATION = "human-or-expert-validation"
    END_TO_END_TRAJECTORIES = "end-to-end-trajectories"
    REAL_WORLD_CASE_STUDY = "real-world-case-study"
    STATISTICAL_UNCERTAINTY = "statistical-uncertainty"
    FAILURE_BOUNDARY_ANALYSIS = "failure-boundary-analysis"
    RESOURCE_COST_REPORTING = "resource-and-cost-reporting"


class VenueInnovationEvidenceStatus(StrEnum):
    PROPOSED_ONLY = "proposed-only"
    DEVELOPMENT_ONLY = "development-only"
    ADMITTED_SUPPORT = "admitted-support"
    CONTRADICTED = "contradicted"


class VenueClaimCentrality(StrEnum):
    """Whether failure of a claim collapses the paper's main argument."""

    CENTRAL = "central"
    SUPPORTING = "supporting"


class VenueComponentMaturity(StrEnum):
    MISSING = "missing"
    DEVELOPMENT_ONLY = "development-only"
    ADMITTED = "admitted"


class VenueComponentDirection(StrEnum):
    NONE = "none"
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    MIXED = "mixed"


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


class VenueEvidenceProgramMode(StrEnum):
    """What the evidence controller must do before more paper-level claims."""

    REPAIR_CONTRADICTED_CORE = "repair-contradicted-core-claim"
    BUILD_ACCEPTED_COMPARABLE_PORTFOLIO = "build-accepted-comparable-portfolio"
    COMPLETE_FOR_REVIEW = "evidence-program-complete-for-review"


class VenueEvidenceScaleMetric(StrEnum):
    """Comparable counts that describe how much evidence a paper actually carries."""

    AUTHENTIC_RESEARCH_TASKS = "authentic-research-task-count"
    SCIENTIFIC_DISCIPLINES = "scientific-discipline-count"
    SOURCE_PUBLICATIONS = "source-publication-count"
    COMPETITIVE_SYSTEMS = "competitive-system-count"
    EXPERT_EVALUATORS = "expert-evaluator-count"
    RANDOM_SEEDS = "random-seed-count"
    MECHANISM_ABLATIONS = "mechanism-ablation-count"
    REAL_WORLD_CASES = "real-world-case-count"


class VenueEvidenceScaleStatus(StrEnum):
    CURRENT_MISSING = "current-missing"
    BELOW_ACCEPTED_REFERENCE = "below-accepted-reference"
    MEETS_OR_EXCEEDS_REFERENCE = "meets-or-exceeds-reference"


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


class VenueInnovationClaim(BaseModel):
    """One source-compared innovation and the observations that could validate it."""

    model_config = _CONFIG

    claim_id: str
    axis: VenueContributionAxis
    contribution: str = Field(min_length=1, max_length=2_000)
    nearest_neighbour_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    closest_overlap: str = Field(min_length=1, max_length=2_000)
    falsifiable_difference: str = Field(min_length=1, max_length=2_000)
    effect_evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def claim_is_canonical(self) -> VenueInnovationClaim:
        validate_entry_id(self.claim_id, field_name="innovation claim_id")
        if self.nearest_neighbour_ids != tuple(sorted(set(self.nearest_neighbour_ids))):
            raise ValueError("innovation nearest-neighbour IDs must be sorted and unique")
        if self.effect_evidence_ids != tuple(sorted(set(self.effect_evidence_ids))):
            raise ValueError("innovation effect evidence IDs must be sorted and unique")
        return self


class VenueEvidenceScaleFact(BaseModel):
    """One source-interpretable count, never an acceptance threshold by itself."""

    model_config = _CONFIG

    metric: VenueEvidenceScaleMetric
    value: int = Field(ge=0, le=1_000_000_000)
    scope: str = Field(min_length=1, max_length=1_000)
    source_basis: str = Field(min_length=1, max_length=2_000)


class AcceptedNeighbourEvidenceProfile(BaseModel):
    """Structured evidence footprint reported by one accepted neighbour."""

    model_config = _CONFIG

    paper_id: str
    components: tuple[VenueEvidenceComponent, ...] = Field(min_length=1, max_length=20)
    scale_facts: tuple[VenueEvidenceScaleFact, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def profile_is_canonical(self) -> AcceptedNeighbourEvidenceProfile:
        if self.components != tuple(sorted(set(self.components), key=lambda item: item.value)):
            raise ValueError("accepted-neighbour evidence components must be sorted and unique")
        metrics = [item.metric for item in self.scale_facts]
        if metrics != sorted(set(metrics), key=lambda item: item.value):
            raise ValueError("accepted-neighbour scale facts must be metric ordered and unique")
        return self


class CurrentEvidenceComponentBinding(BaseModel):
    """Bind current project evidence to a comparable accepted-paper component."""

    model_config = _CONFIG

    component: VenueEvidenceComponent
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def binding_is_canonical(self) -> CurrentEvidenceComponentBinding:
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("current component evidence IDs must be sorted and unique")
        return self


class VenueClaimEvidenceContract(BaseModel):
    """Evidence obligations for one claim in the paper's argument graph."""

    model_config = _CONFIG

    claim_id: str
    centrality: VenueClaimCentrality
    required_components: tuple[VenueEvidenceComponent, ...] = Field(
        min_length=1, max_length=20
    )
    minimum_independent_families: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def contract_is_canonical(self) -> VenueClaimEvidenceContract:
        validate_entry_id(self.claim_id, field_name="claim-evidence contract claim_id")
        if self.required_components != tuple(
            sorted(set(self.required_components), key=lambda item: item.value)
        ):
            raise ValueError("claim-evidence required components must be sorted and unique")
        return self


class VenueComparisonProfile(BaseModel):
    """Project-owned, source-bound comparison with accepted venue papers."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str
    project_id: str
    venue_gap_manifest_id: str
    target_paper_kind: AcceptedPaperKind = AcceptedPaperKind.METHOD_AND_BENCHMARK
    innovation_claims: tuple[VenueInnovationClaim, ...] = Field(min_length=1, max_length=30)
    accepted_evidence_profiles: tuple[AcceptedNeighbourEvidenceProfile, ...] = Field(
        min_length=2, max_length=30
    )
    current_evidence_components: tuple[CurrentEvidenceComponentBinding, ...] = Field(
        default=(), max_length=30
    )
    current_scale_facts: tuple[VenueEvidenceScaleFact, ...] = Field(default=(), max_length=20)
    claim_evidence_contracts: tuple[VenueClaimEvidenceContract, ...] = Field(
        default=(), max_length=30
    )

    @model_validator(mode="after")
    def profile_is_closed(self) -> VenueComparisonProfile:
        validate_entry_id(self.profile_id, field_name="venue comparison profile_id")
        validate_project_id(self.project_id)
        validate_entry_id(
            self.venue_gap_manifest_id,
            field_name="venue comparison venue_gap_manifest_id",
        )
        claim_ids = [item.claim_id for item in self.innovation_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("venue comparison innovation claim IDs must be unique")
        axes = [item.axis for item in self.innovation_claims]
        if len(axes) != len(set(axes)):
            raise ValueError("venue comparison contribution axes must be unique")
        paper_ids = [item.paper_id for item in self.accepted_evidence_profiles]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("venue comparison accepted paper IDs must be unique")
        components = [item.component for item in self.current_evidence_components]
        if len(components) != len(set(components)):
            raise ValueError("venue comparison current evidence components must be unique")
        scale_metrics = [item.metric for item in self.current_scale_facts]
        if scale_metrics != sorted(set(scale_metrics), key=lambda item: item.value):
            raise ValueError("current scale facts must be metric ordered and unique")
        contract_claim_ids = [item.claim_id for item in self.claim_evidence_contracts]
        if len(contract_claim_ids) != len(set(contract_claim_ids)):
            raise ValueError("venue comparison claim-evidence contracts must be unique")
        if self.claim_evidence_contracts and set(contract_claim_ids) != set(claim_ids):
            raise ValueError(
                "claim-evidence contracts must cover every and only innovation claim"
            )
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
    produces_components: tuple[VenueEvidenceComponent, ...] = Field(default=(), max_length=10)
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
        if self.produces_components != tuple(
            sorted(set(self.produces_components), key=lambda item: item.value)
        ):
            raise ValueError("action evidence components must be sorted and unique")
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
    action_kind: VenueGapActionKind
    priority_rank: int = Field(ge=1)
    deadline_adjusted_utility: float = Field(ge=0.0, allow_inf_nan=False)
    closes_unresolved_dimensions: tuple[VenueGapDimension, ...]
    closes_accepted_components: tuple[VenueEvidenceComponent, ...]
    comparable_accepted_paper_ids: tuple[str, ...]
    fits_before_paper_deadline: bool
    estimated_hours: float = Field(gt=0.0, allow_inf_nan=False)
    reason: str


class VenueEvidenceProgramDecision(BaseModel):
    """Controller decision produced from claims and accepted-paper evidence gaps.

    The decision is intentionally stricter than an assessment: when a central claim is
    contradicted it directs the next scientific action and blocks paper-polish work from
    being mistaken for progress on the evidence program.
    """

    model_config = _CONFIG

    mode: VenueEvidenceProgramMode
    next_action_id: str | None
    paper_polish_is_next_action: bool
    paper_level_claims_authorized: bool
    blocking_central_claim_ids: tuple[str, ...]
    missing_accepted_components: tuple[VenueEvidenceComponent, ...]
    scale_shortfall_metrics: tuple[VenueEvidenceScaleMetric, ...]
    comparison_paper_ids: tuple[str, ...]
    rationale: str


class VenueEvidencePortfolioAssessment(BaseModel):
    """Breadth check against the evidence shape of accepted neighbours.

    Counts are diagnostic rather than acceptance thresholds: one experiment can
    answer several questions, and a large benchmark can still miss the paper's
    central causal claim.  The comparison nevertheless prevents one controlled
    table from being mistaken for a complete top-venue evidence portfolio.
    """

    model_config = _CONFIG

    accepted_neighbour_count: int = Field(ge=2)
    accepted_method_neighbour_count: int = Field(ge=0)
    accepted_benchmark_neighbour_count: int = Field(ge=0)
    accepted_neighbour_reported_component_floor: int = Field(ge=1)
    admitted_empirical_family_count: int = Field(ge=0)
    supporting_empirical_family_count: int = Field(ge=0)
    contradicting_empirical_family_count: int = Field(ge=0)
    development_empirical_family_count: int = Field(ge=0)
    admitted_empirical_dimensions: tuple[VenueGapDimension, ...]
    below_neighbour_reported_component_floor: bool
    diagnosis: str


class VenueInnovationClaimAssessment(BaseModel):
    model_config = _CONFIG

    claim_id: str
    axis: VenueContributionAxis
    contribution: str
    nearest_neighbour_ids: tuple[str, ...]
    closest_overlap: str
    falsifiable_difference: str
    effect_evidence_ids: tuple[str, ...]
    evidence_status: VenueInnovationEvidenceStatus
    diagnosis: str


class VenueEvidenceComponentAssessment(BaseModel):
    model_config = _CONFIG

    component: VenueEvidenceComponent
    accepted_neighbour_ids: tuple[str, ...]
    accepted_neighbour_count: int = Field(ge=0)
    current_evidence_ids: tuple[str, ...]
    current_family_ids: tuple[str, ...]
    current_maturity: VenueComponentMaturity
    current_direction: VenueComponentDirection
    diagnosis: str


class VenueClaimArgumentAssessment(BaseModel):
    """Whether one claim has a complete, independent evidential argument."""

    model_config = _CONFIG

    claim_id: str
    centrality: VenueClaimCentrality
    innovation_status: VenueInnovationEvidenceStatus
    required_components: tuple[VenueEvidenceComponent, ...]
    admitted_supporting_components: tuple[VenueEvidenceComponent, ...]
    missing_or_unadmitted_components: tuple[VenueEvidenceComponent, ...]
    admitted_supporting_family_ids: tuple[str, ...]
    contradicting_family_ids: tuple[str, ...]
    minimum_independent_families: int = Field(ge=1)
    complete_for_review: bool
    diagnosis: str


class VenueEvidenceScaleGapAssessment(BaseModel):
    """Count-level contrast with one accepted neighbour, without quality equivalence."""

    model_config = _CONFIG

    metric: VenueEvidenceScaleMetric
    accepted_value: int = Field(ge=0)
    accepted_scope: str
    accepted_source_basis: str
    current_value: int | None = Field(default=None, ge=0)
    current_scope: str | None = None
    status: VenueEvidenceScaleStatus
    diagnosis: str


class AcceptedNeighbourGapAssessment(BaseModel):
    """Direct evidence-shape comparison with one accepted nearest neighbour.

    This is intentionally a gap record, not a score.  Matching the named
    components of an accepted paper does not establish equal scientific quality,
    while a missing component is a concrete warning against paper-level claims.
    """

    model_config = _CONFIG

    paper_id: str
    paper_kind: AcceptedPaperKind
    accepted_components: tuple[VenueEvidenceComponent, ...]
    current_admitted_supporting_components: tuple[VenueEvidenceComponent, ...]
    current_admitted_contradicting_components: tuple[VenueEvidenceComponent, ...]
    missing_or_unadmitted_components: tuple[VenueEvidenceComponent, ...]
    comparable_supporting_family_ids: tuple[str, ...]
    component_shape_matched: bool
    scale_gaps: tuple[VenueEvidenceScaleGapAssessment, ...]
    scale_reference_matched: bool
    quality_equivalence_claimed: Literal[False] = False
    diagnosis: str


class VenueComparisonAssessment(BaseModel):
    """No-score comparison of novelty claims and complete evidence shape."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str
    profile_sha256: str
    target_paper_kind: AcceptedPaperKind
    innovation_claims: tuple[VenueInnovationClaimAssessment, ...]
    claim_arguments: tuple[VenueClaimArgumentAssessment, ...]
    component_matrix: tuple[VenueEvidenceComponentAssessment, ...]
    accepted_neighbour_gaps: tuple[AcceptedNeighbourGapAssessment, ...]
    accepted_neighbour_count: int = Field(ge=2)
    same_venue_neighbour_count: int = Field(ge=0)
    latest_same_venue_year: int | None = Field(default=None, ge=2000, le=2100)
    same_venue_recency_gap_years: int | None = Field(default=None, ge=0, le=100)
    same_venue_lineage_present: bool
    accepted_component_union_count: int = Field(ge=1)
    accepted_majority_components: tuple[VenueEvidenceComponent, ...]
    accepted_method_majority_components: tuple[VenueEvidenceComponent, ...]
    accepted_benchmark_majority_components: tuple[VenueEvidenceComponent, ...]
    target_required_components: tuple[VenueEvidenceComponent, ...]
    current_admitted_component_count: int = Field(ge=0)
    current_admitted_supporting_component_count: int = Field(ge=0)
    current_admitted_contradicting_component_count: int = Field(ge=0)
    current_admitted_family_count: int = Field(ge=0)
    missing_or_unadmitted_accepted_majority_components: tuple[VenueEvidenceComponent, ...]
    missing_or_unadmitted_target_components: tuple[VenueEvidenceComponent, ...]
    claim_contracts_complete: bool
    central_claim_arguments_complete: bool
    independent_empirical_family_floor: Literal[2] = 2
    evidence_shape_complete_for_review: bool
    one_controlled_family_cannot_establish_venue_competitiveness: Literal[True] = True
    diagnosis: str
    comparison_sha256: str

    @model_validator(mode="after")
    def comparison_hash_is_valid(self) -> VenueComparisonAssessment:
        expected = content_sha256(self.model_dump(mode="json", exclude={"comparison_sha256"}))
        if self.comparison_sha256 != expected:
            raise ValueError("venue comparison assessment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueComparisonAssessment:
        payload = {"schema_version": "1.0", **values}
        payload.pop("comparison_sha256", None)
        unsigned = cls.model_construct(comparison_sha256="0" * 64, **payload)
        return cls(
            **payload,
            comparison_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"comparison_sha256"})
            ),
        )


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
    evidence_portfolio: VenueEvidencePortfolioAssessment
    venue_comparison: VenueComparisonAssessment | None = None
    evidence_program_decision: VenueEvidenceProgramDecision
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
    comparison_profile: VenueComparisonProfile | None = None,
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
    comparison = (
        None
        if comparison_profile is None
        else _assess_venue_comparison(manifest, comparison_profile)
    )
    unresolved = tuple(
        item.dimension
        for item in assessments
        if item.status is not VenueCriterionStatus.SUFFICIENT_FOR_REVIEW
    )
    comparison_contradicted = comparison is not None and any(
        item.evidence_status is VenueInnovationEvidenceStatus.CONTRADICTED
        for item in comparison.innovation_claims
    )
    comparison_unresolved = comparison is not None and any(
        item.evidence_status is not VenueInnovationEvidenceStatus.ADMITTED_SUPPORT
        for item in comparison.innovation_claims
    )
    comparison_shape_incomplete = (
        comparison is not None and not comparison.evidence_shape_complete_for_review
    )
    if (
        any(item.status is VenueCriterionStatus.CONTRADICTED for item in assessments)
        or comparison_contradicted
    ):
        position = SubmissionEvidencePosition.CONTRADICTED
    elif unresolved or comparison_unresolved or comparison_shape_incomplete:
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
    portfolio = _assess_evidence_portfolio(manifest)
    paper_hours = _paper_deadline_hours(deadline)
    ranked = _rank_actions(manifest, assessments, paper_hours, comparison)
    program_decision = _decide_evidence_program(position, comparison, ranked)
    criterion_rejection_reasons = tuple(
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
    )
    comparison_rejection_reasons = (
        ()
        if comparison is None
        else (
            *(
                item.diagnosis
                for item in comparison.innovation_claims
                if item.evidence_status is not VenueInnovationEvidenceStatus.ADMITTED_SUPPORT
            ),
            comparison.diagnosis,
        )
    )
    rejection_reasons = tuple(
        dict.fromkeys((*comparison_rejection_reasons, *criterion_rejection_reasons))
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
        evidence_portfolio=portfolio,
        venue_comparison=comparison,
        evidence_program_decision=program_decision,
        single_result_is_insufficient=True,
        acceptance_prediction_made=False,
        oral_prediction_made=False,
        next_actions=ranked,
        strongest_rejection_reasons=rejection_reasons,
    )


def _assess_venue_comparison(
    manifest: VenueGapManifest,
    profile: VenueComparisonProfile,
) -> VenueComparisonAssessment:
    if profile.project_id != manifest.project_id:
        raise ValueError("venue comparison profile and manifest projects differ")
    if profile.venue_gap_manifest_id != manifest.manifest_id:
        raise ValueError("venue comparison profile targets a different venue-gap manifest")

    known_neighbours = {item.paper_id for item in manifest.nearest_neighbours}
    profiled_neighbours = {item.paper_id for item in profile.accepted_evidence_profiles}
    if profiled_neighbours != known_neighbours:
        raise ValueError("venue comparison must profile every and only accepted manifest neighbour")
    evidence_by_id = {item.evidence_id: item for item in manifest.evidence}
    for claim in profile.innovation_claims:
        if set(claim.nearest_neighbour_ids) - known_neighbours:
            raise ValueError("innovation claim references an unknown accepted neighbour")
        if set(claim.effect_evidence_ids) - set(evidence_by_id):
            raise ValueError("innovation claim references unknown effect evidence")
    for binding in profile.current_evidence_components:
        if set(binding.evidence_ids) - set(evidence_by_id):
            raise ValueError("evidence component references unknown current evidence")

    innovation_claims = tuple(
        _assess_innovation_claim(item, evidence_by_id)
        for item in sorted(profile.innovation_claims, key=lambda item: item.axis.value)
    )
    innovation_by_id = {item.claim_id: item for item in innovation_claims}
    claim_by_id = {item.claim_id: item for item in profile.innovation_claims}
    accepted_by_component: dict[VenueEvidenceComponent, set[str]] = defaultdict(set)
    for neighbour in profile.accepted_evidence_profiles:
        for component in neighbour.components:
            accepted_by_component[component].add(neighbour.paper_id)
    current_by_component = {
        item.component: item.evidence_ids for item in profile.current_evidence_components
    }
    matrix = tuple(
        _assess_evidence_component(
            component,
            accepted_by_component.get(component, set()),
            current_by_component.get(component, ()),
            evidence_by_id,
        )
        for component in sorted(VenueEvidenceComponent, key=lambda item: item.value)
    )
    matrix_by_component = {item.component: item for item in matrix}
    accepted_neighbour_gaps = tuple(
        _assess_accepted_neighbour_gap(
            neighbour,
            neighbour_kind_by_id={
                item.paper_id: item.paper_kind for item in manifest.nearest_neighbours
            },
            matrix_by_component=matrix_by_component,
            current_by_component=current_by_component,
            evidence_by_id=evidence_by_id,
            current_scale_by_metric={
                item.metric: item for item in profile.current_scale_facts
            },
        )
        for neighbour in sorted(
            profile.accepted_evidence_profiles,
            key=lambda item: item.paper_id,
        )
    )
    neighbour_count = len(profile.accepted_evidence_profiles)
    accepted_union = {
        component for component, paper_ids in accepted_by_component.items() if paper_ids
    }
    accepted_majority = tuple(
        component
        for component in sorted(accepted_union, key=lambda item: item.value)
        if len(accepted_by_component[component]) * 2 > neighbour_count
    )
    neighbour_kind_by_id = {item.paper_id: item.paper_kind for item in manifest.nearest_neighbours}
    target_series = _venue_series(manifest.target_venue)
    same_venue_neighbours = tuple(
        item
        for item in manifest.nearest_neighbours
        if _venue_series(item.venue) == target_series
    )
    latest_same_venue_year = (
        None if not same_venue_neighbours else max(item.year for item in same_venue_neighbours)
    )
    target_year = _venue_year(manifest.target_venue)
    same_venue_recency_gap = (
        None
        if target_year is None or latest_same_venue_year is None
        else max(0, target_year - latest_same_venue_year)
    )
    same_venue_lineage_present = (
        len(same_venue_neighbours) >= 2
        and (same_venue_recency_gap is None or same_venue_recency_gap <= 2)
    )
    method_neighbour_ids = {
        paper_id
        for paper_id, kind in neighbour_kind_by_id.items()
        if kind in {AcceptedPaperKind.METHOD, AcceptedPaperKind.METHOD_AND_BENCHMARK}
    }
    benchmark_neighbour_ids = {
        paper_id
        for paper_id, kind in neighbour_kind_by_id.items()
        if kind in {AcceptedPaperKind.BENCHMARK, AcceptedPaperKind.METHOD_AND_BENCHMARK}
    }
    accepted_method_majority = _majority_components(
        accepted_by_component,
        method_neighbour_ids,
    )
    accepted_benchmark_majority = _majority_components(
        accepted_by_component,
        benchmark_neighbour_ids,
    )
    target_required = set(accepted_majority)
    if profile.target_paper_kind in {
        AcceptedPaperKind.METHOD,
        AcceptedPaperKind.METHOD_AND_BENCHMARK,
    }:
        target_required.update(accepted_method_majority)
    if profile.target_paper_kind in {
        AcceptedPaperKind.BENCHMARK,
        AcceptedPaperKind.METHOD_AND_BENCHMARK,
    }:
        target_required.update(accepted_benchmark_majority)
    target_required_components = tuple(sorted(target_required, key=lambda item: item.value))
    missing_majority = tuple(
        item.component
        for item in matrix
        if item.component in accepted_majority
        and item.current_maturity is not VenueComponentMaturity.ADMITTED
    )
    missing_target = tuple(
        item.component
        for item in matrix
        if item.component in target_required
        and item.current_maturity is not VenueComponentMaturity.ADMITTED
    )
    admitted_components = tuple(
        item for item in matrix if item.current_maturity is VenueComponentMaturity.ADMITTED
    )
    admitted_family_ids = {
        evidence_by_id[evidence_id].family_id
        for item in admitted_components
        for evidence_id in item.current_evidence_ids
        if evidence_by_id[evidence_id].maturity is EvidenceMaturity.ADMITTED
    }
    supporting_count = sum(
        item.current_direction
        in {VenueComponentDirection.SUPPORTING, VenueComponentDirection.MIXED}
        for item in admitted_components
    )
    contradicting_count = sum(
        item.current_direction
        in {VenueComponentDirection.CONTRADICTING, VenueComponentDirection.MIXED}
        for item in admitted_components
    )
    contradicted_innovations = sum(
        item.evidence_status is VenueInnovationEvidenceStatus.CONTRADICTED
        for item in innovation_claims
    )
    claim_arguments = tuple(
        _assess_claim_argument(
            contract,
            claim_by_id[contract.claim_id],
            innovation_by_id[contract.claim_id],
            current_by_component,
            evidence_by_id,
        )
        for contract in sorted(profile.claim_evidence_contracts, key=lambda item: item.claim_id)
    )
    claim_contracts_complete = bool(profile.claim_evidence_contracts)
    central_claims = tuple(
        item for item in claim_arguments if item.centrality is VenueClaimCentrality.CENTRAL
    )
    central_claim_arguments_complete = (
        claim_contracts_complete
        and bool(central_claims)
        and all(item.complete_for_review for item in central_claims)
    )
    evidence_shape_complete = (
        not contradicted_innovations
        and contradicting_count == 0
        and len(admitted_family_ids) >= 2
        and not missing_target
        and central_claim_arguments_complete
        and same_venue_lineage_present
    )
    if contradicted_innovations:
        diagnosis = (
            f"{contradicted_innovations} declared innovation claim(s) are contradicted by "
            "admitted evidence. Evidence breadth cannot compensate for a failed central mechanism."
        )
    elif not claim_contracts_complete:
        diagnosis = (
            "The comparison profile has no complete claim-evidence argument graph. Component "
            "counts and result tables cannot establish which central claim each study closes."
        )
    elif not central_claim_arguments_complete:
        incomplete = [
            item.claim_id
            for item in central_claims
            if not item.complete_for_review
        ]
        diagnosis = (
            "Central claim arguments remain incomplete: " + ", ".join(incomplete) + ". "
            "A favorable local table cannot substitute for every evidence obligation of the "
            "paper's central argument."
        )
    elif len(admitted_family_ids) <= 1:
        diagnosis = (
            "The current admitted evidence components originate from at most one empirical "
            "family. Accepted neighbours combine multiple independent components, so a single "
            "controlled result cannot establish venue competitiveness."
        )
    elif not same_venue_lineage_present:
        diagnosis = (
            "The comparison set does not contain at least two recent accepted papers from "
            "the target venue series. Cross-venue analogies cannot replace a current "
            "same-venue evidence standard."
        )
    elif missing_target:
        diagnosis = (
            "The current portfolio lacks admitted evidence required by accepted papers of the "
            f"same contribution type ({profile.target_paper_kind.value}): "
            + ", ".join(item.value for item in missing_target)
            + "."
        )
    else:
        diagnosis = (
            "The evidence shape is comparable at the component level; claim direction, novelty, "
            "independence, and scientific importance remain separate reviewer judgments."
        )
    return VenueComparisonAssessment.create(
        profile_id=profile.profile_id,
        profile_sha256=content_sha256(profile.model_dump(mode="json")),
        target_paper_kind=profile.target_paper_kind,
        innovation_claims=innovation_claims,
        claim_arguments=claim_arguments,
        component_matrix=matrix,
        accepted_neighbour_gaps=accepted_neighbour_gaps,
        accepted_neighbour_count=neighbour_count,
        same_venue_neighbour_count=len(same_venue_neighbours),
        latest_same_venue_year=latest_same_venue_year,
        same_venue_recency_gap_years=same_venue_recency_gap,
        same_venue_lineage_present=same_venue_lineage_present,
        accepted_component_union_count=len(accepted_union),
        accepted_majority_components=accepted_majority,
        accepted_method_majority_components=accepted_method_majority,
        accepted_benchmark_majority_components=accepted_benchmark_majority,
        target_required_components=target_required_components,
        current_admitted_component_count=len(admitted_components),
        current_admitted_supporting_component_count=supporting_count,
        current_admitted_contradicting_component_count=contradicting_count,
        current_admitted_family_count=len(admitted_family_ids),
        missing_or_unadmitted_accepted_majority_components=missing_majority,
        missing_or_unadmitted_target_components=missing_target,
        claim_contracts_complete=claim_contracts_complete,
        central_claim_arguments_complete=central_claim_arguments_complete,
        independent_empirical_family_floor=2,
        evidence_shape_complete_for_review=evidence_shape_complete,
        one_controlled_family_cannot_establish_venue_competitiveness=True,
        diagnosis=diagnosis,
    )


def _assess_accepted_neighbour_gap(
    profile: AcceptedNeighbourEvidenceProfile,
    *,
    neighbour_kind_by_id: dict[str, AcceptedPaperKind],
    matrix_by_component: dict[VenueEvidenceComponent, VenueEvidenceComponentAssessment],
    current_by_component: dict[VenueEvidenceComponent, tuple[str, ...]],
    evidence_by_id: dict[str, VenueEvidenceSignal],
    current_scale_by_metric: dict[VenueEvidenceScaleMetric, VenueEvidenceScaleFact],
) -> AcceptedNeighbourGapAssessment:
    """Expose what the current paper lacks relative to one accepted paper."""

    accepted = tuple(sorted(profile.components, key=lambda item: item.value))
    supporting: list[VenueEvidenceComponent] = []
    contradicting: list[VenueEvidenceComponent] = []
    missing: list[VenueEvidenceComponent] = []
    supporting_families: set[str] = set()
    for component in accepted:
        assessed = matrix_by_component[component]
        if assessed.current_maturity is not VenueComponentMaturity.ADMITTED:
            missing.append(component)
            continue
        if assessed.current_direction in {
            VenueComponentDirection.CONTRADICTING,
            VenueComponentDirection.MIXED,
        }:
            contradicting.append(component)
        if assessed.current_direction is VenueComponentDirection.SUPPORTING:
            supporting.append(component)
            supporting_families.update(
                evidence_by_id[evidence_id].family_id
                for evidence_id in current_by_component.get(component, ())
                if evidence_by_id[evidence_id].maturity is EvidenceMaturity.ADMITTED
                and evidence_by_id[evidence_id].headline_eligible
                and evidence_by_id[evidence_id].direction is EvidenceDirection.SUPPORTING
            )
    component_shape_matched = (
        not missing and not contradicting and len(supporting_families) >= 2
    )
    scale_gaps = tuple(
        _assess_evidence_scale_gap(item, current_scale_by_metric.get(item.metric))
        for item in profile.scale_facts
    )
    scale_reference_matched = bool(scale_gaps) and all(
        item.status is VenueEvidenceScaleStatus.MEETS_OR_EXCEEDS_REFERENCE
        for item in scale_gaps
    )
    if missing:
        diagnosis = (
            "Relative to this accepted paper, the current project lacks admitted evidence "
            "for: " + ", ".join(item.value for item in missing) + "."
        )
    elif contradicting:
        diagnosis = (
            "The current evidence includes an admitted contradiction in components also used "
            "by this accepted paper: "
            + ", ".join(item.value for item in contradicting)
            + "."
        )
    elif len(supporting_families) < 2:
        diagnosis = (
            "Comparable components come from fewer than two independent supporting empirical "
            "families; one controlled result is not an accepted-paper evidence portfolio."
        )
    else:
        diagnosis = (
            "Named evidence components are present across independent families. This matches "
            "only the evidence shape and does not claim equal novelty, rigor, scale, or quality."
        )
    return AcceptedNeighbourGapAssessment(
        paper_id=profile.paper_id,
        paper_kind=neighbour_kind_by_id[profile.paper_id],
        accepted_components=accepted,
        current_admitted_supporting_components=tuple(supporting),
        current_admitted_contradicting_components=tuple(contradicting),
        missing_or_unadmitted_components=tuple(missing),
        comparable_supporting_family_ids=tuple(sorted(supporting_families)),
        component_shape_matched=component_shape_matched,
        scale_gaps=scale_gaps,
        scale_reference_matched=scale_reference_matched,
        quality_equivalence_claimed=False,
        diagnosis=diagnosis,
    )


def _assess_evidence_scale_gap(
    accepted: VenueEvidenceScaleFact,
    current: VenueEvidenceScaleFact | None,
) -> VenueEvidenceScaleGapAssessment:
    if current is None:
        return VenueEvidenceScaleGapAssessment(
            metric=accepted.metric,
            accepted_value=accepted.value,
            accepted_scope=accepted.scope,
            accepted_source_basis=accepted.source_basis,
            current_value=None,
            current_scope=None,
            status=VenueEvidenceScaleStatus.CURRENT_MISSING,
            diagnosis=(
                f"The accepted paper reports {accepted.value} for {accepted.metric.value}; "
                "the current project has no comparable registered count."
            ),
        )
    meets = current.value >= accepted.value
    return VenueEvidenceScaleGapAssessment(
        metric=accepted.metric,
        accepted_value=accepted.value,
        accepted_scope=accepted.scope,
        accepted_source_basis=accepted.source_basis,
        current_value=current.value,
        current_scope=current.scope,
        status=(
            VenueEvidenceScaleStatus.MEETS_OR_EXCEEDS_REFERENCE
            if meets
            else VenueEvidenceScaleStatus.BELOW_ACCEPTED_REFERENCE
        ),
        diagnosis=(
            f"The current registered count ({current.value}) "
            + ("meets or exceeds" if meets else "is below")
            + f" this accepted-paper reference ({accepted.value}) for "
            f"{accepted.metric.value}. Scope still differs: current={current.scope}; "
            f"accepted={accepted.scope}. Count parity never establishes quality equivalence."
        ),
    )


def _venue_series(value: str) -> str:
    """Normalize a venue name while removing a four-digit edition year."""

    return " ".join(re.sub(r"\b(?:19|20)\d{2}\b", " ", value.casefold()).split())


def _venue_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return None if match is None else int(match.group(1))


def _majority_components(
    accepted_by_component: dict[VenueEvidenceComponent, set[str]],
    neighbour_ids: set[str],
) -> tuple[VenueEvidenceComponent, ...]:
    """Return components reported by a strict majority of one paper-kind cohort."""

    if not neighbour_ids:
        return ()
    return tuple(
        component
        for component in sorted(VenueEvidenceComponent, key=lambda item: item.value)
        if len(accepted_by_component.get(component, set()) & neighbour_ids) * 2
        > len(neighbour_ids)
    )


def _assess_claim_argument(
    contract: VenueClaimEvidenceContract,
    claim: VenueInnovationClaim,
    innovation: VenueInnovationClaimAssessment,
    current_by_component: dict[VenueEvidenceComponent, tuple[str, ...]],
    evidence_by_id: dict[str, VenueEvidenceSignal],
) -> VenueClaimArgumentAssessment:
    """Require claim-linked evidence rather than crediting a paper-wide table count."""

    claim_evidence_ids = set(claim.effect_evidence_ids)
    admitted_components: list[VenueEvidenceComponent] = []
    supporting_families: set[str] = set()
    contradicting_families = {
        evidence_by_id[evidence_id].family_id
        for evidence_id in claim.effect_evidence_ids
        if evidence_by_id[evidence_id].maturity is EvidenceMaturity.ADMITTED
        and evidence_by_id[evidence_id].direction is EvidenceDirection.CONTRADICTING
    }
    for component in contract.required_components:
        linked = claim_evidence_ids & set(current_by_component.get(component, ()))
        support = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in linked
            if evidence_by_id[evidence_id].maturity is EvidenceMaturity.ADMITTED
            and evidence_by_id[evidence_id].headline_eligible
            and evidence_by_id[evidence_id].direction is EvidenceDirection.SUPPORTING
        )
        if support:
            admitted_components.append(component)
            supporting_families.update(item.family_id for item in support)
    admitted_tuple = tuple(sorted(admitted_components, key=lambda item: item.value))
    missing = tuple(
        item for item in contract.required_components if item not in set(admitted_tuple)
    )
    complete = (
        innovation.evidence_status is VenueInnovationEvidenceStatus.ADMITTED_SUPPORT
        and not contradicting_families
        and not missing
        and len(supporting_families) >= contract.minimum_independent_families
    )
    if innovation.evidence_status is VenueInnovationEvidenceStatus.CONTRADICTED:
        diagnosis = f"{claim.claim_id}: admitted evidence contradicts the claim."
    elif missing:
        diagnosis = (
            f"{claim.claim_id}: missing claim-linked admitted components: "
            + ", ".join(item.value for item in missing)
            + "."
        )
    elif len(supporting_families) < contract.minimum_independent_families:
        diagnosis = (
            f"{claim.claim_id}: {len(supporting_families)} independent admitted supporting "
            f"family/families do not meet the contract floor of "
            f"{contract.minimum_independent_families}."
        )
    elif contradicting_families:
        diagnosis = f"{claim.claim_id}: admitted contradictory evidence remains unresolved."
    else:
        diagnosis = (
            f"{claim.claim_id}: the declared claim-level evidence obligations are covered; "
            "this is not an acceptance judgment."
        )
    return VenueClaimArgumentAssessment(
        claim_id=claim.claim_id,
        centrality=contract.centrality,
        innovation_status=innovation.evidence_status,
        required_components=contract.required_components,
        admitted_supporting_components=admitted_tuple,
        missing_or_unadmitted_components=missing,
        admitted_supporting_family_ids=tuple(sorted(supporting_families)),
        contradicting_family_ids=tuple(sorted(contradicting_families)),
        minimum_independent_families=contract.minimum_independent_families,
        complete_for_review=complete,
        diagnosis=diagnosis,
    )


def _assess_innovation_claim(
    claim: VenueInnovationClaim,
    evidence_by_id: dict[str, VenueEvidenceSignal],
) -> VenueInnovationClaimAssessment:
    evidence = tuple(evidence_by_id[item] for item in claim.effect_evidence_ids)
    admitted_support = tuple(
        item
        for item in evidence
        if item.maturity is EvidenceMaturity.ADMITTED
        and item.headline_eligible
        and item.direction is EvidenceDirection.SUPPORTING
    )
    admitted_contradictions = tuple(
        item
        for item in evidence
        if item.maturity is EvidenceMaturity.ADMITTED
        and item.direction is EvidenceDirection.CONTRADICTING
    )
    if admitted_contradictions:
        status = VenueInnovationEvidenceStatus.CONTRADICTED
        diagnosis = (
            f"{claim.axis.value}: the distinction is source-compared, but admitted evidence "
            "contradicts its claimed effect."
        )
    elif admitted_support:
        status = VenueInnovationEvidenceStatus.ADMITTED_SUPPORT
        diagnosis = (
            f"{claim.axis.value}: the source-compared distinction has admitted effect evidence; "
            "this is not an acceptance judgment."
        )
    elif evidence:
        status = VenueInnovationEvidenceStatus.DEVELOPMENT_ONLY
        diagnosis = (
            f"{claim.axis.value}: the proposed distinction has only development or non-headline "
            "effect evidence."
        )
    else:
        status = VenueInnovationEvidenceStatus.PROPOSED_ONLY
        diagnosis = (
            f"{claim.axis.value}: the proposed distinction is not yet linked to observed effect "
            "evidence."
        )
    return VenueInnovationClaimAssessment(
        claim_id=claim.claim_id,
        axis=claim.axis,
        contribution=claim.contribution,
        nearest_neighbour_ids=claim.nearest_neighbour_ids,
        closest_overlap=claim.closest_overlap,
        falsifiable_difference=claim.falsifiable_difference,
        effect_evidence_ids=claim.effect_evidence_ids,
        evidence_status=status,
        diagnosis=diagnosis,
    )


def _assess_evidence_component(
    component: VenueEvidenceComponent,
    accepted_neighbour_ids: set[str],
    current_evidence_ids: tuple[str, ...],
    evidence_by_id: dict[str, VenueEvidenceSignal],
) -> VenueEvidenceComponentAssessment:
    evidence = tuple(evidence_by_id[item] for item in current_evidence_ids)
    admitted = tuple(
        item
        for item in evidence
        if item.maturity is EvidenceMaturity.ADMITTED
    )
    if admitted:
        maturity = VenueComponentMaturity.ADMITTED
    elif evidence:
        maturity = VenueComponentMaturity.DEVELOPMENT_ONLY
    else:
        maturity = VenueComponentMaturity.MISSING
    directions = {item.direction for item in admitted}
    if directions == {EvidenceDirection.SUPPORTING}:
        direction = VenueComponentDirection.SUPPORTING
    elif directions == {EvidenceDirection.CONTRADICTING}:
        direction = VenueComponentDirection.CONTRADICTING
    elif directions:
        direction = VenueComponentDirection.MIXED
    else:
        direction = VenueComponentDirection.NONE
    accepted_ids = tuple(sorted(accepted_neighbour_ids))
    if maturity is VenueComponentMaturity.MISSING:
        diagnosis = (
            f"{component.value}: present in {len(accepted_ids)} accepted neighbour(s), absent "
            "from the current evidence portfolio."
        )
    elif maturity is VenueComponentMaturity.DEVELOPMENT_ONLY:
        diagnosis = (
            f"{component.value}: current evidence is development-only; accepted-neighbour "
            "coverage does not make it headline evidence."
        )
    else:
        diagnosis = (
            f"{component.value}: admitted current evidence is present with {direction.value} "
            "direction relative to the paper claim."
        )
    return VenueEvidenceComponentAssessment(
        component=component,
        accepted_neighbour_ids=accepted_ids,
        accepted_neighbour_count=len(accepted_ids),
        current_evidence_ids=current_evidence_ids,
        current_family_ids=tuple(sorted({item.family_id for item in evidence})),
        current_maturity=maturity,
        current_direction=direction,
        diagnosis=diagnosis,
    )


def _assess_evidence_portfolio(
    manifest: VenueGapManifest,
) -> VenueEvidencePortfolioAssessment:
    empirical_dimensions = {
        item
        for item in VenueGapDimension
        if item
        not in {
            VenueGapDimension.INNOVATION,
            VenueGapDimension.NARRATIVE_CONTRIBUTION,
        }
    }
    empirical = tuple(
        item
        for item in manifest.evidence
        if item.dimension in empirical_dimensions and (item.objective_measurement or item.held_out)
    )
    admitted = tuple(
        item
        for item in empirical
        if item.maturity is EvidenceMaturity.ADMITTED
    )
    supporting_families = {
        item.family_id
        for item in admitted
        if item.direction is EvidenceDirection.SUPPORTING and item.headline_eligible
    }
    contradicting_families = {
        item.family_id for item in admitted if item.direction is EvidenceDirection.CONTRADICTING
    }
    admitted_families = {item.family_id for item in admitted}
    development_families = {
        item.family_id for item in empirical if item.maturity is EvidenceMaturity.DEVELOPMENT_ONLY
    }
    component_floor = min(len(item.reported_evidence) for item in manifest.nearest_neighbours)
    below_floor = len(admitted_families) < component_floor
    if not admitted_families:
        diagnosis = (
            "No held-out or objective empirical evidence family is admitted; prose, "
            "tests, and development tables cannot establish top-venue readiness."
        )
    elif contradicting_families and not supporting_families:
        diagnosis = (
            "The only admitted empirical portfolio is contradicting; additional tables "
            "cannot repair the central claim without a changed mechanism and new population."
        )
    elif below_floor:
        diagnosis = (
            "The admitted empirical portfolio is narrower than every accepted-neighbour "
            "evidence summary; one controlled family is not a complete paper argument."
        )
    else:
        diagnosis = (
            "Empirical breadth reaches the accepted-neighbour component floor, but claim "
            "validity, effect direction, and reviewer dimensions remain separately binding."
        )
    method_kinds = {AcceptedPaperKind.METHOD, AcceptedPaperKind.METHOD_AND_BENCHMARK}
    benchmark_kinds = {
        AcceptedPaperKind.BENCHMARK,
        AcceptedPaperKind.METHOD_AND_BENCHMARK,
    }
    return VenueEvidencePortfolioAssessment(
        accepted_neighbour_count=len(manifest.nearest_neighbours),
        accepted_method_neighbour_count=sum(
            item.paper_kind in method_kinds for item in manifest.nearest_neighbours
        ),
        accepted_benchmark_neighbour_count=sum(
            item.paper_kind in benchmark_kinds for item in manifest.nearest_neighbours
        ),
        accepted_neighbour_reported_component_floor=component_floor,
        admitted_empirical_family_count=len(admitted_families),
        supporting_empirical_family_count=len(supporting_families),
        contradicting_empirical_family_count=len(contradicting_families),
        development_empirical_family_count=len(development_families),
        admitted_empirical_dimensions=tuple(
            sorted({item.dimension for item in admitted}, key=lambda item: item.value)
        ),
        below_neighbour_reported_component_floor=below_floor,
        diagnosis=diagnosis,
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
        item for item in related if item.maturity is EvidenceMaturity.DEVELOPMENT_ONLY
    )
    contradictions = tuple(
        item
        for item in related
        if item.direction is EvidenceDirection.CONTRADICTING
        and item.maturity is EvidenceMaturity.ADMITTED
    )
    development_contradictions = tuple(
        item for item in development if item.direction is EvidenceDirection.CONTRADICTING
    )
    covered_types = {item.evidence_type for item in admitted_support}
    missing_types = tuple(
        item for item in criterion.required_evidence_types if item not in covered_types
    )
    neighbour_gap = criterion.dimension is VenueGapDimension.INNOVATION and not (
        set(criterion.nearest_neighbour_ids) & known_neighbours
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
    comparison: VenueComparisonAssessment | None,
) -> tuple[RankedVenueGapAction, ...]:
    criterion_by_dimension = {item.dimension: item for item in manifest.criteria}
    unresolved = {
        item.dimension: item
        for item in assessments
        if item.status is not VenueCriterionStatus.SUFFICIENT_FOR_REVIEW
    }
    missing_accepted_components = (
        set()
        if comparison is None
        else set(comparison.missing_or_unadmitted_target_components)
        | set(comparison.missing_or_unadmitted_accepted_majority_components)
    )
    accepted_papers_by_component: dict[VenueEvidenceComponent, set[str]] = defaultdict(set)
    if comparison is not None:
        for neighbour in comparison.accepted_neighbour_gaps:
            for component in neighbour.missing_or_unadmitted_components:
                accepted_papers_by_component[component].add(neighbour.paper_id)
    candidates: list[
        tuple[
            VenueGapAction,
            tuple[VenueGapDimension, ...],
            tuple[VenueEvidenceComponent, ...],
            tuple[str, ...],
            float,
            bool,
        ]
    ] = []
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
        closes_components = tuple(
            item for item in action.produces_components if item in missing_accepted_components
        )
        comparable_papers = tuple(
            sorted(
                {
                    paper_id
                    for component in closes_components
                    for paper_id in accepted_papers_by_component[component]
                }
            )
        )
        if closes_components:
            # A modest multiplier makes the accepted-paper comparison operational while
            # preserving scientific importance, rejection risk, cost, and feasibility.
            utility *= 1.0 + min(0.5, 0.1 * len(closes_components))
        if empirical_core_is_open and action.kind in {
            VenueGapActionKind.WRITING,
            VenueGapActionKind.LITERATURE,
        }:
            utility *= 0.1
        fits = paper_deadline_hours is None or action.estimated_hours <= paper_deadline_hours
        if not fits:
            utility *= 0.05
        candidates.append(
            (action, closes, closes_components, comparable_papers, utility, fits)
        )
    candidates.sort(key=lambda item: (-item[4], item[0].action_id))
    return tuple(
        RankedVenueGapAction(
            action_id=action.action_id,
            action_kind=action.kind,
            priority_rank=index,
            deadline_adjusted_utility=round(utility, 8),
            closes_unresolved_dimensions=closes,
            closes_accepted_components=closes_components,
            comparable_accepted_paper_ids=comparable_papers,
            fits_before_paper_deadline=fits,
            estimated_hours=action.estimated_hours,
            reason=(
                "closes reviewer-critical dimensions and accepted-paper evidence components "
                "under the remaining deadline"
                if closes_components and fits
                else "highest deadline-adjusted breadth and importance of unresolved claim closure"
                if fits
                else "scientifically relevant but does not fit before the paper deadline"
            ),
        )
        for index, (
            action,
            closes,
            closes_components,
            comparable_papers,
            utility,
            fits,
        ) in enumerate(candidates, start=1)
    )


def _decide_evidence_program(
    position: SubmissionEvidencePosition,
    comparison: VenueComparisonAssessment | None,
    ranked: tuple[RankedVenueGapAction, ...],
) -> VenueEvidenceProgramDecision:
    blocking_claims = (
        ()
        if comparison is None
        else tuple(
            item.claim_id
            for item in comparison.claim_arguments
            if item.centrality is VenueClaimCentrality.CENTRAL and not item.complete_for_review
        )
    )
    missing_components = (
        ()
        if comparison is None
        else tuple(
            sorted(
                set(comparison.missing_or_unadmitted_target_components)
                | set(comparison.missing_or_unadmitted_accepted_majority_components),
                key=lambda item: item.value,
            )
        )
    )
    scale_shortfalls = (
        ()
        if comparison is None
        else tuple(
            sorted(
                {
                    gap.metric
                    for neighbour in comparison.accepted_neighbour_gaps
                    for gap in neighbour.scale_gaps
                    if gap.status is not VenueEvidenceScaleStatus.MEETS_OR_EXCEEDS_REFERENCE
                },
                key=lambda item: item.value,
            )
        )
    )
    comparison_papers = (
        ()
        if comparison is None
        else tuple(item.paper_id for item in comparison.accepted_neighbour_gaps)
    )
    next_action = next((item for item in ranked if item.fits_before_paper_deadline), None)
    if position is SubmissionEvidencePosition.CONTRADICTED:
        mode = VenueEvidenceProgramMode.REPAIR_CONTRADICTED_CORE
        rationale = (
            "Admitted evidence contradicts at least one core claim. Execute the highest-value "
            "mechanism or causal experiment before broadening evaluation or polishing prose."
        )
    elif (
        comparison is None
        or position is not SubmissionEvidencePosition.EVIDENCE_PROGRAM_COMPLETE_FOR_REVIEW
        or not comparison.evidence_shape_complete_for_review
    ):
        mode = VenueEvidenceProgramMode.BUILD_ACCEPTED_COMPARABLE_PORTFOLIO
        rationale = (
            "No accepted-paper comparison profile is attached; paper-level claims remain "
            "unauthorized until a source-bound comparison is compiled."
            if comparison is None
            else "The current evidence shape is narrower than accepted nearest neighbours. "
            "Execute the next ranked action that closes reviewer-critical and "
            "paper-comparable gaps."
        )
    else:
        mode = VenueEvidenceProgramMode.COMPLETE_FOR_REVIEW
        rationale = (
            "The declared evidence program is complete for review; this authorizes paper-level "
            "synthesis but does not predict acceptance or oral selection."
        )
    authorized = mode is VenueEvidenceProgramMode.COMPLETE_FOR_REVIEW
    return VenueEvidenceProgramDecision(
        mode=mode,
        next_action_id=None if next_action is None else next_action.action_id,
        paper_polish_is_next_action=(
            authorized
            and next_action is not None
            and next_action.action_kind is VenueGapActionKind.WRITING
        ),
        paper_level_claims_authorized=authorized,
        blocking_central_claim_ids=blocking_claims,
        missing_accepted_components=missing_components,
        scale_shortfall_metrics=scale_shortfalls,
        comparison_paper_ids=comparison_papers,
        rationale=rationale,
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


def load_venue_comparison_profile(path: str | Path) -> VenueComparisonProfile:
    source = _bounded_regular_file(path, maximum_bytes=_MAX_MANIFEST_BYTES)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return VenueComparisonProfile.model_validate(payload)


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
    "AcceptedNeighbourEvidenceProfile",
    "AcceptedNeighbourGapAssessment",
    "AcceptedPaperKind",
    "CurrentEvidenceComponentBinding",
    "EvidenceDirection",
    "EvidenceMaturity",
    "RankedVenueGapAction",
    "SubmissionEvidencePosition",
    "VenueClaimArgumentAssessment",
    "VenueClaimCentrality",
    "VenueClaimEvidenceContract",
    "VenueComparisonAssessment",
    "VenueComparisonProfile",
    "VenueComponentDirection",
    "VenueComponentMaturity",
    "VenueContributionAxis",
    "VenueCriterionAssessment",
    "VenueCriterionStatus",
    "VenueEvidenceComponent",
    "VenueEvidenceComponentAssessment",
    "VenueEvidenceCriterion",
    "VenueEvidencePortfolioAssessment",
    "VenueEvidenceProgramDecision",
    "VenueEvidenceProgramMode",
    "VenueEvidenceScaleFact",
    "VenueEvidenceScaleGapAssessment",
    "VenueEvidenceScaleMetric",
    "VenueEvidenceScaleStatus",
    "VenueEvidenceSignal",
    "VenueGapAction",
    "VenueGapActionKind",
    "VenueGapAssessment",
    "VenueGapDimension",
    "VenueGapManifest",
    "VenueInnovationClaim",
    "VenueInnovationClaimAssessment",
    "VenueInnovationEvidenceStatus",
    "assess_venue_gap",
    "load_venue_comparison_profile",
    "load_venue_gap_manifest",
    "save_venue_gap_assessment",
]
