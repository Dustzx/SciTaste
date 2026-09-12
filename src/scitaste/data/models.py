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
    license_id: str | None = None
    license_url: str | None = None
    access_scope: str | None = None
    derivation_method: str | None = None
    redistributable: bool | None = None
    personal_data_removed: bool | None = None
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
    applicability_conditions: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    counterfactual_probe: str | None = None
    taste_grounding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    outcome_summary: str | None = None
    provenance: list[ProvenanceRecord] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    domain_tags: list[str] = Field(default_factory=list)
    venue_tags: list[str] = Field(default_factory=list)
    writing_level: str | None = None
    section_type: str | None = None
    rhetorical_role: str | None = None
    transition_pattern: str | None = None
    claim_strength: str | None = None
    citation_density: str | None = None
    writing_taste_dimensions: list[str] = Field(default_factory=list)
    style_tags: list[str] = Field(default_factory=list)
    figure_role: str | None = None
    label_basis: str = "project_curated"
    extractor_version: str | None = None
    human_verified: bool = False
    retrieval_eligible: bool = False
    outcome_horizon: str | None = None
    source_action_id: str | None = None

    @field_validator("preferred_action")
    @classmethod
    def preferred_was_considered(cls, value: str, info) -> str:
        candidates = info.data.get("candidate_actions", [])
        if candidates and value not in candidates:
            raise ValueError("preferred_action must belong to candidate_actions")
        return value

    @field_validator("applicability_conditions", "failure_conditions")
    @classmethod
    def transfer_boundaries_are_bounded(cls, value: list[str]) -> list[str]:
        if len(value) > 20 or any(not item.strip() or len(item) > 4_000 for item in value):
            raise ValueError("Taste transfer-boundary items must be bounded non-empty strings")
        if len(value) != len(set(item.casefold() for item in value)):
            raise ValueError("Taste transfer-boundary items must be unique")
        return value
