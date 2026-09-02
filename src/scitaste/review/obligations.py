"""Creation of auditable research obligations from reviewer concerns."""

from __future__ import annotations

from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchObligation, ResearchState, ReviewerConcern


def create_obligation(
    concern: ReviewerConcern, action: ResearchAction, state: ResearchState
) -> ResearchObligation:
    return ResearchObligation(
        obligation_id=f"obligation-{concern.concern_id}",
        concern_id=concern.concern_id,
        action_type=action.type.value,
        required_action={
            **action.model_dump(mode="json"),
            "target_section": concern.target_section,
        },
        target_claim_ids=concern.target_claim_ids,
        required_evidence_types=concern.required_evidence_types,
        estimated_cost=action.parameters.get("estimated_followup_cost", {}),
        evidence_ids_at_open=[item.evidence_id for item in state.evidence_graph.items],
        opened_at_revision=state.revision,
    )
