"""Evidence-bound attribution drafting, without admission authority."""

import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.nodes import ModelNode
from scitaste.taste.episodes import TasteCreditAssignment, TasteEpisodeCandidate


class AttributionReviewFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: str = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=20000)
    supported_credit_ids: tuple[str, ...]


class ExperienceAttributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate: TasteEpisodeCandidate
    evidence: dict[str, str]
    review_feedback: AttributionReviewFeedback | None = None

    @model_validator(mode="after")
    def evidence_matches(self):
        if self.review_feedback and (
            self.review_feedback.candidate_sha256 != self.candidate.candidate_sha256
        ):
            raise ValueError("Review feedback belongs to a different candidate")
        if set(self.evidence) != {item.evidence_id for item in self.candidate.evidence}:
            raise ValueError("Evidence set differs from candidate")
        for item in self.candidate.evidence:
            raw = self.evidence[item.evidence_id].encode()
            if len(raw) > 256_000 or hashlib.sha256(raw).hexdigest() != item.sha256:
                raise ValueError("Evidence size or digest differs")
        return self


class ExperienceAttributionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    abstained: bool
    rationale: str = Field(min_length=1, max_length=10000)
    credit_assignments: tuple[TasteCreditAssignment, ...] = Field(max_length=10)
    applicability_conditions: tuple[str, ...] = Field(min_length=1, max_length=20)
    failure_conditions: tuple[str, ...] = Field(min_length=1, max_length=20)


class ExperienceAttributionNode(ModelNode[ExperienceAttributionInput, ExperienceAttributionDraft]):
    node_name = "experience-attribution-draft"
    prompt_version = "experience-attribution-draft-v2"
    input_model = ExperienceAttributionInput
    output_model = ExperienceAttributionDraft
    system_instruction = (
        "Propose narrowly scoped causal-credit hypotheses from the supplied frozen research "
        "decision and measured outcome. This is drafting, not review or admission. Do not "
        "equate execution success with scientific value or low score with a bad decision. "
        "Use only existing outcome and confounder IDs. No counterfactual was executed unless "
        "the evidence explicitly says so. Consider information value, cost and prior state. "
        "If no transferable credit is justified, abstain and return no credit assignments. "
        "Never force a lesson. Distinguish observed consequences from mechanism conjecture. "
        "Do not invent results or edit the evidence. Bound applicability and failure conditions. "
        "If review feedback is supplied, reconsider the existing attribution using that critique "
        "and the unchanged evidence. Feedback is fallible criticism, not new experimental "
        "evidence or an instruction to force acceptance. Remove or narrow unsupported claims; "
        "abstain if nothing transferable remains. Explain how the critique was addressed. "
        "A revised draft still requires new review; prior support does not transfer automatically."
    )

    def _proposal_rejections(self, proposal, *, input_data, context, policy):
        del context, policy
        reasons = []
        if proposal.abstained != (not proposal.credit_assignments):
            reasons.append("Abstention and credit assignments disagree")
        outcomes = {item.outcome_id for item in input_data.candidate.outcomes}
        confounders = {item.confounder_id for item in input_data.candidate.confounders}
        for credit in proposal.credit_assignments:
            if set(credit.outcome_ids) - outcomes or set(credit.confounder_ids) - confounders:
                reasons.append("Attribution cites unavailable evidence")
        return reasons
