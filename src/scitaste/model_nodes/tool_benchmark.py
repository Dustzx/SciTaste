"""Paired engineering metrics for Tool Intelligence v2 and v3 trials."""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.model_nodes.tool_intelligence import canonical_sha256


class ToolBenchmarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolBenchmarkCondition(StrEnum):
    V2 = "v2-process-local"
    V3 = "v3-durable-project-loop"


class ToolBenchmarkTrial(ToolBenchmarkModel):
    """One measured condition/scenario observation with explicit applicability."""

    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    condition: ToolBenchmarkCondition
    evidence_test: str = Field(min_length=1)
    hotspot_resolved: bool
    manual_controller_steps: int = Field(ge=0)
    model_invocations: int = Field(ge=0)
    tool_handler_invocations: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(default=0, ge=0)
    model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    runtime_ms: float = Field(ge=0, allow_inf_nan=False)
    restart_duplicate_execution_count: int | None = Field(default=None, ge=0)
    crash_recovery_success: bool | None = None
    ambiguous_call_failed_closed: bool | None = None
    stale_or_concurrent_result_accepted: bool | None = None
    locator_attack_rejected: bool | None = None


class ToolBenchmarkConditionMetrics(ToolBenchmarkModel):
    condition: ToolBenchmarkCondition
    trial_count: int = Field(ge=1)
    successful_hotspot_resolution_rate: float = Field(ge=0, le=1)
    manual_controller_steps_per_resolved_hotspot: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    restart_duplicate_execution_rate: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    crash_recovery_success_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    ambiguous_call_fail_closed_rate: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    stale_or_concurrent_result_acceptance_rate: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    locator_attack_rejection_rate: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    model_invocations: int = Field(ge=0)
    tool_handler_invocations: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    unknown_cost_count: int = Field(ge=0)
    model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    mean_runtime_ms: float = Field(ge=0, allow_inf_nan=False)


class ToolBenchmarkDelta(ToolBenchmarkModel):
    """Positive reliability/reduction values favor v3; runtime delta is signed cost."""

    restart_duplicate_execution_rate_reduction: float | None = None
    crash_recovery_success_rate_gain: float | None = None
    ambiguous_call_fail_closed_rate_gain: float | None = None
    stale_result_acceptance_rate_reduction: float | None = None
    locator_attack_rejection_rate_gain: float | None = None
    manual_controller_step_reduction_rate: float | None = None
    hotspot_resolution_rate_gain: float
    model_invocation_reduction_rate: float | None = None
    tool_invocation_reduction_rate: float | None = None
    token_reduction_rate: float | None = None
    known_cost_reduction_rate: float | None = None
    mean_runtime_overhead_ms: float


class ToolIntelligenceBenchmarkReport(ToolBenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    scenario_ids: tuple[str, ...] = Field(min_length=1)
    v2: ToolBenchmarkConditionMetrics
    v3: ToolBenchmarkConditionMetrics
    delta: ToolBenchmarkDelta
    engineering_proxy_only: Literal[True] = True
    scientific_effectiveness_claim: Literal[False] = False

    @model_validator(mode="after")
    def conditions_are_fixed(self) -> ToolIntelligenceBenchmarkReport:
        if self.v2.condition is not ToolBenchmarkCondition.V2 or (
            self.v3.condition is not ToolBenchmarkCondition.V3
        ):
            raise ValueError("benchmark report condition identities drift")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


def evaluate_tool_intelligence_benchmark(
    trials: tuple[ToolBenchmarkTrial, ...],
    *,
    protocol_id: str = "tool-intelligence-v2-v3-paired-v1",
) -> ToolIntelligenceBenchmarkReport:
    """Evaluate exact matched scenarios without inventing missing denominators."""

    validated = tuple(
        ToolBenchmarkTrial.model_validate_json(
            trial.model_dump_json(exclude_computed_fields=True), strict=True
        )
        for trial in trials
    )
    if not validated:
        raise ValueError("Tool Intelligence benchmark requires trials")
    grouped = {
        condition: tuple(trial for trial in validated if trial.condition is condition)
        for condition in ToolBenchmarkCondition
    }
    scenario_sets = {
        condition: {trial.scenario_id for trial in values} for condition, values in grouped.items()
    }
    if not all(grouped.values()) or len(set(map(frozenset, scenario_sets.values()))) != 1:
        raise ValueError("Tool Intelligence benchmark scenarios must be exactly paired")
    for values in grouped.values():
        ids = [trial.scenario_id for trial in values]
        if len(ids) != len(set(ids)):
            raise ValueError("Tool Intelligence benchmark contains a duplicate condition trial")
    v2 = _condition_metrics(ToolBenchmarkCondition.V2, grouped[ToolBenchmarkCondition.V2])
    v3 = _condition_metrics(ToolBenchmarkCondition.V3, grouped[ToolBenchmarkCondition.V3])
    return ToolIntelligenceBenchmarkReport(
        protocol_id=protocol_id,
        scenario_ids=tuple(sorted(scenario_sets[ToolBenchmarkCondition.V2])),
        v2=v2,
        v3=v3,
        delta=ToolBenchmarkDelta(
            restart_duplicate_execution_rate_reduction=_difference(
                v2.restart_duplicate_execution_rate,
                v3.restart_duplicate_execution_rate,
            ),
            crash_recovery_success_rate_gain=_difference(
                v3.crash_recovery_success_rate,
                v2.crash_recovery_success_rate,
            ),
            ambiguous_call_fail_closed_rate_gain=_difference(
                v3.ambiguous_call_fail_closed_rate,
                v2.ambiguous_call_fail_closed_rate,
            ),
            stale_result_acceptance_rate_reduction=_difference(
                v2.stale_or_concurrent_result_acceptance_rate,
                v3.stale_or_concurrent_result_acceptance_rate,
            ),
            locator_attack_rejection_rate_gain=_difference(
                v3.locator_attack_rejection_rate,
                v2.locator_attack_rejection_rate,
            ),
            manual_controller_step_reduction_rate=_reduction(
                v2.manual_controller_steps_per_resolved_hotspot,
                v3.manual_controller_steps_per_resolved_hotspot,
            ),
            hotspot_resolution_rate_gain=(
                v3.successful_hotspot_resolution_rate - v2.successful_hotspot_resolution_rate
            ),
            model_invocation_reduction_rate=_reduction(
                float(v2.model_invocations), float(v3.model_invocations)
            ),
            tool_invocation_reduction_rate=_reduction(
                float(v2.tool_handler_invocations),
                float(v3.tool_handler_invocations),
            ),
            token_reduction_rate=_reduction(
                float(v2.input_tokens + v2.output_tokens),
                float(v3.input_tokens + v3.output_tokens),
            ),
            known_cost_reduction_rate=_reduction(v2.known_cost_usd, v3.known_cost_usd),
            mean_runtime_overhead_ms=v3.mean_runtime_ms - v2.mean_runtime_ms,
        ),
    )


def _condition_metrics(
    condition: ToolBenchmarkCondition,
    trials: tuple[ToolBenchmarkTrial, ...],
) -> ToolBenchmarkConditionMetrics:
    resolved = tuple(trial for trial in trials if trial.hotspot_resolved)
    return ToolBenchmarkConditionMetrics(
        condition=condition,
        trial_count=len(trials),
        successful_hotspot_resolution_rate=len(resolved) / len(trials),
        manual_controller_steps_per_resolved_hotspot=(
            sum(trial.manual_controller_steps for trial in resolved) / len(resolved)
            if resolved
            else None
        ),
        restart_duplicate_execution_rate=_optional_mean(
            trial.restart_duplicate_execution_count for trial in trials
        ),
        crash_recovery_success_rate=_optional_boolean_rate(
            trial.crash_recovery_success for trial in trials
        ),
        ambiguous_call_fail_closed_rate=_optional_boolean_rate(
            trial.ambiguous_call_failed_closed for trial in trials
        ),
        stale_or_concurrent_result_acceptance_rate=_optional_boolean_rate(
            trial.stale_or_concurrent_result_accepted for trial in trials
        ),
        locator_attack_rejection_rate=_optional_boolean_rate(
            trial.locator_attack_rejected for trial in trials
        ),
        model_invocations=sum(trial.model_invocations for trial in trials),
        tool_handler_invocations=sum(trial.tool_handler_invocations for trial in trials),
        input_tokens=sum(trial.input_tokens for trial in trials),
        output_tokens=sum(trial.output_tokens for trial in trials),
        known_cost_usd=sum(trial.known_cost_usd for trial in trials),
        unknown_cost_count=sum(trial.unknown_cost_count for trial in trials),
        model_latency_ms=sum(trial.model_latency_ms for trial in trials),
        tool_latency_ms=sum(trial.tool_latency_ms for trial in trials),
        mean_runtime_ms=statistics.fmean(trial.runtime_ms for trial in trials),
    )


def _optional_mean(values: Iterable[int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return statistics.fmean(present) if present else None


def _optional_boolean_rate(values: Iterable[bool | None]) -> float | None:
    present = [bool(value) for value in values if value is not None]
    return statistics.fmean(present) if present else None


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _reduction(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline == 0:
        return None
    return (baseline - candidate) / baseline


__all__ = [
    "ToolBenchmarkCondition",
    "ToolBenchmarkConditionMetrics",
    "ToolBenchmarkDelta",
    "ToolBenchmarkTrial",
    "ToolIntelligenceBenchmarkReport",
    "evaluate_tool_intelligence_benchmark",
]
