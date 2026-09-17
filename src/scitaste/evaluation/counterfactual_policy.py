"""Fit a frozen, outcome-calibrated Taste policy from development branches."""

from __future__ import annotations

import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchPrefix,
    InteractiveResearchRunReceipt,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_EVIDENCE_STATUS = Literal[
    "unassessed",
    "no-candidate",
    "candidate-untested",
    "candidate-supported",
    "candidate-conflicted",
]


class CounterfactualPolicyActionEstimate(BaseModel):
    model_config = _CONFIG

    action: CounterfactualResearchAction
    state_count: int = Field(ge=1)
    mean_objective_value: float = Field(allow_inf_nan=False)
    maximum_state_regret: float = Field(ge=0.0, allow_inf_nan=False)
    terminal_failure_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    mean_branch_experiment_count: float = Field(ge=0.0, allow_inf_nan=False)
    mean_branch_tokens: float = Field(ge=0.0, allow_inf_nan=False)
    robustly_equivalent_to_state_best: bool


class CounterfactualTasteRule(BaseModel):
    model_config = _CONFIG

    evidence_status: _EVIDENCE_STATUS
    source_study_ids: tuple[str, ...] = Field(min_length=1)
    action_estimates: tuple[CounterfactualPolicyActionEstimate, ...] = Field(
        min_length=2,
        max_length=7,
    )
    robust_action_set: tuple[CounterfactualResearchAction, ...] = Field(min_length=1)
    selected_action: CounterfactualResearchAction
    selection_principle: Literal[
        "minimize-failure-then-experiments-then-objective-within-robust-set"
    ] = "minimize-failure-then-experiments-then-objective-within-robust-set"

    @model_validator(mode="after")
    def rule_is_closed(self) -> CounterfactualTasteRule:
        if self.source_study_ids != tuple(sorted(set(self.source_study_ids))):
            raise ValueError("counterfactual policy source studies must be sorted and unique")
        actions = tuple(item.action for item in self.action_estimates)
        if actions != tuple(sorted(set(actions), key=lambda item: item.value)):
            raise ValueError("counterfactual policy action estimates must be sorted and unique")
        robust = tuple(
            item.action for item in self.action_estimates if item.robustly_equivalent_to_state_best
        )
        if self.robust_action_set != robust:
            raise ValueError("counterfactual policy robust action set mismatch")
        if self.selected_action not in self.robust_action_set:
            raise ValueError("counterfactual policy selected action is not robust")
        return self


class CounterfactualTastePolicy(BaseModel):
    """Development-frozen policy awaiting evaluation on disjoint states."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str
    project_id: str
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    training_population_sha256: str = Field(pattern=_SHA256)
    source_result_sha256s: tuple[str, ...] = Field(min_length=2)
    rules: tuple[CounterfactualTasteRule, ...] = Field(min_length=1)
    fallback_action: CounterfactualResearchAction
    fallback_reason: str
    development_only: Literal[True] = True
    frozen_before_confirmation: Literal[True] = True
    confirmation_evaluated: Literal[False] = False
    headline_eligible: Literal[False] = False
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> CounterfactualTastePolicy:
        validate_entry_id(self.policy_id, field_name="counterfactual Taste policy_id")
        validate_project_id(self.project_id)
        if self.source_result_sha256s != tuple(sorted(set(self.source_result_sha256s))):
            raise ValueError("counterfactual policy source results must be sorted and unique")
        statuses = tuple(item.evidence_status for item in self.rules)
        if statuses != tuple(sorted(set(statuses))):
            raise ValueError("counterfactual policy rules must be sorted and unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("counterfactual Taste policy hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualTastePolicy:
        payload = {"schema_version": "1.0", **values}
        payload.pop("policy_sha256", None)
        unsigned = cls.model_construct(policy_sha256="0" * 64, **payload)
        return cls(
            **payload,
            policy_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"policy_sha256"})
            ),
        )

    def action_for(self, evidence_status: str) -> CounterfactualResearchAction:
        rule = next(
            (item for item in self.rules if item.evidence_status == evidence_status),
            None,
        )
        return self.fallback_action if rule is None else rule.selected_action


def fit_counterfactual_taste_policy(
    *,
    policy_id: str,
    project_id: str,
    results: tuple[CounterfactualActionSetResult, ...],
    prefixes: tuple[InteractiveResearchPrefix, ...],
    branch_receipts: tuple[tuple[InteractiveResearchRunReceipt, ...], ...],
    fallback_action: CounterfactualResearchAction = CounterfactualResearchAction.PROBE,
) -> CounterfactualTastePolicy:
    """Fit robust rules from objective outcomes; never inspect confirmation states."""

    if not (len(results) == len(prefixes) == len(branch_receipts)) or len(results) < 2:
        raise ValueError(
            "counterfactual policy training inputs must align across two or more states"
        )
    contracts = {
        (item.primary_metric, item.metric_direction, item.failure_value) for item in results
    }
    if len(contracts) != 1:
        raise ValueError("counterfactual policy results use different metric contracts")
    groups: dict[str, list[int]] = defaultdict(list)
    population_bindings = []
    for index, (result, prefix, receipts) in enumerate(
        zip(results, prefixes, branch_receipts, strict=True)
    ):
        if result.project_id != project_id or prefix.project_id != project_id:
            raise ValueError("counterfactual policy input targets another project")
        if result.prefix_sha256 != prefix.prefix_sha256:
            raise ValueError("counterfactual policy result and prefix differ")
        receipt_hashes = {item.receipt_sha256 for item in receipts}
        outcome_hashes = {item.receipt_sha256 for item in result.outcomes}
        if receipt_hashes != outcome_hashes:
            raise ValueError("counterfactual policy branch receipts differ from result outcomes")
        status = prefix.turns[-1].decision.proposal.evidence_status
        groups[status].append(index)
        population_bindings.append(
            {
                "study_id": result.study_id,
                "result_sha256": result.result_sha256,
                "prefix_sha256": prefix.prefix_sha256,
                "receipt_sha256s": sorted(receipt_hashes),
                "evidence_status": status,
            }
        )

    rules = tuple(
        _fit_status_rule(status, indices, results, prefixes, branch_receipts)
        for status, indices in sorted(groups.items())
    )
    primary_metric, metric_direction, _ = next(iter(contracts))
    return CounterfactualTastePolicy.create(
        policy_id=policy_id,
        project_id=project_id,
        primary_metric=primary_metric,
        metric_direction=metric_direction,
        training_population_sha256=content_sha256(population_bindings),
        source_result_sha256s=tuple(sorted(item.result_sha256 for item in results)),
        rules=rules,
        fallback_action=fallback_action,
        fallback_reason=(
            "Unseen evidence states retain diagnostic exploration; the development policy "
            "does not extrapolate an unsupported action preference."
        ),
        development_only=True,
        frozen_before_confirmation=True,
        confirmation_evaluated=False,
        headline_eligible=False,
    )


def _fit_status_rule(
    status: str,
    indices: list[int],
    results: tuple[CounterfactualActionSetResult, ...],
    prefixes: tuple[InteractiveResearchPrefix, ...],
    branch_receipts: tuple[tuple[InteractiveResearchRunReceipt, ...], ...],
) -> CounterfactualTasteRule:
    action_rows: dict[
        CounterfactualResearchAction,
        list[tuple[float, float, int, int, int]],
    ] = defaultdict(list)
    tolerances: list[float] = []
    for index in indices:
        result = results[index]
        prefix = prefixes[index]
        receipts = {item.receipt_sha256: item for item in branch_receipts[index]}
        utilities = {
            item.action: (
                item.objective_value
                if result.metric_direction == "higher"
                else -item.objective_value
            )
            for item in result.outcomes
        }
        best = max(utilities.values())
        tolerances.append(result.practical_equivalence_tolerance)
        for outcome in result.outcomes:
            receipt = receipts[outcome.receipt_sha256]
            branch_experiments = receipt.experiment_count - prefix.experiment_count
            branch_tokens = (
                receipt.input_tokens
                + receipt.output_tokens
                - prefix.input_tokens
                - prefix.output_tokens
            )
            action_rows[outcome.action].append(
                (
                    outcome.objective_value,
                    best - utilities[outcome.action],
                    int(not outcome.objective_observed),
                    branch_experiments,
                    branch_tokens,
                )
            )
    estimates = []
    for action, rows in sorted(action_rows.items(), key=lambda item: item[0].value):
        objectives = [item[0] for item in rows]
        regrets = [item[1] for item in rows]
        failure_rate = math.fsum(item[2] for item in rows) / len(rows)
        experiments = [item[3] for item in rows]
        tokens = [item[4] for item in rows]
        robust = all(
            regret <= tolerance
            for regret, tolerance in zip(regrets, tolerances, strict=True)
        )
        estimates.append(
            CounterfactualPolicyActionEstimate(
                action=action,
                state_count=len(rows),
                mean_objective_value=math.fsum(objectives) / len(rows),
                maximum_state_regret=max(regrets),
                terminal_failure_rate=failure_rate,
                mean_branch_experiment_count=math.fsum(experiments) / len(rows),
                mean_branch_tokens=math.fsum(tokens) / len(rows),
                robustly_equivalent_to_state_best=robust,
            )
        )
    robust = tuple(item for item in estimates if item.robustly_equivalent_to_state_best)
    if not robust:
        minimum_regret = min(item.maximum_state_regret for item in estimates)
        robust = tuple(item for item in estimates if item.maximum_state_regret == minimum_regret)
        estimates = [
            item.model_copy(
                update={"robustly_equivalent_to_state_best": item in robust}
            )
            for item in estimates
        ]
    direction = results[indices[0]].metric_direction
    selected = min(
        robust,
        key=lambda item: (
            item.terminal_failure_rate,
            item.mean_branch_experiment_count,
            item.mean_branch_tokens,
            (
                item.mean_objective_value
                if direction == "lower"
                else -item.mean_objective_value
            ),
            item.action.value,
        ),
    )
    return CounterfactualTasteRule(
        evidence_status=status,
        source_study_ids=tuple(sorted(results[index].study_id for index in indices)),
        action_estimates=tuple(estimates),
        robust_action_set=tuple(
            item.action for item in estimates if item.robustly_equivalent_to_state_best
        ),
        selected_action=selected.action,
    )


def save_counterfactual_taste_policy(
    policy: CounterfactualTastePolicy,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((policy.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


__all__ = [
    "CounterfactualPolicyActionEstimate",
    "CounterfactualTastePolicy",
    "CounterfactualTasteRule",
    "fit_counterfactual_taste_policy",
    "save_counterfactual_taste_policy",
]
