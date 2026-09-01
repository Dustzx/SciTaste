"""Route evidence states to advance, reproduce, collect, or pivot actions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evidence.claim_graph import ClaimGraph, ClaimStatus
from scitaste.evidence.experiment_planner import (
    EvidenceExperimentPlan,
    EvidenceExperimentPlanner,
)
from scitaste.evidence.gap import EvidenceGap
from scitaste.evidence.interpretation import (
    InterpretationDisposition,
    InterpretationReview,
)
from scitaste.schema.actions import MetaAction, ResearchAction


class EvidenceRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ResearchAction
    reason: str
    trigger_claim_ids: list[str] = Field(default_factory=list)
    experiment_plan: EvidenceExperimentPlan | None = None


class EvidenceRouter:
    def __init__(self, planner: EvidenceExperimentPlanner | None = None) -> None:
        self.planner = planner or EvidenceExperimentPlanner()

    def route(
        self,
        claims: ClaimGraph,
        gaps: list[EvidenceGap],
        *,
        reviews: list[InterpretationReview] | None = None,
    ) -> EvidenceRoute:
        reviews = reviews or []
        contradicted = sorted(
            report.claim_id
            for report in gaps
            if report.status == ClaimStatus.CONTRADICTED and report.contradiction_score >= 0.65
        )
        if contradicted:
            return EvidenceRoute(
                action=ResearchAction(
                    action_id=f"evidence-pivot-{'-'.join(contradicted)}",
                    type=MetaAction.PIVOT,
                    description="Pivot from stable contradictory evidence without discarding it",
                    parameters={"contradicted_claim_ids": contradicted},
                    expected_value={"information_gain": 0.95, "problem_validity": 0.9},
                    tags=["evidence-backed-pivot", "contradiction"],
                ),
                reason="stable contradictory evidence requires hypothesis or problem reformulation",
                trigger_claim_ids=contradicted,
            )

        uncertain_claims = sorted(
            {
                review.claim_assessment.claim_id
                for review in reviews
                if review.claim_assessment.disposition == InterpretationDisposition.UNCERTAIN
            }
        )
        if uncertain_claims:
            return EvidenceRoute(
                action=ResearchAction(
                    action_id=f"evidence-reproduce-{'-'.join(uncertain_claims)}",
                    type=MetaAction.REPRODUCE,
                    description="Resolve uncertainty and validity threats before updating claims",
                    parameters={"claim_ids": uncertain_claims},
                    expected_cost={"experiments": 1.0},
                    expected_value={"information_gain": 0.85},
                    tags=["interpretation-uncertainty"],
                ),
                reason="an interpretation critic found unresolved uncertainty or validity threats",
                trigger_claim_ids=uncertain_claims,
            )

        plan = self.planner.plan_next(claims, gaps)
        if plan is not None:
            return EvidenceRoute(
                action=plan.action,
                reason="an active claim has an unresolved evidence gap",
                trigger_claim_ids=[plan.claim_id],
                experiment_plan=plan,
            )

        return EvidenceRoute(
            action=ResearchAction(
                action_id="evidence-advance",
                type=MetaAction.ADVANCE,
                description="Advance because active claims satisfy their evidence contracts",
                expected_value={"claim_relevance": 1.0},
                tags=["evidence-complete"],
            ),
            reason="all active claims are supported",
        )
