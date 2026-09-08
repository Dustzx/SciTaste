"""Proposal-only semantic node for paper-level Writing Taste decisions."""

from __future__ import annotations

from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.runtime import ModelNodeRegistration
from scitaste.writing.semantic_models import (
    WRITING_TASTE_NODE,
    WritingRevisionAction,
    WritingTasteReviewProposal,
    WritingTasteSemanticInput,
)


class WritingTasteNode(ModelNode[WritingTasteSemanticInput, WritingTasteReviewProposal]):
    """Judge semantic writing choices while retaining deterministic acceptance authority."""

    node_name = WRITING_TASTE_NODE
    prompt_version = "writing-taste-v1"
    system_instruction = (
        "Review the registered manuscript as scientific writing at paper, section, paragraph, "
        "sentence, and phrase levels. Evaluate scientific positioning, narrative focus, "
        "argumentative structure, evidence prioritization, claim calibration, positive-scope "
        "anti-defensive style, reader guidance, venue fit, terminology, and global coherence. "
        "Anti-defensive style is only one dimension. Scientific integrity, claim-evidence "
        "calibration, and material limitations outrank persuasion: never hide counterevidence, "
        "omit a registered material limitation, expand a claim, invent evidence, or treat "
        "selective reporting as stronger writing. Prefer a direct evidence-centered story over "
        "a project log. Return advisory data only; do not rewrite files, mutate state, call "
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
        WRITING_TASTE_NODE: ModelNodeRegistration(
            WritingTasteNode,
            WritingTasteSemanticInput,
            WritingTasteReviewProposal,
        )
    }


__all__ = ["WRITING_TASTE_NODE", "WritingTasteNode", "writing_node_types"]
