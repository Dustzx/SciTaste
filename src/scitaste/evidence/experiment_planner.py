"""Information-value-based planning for claim evidence gaps."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evidence.claim_graph import ClaimGraph, ClaimStatus, ScientificClaim
from scitaste.evidence.gap import EvidenceGap
from scitaste.schema.actions import MetaAction, ResearchAction


class EvidenceExperimentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    claim_id: str
    target_evidence_type: str
    objective: str
    falsification_test: str
    counterfactual: str
    matched_baseline: str
    negative_control: str
    expected_information_gain: float = Field(ge=0.0, le=1.0)
    expected_research_utility: float = Field(ge=0.0)
    action: ResearchAction


class EvidenceExperimentPlanner:
    """Choose an evidence action by information gain, importance, relevance, and cost."""

    _information_gain: ClassVar[dict[ClaimStatus, float]] = {
        ClaimStatus.UNSUPPORTED: 1.0,
        ClaimStatus.CONTRADICTED: 0.95,
        ClaimStatus.OVERCLAIMED: 0.85,
        ClaimStatus.PARTIALLY_SUPPORTED: 0.7,
        ClaimStatus.SUPPORTED: 0.0,
    }

    def plan_next(
        self,
        claims: ClaimGraph,
        gaps: list[EvidenceGap],
    ) -> EvidenceExperimentPlan | None:
        candidates: list[EvidenceExperimentPlan] = []
        for gap in gaps:
            if gap.status == ClaimStatus.SUPPORTED:
                continue
            claim = claims.get(gap.claim_id)
            candidates.append(self._plan(claim, gap))
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda plan: (-plan.expected_research_utility, plan.claim_id),
        )[0]

    def _plan(self, claim: ScientificClaim, gap: EvidenceGap) -> EvidenceExperimentPlan:
        evidence_type = (
            gap.missing_evidence_types[0]
            if gap.missing_evidence_types
            else claim.required_evidence_types[0]
        )
        cost = _estimated_cost(evidence_type)
        information_gain = self._information_gain[gap.status]
        scalar_cost = sum(cost.values())
        utility = (
            information_gain
            * claim.scientific_importance
            * claim.claim_relevance
            / (1.0 + scalar_cost)
        )
        action_type = (
            MetaAction.REPRODUCE
            if gap.status == ClaimStatus.CONTRADICTED
            else MetaAction.COLLECT_EVIDENCE
        )
        action_id = f"evidence-{action_type.value.lower()}-{claim.claim_id}-{evidence_type}"
        action = ResearchAction(
            action_id=action_id,
            type=action_type,
            description=f"Collect {evidence_type} evidence for claim {claim.claim_id}",
            parameters={
                "claim_id": claim.claim_id,
                "target_evidence_type": evidence_type,
                "current_status": gap.status.value,
                "falsification_test": f"Test a condition under which {claim.text} must fail",
                "counterfactual": "Remove the proposed causal factor while holding inputs fixed",
                "matched_baseline": "Compare against a cost- and data-matched baseline",
                "negative_control": "Run a condition where no claimed effect should occur",
            },
            expected_cost=cost,
            expected_value={
                "information_gain": information_gain,
                "scientific_importance": claim.scientific_importance,
                "claim_relevance": claim.claim_relevance,
            },
            preconditions=[f"claim:{claim.claim_id}"],
            tags=["evidence-gap", evidence_type],
        )
        return EvidenceExperimentPlan(
            plan_id=f"plan-{claim.claim_id}-{evidence_type}",
            claim_id=claim.claim_id,
            target_evidence_type=evidence_type,
            objective=f"Resolve {gap.status.value} status for: {claim.text}",
            falsification_test=f"Test a condition under which {claim.text} must fail",
            counterfactual="Remove the proposed causal factor while holding inputs fixed",
            matched_baseline="Compare against a cost- and data-matched baseline",
            negative_control="Run a condition where no claimed effect should occur",
            expected_information_gain=information_gain,
            expected_research_utility=utility,
            action=action,
        )


def _estimated_cost(evidence_type: str) -> dict[str, float]:
    normalized = evidence_type.casefold()
    if "scal" in normalized or "compute" in normalized:
        return {"experiments": 1.0, "gpu_hours": 2.0}
    if "robust" in normalized or "general" in normalized:
        return {"experiments": 1.0, "gpu_hours": 0.5}
    if "mechan" in normalized or "ablation" in normalized:
        return {"experiments": 1.0, "gpu_hours": 0.25}
    return {"experiments": 1.0, "gpu_hours": 0.1}
