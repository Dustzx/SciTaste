"""Proposal-only semantic node for paper-level Writing Taste decisions."""

from __future__ import annotations

import re

from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.runtime import ModelNodeRegistration
from scitaste.writing.semantic_models import (
    EVIDENCE_PAPER_DRAFT_NODE,
    WRITING_TASTE_NODE,
    EvidencePaperDraftInput,
    EvidencePaperDraftProposal,
    EvidencePaperParagraphRole,
    PaperClaimSupport,
    WritingRevisionAction,
    WritingTasteReviewProposal,
    WritingTasteSemanticInput,
)


class EvidencePaperDraftNode(ModelNode[EvidencePaperDraftInput, EvidencePaperDraftProposal]):
    """Draft full paper content while retaining closed claim/evidence authority."""

    node_name = EVIDENCE_PAPER_DRAFT_NODE
    prompt_version = "evidence-paper-draft-v1"
    system_instruction = (
        "Draft a complete venue-oriented research paper only from the supplied claims, evidence, "
        "citations, and limitations. Return the required sections in their declared order and "
        "reference only supplied identifiers. Every empirical paragraph must cite registered "
        "evidence supporting its referenced claims. Preserve unsupported or contradicted claims "
        "as explicit boundaries, preserve every material limitation, and do not invent numeric "
        "values. Report the complete sorted numeric-token inventory found in the generated text. "
        "Put citation identifiers only in citation_ids; do not write citation commands or "
        "internal identifiers into reader-facing text. "
        "This is a proposal only: do not mutate manuscript files, execute experiments, call "
        "tools, claim venue acceptance, or imply independent review."
    )
    input_model = EvidencePaperDraftInput
    output_model = EvidencePaperDraftProposal

    def _proposal_rejections(
        self,
        proposal: EvidencePaperDraftProposal,
        *,
        input_data: EvidencePaperDraftInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        claims = {item.claim_id: item for item in input_data.claims}
        evidence = {item.evidence_id for item in input_data.evidence}
        citations = {item.citation_id for item in input_data.citations}
        limitations = {item.limitation_id for item in input_data.material_limitations}
        if proposal.input_fingerprint != input_data.fingerprint:
            reasons.append("paper proposal targets a different evidence projection")
        if tuple(item.section_name for item in proposal.sections) != input_data.required_sections:
            reasons.append("paper proposal does not preserve the required section order")
        if set(context.claim_ids) != set(claims):
            reasons.append("node context claim scope differs from paper-draft input")
        if set(context.evidence_ids) != evidence:
            reasons.append("node context evidence scope differs from paper-draft input")
        if set(context.section_ids) != set(input_data.required_sections):
            reasons.append("node context section scope differs from paper-draft input")
        if set(proposal.retained_limitation_ids) != limitations:
            reasons.append("paper proposal omitted or invented a material limitation")
        if set(proposal.observed_numeric_tokens) - set(input_data.authorized_numeric_tokens):
            reasons.append("paper proposal contains an unauthorized numeric token")
        if proposal.word_count > input_data.maximum_words:
            reasons.append("paper proposal exceeds the approved word budget")
        internal_ids = {
            *claims,
            *evidence,
            *citations,
            *limitations,
            *(item.bibtex_key for item in input_data.citations),
        }
        leaked_ids = sorted(
            identifier
            for identifier in internal_ids
            if _identifier_occurs(proposal.complete_text, identifier)
        )
        if leaked_ids:
            reasons.append("paper proposal leaks internal identifiers into reader-facing text")
        if re.search(r"\\cite[pt]?\{", proposal.complete_text):
            reasons.append("paper proposal contains renderer-owned citation markup")

        paragraphs = [
            proposal.abstract,
            *(paragraph for section in proposal.sections for paragraph in section.paragraphs),
        ]
        referenced_claims: set[str] = set()
        referenced_limitations: set[str] = set()
        for paragraph in paragraphs:
            unknown_claims = set(paragraph.claim_ids) - set(claims)
            unknown_evidence = set(paragraph.evidence_ids) - evidence
            unknown_citations = set(paragraph.citation_ids) - citations
            unknown_limitations = set(paragraph.limitation_ids) - limitations
            if unknown_claims:
                reasons.append(f"paragraph {paragraph.paragraph_id!r} references unknown claims")
            if unknown_evidence:
                reasons.append(f"paragraph {paragraph.paragraph_id!r} references unknown evidence")
            if unknown_citations:
                reasons.append(
                    f"paragraph {paragraph.paragraph_id!r} references unknown citations"
                )
            if unknown_limitations:
                reasons.append(
                    f"paragraph {paragraph.paragraph_id!r} references unknown limitations"
                )
            if unknown_claims or unknown_evidence:
                continue
            referenced_claims.update(paragraph.claim_ids)
            referenced_limitations.update(paragraph.limitation_ids)
            for claim_id in paragraph.claim_ids:
                claim = claims[claim_id]
                if (
                    paragraph.role is EvidencePaperParagraphRole.EMPIRICAL_RESULT
                    and claim.support_status is PaperClaimSupport.UNSUPPORTED
                ):
                    reasons.append(
                        f"paragraph {paragraph.paragraph_id!r} presents an unsupported claim "
                        "as an empirical result"
                    )
                if claim.support_status is not PaperClaimSupport.UNSUPPORTED and not (
                    set(paragraph.evidence_ids) & set(claim.evidence_ids)
                ):
                    reasons.append(
                        f"paragraph {paragraph.paragraph_id!r} does not cite evidence bound to "
                        f"claim {claim_id!r}"
                    )
        headline_claims = {item.claim_id for item in input_data.claims if item.headline}
        if not headline_claims.issubset(referenced_claims):
            reasons.append("paper proposal omits a headline claim")
        if referenced_limitations != limitations:
            reasons.append("paper proposal does not state every material limitation explicitly")
        return sorted(set(reasons))


def render_evidence_paper_markdown(
    proposal: EvidencePaperDraftProposal,
    *,
    input_data: EvidencePaperDraftInput,
) -> str:
    """Render clean paper prose while keeping internal IDs in the typed sidecar."""

    validated = EvidencePaperDraftProposal.model_validate(proposal.model_dump(mode="json"))
    bound_input = EvidencePaperDraftInput.model_validate(input_data.model_dump(mode="json"))
    if validated.input_fingerprint != bound_input.fingerprint:
        raise ValueError("paper proposal does not match the supplied draft input")
    internal_ids = {
        *(item.claim_id for item in bound_input.claims),
        *(item.evidence_id for item in bound_input.evidence),
        *(item.citation_id for item in bound_input.citations),
        *(item.limitation_id for item in bound_input.material_limitations),
        *(item.bibtex_key for item in bound_input.citations),
    }
    if any(_identifier_occurs(validated.complete_text, item) for item in internal_ids):
        raise ValueError("reader-facing paper text contains an internal identifier")
    if re.search(r"\\cite[pt]?\{", validated.complete_text):
        raise ValueError("reader-facing paper text contains renderer-owned citation markup")
    citation_keys = {item.citation_id: item.bibtex_key for item in bound_input.citations}

    def render_paragraph(text: str, citation_ids: tuple[str, ...]) -> str:
        try:
            suffix = " ".join(f"\\citep{{{citation_keys[item]}}}" for item in citation_ids)
        except KeyError as exc:
            raise ValueError("paper paragraph references an unknown citation") from exc
        return text if not suffix else f"{text} {suffix}"

    sections = "\n\n".join(
        "\n\n".join(
            [
                f"# {section.section_name}",
                *(
                    render_paragraph(paragraph.text, paragraph.citation_ids)
                    for paragraph in section.paragraphs
                ),
            ]
        )
        for section in validated.sections
    )
    return (
        f"## Title\n{validated.title}\n\n"
        f"## Abstract\n\n"
        f"{render_paragraph(validated.abstract.text, validated.abstract.citation_ids)}\n\n"
        f"{sections}\n"
    )


def _identifier_occurs(text: str, identifier: str) -> bool:
    boundary = r"A-Za-z0-9_.:-"
    return re.search(
        rf"(?<![{boundary}]){re.escape(identifier)}(?![{boundary}])",
        text,
    ) is not None


class WritingTasteNode(ModelNode[WritingTasteSemanticInput, WritingTasteReviewProposal]):
    """Judge semantic writing choices while retaining deterministic acceptance authority."""

    node_name = WRITING_TASTE_NODE
    prompt_version = "writing-taste-v2"
    system_instruction = (
        "Review the registered manuscript as scientific writing at paper, section, paragraph, "
        "sentence, and phrase levels. Evaluate scientific positioning, narrative focus, "
        "argumentative structure, evidence prioritization, claim calibration, positive-scope "
        "anti-defensive style, reader guidance, venue fit, terminology, and global coherence. "
        "Anti-defensive style is only one dimension. Scientific integrity, claim-evidence "
        "calibration, and material limitations outrank persuasion: never hide counterevidence, "
        "omit a registered material limitation, expand a claim, invent evidence, or treat "
        "selective reporting as stronger writing. Prefer a direct evidence-centered story over "
        "a project log. When a content-bound venue_taste_context is supplied, use only its "
        "applicable principles and archetype duties for venue-specific advice. Treat candidate "
        "principles as hypotheses, never as acceptance rules or numeric figure, table, experiment, "
        "or ablation quotas. Do not infer omitted archetype guidance. Return advisory data only; "
        "do not rewrite files, mutate state, call "
        "tools, accept evidence, or execute actions. Reference only supplied identifiers and "
        "retain every supplied material limitation identifier."
    )
    input_model = WritingTasteSemanticInput
    output_model = WritingTasteReviewProposal

    def _proposal_rejections(
        self,
        proposal: WritingTasteReviewProposal,
        *,
        input_data: WritingTasteSemanticInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        known_claims = set(input_data.known_claim_ids)
        known_evidence = set(input_data.known_evidence_ids)
        known_sections = set(input_data.section_names)
        limitations = {item.limitation_id for item in input_data.material_limitations}
        if proposal.manuscript_sha256 != input_data.manuscript_sha256:
            reasons.append("writing-taste proposal targets a different manuscript")
        if proposal.strongest_supported_claim_id not in input_data.headline_claim_ids:
            reasons.append("strongest claim is not an admitted headline claim")
        if set(proposal.recommended_section_order) != known_sections:
            reasons.append("recommended section order must contain every supplied section once")
        if set(proposal.retained_material_limitation_ids) != limitations:
            reasons.append("writing-taste proposal omitted or invented a material limitation")
        if set(context.claim_ids) != known_claims:
            reasons.append("node context claim scope differs from writing-taste input")
        if set(context.evidence_ids) != known_evidence:
            reasons.append("node context evidence scope differs from writing-taste input")
        if set(context.section_ids) != known_sections:
            reasons.append("node context section scope differs from writing-taste input")
        for finding in proposal.findings:
            if finding.section_name is not None and finding.section_name not in known_sections:
                reasons.append(f"finding {finding.finding_id!r} references an unknown section")
            if set(finding.claim_ids) - known_claims:
                reasons.append(f"finding {finding.finding_id!r} references an unknown claim")
            if set(finding.evidence_ids) - known_evidence:
                reasons.append(f"finding {finding.finding_id!r} references unknown evidence")
            if set(finding.material_limitation_ids) - limitations:
                reasons.append(
                    f"finding {finding.finding_id!r} references an unknown material limitation"
                )
            if finding.material_limitation_ids and finding.action in {
                WritingRevisionAction.MOVE_TO_APPENDIX,
                WritingRevisionAction.REMOVE_REDUNDANCY,
            }:
                reasons.append(
                    f"finding {finding.finding_id!r} attempts to demote a material limitation"
                )
        return sorted(set(reasons))


def writing_node_types() -> dict[str, ModelNodeRegistration]:
    """Return the semantic Writing Taste extension understood by the durable runtime."""

    return {
        EVIDENCE_PAPER_DRAFT_NODE: ModelNodeRegistration(
            EvidencePaperDraftNode,
            EvidencePaperDraftInput,
            EvidencePaperDraftProposal,
        ),
        WRITING_TASTE_NODE: ModelNodeRegistration(
            WritingTasteNode,
            WritingTasteSemanticInput,
            WritingTasteReviewProposal,
        ),
    }


__all__ = [
    "EVIDENCE_PAPER_DRAFT_NODE",
    "WRITING_TASTE_NODE",
    "EvidencePaperDraftNode",
    "WritingTasteNode",
    "render_evidence_paper_markdown",
    "writing_node_types",
]
