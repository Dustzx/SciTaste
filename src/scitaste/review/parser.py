"""Deterministic decomposition of structured reviewer feedback."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.schema.review import ConcernCategory, ConcernSeverity
from scitaste.state.research_state import ReviewerConcern


class ReviewFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concern_id: str
    category: ConcernCategory
    severity: ConcernSeverity
    target_claim_ids: list[str] = Field(default_factory=list)
    target_section: str | None = None
    text: str = Field(min_length=1)
    requires_new_evidence: bool = False
    requires_new_experiment: bool = False
    required_evidence_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_requirements_are_consistent(self) -> ReviewFeedback:
        if self.requires_new_experiment and not self.requires_new_evidence:
            raise ValueError("a requested experiment must require new evidence")
        if self.required_evidence_types and not self.requires_new_evidence:
            raise ValueError("required evidence types require new evidence")
        return self


def parse_feedback(items: list[ReviewFeedback]) -> list[ReviewerConcern]:
    return [
        ReviewerConcern(
            concern_id=item.concern_id,
            category=item.category.value,
            severity=item.severity.value,
            target_claim_ids=item.target_claim_ids,
            target_section=item.target_section,
            text=item.text,
            requires_new_evidence=item.requires_new_evidence,
            requires_new_experiment=item.requires_new_experiment,
            required_evidence_types=item.required_evidence_types,
        )
        for item in items
    ]
