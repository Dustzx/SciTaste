"""High-level deterministic façade for the Phase 5 Evidence Loop."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from scitaste.evidence.claim_graph import ClaimGraph
from scitaste.evidence.evidence_graph import EvidenceGraph, EvidenceItem
from scitaste.evidence.gap import EvidenceGap, EvidenceGapAnalyzer
from scitaste.evidence.interpretation import InterpretationReview
from scitaste.evidence.routing import EvidenceRoute, EvidenceRouter


class EvidenceLoopResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gaps: list[EvidenceGap]
    route: EvidenceRoute


class EvidenceLoop:
    """Own claim/evidence graphs and return the next auditable research action."""

    def __init__(
        self,
        claims: ClaimGraph,
        *,
        evidence: EvidenceGraph | None = None,
        gap_analyzer: EvidenceGapAnalyzer | None = None,
        router: EvidenceRouter | None = None,
    ) -> None:
        self.claims = claims
        self.evidence = evidence or EvidenceGraph()
        self.gap_analyzer = gap_analyzer or EvidenceGapAnalyzer()
        self.router = router or EvidenceRouter()

    def add_evidence(
        self,
        item: EvidenceItem,
        *,
        reviews: list[InterpretationReview] | None = None,
    ) -> EvidenceLoopResult:
        self.evidence.add(item, self.claims)
        return self.assess(reviews=reviews)

    def add_review(self, review: InterpretationReview) -> EvidenceLoopResult:
        return self.add_evidence(review.to_evidence_item(), reviews=[review])

    def assess(
        self,
        *,
        reviews: list[InterpretationReview] | None = None,
    ) -> EvidenceLoopResult:
        gaps = self.gap_analyzer.analyze_all(self.claims, self.evidence)
        route = self.router.route(self.claims, gaps, reviews=reviews)
        return EvidenceLoopResult(gaps=gaps, route=route)
