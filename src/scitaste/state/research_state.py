"""Canonical persistent state for the complete SciTaste lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.schema.actions import MetaAction
from scitaste.schema.decisions import ResearchDecision


class SciTasteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ResearchStage(StrEnum):
    DISCOVERY = "DISCOVERY"
    PROBLEM_FORMULATION = "PROBLEM_FORMULATION"
    IDEATION = "IDEATION"
    PILOT = "PILOT"
    EVIDENCE = "EVIDENCE"
    COMMUNICATION = "COMMUNICATION"
    REVIEW = "REVIEW"
    COMPLETE = "COMPLETE"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    DROPPED = "DROPPED"


class WorkingHypothesisStatus(StrEnum):
    PROVISIONAL = "provisional"
    SUPPORTED = "supported"
    REFINED = "refined"
    CONTRADICTED = "contradicted"
    DISCARDED = "discarded"


class ResourceBudget(SciTasteModel):
    gpu_hours: float | None = Field(default=None, ge=0)
    max_experiments: int | None = Field(default=None, ge=0)
    max_wall_time_hours: float | None = Field(default=None, ge=0)
    max_api_cost_usd: float | None = Field(default=None, ge=0)
    dataset_constraints: list[str] = Field(default_factory=list)
    compute_constraints: list[str] = Field(default_factory=list)


class ResourceUsage(SciTasteModel):
    gpu_hours: float = Field(default=0.0, ge=0)
    experiments: float = Field(default=0.0, ge=0)
    wall_time_hours: float = Field(default=0.0, ge=0)
    api_cost_usd: float = Field(default=0.0, ge=0)


class LiteratureLandscape(SciTasteModel):
    solved_problems: list[str] = Field(default_factory=list)
    active_problems: list[str] = Field(default_factory=list)
    emerging_directions: list[str] = Field(default_factory=list)
    saturated_directions: list[str] = Field(default_factory=list)
    methodological_bottlenecks: list[str] = Field(default_factory=list)
    evaluation_gaps: list[str] = Field(default_factory=list)
    controversial_findings: list[str] = Field(default_factory=list)
    unexplained_failures: list[str] = Field(default_factory=list)


class ResearchIntuition(SciTasteModel):
    intuition_id: str
    statement: str
    source: str
    supporting_context_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class WorkingHypothesis(SciTasteModel):
    hypothesis_id: str
    statement: str
    derived_from_intuition_ids: list[str] = Field(default_factory=list)
    derived_from_hypothesis_ids: list[str] = Field(default_factory=list)
    falsifiable_predictions: list[str] = Field(default_factory=list)
    proposed_probe_types: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: WorkingHypothesisStatus = WorkingHypothesisStatus.PROVISIONAL


class ResearchObservation(SciTasteModel):
    observation_id: str
    statement: str
    source_result_id: str | None = None
    hypothesis_id: str | None = None
    probe_type: str | None = None
    reproducible: bool | None = None
    stability: float | None = Field(default=None, ge=0.0, le=1.0)
    expected: bool | None = None
    effect_size: float | None = None
    boundary_conditions: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)


class ResearchProblem(SciTasteModel):
    problem_id: str
    observed_phenomenon: str
    boundary_conditions: list[str] = Field(default_factory=list)
    explanation_gap: str
    importance: str
    reproducible: bool
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class ResearchIdea(SciTasteModel):
    idea_id: str
    problem: str
    observation_evidence: str
    hypothesis: str
    proposed_mechanism: str
    expected_validation: list[str] = Field(default_factory=list)
    expected_cost: dict[str, float] = Field(default_factory=dict)
    expected_value: dict[str, float] = Field(default_factory=dict)
    main_risk: str
    generator: str | None = None
    source_problem_ids: list[str] = Field(default_factory=list)
    source_observation_ids: list[str] = Field(default_factory=list)
    status: str = "candidate"


class IdeaPortfolio(SciTasteModel):
    primary_idea_id: str
    low_risk_backup_id: str | None = None
    high_risk_high_reward_id: str | None = None
    diagnostic_only_ids: list[str] = Field(default_factory=list)
    dropped_ids: list[str] = Field(default_factory=list)


class ResearchHypothesis(SciTasteModel):
    hypothesis_id: str
    statement: str
    idea_id: str | None = None
    status: str = "active"


class MethodState(SciTasteModel):
    summary: str
    implementation_ref: str | None = None
    status: str = "proposed"


class ExperimentRecord(SciTasteModel):
    experiment_id: str
    action_id: str
    status: str
    result_ref: str | None = None
    cost: dict[str, float] = Field(default_factory=dict)


class ExperimentPlan(SciTasteModel):
    plan_id: str
    objective: str
    falsifies: list[str] = Field(default_factory=list)
    estimated_cost: dict[str, float] = Field(default_factory=dict)
    target_claim_ids: list[str] = Field(default_factory=list)
    target_evidence_type: str | None = None
    counterfactuals: list[str] = Field(default_factory=list)
    matched_baselines: list[str] = Field(default_factory=list)
    negative_controls: list[str] = Field(default_factory=list)
    expected_information_gain: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidenceItem(SciTasteModel):
    evidence_id: str
    source_type: str
    evidence_type: str = "unspecified"
    experiment_id: str | None = None
    observation: str
    supports_claim_ids: list[str] = Field(default_factory=list)
    contradicts_claim_ids: list[str] = Field(default_factory=list)
    relates_to_claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    stability: float = Field(default=1.0, ge=0.0, le=1.0)
    cost: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def claim_relations_do_not_overlap(self) -> EvidenceItem:
        relations = [
            set(self.supports_claim_ids),
            set(self.contradicts_claim_ids),
            set(self.relates_to_claim_ids),
        ]
        if (
            relations[0] & relations[1]
            or relations[0] & relations[2]
            or relations[1] & relations[2]
        ):
            raise ValueError("one evidence item cannot have multiple relations to the same claim")
        return self


class EvidenceGraph(SciTasteModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)


class ScientificClaim(SciTasteModel):
    claim_id: str
    text: str
    claim_type: str
    strength: str
    required_evidence_types: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    status: str = "unsupported"
    scientific_importance: float = Field(default=0.5, ge=0.0, le=1.0)
    claim_relevance: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def evidence_roles_do_not_overlap(self) -> ScientificClaim:
        overlap = set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids)
        if overlap:
            raise ValueError(f"evidence cannot both support and contradict: {sorted(overlap)}")
        return self


class NarrativeSpine(SciTasteModel):
    core_problem: str
    overlooked_failure: str | None = None
    key_observation: str
    central_insight: str
    proposed_solution: str
    evidence_chain: list[str] = Field(default_factory=list)
    broader_implication: str
    contribution_order: list[str] = Field(default_factory=list)


class SectionContract(SciTasteModel):
    section_name: str
    purpose: str
    required_claim_ids: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    rhetorical_moves: list[str] = Field(default_factory=list)
    word_budget: int = Field(gt=0)


class ParagraphContract(SciTasteModel):
    section_name: str
    paragraph_index: int = Field(ge=1)
    rhetorical_role: str
    input_context: str
    intended_takeaway: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    transition_in: str | None = None
    transition_out: str | None = None


class WritingCritique(SciTasteModel):
    critic: str
    severity: str
    message: str
    finding_id: str | None = None
    code: str | None = None
    dimension: str | None = None
    level: str | None = None
    recommendation: str | None = None
    section_name: str | None = None
    paragraph_index: int | None = Field(default=None, ge=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class WritingState(SciTasteModel):
    status: str = "not_started"
    artifact_refs: list[str] = Field(default_factory=list)
    section_contracts: list[SectionContract] = Field(default_factory=list)
    paragraph_contracts: list[ParagraphContract] = Field(default_factory=list)
    section_drafts: dict[str, str] = Field(default_factory=dict)
    critic_findings: list[WritingCritique] = Field(default_factory=list)
    retrieved_taste_case_ids: list[str] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)


class FigureEntity(SciTasteModel):
    entity_id: str
    label: str
    role: str


class FigureRelation(SciTasteModel):
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    label: str


class FigurePanelPlan(SciTasteModel):
    panel_id: str
    title: str
    objective: str
    entity_ids: list[str] = Field(min_length=1)


class FigureContract(SciTasteModel):
    figure_id: str
    purpose: str
    target_claim_ids: list[str] = Field(min_length=1)
    intended_reader_takeaway: str
    required_entities: list[FigureEntity] = Field(min_length=1)
    required_relations: list[FigureRelation] = Field(default_factory=list)
    optional_entities: list[FigureEntity] = Field(default_factory=list)
    forbidden_emphasis: list[str] = Field(default_factory=list)
    panel_plan: list[FigurePanelPlan] = Field(min_length=1)
    reference_figure_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def internal_references_exist(self) -> FigureContract:
        entity_ids = [
            *(item.entity_id for item in self.required_entities),
            *(item.entity_id for item in self.optional_entities),
        ]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("figure entity ids must be unique")
        known = set(entity_ids)
        relation_ids = [item.relation_id for item in self.required_relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("figure relation ids must be unique")
        for relation in self.required_relations:
            if {relation.source_entity_id, relation.target_entity_id} - known:
                raise ValueError(f"relation {relation.relation_id!r} references unknown entity")
        panel_ids = [panel.panel_id for panel in self.panel_plan]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("figure panel ids must be unique")
        assigned = [entity_id for panel in self.panel_plan for entity_id in panel.entity_ids]
        if set(assigned) - known:
            raise ValueError("panel plan references unknown entity")
        if len(assigned) != len(set(assigned)):
            raise ValueError("an entity cannot be assigned to multiple figure panels")
        if set(item.entity_id for item in self.required_entities) - set(assigned):
            raise ValueError("every required entity must be assigned to a panel")
        if set(self.forbidden_emphasis) - known:
            raise ValueError("forbidden_emphasis references unknown entity")
        return self


class FigureObject(SciTasteModel):
    object_id: str
    label: str
    role: str
    panel_id: str
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    emphasis: str = "normal"


class FigureCritique(SciTasteModel):
    dimension: str
    category: str
    score: int = Field(ge=1, le=5)
    severity: str
    message: str
    object_ids: list[str] = Field(default_factory=list)
    suggested_operation: str | None = None


class FigurePatch(SciTasteModel):
    operation: str
    object_id: str
    field: str
    old_value: str
    new_value: str
    rationale: str


class FigureState(SciTasteModel):
    status: str = "not_started"
    figure_refs: list[str] = Field(default_factory=list)
    contract: FigureContract | None = None
    semantic_objects: list[FigureObject] = Field(default_factory=list)
    initial_critic_report: list[FigureCritique] = Field(default_factory=list)
    final_critic_report: list[FigureCritique] = Field(default_factory=list)
    patch_history: list[FigurePatch] = Field(default_factory=list)
    retrieved_taste_case_ids: list[str] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def semantic_objects_match_contract(self) -> FigureState:
        if self.contract is None or not self.semantic_objects:
            return self
        entity_ids = {
            item.entity_id
            for item in [*self.contract.required_entities, *self.contract.optional_entities]
        }
        object_ids = [item.object_id for item in self.semantic_objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("figure semantic object ids must be unique")
        if set(object_ids) - entity_ids:
            raise ValueError("figure state contains objects outside its contract")
        declared_panels = {
            entity_id: panel.panel_id
            for panel in self.contract.panel_plan
            for entity_id in panel.entity_ids
        }
        if any(
            item.panel_id != declared_panels.get(item.object_id) for item in self.semantic_objects
        ):
            raise ValueError("figure semantic object violates the declared panel plan")
        if set(patch.object_id for patch in self.patch_history) - set(object_ids):
            raise ValueError("figure patch references an unknown semantic object")
        return self


class ReviewerConcern(SciTasteModel):
    concern_id: str
    category: str
    severity: str
    target_claim_ids: list[str] = Field(default_factory=list)
    target_section: str | None = None
    text: str
    requires_new_evidence: bool = False
    requires_new_experiment: bool = False
    required_evidence_types: list[str] = Field(default_factory=list)
    status: str = "open"


class ResearchObligation(SciTasteModel):
    obligation_id: str
    concern_id: str
    action_type: str
    required_action: dict[str, Any]
    target_claim_ids: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    estimated_cost: dict[str, float] = Field(default_factory=dict)
    evidence_ids_at_open: list[str] = Field(default_factory=list)
    resolution_evidence_ids: list[str] = Field(default_factory=list)
    resolution_summary: str | None = None
    opened_at_revision: int = Field(default=0, ge=0)
    status: str = "open"


class StateTransition(SciTasteModel):
    transition_id: str
    decision_id: str
    action_type: MetaAction
    from_stage: ResearchStage
    to_stage: ResearchStage
    state_revision: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchState(SciTasteModel):
    """Single source of truth updated after every selected research action."""

    schema_version: str = "1.0"
    revision: int = Field(default=0, ge=0)
    project_id: str

    research_direction: str
    target_domain: str
    target_venue: str | None = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)

    literature_landscape: LiteratureLandscape | None = None
    research_intuitions: list[ResearchIntuition] = Field(default_factory=list)
    working_hypotheses: list[WorkingHypothesis] = Field(default_factory=list)
    observations: list[ResearchObservation] = Field(default_factory=list)
    problem_candidates: list[ResearchProblem] = Field(default_factory=list)
    active_working_hypothesis_id: str | None = None
    active_problem_id: str | None = None

    candidate_ideas: list[ResearchIdea] = Field(default_factory=list)
    active_idea_id: str | None = None
    idea_portfolio: IdeaPortfolio | None = None

    hypotheses: list[ResearchHypothesis] = Field(default_factory=list)
    method_state: MethodState | None = None

    experiment_history: list[ExperimentRecord] = Field(default_factory=list)
    current_experiment_plan: ExperimentPlan | None = None

    evidence_graph: EvidenceGraph = Field(default_factory=EvidenceGraph)
    claims: list[ScientificClaim] = Field(default_factory=list)
    interpretation_history: list[dict[str, Any]] = Field(default_factory=list)

    narrative_spine: NarrativeSpine | None = None
    writing_state: WritingState | None = None
    figure_state: FigureState | None = None

    reviewer_concerns: list[ReviewerConcern] = Field(default_factory=list)
    open_research_obligations: list[ResearchObligation] = Field(default_factory=list)

    current_stage: ResearchStage = ResearchStage.DISCOVERY
    decision_history: list[ResearchDecision] = Field(default_factory=list)
    transition_history: list[StateTransition] = Field(default_factory=list)
    taste_context_ids: list[str] = Field(default_factory=list)
    status: ProjectStatus = ProjectStatus.ACTIVE
    executor_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def active_references_exist(self) -> ResearchState:
        working_ids = {item.hypothesis_id for item in self.working_hypotheses}
        problem_ids = {item.problem_id for item in self.problem_candidates}
        idea_ids = {item.idea_id for item in self.candidate_ideas}
        checks = (
            (self.active_working_hypothesis_id, working_ids, "working hypothesis"),
            (self.active_problem_id, problem_ids, "problem"),
            (self.active_idea_id, idea_ids, "idea"),
        )
        for active_id, known_ids, label in checks:
            if active_id is not None and active_id not in known_ids:
                raise ValueError(f"active {label} id {active_id!r} is not present in state")
        if self.idea_portfolio is not None:
            portfolio_ids = {
                self.idea_portfolio.primary_idea_id,
                self.idea_portfolio.low_risk_backup_id,
                self.idea_portfolio.high_risk_high_reward_id,
                *self.idea_portfolio.diagnostic_only_ids,
                *self.idea_portfolio.dropped_ids,
            } - {None}
            unknown = portfolio_ids - idea_ids
            if unknown:
                raise ValueError(f"idea portfolio references unknown ids: {sorted(unknown)}")
        claim_ids = [claim.claim_id for claim in self.claims]
        evidence_ids = [item.evidence_id for item in self.evidence_graph.items]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim ids must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence ids must be unique")
        known_claims = set(claim_ids)
        known_evidence = set(evidence_ids)
        for item in self.evidence_graph.items:
            targets = {
                *item.supports_claim_ids,
                *item.contradicts_claim_ids,
                *item.relates_to_claim_ids,
            }
            if targets - known_claims:
                raise ValueError(f"evidence {item.evidence_id!r} references unknown claims")
        for claim in self.claims:
            linked = {*claim.supporting_evidence_ids, *claim.contradicting_evidence_ids}
            if linked - known_evidence:
                raise ValueError(f"claim {claim.claim_id!r} references unknown evidence")
        if self.narrative_spine is not None:
            unknown = set(self.narrative_spine.evidence_chain) - known_evidence
            if unknown:
                raise ValueError(f"narrative spine references unknown evidence: {sorted(unknown)}")
            unknown = set(self.narrative_spine.contribution_order) - known_claims
            if unknown:
                raise ValueError(f"narrative spine references unknown claims: {sorted(unknown)}")
        if self.writing_state is not None:
            section_names = [item.section_name for item in self.writing_state.section_contracts]
            if len(section_names) != len(set(section_names)):
                raise ValueError("section contract names must be unique")
            for contract in self.writing_state.section_contracts:
                if set(contract.required_claim_ids) - known_claims:
                    raise ValueError(f"section {contract.section_name!r} references unknown claims")
                if set(contract.required_evidence_ids) - known_evidence:
                    raise ValueError(
                        f"section {contract.section_name!r} references unknown evidence"
                    )
            for contract in self.writing_state.paragraph_contracts:
                if contract.section_name not in set(section_names):
                    raise ValueError(
                        f"paragraph references unknown section {contract.section_name!r}"
                    )
                if set(contract.claim_ids) - known_claims:
                    raise ValueError("paragraph contract references unknown claims")
                if set(contract.evidence_ids) - known_evidence:
                    raise ValueError("paragraph contract references unknown evidence")
        if self.figure_state is not None and self.figure_state.contract is not None:
            contract = self.figure_state.contract
            if set(contract.target_claim_ids) - known_claims:
                raise ValueError("figure contract references unknown claims")
        concern_ids = [concern.concern_id for concern in self.reviewer_concerns]
        obligation_ids = [item.obligation_id for item in self.open_research_obligations]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("reviewer concern ids must be unique")
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ValueError("research obligation ids must be unique")
        known_concerns = set(concern_ids)
        for concern in self.reviewer_concerns:
            if set(concern.target_claim_ids) - known_claims:
                raise ValueError(f"concern {concern.concern_id!r} references unknown claims")
        for obligation in self.open_research_obligations:
            if obligation.concern_id not in known_concerns:
                raise ValueError(
                    f"obligation {obligation.obligation_id!r} references unknown concern"
                )
            if set(obligation.target_claim_ids) - known_claims:
                raise ValueError(
                    f"obligation {obligation.obligation_id!r} references unknown claims"
                )
            if set(obligation.resolution_evidence_ids) - known_evidence:
                raise ValueError(
                    f"obligation {obligation.obligation_id!r} references unknown evidence"
                )
        return self
