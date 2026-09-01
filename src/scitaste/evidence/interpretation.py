"""Interpretation critic separating results, observations, interpretations, and claims."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evidence.evidence_graph import EvidenceItem


class ClaimRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class InterpretationDisposition(StrEnum):
    SUPPORT = "support"
    UNCERTAIN = "uncertain"
    CONTRADICTION = "contradiction"


class ResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_id: str
    experiment_id: str
    summary: str = Field(min_length=1)
    metrics: dict[str, float] = Field(default_factory=dict)
    cost: dict[str, float] = Field(default_factory=dict)


class InterpretationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    evidence_type: str
    expected: str = Field(min_length=1)
    observed: str = Field(min_length=1)
    relation: ClaimRelation
    reproducible: bool
    stability: float = Field(ge=0.0, le=1.0)
    statistical_uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    confounders: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    benchmark_artifacts: list[str] = Field(default_factory=list)
    compute_mismatch: bool = False
    data_leakage: bool = False
    implementation_artifacts: list[str] = Field(default_factory=list)


class ObservationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str
    result_id: str
    statement: str
    expected: bool
    reproducible: bool
    stability: float = Field(ge=0.0, le=1.0)


class InterpretationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interpretation_id: str
    observation_id: str
    disposition: InterpretationDisposition
    rationale: str
    validity_threats: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    disposition: InterpretationDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    may_update_claim: bool


class InterpretationReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: ResultRecord
    observation: ObservationRecord
    interpretation: InterpretationRecord
    claim_assessment: ClaimAssessment
    evidence_type: str

    def to_evidence_item(self) -> EvidenceItem:
        disposition = self.claim_assessment.disposition
        claim_id = self.claim_assessment.claim_id
        return EvidenceItem(
            evidence_id=f"evidence-{self.result.result_id}-{claim_id}",
            source_type="experiment",
            evidence_type=self.evidence_type,
            experiment_id=self.result.experiment_id,
            observation=self.observation.statement,
            supports_claim_ids=(
                [claim_id] if disposition == InterpretationDisposition.SUPPORT else []
            ),
            contradicts_claim_ids=(
                [claim_id] if disposition == InterpretationDisposition.CONTRADICTION else []
            ),
            relates_to_claim_ids=(
                [claim_id] if disposition == InterpretationDisposition.UNCERTAIN else []
            ),
            confidence=self.claim_assessment.confidence,
            stability=self.observation.stability,
            cost=self.result.cost,
        )


class InterpretationCritic:
    """Reject direct metric-to-claim promotion when validity threats remain."""

    def __init__(self, *, uncertainty_threshold: float = 0.25) -> None:
        if not 0.0 <= uncertainty_threshold <= 1.0:
            raise ValueError("uncertainty_threshold must be between zero and one")
        self.uncertainty_threshold = uncertainty_threshold

    def review(
        self,
        result: ResultRecord,
        context: InterpretationContext,
    ) -> InterpretationReview:
        threats = _validity_threats(context)
        uncertain = (
            not context.reproducible
            or context.stability < 0.6
            or context.statistical_uncertainty > self.uncertainty_threshold
            or bool(threats)
            or bool(context.alternative_explanations)
        )
        if uncertain:
            disposition = InterpretationDisposition.UNCERTAIN
            rationale = "validity threats or uncertainty prevent a claim update"
        elif context.relation == ClaimRelation.CONTRADICTS:
            disposition = InterpretationDisposition.CONTRADICTION
            rationale = "a stable, reproducible observation contradicts the expected outcome"
        else:
            disposition = InterpretationDisposition.SUPPORT
            rationale = "a stable, reproducible observation supports the expected outcome"

        confidence = max(0.0, min(1.0, 1.0 - context.statistical_uncertainty))
        observation_id = f"observation-{result.result_id}"
        observation = ObservationRecord(
            observation_id=observation_id,
            result_id=result.result_id,
            statement=context.observed,
            expected=context.relation == ClaimRelation.SUPPORTS,
            reproducible=context.reproducible,
            stability=context.stability,
        )
        interpretation = InterpretationRecord(
            interpretation_id=f"interpretation-{result.result_id}-{context.claim_id}",
            observation_id=observation_id,
            disposition=disposition,
            rationale=rationale,
            validity_threats=threats,
            alternative_explanations=context.alternative_explanations,
        )
        assessment = ClaimAssessment(
            claim_id=context.claim_id,
            disposition=disposition,
            confidence=confidence,
            may_update_claim=disposition != InterpretationDisposition.UNCERTAIN,
        )
        return InterpretationReview(
            result=result,
            observation=observation,
            interpretation=interpretation,
            claim_assessment=assessment,
            evidence_type=context.evidence_type,
        )


def _validity_threats(context: InterpretationContext) -> list[str]:
    threats = [f"confounder: {item}" for item in context.confounders]
    threats.extend(f"benchmark artifact: {item}" for item in context.benchmark_artifacts)
    if context.compute_mismatch:
        threats.append("compute mismatch")
    if context.data_leakage:
        threats.append("data leakage")
    threats.extend(f"implementation artifact: {item}" for item in context.implementation_artifacts)
    return threats
