"""Provenance-preserving records for knowledge and taste libraries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LibraryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceRecord(LibraryModel):
    source_type: str
    locator: str
    title: str | None = None
    version: str | None = None
    content_hash: str | None = None
    accessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocument(LibraryModel):
    """Factual scientific material answering: what is known?"""

    document_id: str
    title: str
    abstract: str = ""
    content: str = Field(min_length=1)
    domain_tags: list[str] = Field(default_factory=list)
    method_tags: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(min_length=1)


class TasteCase(LibraryModel):
    """Decision precedent answering: what was a good choice in this situation?"""

    case_id: str
    stage: str
    context_summary: str = Field(min_length=1)
    problem_pattern: str | None = None
    evidence_state: str | None = None
    reviewer_context: str | None = None
    candidate_actions: list[str] = Field(min_length=1)
    preferred_action: str
    rejected_actions: list[str] = Field(default_factory=list)
    decision_principle: str = Field(min_length=1)
    why_preferred: str = Field(min_length=1)
    outcome_summary: str | None = None
    provenance: list[ProvenanceRecord] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    domain_tags: list[str] = Field(default_factory=list)
    venue_tags: list[str] = Field(default_factory=list)
    rhetorical_role: str | None = None
    figure_role: str | None = None

    @field_validator("preferred_action")
    @classmethod
    def preferred_was_considered(cls, value: str, info) -> str:
        candidates = info.data.get("candidate_actions", [])
        if candidates and value not in candidates:
            raise ValueError("preferred_action must belong to candidate_actions")
        return value
