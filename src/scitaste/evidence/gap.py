"""Deterministic evidence-gap analysis for active scientific claims."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evidence.claim_graph import (
    ClaimGraph,
    ClaimStatus,
    ClaimStrength,
    ScientificClaim,
)
from scitaste.evidence.evidence_graph import EvidenceGraph, EvidenceItem


class EvidenceGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    status: ClaimStatus
    missing_evidence_types: list[str] = Field(default_factory=list)
    support_score: float = Field(ge=0.0, le=1.0)
    contradiction_score: float = Field(ge=0.0, le=1.0)
    type_coverage: float = Field(ge=0.0, le=1.0)
    reliable_support_count: int = Field(ge=0)
    rationale: str


class EvidenceGapAnalyzer:
    """Map explicit evidence to the five statuses required by the specification."""

    def __init__(self, *, reliability_threshold: float = 0.65) -> None:
        if not 0.0 <= reliability_threshold <= 1.0:
            raise ValueError("reliability_threshold must be between zero and one")
        self.reliability_threshold = reliability_threshold

    def analyze(self, claim: ScientificClaim, evidence: EvidenceGraph) -> EvidenceGap:
        related = evidence.for_claim(claim.claim_id)
        supports = [item for item in related if claim.claim_id in item.supports_claim_ids]
        contradictions = [item for item in related if claim.claim_id in item.contradicts_claim_ids]
        reliable_supports = self._reliable(supports)
        reliable_contradictions = self._reliable(contradictions)
        covered_types = {item.evidence_type for item in reliable_supports}
        missing = [
            evidence_type
            for evidence_type in claim.required_evidence_types
            if evidence_type not in covered_types
        ]
        coverage = 1.0 - (len(missing) / len(claim.required_evidence_types))
        support_score = max((item.effective_confidence for item in supports), default=0.0)
        contradiction_score = max(
            (item.effective_confidence for item in contradictions), default=0.0
        )

        if reliable_contradictions:
            status = ClaimStatus.CONTRADICTED
            rationale = "reliable evidence contradicts the claim"
        elif not supports:
            status = ClaimStatus.UNSUPPORTED
            rationale = "no supporting evidence is linked"
        elif claim.strength == ClaimStrength.STRONG and (
            coverage < 1.0 or len(reliable_supports) < 2
        ):
            status = ClaimStatus.OVERCLAIMED
            rationale = "the stated strength exceeds evidence coverage or replication"
        elif coverage < 1.0 or support_score < self.reliability_threshold:
            status = ClaimStatus.PARTIALLY_SUPPORTED
            rationale = "support exists but is incomplete or uncertain"
        else:
            status = ClaimStatus.SUPPORTED
            rationale = "all required evidence types have reliable support"

        return EvidenceGap(
            claim_id=claim.claim_id,
            status=status,
            missing_evidence_types=missing,
            support_score=support_score,
            contradiction_score=contradiction_score,
            type_coverage=coverage,
            reliable_support_count=len(reliable_supports),
            rationale=rationale,
        )

    def analyze_all(self, claims: ClaimGraph, evidence: EvidenceGraph) -> list[EvidenceGap]:
        reports = [self.analyze(claim, evidence) for claim in claims.claims]
        by_id = {report.claim_id: report for report in reports}
        for claim in claims.claims:
            claim.status = by_id[claim.claim_id].status
        return reports

    def _reliable(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        return [item for item in items if item.effective_confidence >= self.reliability_threshold]
