"""Strict input and proposal schemas for the first bounded model nodes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evidence.interpretation import InterpretationContext, ResultRecord
from scitaste.review.parser import ConcernCategory, ConcernSeverity
from scitaste.schema.actions import MetaAction, ResearchAction


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
