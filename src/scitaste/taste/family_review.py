"""Outcome-blind cross-model review for Scientific Taste decision families."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResult, NodeResultStatus
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.openai_compatible import StructuredOpenAICompatibleConfig
from scitaste.model_nodes.profiles import ModelNodeProfile, validate_profile_binding
from scitaste.model_nodes.runtime import (
    ModelNodeRegistration,
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeBackendMode,
    RuntimeOutcome,
)
from scitaste.model_nodes.runtime_config import LiveRuntimeBackend, ModelNodeRuntimeConfig
from scitaste.project import ProjectRuntime
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding, idea_binding_matches_current
from scitaste.project.models import content_sha256
from scitaste.taste.decision_families import (
    SCIENTIFIC_TASTE_DECISION_FAMILY_DESCRIPTIONS,
    SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256,
    SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION,
    ScientificDecisionFamilyAssignment,
    ScientificDecisionFamilyReview,
    ScientificTasteDecisionFamily,
)
from scitaste.taste.episode_learning import AdmittedTasteEpisode
from scitaste.taste.episodes import TasteEpisodeAlternative

SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE = "scientific-decision-family-review"
_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class ScientificDecisionFamilyReviewInput(BaseModel):
    """Outcome-blind episode projection over the fixed seven-family ontology."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    admission_id: str
    admission_sha256: str = Field(pattern=_SHA256)
    idea_revision_binding_sha256: str = Field(pattern=_SHA256)
    stage: str
    state_summary: str
    alternatives: tuple[TasteEpisodeAlternative, ...] = Field(min_length=2, max_length=30)
    selected_action_id: str
    decision_principle: str
    why_preferred: str
    applicability_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    failure_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    counterfactual_probe: str
    ontology_version: Literal[SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION] = (
        SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION
    )
    ontology_sha256: str = Field(pattern=_SHA256)
    family_descriptions: dict[ScientificTasteDecisionFamily, str]
    packet_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def input_is_closed(self) -> ScientificDecisionFamilyReviewInput:
        if self.ontology_sha256 != SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256:
            raise ValueError("decision-family review uses another ontology")
        if self.family_descriptions != SCIENTIFIC_TASTE_DECISION_FAMILY_DESCRIPTIONS:
            raise ValueError("decision-family review descriptions differ from the ontology")
        if self.selected_action_id not in {item.action_id for item in self.alternatives}:
            raise ValueError("decision-family selected action is outside alternatives")
        expected = content_sha256(self.model_dump(mode="json", exclude={"packet_sha256"}))
        if self.packet_sha256 != expected:
            raise ValueError("decision-family review packet hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> ScientificDecisionFamilyReviewInput:
        payload = {
            "schema_version": "1.0",
            "ontology_version": SCIENTIFIC_TASTE_DECISION_ONTOLOGY_VERSION,
            "ontology_sha256": SCIENTIFIC_TASTE_DECISION_ONTOLOGY_SHA256,
            "family_descriptions": SCIENTIFIC_TASTE_DECISION_FAMILY_DESCRIPTIONS,
            **values,
        }
        payload.pop("packet_sha256", None)
        unsigned = cls.model_construct(packet_sha256="0" * 64, **payload)
        return cls(
            **payload,
            packet_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"packet_sha256"})
            ),
        )


class ScientificDecisionFamilyReviewProposal(BaseModel):
    """Untrusted outcome-blind ontology assignment from one AI reviewer."""

    model_config = _CONFIG

    packet_sha256: str = Field(pattern=_SHA256)
    decision_family: ScientificTasteDecisionFamily
    rationale: str = Field(min_length=1, max_length=10_000)


class ScientificDecisionFamilyReviewMaterial(BaseModel):
    model_config = _CONFIG

    project_id: str
    project_revision: int = Field(ge=0)
    node_input: ScientificDecisionFamilyReviewInput


class ScientificDecisionFamilyReviewNode(
    ModelNode[ScientificDecisionFamilyReviewInput, ScientificDecisionFamilyReviewProposal]
):
    """Assign one decision to exactly one scientific-judgment family."""

    node_name = SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE
    prompt_version = "scientific-decision-family-review-v1"
    system_instruction = (
        "Assign the supplied research decision to exactly one member of the fixed Scientific "
        "Taste decision-family ontology. Use only the decision-time state, alternatives, selected "
        "action, rationale, applicability limits, and counterfactual. Outcomes, credit labels, "
        "experiment conditions, paper claims, and other reviews are deliberately unavailable; do "
        "not infer them. Choose the family describing the primary judgment exercised by this "
        "decision, not its lifecycle stage or eventual result. This is isolated AI review, not "
        "human validation, and it cannot change the episode or policy."
    )
    input_model = ScientificDecisionFamilyReviewInput
    output_model = ScientificDecisionFamilyReviewProposal

    def _proposal_rejections(
        self,
        proposal: ScientificDecisionFamilyReviewProposal,
        *,
        input_data: ScientificDecisionFamilyReviewInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        if proposal.packet_sha256 != input_data.packet_sha256:
            reasons.append("decision-family review targets another packet")
        if context.state_snapshot_id != input_data.packet_sha256:
            reasons.append("decision-family context targets another packet")
        if context.stage != "TASTE_DECISION_FAMILY_REVIEW":
            reasons.append("decision-family context uses another stage")
        if (
            context.claim_ids
            or context.evidence_ids
            or context.section_ids
            or context.candidate_actions
        ):
            reasons.append("decision-family context exposes outcome or project state")
        return sorted(set(reasons))


def family_review_node_types() -> dict[str, ModelNodeRegistration]:
    return {
        SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE: ModelNodeRegistration(
            ScientificDecisionFamilyReviewNode,
            ScientificDecisionFamilyReviewInput,
            ScientificDecisionFamilyReviewProposal,
        )
    }


def build_scientific_decision_family_review_material(
    runtime: ProjectRuntime,
    episode: AdmittedTasteEpisode,
    *,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> ScientificDecisionFamilyReviewMaterial:
    """Project an admitted episode without any outcome or causal-credit field."""

    if not idea_binding_matches_current(episode.candidate.idea_revision, current_idea_revision):
        raise ValueError("decision-family review episode belongs to another Idea revision")
    if not episode.policy_training_eligible:
        raise ValueError("decision-family review requires a policy-training-eligible episode")
    snapshot = runtime.open(episode.candidate.project_id)
    candidate = episode.candidate
    return ScientificDecisionFamilyReviewMaterial(
        project_id=candidate.project_id,
        project_revision=snapshot.revision,
        node_input=ScientificDecisionFamilyReviewInput.create(
            admission_id=episode.admission_id,
            admission_sha256=episode.admission_sha256,
            idea_revision_binding_sha256=candidate.idea_revision.binding_sha256,
            stage=candidate.stage,
            state_summary=candidate.state_summary,
            alternatives=candidate.alternatives,
            selected_action_id=candidate.selected_action_id,
            decision_principle=candidate.decision_principle,
            why_preferred=candidate.why_preferred,
            applicability_conditions=candidate.applicability_conditions,
            failure_conditions=candidate.failure_conditions,
            counterfactual_probe=candidate.counterfactual_probe,
        ),
    )


def build_scientific_decision_family_runtime_config(
    material: ScientificDecisionFamilyReviewMaterial,
    *,
    profile: ModelNodeProfile,
    backend_config: StructuredOpenAICompatibleConfig,
) -> ModelNodeRuntimeConfig:
    """Build one provider-bound, no-secret family-review runtime config."""

    if SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE not in profile.allowed_node_names:
        raise ValueError("selected model profile does not permit decision-family review")
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("decision-family review backend identity differs from its profile")
    if backend_config.max_output_tokens < profile.generation.max_output_tokens:
        raise ValueError("decision-family review backend output ceiling is below its profile")
    policy = NodePolicy(
        policy_id=f"{profile.profile_id}-family-policy-v1",
        enabled=True,
        allowed_node_names=[SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE],
        expected_backend=profile.provider,
        expected_model=profile.model,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    validate_profile_binding(
        profile,
        policy,
        node_name=SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE,
    )
    node_input = material.node_input
    return ModelNodeRuntimeConfig(
        node_name=SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE,
        node_input=node_input.model_dump(mode="json"),
        state_projection=ImmutableStateProjection(
            project_id=material.project_id,
            state_snapshot_id=node_input.packet_sha256,
            state_revision=material.project_revision,
            stage="TASTE_DECISION_FAMILY_REVIEW",
            metadata={
                "admission_sha256": node_input.admission_sha256,
                "outcomes_exposed": False,
                "paper_claims_exposed": False,
            },
        ),
        trigger=ModelNodeTrigger(
            trigger_id=f"family-{node_input.admission_id}",
            reason="Outcome-blind AI assignment to the fixed Scientific Taste ontology.",
        ),
        policy=policy,
        backend=LiveRuntimeBackend(config=backend_config),
        seed=0,
    )


def scientific_decision_family_review_from_runtime(
    runtime: ProjectRuntime,
    episode: AdmittedTasteEpisode,
    *,
    project_id: str,
    run_id: str,
    invocation_id: str,
    reviewer_id: str,
    role: Literal["primary", "adjudicator"],
) -> ScientificDecisionFamilyReview:
    """Import one actual generation from the verified project ledger."""

    if project_id != episode.candidate.project_id:
        raise ValueError("decision-family review project differs from the episode")
    from scitaste.model_nodes.registry import first_party_node_types

    entry = ModelNodeRuntime(runtime, node_types=first_party_node_types()).entry(
        project_id=project_id,
        run_id=run_id,
        invocation_id=invocation_id,
    )
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("decision-family import requires an accepted runtime entry")
    if entry.intent.backend_mode not in {RuntimeBackendMode.LIVE, RuntimeBackendMode.LOCAL}:
        raise ValueError("decision-family review requires an actual model generation")
    if entry.intent.node_name != SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE:
        raise ValueError("runtime entry is not a decision-family review")
    result = NodeResult[ScientificDecisionFamilyReviewProposal].model_validate(entry.result)
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("decision-family runtime entry has no accepted proposal")
    node_input = ScientificDecisionFamilyReviewInput.model_validate(entry.intent.node_input)
    if (
        node_input.admission_id != episode.admission_id
        or node_input.admission_sha256 != episode.admission_sha256
        or node_input.idea_revision_binding_sha256 != episode.candidate.idea_revision.binding_sha256
    ):
        raise ValueError("decision-family runtime input binds another episode")
    if result.proposal.packet_sha256 != node_input.packet_sha256:
        raise ValueError("decision-family proposal binds another packet")
    return ScientificDecisionFamilyReview(
        reviewer_id=reviewer_id,
        invocation_id=entry.intent.invocation_id,
        model_identifier=f"{result.response.backend}:{result.response.model}",
        role=role,
        decision_family=result.proposal.decision_family,
        rationale=result.proposal.rationale,
        raw_response_sha256=result.response.raw_response_sha256,
        runtime_bound=True,
        admission_id=episode.admission_id,
        admission_sha256=episode.admission_sha256,
        packet_sha256=node_input.packet_sha256,
        provider_id=result.response.backend,
        model_id=result.response.model,
        project_run_id=entry.intent.run_id,
        ledger_entry_sha256=entry.entry_sha256,
    )


def compile_scientific_decision_family_assignment(
    episode: AdmittedTasteEpisode,
    reviews: tuple[ScientificDecisionFamilyReview, ...],
    *,
    assignment_id: str,
) -> ScientificDecisionFamilyAssignment:
    """Resolve agreement or one adjudication without a manual family label."""

    primary = tuple(item for item in reviews if item.role == "primary")
    adjudicators = tuple(item for item in reviews if item.role == "adjudicator")
    if len(primary) != 2:
        raise ValueError("decision-family panel requires exactly two primary reviews")
    primary_families = {item.decision_family for item in primary}
    if len(primary_families) == 1:
        if adjudicators:
            raise ValueError("unanimous decision-family panel does not use adjudication")
        decision_family = primary[0].decision_family
        decisive = primary
    else:
        if len(adjudicators) != 1:
            raise ValueError("split decision-family panel requires one adjudicator")
        decision_family = adjudicators[0].decision_family
        decisive = (*primary, adjudicators[0])
    rationale = " ".join(item.rationale for item in decisive)
    return ScientificDecisionFamilyAssignment.create(
        assignment_id=assignment_id,
        admission_id=episode.admission_id,
        admission_sha256=episode.admission_sha256,
        decision_family=decision_family,
        observed_outcome_families=tuple(
            item.family for item in episode.candidate.credit_assignments
        ),
        rationale=rationale,
        reviews=reviews,
    )


__all__ = [
    "SCIENTIFIC_DECISION_FAMILY_REVIEW_NODE",
    "ScientificDecisionFamilyReviewInput",
    "ScientificDecisionFamilyReviewMaterial",
    "ScientificDecisionFamilyReviewNode",
    "ScientificDecisionFamilyReviewProposal",
    "build_scientific_decision_family_review_material",
    "build_scientific_decision_family_runtime_config",
    "compile_scientific_decision_family_assignment",
    "family_review_node_types",
    "scientific_decision_family_review_from_runtime",
]
