"""Versioned schemas for controlled SciTasteBench evaluation."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.backends.base import PreferenceRequest, Usage
from scitaste.schema.actions import ResearchAction
from scitaste.taste.intrinsic import TasteTask


class BenchmarkCondition(StrEnum):
    BASE = "base"
    KNOWLEDGE_RAG = "knowledge_rag"
    TASTE_LIBRARY = "taste_library"
    TASTE_CRITICS = "taste_critics"
    FULL_SCITASTE = "full_scitaste"


class TransferAxis(StrEnum):
    FUTURE_YEAR = "future_year"
    CROSS_VENUE = "cross_venue"
    CROSS_DOMAIN = "cross_domain"


class BenchmarkCase(BaseModel):
    """One held-out, fixed-pair scientific decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    task: TasteTask
    stage: str
    domain: str
    venue: str
    publication_year: int = Field(ge=1900)
    decision_context: str = Field(min_length=1)
    candidate_actions: list[ResearchAction] = Field(min_length=2, max_length=2)
    action_roles: dict[str, str]
    preferred_action_id: str
    wrong_level_action_ids: list[str] = Field(default_factory=list)
    expert_distribution: dict[str, float]
    transfer_axes: set[TransferAxis] = Field(default_factory=set)
    style_group: str | None = None
    paraphrase_group: str | None = None
    knowledge_context: str = ""
    taste_principle: str = ""
    critic_feedback: str = ""
    controller_context: str = ""
    headline_eligible: bool = True
    self_referential: bool = False
    scripted_selections: dict[BenchmarkCondition, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references_are_valid(self) -> BenchmarkCase:
        candidate_ids = [action.action_id for action in self.candidate_actions]
        candidate_set = set(candidate_ids)
        if len(candidate_set) != 2:
            raise ValueError("benchmark candidate action ids must be unique")
        if set(self.action_roles) != candidate_set:
            raise ValueError("action_roles must cover exactly the candidate action ids")
        if self.preferred_action_id not in candidate_set:
            raise ValueError("preferred_action_id must be a candidate")
        if not set(self.wrong_level_action_ids).issubset(candidate_set):
            raise ValueError("wrong_level_action_ids must be candidates")
        if set(self.expert_distribution) != candidate_set:
            raise ValueError("expert_distribution must cover exactly the candidates")
        if any(value < 0 or value > 1 for value in self.expert_distribution.values()):
            raise ValueError("expert_distribution values must be between zero and one")
        if abs(sum(self.expert_distribution.values()) - 1.0) > 1e-6:
            raise ValueError("expert_distribution must sum to one")
        if any(selection not in candidate_set for selection in self.scripted_selections.values()):
            raise ValueError("scripted selections must be candidates")
        if self.self_referential and self.headline_eligible:
            raise ValueError("self-referential cases cannot be headline eligible")
        return self

    def request_id(self, condition: BenchmarkCondition) -> str:
        return f"{self.case_id}::{condition.value}"

    def to_request(self, condition: BenchmarkCondition, *, seed: int) -> PreferenceRequest:
        sections = [self.decision_context]
        if condition in {BenchmarkCondition.KNOWLEDGE_RAG, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Retrieved knowledge:\n{self.knowledge_context}")
        if condition in {BenchmarkCondition.TASTE_LIBRARY, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Retrieved taste principle:\n{self.taste_principle}")
        if condition in {BenchmarkCondition.TASTE_CRITICS, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Independent critic feedback:\n{self.critic_feedback}")
        if condition == BenchmarkCondition.FULL_SCITASTE:
            sections.append(f"Controller state:\n{self.controller_context}")
        return PreferenceRequest(
            request_id=self.request_id(condition),
            task=self.task.value,
            stage=self.stage,
            decision_context="\n\n".join(sections),
            candidate_actions=self.candidate_actions,
            seed=seed,
            prompt_version=f"scitastebench-v1/{condition.value}",
        )


class BenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    version: str
    description: str
    conditions: list[BenchmarkCondition]
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def suite_is_controlled(self) -> BenchmarkSuite:
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("benchmark conditions must be unique")
        required = {BenchmarkCondition.BASE, BenchmarkCondition.FULL_SCITASTE}
        if not required.issubset(self.conditions):
            raise ValueError("suite must include base and full_scitaste conditions")
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("benchmark case ids must be unique")
        if not any(case.headline_eligible for case in self.cases):
            raise ValueError("suite must contain at least one headline-eligible case")
        return self

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class BenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    condition: BenchmarkCondition
    task: TasteTask
    selected_action_id: str
    selected_role: str
    preferred_action_id: str
    correct: bool
    wrong_level: bool
    confidence: float
    expert_agreement: float
    rationale: str
    backend: str
    model: str
    request_fingerprint: str
    cached: bool
    usage: Usage


class BenchmarkMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=0)
    pairwise_accuracy: float = Field(ge=0, le=1)
    expert_agreement: float = Field(ge=0, le=1)
    mean_confidence: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)
    expected_calibration_error: float = Field(ge=0, le=1)
    wrong_level_decision_rate: float = Field(ge=0, le=1)


class ConditionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: BenchmarkCondition
    overall: BenchmarkMetrics
    headline: BenchmarkMetrics
    by_task: dict[TasteTask, BenchmarkMetrics]
    transfer: dict[TransferAxis, BenchmarkMetrics]
    style_invariance: float | None = Field(default=None, ge=0, le=1)
    paraphrase_consistency: float | None = Field(default=None, ge=0, le=1)
    results: list[BenchmarkResult]


class ConditionComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: BenchmarkCondition
    eligible_case_count: int
    accuracy_delta: float
    expert_agreement_delta: float
    wrong_level_rate_delta: float
    paired_improvements: int
    paired_regressions: int
    paired_unchanged: int


class CapabilityBoundaryReport(BaseModel):
    """Paired evidence separating model-only misses from augmentation effects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str = "paired-base-full-boundary-v1"
    diagnostic_only: bool = True
    no_observed_limit_case_ids: list[str]
    system_recovery_case_ids: list[str]
    system_regression_case_ids: list[str]
    shared_failure_case_ids: list[str]
    model_capability_conclusion: str
    system_conclusion: str


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    suite_id: str
    suite_version: str
    suite_sha256: str
    backend: str
    model: str
    seed: int
    conditions: dict[BenchmarkCondition, ConditionReport]
    comparisons_to_base: dict[BenchmarkCondition, ConditionComparison]
    excluded_headline_case_ids: list[str]
    unavailable_metrics: dict[str, str]
    capability_boundary: CapabilityBoundaryReport | None = None


class CrossModelCapabilityComparison(BaseModel):
    """Same-suite differential evidence for model-specific versus shared limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    method: str = "paired-cross-model-boundary-v1"
    diagnostic_only: bool = True
    suite_id: str
    suite_sha256: str
    seed: int
    primary_backend: str
    primary_model: str
    comparator_backend: str
    comparator_model: str
    both_base_correct_case_ids: list[str]
    primary_model_limit_candidate_case_ids: list[str]
    comparator_model_limit_candidate_case_ids: list[str]
    shared_base_failure_case_ids: list[str]
    primary_system_regression_case_ids: list[str]
    comparator_system_regression_case_ids: list[str]
    attribution_rule: str
