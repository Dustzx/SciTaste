"""Confirm a frozen Scientific Taste policy on disjoint action branches."""

from __future__ import annotations

import itertools
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.counterfactual_policy import CounterfactualTastePolicy
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.interactive_research import InteractiveResearchPrefix
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_STATIC_BASELINES = (
    CounterfactualResearchAction.PROBE,
    CounterfactualResearchAction.EXPERIMENT,
    CounterfactualResearchAction.STOP,
)


class CounterfactualConfirmationState(BaseModel):
    """One prospective policy decision and all matched potential outcomes."""

    model_config = _CONFIG

    study_id: str
    task_id: str
    task_cluster_id: str
    prefix_turn_count: int = Field(ge=1)
    evidence_status: str
    prefix_sha256: str = Field(pattern=_SHA256)
    result_sha256: str = Field(pattern=_SHA256)
    policy_action: CounterfactualResearchAction
    policy_value: float = Field(allow_inf_nan=False)
    policy_objective_observed: bool
    baseline_values: dict[CounterfactualResearchAction, float]
    baseline_objective_observed: dict[CounterfactualResearchAction, bool]
    oracle_action: CounterfactualResearchAction
    oracle_value: float = Field(allow_inf_nan=False)
    oracle_regret: float = Field(ge=0.0, allow_inf_nan=False)


class CounterfactualConfirmationContrast(BaseModel):
    """Paired policy contrast with uncertainty clustered by independent task."""

    model_config = _CONFIG

    baseline_action: CounterfactualResearchAction
    state_count: int = Field(ge=1)
    task_cluster_count: int = Field(ge=1)
    policy_mean: float = Field(allow_inf_nan=False)
    baseline_mean: float = Field(allow_inf_nan=False)
    paired_mean_difference: float = Field(allow_inf_nan=False)
    task_cluster_mean_differences: dict[str, float]
    exhaustive_task_cluster_bootstrap_95_interval: tuple[float, float]
    bootstrap_enumeration_count: int = Field(ge=1)
    practical_wins: int = Field(ge=0)
    practical_losses: int = Field(ge=0)
    practical_ties: int = Field(ge=0)
    exact_two_sided_sign_p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    policy_failure_rate: float = Field(ge=0.0, le=1.0)
    baseline_failure_rate: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def counts_are_closed(self) -> CounterfactualConfirmationContrast:
        if self.practical_wins + self.practical_losses + self.practical_ties != self.state_count:
            raise ValueError("confirmation win/loss/tie counts differ from state count")
        if len(self.task_cluster_mean_differences) != self.task_cluster_count:
            raise ValueError("confirmation task-cluster effects differ from cluster count")
        return self


class CounterfactualConfirmationReport(BaseModel):
    """A claim-bounded report for a frozen, disjoint confirmation population."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_id: str
    project_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    policy_sha256: str = Field(pattern=_SHA256)
    training_population_sha256: str = Field(pattern=_SHA256)
    primary_metric: str
    source_metric: str
    metric_transform: Literal["exp-negative"]
    practical_equivalence_tolerance: float = Field(ge=0.0, allow_inf_nan=False)
    state_count: int = Field(ge=1)
    task_cluster_count: int = Field(ge=1)
    action_count_per_state: int = Field(ge=2, le=7)
    objective_observation_rate: float = Field(ge=0.0, le=1.0)
    policy_action_counts: dict[CounterfactualResearchAction, int]
    mean_policy_value: float = Field(allow_inf_nan=False)
    mean_oracle_value: float = Field(allow_inf_nan=False)
    mean_oracle_regret: float = Field(ge=0.0, allow_inf_nan=False)
    branch_input_tokens: int = Field(ge=0)
    branch_output_tokens: int = Field(ge=0)
    known_branch_api_cost_usd: float = Field(ge=0.0, allow_inf_nan=False)
    unknown_branch_cost_count: int = Field(ge=0)
    states: tuple[CounterfactualConfirmationState, ...] = Field(min_length=1)
    contrasts: tuple[CounterfactualConfirmationContrast, ...] = Field(min_length=3)
    confirmation_population_valid: bool
    verdict: Literal["supported", "not-supported", "inadmissible"]
    verdict_reasons: tuple[str, ...] = Field(min_length=1)
    headline_eligible: Literal[False] = False
    venue_ready: Literal[False] = False
    policy_update_allowed_from_confirmation_split: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> CounterfactualConfirmationReport:
        validate_entry_id(self.report_id, field_name="counterfactual confirmation report_id")
        validate_project_id(self.project_id)
        if self.state_count != len(self.states):
            raise ValueError("confirmation state count mismatch")
        if self.task_cluster_count != len({item.task_cluster_id for item in self.states}):
            raise ValueError("confirmation task-cluster count mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("counterfactual confirmation report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualConfirmationReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def analyze_counterfactual_confirmation(
    *,
    report_id: str,
    protocol_sha256: str,
    policy: CounterfactualTastePolicy,
    population: tuple[tuple[CounterfactualActionSetResult, InteractiveResearchPrefix], ...],
    expected_state_count: int,
    expected_task_cluster_count: int,
    minimum_objective_observation_rate: float,
) -> CounterfactualConfirmationReport:
    """Evaluate a frozen policy without refitting it on the confirmation split."""

    if len(population) != expected_state_count:
        raise ValueError("confirmation population differs from frozen state count")
    if not 0.0 <= minimum_objective_observation_rate <= 1.0:
        raise ValueError("minimum objective observation rate must be within [0, 1]")

    states: list[CounterfactualConfirmationState] = []
    all_outcomes = []
    input_tokens = 0
    output_tokens = 0
    known_cost = 0.0
    unknown_cost = 0
    seen_prefixes: set[str] = set()
    turns_by_task: dict[str, set[int]] = defaultdict(set)
    contracts: set[tuple[object, ...]] = set()

    for result, prefix in population:
        if result.project_id != policy.project_id or prefix.project_id != policy.project_id:
            raise ValueError("confirmation state targets another project")
        if result.prefix_sha256 != prefix.prefix_sha256 or result.task_id != prefix.task_id:
            raise ValueError("confirmation result and prefix differ")
        if result.result_sha256 in policy.source_result_sha256s:
            raise ValueError("confirmation population overlaps policy development results")
        if result.prefix_sha256 in seen_prefixes:
            raise ValueError("confirmation population repeats a prefix")
        seen_prefixes.add(result.prefix_sha256)
        turns_by_task[result.task_id].add(prefix.turn_count)
        actions = {item.action: item for item in result.outcomes}
        if set(actions) != set(CounterfactualResearchAction):
            raise ValueError("confirmation state does not contain the complete action space")
        contracts.add(
            (
                result.primary_metric,
                result.source_metric,
                result.metric_transform,
                result.metric_direction,
                result.failure_value,
                result.practical_equivalence_tolerance,
            )
        )
        if result.metric_direction != "higher":
            raise ValueError("confirmation analysis currently requires higher-is-better utility")
        if policy.primary_metric not in {result.primary_metric, result.source_metric}:
            raise ValueError("confirmation endpoint is not monotonic with policy endpoint")

        evidence_status = prefix.turns[-1].decision.proposal.evidence_status
        policy_action = policy.action_for(evidence_status)
        selected = actions[policy_action]
        oracle = max(result.outcomes, key=lambda item: (item.objective_value, item.action.value))
        baseline_values = {action: actions[action].objective_value for action in _STATIC_BASELINES}
        baseline_observed = {
            action: actions[action].objective_observed for action in _STATIC_BASELINES
        }
        states.append(
            CounterfactualConfirmationState(
                study_id=result.study_id,
                task_id=result.task_id,
                task_cluster_id=result.task_id,
                prefix_turn_count=prefix.turn_count,
                evidence_status=evidence_status,
                prefix_sha256=prefix.prefix_sha256,
                result_sha256=result.result_sha256,
                policy_action=policy_action,
                policy_value=selected.objective_value,
                policy_objective_observed=selected.objective_observed,
                baseline_values=baseline_values,
                baseline_objective_observed=baseline_observed,
                oracle_action=oracle.action,
                oracle_value=oracle.objective_value,
                oracle_regret=oracle.objective_value - selected.objective_value,
            )
        )
        for outcome in result.outcomes:
            all_outcomes.append(outcome)
            input_tokens += outcome.branch_input_tokens
            output_tokens += outcome.branch_output_tokens
            if outcome.branch_api_cost_usd is None:
                unknown_cost += 1
            else:
                known_cost += outcome.branch_api_cost_usd

    if len(contracts) != 1:
        raise ValueError("confirmation population uses different metric contracts")
    if len(turns_by_task) != expected_task_cluster_count:
        raise ValueError("confirmation population differs from frozen task count")
    expected_turns = set(range(1, expected_state_count // expected_task_cluster_count + 1))
    if any(turns != expected_turns for turns in turns_by_task.values()):
        raise ValueError("confirmation tasks do not share the frozen prefix phases")

    states.sort(key=lambda item: (item.task_id, item.prefix_turn_count))
    metric, source_metric, transform, _direction, _failure, tolerance = contracts.pop()
    contrasts = tuple(_contrast(states, action, float(tolerance)) for action in _STATIC_BASELINES)
    observation_rate = sum(item.objective_observed for item in all_outcomes) / len(all_outcomes)
    population_valid = observation_rate >= minimum_objective_observation_rate
    primary = contrasts[0]
    strongest_static = max(contrasts, key=lambda item: item.baseline_mean)
    primary_low, _primary_high = primary.exhaustive_task_cluster_bootstrap_95_interval
    supported = (
        population_valid
        and primary_low > 0.0
        and primary.paired_mean_difference > tolerance
        and all(item.paired_mean_difference >= -tolerance for item in contrasts)
    )
    if not population_valid:
        verdict: Literal["supported", "not-supported", "inadmissible"] = "inadmissible"
        reasons = (
            "objective-observation-rate-below-frozen-admission-threshold",
        )
    elif supported:
        verdict = "supported"
        reasons = ("frozen-policy-outperforms-preselected-baseline-with-clustered-uncertainty",)
    else:
        verdict = "not-supported"
        reasons_list = []
        if primary_low <= 0.0:
            reasons_list.append("primary-task-cluster-interval-includes-nonpositive-effects")
        if primary.practical_wins <= primary.practical_losses:
            reasons_list.append("primary-practical-wins-do-not-exceed-losses")
        if strongest_static.paired_mean_difference < -tolerance:
            reasons_list.append(
                f"static-{strongest_static.baseline_action.value.casefold()}-has-higher-mean"
            )
        reasons = tuple(reasons_list or ["frozen-confirmatory-success-rule-not-met"])

    action_counts = Counter(item.policy_action for item in states)
    return CounterfactualConfirmationReport.create(
        report_id=report_id,
        project_id=policy.project_id,
        protocol_sha256=protocol_sha256,
        policy_sha256=policy.policy_sha256,
        training_population_sha256=policy.training_population_sha256,
        primary_metric=str(metric),
        source_metric=str(source_metric),
        metric_transform=transform,
        practical_equivalence_tolerance=float(tolerance),
        state_count=len(states),
        task_cluster_count=len(turns_by_task),
        action_count_per_state=len(CounterfactualResearchAction),
        objective_observation_rate=observation_rate,
        policy_action_counts=dict(sorted(action_counts.items(), key=lambda item: item[0].value)),
        mean_policy_value=math.fsum(item.policy_value for item in states) / len(states),
        mean_oracle_value=math.fsum(item.oracle_value for item in states) / len(states),
        mean_oracle_regret=math.fsum(item.oracle_regret for item in states) / len(states),
        branch_input_tokens=input_tokens,
        branch_output_tokens=output_tokens,
        known_branch_api_cost_usd=known_cost,
        unknown_branch_cost_count=unknown_cost,
        states=tuple(states),
        contrasts=contrasts,
        confirmation_population_valid=population_valid,
        verdict=verdict,
        verdict_reasons=reasons,
        headline_eligible=False,
        venue_ready=False,
        policy_update_allowed_from_confirmation_split=False,
    )


def _contrast(
    states: list[CounterfactualConfirmationState],
    baseline_action: CounterfactualResearchAction,
    tolerance: float,
) -> CounterfactualConfirmationContrast:
    effects = [item.policy_value - item.baseline_values[baseline_action] for item in states]
    clustered: dict[str, list[float]] = defaultdict(list)
    for state, effect in zip(states, effects, strict=True):
        clustered[state.task_cluster_id].append(effect)
    cluster_effects = {
        task: math.fsum(values) / len(values) for task, values in sorted(clustered.items())
    }
    interval, enumeration_count = _exhaustive_cluster_bootstrap(tuple(cluster_effects.values()))
    wins = sum(effect > tolerance for effect in effects)
    losses = sum(effect < -tolerance for effect in effects)
    ties = len(effects) - wins - losses
    policy_failures = sum(not item.policy_objective_observed for item in states)
    baseline_failures = sum(
        not item.baseline_objective_observed[baseline_action] for item in states
    )
    return CounterfactualConfirmationContrast(
        baseline_action=baseline_action,
        state_count=len(states),
        task_cluster_count=len(cluster_effects),
        policy_mean=math.fsum(item.policy_value for item in states) / len(states),
        baseline_mean=(
            math.fsum(item.baseline_values[baseline_action] for item in states) / len(states)
        ),
        paired_mean_difference=math.fsum(effects) / len(effects),
        task_cluster_mean_differences=cluster_effects,
        exhaustive_task_cluster_bootstrap_95_interval=interval,
        bootstrap_enumeration_count=enumeration_count,
        practical_wins=wins,
        practical_losses=losses,
        practical_ties=ties,
        exact_two_sided_sign_p_value=_exact_two_sided_sign_test(wins, losses),
        policy_failure_rate=policy_failures / len(states),
        baseline_failure_rate=baseline_failures / len(states),
    )


def _exhaustive_cluster_bootstrap(
    cluster_effects: tuple[float, ...],
) -> tuple[tuple[float, float], int]:
    if not cluster_effects:
        raise ValueError("cluster bootstrap requires at least one task")
    count = len(cluster_effects)
    estimates = sorted(
        math.fsum(sample) / count
        for sample in itertools.product(cluster_effects, repeat=count)
    )
    low = estimates[int(0.025 * (len(estimates) - 1))]
    high = estimates[math.ceil(0.975 * (len(estimates) - 1))]
    return (low, high), len(estimates)


def _exact_two_sided_sign_test(wins: int, losses: int) -> float | None:
    discordant = wins + losses
    if discordant == 0:
        return None
    tail = sum(math.comb(discordant, index) for index in range(min(wins, losses) + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


def save_counterfactual_confirmation_report(
    report: CounterfactualConfirmationReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((report.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


__all__ = [
    "CounterfactualConfirmationContrast",
    "CounterfactualConfirmationReport",
    "CounterfactualConfirmationState",
    "analyze_counterfactual_confirmation",
    "save_counterfactual_confirmation_report",
]
