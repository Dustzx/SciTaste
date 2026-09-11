"""Typed contracts for proposal-only semantic Writing Taste review."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.writing.taste import WritingTasteDimension, WritingTasteLevel
from scitaste.writing.venue_taste import VenueWritingTasteContext

WRITING_TASTE_NODE = "writing-taste"
EVIDENCE_PAPER_DRAFT_NODE = "evidence-paper-draft"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_BIBTEX_KEY = r"^[A-Za-z][A-Za-z0-9_:-]*$"
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?%?)(?![A-Za-z0-9_]|\.\d)"
)


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


class PaperClaimSupport(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class EvidencePaperClaimInput(WritingSemanticModel):
    claim_id: str = Field(pattern=_IDENTIFIER)
    statement: str = Field(min_length=1, max_length=8_000)
    support_status: PaperClaimSupport
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)
    headline: bool = False

    @field_validator("evidence_ids")
    @classmethod
    def evidence_is_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper claim evidence identifiers must be sorted and unique")
        return values

    @model_validator(mode="after")
    def support_has_evidence(self) -> EvidencePaperClaimInput:
        if self.support_status is not PaperClaimSupport.UNSUPPORTED and not self.evidence_ids:
            raise ValueError("supported or contradicted paper claims require evidence")
        return self


class EvidencePaperEvidenceInput(WritingSemanticModel):
    evidence_id: str = Field(pattern=_IDENTIFIER)
    evidence_type: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=12_000)
    provenance_locator: str = Field(min_length=1, max_length=2_000)


class EvidencePaperCitationInput(WritingSemanticModel):
    citation_id: str = Field(pattern=_IDENTIFIER)
    bibtex_key: str = Field(pattern=_BIBTEX_KEY)
    title: str = Field(min_length=1, max_length=2_000)
    relevance: str = Field(min_length=1, max_length=4_000)


class EvidencePaperDraftInput(WritingSemanticModel):
    """Closed claims, evidence, precedents, and venue duties visible to one draft call."""

    schema_version: Literal["1.0"] = "1.0"
    manuscript_id: str = Field(pattern=_IDENTIFIER)
    title_hint: str = Field(min_length=1, max_length=1_000)
    target_venue: str = Field(min_length=1, max_length=500)
    central_question: str = Field(min_length=1, max_length=8_000)
    intended_contribution: str = Field(min_length=1, max_length=8_000)
    claims: tuple[EvidencePaperClaimInput, ...] = Field(min_length=1, max_length=200)
    evidence: tuple[EvidencePaperEvidenceInput, ...] = Field(default=(), max_length=500)
    citations: tuple[EvidencePaperCitationInput, ...] = Field(default=(), max_length=500)
    material_limitations: tuple[MaterialWritingLimitation, ...] = Field(
        default=(), max_length=100
    )
    required_sections: tuple[str, ...] = Field(min_length=5, max_length=20)
    authorized_numeric_tokens: tuple[str, ...] = Field(default=(), max_length=500)
    maximum_words: int = Field(ge=1_000, le=30_000)

    @field_validator("required_sections")
    @classmethod
    def sections_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("required paper sections cannot be empty")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("required paper sections must be unique")
        return values

    @field_validator("authorized_numeric_tokens")
    @classmethod
    def numeric_tokens_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("authorized numeric tokens must be sorted and unique")
        if any(_NUMBER.fullmatch(value) is None for value in values):
            raise ValueError("authorized numeric tokens must be complete numeric tokens")
        return values

    @model_validator(mode="after")
    def references_are_closed(self) -> EvidencePaperDraftInput:
        claim_ids = [item.claim_id for item in self.claims]
        evidence_ids = [item.evidence_id for item in self.evidence]
        citation_ids = [item.citation_id for item in self.citations]
        for values, label in (
            (claim_ids, "claim"),
            (evidence_ids, "evidence"),
            (citation_ids, "citation"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"paper-draft {label} identifiers must be unique")
        known_evidence = set(evidence_ids)
        if any(set(item.evidence_ids) - known_evidence for item in self.claims):
            raise ValueError("paper claim references unknown evidence")
        known_claims = set(claim_ids)
        if any(set(item.affected_claim_ids) - known_claims for item in self.material_limitations):
            raise ValueError("paper limitation references an unknown claim")
        limitation_ids = [item.limitation_id for item in self.material_limitations]
        if len(limitation_ids) != len(set(limitation_ids)):
            raise ValueError("paper limitation identifiers must be unique")
        if not any(item.headline for item in self.claims):
            raise ValueError("paper draft requires at least one headline claim")
        bibtex_keys = [item.bibtex_key for item in self.citations]
        if len(bibtex_keys) != len(set(bibtex_keys)):
            raise ValueError("paper-draft BibTeX keys must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class EvidencePaperParagraphRole(StrEnum):
    MOTIVATION = "motivation"
    POSITIONING = "positioning"
    METHOD = "method"
    EMPIRICAL_RESULT = "empirical_result"
    INTERPRETATION = "interpretation"
    LIMITATION = "limitation"
    CONCLUSION = "conclusion"


class EvidencePaperParagraph(WritingSemanticModel):
    paragraph_id: str = Field(pattern=_IDENTIFIER)
    role: EvidencePaperParagraphRole
    text: str = Field(min_length=1, max_length=30_000)
    claim_ids: tuple[str, ...] = Field(default=(), max_length=100)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=200)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=100)
    limitation_ids: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("claim_ids", "evidence_ids", "citation_ids", "limitation_ids")
    @classmethod
    def references_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper paragraph references must be sorted and unique")
        return values

    @model_validator(mode="after")
    def empirical_paragraph_has_evidence(self) -> EvidencePaperParagraph:
        if self.role is EvidencePaperParagraphRole.EMPIRICAL_RESULT and not self.evidence_ids:
            raise ValueError("empirical paper paragraphs require registered evidence")
        if self.limitation_ids and self.role is not EvidencePaperParagraphRole.LIMITATION:
            raise ValueError("material limitations must remain explicit limitation paragraphs")
        return self


class EvidencePaperDraftSection(WritingSemanticModel):
    section_name: str = Field(min_length=1, max_length=200)
    paragraphs: tuple[EvidencePaperParagraph, ...] = Field(min_length=1, max_length=100)


class EvidencePaperDraftProposal(WritingSemanticModel):
    """Proposal-only full paper whose references remain deterministically checkable."""

    schema_version: Literal["1.0"] = "1.0"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=1_000)
    abstract: EvidencePaperParagraph
    sections: tuple[EvidencePaperDraftSection, ...] = Field(min_length=5, max_length=20)
    retained_limitation_ids: tuple[str, ...] = Field(default=(), max_length=100)
    observed_numeric_tokens: tuple[str, ...] = Field(default=(), max_length=500)
    proposal_only: Literal[True] = True
    manuscript_mutation_authorized: Literal[False] = False
    empirical_execution_authorized: Literal[False] = False

    @field_validator("retained_limitation_ids", "observed_numeric_tokens")
    @classmethod
    def closed_values_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper proposal closed values must be sorted and unique")
        return values

    @model_validator(mode="after")
    def local_structure_is_unique(self) -> EvidencePaperDraftProposal:
        section_names = [item.section_name for item in self.sections]
        if len({item.casefold() for item in section_names}) != len(section_names):
            raise ValueError("paper proposal section names must be unique")
        paragraphs = [
            self.abstract,
            *(item for section in self.sections for item in section.paragraphs),
        ]
        paragraph_ids = [item.paragraph_id for item in paragraphs]
        if len(paragraph_ids) != len(set(paragraph_ids)):
            raise ValueError("paper proposal paragraph identifiers must be unique")
        observed = tuple(sorted(set(_NUMBER.findall(self.complete_text))))
        if observed != self.observed_numeric_tokens:
            raise ValueError("paper proposal numeric-token inventory is incomplete")
        return self

    @property
    def complete_text(self) -> str:
        return "\n\n".join(
            [
                self.title,
                self.abstract.text,
                *(
                    paragraph.text
                    for section in self.sections
                    for paragraph in section.paragraphs
                ),
            ]
        )

    @property
    def word_count(self) -> int:
        return len(self.complete_text.split())

__all__ = [
    "EVIDENCE_PAPER_DRAFT_NODE",
    "WRITING_TASTE_NODE",
    "EvidencePaperCitationInput",
    "EvidencePaperClaimInput",
    "EvidencePaperDraftInput",
    "EvidencePaperDraftProposal",
    "EvidencePaperDraftSection",
    "EvidencePaperEvidenceInput",
    "EvidencePaperParagraph",
    "EvidencePaperParagraphRole",
    "MaterialWritingLimitation",
    "PaperClaimSupport",
    "SemanticWritingTasteFinding",
    "WritingRevisionAction",
    "WritingTasteReviewProposal",
    "WritingTasteSectionInput",
    "WritingTasteSemanticInput",
]
