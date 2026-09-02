"""Route reviewer concerns to research actions instead of generic rewriting."""

from __future__ import annotations

from typing import ClassVar

from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ReviewerConcern


class ReviewActionRouter:
    ROUTES: ClassVar[dict[str, MetaAction]] = {
        "clarity": MetaAction.CLARIFY_EXISTING_TEXT,
        "missing_evidence": MetaAction.ADD_EXPERIMENT,
        "missing_baseline": MetaAction.ADD_BASELINE,
        "analysis": MetaAction.ADD_ANALYSIS,
        "method": MetaAction.REVISE_METHOD,
        "overclaim": MetaAction.NARROW_CLAIM,
        "error": MetaAction.CORRECT_ERROR,
        "limitation": MetaAction.ACKNOWLEDGE_LIMITATION,
        "validity": MetaAction.ADD_EXPERIMENT,
    }

    def route(self, concern: ReviewerConcern) -> ResearchAction:
        action_type = self.ROUTES.get(concern.category)
        if action_type is None:
            raise ValueError(f"unsupported reviewer concern category {concern.category!r}")
        experiment = action_type in {
            MetaAction.ADD_EXPERIMENT,
            MetaAction.ADD_BASELINE,
            MetaAction.REVISE_METHOD,
        }
        followup_cost = {"experiments": 1.0} if experiment else {"wall_time_hours": 0.25}
        value = 1.0 if concern.severity in {"high", "critical"} else 0.6
        return ResearchAction(
            action_id=f"review-action-{concern.concern_id}",
            type=action_type,
            description=f"Resolve reviewer concern: {concern.text}",
            parameters={
                "concern_id": concern.concern_id,
                "target_claim_ids": concern.target_claim_ids,
                "target_section": concern.target_section,
                "estimated_followup_cost": followup_cost,
            },
            expected_value={
                "claim_relevance": value,
                "information_gain": value if experiment else 0.1,
            },
            tags=["review-obligation", concern.category],
        )
