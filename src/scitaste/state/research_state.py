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


class EvidenceItem(SciTasteModel):
    evidence_id: str
    source_type: str
    experiment_id: str | None = None
    observation: str
    supports_claim_ids: list[str] = Field(default_factory=list)
    contradicts_claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    cost: dict[str, float] = Field(default_factory=dict)


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


class NarrativeSpine(SciTasteModel):
    core_problem: str
    overlooked_failure: str | None = None
    key_observation: str
    central_insight: str
    proposed_solution: str
    evidence_chain: list[str] = Field(default_factory=list)
    broader_implication: str
    contribution_order: list[str] = Field(default_factory=list)


class WritingState(SciTasteModel):
    status: str = "not_started"
    artifact_refs: list[str] = Field(default_factory=list)


class FigureState(SciTasteModel):
    status: str = "not_started"
    figure_refs: list[str] = Field(default_factory=list)


class ReviewerConcern(SciTasteModel):
    concern_id: str
    category: str
    severity: str
    target_claim_ids: list[str] = Field(default_factory=list)
    target_section: str | None = None
    text: str
    requires_new_evidence: bool = False
    requires_new_experiment: bool = False
    status: str = "open"


class ResearchObligation(SciTasteModel):
    obligation_id: str
    concern_id: str
    action_type: str
    required_action: dict[str, Any]
    target_claim_ids: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    estimated_cost: dict[str, float] = Field(default_factory=dict)
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
        return self
