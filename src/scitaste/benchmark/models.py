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
    TASTE_PLACEBO = "taste_placebo"


class BenchmarkEvidenceTier(StrEnum):
    SYNTHETIC_ACCEPTANCE = "synthetic_acceptance"
    NATURAL_PILOT = "natural_pilot"
    FORMAL = "formal"


class CandidateOrder(StrEnum):
    DECLARED = "declared"
    REVERSED = "reversed"


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
    knowledge_evidence_ids: tuple[str, ...] = ()
    taste_principle: str = ""
    taste_precedent_ids: tuple[str, ...] = ()
    taste_precedent_source_group_ids: tuple[str, ...] = ()
    placebo_taste_principle: str = ""
    placebo_precedent_ids: tuple[str, ...] = ()
    placebo_precedent_source_group_ids: tuple[str, ...] = ()
    critic_feedback: str = ""
    controller_context: str = ""
    source_group_id: str | None = None
    source_ref: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    primary_label_count: int | None = Field(default=None, ge=2)
    primary_label_agreement: float | None = Field(default=None, ge=0, le=1)
    annotation_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(default="scitastebench-v1", min_length=1, max_length=100)
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
        provenance_groups = (
            self.taste_precedent_source_group_ids,
            self.placebo_precedent_source_group_ids,
        )
        if any(len(values) != len(set(values)) for values in provenance_groups):
            raise ValueError("benchmark precedent source-group ids must be unique")
        if len(self.knowledge_evidence_ids) != len(set(self.knowledge_evidence_ids)):
            raise ValueError("benchmark knowledge evidence ids must be unique")
        if len(self.taste_precedent_ids) != len(set(self.taste_precedent_ids)):
            raise ValueError("benchmark taste precedent ids must be unique")
        if len(self.placebo_precedent_ids) != len(set(self.placebo_precedent_ids)):
            raise ValueError("benchmark placebo precedent ids must be unique")
        if set(self.taste_precedent_ids) & set(self.placebo_precedent_ids):
            raise ValueError("matched and placebo Taste precedents must be disjoint")
        if self.source_group_id is not None and self.source_group_id in {
            *self.taste_precedent_source_group_ids,
            *self.placebo_precedent_source_group_ids,
        }:
            raise ValueError("benchmark source group cannot enter its Taste context")
        return self

    def request_id(
        self,
        condition: BenchmarkCondition,
        candidate_order: CandidateOrder = CandidateOrder.DECLARED,
    ) -> str:
        suffix = "" if candidate_order is CandidateOrder.DECLARED else "::reversed"
        return f"{self.case_id}::{condition.value}{suffix}"

    def to_request(
        self,
        condition: BenchmarkCondition,
        *,
        seed: int,
        candidate_order: CandidateOrder = CandidateOrder.DECLARED,
    ) -> PreferenceRequest:
        sections = [self.decision_context]
        if condition in {BenchmarkCondition.KNOWLEDGE_RAG, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Retrieved knowledge:\n{self.knowledge_context}")
        if condition in {BenchmarkCondition.TASTE_LIBRARY, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Retrieved taste principle:\n{self.taste_principle}")
        if condition is BenchmarkCondition.TASTE_PLACEBO:
            sections.append(f"Retrieved taste principle:\n{self.placebo_taste_principle}")
        if condition in {BenchmarkCondition.TASTE_CRITICS, BenchmarkCondition.FULL_SCITASTE}:
            sections.append(f"Independent critic feedback:\n{self.critic_feedback}")
        if condition == BenchmarkCondition.FULL_SCITASTE:
            sections.append(f"Controller state:\n{self.controller_context}")
        return PreferenceRequest(
            request_id=self.request_id(condition, candidate_order),
            task=self.task.value,
            stage=self.stage,
            decision_context="\n\n".join(sections),
            candidate_actions=(
                self.candidate_actions
                if candidate_order is CandidateOrder.DECLARED
                else list(reversed(self.candidate_actions))
            ),
            seed=seed,
            prompt_version=(
                f"{self.prompt_version}/{condition.value}"
                if candidate_order is CandidateOrder.DECLARED
                else f"{self.prompt_version}/{condition.value}/reversed"
            ),
        )


class BenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    version: str
    description: str
    evidence_tier: BenchmarkEvidenceTier = BenchmarkEvidenceTier.SYNTHETIC_ACCEPTANCE
    annotation_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    precedent_corpus_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    precedent_source_group_ids: tuple[str, ...] = ()
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
        if self.evidence_tier is BenchmarkEvidenceTier.FORMAL:
            headline = [case for case in self.cases if case.headline_eligible]
            if len(headline) < 120:
                raise ValueError("formal SciTasteBench requires at least 120 headline cases")
            if len({case.domain for case in headline}) < 3:
                raise ValueError("formal SciTasteBench requires at least three domains")
            if {case.task for case in headline} != set(TasteTask):
                raise ValueError("formal SciTasteBench must cover every taste decision family")
            if BenchmarkCondition.TASTE_PLACEBO not in self.conditions:
                raise ValueError("formal SciTasteBench requires a mismatched-Taste placebo")
            if self.annotation_manifest_sha256 is None or self.precedent_corpus_sha256 is None:
                raise ValueError("formal SciTasteBench requires annotation and precedent hashes")
            if not self.precedent_source_group_ids or len(self.precedent_source_group_ids) != len(
                set(self.precedent_source_group_ids)
            ):
                raise ValueError("formal SciTasteBench requires unique precedent source groups")
            if {case.source_group_id for case in headline} & set(self.precedent_source_group_ids):
                raise ValueError("formal case and precedent source groups must be disjoint")
            if any(
                case.source_group_id is None
                or case.source_ref is None
                or case.source_sha256 is None
                or case.primary_label_count is None
                or case.annotation_manifest_sha256 != self.annotation_manifest_sha256
                or case.prompt_version != "scitastebench-v2"
                or not case.placebo_taste_principle
                or not case.knowledge_evidence_ids
                or not case.taste_precedent_ids
                or not case.taste_precedent_source_group_ids
                or not case.placebo_precedent_ids
                or not case.placebo_precedent_source_group_ids
                or case.self_referential
                or case.scripted_selections
                for case in headline
            ):
                raise ValueError(
                    "formal SciTasteBench cases require natural-source, human-label, placebo, "
                    "and v2 protocol bindings"
                )
        return self

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        for case in payload["cases"]:
            observed = set(case["transfer_axes"])
            case["transfer_axes"] = [axis.value for axis in TransferAxis if axis.value in observed]
        if self.version == "1.0":
            for field in (
                "evidence_tier",
                "annotation_manifest_sha256",
                "precedent_corpus_sha256",
                "precedent_source_group_ids",
            ):
                payload.pop(field, None)
            additive_case_fields = (
                "knowledge_evidence_ids",
                "taste_precedent_ids",
                "taste_precedent_source_group_ids",
                "placebo_taste_principle",
                "placebo_precedent_ids",
                "placebo_precedent_source_group_ids",
                "source_group_id",
                "source_ref",
                "source_sha256",
                "primary_label_count",
                "primary_label_agreement",
                "annotation_manifest_sha256",
                "prompt_version",
            )
            for case in payload["cases"]:
                for field in additive_case_fields:
                    case.pop(field, None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class BenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    condition: BenchmarkCondition
    candidate_order: CandidateOrder = CandidateOrder.DECLARED
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
    candidate_order: CandidateOrder = CandidateOrder.DECLARED
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
    candidate_order: CandidateOrder = CandidateOrder.DECLARED
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
