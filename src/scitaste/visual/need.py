"""Decide whether a scientific relation benefits from a figure."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from scitaste.state.research_state import FigureContract


class FigureNeedAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    needed: bool
    reason: str


class FigureNeedDetector:
    def assess(self, source_text: str, contract: FigureContract) -> FigureNeedAssessment:
        relation_count = len(contract.required_relations)
        needed = relation_count >= 2 and len(source_text.strip()) >= 24
        reason = (
            f"The claim requires readers to track {relation_count} named relations; "
            "a figure reduces prose-only reconstruction cost."
            if needed
            else "The supplied content does not yet justify a separate scientific figure."
        )
        return FigureNeedAssessment(needed=needed, reason=reason)
