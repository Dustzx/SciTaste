"""Schemas for Phase 9 matched-budget system studies."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudyCategory(StrEnum):
    DIAGNOSIS_FRIENDLY = "diagnosis_friendly"
    CLEAR_HYPOTHESIS = "clear_hypothesis"
    NEW_FORMULATION = "new_formulation"
    AMBIGUOUS_DIRECTION = "ambiguous_direction"


class SystemCondition(StrEnum):
    AUTORESEARCHCLAW = "autoresearchclaw"
    KNOWLEDGE_RAG = "knowledge_rag"
    TASTE_LIBRARY = "taste_library"
    FULL_SCITASTE = "full_scitaste"
    SIBYL = "sibyl"
    AI_SCIENTIST_V2 = "ai_scientist_v2"


class StudyStatus(StrEnum):
    INCOMPLETE = "incomplete"
    ACCEPTANCE_ONLY = "acceptance_only"
    ELIGIBLE = "eligible"


class CellStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvidenceClass(StrEnum):
    REAL = "real"
    SYNTHETIC = "synthetic"


class ReviewSource(StrEnum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    SYNTHETIC = "synthetic"


class StudyBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gpu_hours: float = Field(gt=0)
    max_experiments: int = Field(gt=0)
    max_wall_time_hours: float = Field(gt=0)
    max_api_cost_usd: float = Field(gt=0)
    max_search_queries: int = Field(ge=0)
    max_llm_tokens: int = Field(gt=0)


class SearchAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str
    provider: str
    frozen_snapshot: str


class StudyTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    category: StudyCategory
    research_direction: str = Field(min_length=1)
    domain: str
    asset_path: str
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_discovery_behavior: str = Field(min_length=1)
    self_referential: bool = False

    @model_validator(mode="after")
    def independent_task(self) -> StudyTask:
        if self.self_referential:
            raise ValueError("matched-budget headline tasks cannot be self-referential")
        return self


class StudyConditionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: SystemCondition
    enabled: bool
    implementation_ref: str | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def availability_is_explicit(self) -> StudyConditionConfig:
        if self.enabled and not self.implementation_ref:
            raise ValueError("enabled conditions require implementation_ref")
        if not self.enabled and not self.unavailable_reason:
            raise ValueError("disabled conditions require unavailable_reason")
        return self


class ExpertPanelProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_version: str
    min_reviewers_per_cell: int = Field(ge=2)
    condition_blinded: bool
    adjudication_required_on_conflict: bool
    dimensions: list[str] = Field(min_length=1)


class MatchedStudyProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: str
    version: str
    description: str
    base_model: str
    base_model_revision: str
    codebase_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    search_access: SearchAccess
    budget: StudyBudget
    seeds: list[int] = Field(min_length=1)
    repetitions_per_seed: int = Field(default=1, gt=0)
    tasks: list[StudyTask] = Field(min_length=1)
    conditions: list[StudyConditionConfig] = Field(min_length=1)
    expert_panel: ExpertPanelProtocol
    preregistered_outcomes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def matrix_is_matched(self) -> MatchedStudyProtocol:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("study seeds must be unique")
        task_ids = [task.task_id for task in self.tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("study task ids must be unique")
        categories = {task.category for task in self.tasks}
        if categories != set(StudyCategory):
            raise ValueError("study must cover all four research task categories")
        condition_ids = [condition.condition for condition in self.conditions]
        if len(set(condition_ids)) != len(condition_ids):
            raise ValueError("study conditions must be unique")
        if set(condition_ids) != set(SystemCondition):
            raise ValueError("study must register all required comparison conditions")
        enabled = {condition.condition for condition in self.conditions if condition.enabled}
        core = {
            SystemCondition.AUTORESEARCHCLAW,
            SystemCondition.KNOWLEDGE_RAG,
            SystemCondition.TASTE_LIBRARY,
            SystemCondition.FULL_SCITASTE,
        }
        if not core.issubset(enabled):
            raise ValueError("all four core conditions must be enabled")
        if not self.expert_panel.condition_blinded:
            raise ValueError("expert evaluation must be condition blinded")
        return self

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class StudyCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    blind_id: str
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    condition: SystemCondition
    seed: int
    repetition: int = Field(ge=0)
    budget: StudyBudget


class StudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    study_id: str
    study_version: str
    protocol_sha256: str
    cells: list[StudyCell]
    disabled_conditions: dict[SystemCondition, str]
    readiness_blockers: list[str]

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class StudyUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gpu_hours: float | None = Field(default=None, ge=0)
    experiments: int | None = Field(default=None, ge=0)
    wall_time_hours: float | None = Field(default=None, ge=0)
    api_cost_usd: float | None = Field(default=None, ge=0)
    search_queries: int | None = Field(default=None, ge=0)
    llm_tokens: int | None = Field(default=None, ge=0)


class StudyOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    useful_results: int = Field(ge=0)
    proposed_ideas: int = Field(ge=0)
    valid_ideas: int = Field(ge=0)
    pilots: int = Field(ge=0)
    discarded_ideas: int = Field(ge=0)
    unproductive_experiments: int = Field(ge=0)
    total_experiments: int = Field(ge=0)
    gpu_hours_before_useful_signal: float | None = Field(default=None, ge=0)
    pivots: int = Field(ge=0)
    correct_pivots: int = Field(ge=0)
    evidence_sufficiency: float = Field(ge=0, le=1)
    reviewer_concerns_opened: int = Field(ge=0)
    reviewer_concerns_closed: int = Field(ge=0)
    total_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> StudyOutcome:
        if self.valid_ideas > self.proposed_ideas:
            raise ValueError("valid_ideas cannot exceed proposed_ideas")
        if self.unproductive_experiments > self.total_experiments:
            raise ValueError("unproductive_experiments cannot exceed total_experiments")
        if self.correct_pivots > self.pivots:
            raise ValueError("correct_pivots cannot exceed pivots")
        if self.reviewer_concerns_closed > self.reviewer_concerns_opened:
            raise ValueError("closed reviewer concerns cannot exceed opened concerns")
        if self.unsupported_claims > self.total_claims:
            raise ValueError("unsupported_claims cannot exceed total_claims")
        return self


class StudyArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class StudyExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    status: CellStatus
    evidence_class: EvidenceClass
    usage: StudyUsage
    outcome: StudyOutcome | None = None
    artifacts: list[StudyArtifact] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def successful_records_have_outputs(self) -> StudyExecutionRecord:
        if self.status == CellStatus.SUCCEEDED and self.outcome is None:
            raise ValueError("successful study records require outcome measures")
        if self.status == CellStatus.SUCCEEDED and not self.artifacts:
            raise ValueError("successful study records require hashed artifacts")
        return self


class ExpertPanelReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blind_id: str
    source: ReviewSource
    reviewer_identity_hashes: list[str] = Field(min_length=2)
    rubric_version: str
    problem_quality: float = Field(ge=0, le=1)
    idea_quality: float = Field(ge=0, le=1)
    evidence_quality: float = Field(ge=0, le=1)
    story_quality: float = Field(ge=0, le=1)
    writing_quality: float = Field(ge=0, le=1)
    figure_quality: float = Field(ge=0, le=1)
    final_preference_score: float = Field(ge=0, le=1)
    conflict: bool = False
    adjudicated: bool = False

    @model_validator(mode="after")
    def conflict_is_resolved(self) -> ExpertPanelReview:
        if len(set(self.reviewer_identity_hashes)) != len(self.reviewer_identity_hashes):
            raise ValueError("reviewer identities must be unique")
        if self.conflict and not self.adjudicated:
            raise ValueError("conflicting panel reviews require adjudication")
        return self


class StudyResults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[StudyExecutionRecord]
    expert_reviews: list[ExpertPanelReview]


class CellAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    telemetry_complete: bool
    missing_telemetry: list[str]
    budget_compliant: bool
    budget_violations: list[str]
    expert_review_present: bool
    expert_review_valid: bool
    review_violations: list[str]
    outcome_consistent: bool
    integrity_violations: list[str]


class SystemMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_count: int
    research_yield_per_gpu_hour: float | None
    idea_yield: float | None
    invalid_idea_rate: float | None
    mean_pilots: float | None
    mean_discarded_ideas: float | None
    unproductive_experiment_rate: float | None
    mean_gpu_hours_before_useful_signal: float | None
    mean_pivots: float | None
    evidence_sufficiency: float | None
    reviewer_concern_closure_rate: float | None
    unsupported_claim_rate: float | None
    correct_pivot_rate: float | None
    problem_quality: float | None
    idea_quality: float | None
    evidence_quality: float | None
    story_quality: float | None
    writing_quality: float | None
    figure_quality: float | None
    final_expert_preference: float | None


class SystemComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: SystemCondition
    baseline: SystemCondition = SystemCondition.AUTORESEARCHCLAW
    comparable_cell_count: int
    research_yield_delta: float | None
    idea_yield_delta: float | None
    unproductive_experiment_rate_delta: float | None
    evidence_sufficiency_delta: float | None
    unsupported_claim_rate_delta: float | None
    correct_pivot_rate_delta: float | None
    final_expert_preference_delta: float | None


class MatchedStudyReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    study_id: str
    protocol_sha256: str
    plan_sha256: str
    status: StudyStatus
    headline_eligible: bool
    planned_cells: int
    completed_cells: int
    missing_cell_ids: list[str]
    blockers: list[str]
    audits: list[CellAudit]
    by_condition: dict[SystemCondition, SystemMetrics]
    comparisons_to_autoresearchclaw: dict[SystemCondition, SystemComparison]
    disabled_conditions: dict[SystemCondition, str]
