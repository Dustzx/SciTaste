"""Typed contracts for proposal-only semantic Writing Taste review."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.schema.review import ConcernCategory, ConcernSeverity
from scitaste.writing.taste import WritingTasteDimension, WritingTasteLevel
from scitaste.writing.venue_taste import VenueWritingTasteContext

WRITING_TASTE_NODE = "writing-taste"
EVIDENCE_PAPER_DRAFT_NODE = "evidence-paper-draft"
EVIDENCE_PAPER_REVISION_NODE = "evidence-paper-revision"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_BIBTEX_KEY = r"^[A-Za-z][A-Za-z0-9_:-]*$"
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?%?)(?![A-Za-z0-9_]|\.\d)")


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
    material_limitations: tuple[MaterialWritingLimitation, ...] = Field(default=(), max_length=100)
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
                *(paragraph.text for section in self.sections for paragraph in section.paragraphs),
            ]
        )

    @property
    def word_count(self) -> int:
        return len(self.complete_text.split())


class PaperRevisionRequirement(StrEnum):
    TEXT_ONLY = "text_only"
    EVIDENCE = "evidence"
    EXPERIMENT = "experiment"


class PaperRevisionTreatmentMode(StrEnum):
    PROSE_REVISION = "prose_revision"
    EVIDENCE_INTEGRATED = "evidence_integrated"
    EXPERIMENT_INTEGRATED = "experiment_integrated"
    PENDING_EVIDENCE = "pending_evidence"
    PENDING_EXPERIMENT = "pending_experiment"


_EXPERIMENT_CONCERN_CATEGORIES = {
    ConcernCategory.MISSING_EVIDENCE,
    ConcernCategory.MISSING_BASELINE,
    ConcernCategory.VALIDITY,
}
_EVIDENCE_CONCERN_CATEGORIES = {
    ConcernCategory.ANALYSIS,
    ConcernCategory.METHOD,
}


class PaperRevisionConcernInput(WritingSemanticModel):
    concern_id: str = Field(pattern=_IDENTIFIER)
    source_report_id: str = Field(pattern=_IDENTIFIER)
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    category: ConcernCategory
    severity: ConcernSeverity
    text: str = Field(min_length=1, max_length=16_000)
    target_claim_ids: tuple[str, ...] = Field(default=(), max_length=100)
    target_section: str | None = Field(default=None, min_length=1, max_length=500)
    requires_new_evidence: bool = False
    requires_new_experiment: bool = False
    required_evidence_types: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("target_claim_ids", "required_evidence_types")
    @classmethod
    def concern_values_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper revision concern values must be sorted and unique")
        return values

    @model_validator(mode="after")
    def declared_requirements_are_consistent(self) -> PaperRevisionConcernInput:
        if self.requires_new_experiment and not self.requires_new_evidence:
            raise ValueError("an experimental concern must require new evidence")
        if self.required_evidence_types and not self.requires_new_evidence:
            raise ValueError("required evidence types require new evidence")
        return self

    @property
    def requirement(self) -> PaperRevisionRequirement:
        if self.requires_new_experiment or self.category in _EXPERIMENT_CONCERN_CATEGORIES:
            return PaperRevisionRequirement.EXPERIMENT
        if (
            self.requires_new_evidence
            or self.required_evidence_types
            or self.category in _EVIDENCE_CONCERN_CATEGORIES
        ):
            return PaperRevisionRequirement.EVIDENCE
        return PaperRevisionRequirement.TEXT_ONLY


class PaperRevisionEvidenceProofItem(WritingSemanticModel):
    evidence_id: str = Field(pattern=_IDENTIFIER)
    evidence_type: str = Field(min_length=1, max_length=500)
    target_claim_ids: tuple[str, ...] = Field(default=(), max_length=100)
    experiment_id: str | None = Field(default=None, pattern=_IDENTIFIER)

    @field_validator("target_claim_ids")
    @classmethod
    def claims_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("revision proof claims must be sorted and unique")
        return values


class PaperRevisionExperimentProofItem(WritingSemanticModel):
    experiment_id: str = Field(pattern=_IDENTIFIER)
    status: Literal["completed"]
    result_locator: str = Field(min_length=1, max_length=1_000)
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaperRevisionClosureProof(WritingSemanticModel):
    """Deterministic state-derived proof; never part of model-authored output."""

    schema_version: Literal["1.0"] = "1.0"
    proof_id: str = Field(pattern=_IDENTIFIER)
    concern_id: str = Field(pattern=_IDENTIFIER)
    opened_state_locator: str | None = Field(default=None, min_length=1, max_length=1_000)
    closed_state_locator: str | None = Field(default=None, min_length=1, max_length=1_000)
    opened_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    closed_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    opened_revision: int = Field(ge=0)
    closed_revision: int = Field(ge=1)
    evidence_ids_at_open: tuple[str, ...] = Field(default=(), max_length=2_000)
    new_evidence: tuple[PaperRevisionEvidenceProofItem, ...] = Field(min_length=1, max_length=100)
    experiments: tuple[PaperRevisionExperimentProofItem, ...] = Field(default=(), max_length=32)
    proof_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evidence_ids_at_open")
    @classmethod
    def open_evidence_is_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("open evidence IDs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def proof_is_new_and_self_hashed(self) -> PaperRevisionClosureProof:
        if (self.opened_state_locator is None) != (self.closed_state_locator is None):
            raise ValueError("revision closure proof state locators must appear together")
        if self.closed_revision <= self.opened_revision:
            raise ValueError("revision closure proof requires a later state revision")
        if self.closed_state_sha256 == self.opened_state_sha256:
            raise ValueError("revision closure proof requires a changed state hash")
        evidence_ids = [item.evidence_id for item in self.new_evidence]
        experiment_ids = [item.experiment_id for item in self.experiments]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("revision closure proof evidence IDs must be unique")
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("revision closure proof experiment IDs must be unique")
        if set(evidence_ids) & set(self.evidence_ids_at_open):
            raise ValueError("revision closure proof evidence must be new")
        if {
            item.experiment_id for item in self.new_evidence if item.experiment_id is not None
        } - set(experiment_ids):
            raise ValueError("revision evidence references an unproved experiment")
        payload = self.model_dump(mode="json", exclude={"proof_sha256"})
        expected = _content_sha256(payload)
        legacy_expected = _content_sha256(
            {key: value for key, value in payload.items() if value is not None}
        )
        if self.proof_sha256 not in {expected, legacy_expected}:
            raise ValueError("revision closure proof hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> PaperRevisionClosureProof:
        payload = {"schema_version": "1.0", **values}
        payload.pop("proof_sha256", None)
        payload["new_evidence"] = tuple(
            item
            if isinstance(item, PaperRevisionEvidenceProofItem)
            else PaperRevisionEvidenceProofItem.model_validate(item)
            for item in payload.get("new_evidence", ())
        )
        payload["experiments"] = tuple(
            item
            if isinstance(item, PaperRevisionExperimentProofItem)
            else PaperRevisionExperimentProofItem.model_validate(item)
            for item in payload.get("experiments", ())
        )
        unsigned = cls.model_construct(proof_sha256="0" * 64, **payload)
        return cls(
            **payload,
            proof_sha256=_content_sha256(
                unsigned.model_dump(mode="json", exclude={"proof_sha256"})
            ),
        )


class EvidencePaperRevisionInput(WritingSemanticModel):
    """One accepted draft, a target evidence scope, and exact review obligations."""

    schema_version: Literal["1.0"] = "1.0"
    source_paper_directory: str = Field(pattern=_IDENTIFIER)
    source_adoption_run_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    target_manuscript_id: str = Field(pattern=_IDENTIFIER)
    source_paper_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_report_sha256s: tuple[str, ...] = Field(min_length=1, max_length=8)
    source_draft_input: EvidencePaperDraftInput
    target_draft_input: EvidencePaperDraftInput
    prior_proposal: EvidencePaperDraftProposal
    concerns: tuple[PaperRevisionConcernInput, ...] = Field(min_length=1, max_length=320)
    closure_proofs: tuple[PaperRevisionClosureProof, ...] = Field(default=(), max_length=320)

    @field_validator("source_report_sha256s")
    @classmethod
    def report_hashes_are_closed(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper revision report hashes must be sorted and unique")
        return values

    @model_validator(mode="after")
    def revision_scope_is_closed(self) -> EvidencePaperRevisionInput:
        if self.prior_proposal.input_fingerprint != self.source_draft_input.fingerprint:
            raise ValueError("prior paper proposal targets a different source draft input")
        if self.source_draft_input.manuscript_id != self.source_paper_directory:
            raise ValueError("source draft input differs from the reviewed paper directory")
        if self.target_draft_input.manuscript_id != self.target_manuscript_id:
            raise ValueError("target draft input differs from the revision manuscript identity")
        if self.source_paper_directory == self.target_manuscript_id:
            raise ValueError("paper revision requires a new manuscript identity")
        concern_ids = [item.concern_id for item in self.concerns]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("paper revision concern identifiers must be unique")
        if {item.source_report_sha256 for item in self.concerns} - set(self.source_report_sha256s):
            raise ValueError("paper revision concern references an unbound report")
        known_claims = {item.claim_id for item in self.target_draft_input.claims}
        if any(set(item.target_claim_ids) - known_claims for item in self.concerns):
            raise ValueError("paper revision concern references an unknown target claim")
        known_sections = set(self.target_draft_input.required_sections)
        if any(
            item.target_section is not None and item.target_section not in known_sections
            for item in self.concerns
        ):
            raise ValueError("paper revision concern references an unknown target section")
        proof_ids = [item.proof_id for item in self.closure_proofs]
        proof_concerns = [item.concern_id for item in self.closure_proofs]
        if len(proof_ids) != len(set(proof_ids)) or len(proof_concerns) != len(set(proof_concerns)):
            raise ValueError("paper revision closure proofs must be unique")
        concerns = {item.concern_id: item for item in self.concerns}
        target_evidence = {item.evidence_id: item for item in self.target_draft_input.evidence}
        target_claims = {item.claim_id: item for item in self.target_draft_input.claims}
        source_evidence = {item.evidence_id for item in self.source_draft_input.evidence}
        for proof in self.closure_proofs:
            concern = concerns.get(proof.concern_id)
            if concern is None:
                raise ValueError("paper revision proof references an unknown concern")
            if concern.requirement is PaperRevisionRequirement.TEXT_ONLY:
                raise ValueError("a text-only concern cannot claim an evidence closure proof")
            if set(proof.evidence_ids_at_open) != source_evidence:
                raise ValueError("revision proof open evidence differs from the source draft")
            for new_item in proof.new_evidence:
                target = target_evidence.get(new_item.evidence_id)
                if target is None or target.evidence_type != new_item.evidence_type:
                    raise ValueError("revision proof evidence differs from target draft evidence")
                if set(new_item.target_claim_ids) - set(concern.target_claim_ids):
                    raise ValueError("revision proof evidence targets claims outside its concern")
                if any(
                    new_item.evidence_id not in target_claims[claim_id].evidence_ids
                    for claim_id in new_item.target_claim_ids
                ):
                    raise ValueError("revision proof evidence is not bound to its target claim")
                if (
                    concern.required_evidence_types
                    and new_item.evidence_type not in concern.required_evidence_types
                ):
                    raise ValueError("revision proof evidence type does not satisfy its concern")
            if concern.requirement is PaperRevisionRequirement.EXPERIMENT:
                experiments = {item.experiment_id for item in proof.experiments}
                if not experiments or not any(
                    item.experiment_id in experiments for item in proof.new_evidence
                ):
                    raise ValueError("experimental concern requires completed experiment evidence")
        return self

    @property
    def fingerprint(self) -> str:
        return _content_sha256(self.model_dump(mode="json"))

    @property
    def closure_proof_by_concern(self) -> dict[str, PaperRevisionClosureProof]:
        return {item.concern_id: item for item in self.closure_proofs}


class PaperRevisionTreatment(WritingSemanticModel):
    concern_id: str = Field(pattern=_IDENTIFIER)
    mode: PaperRevisionTreatmentMode
    target_paragraph_ids: tuple[str, ...] = Field(default=(), max_length=100)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)
    experiment_ids: tuple[str, ...] = Field(default=(), max_length=32)
    rationale: str = Field(min_length=1, max_length=4_000)

    @field_validator("target_paragraph_ids", "evidence_ids", "experiment_ids")
    @classmethod
    def references_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper revision treatment references must be sorted and unique")
        return values


class EvidencePaperRevisionProposal(WritingSemanticModel):
    """Proposal-only revision; review closure remains original-reviewer authority."""

    schema_version: Literal["1.0"] = "1.0"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_paper_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_report_sha256s: tuple[str, ...] = Field(min_length=1, max_length=8)
    revised_draft: EvidencePaperDraftProposal
    treatments: tuple[PaperRevisionTreatment, ...] = Field(min_length=1, max_length=320)
    blocked_concern_ids: tuple[str, ...] = Field(default=(), max_length=320)
    revision_summary: str = Field(min_length=1, max_length=8_000)
    proposal_only: Literal[True] = True
    manuscript_mutation_authorized: Literal[False] = False
    review_closure_authorized: Literal[False] = False
    empirical_execution_authorized: Literal[False] = False

    @field_validator("source_report_sha256s", "blocked_concern_ids")
    @classmethod
    def closed_sets_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("paper revision closed sets must be sorted and unique")
        return values

    @model_validator(mode="after")
    def local_revision_structure_is_closed(self) -> EvidencePaperRevisionProposal:
        treatment_ids = [item.concern_id for item in self.treatments]
        if len(treatment_ids) != len(set(treatment_ids)):
            raise ValueError("paper revision treatments must cover unique concerns")
        return self


def paper_draft_proposal_sha256(proposal: EvidencePaperDraftProposal) -> str:
    return _content_sha256(proposal.model_dump(mode="json"))


def _content_sha256(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "EVIDENCE_PAPER_DRAFT_NODE",
    "EVIDENCE_PAPER_REVISION_NODE",
    "WRITING_TASTE_NODE",
    "EvidencePaperCitationInput",
    "EvidencePaperClaimInput",
    "EvidencePaperDraftInput",
    "EvidencePaperDraftProposal",
    "EvidencePaperDraftSection",
    "EvidencePaperEvidenceInput",
    "EvidencePaperParagraph",
    "EvidencePaperParagraphRole",
    "EvidencePaperRevisionInput",
    "EvidencePaperRevisionProposal",
    "MaterialWritingLimitation",
    "PaperClaimSupport",
    "PaperRevisionClosureProof",
    "PaperRevisionConcernInput",
    "PaperRevisionEvidenceProofItem",
    "PaperRevisionExperimentProofItem",
    "PaperRevisionRequirement",
    "PaperRevisionTreatment",
    "PaperRevisionTreatmentMode",
    "SemanticWritingTasteFinding",
    "WritingRevisionAction",
    "WritingTasteReviewProposal",
    "WritingTasteSectionInput",
    "WritingTasteSemanticInput",
    "paper_draft_proposal_sha256",
]
