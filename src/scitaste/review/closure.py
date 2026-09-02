"""Evidence-aware closure of reviewer-driven research obligations."""

from __future__ import annotations

from scitaste.state.research_state import ResearchObligation, ResearchState

EVIDENCE_ACTIONS = {"ADD_EXPERIMENT", "ADD_BASELINE", "ADD_ANALYSIS", "REVISE_METHOD"}


def close_satisfied_obligations(state: ResearchState) -> list[ResearchObligation]:
    closed: list[ResearchObligation] = []
    evidence = {item.evidence_id: item for item in state.evidence_graph.items}
    for obligation in state.open_research_obligations:
        if obligation.status != "open":
            continue
        if obligation.action_type not in EVIDENCE_ACTIONS:
            continue
        new_items = [
            item
            for identifier, item in evidence.items()
            if identifier not in obligation.evidence_ids_at_open
            and (
                not obligation.target_claim_ids
                or set(obligation.target_claim_ids)
                & {
                    *item.supports_claim_ids,
                    *item.contradicts_claim_ids,
                    *item.relates_to_claim_ids,
                }
            )
            and (
                not obligation.required_evidence_types
                or item.evidence_type in obligation.required_evidence_types
            )
        ]
        if not new_items:
            continue
        obligation.resolution_evidence_ids = [item.evidence_id for item in new_items]
        obligation.resolution_summary = (
            f"Resolved with {len(new_items)} new evidence item(s): "
            + ", ".join(obligation.resolution_evidence_ids)
        )
        obligation.status = "closed"
        concern = next(
            item for item in state.reviewer_concerns if item.concern_id == obligation.concern_id
        )
        concern.status = "closed"
        closed.append(obligation)
    return closed
