#!/usr/bin/env python3
"""Evaluate one frozen outcome-calibrated Taste policy on formal cases."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.outcome_calibrated_taste import (
    OutcomeCalibratedTasteDecision,
    OutcomeCalibratedTasteModel,
    decide_outcome_calibrated_taste,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 256 * 1024 * 1024


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)


class FormalPopulationBinding(BaseModel):
    model_config = _CONFIG

    cases_locator: str
    materialization_report_locator: str
    materialization_study_id: str


class FormalEvaluationConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    frozen_selector_model: FileBinding
    development_cases: FileBinding
    formal_population: FormalPopulationBinding
    split_assignment: Literal["test"]
    primary_endpoint: Literal["cluster-mean-paired-regret-reduction"]
    baseline: Literal["development-frozen-stage-static-policy"]
    uncertainty_unit: Literal["task-cluster"]
    alpha: float = Field(gt=0.0, lt=0.5)
    bootstrap_resamples: int = Field(ge=10_000, le=100_000)
    bootstrap_seed: int = Field(ge=0)
    minimum_mean_regret_reduction: float = Field(ge=0.0)
    require_bootstrap_ci_lower_above_zero: Literal[True]
    require_exact_sign_flip_p_below_alpha: Literal[True]
    formal_outcomes_used_for_model_selection: Literal[False]
    method_revision_after_formal_open_prohibited: Literal[True]

    @model_validator(mode="after")
    def config_is_closed(self) -> FormalEvaluationConfig:
        validate_entry_id(self.study_id, field_name="formal Taste evaluation study_id")
        validate_project_id(self.project_id)
        validate_entry_id(
            self.formal_population.materialization_study_id,
            field_name="formal materialization study_id",
        )
        return self


class FormalDecisionResult(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    task_cluster_id: str
    stage: Literal["early", "middle", "late"]
    decision: OutcomeCalibratedTasteDecision
    baseline_action_id: str
    best_utility: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    selector_utility: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    baseline_utility: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    selector_regret: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    baseline_regret: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    paired_regret_reduction: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    practical_equivalence_tolerance: float = Field(ge=0.0, allow_inf_nan=False)
    comparison: Literal["win", "loss", "tie"]
    selector_failure_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    baseline_failure_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    target_outcomes_used_for_selection: Literal[False] = False
    formal_outcomes_used_for_model_fitting: Literal[False] = False
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> FormalDecisionResult:
        if self.study_id != self.decision.study_id:
            raise ValueError("formal result and decision study IDs differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("formal Taste result hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> FormalDecisionResult:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            "formal_outcomes_used_for_model_fitting": False,
            **values,
        }
        payload.pop("result_sha256", None)
        unsigned = cls.model_construct(result_sha256="0" * 64, **payload)
        return cls(
            **payload,
            result_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"result_sha256"})
            ),
        )


def execute(args: argparse.Namespace) -> dict[str, object]:
    root = args.workspace_root.resolve(strict=True)
    config_raw = _bounded_file(args.config.resolve(strict=True))
    config = FormalEvaluationConfig.model_validate(yaml.safe_load(config_raw))
    model = OutcomeCalibratedTasteModel.model_validate_json(
        _bytes(_bound(root, config.frozen_selector_model)), strict=True
    )
    development = _load_cases(_bound(root, config.development_cases))
    formal, formal_cases_sha256, materialization_report_sha256 = _load_formal_population(
        root, config.formal_population
    )
    if any(item.task_binding.split_assignment != "development" for item in development):
        raise ValueError("formal Taste baseline source is not development-only")
    if any(item.task_binding.split_assignment != "test" for item in formal):
        raise ValueError("formal Taste target population is not test-only")
    if set(model.source_case_ids) != {item.study_id for item in development}:
        raise ValueError("frozen Taste model and development population differ")

    decisions = tuple(
        decide_outcome_calibrated_taste(
            model,
            target.situation,
            target.available_actions,
        )
        for target in formal
    )
    baseline_policy = _freeze_stage_static_policy(development)
    results = tuple(
        _score(target, decision, baseline_policy)
        for target, decision in zip(formal, decisions, strict=True)
    )
    report = _report(
        config,
        model,
        results,
        baseline_policy,
        formal_cases_sha256=formal_cases_sha256,
        materialization_report_sha256=materialization_report_sha256,
    )
    _publish(args.output, config_raw, results, report)
    return report


def _stage(study_id: str) -> Literal["early", "middle", "late"]:
    value = study_id.rsplit("-", 1)[-1]
    if value not in {"early", "middle", "late"}:
        raise ValueError(f"unknown objective-fork stage: {study_id}")
    return value  # type: ignore[return-value]


def _freeze_stage_static_policy(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
) -> dict[str, str]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    menus: dict[str, tuple[str, ...]] = {}
    for case in cases:
        stage = _stage(case.study_id)
        if stage in menus and menus[stage] != case.available_actions:
            raise ValueError("development action menu drift within stage")
        menus[stage] = case.available_actions
        for action_id in case.available_actions:
            values[stage][action_id].append(case.action_utility_estimates[action_id])
    if set(values) != {"early", "middle", "late"}:
        raise ValueError("development baseline lacks a decision stage")
    return {
        stage: max(
            menus[stage],
            key=lambda action_id: (
                math.fsum(values[stage][action_id]) / len(values[stage][action_id]),
                action_id,
            ),
        )
        for stage in sorted(values)
    }


def _score(
    case: FormalObjectiveForkSituationCase,
    decision: OutcomeCalibratedTasteDecision,
    baseline_policy: dict[str, str],
) -> FormalDecisionResult:
    stage = _stage(case.study_id)
    baseline = baseline_policy[stage]
    if baseline not in case.available_actions:
        raise ValueError("frozen baseline action is absent from formal action menu")
    utilities = case.action_utility_estimates
    best = max(utilities.values())
    selector_regret = best - utilities[decision.selected_action_id]
    baseline_regret = best - utilities[baseline]
    effect = baseline_regret - selector_regret
    tolerance = case.scorer_contract.practical_equivalence_tolerance
    comparison: Literal["win", "loss", "tie"]
    if effect > tolerance:
        comparison = "win"
    elif effect < -tolerance:
        comparison = "loss"
    else:
        comparison = "tie"
    return FormalDecisionResult.create(
        study_id=case.study_id,
        task_cluster_id=case.task_cluster_id,
        stage=stage,
        decision=decision,
        baseline_action_id=baseline,
        best_utility=best,
        selector_utility=utilities[decision.selected_action_id],
        baseline_utility=utilities[baseline],
        selector_regret=selector_regret,
        baseline_regret=baseline_regret,
        paired_regret_reduction=effect,
        practical_equivalence_tolerance=tolerance,
        comparison=comparison,
        selector_failure_rate=_failure_rate(case, decision.selected_action_id),
        baseline_failure_rate=_failure_rate(case, baseline),
    )


def _failure_rate(case: FormalObjectiveForkSituationCase, action_id: str) -> float:
    outcomes = tuple(item for item in case.replicate_outcomes if item.action_id == action_id)
    if not outcomes:
        raise ValueError("formal action has no registered replicates")
    return sum(not item.objective_observed for item in outcomes) / len(outcomes)


def _report(
    config: FormalEvaluationConfig,
    model: OutcomeCalibratedTasteModel,
    results: tuple[FormalDecisionResult, ...],
    baseline_policy: dict[str, str],
    *,
    formal_cases_sha256: str,
    materialization_report_sha256: str,
) -> dict[str, object]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in results:
        grouped[item.task_cluster_id].append(item.paired_regret_reduction)
    cluster_effects = np.asarray(
        [math.fsum(grouped[key]) / len(grouped[key]) for key in sorted(grouped)],
        dtype=float,
    )
    observed = float(cluster_effects.mean())
    rng = np.random.default_rng(config.bootstrap_seed)
    bootstrap = cluster_effects[
        rng.integers(
            0,
            len(cluster_effects),
            size=(config.bootstrap_resamples, len(cluster_effects)),
        )
    ].mean(axis=1)
    ci_low, ci_high = (float(item) for item in np.quantile(bootstrap, [0.025, 0.975]))
    sign_flip_values = np.asarray(
        [
            float(np.mean(cluster_effects * np.asarray(signs, dtype=float)))
            for signs in itertools.product((-1.0, 1.0), repeat=len(cluster_effects))
        ]
    )
    p_value = float(np.mean(sign_flip_values >= observed - 1e-15))
    counts = Counter(item.comparison for item in results)
    action_counts = Counter(item.decision.selected_action_id for item in results)
    selector_regrets = [item.selector_regret for item in results]
    baseline_regrets = [item.baseline_regret for item in results]
    gates = {
        "positive_mean_regret_reduction": (observed > config.minimum_mean_regret_reduction),
        "bootstrap_ci_lower_above_zero": ci_low > 0.0,
        "exact_sign_flip_p_below_alpha": p_value < config.alpha,
    }
    report: dict[str, object] = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "project_id": config.project_id,
        "analysis_scope": "formal-frozen-policy-test",
        "case_count": len(results),
        "task_cluster_count": len(grouped),
        "primary_endpoint": config.primary_endpoint,
        "selector_mean_regret": math.fsum(selector_regrets) / len(results),
        "baseline_mean_regret": math.fsum(baseline_regrets) / len(results),
        "mean_paired_regret_reduction": observed,
        "relative_mean_regret_reduction": (
            observed / (math.fsum(baseline_regrets) / len(results))
            if math.fsum(baseline_regrets) > 0
            else None
        ),
        "cluster_bootstrap_95_ci": [ci_low, ci_high],
        "exact_cluster_sign_flip_p_one_sided": p_value,
        "comparison_counts": dict(sorted(counts.items())),
        "selected_action_counts": dict(sorted(action_counts.items())),
        "baseline_policy": baseline_policy,
        "selector_mean_failure_rate": math.fsum(item.selector_failure_rate for item in results)
        / len(results),
        "baseline_mean_failure_rate": math.fsum(item.baseline_failure_rate for item in results)
        / len(results),
        "task_cluster_effects": {
            key: math.fsum(grouped[key]) / len(grouped[key]) for key in sorted(grouped)
        },
        "gates": gates,
        "formal_effect_supported": all(gates.values()),
        "frozen_model_sha256": model.model_sha256,
        "formal_cases_sha256": formal_cases_sha256,
        "materialization_report_sha256": materialization_report_sha256,
        "target_outcomes_used_for_selection": False,
        "formal_outcomes_used_for_model_fitting": False,
        "formal_outcomes_used_for_model_selection": False,
        "method_revision_after_formal_open_prohibited": True,
    }
    report["report_sha256"] = content_sha256(report)
    return report


def _load_formal_population(
    root: Path,
    binding: FormalPopulationBinding,
) -> tuple[tuple[FormalObjectiveForkSituationCase, ...], str, str]:
    cases_path = _safe_path(root, binding.cases_locator)
    report_path = _safe_path(root, binding.materialization_report_locator)
    report_raw = _bytes(report_path)
    report = json.loads(report_raw)
    if report.get("study_id") != binding.materialization_study_id:
        raise ValueError("formal materialization report identity differs")
    cases_sha256 = hashlib.sha256(_bytes(cases_path)).hexdigest()
    if cases_sha256 != report.get("formal_test_cases_sha256"):
        raise ValueError("formal cases differ from the materialization report")
    return _load_cases(cases_path), cases_sha256, hashlib.sha256(report_raw).hexdigest()


def _load_cases(path: Path) -> tuple[FormalObjectiveForkSituationCase, ...]:
    cases = tuple(
        FormalObjectiveForkSituationCase.model_validate_json(line, strict=True)
        for line in _bytes(path).splitlines()
        if line.strip()
    )
    if len(cases) < 6 or len({item.study_id for item in cases}) != len(cases):
        raise ValueError("formal Taste population is too small or duplicated")
    return tuple(sorted(cases, key=lambda item: item.study_id))


def _safe_path(root: Path, locator: str) -> Path:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != locator:
        raise ValueError("unsafe formal Taste input locator")
    path = root.joinpath(*pure.parts).resolve(strict=True)
    path.relative_to(root)
    _bounded_file(path)
    return path


def _bound(root: Path, binding: FileBinding) -> Path:
    path = _safe_path(root, binding.locator)
    if hashlib.sha256(_bytes(path)).hexdigest() != binding.sha256:
        raise ValueError("formal Taste bound input hash differs")
    return path


def _bounded_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"formal Taste input must be a regular file: {path}")
    if not 1 <= path.stat().st_size <= _MAX_INPUT_BYTES:
        raise ValueError(f"formal Taste input exceeds its byte ceiling: {path}")
    return path.read_bytes()


def _bytes(path: Path) -> bytes:
    return _bounded_file(path)


def _publish(
    target: Path,
    config_raw: bytes,
    results: tuple[FormalDecisionResult, ...],
    report: dict[str, object],
) -> None:
    destination = target.resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        _write_new(temporary / "PLAN.yaml", config_raw)
        _write_new(
            temporary / "RESULTS.jsonl",
            b"".join((item.model_dump_json() + "\n").encode() for item in results),
        )
        _write_new(
            temporary / "REPORT.json",
            (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(),
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    return parser


def main() -> None:
    report = execute(build_parser().parse_args())
    print(
        f"study={report['study_id']} effect={report['mean_paired_regret_reduction']:.6f} "
        f"p={report['exact_cluster_sign_flip_p_one_sided']:.6f} "
        f"supported={report['formal_effect_supported']}"
    )


if __name__ == "__main__":
    main()
