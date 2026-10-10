"""Content-bound revision of unapproved manuscripts without approval authority."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.model_nodes.nodes import ModelNode


class CandidateRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    paper_sha256: str
    paragraphs: dict[str, str]
    protected_blocks: dict[str, str] = Field(default_factory=dict)
    concerns: dict[str, str]
    evidence: dict[str, str]
    format_feedback: tuple[str, ...] = ()


class CandidateParagraphEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    paragraph_id: str
    replacement: str = Field(min_length=1, max_length=18000)
    concern_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class CandidateConcernResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    concern_id: str
    disposition: Literal["revised-in-text", "pending-evidence", "not-addressed"]
    explanation: str = Field(min_length=1, max_length=4000)


class CandidateRevisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    paper_sha256: str
    edits: tuple[CandidateParagraphEdit, ...] = Field(min_length=1, max_length=30)
    responses: tuple[CandidateConcernResponse, ...] = Field(min_length=1, max_length=80)


class CandidateRevisionNode(ModelNode[CandidateRevisionInput, CandidateRevisionProposal]):
    node_name = "candidate-paper-revision"
    prompt_version = "candidate-paper-revision-v3"
    input_model = CandidateRevisionInput
    output_model = CandidateRevisionProposal
    system_instruction = (
        "Revise an unapproved manuscript using its actual review and supplied evidence. "
        "Return only paragraph replacements, not an entire paper or a pasted input. "
        "Copy paper_sha256 exactly. Leave heading/title blocks unchanged. "
        "Only IDs in paragraphs are editable; protected_blocks provides read-only section "
        "context and must never be targeted. IDs are opaque: do not infer or renumber them. "
        "Use each paragraph_id at most once; consolidate all changes to it in one replacement. "
        "If format_feedback is present, correct those rejected output constraints. "
        "Preserve existing figure references and paths; never invent image files. "
        "Correct conflation of successful experiment completion with later agent interruption. "
        "Use existing evidence to define the metric and describe methods. Remove administrative "
        "phrases such as proposal-only and venue readiness from the scientific narrative. "
        "Preserve negative measurements, uncertainty and limitations. Do not invent citations, "
        "new experiments, mechanisms, improvements or review approval. A reviewer is fallible; "
        "do not execute requested experiments. A literature gap may remain pending-evidence. "
        "Respond once to every concern. Revised-in-text means proposed text, not verified "
        "resolution. Cite evidence IDs in edit metadata for factual changes. Keep replacements "
        "concise and coherent across the entire manuscript; do not insert Markdown headings."
    )

    def _proposal_rejections(self, proposal, *, input_data, context, policy):
        del context, policy
        reasons = []
        if proposal.paper_sha256 != input_data.paper_sha256:
            reasons.append("Revision targets different paper bytes")
        targets = [edit.paragraph_id for edit in proposal.edits]
        if len(set(targets)) != len(targets) or set(targets) - input_data.paragraphs.keys():
            reasons.append("Revision paragraph targets are duplicated or unknown")
        responses = [response.concern_id for response in proposal.responses]
        if len(set(responses)) != len(responses) or set(responses) != set(input_data.concerns):
            reasons.append("Every concern requires exactly one response")
        for edit in proposal.edits:
            if (
                set(edit.concern_ids) - input_data.concerns.keys()
                or set(edit.evidence_ids) - input_data.evidence.keys()
            ):
                reasons.append("Revision references unavailable concerns or evidence")
            if input_data.paragraphs.get(edit.paragraph_id, "").lstrip().startswith("#"):
                reasons.append("Revision cannot replace heading blocks")
            if any(line.lstrip().startswith("#") for line in edit.replacement.splitlines()):
                reasons.append("Replacement cannot insert section headings")
        for response in proposal.responses:
            if response.disposition == "revised-in-text" and not any(
                response.concern_id in edit.concern_ids for edit in proposal.edits
            ):
                reasons.append("Text response has no linked edit")
        return reasons


def paragraph_map(markdown: str):
    blocks = markdown.strip().split("\n\n")
    return {f"p-{index:03d}": block for index, block in enumerate(blocks)}


def apply_candidate_revision(markdown, packet, proposal):
    if hashlib.sha256(markdown.encode()).hexdigest() != packet.paper_sha256:
        raise ValueError("Original paper changed")
    original = paragraph_map(markdown)
    if set(packet.paragraphs) & set(packet.protected_blocks):
        raise ValueError("Editable and protected paragraph IDs overlap")
    if original != {**packet.paragraphs, **packet.protected_blocks}:
        raise ValueError("Original paragraph projection changed")
    reasons = CandidateRevisionNode()._proposal_rejections(
        proposal,
        input_data=packet,
        context=None,
        policy=None,
    )
    if reasons:
        raise ValueError("; ".join(reasons))
    replacements = {edit.paragraph_id: edit.replacement for edit in proposal.edits}
    return "\n\n".join(replacements.get(key, text) for key, text in original.items()) + "\n"
