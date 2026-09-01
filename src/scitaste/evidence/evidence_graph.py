"""First-class evidence records and their typed claim relations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evidence.claim_graph import ClaimGraph


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    experiment_id: str | None = None
    observation: str = Field(min_length=1)
    supports_claim_ids: list[str] = Field(default_factory=list)
    contradicts_claim_ids: list[str] = Field(default_factory=list)
    relates_to_claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    stability: float = Field(default=1.0, ge=0.0, le=1.0)
    cost: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def relations_are_valid(self) -> EvidenceItem:
        support = set(self.supports_claim_ids)
        contradict = set(self.contradicts_claim_ids)
        related = set(self.relates_to_claim_ids)
        if not support and not contradict and not related:
            raise ValueError("evidence must be related to at least one claim")
        if support & contradict or support & related or contradict & related:
            raise ValueError("a claim must have exactly one relation to an evidence item")
        if any(value < 0 for value in self.cost.values()):
            raise ValueError("evidence cost must be nonnegative")
        return self

    @property
    def effective_confidence(self) -> float:
        return self.confidence * self.stability


class EvidenceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    items: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> EvidenceGraph:
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence ids must be unique")
        return self

    def add(self, item: EvidenceItem, claims: ClaimGraph) -> None:
        if any(existing.evidence_id == item.evidence_id for existing in self.items):
            raise ValueError(f"evidence {item.evidence_id!r} already exists")
        target_ids = {
            *item.supports_claim_ids,
            *item.contradicts_claim_ids,
            *item.relates_to_claim_ids,
        }
        known_ids = {claim.claim_id for claim in claims.claims}
        unknown_ids = target_ids - known_ids
        if unknown_ids:
            raise ValueError(f"evidence references unknown claims: {sorted(unknown_ids)}")
        self.items.append(item)
        for claim_id in item.supports_claim_ids:
            claims.link_support(claim_id, item.evidence_id)
        for claim_id in item.contradicts_claim_ids:
            claims.link_contradiction(claim_id, item.evidence_id)

    def get(self, evidence_id: str) -> EvidenceItem:
        for item in self.items:
            if item.evidence_id == evidence_id:
                return item
        raise KeyError(f"unknown evidence {evidence_id!r}")

    def for_claim(self, claim_id: str) -> list[EvidenceItem]:
        return [
            item
            for item in self.items
            if claim_id
            in {
                *item.supports_claim_ids,
                *item.contradicts_claim_ids,
                *item.relates_to_claim_ids,
            }
        ]
