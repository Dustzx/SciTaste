"""Strict input and proposal schemas for the first bounded model nodes."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evidence.interpretation import InterpretationContext, ResultRecord
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.review import ConcernCategory, ConcernSeverity


class ReviewSemanticInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_text: str = Field(min_length=1)
    permitted_evidence_types: list[str] = Field(default_factory=list)

    @field_validator("permitted_evidence_types")
    @classmethod
    def evidence_types_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("permitted evidence types must be unique")
        return sorted(values)


class ReviewConcernProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concern_id: str = Field(min_length=1)
    category: ConcernCategory
    severity: ConcernSeverity
    target_claim_ids: list[str] = Field(default_factory=list)
    target_section: str | None = None
    text: str = Field(min_length=1)
    requires_new_evidence: bool = False
    requires_new_experiment: bool = False
    required_evidence_types: list[str] = Field(default_factory=list)
    proposed_action_type: MetaAction

    @model_validator(mode="after")
    def experiment_implies_evidence(self) -> ReviewConcernProposal:
        if self.requires_new_experiment and not self.requires_new_evidence:
            raise ValueError("a proposed experiment must also require new evidence")
        if self.required_evidence_types and not self.requires_new_evidence:
            raise ValueError("required evidence types require requires_new_evidence=true")
        return self


class ReviewSemanticOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concerns: list[ReviewConcernProposal] = Field(min_length=1)
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def concern_ids_are_unique(self) -> ReviewSemanticOutput:
        concern_ids = [item.concern_id for item in self.concerns]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("proposed concern ids must be unique")
        return self


_ICLR_REVIEW_CRITERIA = (
    "specific_question",
    "motivation_and_literature",
    "claim_support_and_rigor",
    "significance_and_community_value",
)


class VenuePaperReviewInput(BaseModel):
    """Exact paper text supplied to a proposal-only venue reviewer node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_text: str = Field(min_length=1, max_length=800_000)
    paper_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    venue_id: str = Field(min_length=1, max_length=100)
    registered_claim_ids: tuple[str, ...] = Field(default=(), max_length=128)
    permitted_evidence_types: tuple[str, ...] = Field(default=(), max_length=40)
    criteria: tuple[str, ...] = _ICLR_REVIEW_CRITERIA

    @model_validator(mode="after")
    def input_is_content_bound(self) -> VenuePaperReviewInput:
        if hashlib.sha256(self.paper_text.encode()).hexdigest() != self.paper_text_sha256:
            raise ValueError("paper_text_sha256 does not match paper_text")
        if self.criteria != _ICLR_REVIEW_CRITERIA:
            raise ValueError("venue paper review must preserve the four ICLR questions")
        for values, label in (
            (self.registered_claim_ids, "registered claim"),
            (self.permitted_evidence_types, "permitted evidence type"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} values must be sorted and unique")
        return self


class VenueReviewCriterionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Literal[
        "specific_question",
        "motivation_and_literature",
        "claim_support_and_rigor",
        "significance_and_community_value",
    ]
    assessment: Literal["satisfied", "partially_satisfied", "not_satisfied", "uncertain"]
    rationale: str = Field(min_length=1, max_length=16_000)


class VenuePaperReviewProposal(BaseModel):
    """Untrusted model content; deterministic code adds reviewer identity and hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str = Field(min_length=1, max_length=16_000)
    strengths: tuple[str, ...] = Field(min_length=1, max_length=20)
    weaknesses: tuple[str, ...] = Field(default=(), max_length=20)
    criteria: tuple[VenueReviewCriterionProposal, ...] = Field(min_length=4, max_length=4)
    initial_recommendation: Literal["accept", "reject"]
    decision_reasons: tuple[str, ...] = Field(min_length=1, max_length=2)
    questions: tuple[str, ...] = Field(default=(), max_length=20)
    additional_feedback: tuple[str, ...] = Field(default=(), max_length=20)
    concerns: tuple[ReviewConcernProposal, ...] = Field(default=(), max_length=40)
    confidence: Literal["low", "medium", "high"]
    ethics_concern: Literal["none", "potential"] = "none"
    ethics_explanation: str | None = Field(default=None, max_length=16_000)

    @model_validator(mode="after")
    def proposal_is_complete(self) -> VenuePaperReviewProposal:
        if tuple(item.criterion for item in self.criteria) != _ICLR_REVIEW_CRITERIA:
            raise ValueError("venue review proposal must assess all four questions in order")
        concern_ids = [item.concern_id for item in self.concerns]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("venue review concern IDs must be unique")
        if self.initial_recommendation == "reject" and not self.concerns:
            raise ValueError("a reject recommendation requires a decision-relevant concern")
        if self.ethics_concern == "potential" and not self.ethics_explanation:
            raise ValueError("a potential ethics concern requires an explanation")
        if self.ethics_concern == "none" and self.ethics_explanation is not None:
            raise ValueError("an ethics explanation requires ethics_concern=potential")
        return self


class ValidityThreatKind(StrEnum):
    CONFOUNDER = "confounder"
    ALTERNATIVE_EXPLANATION = "alternative_explanation"
    STATISTICAL_UNCERTAINTY = "statistical_uncertainty"
    BENCHMARK_ARTIFACT = "benchmark_artifact"
    COMPUTE_MISMATCH = "compute_mismatch"
    DATA_LEAKAGE = "data_leakage"
    IMPLEMENTATION_ARTIFACT = "implementation_artifact"


class ValidityThreatProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threat_id: str = Field(min_length=1)
    kind: ValidityThreatKind
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class InterpretationThreatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: ResultRecord
    interpretation_context: InterpretationContext


class InterpretationThreatOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threats: list[ValidityThreatProposal] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    recommended_action_type: MetaAction | None = None
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def threat_ids_are_unique(self) -> InterpretationThreatOutput:
        threat_ids = [item.threat_id for item in self.threats]
        if len(threat_ids) != len(set(threat_ids)):
            raise ValueError("proposed threat ids must be unique")
        return self


class AmbiguousActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_context: str = Field(min_length=1)
    candidate_actions: list[ResearchAction] = Field(min_length=2)
    deterministic_scores: dict[str, float]

    @field_validator("deterministic_scores")
    @classmethod
    def scores_are_finite(cls, values: dict[str, float]) -> dict[str, float]:
        for action_id, value in values.items():
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"score for {action_id} must be finite")
        return values

    @model_validator(mode="after")
    def scores_cover_candidates(self) -> AmbiguousActionInput:
        action_ids = [item.action_id for item in self.candidate_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("candidate action ids must be unique")
        if set(action_ids) != set(self.deterministic_scores):
            raise ValueError("deterministic_scores must cover exactly the candidate actions")
        return self

    @property
    def score_margin(self) -> float:
        ranked = sorted(self.deterministic_scores.values(), reverse=True)
        return ranked[0] - ranked[1]


class AmbiguousActionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ranked_action_ids: list[str] = Field(min_length=2)
    preferred_action_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def preferred_action_is_first_and_ranking_is_unique(self) -> AmbiguousActionOutput:
        if len(self.ranked_action_ids) != len(set(self.ranked_action_ids)):
            raise ValueError("ranked action ids must be unique")
        if self.ranked_action_ids[0] != self.preferred_action_id:
            raise ValueError("preferred_action_id must be first in ranked_action_ids")
        return self
