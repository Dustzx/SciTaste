"""Evidence-gated review of a paper's narrative spine."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scitaste.state.research_state import NarrativeSpine, ResearchState


class NarrativeTasteReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passes: bool
    findings: list[str] = Field(default_factory=list)


def review_narrative(spine: NarrativeSpine, state: ResearchState) -> NarrativeTasteReview:
    findings: list[str] = []
    evidence = {item.evidence_id: item for item in state.evidence_graph.items}
    claims = {claim.claim_id: claim for claim in state.claims}
    if not spine.evidence_chain:
        findings.append("narrative spine has no evidence chain")
    for evidence_id in spine.evidence_chain:
        if evidence_id not in evidence:
            findings.append(f"unknown narrative evidence {evidence_id}")
    if not spine.contribution_order:
        findings.append("narrative spine has no contribution order")
    for claim_id in spine.contribution_order:
        claim = claims.get(claim_id)
        if claim is None:
            findings.append(f"unknown contribution claim {claim_id}")
        elif claim.status not in {"supported", "partially_supported"}:
            findings.append(f"contribution claim {claim_id} is {claim.status}")
    if not spine.key_observation.strip() or not spine.central_insight.strip():
        findings.append("narrative spine lacks an observation or central insight")
    return NarrativeTasteReview(passes=not findings, findings=findings)
