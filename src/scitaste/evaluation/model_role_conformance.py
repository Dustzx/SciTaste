"""Task-excluded conformance and evidence-only model-role selection.

This module deliberately has no provider or accelerator backend.  ``plan``
binds candidates to a static inventory and frozen criteria; ``compile`` can
only consume existing, content-addressed run receipts and their evidence.
Inventory presence is therefore never confused with demonstrated role fit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 8 * 1024 * 1024
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class ModelRole(StrEnum):
    """Roles selected independently for one autonomous-research program."""

    RESEARCH_AGENT = "research_agent"
    CODE_AGENT = "code_agent"
    JUDGE = "judge"
    EMBEDDING = "embedding"
    TASK_TRAINING = "task_training"


class ExecutionKind(StrEnum):
    API = "api"
    LOCAL = "local"


class IdentityScope(StrEnum):
    IMMUTABLE_CHECKPOINT = "immutable_checkpoint"
    HOSTED_TEMPORAL_WINDOW = "hosted_temporal_window"


class SelectionStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NON_HEADLINE = "non_headline"


class EvidenceKind(StrEnum):
    EXECUTOR_RECEIPT = "executor_receipt"
    CASE_MANIFEST = "case_manifest"
    CASE_RESULTS = "case_results"


class EvidenceValidator(StrEnum):
    MODEL_NODE_RUNTIME_V1 = "scitaste-model-node-runtime-v1"
    BENCHMARK_DEVELOPMENT_V1 = "scitaste-benchmark-development-v1"
    CONFORMANCE_EXECUTION_V1 = "scitaste-conformance-execution-v1"
    CASE_MANIFEST_V1 = "scitaste-model-role-case-manifest-v1"
    CASE_RESULTS_V1 = "scitaste-model-role-case-results-v1"


class CriterionThreshold(BaseModel):
    model_config = _CONFIG

    weight: float = Field(gt=0.0, le=1.0)
    minimum: Score


class FrozenConformanceCriteria(BaseModel):
    """Frozen, role-agnostic criteria; each dimension is reported separately."""

    model_config = _CONFIG

    schema_adherence: CriterionThreshold
    tool_adherence: CriterionThreshold
    success: CriterionThreshold
    context: CriterionThreshold
    latency_cost: CriterionThreshold
    reproducibility: CriterionThreshold
    task_fit: CriterionThreshold

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> FrozenConformanceCriteria:
        weights = [item.weight for item in self.as_mapping().values()]
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError("model-role conformance criterion weights must sum to one")
        return self

    def as_mapping(self) -> dict[str, CriterionThreshold]:
        return {
            "schema_adherence": self.schema_adherence,
            "tool_adherence": self.tool_adherence,
            "success": self.success,
            "context": self.context,
            "latency_cost": self.latency_cost,
            "reproducibility": self.reproducibility,
            "task_fit": self.task_fit,
        }


class ConformanceMeasurements(BaseModel):
    model_config = _CONFIG

    schema_adherence: Score
    tool_adherence: Score
    success: Score
    context: Score
    latency_cost: Score
    reproducibility: Score
    task_fit: Score
    successful_cases: int = Field(ge=0)
    total_cases: int = Field(gt=0)
    latency_p95_ms: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)

    @model_validator(mode="after")
    def case_counts_are_possible(self) -> ConformanceMeasurements:
        if self.successful_cases > self.total_cases:
            raise ValueError("successful conformance cases cannot exceed total cases")
        return self

    def scores(self) -> dict[str, float]:
        return {
            name: float(getattr(self, name))
            for name in (
                "schema_adherence",
                "tool_adherence",
                "success",
                "context",
                "latency_cost",
                "reproducibility",
                "task_fit",
            )
        }


class TaskExclusionContract(BaseModel):
    """Explicit firewall between selection material and reported tasks."""

    model_config = _CONFIG

    conformance_task_ids: tuple[str, ...] = Field(min_length=1)
    conformance_source_group_ids: tuple[str, ...] = Field(min_length=1)
    formal_task_ids: tuple[str, ...]
    heldout_task_ids: tuple[str, ...]
    formal_source_group_ids: tuple[str, ...]
    heldout_source_group_ids: tuple[str, ...]
    formal_or_heldout_inputs_allowed: Literal[False] = False
    conformance_task_bytes_bound: bool
    conformance_tasks_are_planning_labels_only: bool
    conformance_case_input_sha256: dict[str, str]
    conformance_source_group_by_task: dict[str, str]

    @model_validator(mode="after")
    def partitions_are_disjoint(self) -> TaskExclusionContract:
        if self.conformance_task_bytes_bound == self.conformance_tasks_are_planning_labels_only:
            raise ValueError(
                "conformance tasks must be either byte-bound or planning-only, never both"
            )
        task_ids = set(self.conformance_task_ids)
        if self.conformance_task_bytes_bound:
            if set(self.conformance_case_input_sha256) != task_ids or set(
                self.conformance_source_group_by_task
            ) != task_ids:
                raise ValueError("byte-bound conformance tasks require a hash and source group")
            if any(
                not isinstance(value, str) or not re.fullmatch(_SHA256, value)
                for value in self.conformance_case_input_sha256.values()
            ):
                raise ValueError("conformance case input hashes must be SHA-256 values")
            if not set(self.conformance_source_group_by_task.values()) <= set(
                self.conformance_source_group_ids
            ):
                raise ValueError("conformance case source groups are outside the allowed partition")
        elif self.conformance_case_input_sha256 or self.conformance_source_group_by_task:
            raise ValueError("planning-only conformance tasks cannot carry byte bindings")
        groups = {
            "task": (
                set(self.conformance_task_ids),
                set(self.formal_task_ids) | set(self.heldout_task_ids),
            ),
            "source group": (
                set(self.conformance_source_group_ids),
                set(self.formal_source_group_ids) | set(self.heldout_source_group_ids),
            ),
        }
        for label, (selection, prohibited) in groups.items():
            if selection & prohibited:
                raise ValueError(f"conformance and formal/heldout {label} IDs must be disjoint")
        for name in (
            "conformance_task_ids",
            "conformance_source_group_ids",
            "formal_task_ids",
            "heldout_task_ids",
            "formal_source_group_ids",
            "heldout_source_group_ids",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique IDs")
        return self


class ModelIdentityExpectation(BaseModel):
    model_config = _CONFIG

    execution_kind: ExecutionKind
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)
    revision: str | None = Field(default=None, min_length=1, max_length=300)


class ExactModelIdentity(BaseModel):
    """Identity returned by an actual conformance run, not by inventory scan."""

    model_config = _CONFIG

    execution_kind: ExecutionKind
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)
    revision: str | None = Field(default=None, min_length=1, max_length=300)
    route: str = Field(min_length=1, max_length=500)
    scope: IdentityScope
    artifact_sha256: str | None = Field(default=None, pattern=_SHA256)
    temporal_window_id: str | None = Field(default=None, pattern=_ID)
    identity_evidence_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def scope_has_exact_evidence(self) -> ExactModelIdentity:
        if self.scope is IdentityScope.IMMUTABLE_CHECKPOINT:
            if self.artifact_sha256 is None or self.temporal_window_id is not None:
                raise ValueError("immutable model identity requires only artifact_sha256")
        elif self.temporal_window_id is None or self.artifact_sha256 is not None:
            raise ValueError("hosted model identity requires only temporal_window_id")
        if (
            self.execution_kind is ExecutionKind.API
            and self.scope is not IdentityScope.HOSTED_TEMPORAL_WINDOW
        ):
            raise ValueError("API model identity must be bound to a hosted temporal window")
        if (
            self.execution_kind is ExecutionKind.LOCAL
            and self.scope is not IdentityScope.IMMUTABLE_CHECKPOINT
        ):
            raise ValueError("local model identity must be bound to an immutable checkpoint")
        return self

    @property
    def exact_identity_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"exact_identity_sha256"}))

    @property
    def model_stratum_sha256(self) -> str:
        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"exact_identity_sha256", "identity_evidence_sha256"},
            )
        )

    @property
    def independence_key(self) -> tuple[str, str, str | None]:
        """Conservatively identify a model family across routes or API windows."""

        return (self.provider, self.model_id, self.revision)


class RoleProfileSpec(BaseModel):
    model_config = _CONFIG

    profile_id: str = Field(pattern=_ID)
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    role: ModelRole
    contract_ref: str = Field(min_length=1, max_length=500)
    contract_sha256: str = Field(pattern=_SHA256)
    prompt_contract_id: str = Field(pattern=_ID)
    tool_contract_id: str = Field(pattern=_ID)
    inference_parameters: dict[str, str | int | float | bool] = Field(min_length=1)

    @property
    def profile_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"profile_sha256"}))


class RoleBudget(BaseModel):
    model_config = _CONFIG

    budget_id: str = Field(pattern=_ID)
    max_invocations: int = Field(gt=0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_latency_ms: int = Field(gt=0)
    max_cost_usd: float = Field(ge=0.0)
    max_gpu_hours: float = Field(ge=0.0)

    @model_validator(mode="after")
    def total_tokens_cover_one_call(self) -> RoleBudget:
        if self.max_total_tokens < self.max_input_tokens + self.max_output_tokens:
            raise ValueError("role budget total-token ceiling cannot be below one maximum call")
        return self

    @property
    def budget_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"budget_sha256"}))


class ModelRoleCandidate(BaseModel):
    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    role: ModelRole
    selection_scope_id: str = Field(pattern=_ID)
    resource_id: str = Field(pattern=_ID)
    identity: ModelIdentityExpectation
    profile_id: str = Field(pattern=_ID)
    budget_id: str = Field(pattern=_ID)
    minimum_receipts: int = Field(default=1, ge=1, le=100)


class ModelRoleConformanceSuite(BaseModel):
    """Human-authored candidate suite; it grants no execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    suite_id: str = Field(pattern=_ID)
    inventory_ref: str = Field(min_length=1, max_length=500)
    inventory_sha256: str = Field(pattern=_SHA256)
    criteria: FrozenConformanceCriteria
    exclusions: TaskExclusionContract
    profiles: tuple[RoleProfileSpec, ...] = Field(min_length=5)
    budgets: tuple[RoleBudget, ...] = Field(min_length=1)
    candidates: tuple[ModelRoleCandidate, ...] = Field(min_length=5)
    inventory_presence_selects_model: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_downloads: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def references_are_closed(self) -> ModelRoleConformanceSuite:
        _require_unique([item.profile_id for item in self.profiles], "profile IDs")
        _require_unique([item.budget_id for item in self.budgets], "budget IDs")
        _require_unique([item.candidate_id for item in self.candidates], "candidate IDs")
        profile_by_id = {item.profile_id: item for item in self.profiles}
        budget_ids = {item.budget_id for item in self.budgets}
        roles = set(ModelRole)
        if {item.role for item in self.profiles} != roles:
            raise ValueError("model-role suite must define profiles for all five roles")
        if {item.role for item in self.candidates} != roles:
            raise ValueError("model-role suite must contain candidates for all five roles")
        for candidate in self.candidates:
            profile = profile_by_id.get(candidate.profile_id)
            if profile is None or profile.role is not candidate.role:
                raise ValueError("candidate role/profile binding is invalid")
            if candidate.budget_id not in budget_ids:
                raise ValueError("candidate references an unknown role budget")
            if candidate.role in {
                ModelRole.RESEARCH_AGENT,
                ModelRole.CODE_AGENT,
                ModelRole.JUDGE,
            } and candidate.selection_scope_id != "agent-global":
                raise ValueError("agent and judge candidates must use the agent-global scope")
            if (
                candidate.role is ModelRole.TASK_TRAINING
                and candidate.selection_scope_id == "agent-global"
            ):
                raise ValueError("task-training models must be selected by benchmark/task family")
        return self


class PlannedModelRoleCandidate(BaseModel):
    model_config = _CONFIG

    candidate: ModelRoleCandidate
    profile: RoleProfileSpec
    budget: RoleBudget
    inventory_role_fit: str
    selection_state: Literal["awaiting_actual_receipts"] = "awaiting_actual_receipts"


class ModelRoleConformancePlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    suite_id: str = Field(pattern=_ID)
    suite_sha256: str = Field(pattern=_SHA256)
    inventory_ref: str
    inventory_sha256: str = Field(pattern=_SHA256)
    criteria: FrozenConformanceCriteria
    exclusions: TaskExclusionContract
    candidates: tuple[PlannedModelRoleCandidate, ...] = Field(min_length=5)
    inventory_presence_selects_model: Literal[False] = False
    no_receipts_compiled: Literal[True] = True
    authorizes_execution: Literal[False] = False
    no_api_call_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class EvidenceArtifact(BaseModel):
    model_config = _CONFIG

    kind: EvidenceKind
    validator: EvidenceValidator
    locator: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_relative(self) -> EvidenceArtifact:
        _validate_relative_path(self.locator, "evidence artifact locator")
        allowed = {
            EvidenceKind.EXECUTOR_RECEIPT: {
                EvidenceValidator.MODEL_NODE_RUNTIME_V1,
                EvidenceValidator.BENCHMARK_DEVELOPMENT_V1,
                EvidenceValidator.CONFORMANCE_EXECUTION_V1,
            },
            EvidenceKind.CASE_MANIFEST: {EvidenceValidator.CASE_MANIFEST_V1},
            EvidenceKind.CASE_RESULTS: {EvidenceValidator.CASE_RESULTS_V1},
        }
        if self.validator not in allowed[self.kind]:
            raise ValueError("evidence kind and validator are incompatible")
        return self


class ConformanceCase(BaseModel):
    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    input_sha256: str = Field(pattern=_SHA256)


class ConformanceCaseManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str = Field(pattern=_ID)
    partition: Literal["conformance"] = "conformance"
    cases: tuple[ConformanceCase, ...] = Field(min_length=1)
    formal_or_heldout_content_present: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_self_hashed(self) -> ConformanceCaseManifest:
        _require_unique([item.case_id for item in self.cases], "conformance case IDs")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if expected != self.manifest_sha256:
            raise ValueError("conformance case manifest self-hash is invalid")
        return self

    @classmethod
    def create(cls, **values: object) -> ConformanceCaseManifest:
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **values)
        digest = _canonical_sha256(unsigned.model_dump(mode="json", exclude={"manifest_sha256"}))
        return cls(**values, manifest_sha256=digest)


class ConformanceCaseResult(BaseModel):
    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    succeeded: bool
    output_sha256: str = Field(pattern=_SHA256)


class ConformanceCaseResults(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    case_manifest_sha256: str = Field(pattern=_SHA256)
    executor_receipt_file_sha256: str = Field(pattern=_SHA256)
    cases: tuple[ConformanceCaseResult, ...] = Field(min_length=1)
    results_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def results_are_self_hashed(self) -> ConformanceCaseResults:
        _require_unique([item.case_id for item in self.cases], "conformance result case IDs")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"results_sha256"}))
        if expected != self.results_sha256:
            raise ValueError("conformance case-results self-hash is invalid")
        return self

    @classmethod
    def create(cls, **values: object) -> ConformanceCaseResults:
        unsigned = cls.model_construct(results_sha256="0" * 64, **values)
        digest = _canonical_sha256(unsigned.model_dump(mode="json", exclude={"results_sha256"}))
        return cls(**values, results_sha256=digest)


class ConformanceExecutorReceipt(BaseModel):
    """Self-hashed fallback for role runners without a native SciTaste receipt."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    runner_id: str = Field(pattern=_ID)
    runner_version: str = Field(min_length=1, max_length=100)
    candidate_id: str = Field(pattern=_ID)
    role: ModelRole
    selection_scope_id: str = Field(pattern=_ID)
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)
    revision: str | None = Field(default=None, min_length=1, max_length=300)
    profile_sha256: str = Field(pattern=_SHA256)
    budget_sha256: str = Field(pattern=_SHA256)
    started_at_utc: datetime
    completed_at_utc: datetime
    status: Literal["succeeded"] = "succeeded"
    actual_execution: Literal[True]
    request_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def execution_is_temporal_and_self_hashed(self) -> ConformanceExecutorReceipt:
        if self.started_at_utc.tzinfo is None or self.completed_at_utc.tzinfo is None:
            raise ValueError("conformance execution timestamps must be timezone-aware")
        if self.completed_at_utc <= self.started_at_utc:
            raise ValueError("conformance execution must complete after it starts")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if expected != self.receipt_sha256:
            raise ValueError("conformance executor receipt self-hash is invalid")
        return self

    @classmethod
    def create(cls, **values: object) -> ConformanceExecutorReceipt:
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **values)
        digest = _canonical_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**values, receipt_sha256=digest)


class ModelRoleConformanceRunResult(BaseModel):
    """Receipt emitted after a real conformance run by a separate runner."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    suite_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    run_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    role: ModelRole
    selection_scope_id: str = Field(pattern=_ID)
    exact_identity: ExactModelIdentity
    profile_sha256: str = Field(pattern=_SHA256)
    budget_sha256: str = Field(pattern=_SHA256)
    task_ids: tuple[str, ...] = Field(min_length=1)
    source_group_ids: tuple[str, ...] = Field(min_length=1)
    measurements: ConformanceMeasurements
    evidence_artifacts: tuple[EvidenceArtifact, ...] = Field(min_length=1)
    actual_execution: Literal[True]
    inventory_presence_was_not_used_as_result: Literal[True]
    formal_or_heldout_content_used: Literal[False]

    @model_validator(mode="after")
    def receipt_sets_are_unique(self) -> ModelRoleConformanceRunResult:
        _require_unique(self.task_ids, "receipt task IDs")
        _require_unique(self.source_group_ids, "receipt source-group IDs")
        _require_unique([item.locator for item in self.evidence_artifacts], "evidence locators")
        kinds = [item.kind for item in self.evidence_artifacts]
        required = {
            EvidenceKind.EXECUTOR_RECEIPT,
            EvidenceKind.CASE_MANIFEST,
            EvidenceKind.CASE_RESULTS,
        }
        if set(kinds) != required or len(kinds) != len(required):
            raise ValueError(
                "model-role receipt requires exactly one executor, case-manifest, "
                "and case-results artifact"
            )
        executor = next(
            item for item in self.evidence_artifacts if item.kind is EvidenceKind.EXECUTOR_RECEIPT
        )
        if self.exact_identity.identity_evidence_sha256 != executor.sha256:
            raise ValueError("exact identity must be evidenced by the executor receipt bytes")
        return self


class CandidateConformanceResult(BaseModel):
    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    role: ModelRole
    selection_scope_id: str = Field(pattern=_ID)
    receipt_count: int = Field(ge=0)
    receipt_file_sha256s: tuple[str, ...]
    exact_identity: ExactModelIdentity | None
    mean_measurements: dict[str, Score]
    weighted_score: float = Field(ge=0.0, le=1.0)
    passes: bool
    blockers: tuple[str, ...]
    evidence_sha256: str | None = Field(default=None, pattern=_SHA256)


class SelectedModelRoleBinding(BaseModel):
    """Exact project-controller binding produced from qualifying receipts."""

    model_config = _CONFIG

    role: ModelRole
    selection_scope_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    resource_id: str = Field(pattern=_ID)
    exact_identity: ExactModelIdentity
    profile: RoleProfileSpec
    budget: RoleBudget
    weighted_score: float = Field(ge=0.0, le=1.0)
    evidence_sha256: str = Field(pattern=_SHA256)
    headline_independent: bool


class ModelRoleSelectionManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    suite_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    status: SelectionStatus
    candidate_results: tuple[CandidateConformanceResult, ...]
    selections: tuple[SelectedModelRoleBinding, ...]
    missing_roles: tuple[ModelRole, ...]
    missing_selection_scopes: tuple[str, ...]
    judge_generator_conflicts: tuple[str, ...]
    headline_eligible: bool
    compiled_from_actual_receipts_only: Literal[True] = True
    inventory_presence_selects_model: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_api_call_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True

    @model_validator(mode="after")
    def role_scope_bindings_are_closed(self) -> ModelRoleSelectionManifest:
        selection_keys = [(item.role, item.selection_scope_id) for item in self.selections]
        _require_unique(
            [_scope_key(role, scope_id) for role, scope_id in selection_keys],
            "selected role/scope bindings",
        )
        _require_unique(list(self.missing_selection_scopes), "missing role/scope bindings")
        if set(_scope_key(*item) for item in selection_keys) & set(
            self.missing_selection_scopes
        ):
            raise ValueError("a role/scope cannot be both selected and missing")
        if self.headline_eligible:
            if self.status is not SelectionStatus.COMPLETE or self.missing_selection_scopes:
                raise ValueError("headline eligibility requires a complete scoped selection")
            if any(
                not item.headline_independent
                for item in self.selections
                if item.role is ModelRole.JUDGE
            ):
                raise ValueError("headline eligibility requires identity-distinct judges")
        if self.status is SelectionStatus.INCOMPLETE and not self.missing_selection_scopes:
            raise ValueError("incomplete selection must name missing role/scope bindings")
        if self.status is SelectionStatus.NON_HEADLINE and self.headline_eligible:
            raise ValueError("non-headline selection cannot be headline eligible")
        return self

    @computed_field
    @property
    def selection_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"selection_sha256"}))


class ModelRoleConformanceStatus(BaseModel):
    model_config = _CONFIG

    suite_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    candidates_by_scope: dict[str, int]
    valid_actual_receipts: int = Field(ge=0)
    receipt_counts_by_candidate: dict[str, int]
    ready_candidates_by_scope: dict[str, int]
    selection_status: SelectionStatus
    selected_roles: tuple[ModelRole, ...]
    selected_scopes: tuple[str, ...]
    missing_roles: tuple[ModelRole, ...]
    missing_selection_scopes: tuple[str, ...]
    headline_eligible: bool
    executable_for_conformance: bool
    next_action: str


def plan_model_role_conformance(
    suite_path: str | Path,
    *,
    repository_root: str | Path = ".",
) -> ModelRoleConformancePlan:
    """Compile a no-run suite against the declared resource inventory."""

    suite_source, suite_payload = _load_yaml_object(suite_path, "model-role conformance suite")
    suite = ModelRoleConformanceSuite.model_validate(suite_payload)
    root = Path(repository_root).resolve(strict=True)
    inventory_source = _resolve_beneath(root, suite.inventory_ref, "model-role inventory")
    if _file_sha256(inventory_source) != suite.inventory_sha256:
        raise ValueError("model-role inventory content hash differs from the frozen suite")
    _, inventory = _load_yaml_object(inventory_source, "model-role inventory")
    inventory_roles = _inventory_role_fit(inventory)
    profiles = {item.profile_id: item for item in suite.profiles}
    budgets = {item.budget_id: item for item in suite.budgets}
    planned: list[PlannedModelRoleCandidate] = []
    for candidate in suite.candidates:
        role_fit = inventory_roles.get(candidate.resource_id, {}).get(candidate.role.value)
        if role_fit is None:
            raise ValueError(
                f"candidate {candidate.candidate_id!r} is absent from the inventory for "
                f"role {candidate.role.value!r}"
            )
        if role_fit in {"blocked", "not_applicable"}:
            raise ValueError(
                f"candidate {candidate.candidate_id!r} has ineligible inventory role fit "
                f"{role_fit!r}"
            )
        profile = profiles[candidate.profile_id]
        contract_source = _resolve_beneath(root, profile.contract_ref, "role contract")
        if _file_sha256(contract_source) != profile.contract_sha256:
            raise ValueError(f"role contract hash drift for profile {profile.profile_id!r}")
        planned.append(
            PlannedModelRoleCandidate(
                candidate=candidate,
                profile=profile,
                budget=budgets[candidate.budget_id],
                inventory_role_fit=role_fit,
            )
        )
    return ModelRoleConformancePlan(
        suite_id=suite.suite_id,
        suite_sha256=_file_sha256(suite_source),
        inventory_ref=suite.inventory_ref,
        inventory_sha256=suite.inventory_sha256,
        criteria=suite.criteria,
        exclusions=suite.exclusions,
        candidates=tuple(planned),
    )


def compile_model_role_selection(
    plan: ModelRoleConformancePlan,
    receipt_paths: list[str | Path],
    *,
    evidence_root: str | Path = ".",
) -> ModelRoleSelectionManifest:
    """Select each role deterministically from verified, actual run receipts."""

    root = Path(evidence_root).resolve(strict=True)
    receipts = _load_and_verify_receipts(plan, receipt_paths, evidence_root=root)
    by_candidate: dict[str, list[tuple[ModelRoleConformanceRunResult, str]]] = defaultdict(list)
    for receipt, file_sha256 in receipts:
        by_candidate[receipt.candidate_id].append((receipt, file_sha256))

    candidate_results = tuple(
        _aggregate_candidate(plan, item, by_candidate.get(item.candidate.candidate_id, []))
        for item in plan.candidates
    )
    planned_by_id = {item.candidate.candidate_id: item for item in plan.candidates}
    required_keys = tuple(
        dict.fromkeys(
            (item.candidate.role, item.candidate.selection_scope_id) for item in plan.candidates
        )
    )
    selections: list[SelectedModelRoleBinding] = []

    # Every role/scope is selected independently. Task-training is therefore
    # never promoted into one nonsensical project-global backbone.
    for role, scope_id in required_keys:
        if role is ModelRole.JUDGE:
            continue
        binding = _choose_role_binding(
            role,
            scope_id,
            candidate_results,
            planned_by_id,
            headline_independent=True,
        )
        if binding is not None:
            selections.append(binding)

    generator_keys = {
        binding.exact_identity.independence_key
        for binding in selections
        if binding.role in {ModelRole.RESEARCH_AGENT, ModelRole.CODE_AGENT}
    }
    judge_candidates = [
        item
        for item in candidate_results
        if item.role is ModelRole.JUDGE and item.passes and item.exact_identity is not None
    ]
    for role, scope_id in required_keys:
        if role is not ModelRole.JUDGE:
            continue
        scoped_judges = [item for item in judge_candidates if item.selection_scope_id == scope_id]
        independent_judges = [
            item
            for item in scoped_judges
            if item.exact_identity.independence_key not in generator_keys
        ]
        judge_pool = independent_judges or scoped_judges
        judge_result = _rank_results(judge_pool)
        if judge_result is not None:
            judge_independent = bool(
                judge_result.exact_identity is not None
                and judge_result.exact_identity.independence_key not in generator_keys
            )
            selections.append(
                _binding_from_result(
                    judge_result,
                    planned_by_id[judge_result.candidate_id],
                    headline_independent=judge_independent,
                )
            )
    selected_keys = {(item.role, item.selection_scope_id) for item in selections}
    missing_keys = tuple(key for key in required_keys if key not in selected_keys)
    selected_roles = {item.role for item in selections}
    missing_roles = tuple(role for role in ModelRole if role not in selected_roles)
    missing_scopes = tuple(_scope_key(*key) for key in missing_keys)
    conflicts = tuple(
        sorted(
            item.candidate_id
            for item in judge_candidates
            if item.exact_identity is not None
            and item.exact_identity.independence_key in generator_keys
        )
    )
    all_judges_independent = all(
        item.headline_independent for item in selections if item.role is ModelRole.JUDGE
    )
    headline_eligible = not missing_keys and all_judges_independent
    if missing_keys:
        status = SelectionStatus.INCOMPLETE
    elif not headline_eligible:
        status = SelectionStatus.NON_HEADLINE
    else:
        status = SelectionStatus.COMPLETE
    return ModelRoleSelectionManifest(
        suite_id=plan.suite_id,
        plan_sha256=plan.plan_sha256,
        status=status,
        candidate_results=candidate_results,
        selections=tuple(selections),
        missing_roles=missing_roles,
        missing_selection_scopes=missing_scopes,
        judge_generator_conflicts=conflicts,
        headline_eligible=headline_eligible,
    )


def inspect_model_role_conformance(
    plan: ModelRoleConformancePlan,
    receipt_paths: list[str | Path],
    *,
    evidence_root: str | Path = ".",
    selection: ModelRoleSelectionManifest | None = None,
) -> ModelRoleConformanceStatus:
    compiled = compile_model_role_selection(plan, receipt_paths, evidence_root=evidence_root)
    if selection is not None:
        if selection.plan_sha256 != plan.plan_sha256:
            raise ValueError("model-role selection manifest belongs to another plan")
        if selection.selection_sha256 != compiled.selection_sha256:
            raise ValueError("model-role selection manifest differs from current receipt evidence")
        compiled = selection
    scope_keys = tuple(
        dict.fromkeys(
            _scope_key(item.candidate.role, item.candidate.selection_scope_id)
            for item in plan.candidates
        )
    )
    candidates_by_scope = {
        key: sum(
            _scope_key(item.candidate.role, item.candidate.selection_scope_id) == key
            for item in plan.candidates
        )
        for key in scope_keys
    }
    ready_by_scope = {
        key: sum(
            _scope_key(item.role, item.selection_scope_id) == key and item.passes
            for item in compiled.candidate_results
        )
        for key in scope_keys
    }
    counts = {item.candidate_id: item.receipt_count for item in compiled.candidate_results}
    selected_roles = tuple(
        role for role in ModelRole if any(item.role is role for item in compiled.selections)
    )
    selected_scopes = tuple(
        _scope_key(item.role, item.selection_scope_id) for item in compiled.selections
    )
    executable = plan.exclusions.conformance_task_bytes_bound
    if not executable:
        next_action = "freeze conformance case bytes and source-group bindings before execution"
    elif compiled.status is SelectionStatus.COMPLETE:
        next_action = "bind exact role selections to the project controller"
    elif compiled.status is SelectionStatus.NON_HEADLINE:
        next_action = "run an identity-distinct judge conformance candidate before headline use"
    else:
        next_action = "execute only the missing task-excluded conformance runs"
    return ModelRoleConformanceStatus(
        suite_id=plan.suite_id,
        plan_sha256=plan.plan_sha256,
        candidates_by_scope=candidates_by_scope,
        valid_actual_receipts=sum(counts.values()),
        receipt_counts_by_candidate=counts,
        ready_candidates_by_scope=ready_by_scope,
        selection_status=compiled.status,
        selected_roles=selected_roles,
        selected_scopes=selected_scopes,
        missing_roles=compiled.missing_roles,
        missing_selection_scopes=compiled.missing_selection_scopes,
        headline_eligible=compiled.headline_eligible,
        executable_for_conformance=executable,
        next_action=next_action,
    )


def save_model_role_document(document: BaseModel, path: str | Path) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("model-role output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = document.model_dump_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_model_role_plan(path: str | Path) -> ModelRoleConformancePlan:
    return _load_json_model(path, ModelRoleConformancePlan, "model-role conformance plan")


def load_model_role_selection(path: str | Path) -> ModelRoleSelectionManifest:
    return _load_json_model(path, ModelRoleSelectionManifest, "model-role selection manifest")


def _aggregate_candidate(
    plan: ModelRoleConformancePlan,
    planned: PlannedModelRoleCandidate,
    receipt_records: list[tuple[ModelRoleConformanceRunResult, str]],
) -> CandidateConformanceResult:
    candidate = planned.candidate
    blockers: list[str] = []
    if len(receipt_records) < candidate.minimum_receipts:
        blockers.append(
            f"requires {candidate.minimum_receipts} actual receipts; found {len(receipt_records)}"
        )
    identities = {item.exact_identity.model_stratum_sha256 for item, _ in receipt_records}
    if len(identities) > 1:
        blockers.append("exact model identity drifted across conformance receipts")
    means: dict[str, float] = {}
    if receipt_records:
        for name in plan.criteria.as_mapping():
            total = sum(item.measurements.scores()[name] for item, _ in receipt_records)
            means[name] = total / len(receipt_records)
            if means[name] < plan.criteria.as_mapping()[name].minimum:
                blockers.append(f"{name} mean is below its frozen threshold")
    score = sum(
        means.get(name, 0.0) * threshold.weight
        for name, threshold in plan.criteria.as_mapping().items()
    )
    exact_identity = receipt_records[0][0].exact_identity if len(identities) == 1 else None
    file_hashes = tuple(sorted(file_hash for _, file_hash in receipt_records))
    evidence_hash = (
        _canonical_sha256(
            {
                "receipt_files": file_hashes,
                "artifacts": sorted(
                    artifact.sha256
                    for receipt, _ in receipt_records
                    for artifact in receipt.evidence_artifacts
                ),
            }
        )
        if receipt_records
        else None
    )
    return CandidateConformanceResult(
        candidate_id=candidate.candidate_id,
        role=candidate.role,
        selection_scope_id=candidate.selection_scope_id,
        receipt_count=len(receipt_records),
        receipt_file_sha256s=file_hashes,
        exact_identity=exact_identity,
        mean_measurements=means,
        weighted_score=score,
        passes=not blockers,
        blockers=tuple(blockers),
        evidence_sha256=evidence_hash,
    )


def _load_and_verify_receipts(
    plan: ModelRoleConformancePlan,
    receipt_paths: list[str | Path],
    *,
    evidence_root: Path,
) -> list[tuple[ModelRoleConformanceRunResult, str]]:
    if receipt_paths and not plan.exclusions.conformance_task_bytes_bound:
        raise ValueError(
            "conformance suite contains planning labels only; freeze task bytes before receipts"
        )
    planned_by_id = {item.candidate.candidate_id: item for item in plan.candidates}
    records: list[tuple[ModelRoleConformanceRunResult, str]] = []
    run_ids: set[str] = set()
    for raw_path in receipt_paths:
        source = _regular_file(raw_path, "model-role conformance receipt")
        receipt = _load_json_model(source, ModelRoleConformanceRunResult, "model-role receipt")
        if receipt.run_id in run_ids:
            raise ValueError(f"duplicate model-role conformance run_id {receipt.run_id!r}")
        run_ids.add(receipt.run_id)
        planned = planned_by_id.get(receipt.candidate_id)
        if planned is None:
            raise ValueError(f"receipt references unknown candidate {receipt.candidate_id!r}")
        candidate = planned.candidate
        if receipt.suite_id != plan.suite_id or receipt.plan_sha256 != plan.plan_sha256:
            raise ValueError("model-role receipt belongs to another suite or plan")
        if receipt.role is not candidate.role:
            raise ValueError("model-role receipt role differs from its candidate")
        if receipt.selection_scope_id != candidate.selection_scope_id:
            raise ValueError("model-role receipt scope differs from its candidate")
        expected = candidate.identity
        observed = receipt.exact_identity
        if (
            observed.execution_kind is not expected.execution_kind
            or observed.provider != expected.provider
            or observed.model_id != expected.model_id
            or (expected.revision is not None and observed.revision != expected.revision)
        ):
            raise ValueError("model-role receipt identity differs from its candidate declaration")
        if receipt.profile_sha256 != planned.profile.profile_sha256:
            raise ValueError("model-role receipt profile differs from its frozen candidate")
        if receipt.budget_sha256 != planned.budget.budget_sha256:
            raise ValueError("model-role receipt budget differs from its frozen candidate")
        _verify_exclusions(plan.exclusions, receipt)
        _verify_receipt_evidence(
            receipt,
            exclusions=plan.exclusions,
            evidence_root=evidence_root,
        )
        records.append((receipt, _file_sha256(source)))
    return records


def _verify_receipt_evidence(
    receipt: ModelRoleConformanceRunResult,
    *,
    exclusions: TaskExclusionContract,
    evidence_root: Path,
) -> None:
    parsed: dict[EvidenceKind, BaseModel] = {}
    file_hashes: dict[EvidenceKind, str] = {}
    for artifact in receipt.evidence_artifacts:
        evidence = _resolve_beneath(evidence_root, artifact.locator, "conformance evidence")
        file_sha256 = _file_sha256(evidence)
        if file_sha256 != artifact.sha256:
            raise ValueError(f"conformance evidence hash drift for {artifact.locator!r}")
        parsed[artifact.kind] = _validate_evidence(artifact.validator, evidence)
        file_hashes[artifact.kind] = file_sha256

    executor = parsed[EvidenceKind.EXECUTOR_RECEIPT]
    if isinstance(executor, ConformanceExecutorReceipt):
        if (
            executor.candidate_id != receipt.candidate_id
            or executor.role is not receipt.role
            or executor.selection_scope_id != receipt.selection_scope_id
            or (executor.provider, executor.model_id, executor.revision)
            != (
                receipt.exact_identity.provider,
                receipt.exact_identity.model_id,
                receipt.exact_identity.revision,
            )
            or executor.profile_sha256 != receipt.profile_sha256
            or executor.budget_sha256 != receipt.budget_sha256
        ):
            raise ValueError("conformance executor receipt differs from the role run result")

    case_manifest = parsed[EvidenceKind.CASE_MANIFEST]
    case_results = parsed[EvidenceKind.CASE_RESULTS]
    if not isinstance(case_manifest, ConformanceCaseManifest) or not isinstance(
        case_results, ConformanceCaseResults
    ):
        raise ValueError("conformance case evidence has an invalid validator result")
    if set(receipt.task_ids) != {item.task_id for item in case_manifest.cases}:
        raise ValueError("receipt task IDs differ from its case manifest")
    if set(receipt.source_group_ids) != {item.source_group_id for item in case_manifest.cases}:
        raise ValueError("receipt source-group IDs differ from its case manifest")
    for case in case_manifest.cases:
        if exclusions.conformance_case_input_sha256[case.task_id] != case.input_sha256:
            raise ValueError("case manifest input bytes differ from the frozen task binding")
        if exclusions.conformance_source_group_by_task[case.task_id] != case.source_group_id:
            raise ValueError("case manifest source group differs from the frozen task binding")
    if case_results.case_manifest_sha256 != case_manifest.manifest_sha256:
        raise ValueError("case results differ from the case-manifest identity")
    if (
        case_results.executor_receipt_file_sha256
        != file_hashes[EvidenceKind.EXECUTOR_RECEIPT]
    ):
        raise ValueError("case results differ from the executor-receipt bytes")
    if {item.case_id for item in case_results.cases} != {
        item.case_id for item in case_manifest.cases
    }:
        raise ValueError("case results do not cover exactly the frozen case manifest")
    succeeded = sum(item.succeeded for item in case_results.cases)
    if (
        receipt.measurements.total_cases != len(case_results.cases)
        or receipt.measurements.successful_cases != succeeded
    ):
        raise ValueError("aggregate measurements differ from case-level results")


def _validate_evidence(validator: EvidenceValidator, path: Path) -> BaseModel:
    """Validator registry for native receipts and conformance case evidence."""

    if validator is EvidenceValidator.MODEL_NODE_RUNTIME_V1:
        from scitaste.model_nodes.runtime import RuntimeInvocationReceipt, RuntimeOutcome

        document = _load_json_model(path, RuntimeInvocationReceipt, "model-node runtime receipt")
        if (
            document.outcome is not RuntimeOutcome.ACCEPTED
            or document.recovered_without_provider
            or document.telemetry.cached
            or document.telemetry.replayed
            or document.recording_locator is None
        ):
            raise ValueError("model-node evidence is not an actual accepted generation")
        return document
    if validator is EvidenceValidator.BENCHMARK_DEVELOPMENT_V1:
        from scitaste.evaluation.task_execution import BenchmarkDevelopmentExecutionReceipt

        document = _load_json_model(
            path,
            BenchmarkDevelopmentExecutionReceipt,
            "benchmark development receipt",
        )
        if document.status != "succeeded":
            raise ValueError("benchmark development evidence is not a successful execution")
        return document
    model_by_validator: dict[EvidenceValidator, type[BaseModel]] = {
        EvidenceValidator.CONFORMANCE_EXECUTION_V1: ConformanceExecutorReceipt,
        EvidenceValidator.CASE_MANIFEST_V1: ConformanceCaseManifest,
        EvidenceValidator.CASE_RESULTS_V1: ConformanceCaseResults,
    }
    try:
        model = model_by_validator[validator]
    except KeyError as exc:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unsupported conformance evidence validator {validator.value!r}") from exc
    return _load_json_model(path, model, f"{validator.value} evidence")


def _verify_exclusions(
    exclusions: TaskExclusionContract,
    receipt: ModelRoleConformanceRunResult,
) -> None:
    task_ids = set(receipt.task_ids)
    source_ids = set(receipt.source_group_ids)
    if not task_ids <= set(exclusions.conformance_task_ids):
        raise ValueError("receipt contains a task outside the frozen conformance partition")
    if not source_ids <= set(exclusions.conformance_source_group_ids):
        raise ValueError("receipt contains a source group outside the conformance partition")
    prohibited_tasks = set(exclusions.formal_task_ids) | set(exclusions.heldout_task_ids)
    prohibited_sources = set(exclusions.formal_source_group_ids) | set(
        exclusions.heldout_source_group_ids
    )
    if task_ids & prohibited_tasks or source_ids & prohibited_sources:
        raise ValueError("formal or heldout material contaminated model-role selection")


def _choose_role_binding(
    role: ModelRole,
    selection_scope_id: str,
    results: tuple[CandidateConformanceResult, ...],
    planned_by_id: dict[str, PlannedModelRoleCandidate],
    *,
    headline_independent: bool,
) -> SelectedModelRoleBinding | None:
    result = _rank_results(
        [
            item
            for item in results
            if item.role is role and item.selection_scope_id == selection_scope_id and item.passes
        ]
    )
    if result is None:
        return None
    return _binding_from_result(
        result,
        planned_by_id[result.candidate_id],
        headline_independent=headline_independent,
    )


def _binding_from_result(
    result: CandidateConformanceResult,
    planned: PlannedModelRoleCandidate,
    *,
    headline_independent: bool,
) -> SelectedModelRoleBinding:
    if result.exact_identity is None or result.evidence_sha256 is None:
        raise ValueError("passing candidate lacks exact identity or evidence hash")
    return SelectedModelRoleBinding(
        role=result.role,
        selection_scope_id=result.selection_scope_id,
        candidate_id=result.candidate_id,
        resource_id=planned.candidate.resource_id,
        exact_identity=result.exact_identity,
        profile=planned.profile,
        budget=planned.budget,
        weighted_score=result.weighted_score,
        evidence_sha256=result.evidence_sha256,
        headline_independent=headline_independent,
    )


def _rank_results(
    results: list[CandidateConformanceResult],
) -> CandidateConformanceResult | None:
    if not results:
        return None
    return sorted(results, key=lambda item: (-item.weighted_score, item.candidate_id))[0]


def _scope_key(role: ModelRole, selection_scope_id: str) -> str:
    return f"{role.value}:{selection_scope_id}"


def _inventory_role_fit(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for section, id_field in (("api_models", "resource_id"), ("local_assets", "asset_id")):
        entries = payload.get(section)
        if not isinstance(entries, list):
            raise ValueError(f"model-role inventory requires a {section!r} list")
        for raw in entries:
            if not isinstance(raw, dict) or not isinstance(raw.get(id_field), str):
                raise ValueError(f"invalid model-role inventory entry in {section!r}")
            role_fit = raw.get("role_fit")
            if not isinstance(role_fit, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in role_fit.items()
            ):
                raise ValueError("inventory role_fit must map role names to statuses")
            identifier = str(raw[id_field])
            if identifier in result:
                raise ValueError(f"duplicate model resource ID {identifier!r}")
            result[identifier] = {str(key): str(value) for key, value in role_fit.items()}
    return result


def _load_yaml_object(path: str | Path, label: str) -> tuple[Path, dict[str, object]]:
    source = _regular_file(path, label)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} must contain valid UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    return source, payload


def _load_json_model(path: str | Path, model: type[BaseModel], label: str):
    source = _regular_file(path, label)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    serialized_hash = None
    hash_field = None
    for candidate in ("plan_sha256", "selection_sha256"):
        if candidate in payload and candidate in getattr(model, "model_computed_fields", {}):
            serialized_hash = payload.pop(candidate)
            hash_field = candidate
            break
    document = model.model_validate(payload)
    if hash_field is not None and getattr(document, hash_field) != serialized_hash:
        raise ValueError(f"{label} serialized content hash is invalid")
    return document


def _regular_file(path: str | Path, label: str) -> Path:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    if source.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds its size limit")
    return source.resolve(strict=True)


def _resolve_beneath(root: Path, locator: str, label: str) -> Path:
    _validate_relative_path(locator, f"{label} locator")
    candidate = root / PurePosixPath(locator)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"{label} is missing or escapes its evidence root: {locator!r}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    if resolved.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds its size limit")
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "//" in value
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_unique(values: list[str] | tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"model-role {label} must be unique")


__all__ = [
    "CandidateConformanceResult",
    "ConformanceCase",
    "ConformanceCaseManifest",
    "ConformanceCaseResult",
    "ConformanceCaseResults",
    "ConformanceExecutorReceipt",
    "ConformanceMeasurements",
    "EvidenceArtifact",
    "EvidenceKind",
    "EvidenceValidator",
    "ExactModelIdentity",
    "ExecutionKind",
    "FrozenConformanceCriteria",
    "IdentityScope",
    "ModelRole",
    "ModelRoleCandidate",
    "ModelRoleConformancePlan",
    "ModelRoleConformanceRunResult",
    "ModelRoleConformanceStatus",
    "ModelRoleConformanceSuite",
    "ModelRoleSelectionManifest",
    "RoleBudget",
    "RoleProfileSpec",
    "SelectedModelRoleBinding",
    "SelectionStatus",
    "compile_model_role_selection",
    "inspect_model_role_conformance",
    "load_model_role_plan",
    "load_model_role_selection",
    "plan_model_role_conformance",
    "save_model_role_document",
]
