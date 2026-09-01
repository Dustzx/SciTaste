"""Memory-level taste updates from decisions and observed outcomes."""

from __future__ import annotations

import hashlib

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.schema.decisions import ResearchDecision


class TasteMemory:
    def __init__(self, library: TasteLibrary) -> None:
        self.library = library

    def reflect(
        self,
        decision: ResearchDecision,
        *,
        outcome_summary: str,
        decision_principle: str,
        domain_tags: list[str] | None = None,
        venue_tags: list[str] | None = None,
    ) -> TasteCase:
        """Convert an executed decision into a traceable taste precedent."""

        identity = hashlib.sha256(
            f"{decision.decision_id}:{decision.executor_result_id}:{outcome_summary}".encode()
        ).hexdigest()[:24]
        candidates = [action.type.value for action in decision.candidate_actions]
        preferred = decision.selected_action.type.value
        rejected = [
            action.type.value
            for action in decision.candidate_actions
            if action.action_id != decision.selected_action.action_id
        ]
        case = TasteCase(
            case_id=f"taste-{identity}",
            stage=decision.stage,
            context_summary=decision.rationale,
            evidence_state=outcome_summary,
            candidate_actions=candidates,
            preferred_action=preferred,
            rejected_actions=rejected,
            decision_principle=decision_principle,
            why_preferred=decision.rationale,
            outcome_summary=outcome_summary,
            provenance=[
                ProvenanceRecord(
                    source_type="decision_log",
                    locator=decision.state_snapshot_id,
                    version=decision.decision_id,
                    metadata={"executor_result_id": decision.executor_result_id},
                )
            ],
            confidence=decision.confidence,
            domain_tags=domain_tags or [],
            venue_tags=venue_tags or [],
        )
        self.library.upsert(case)
        return case
