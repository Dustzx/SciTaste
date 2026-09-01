"""Typed scientific claims and their evidence links."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClaimType(StrEnum):
    PERFORMANCE = "performance"
    GENERALIZATION = "generalization"
    ROBUSTNESS = "robustness"
    EFFICIENCY = "efficiency"
    MECHANISM = "mechanism"
    REPRESENTATION = "representation"
    INTERPRETABILITY = "interpretability"
    SCALABILITY = "scalability"
    RELIABILITY = "reliability"


class ClaimStrength(StrEnum):
    EXPLORATORY = "exploratory"
    MODERATE = "moderate"
    STRONG = "strong"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    OVERCLAIMED = "overclaimed"


class ScientificClaim(BaseModel):
    """A claim whose status is derived from evidence, never entered as a result."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    claim_type: ClaimType
    strength: ClaimStrength = ClaimStrength.MODERATE
    required_evidence_types: list[str] = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.UNSUPPORTED
    scientific_importance: float = Field(default=0.5, ge=0.0, le=1.0)
    claim_relevance: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def evidence_roles_do_not_overlap(self) -> ScientificClaim:
        overlap = set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids)
        if overlap:
            raise ValueError(
                f"evidence cannot both support and contradict a claim: {sorted(overlap)}"
            )
        return self


class ClaimGraph(BaseModel):
    """Small deterministic claim graph with unique claim identifiers."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    claims: list[ScientificClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def claim_ids_are_unique(self) -> ClaimGraph:
        ids = [claim.claim_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim ids must be unique")
        return self

    def add(self, claim: ScientificClaim) -> None:
        if any(existing.claim_id == claim.claim_id for existing in self.claims):
            raise ValueError(f"claim {claim.claim_id!r} already exists")
        self.claims.append(claim)

    def get(self, claim_id: str) -> ScientificClaim:
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim
        raise KeyError(f"unknown claim {claim_id!r}")

    def link_support(self, claim_id: str, evidence_id: str) -> None:
        claim = self.get(claim_id)
        if evidence_id in claim.contradicting_evidence_ids:
            raise ValueError(f"evidence {evidence_id!r} already contradicts claim {claim_id!r}")
        if evidence_id not in claim.supporting_evidence_ids:
            claim.supporting_evidence_ids.append(evidence_id)

    def link_contradiction(self, claim_id: str, evidence_id: str) -> None:
        claim = self.get(claim_id)
        if evidence_id in claim.supporting_evidence_ids:
            raise ValueError(f"evidence {evidence_id!r} already supports claim {claim_id!r}")
        if evidence_id not in claim.contradicting_evidence_ids:
            claim.contradicting_evidence_ids.append(evidence_id)
