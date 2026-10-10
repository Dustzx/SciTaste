#!/usr/bin/env python3
"""Fit and cross-validate outcome-calibrated Taste on development forks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge

from scitaste.evaluation.outcome_calibrated_taste import (
    OutcomeCalibratedTasteDecision,
    OutcomeCalibratedTasteModel,
    decide_outcome_calibrated_taste,
    grounded_situation_action_features,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 128 * 1024 * 1024


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)


class SuccessGates(BaseModel):
    model_config = _CONFIG

    require_complete_coverage: Literal[True]
    require_lower_mean_regret_than_baseline: Literal[True]
    require_no_practical_regressions: Literal[True] | None = None
    minimum_practical_win_loss_ratio: float | None = Field(default=None, ge=1.0)
    maximum_practical_regression: float | None = Field(default=None, gt=0.0)
    require_lower_or_equal_maximum_regret: Literal[True]
    minimum_selected_action_types: int = Field(ge=2, le=7)

    @model_validator(mode="after")
    def tradeoff_gate_is_closed(self) -> SuccessGates:
        zero_loss = self.require_no_practical_regressions is True
        bounded = (
            self.minimum_practical_win_loss_ratio is not None
            and self.maximum_practical_regression is not None
        )
        if zero_loss == bounded:
            raise ValueError(
                "select exactly one practical-regression gate: zero loss or bounded tradeoff"
            )
        return self


class StudyConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"]
    study_id: str
    project_id: str
    purpose: str
    source_cases: FileBinding
    split_assignment: Literal["development"]
    hidden_split_opened: Literal[False]
    model_family: Literal["grounded-sparse-ridge-v1"]
    training_target: Literal["matched-counterfactual-mean-utility"]
    alpha_grid: tuple[float, ...] = Field(min_length=2)
    outer_validation: Literal["leave-one-task-cluster-out"]
    inner_validation: Literal["leave-one-task-cluster-out"]
    baseline: Literal["source-excluded-stage-static-utility"]
    success_gates: SuccessGates
    supersedes: str | None = None
    revision_reason: str | None = None
    claim_boundary: str
    formal_evidence: Literal[False]
    effect_claim_authorized: Literal[False]

    @model_validator(mode="after")
    def config_is_closed(self) -> StudyConfig:
        validate_entry_id(self.study_id, field_name="outcome-calibrated study_id")
        validate_project_id(self.project_id)
        if self.alpha_grid != tuple(sorted(set(self.alpha_grid))):
            raise ValueError("outcome-calibrated alpha grid must be canonical")
        if any(not math.isfinite(item) or item <= 0 for item in self.alpha_grid):
            raise ValueError("outcome-calibrated alpha grid must be finite and positive")
        if self.schema_version == "1.0" and (
            self.supersedes is not None or self.revision_reason is not None
        ):
            raise ValueError("schema 1.0 cannot describe a revised development rule")
        if self.schema_version == "1.1" and (not self.supersedes or not self.revision_reason):
            raise ValueError("schema 1.1 requires transparent development-rule provenance")
        return self


class FoldDecision(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    task_cluster_id: str
    outer_training_cluster_ids: tuple[str, ...]
    selected_alpha: float = Field(gt=0.0, allow_inf_nan=False)
    decision: OutcomeCalibratedTasteDecision
    baseline_action_id: str
    action_utility_estimates: dict[str, float]
    selector_regret: float = Field(ge=0.0, allow_inf_nan=False)
    baseline_regret: float = Field(ge=0.0, allow_inf_nan=False)
    practical_equivalence_tolerance: float = Field(ge=0.0, allow_inf_nan=False)
    comparison: Literal["win", "loss", "tie"]
    selector_failure_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    baseline_failure_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    target_outcomes_used_for_selection: Literal[False] = False
    target_outcomes_used_for_development_analysis: Literal[True] = True
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> FoldDecision:
        if self.study_id != self.decision.study_id:
            raise ValueError("fold and Taste decision study IDs differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("outcome-calibrated fold result hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> FoldDecision:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            "target_outcomes_used_for_development_analysis": True,
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
    workspace = args.workspace_root.resolve(strict=True)
    config_raw = _bounded(args.config, _MAX_INPUT_BYTES)
    config = StudyConfig.model_validate(yaml.safe_load(config_raw))
    source_path = _bound(workspace, config.source_cases)
    cases = _load_cases(source_path)
    clusters = tuple(sorted({item.task_cluster_id for item in cases}))
    if len(clusters) < 3:
        raise ValueError("outcome-calibrated study requires at least three task clusters")
    if any(item.task_binding.split_assignment != "development" for item in cases):
        raise ValueError("outcome-calibrated development opened a non-development split")

    fold_results: list[FoldDecision] = []
    for held_cluster in clusters:
        training = tuple(item for item in cases if item.task_cluster_id != held_cluster)
        targets = tuple(item for item in cases if item.task_cluster_id == held_cluster)
        alpha = _select_alpha(training, config.alpha_grid)
        model = _fit_serialized_model(
            training,
            alpha=alpha,
            model_id=f"{config.study_id}-{_slug(held_cluster)}-fold",
        )
        for target in targets:
            decision = decide_outcome_calibrated_taste(
                model,
                target.situation,
                target.available_actions,
            )
            baseline = _stage_static_action(training, target)
            utilities = target.action_utility_estimates
            best = max(utilities.values())
            selector_regret = best - utilities[decision.selected_action_id]
            baseline_regret = best - utilities[baseline]
            tolerance = target.scorer_contract.practical_equivalence_tolerance
            delta = baseline_regret - selector_regret
            comparison: Literal["win", "loss", "tie"]
            if delta > tolerance:
                comparison = "win"
            elif delta < -tolerance:
                comparison = "loss"
            else:
                comparison = "tie"
            fold_results.append(
                FoldDecision.create(
                    study_id=target.study_id,
                    task_cluster_id=target.task_cluster_id,
                    outer_training_cluster_ids=tuple(
                        sorted({item.task_cluster_id for item in training})
                    ),
                    selected_alpha=alpha,
                    decision=decision,
                    baseline_action_id=baseline,
                    action_utility_estimates=utilities,
                    selector_regret=selector_regret,
                    baseline_regret=baseline_regret,
                    practical_equivalence_tolerance=tolerance,
                    comparison=comparison,
                    selector_failure_rate=_failure_rate(target, decision.selected_action_id),
                    baseline_failure_rate=_failure_rate(target, baseline),
                )
            )

    final_alpha = _select_alpha(cases, config.alpha_grid)
    final_model = _fit_serialized_model(
        cases,
        alpha=final_alpha,
        model_id=f"{config.study_id}-frozen-development-model",
    )
    report = _report(config, cases, tuple(fold_results), final_model)
    _publish(args.output, config_raw, final_model, tuple(fold_results), report)
    return report


def _select_alpha(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    alpha_grid: tuple[float, ...],
) -> float:
    clusters = tuple(sorted({item.task_cluster_id for item in cases}))
    losses: dict[float, list[float]] = {item: [] for item in alpha_grid}
    for held in clusters:
        training = tuple(item for item in cases if item.task_cluster_id != held)
        targets = tuple(item for item in cases if item.task_cluster_id == held)
        for alpha in alpha_grid:
            vectorizer, fitted = _fit_estimator(training, alpha)
            regrets = []
            for target in targets:
                selected = _predict(vectorizer, fitted, target)
                best = max(target.action_utility_estimates.values())
                regrets.append(best - target.action_utility_estimates[selected])
            losses[alpha].append(math.fsum(regrets) / len(regrets))
    return min(alpha_grid, key=lambda item: (math.fsum(losses[item]) / len(losses[item]), item))


def _fit_estimator(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    alpha: float,
) -> tuple[DictVectorizer, Ridge]:
    rows = [
        grounded_situation_action_features(case.situation, action_id)
        for case in cases
        for action_id in case.available_actions
    ]
    targets = np.asarray(
        [
            case.action_utility_estimates[action_id]
            for case in cases
            for action_id in case.available_actions
        ],
        dtype=float,
    )
    vectorizer = DictVectorizer(sparse=True, sort=True)
    design = vectorizer.fit_transform(rows)
    fitted = Ridge(alpha=alpha).fit(design, targets)
    return vectorizer, fitted


def _fit_serialized_model(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    *,
    alpha: float,
    model_id: str,
) -> OutcomeCalibratedTasteModel:
    del model_id  # Semantic identity is content-derived; the study owns the human-readable ID.
    vectorizer, fitted = _fit_estimator(cases, alpha)
    names = tuple(str(item) for item in vectorizer.get_feature_names_out())
    return OutcomeCalibratedTasteModel.create(
        feature_names=names,
        coefficients=tuple(float(item) for item in fitted.coef_),
        intercept=float(fitted.intercept_),
        ridge_alpha=alpha,
        source_case_ids=tuple(sorted(item.study_id for item in cases)),
        source_task_cluster_ids=tuple(sorted({item.task_cluster_id for item in cases})),
        training_population_sha256=content_sha256(
            tuple(
                {
                    "study_id": item.study_id,
                    "result_sha256": item.result_sha256,
                    "situation_sha256": item.situation.situation_sha256,
                }
                for item in sorted(cases, key=lambda value: value.study_id)
            )
        ),
    )


def _predict(
    vectorizer: DictVectorizer,
    fitted: Ridge,
    target: FormalObjectiveForkSituationCase,
) -> str:
    actions = target.available_actions
    design = vectorizer.transform(
        [grounded_situation_action_features(target.situation, item) for item in actions]
    )
    predictions = fitted.predict(design)
    return max(
        zip(actions, predictions, strict=True),
        key=lambda item: (float(item[1]), item[0]),
    )[0]


def _stage_static_action(
    training: tuple[FormalObjectiveForkSituationCase, ...],
    target: FormalObjectiveForkSituationCase,
) -> str:
    stage = target.study_id.rsplit("-", 1)[-1]
    values: dict[str, list[float]] = defaultdict(list)
    for item in training:
        if item.study_id.rsplit("-", 1)[-1] != stage:
            continue
        for action_id in set(item.available_actions) & set(target.available_actions):
            values[action_id].append(item.action_utility_estimates[action_id])
    if set(values) != set(target.available_actions) or any(not item for item in values.values()):
        raise ValueError("source-excluded stage-static baseline lacks complete action support")
    return max(
        target.available_actions,
        key=lambda action_id: (
            math.fsum(values[action_id]) / len(values[action_id]),
            action_id,
        ),
    )


def _failure_rate(case: FormalObjectiveForkSituationCase, action_id: str) -> float:
    outcomes = [item for item in case.replicate_outcomes if item.action_id == action_id]
    return sum(not item.objective_observed for item in outcomes) / len(outcomes)


def _report(
    config: StudyConfig,
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    results: tuple[FoldDecision, ...],
    model: OutcomeCalibratedTasteModel,
) -> dict[str, object]:
    selector_regrets = [item.selector_regret for item in results]
    baseline_regrets = [item.baseline_regret for item in results]
    comparison_counts = Counter(item.comparison for item in results)
    action_counts = Counter(item.decision.selected_action_id for item in results)
    cluster_deltas = {
        cluster: math.fsum(
            item.baseline_regret - item.selector_regret
            for item in results
            if item.task_cluster_id == cluster
        )
        / sum(item.task_cluster_id == cluster for item in results)
        for cluster in sorted({item.task_cluster_id for item in results})
    }
    practical_regressions = [
        item.selector_regret - item.baseline_regret for item in results if item.comparison == "loss"
    ]
    maximum_practical_regression = max(practical_regressions, default=0.0)
    win_loss_ratio = comparison_counts["win"] / max(comparison_counts["loss"], 1)
    if config.success_gates.require_no_practical_regressions:
        practical_gate_name = "no_practical_regressions"
        practical_gate_passed = comparison_counts["loss"] == 0
    else:
        practical_gate_name = "bounded_practical_tradeoff"
        practical_gate_passed = win_loss_ratio >= float(
            config.success_gates.minimum_practical_win_loss_ratio
        ) and maximum_practical_regression <= float(
            config.success_gates.maximum_practical_regression
        )
    gates = {
        "complete_coverage": len(results) == len(cases),
        "lower_mean_regret_than_baseline": (
            math.fsum(selector_regrets) < math.fsum(baseline_regrets)
        ),
        practical_gate_name: practical_gate_passed,
        "lower_or_equal_maximum_regret": max(selector_regrets) <= max(baseline_regrets),
        "selected_action_diversity": (
            len(action_counts) >= config.success_gates.minimum_selected_action_types
        ),
    }
    report: dict[str, object] = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "project_id": config.project_id,
        "analysis_scope": "development-only-nested-leave-one-task-cluster-out",
        "case_count": len(cases),
        "task_cluster_count": len({item.task_cluster_id for item in cases}),
        "branch_trajectory_count": sum(len(item.replicate_outcomes) for item in cases),
        "coverage": len(results) / len(cases),
        "selector_mean_regret": math.fsum(selector_regrets) / len(selector_regrets),
        "baseline_mean_regret": math.fsum(baseline_regrets) / len(baseline_regrets),
        "regret_reduction": (math.fsum(baseline_regrets) - math.fsum(selector_regrets))
        / len(selector_regrets),
        "selector_maximum_regret": max(selector_regrets),
        "baseline_maximum_regret": max(baseline_regrets),
        "comparison_counts": dict(sorted(comparison_counts.items())),
        "practical_win_loss_ratio": win_loss_ratio,
        "maximum_practical_regression": maximum_practical_regression,
        "selected_action_counts": dict(sorted(action_counts.items())),
        "selector_mean_failure_rate": math.fsum(item.selector_failure_rate for item in results)
        / len(results),
        "baseline_mean_failure_rate": math.fsum(item.baseline_failure_rate for item in results)
        / len(results),
        "task_cluster_regret_reduction": cluster_deltas,
        "outer_selected_alpha_counts": dict(
            sorted(Counter(str(item.selected_alpha) for item in results).items())
        ),
        "frozen_model_alpha": model.ridge_alpha,
        "frozen_model_sha256": model.model_sha256,
        "gates": gates,
        "formal_evaluation_freeze_recommended": all(gates.values()),
        "hidden_split_opened": False,
        "formal_evidence": False,
        "effect_claim_authorized": False,
        "target_outcomes_used_for_training": True,
        "target_outcomes_used_for_selection": False,
        "claim_boundary": config.claim_boundary,
    }
    report["report_sha256"] = content_sha256(report)
    return report


def _publish(
    target: Path,
    config_raw: bytes,
    model: OutcomeCalibratedTasteModel,
    results: tuple[FoldDecision, ...],
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
            temporary / "MODEL.json",
            (model.model_dump_json(indent=2) + "\n").encode(),
        )
        decision_bytes = b"".join((item.model_dump_json() + "\n").encode() for item in results)
        _write_new(temporary / "DECISIONS.jsonl", decision_bytes)
        _write_new(
            temporary / "REPORT.json",
            (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(),
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _load_cases(path: Path) -> tuple[FormalObjectiveForkSituationCase, ...]:
    cases = tuple(
        FormalObjectiveForkSituationCase.model_validate_json(line, strict=True)
        for line in path.read_bytes().splitlines()
        if line.strip()
    )
    if len(cases) < 3 or len({item.study_id for item in cases}) != len(cases):
        raise ValueError("outcome-calibrated case population is too small or duplicated")
    return tuple(sorted(cases, key=lambda item: item.study_id))


def _bound(workspace: Path, binding: FileBinding) -> Path:
    pure = PurePosixPath(binding.locator)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != binding.locator:
        raise ValueError("unsafe outcome-calibrated source locator")
    path = _bounded(workspace.joinpath(*pure.parts), _MAX_INPUT_BYTES)
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding.sha256:
        raise ValueError("outcome-calibrated source bytes changed")
    return path


def _bounded(path: Path, maximum_bytes: int) -> bytes | Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bounded input must be a regular file: {path}")
    if not 1 <= path.stat().st_size <= maximum_bytes:
        raise ValueError(f"bounded input exceeds its byte ceiling: {path}")
    if path.suffix in {".yaml", ".yml"}:
        return path.read_bytes()
    return path


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    return parser


def main() -> None:
    report = execute(build_parser().parse_args())
    print(
        "study="
        f"{report['study_id']} mean_regret={report['selector_mean_regret']:.6f} "
        f"baseline={report['baseline_mean_regret']:.6f} "
        f"freeze={report['formal_evaluation_freeze_recommended']}"
    )


if __name__ == "__main__":
    main()
