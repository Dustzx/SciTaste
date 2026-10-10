#!/usr/bin/env python3
"""Evaluate one frozen conservative Taste policy on fresh formal cases."""

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
    ConservativeTasteDecision,
    ConservativeTastePolicy,
    decide_conservative_taste,
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
    frozen_policy: FileBinding
    formal_population: FormalPopulationBinding
    split_assignment: Literal["test"]
    primary_endpoint: Literal["cluster-mean-paired-regret-reduction"]
    baseline: Literal["policy-frozen-stage-static-action"]
    uncertainty_unit: Literal["task-cluster"]
    bootstrap_resamples: int = Field(ge=10_000, le=100_000)
    bootstrap_seed: int = Field(ge=0)
    practical_effect_direction: Literal["higher"]
    formal_outcomes_used_for_policy_fitting: Literal[False]
    formal_outcomes_used_for_policy_selection: Literal[False]
    method_revision_after_formal_open_prohibited: Literal[True]

    @model_validator(mode="after")
    def config_is_closed(self) -> FormalEvaluationConfig:
        validate_entry_id(self.study_id, field_name="formal conservative Taste study_id")
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
    decision: ConservativeTasteDecision
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
    formal_outcomes_used_for_policy_fitting: Literal[False] = False
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> FormalDecisionResult:
        if self.study_id != self.decision.study_id:
            raise ValueError("formal result and conservative decision IDs differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("formal conservative Taste result hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> FormalDecisionResult:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            "formal_outcomes_used_for_policy_fitting": False,
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    data = path.read_bytes()
    if len(data) > _MAX_INPUT_BYTES:
        raise ValueError(f"bound input exceeds {_MAX_INPUT_BYTES} bytes: {path}")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bound(root: Path, binding: FileBinding) -> Path:
    locator = PurePosixPath(binding.locator)
    if locator.is_absolute() or ".." in locator.parts:
        raise ValueError(f"unsafe formal input locator: {binding.locator}")
    path = (root / Path(*locator.parts)).resolve(strict=True)
    path.relative_to(root)
    if _sha256(path) != binding.sha256:
        raise ValueError(f"formal input hash mismatch: {binding.locator}")
    return path


def _stage(study_id: str) -> Literal["early", "middle", "late"]:
    value = study_id.rsplit("-", 1)[-1]
    if value not in {"early", "middle", "late"}:
        raise ValueError(f"unknown objective-fork stage: {study_id}")
    return value  # type: ignore[return-value]


def _load_formal_population(
    root: Path,
    binding: FormalPopulationBinding,
) -> tuple[tuple[FormalObjectiveForkSituationCase, ...], str, str]:
    cases_path = (root / binding.cases_locator).resolve(strict=True)
    report_path = (root / binding.materialization_report_locator).resolve(strict=True)
    cases_path.relative_to(root)
    report_path.relative_to(root)
    report = json.loads(_bytes(report_path))
    if report.get("study_id") != binding.materialization_study_id:
        raise ValueError("formal materialization study identity differs")
    if not report.get("formal_case_materialization_complete"):
        raise ValueError("formal case materialization is incomplete")
    raw = _bytes(cases_path)
    if hashlib.sha256(raw).hexdigest() != report.get("formal_test_cases_sha256"):
        raise ValueError("formal cases differ from materialization report")
    cases = tuple(
        FormalObjectiveForkSituationCase.model_validate_json(line, strict=True)
        for line in raw.decode().splitlines()
        if line.strip()
    )
    return cases, hashlib.sha256(raw).hexdigest(), _sha256(report_path)


def _failure_rate(case: FormalObjectiveForkSituationCase, action_id: str) -> float:
    outcomes = tuple(item for item in case.replicate_outcomes if item.action_id == action_id)
    if not outcomes:
        raise ValueError("formal action has no registered replicates")
    return sum(not item.objective_observed for item in outcomes) / len(outcomes)


def _score(
    case: FormalObjectiveForkSituationCase,
    decision: ConservativeTasteDecision,
) -> FormalDecisionResult:
    utilities = case.action_utility_estimates
    best = max(utilities.values())
    selector_regret = best - utilities[decision.selected_action_id]
    baseline_regret = best - utilities[decision.baseline_action_id]
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
        stage=_stage(case.study_id),
        decision=decision,
        best_utility=best,
        selector_utility=utilities[decision.selected_action_id],
        baseline_utility=utilities[decision.baseline_action_id],
        selector_regret=selector_regret,
        baseline_regret=baseline_regret,
        paired_regret_reduction=effect,
        practical_equivalence_tolerance=tolerance,
        comparison=comparison,
        selector_failure_rate=_failure_rate(case, decision.selected_action_id),
        baseline_failure_rate=_failure_rate(case, decision.baseline_action_id),
    )


def _sign_flip_p(cluster_effects: np.ndarray) -> float:
    observed = float(cluster_effects.mean())
    values = [
        float((cluster_effects * np.asarray(signs, dtype=float)).mean())
        for signs in itertools.product((-1.0, 1.0), repeat=len(cluster_effects))
    ]
    return sum(item >= observed - 1e-15 for item in values) / len(values)


def execute(args: argparse.Namespace) -> dict[str, object]:
    root = args.workspace_root.resolve(strict=True)
    config_raw = _bytes(args.config.resolve(strict=True))
    config = FormalEvaluationConfig.model_validate(yaml.safe_load(config_raw))
    policy = ConservativeTastePolicy.model_validate_json(
        _bytes(_bound(root, config.frozen_policy)), strict=True
    )
    cases, cases_sha256, report_sha256 = _load_formal_population(root, config.formal_population)
    if any(item.task_binding.split_assignment != "test" for item in cases):
        raise ValueError("formal conservative Taste opened a non-test case")
    results = tuple(
        _score(
            case,
            decide_conservative_taste(
                policy,
                case.situation,
                case.available_actions,
                stage=_stage(case.study_id),
            ),
        )
        for case in cases
    )
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in results:
        grouped[item.task_cluster_id].append(item.paired_regret_reduction)
    cluster_effects = np.asarray(
        [math.fsum(grouped[key]) / len(grouped[key]) for key in sorted(grouped)],
        dtype=float,
    )
    rng = np.random.default_rng(config.bootstrap_seed)
    bootstrap = cluster_effects[
        rng.integers(
            0,
            len(cluster_effects),
            size=(config.bootstrap_resamples, len(cluster_effects)),
        )
    ].mean(axis=1)
    effects = [item.paired_regret_reduction for item in results]
    report: dict[str, object] = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "project_id": config.project_id,
        "analysis_scope": "fresh-formal-conservative-policy-test",
        "case_count": len(results),
        "task_cluster_count": len(grouped),
        "primary_endpoint": config.primary_endpoint,
        "selector_mean_regret": math.fsum(item.selector_regret for item in results) / len(results),
        "baseline_mean_regret": math.fsum(item.baseline_regret for item in results) / len(results),
        "mean_paired_regret_reduction": math.fsum(effects) / len(effects),
        "cluster_bootstrap_95_interval": [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ],
        "exact_cluster_sign_flip_p_one_sided": _sign_flip_p(cluster_effects),
        "comparison_counts": dict(sorted(Counter(item.comparison for item in results).items())),
        "intervention_count": sum(item.decision.intervened for item in results),
        "intervention_rate": sum(item.decision.intervened for item in results) / len(results),
        "selector_mean_failure_rate": math.fsum(item.selector_failure_rate for item in results)
        / len(results),
        "baseline_mean_failure_rate": math.fsum(item.baseline_failure_rate for item in results)
        / len(results),
        "stage_effects": {
            stage: math.fsum(
                item.paired_regret_reduction for item in results if item.stage == stage
            )
            / sum(item.stage == stage for item in results)
            for stage in ("early", "middle", "late")
        },
        "policy_sha256": policy.policy_sha256,
        "formal_cases_sha256": cases_sha256,
        "materialization_report_sha256": report_sha256,
        "formal_outcomes_used_for_policy_fitting": False,
        "formal_outcomes_used_for_policy_selection": False,
        "method_revision_after_formal_open_prohibited": True,
    }
    report["report_sha256"] = content_sha256(report)
    _publish(args.output, config_raw, results, report)
    return report


def _publish(
    output: Path,
    config_raw: bytes,
    results: tuple[FormalDecisionResult, ...],
    report: dict[str, object],
) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        (temporary / "PLAN.yaml").write_bytes(config_raw)
        (temporary / "RESULTS.jsonl").write_text(
            "".join(item.model_dump_json() + "\n" for item in results), encoding="utf-8"
        )
        (temporary / "REPORT.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if output.exists():
            shutil.rmtree(output)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    args = _parser().parse_args()
    report = execute(args)
    print(
        f"study={report['study_id']} effect={report['mean_paired_regret_reduction']:.6f} "
        f"interventions={report['intervention_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
