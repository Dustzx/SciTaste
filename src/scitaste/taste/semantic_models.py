"""Typed contracts for source-grounded Scientific Taste abstraction."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_EXACT_TEXT_CONFIG = ConfigDict(extra="forbid", frozen=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"

TASTE_ABSTRACTION_NODE = "taste-abstraction"


class TasteCaseAbstraction(BaseModel):
    """Untrusted proposed decision principle; trust is added only by review."""

    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    context_summary: str = Field(min_length=1, max_length=20_000)
    problem_pattern: str | None = Field(default=None, max_length=4_000)
    evidence_state: str | None = Field(default=None, max_length=10_000)
    reviewer_context: str | None = Field(default=None, max_length=10_000)
    candidate_actions: tuple[str, ...] = Field(min_length=2, max_length=20)
    preferred_action: str = Field(min_length=1, max_length=500)
    rejected_actions: tuple[str, ...] = Field(min_length=1, max_length=19)
    decision_principle: str = Field(min_length=1, max_length=10_000)
    why_preferred: str = Field(min_length=1, max_length=10_000)
    outcome_summary: str | None = Field(default=None, max_length=10_000)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def actions_form_a_closed_decision(self) -> TasteCaseAbstraction:
        if len(self.candidate_actions) != len(set(self.candidate_actions)):
            raise ValueError("Taste abstraction candidate actions must be unique")
        if self.preferred_action not in self.candidate_actions:
            raise ValueError("Taste abstraction preferred action must be a candidate")
        if self.preferred_action in self.rejected_actions:
            raise ValueError("Taste abstraction cannot reject its preferred action")
        expected = set(self.candidate_actions) - {self.preferred_action}
        if set(self.rejected_actions) != expected:
            raise ValueError("Taste abstraction must explicitly reject every other candidate")
        return self


class TasteAbstractionInput(BaseModel):
    """Exact source projection visible to the proposal-only abstraction node."""

    model_config = _EXACT_TEXT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    source_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    stage: str = Field(min_length=1, max_length=100)
    decision_role: str = Field(min_length=1, max_length=300)
    source_projection: str = Field(min_length=1, max_length=800_000)
    source_projection_sha256: str = Field(pattern=_SHA256)
    domain_tags: tuple[str, ...] = Field(min_length=1, max_length=20)
    outcome_information_availability: Literal["available", "withheld"]
    relation_label_hidden: Literal[True] = True
    held_out_task_content_excluded: Literal[True] = True
    source_projection_is_only_source_content: Literal[True] = True

    @model_validator(mode="after")
    def source_scope_is_exact(self) -> TasteAbstractionInput:
        if not self.source_projection.strip():
            raise ValueError("Taste abstraction source projection cannot be blank")
        if hashlib.sha256(self.source_projection.encode()).hexdigest() != (
            self.source_projection_sha256
        ):
            raise ValueError("Taste abstraction source projection hash mismatch")
        if self.stage != self.stage.strip() or self.decision_role != self.decision_role.strip():
            raise ValueError("Taste abstraction metadata cannot contain boundary whitespace")
        if len(self.domain_tags) != len(set(item.casefold() for item in self.domain_tags)):
            raise ValueError("Taste abstraction domain tags must be unique")
        if any(not item or item != item.strip() or len(item) > 200 for item in self.domain_tags):
            raise ValueError("Taste abstraction domain tags must be bounded")
        return self


__all__ = [
    "TASTE_ABSTRACTION_NODE",
    "TasteAbstractionInput",
    "TasteCaseAbstraction",
]
