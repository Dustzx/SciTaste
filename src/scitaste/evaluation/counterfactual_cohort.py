"""Cohort-level diagnosis for objective Scientific Taste counterfactuals."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class CounterfactualTrajectoryPhase(StrEnum):
    EARLY = "early"
    MIDDLE = "middle"
    LATE = "late"


class CounterfactualCohortState(BaseModel):
    """One result reduced to the state-level facts used by a cohort analysis."""

    model_config = _CONFIG

    state_id: str
    domain_id: str
    phase: CounterfactualTrajectoryPhase
    result_sha256: str = Field(pattern=_SHA256)
    task_id: str
    environment_sha256: str = Field(pattern=_SHA256)
    prefix_sha256: str = Field(pattern=_SHA256)
    action_count: int = Field(ge=2, le=7)
    objective_observed_count: int = Field(ge=0, le=7)
    objective_failure_count: int = Field(ge=0, le=7)
    preferred_actions: tuple[CounterfactualResearchAction, ...] = Field(min_length=1)
    observed_preferred_actions: tuple[CounterfactualResearchAction, ...] = Field(
        default=()
    )
    objective_spread: float = Field(ge=0.0, allow_inf_nan=False)
    observed_objective_spread: float = Field(ge=0.0, allow_inf_nan=False)
    practical_equivalence_tolerance: float = Field(ge=0.0, allow_inf_nan=False)
    end_to_end_choice_sensitive: bool
    scientific_choice_sensitive: bool
    reliability_only_sensitive: bool

    @model_validator(mode="after")
    def state_is_consistent(self) -> CounterfactualCohortState:
        validate_entry_id(self.state_id, field_name="counterfactual cohort state_id")
        validate_entry_id(self.domain_id, field_name="counterfactual cohort domain_id")
        validate_entry_id(self.task_id, field_name="counterfactual cohort task_id")
        if self.objective_observed_count > self.action_count:
            raise ValueError("counterfactual observed outcomes exceed action count")
        if self.objective_failure_count != self.action_count - self.objective_observed_count:
            raise ValueError("counterfactual failure count does not close")
        expected_end_to_end = self.objective_spread > self.practical_equivalence_tolerance
        expected_scientific = (
            self.observed_objective_spread > self.practical_equivalence_tolerance
        )
        if self.end_to_end_choice_sensitive != expected_end_to_end:
            raise ValueError("counterfactual end-to-end sensitivity differs from the result")
        if self.scientific_choice_sensitive != expected_scientific:
            raise ValueError("counterfactual scientific sensitivity differs from the result")
        if self.reliability_only_sensitive != (
            expected_end_to_end and not expected_scientific and self.objective_failure_count > 0
        ):
            raise ValueError("counterfactual reliability-only sensitivity mismatch")
        if self.preferred_actions != tuple(
            sorted(set(self.preferred_actions), key=lambda item: item.value)
        ):
            raise ValueError("counterfactual preferred actions must be sorted and unique")
        if self.observed_preferred_actions != tuple(
            sorted(set(self.observed_preferred_actions), key=lambda item: item.value)
        ):
            raise ValueError("observed preferred actions must be sorted and unique")
        return self

    @classmethod
    def from_result(
        cls,
        result: CounterfactualActionSetResult,
        *,
        state_id: str,
        domain_id: str,
        phase: CounterfactualTrajectoryPhase,
    ) -> CounterfactualCohortState:
        observed_outcomes = tuple(
            item for item in result.outcomes if item.objective_observed
        )
        observed_utilities = {
            item.action: (
                item.objective_value
                if result.metric_direction == "higher"
                else -item.objective_value
            )
            for item in observed_outcomes
        }
        if observed_utilities:
            observed_best = max(observed_utilities.values())
            observed_preferred = tuple(
                sorted(
                    (
                        action
                        for action, utility in observed_utilities.items()
                        if observed_best - utility
                        <= result.practical_equivalence_tolerance
                    ),
                    key=lambda item: item.value,
                )
            )
            observed_spread = max(observed_utilities.values()) - min(
                observed_utilities.values()
            )
        else:
            observed_preferred = ()
            observed_spread = 0.0
        observed_count = len(observed_outcomes)
        end_to_end_sensitive = (
            result.objective_spread > result.practical_equivalence_tolerance
        )
        scientific_sensitive = (
            observed_spread > result.practical_equivalence_tolerance
        )
        return cls(
            state_id=state_id,
            domain_id=domain_id,
            phase=phase,
            result_sha256=result.result_sha256,
            task_id=result.task_id,
            environment_sha256=result.environment_sha256,
            prefix_sha256=result.prefix_sha256,
            action_count=len(result.outcomes),
            objective_observed_count=observed_count,
            objective_failure_count=len(result.outcomes) - observed_count,
            preferred_actions=result.preferred_actions,
            observed_preferred_actions=observed_preferred,
            objective_spread=result.objective_spread,
            observed_objective_spread=observed_spread,
            practical_equivalence_tolerance=result.practical_equivalence_tolerance,
            end_to_end_choice_sensitive=end_to_end_sensitive,
            scientific_choice_sensitive=scientific_sensitive,
            reliability_only_sensitive=(
                end_to_end_sensitive
                and not scientific_sensitive
                and observed_count < len(result.outcomes)
            ),
        )


class CounterfactualDevelopmentCohortProtocol(BaseModel):
    """Prospective sufficiency requirements for learning, never evidence admission."""

    model_config = _CONFIG

    protocol_id: str
    minimum_state_count: int = Field(ge=2, le=10_000)
    minimum_domain_count: int = Field(ge=1, le=1_000)
    minimum_phase_count: int = Field(ge=1, le=3)
    minimum_objective_observation_rate: float = Field(ge=0.0, le=1.0)
    minimum_choice_sensitive_state_count: int = Field(ge=1, le=10_000)
    require_complete_action_space: bool = True

    @model_validator(mode="after")
    def protocol_is_identified(self) -> CounterfactualDevelopmentCohortProtocol:
        validate_entry_id(self.protocol_id, field_name="counterfactual cohort protocol_id")
        if self.minimum_choice_sensitive_state_count > self.minimum_state_count:
            raise ValueError("choice-sensitive minimum exceeds the minimum state count")
        return self


class CounterfactualPreferredSetFrequency(BaseModel):
    model_config = _CONFIG

    actions: tuple[CounterfactualResearchAction, ...]
    state_count: int = Field(ge=1)


class CounterfactualDevelopmentCohortReport(BaseModel):
    """Determine whether development states can support conditional-policy learning."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cohort_id: str
    project_id: str
    protocol_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    failure_value: float = Field(allow_inf_nan=False)
    states: tuple[CounterfactualCohortState, ...] = Field(min_length=2)
    state_count: int = Field(ge=2)
    domain_count: int = Field(ge=1)
    phase_count: int = Field(ge=1, le=3)
    objective_observation_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    complete_action_state_count: int = Field(ge=0)
    scientific_choice_sensitive_state_count: int = Field(ge=0)
    reliability_only_sensitive_state_count: int = Field(ge=0)
    scientifically_indifferent_state_count: int = Field(ge=0)
    preferred_set_frequencies: tuple[CounterfactualPreferredSetFrequency, ...]
    state_selectivity_observed: bool
    development_requirements_met: bool
    development_only: Literal[True] = True
    headline_eligible: Literal[False] = False
    blockers: tuple[str, ...]
    diagnosis: str
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> CounterfactualDevelopmentCohortReport:
        validate_entry_id(self.cohort_id, field_name="counterfactual cohort_id")
        validate_project_id(self.project_id)
        validate_entry_id(self.protocol_id, field_name="counterfactual cohort protocol_id")
        if self.state_count != len(self.states):
            raise ValueError("counterfactual cohort state count mismatch")
        if (
            self.scientific_choice_sensitive_state_count
            + self.scientifically_indifferent_state_count
            != self.state_count
        ):
            raise ValueError("counterfactual scientific sensitivity counts do not close")
        if (
            self.reliability_only_sensitive_state_count
            > self.scientifically_indifferent_state_count
        ):
            raise ValueError("reliability-only count exceeds scientifically indifferent states")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("counterfactual cohort report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualDevelopmentCohortReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def summarize_counterfactual_development_cohort(
    *,
    cohort_id: str,
    project_id: str,
    protocol: CounterfactualDevelopmentCohortProtocol,
    results: tuple[CounterfactualActionSetResult, ...],
    state_ids: tuple[str, ...],
    domain_ids: tuple[str, ...],
    phases: tuple[CounterfactualTrajectoryPhase, ...],
) -> CounterfactualDevelopmentCohortReport:
    """Aggregate heterogeneous development states without admitting paper evidence."""

    if not (len(results) == len(state_ids) == len(domain_ids) == len(phases)):
        raise ValueError("counterfactual cohort result metadata must align")
    if len(results) < 2:
        raise ValueError("counterfactual cohort requires at least two states")
    if any(result.project_id != project_id for result in results):
        raise ValueError("counterfactual cohort results target another project")
    metric_contracts = {
        (result.primary_metric, result.metric_direction, result.failure_value)
        for result in results
    }
    if len(metric_contracts) != 1:
        raise ValueError("counterfactual cohort results use different metric contracts")
    identities = {(result.environment_sha256, result.prefix_sha256) for result in results}
    if len(identities) != len(results):
        raise ValueError("counterfactual cohort repeats a research state")

    states = tuple(
        sorted(
            (
                CounterfactualCohortState.from_result(
                    result,
                    state_id=state_id,
                    domain_id=domain_id,
                    phase=phase,
                )
                for result, state_id, domain_id, phase in zip(
                    results, state_ids, domain_ids, phases, strict=True
                )
            ),
            key=lambda item: item.state_id,
        )
    )
    action_total = sum(item.action_count for item in states)
    observed_total = sum(item.objective_observed_count for item in states)
    observation_rate = observed_total / action_total
    full_action_count = sum(
        item.action_count == len(CounterfactualResearchAction) for item in states
    )
    sensitive_count = sum(item.scientific_choice_sensitive for item in states)
    reliability_only_count = sum(item.reliability_only_sensitive for item in states)
    frequencies: dict[tuple[CounterfactualResearchAction, ...], int] = {}
    for state in states:
        frequencies[state.observed_preferred_actions] = (
            frequencies.get(state.observed_preferred_actions, 0) + 1
        )
    preferred_frequencies = tuple(
        CounterfactualPreferredSetFrequency(actions=actions, state_count=count)
        for actions, count in sorted(
            frequencies.items(),
            key=lambda item: tuple(action.value for action in item[0]),
        )
    )
    blockers: list[str] = []
    domains = {item.domain_id for item in states}
    phase_values = {item.phase for item in states}
    if len(states) < protocol.minimum_state_count:
        blockers.append("insufficient-development-states")
    if len(domains) < protocol.minimum_domain_count:
        blockers.append("insufficient-development-domains")
    if len(phase_values) < protocol.minimum_phase_count:
        blockers.append("insufficient-trajectory-phase-coverage")
    if observation_rate < protocol.minimum_objective_observation_rate:
        blockers.append("insufficient-objective-metric-coverage")
    if sensitive_count < protocol.minimum_choice_sensitive_state_count:
        blockers.append("insufficient-choice-sensitive-states")
    if protocol.require_complete_action_space and full_action_count != len(states):
        blockers.append("incomplete-action-space")
    state_selectivity = len(frequencies) > 1 and () not in frequencies
    if not state_selectivity:
        blockers.append("no-state-varying-preference")
    requirements_met = not blockers
    diagnosis = (
        f"Observed {sensitive_count} scientifically choice-sensitive, "
        f"{len(states) - sensitive_count} scientifically indifferent, and "
        f"{reliability_only_count} reliability-only-sensitive development states across "
        f"{len(domains)} domains and {len(phase_values)} trajectory phases. "
        + (
            "The cohort is sufficient to fit a frozen development policy; it remains "
            "ineligible as paper evidence until evaluated on an isolated confirmation split."
            if requirements_met
            else "The cohort is not yet sufficient to fit a defensible conditional policy."
        )
    )
    primary_metric, metric_direction, failure_value = next(iter(metric_contracts))
    return CounterfactualDevelopmentCohortReport.create(
        cohort_id=cohort_id,
        project_id=project_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=content_sha256(protocol.model_dump(mode="json")),
        primary_metric=primary_metric,
        metric_direction=metric_direction,
        failure_value=failure_value,
        states=states,
        state_count=len(states),
        domain_count=len(domains),
        phase_count=len(phase_values),
        objective_observation_rate=observation_rate,
        complete_action_state_count=full_action_count,
        scientific_choice_sensitive_state_count=sensitive_count,
        reliability_only_sensitive_state_count=reliability_only_count,
        scientifically_indifferent_state_count=len(states) - sensitive_count,
        preferred_set_frequencies=preferred_frequencies,
        state_selectivity_observed=state_selectivity,
        development_requirements_met=requirements_met,
        development_only=True,
        headline_eligible=False,
        blockers=tuple(blockers),
        diagnosis=diagnosis,
    )


def save_counterfactual_development_cohort_report(
    report: CounterfactualDevelopmentCohortReport,
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
    "CounterfactualCohortState",
    "CounterfactualDevelopmentCohortProtocol",
    "CounterfactualDevelopmentCohortReport",
    "CounterfactualPreferredSetFrequency",
    "CounterfactualTrajectoryPhase",
    "save_counterfactual_development_cohort_report",
    "summarize_counterfactual_development_cohort",
]
