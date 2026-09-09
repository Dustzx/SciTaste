"""Typed contracts for proposal-only semantic Writing Taste review."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.writing.taste import WritingTasteDimension, WritingTasteLevel
from scitaste.writing.venue_taste import VenueWritingTasteContext

WRITING_TASTE_NODE = "writing-taste"


class WritingSemanticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WritingTasteSectionInput(WritingSemanticModel):
    section_name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=30_000)
    claim_ids: tuple[str, ...] = Field(default=(), max_length=100)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=200)

    @field_validator("claim_ids", "evidence_ids")
    @classmethod
    def references_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("writing section references must be unique")
        return tuple(sorted(values))


class MaterialWritingLimitation(WritingSemanticModel):
    limitation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    text: str = Field(min_length=1, max_length=4_000)
    affected_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=100)

    @field_validator("affected_claim_ids")
    @classmethod
    def claims_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("limitation claim references must be unique")
        return tuple(sorted(values))


class WritingTasteSemanticInput(WritingSemanticModel):
    """Only registered manuscript content and references visible to the semantic node."""

    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=500)
    target_venue: str | None = Field(default=None, max_length=500)
    central_problem: str = Field(min_length=1, max_length=4_000)
    intended_contribution: str = Field(min_length=1, max_length=4_000)
    known_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=200)
    known_evidence_ids: tuple[str, ...] = Field(default=(), max_length=500)
    headline_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    sections: tuple[WritingTasteSectionInput, ...] = Field(min_length=1, max_length=40)
    material_limitations: tuple[MaterialWritingLimitation, ...] = Field(default=(), max_length=100)
    deterministic_finding_ids: tuple[str, ...] = Field(default=(), max_length=200)
    venue_taste_context: VenueWritingTasteContext | None = None

    @field_validator(
        "known_claim_ids",
        "known_evidence_ids",
        "headline_claim_ids",
        "deterministic_finding_ids",
    )
    @classmethod
    def identifiers_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("writing-taste identifiers must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def references_are_closed(self) -> WritingTasteSemanticInput:
        claims = set(self.known_claim_ids)
        evidence = set(self.known_evidence_ids)
        if set(self.headline_claim_ids) - claims:
            raise ValueError("headline claims must belong to known_claim_ids")
        section_names = [item.section_name for item in self.sections]
        if len(section_names) != len({item.casefold() for item in section_names}):
            raise ValueError("writing-taste input section names must be unique")
        if any(set(item.claim_ids) - claims for item in self.sections):
            raise ValueError("writing section references an unknown claim")
        if any(set(item.evidence_ids) - evidence for item in self.sections):
            raise ValueError("writing section references unknown evidence")
        limitation_ids = [item.limitation_id for item in self.material_limitations]
        if len(limitation_ids) != len(set(limitation_ids)):
            raise ValueError("material limitation identifiers must be unique")
        if any(set(item.affected_claim_ids) - claims for item in self.material_limitations):
            raise ValueError("material limitation references an unknown claim")
        if self.venue_taste_context is not None:
            if self.venue_taste_context.manuscript_sha256 != self.manuscript_sha256:
                raise ValueError("venue taste context targets a different manuscript")
            if self.target_venue is None:
                raise ValueError("venue taste context requires target_venue")
            accepted_venue_names = {
                self.venue_taste_context.venue_id.casefold(),
                self.venue_taste_context.venue_name.casefold(),
            }
            if self.target_venue.casefold() not in accepted_venue_names:
                raise ValueError("venue taste context targets a different venue")
        return self

    @property
    def manuscript_sha256(self) -> str:
        rendered = "\n\n".join(
            [self.title, *(f"# {item.section_name}\n\n{item.text}" for item in self.sections)]
        )
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    @property
    def section_names(self) -> tuple[str, ...]:
        return tuple(item.section_name for item in self.sections)


class WritingRevisionAction(StrEnum):
    KEEP = "keep"
    REFRAME = "reframe"
    REORDER = "reorder"
    RENAME_SECTION = "rename_section"
    MOVE_TO_APPENDIX = "move_to_appendix"
    NARROW_CLAIM = "narrow_claim"
    REQUEST_EVIDENCE = "request_evidence"
    REMOVE_REDUNDANCY = "remove_redundancy"
    REWRITE = "rewrite"


class SemanticWritingTasteFinding(WritingSemanticModel):
    finding_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dimension: WritingTasteDimension
    level: WritingTasteLevel
    severity: Literal["major", "minor"]
    section_name: str | None = Field(default=None, max_length=200)
    diagnosis: str = Field(min_length=1, max_length=4_000)
    recommendation: str = Field(min_length=1, max_length=4_000)
    action: WritingRevisionAction
    claim_ids: tuple[str, ...] = Field(default=(), max_length=100)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=200)
    material_limitation_ids: tuple[str, ...] = Field(default=(), max_length=100)
    requires_new_evidence: bool = False

    @field_validator("claim_ids", "evidence_ids", "material_limitation_ids")
    @classmethod
    def finding_references_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("semantic writing finding references must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def evidence_action_is_coherent(self) -> SemanticWritingTasteFinding:
        evidence_actions = {
            WritingRevisionAction.REQUEST_EVIDENCE,
            WritingRevisionAction.NARROW_CLAIM,
        }
        if self.requires_new_evidence and self.action not in evidence_actions:
            raise ValueError("evidence-requiring finding must request evidence or narrow a claim")
        if self.action is WritingRevisionAction.REQUEST_EVIDENCE and not self.requires_new_evidence:
            raise ValueError("request_evidence action must declare requires_new_evidence")
        return self


class WritingTasteReviewProposal(WritingSemanticModel):
    """Advisory paper strategy with no manuscript mutation or evidence-admission authority."""

    schema_version: Literal["1.0"] = "1.0"
    manuscript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    central_takeaway: str = Field(min_length=1, max_length=4_000)
    strongest_supported_claim_id: str = Field(min_length=1, max_length=200)
    narrative_strategy: str = Field(min_length=1, max_length=8_000)
    recommended_section_order: tuple[str, ...] = Field(min_length=1, max_length=40)
    findings: tuple[SemanticWritingTasteFinding, ...] = Field(default=(), max_length=40)
    retained_material_limitation_ids: tuple[str, ...] = Field(default=(), max_length=100)
    uncertainty: str = Field(min_length=1, max_length=4_000)
    preserves_material_limitations: Literal[True] = True
    advisory_only: Literal[True] = True

    @field_validator("recommended_section_order", "retained_material_limitation_ids")
    @classmethod
    def proposal_identifiers_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("writing-taste proposal identifiers must be unique")
        return values

    @field_validator("findings")
    @classmethod
    def finding_ids_are_unique(
        cls,
        values: tuple[SemanticWritingTasteFinding, ...],
    ) -> tuple[SemanticWritingTasteFinding, ...]:
        identifiers = [item.finding_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("semantic writing finding IDs must be unique")
        return values


__all__ = [
    "WRITING_TASTE_NODE",
    "MaterialWritingLimitation",
    "SemanticWritingTasteFinding",
    "WritingRevisionAction",
    "WritingTasteReviewProposal",
    "WritingTasteSectionInput",
    "WritingTasteSemanticInput",
]
