"""Preregistered paired evaluation for bounded Tool Intelligence quality."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
    model_validator,
)

from scitaste.data.models import KnowledgeDocument
from scitaste.model_nodes.tool_bindings import (
    ProjectEvidenceRecord,
    RegisteredRunMetricsRecord,
)
from scitaste.model_nodes.tool_execution import ReadOnlyToolHandler
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolName,
    EvidenceInspectArguments,
    EvidenceInspectStep,
    KnowledgeQueryArguments,
    KnowledgeQueryStep,
    RegisteredRunCompareArguments,
    RegisteredRunCompareStep,
    ToolPlanStep,
    ToolScopeProjection,
    canonical_sha256,
)

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
ScopedValue = Annotated[str, Field(pattern=_IDENTIFIER, max_length=128)]


class ToolEffectivenessError(ValueError):
    """Raised when a study definition or paired result is not auditable."""


class ToolEffectivenessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolEffectivenessCondition(StrEnum):
    V2_FIXED_ROUTER = "v2-fixed-router"
    V3_LIVE_PROJECT_LOOP = "v3-live-project-loop"


class ToolEffectivenessStratum(StrEnum):
    EXPLICIT = "explicit-routing"
    SEMANTIC = "semantic-routing"


class ToolEffectivenessGoldTarget(ToolEffectivenessModel):
    """Expert-authored target fixed before any provider response is observed."""

    expected_tool_name: ControlledToolName
    required_library_ids: tuple[ScopedValue, ...] = ()
    required_evidence_ids: tuple[ScopedValue, ...] = ()
    required_run_ids: tuple[ScopedValue, ...] = ()
    required_metric_names: tuple[ScopedValue, ...] = ()
    expected_observation_ids: tuple[ScopedValue, ...] = Field(min_length=1)

    @field_validator(
        "required_library_ids",
        "required_evidence_ids",
        "required_run_ids",
        "required_metric_names",
        "expected_observation_ids",
    )
    @classmethod
    def identifiers_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("gold identifiers must not contain duplicates")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def target_matches_tool(self) -> ToolEffectivenessGoldTarget:
        requirements = {
            ControlledToolName.KNOWLEDGE_QUERY: bool(self.required_library_ids),
            ControlledToolName.EVIDENCE_INSPECT: bool(self.required_evidence_ids),
            ControlledToolName.REGISTERED_RUN_COMPARE: bool(
                self.required_run_ids and self.required_metric_names
            ),
        }
        if not requirements[self.expected_tool_name]:
            raise ValueError("gold target lacks the identifiers required by its tool")
        unrelated = {
            ControlledToolName.KNOWLEDGE_QUERY: (
                self.required_evidence_ids,
                self.required_run_ids,
                self.required_metric_names,
            ),
            ControlledToolName.EVIDENCE_INSPECT: (
                self.required_library_ids,
                self.required_run_ids,
                self.required_metric_names,
            ),
            ControlledToolName.REGISTERED_RUN_COMPARE: (
                self.required_library_ids,
                self.required_evidence_ids,
            ),
        }
        if any(unrelated[self.expected_tool_name]):
            raise ValueError("gold target mixes identifiers from unrelated tools")
        return self


class ToolEffectivenessTask(ToolEffectivenessModel):
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    stratum: ToolEffectivenessStratum
    objective: str = Field(min_length=1, max_length=4_000)
    scope: ToolScopeProjection
    candidate_tool_names: tuple[ControlledToolName, ...] = Field(min_length=2, max_length=3)
    gold: ToolEffectivenessGoldTarget

    @field_validator("candidate_tool_names")
    @classmethod
    def candidate_tools_are_unique(
        cls, values: tuple[ControlledToolName, ...]
    ) -> tuple[ControlledToolName, ...]:
        if len(values) != len(set(values)):
            raise ValueError("candidate tools must not contain duplicates")
        return tuple(sorted(values, key=lambda item: item.value))

    @model_validator(mode="after")
    def gold_is_inside_visible_scope(self) -> ToolEffectivenessTask:
        if self.gold.expected_tool_name not in self.candidate_tool_names:
            raise ValueError("gold tool is absent from the task candidate set")
        checks = (
            (self.gold.required_library_ids, self.scope.library_ids),
            (self.gold.required_evidence_ids, self.scope.evidence_ids),
            (self.gold.required_run_ids, self.scope.run_ids),
            (self.gold.required_metric_names, self.scope.metric_names),
        )
        if any(set(required) - set(visible) for required, visible in checks):
            raise ValueError("gold target escapes the task-visible scope")
        return self


class ToolEffectivenessProtocol(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    protocol_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=2)
    tasks: tuple[ToolEffectivenessTask, ...] = Field(min_length=4)
    primary_endpoint: Literal["grounded_resolution_correct"] = "grounded_resolution_correct"
    analysis_unit: Literal["task-majority-over-seeds"] = "task-majority-over-seeds"
    alpha: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)
    minimum_paired_trials: int = Field(default=20, ge=4)
    minimum_independent_tasks: int = Field(default=12, ge=6)
    condition_order_blinded: Literal[True] = True
    independent_domain_review_required: Literal[True] = True
    external_validity: Literal["unestablished"] = "unestablished"

    @field_validator("seeds")
    @classmethod
    def seeds_are_unique(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 for value in values) or len(values) != len(set(values)):
            raise ValueError("study seeds must be unique non-negative integers")
        if len(values) % 2 == 0:
            raise ValueError("task-majority analysis requires an odd number of seeds")
        return values

    @model_validator(mode="after")
    def task_matrix_is_preregistered(self) -> ToolEffectivenessProtocol:
        identifiers = [task.task_id for task in self.tasks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("study task IDs must be unique")
        if len(self.tasks) * len(self.seeds) < self.minimum_paired_trials:
            raise ValueError("study matrix is smaller than minimum_paired_trials")
        if len(self.tasks) < self.minimum_independent_tasks:
            raise ValueError("study has too few independent task units")
        strata = {task.stratum for task in self.tasks}
        if strata != set(ToolEffectivenessStratum):
            raise ValueError("study must include explicit and semantic routing strata")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolEffectivenessFixture(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    fixture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    protocol: ToolEffectivenessProtocol
    knowledge_libraries: dict[ScopedValue, tuple[KnowledgeDocument, ...]]
    evidence_records: tuple[ProjectEvidenceRecord, ...]
    run_metrics: tuple[RegisteredRunMetricsRecord, ...]

    @model_validator(mode="after")
    def resources_cover_every_scope(self) -> ToolEffectivenessFixture:
        document_ids: set[str] = set()
        for library_id, documents in self.knowledge_libraries.items():
            if not documents:
                raise ValueError(f"knowledge library {library_id!r} is empty")
            ids = [item.document_id for item in documents]
            if len(ids) != len(set(ids)) or document_ids.intersection(ids):
                raise ValueError("knowledge document IDs must be globally unique")
            document_ids.update(ids)
        evidence_ids = [item.evidence.evidence_id for item in self.evidence_records]
        run_ids = [item.run_id for item in self.run_metrics]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("fixture evidence IDs must be unique")
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("fixture run metric IDs must be unique")
        metrics = {name for row in self.run_metrics for name in row.metrics}
        for task in self.protocol.tasks:
            if set(task.scope.library_ids) - set(self.knowledge_libraries):
                raise ValueError("task references an unknown fixture library")
            if set(task.scope.evidence_ids) - set(evidence_ids):
                raise ValueError("task references unknown fixture evidence")
            if set(task.scope.run_ids) - set(run_ids):
                raise ValueError("task references unknown fixture run metrics")
            if set(task.scope.metric_names) - metrics:
                raise ValueError("task references an unknown fixture metric")
            if set(task.gold.expected_observation_ids) - (
                document_ids | set(evidence_ids) | set(run_ids)
            ):
                raise ValueError("gold observation references an unknown fixture record")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolEffectivenessTrial(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    pair_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    stratum: ToolEffectivenessStratum
    seed: int = Field(ge=0)
    condition: ToolEffectivenessCondition
    model_admitted: bool
    workflow_resolved: bool
    selected_step: ToolPlanStep | None = None
    observation_payload: dict[str, JsonValue] | None = None
    action_correct: bool
    grounded_resolution_correct: bool
    scope_violation_detected: bool
    model_invocations: int = Field(ge=0, le=1)
    tool_invocations: int = Field(ge=0, le=1)
    input_tokens: int = Field(ge=0)
    prompt_cache_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(ge=0, le=1)
    model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    raw_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_locator: str | None = None
    failure_reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> ToolEffectivenessTrial:
        if self.prompt_cache_input_tokens > self.input_tokens:
            raise ValueError("prompt cache tokens exceed trial input tokens")
        if self.workflow_resolved and (
            self.selected_step is None or self.observation_payload is None
        ):
            raise ValueError("resolved trial requires a selected step and observation")
        if self.grounded_resolution_correct and not (
            self.workflow_resolved and self.action_correct and not self.scope_violation_detected
        ):
            raise ValueError("grounded correctness requires a safe correct resolved action")
        if self.condition is ToolEffectivenessCondition.V2_FIXED_ROUTER:
            if self.model_invocations or self.input_tokens or self.output_tokens:
                raise ValueError("fixed-router baseline cannot contain model usage")
            if self.model_admitted or self.raw_response_sha256 is not None:
                raise ValueError("fixed-router baseline cannot contain a model response")
        if self.unknown_cost_count and self.known_cost_usd:
            raise ValueError("one trial cannot report known and unknown model cost")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class WilsonInterval(ToolEffectivenessModel):
    lower: float = Field(ge=0, le=1, allow_inf_nan=False)
    upper: float = Field(ge=0, le=1, allow_inf_nan=False)


class ToolEffectivenessConditionMetrics(ToolEffectivenessModel):
    condition: ToolEffectivenessCondition
    trial_count: int = Field(ge=1)
    model_admission_rate: float = Field(ge=0, le=1)
    workflow_resolution_rate: float = Field(ge=0, le=1)
    action_accuracy: float = Field(ge=0, le=1)
    grounded_resolution_accuracy: float = Field(ge=0, le=1)
    grounded_resolution_wilson95: WilsonInterval
    scope_violation_rate: float = Field(ge=0, le=1)
    model_invocations: int = Field(ge=0)
    tool_invocations: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    prompt_cache_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(ge=0)
    mean_model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    mean_tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)


class ToolEffectivenessPairedTest(ToolEffectivenessModel):
    endpoint: Literal["grounded_resolution_correct"] = "grounded_resolution_correct"
    analysis_unit: Literal["task-majority-over-seeds"] = "task-majority-over-seeds"
    improved_pairs: int = Field(ge=0)
    regressed_pairs: int = Field(ge=0)
    tied_pairs: int = Field(ge=0)
    absolute_accuracy_gain: float = Field(ge=-1, le=1, allow_inf_nan=False)
    exact_two_sided_mcnemar_p: float | None = Field(default=None, ge=0, le=1)


class ToolEffectivenessStudyReport(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str
    protocol_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    replicate_pair_count: int = Field(ge=1)
    independent_task_count: int = Field(ge=1)
    baseline: ToolEffectivenessConditionMetrics
    treatment: ToolEffectivenessConditionMetrics
    paired_test: ToolEffectivenessPairedTest
    preliminary_effectiveness_signal: bool
    independent_domain_review_complete: Literal[False] = False
    scientific_effectiveness_claim: Literal[False] = False
    benchmark_scope: Literal["bounded-project-evidence-acquisition"] = (
        "bounded-project-evidence-acquisition"
    )
    external_validity: Literal["unestablished"] = "unestablished"

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolEffectivenessBlindItem(ToolEffectivenessModel):
    blind_id: str = Field(pattern=r"^blind-[0-9a-f]{24}$")
    objective: str
    selected_step: ToolPlanStep | None = None
    observation_payload: dict[str, JsonValue] | None = None
    failure_reason_codes: tuple[str, ...] = ()


class ToolEffectivenessBlindPacket(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: tuple[ToolEffectivenessBlindItem, ...] = Field(min_length=1)
    condition_hidden: Literal[True] = True
    gold_hidden: Literal[True] = True

    @model_validator(mode="after")
    def blind_ids_are_unique(self) -> ToolEffectivenessBlindPacket:
        identifiers = [item.blind_id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("blind review IDs must be unique")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolEffectivenessBlindKeyEntry(ToolEffectivenessModel):
    blind_id: str = Field(pattern=r"^blind-[0-9a-f]{24}$")
    pair_id: str
    task_id: str
    seed: int = Field(ge=0)
    condition: ToolEffectivenessCondition
    trial_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ToolEffectivenessBlindKey(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    packet_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[ToolEffectivenessBlindKeyEntry, ...] = Field(min_length=1)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolEffectivenessBlindReviewRating(ToolEffectivenessModel):
    blind_id: str = Field(pattern=r"^blind-[0-9a-f]{24}$")
    grounded_and_relevant: bool
    scope_appropriate: bool
    rationale: str = Field(min_length=1, max_length=2_000)
    confidence: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def usable_rating_requires_safe_scope(self) -> ToolEffectivenessBlindReviewRating:
        if self.grounded_and_relevant and not self.scope_appropriate:
            raise ValueError("a grounded review rating cannot approve inappropriate scope")
        return self


class ToolEffectivenessBlindReview(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    review_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    reviewer_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    packet_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    independence_attested: Literal[True]
    fixture_author: Literal[False]
    private_key_received_before_completion: Literal[False]
    ratings: tuple[ToolEffectivenessBlindReviewRating, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def blind_ids_are_unique(self) -> ToolEffectivenessBlindReview:
        identifiers = [item.blind_id for item in self.ratings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("blind review ratings contain duplicate IDs")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolEffectivenessIndependentReviewReport(ToolEffectivenessModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    packet_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_id: str
    rating_count: int = Field(ge=1)
    replicate_pair_count: int = Field(ge=1)
    independent_task_count: int = Field(ge=1)
    baseline_grounded_relevance_rate: float = Field(ge=0, le=1)
    treatment_grounded_relevance_rate: float = Field(ge=0, le=1)
    baseline_scope_appropriate_rate: float = Field(ge=0, le=1)
    treatment_scope_appropriate_rate: float = Field(ge=0, le=1)
    improved_task_pairs: int = Field(ge=0)
    regressed_task_pairs: int = Field(ge=0)
    tied_task_pairs: int = Field(ge=0)
    exact_two_sided_mcnemar_p: float | None = Field(default=None, ge=0, le=1)
    independent_domain_review_complete: Literal[True] = True
    scientific_effectiveness_claim: Literal[False] = False
    external_validity: Literal["unestablished"] = "unestablished"

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


def load_tool_effectiveness_fixture(path: str | Path) -> ToolEffectivenessFixture:
    """Load a strict JSON preregistration without accepting duplicate keys."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = source.read_text(encoding="utf-8")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return ToolEffectivenessFixture.model_validate_json(encoded, strict=True)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ToolEffectivenessError("invalid Tool Intelligence effectiveness fixture") from exc


def deterministic_v2_router(task: ToolEffectivenessTask) -> ToolPlanStep:
    """Frozen no-model baseline approximating a caller-bound keyword router."""

    objective = task.objective.casefold()
    mentioned_evidence = _mentioned(task.scope.evidence_ids, objective)
    mentioned_runs = _mentioned(task.scope.run_ids, objective)
    mentioned_metrics = _mentioned(task.scope.metric_names, objective)
    if mentioned_evidence or "inspect evidence" in objective or "evidence record" in objective:
        selected = ControlledToolName.EVIDENCE_INSPECT
    elif (
        len(mentioned_runs) >= 2
        or "compare registered runs" in objective
        or "registered-run comparison" in objective
    ):
        selected = ControlledToolName.REGISTERED_RUN_COMPARE
    elif "search the knowledge" in objective or "knowledge query" in objective:
        selected = ControlledToolName.KNOWLEDGE_QUERY
    else:
        selected = min(task.candidate_tool_names, key=lambda item: item.value)
    if selected not in task.candidate_tool_names:
        selected = min(task.candidate_tool_names, key=lambda item: item.value)

    if selected is ControlledToolName.KNOWLEDGE_QUERY:
        libraries = _mentioned(task.scope.library_ids, objective) or task.scope.library_ids[:1]
        return KnowledgeQueryStep(
            step_id="baseline-step",
            purpose="Frozen keyword-router knowledge lookup.",
            arguments=KnowledgeQueryArguments(
                query=task.objective,
                library_ids=libraries,
                top_k=3,
            ),
        )
    if selected is ControlledToolName.EVIDENCE_INSPECT:
        evidence = mentioned_evidence or task.scope.evidence_ids[:1]
        return EvidenceInspectStep(
            step_id="baseline-step",
            purpose="Frozen keyword-router evidence inspection.",
            arguments=EvidenceInspectArguments(evidence_ids=evidence[:1]),
        )
    runs = mentioned_runs if len(mentioned_runs) >= 2 else task.scope.run_ids[:2]
    metrics = mentioned_metrics or task.scope.metric_names[:1]
    return RegisteredRunCompareStep(
        step_id="baseline-step",
        purpose="Frozen keyword-router registered-run comparison.",
        arguments=RegisteredRunCompareArguments(run_ids=runs[:2], metric_names=metrics[:1]),
    )


def execute_read_only_step(
    step: ToolPlanStep,
    handlers: tuple[ReadOnlyToolHandler, ...],
) -> dict[str, JsonValue]:
    """Execute one trusted fixture handler for the fixed baseline only."""

    registry = {handler.descriptor.tool_name: handler for handler in handlers}
    if len(registry) != len(handlers) or step.tool_name not in registry:
        raise ToolEffectivenessError("study handler registry is incomplete or ambiguous")
    return registry[step.tool_name].execute(step.arguments)


def build_tool_effectiveness_trial(
    *,
    fixture: ToolEffectivenessFixture,
    task: ToolEffectivenessTask,
    seed: int,
    condition: ToolEffectivenessCondition,
    model_admitted: bool,
    workflow_resolved: bool,
    selected_step: ToolPlanStep | None,
    observation_payload: dict[str, JsonValue] | None,
    model_invocations: int,
    tool_invocations: int,
    input_tokens: int = 0,
    prompt_cache_input_tokens: int = 0,
    output_tokens: int = 0,
    known_cost_usd: float = 0.0,
    unknown_cost_count: int = 0,
    model_latency_ms: float = 0.0,
    tool_latency_ms: float = 0.0,
    raw_response_sha256: str | None = None,
    evidence_locator: str | None = None,
    failure_reason_codes: tuple[str, ...] = (),
) -> ToolEffectivenessTrial:
    action_correct, grounded, scope_violation = score_tool_effectiveness_outcome(
        task,
        selected_step=selected_step,
        observation_payload=observation_payload,
        workflow_resolved=workflow_resolved,
    )
    return ToolEffectivenessTrial(
        protocol_fingerprint=fixture.protocol.fingerprint,
        fixture_fingerprint=fixture.fingerprint,
        pair_id=f"{task.task_id}.seed-{seed}",
        task_id=task.task_id,
        stratum=task.stratum,
        seed=seed,
        condition=condition,
        model_admitted=model_admitted,
        workflow_resolved=workflow_resolved,
        selected_step=selected_step,
        observation_payload=observation_payload,
        action_correct=action_correct,
        grounded_resolution_correct=grounded,
        scope_violation_detected=scope_violation,
        model_invocations=model_invocations,
        tool_invocations=tool_invocations,
        input_tokens=input_tokens,
        prompt_cache_input_tokens=prompt_cache_input_tokens,
        output_tokens=output_tokens,
        known_cost_usd=known_cost_usd,
        unknown_cost_count=unknown_cost_count,
        model_latency_ms=model_latency_ms,
        tool_latency_ms=tool_latency_ms,
        raw_response_sha256=raw_response_sha256,
        evidence_locator=evidence_locator,
        failure_reason_codes=failure_reason_codes,
    )


def score_tool_effectiveness_outcome(
    task: ToolEffectivenessTask,
    *,
    selected_step: ToolPlanStep | None,
    observation_payload: dict[str, JsonValue] | None,
    workflow_resolved: bool,
) -> tuple[bool, bool, bool]:
    if selected_step is None:
        return False, False, False
    scope_violation = _scope_violation(task.scope, selected_step)
    action_correct = not scope_violation and _action_matches(task.gold, selected_step)
    observed = _observation_ids(observation_payload) if observation_payload is not None else set()
    grounded = bool(
        workflow_resolved
        and action_correct
        and set(task.gold.expected_observation_ids).issubset(observed)
    )
    return action_correct, grounded, scope_violation


def evaluate_tool_effectiveness_study(
    fixture: ToolEffectivenessFixture,
    trials: tuple[ToolEffectivenessTrial, ...],
) -> ToolEffectivenessStudyReport:
    expected_pairs = {
        f"{task.task_id}.seed-{seed}"
        for task in fixture.protocol.tasks
        for seed in fixture.protocol.seeds
    }
    grouped: dict[str, dict[ToolEffectivenessCondition, ToolEffectivenessTrial]] = {}
    for trial in trials:
        if (
            trial.protocol_fingerprint != fixture.protocol.fingerprint
            or trial.fixture_fingerprint != fixture.fingerprint
        ):
            raise ToolEffectivenessError("trial belongs to another protocol or fixture")
        conditions = grouped.setdefault(trial.pair_id, {})
        if trial.condition in conditions:
            raise ToolEffectivenessError("duplicate condition in one paired trial")
        conditions[trial.condition] = trial
    if set(grouped) != expected_pairs or any(
        set(values) != set(ToolEffectivenessCondition) for values in grouped.values()
    ):
        raise ToolEffectivenessError("study trials do not form the exact preregistered matrix")

    baseline_trials = tuple(
        grouped[pair][ToolEffectivenessCondition.V2_FIXED_ROUTER] for pair in sorted(grouped)
    )
    treatment_trials = tuple(
        grouped[pair][ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP] for pair in sorted(grouped)
    )
    baseline = _condition_metrics(ToolEffectivenessCondition.V2_FIXED_ROUTER, baseline_trials)
    treatment = _condition_metrics(
        ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP, treatment_trials
    )
    task_outcomes: list[tuple[bool, bool]] = []
    for task in fixture.protocol.tasks:
        task_baseline = tuple(
            grouped[f"{task.task_id}.seed-{seed}"][ToolEffectivenessCondition.V2_FIXED_ROUTER]
            for seed in fixture.protocol.seeds
        )
        task_treatment = tuple(
            grouped[f"{task.task_id}.seed-{seed}"][ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP]
            for seed in fixture.protocol.seeds
        )
        threshold = len(fixture.protocol.seeds) // 2
        task_outcomes.append(
            (
                sum(item.grounded_resolution_correct for item in task_baseline) > threshold,
                sum(item.grounded_resolution_correct for item in task_treatment) > threshold,
            )
        )
    improved = sum((not left) and right for left, right in task_outcomes)
    regressed = sum(left and (not right) for left, right in task_outcomes)
    paired_test = ToolEffectivenessPairedTest(
        improved_pairs=improved,
        regressed_pairs=regressed,
        tied_pairs=len(task_outcomes) - improved - regressed,
        absolute_accuracy_gain=(
            treatment.grounded_resolution_accuracy - baseline.grounded_resolution_accuracy
        ),
        exact_two_sided_mcnemar_p=_exact_two_sided_mcnemar(improved, regressed),
    )
    signal = bool(
        len(baseline_trials) >= fixture.protocol.minimum_paired_trials
        and len(task_outcomes) >= fixture.protocol.minimum_independent_tasks
        and paired_test.absolute_accuracy_gain > 0
        and paired_test.exact_two_sided_mcnemar_p is not None
        and paired_test.exact_two_sided_mcnemar_p <= fixture.protocol.alpha
        and treatment.scope_violation_rate == 0
    )
    return ToolEffectivenessStudyReport(
        protocol_id=fixture.protocol.protocol_id,
        protocol_fingerprint=fixture.protocol.fingerprint,
        fixture_fingerprint=fixture.fingerprint,
        replicate_pair_count=len(baseline_trials),
        independent_task_count=len(task_outcomes),
        baseline=baseline,
        treatment=treatment,
        paired_test=paired_test,
        preliminary_effectiveness_signal=signal,
    )


def build_tool_effectiveness_blind_packet(
    fixture: ToolEffectivenessFixture,
    trials: tuple[ToolEffectivenessTrial, ...],
    *,
    blinding_salt: str,
) -> tuple[ToolEffectivenessBlindPacket, ToolEffectivenessBlindKey]:
    if len(blinding_salt) < 16:
        raise ToolEffectivenessError("blinding salt must contain at least 16 characters")
    tasks = {task.task_id: task for task in fixture.protocol.tasks}
    items: list[ToolEffectivenessBlindItem] = []
    key_values: list[tuple[ToolEffectivenessTrial, str]] = []
    for trial in trials:
        if trial.task_id not in tasks:
            raise ToolEffectivenessError("trial references an unknown review task")
        digest = hashlib.sha256(f"{blinding_salt}:{trial.fingerprint}".encode()).hexdigest()
        blind_id = f"blind-{digest[:24]}"
        items.append(
            ToolEffectivenessBlindItem(
                blind_id=blind_id,
                objective=tasks[trial.task_id].objective,
                selected_step=trial.selected_step,
                observation_payload=trial.observation_payload,
                failure_reason_codes=trial.failure_reason_codes,
            )
        )
        key_values.append((trial, blind_id))
    items.sort(key=lambda item: item.blind_id)
    packet = ToolEffectivenessBlindPacket(
        protocol_fingerprint=fixture.protocol.fingerprint,
        items=tuple(items),
    )
    key = ToolEffectivenessBlindKey(
        packet_fingerprint=packet.fingerprint,
        entries=tuple(
            ToolEffectivenessBlindKeyEntry(
                blind_id=blind_id,
                pair_id=trial.pair_id,
                task_id=trial.task_id,
                seed=trial.seed,
                condition=trial.condition,
                trial_fingerprint=trial.fingerprint,
            )
            for trial, blind_id in sorted(key_values, key=lambda item: item[1])
        ),
    )
    return packet, key


def evaluate_tool_effectiveness_blind_review(
    fixture: ToolEffectivenessFixture,
    packet: ToolEffectivenessBlindPacket,
    key: ToolEffectivenessBlindKey,
    review: ToolEffectivenessBlindReview,
) -> ToolEffectivenessIndependentReviewReport:
    """Validate and unblind one complete independent secondary-outcome review."""

    if (
        packet.protocol_fingerprint != fixture.protocol.fingerprint
        or key.packet_fingerprint != packet.fingerprint
        or review.packet_fingerprint != packet.fingerprint
    ):
        raise ToolEffectivenessError("blind review identity differs from the study packet")
    packet_ids = {item.blind_id for item in packet.items}
    key_by_id = {item.blind_id: item for item in key.entries}
    ratings = {item.blind_id: item for item in review.ratings}
    if set(key_by_id) != packet_ids or set(ratings) != packet_ids:
        raise ToolEffectivenessError("blind review does not cover the exact packet")

    expected_pairs = len(fixture.protocol.tasks) * len(fixture.protocol.seeds)
    if len(packet_ids) != expected_pairs * len(ToolEffectivenessCondition):
        raise ToolEffectivenessError("blind packet does not contain the exact paired matrix")

    unblinded: dict[
        tuple[str, int, ToolEffectivenessCondition], ToolEffectivenessBlindReviewRating
    ] = {}
    for blind_id, entry in key_by_id.items():
        identity = (entry.task_id, entry.seed, entry.condition)
        if identity in unblinded:
            raise ToolEffectivenessError("blind key contains a duplicate trial identity")
        unblinded[identity] = ratings[blind_id]

    condition_ratings: dict[
        ToolEffectivenessCondition, list[ToolEffectivenessBlindReviewRating]
    ] = {condition: [] for condition in ToolEffectivenessCondition}
    task_outcomes: list[tuple[bool, bool]] = []
    threshold = len(fixture.protocol.seeds) // 2
    for task in fixture.protocol.tasks:
        per_condition: dict[ToolEffectivenessCondition, list[bool]] = {
            condition: [] for condition in ToolEffectivenessCondition
        }
        for seed in fixture.protocol.seeds:
            for condition in ToolEffectivenessCondition:
                try:
                    rating = unblinded[(task.task_id, seed, condition)]
                except KeyError as exc:
                    raise ToolEffectivenessError(
                        "blind key does not match the preregistered matrix"
                    ) from exc
                condition_ratings[condition].append(rating)
                per_condition[condition].append(rating.grounded_and_relevant)
        task_outcomes.append(
            (
                sum(per_condition[ToolEffectivenessCondition.V2_FIXED_ROUTER]) > threshold,
                sum(per_condition[ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP]) > threshold,
            )
        )

    baseline = condition_ratings[ToolEffectivenessCondition.V2_FIXED_ROUTER]
    treatment = condition_ratings[ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP]
    improved = sum((not left) and right for left, right in task_outcomes)
    regressed = sum(left and (not right) for left, right in task_outcomes)
    return ToolEffectivenessIndependentReviewReport(
        protocol_fingerprint=fixture.protocol.fingerprint,
        packet_fingerprint=packet.fingerprint,
        review_fingerprint=review.fingerprint,
        reviewer_id=review.reviewer_id,
        rating_count=len(review.ratings),
        replicate_pair_count=expected_pairs,
        independent_task_count=len(fixture.protocol.tasks),
        baseline_grounded_relevance_rate=(
            sum(item.grounded_and_relevant for item in baseline) / len(baseline)
        ),
        treatment_grounded_relevance_rate=(
            sum(item.grounded_and_relevant for item in treatment) / len(treatment)
        ),
        baseline_scope_appropriate_rate=(
            sum(item.scope_appropriate for item in baseline) / len(baseline)
        ),
        treatment_scope_appropriate_rate=(
            sum(item.scope_appropriate for item in treatment) / len(treatment)
        ),
        improved_task_pairs=improved,
        regressed_task_pairs=regressed,
        tied_task_pairs=len(task_outcomes) - improved - regressed,
        exact_two_sided_mcnemar_p=_exact_two_sided_mcnemar(improved, regressed),
    )


def _condition_metrics(
    condition: ToolEffectivenessCondition,
    trials: tuple[ToolEffectivenessTrial, ...],
) -> ToolEffectivenessConditionMetrics:
    count = len(trials)
    successes = sum(trial.grounded_resolution_correct for trial in trials)
    return ToolEffectivenessConditionMetrics(
        condition=condition,
        trial_count=count,
        model_admission_rate=sum(trial.model_admitted for trial in trials) / count,
        workflow_resolution_rate=sum(trial.workflow_resolved for trial in trials) / count,
        action_accuracy=sum(trial.action_correct for trial in trials) / count,
        grounded_resolution_accuracy=successes / count,
        grounded_resolution_wilson95=_wilson(successes, count),
        scope_violation_rate=sum(trial.scope_violation_detected for trial in trials) / count,
        model_invocations=sum(trial.model_invocations for trial in trials),
        tool_invocations=sum(trial.tool_invocations for trial in trials),
        input_tokens=sum(trial.input_tokens for trial in trials),
        prompt_cache_input_tokens=sum(trial.prompt_cache_input_tokens for trial in trials),
        output_tokens=sum(trial.output_tokens for trial in trials),
        known_cost_usd=sum(trial.known_cost_usd for trial in trials),
        unknown_cost_count=sum(trial.unknown_cost_count for trial in trials),
        mean_model_latency_ms=statistics.fmean(trial.model_latency_ms for trial in trials),
        mean_tool_latency_ms=statistics.fmean(trial.tool_latency_ms for trial in trials),
    )


def _wilson(successes: int, total: int) -> WilsonInterval:
    z = 1.959963984540054
    probability = successes / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    half = (
        z
        * math.sqrt(probability * (1 - probability) / total + z * z / (4 * total * total))
        / denominator
    )
    return WilsonInterval(lower=max(0.0, center - half), upper=min(1.0, center + half))


def _exact_two_sided_mcnemar(improved: int, regressed: int) -> float | None:
    discordant = improved + regressed
    if discordant == 0:
        return None
    tail = sum(math.comb(discordant, index) for index in range(min(improved, regressed) + 1)) / (
        2**discordant
    )
    return min(1.0, 2 * tail)


def _action_matches(gold: ToolEffectivenessGoldTarget, step: ToolPlanStep) -> bool:
    if step.tool_name is not gold.expected_tool_name:
        return False
    arguments = step.arguments
    if isinstance(arguments, KnowledgeQueryArguments):
        return set(gold.required_library_ids).issubset(arguments.library_ids)
    if isinstance(arguments, EvidenceInspectArguments):
        return set(gold.required_evidence_ids).issubset(arguments.evidence_ids)
    return set(gold.required_run_ids).issubset(arguments.run_ids) and set(
        gold.required_metric_names
    ).issubset(arguments.metric_names)


def _scope_violation(scope: ToolScopeProjection, step: ToolPlanStep) -> bool:
    arguments = step.arguments
    if isinstance(arguments, KnowledgeQueryArguments):
        return bool(set(arguments.library_ids) - set(scope.library_ids))
    if isinstance(arguments, EvidenceInspectArguments):
        return bool(set(arguments.evidence_ids) - set(scope.evidence_ids))
    return bool(
        set(arguments.run_ids) - set(scope.run_ids)
        or set(arguments.metric_names) - set(scope.metric_names)
    )


def _observation_ids(payload: dict[str, JsonValue]) -> set[str]:
    identifiers: set[str] = set()
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in ("document_id", "evidence_id"):
                value = item.get(field)
                if isinstance(value, str):
                    identifiers.add(value)
    rows = payload.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("run_id"), str):
                identifiers.add(row["run_id"])
    return identifiers


def _mentioned(options: tuple[str, ...], objective: str) -> tuple[str, ...]:
    return tuple(value for value in options if value.casefold() in objective)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


__all__ = [
    "ToolEffectivenessBlindKey",
    "ToolEffectivenessBlindPacket",
    "ToolEffectivenessCondition",
    "ToolEffectivenessError",
    "ToolEffectivenessFixture",
    "ToolEffectivenessGoldTarget",
    "ToolEffectivenessProtocol",
    "ToolEffectivenessStratum",
    "ToolEffectivenessStudyReport",
    "ToolEffectivenessTask",
    "ToolEffectivenessTrial",
    "build_tool_effectiveness_blind_packet",
    "build_tool_effectiveness_trial",
    "deterministic_v2_router",
    "evaluate_tool_effectiveness_study",
    "execute_read_only_step",
    "load_tool_effectiveness_fixture",
    "score_tool_effectiveness_outcome",
]
