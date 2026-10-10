#!/usr/bin/env python3
"""Freeze and diagnose conservative Scientific Taste on historical forks."""

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
    ConservativeTasteDecision,
    ConservativeTastePolicy,
    OutcomeCalibratedTasteModel,
    decide_conservative_taste,
    grounded_situation_axis_action_features,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 256 * 1024 * 1024
_GROUP = re.compile(r"(?:^|-)m(\d+)(?:-|$)")


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)


class HistoricalCaseSource(BaseModel):
    model_config = _CONFIG

    source_id: str
    original_designation: Literal["development", "formal-test-v1"]
    cases: FileBinding


class StudyConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    purpose: str
    historical_sources: tuple[HistoricalCaseSource, ...] = Field(min_length=2)
    historical_evidence_cutoff: str
    model_family: Literal["axis-jackknife-conservative-ridge-v1"]
    feature_contract: Literal["grounded-situation-axis-action-v1"]
    grouping_unit: Literal["newtonbench-law-module"]
    ridge_alpha: float = Field(gt=0.0, allow_inf_nan=False)
    intervention_margin: float = Field(ge=0.0, allow_inf_nan=False)
    minimum_member_agreement: float = Field(gt=0.5, le=1.0, allow_inf_nan=False)
    validation: Literal["leave-one-law-module-out"]
    baseline: Literal["source-excluded-stage-static-utility"]
    formal_evidence: Literal[False]
    effect_claim_authorized: Literal[False]
    claim_boundary: str

    @model_validator(mode="after")
    def config_is_closed(self) -> StudyConfig:
        validate_entry_id(self.study_id, field_name="conservative Taste study_id")
        validate_project_id(self.project_id)
        source_ids = tuple(item.source_id for item in self.historical_sources)
        if source_ids != tuple(sorted(set(source_ids))):
            raise ValueError("historical conservative Taste sources must be canonical")
        if {item.original_designation for item in self.historical_sources} != {
            "development",
            "formal-test-v1",
        }:
            raise ValueError("conservative Taste requires development and disclosed v1 evidence")
        return self


class HistoricalDecision(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    law_group_id: str
    decision: ConservativeTasteDecision
    best_utility: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    selector_regret: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    baseline_regret: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    paired_regret_reduction: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    comparison: Literal["win", "loss", "tie"]
    target_outcomes_used_for_selection: Literal[False] = False
    target_outcomes_used_for_historical_analysis: Literal[True] = True
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> HistoricalDecision:
        if self.study_id != self.decision.study_id:
            raise ValueError("historical result and decision study IDs differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("historical conservative Taste result hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> HistoricalDecision:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            "target_outcomes_used_for_historical_analysis": True,
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
        raise ValueError(f"unsafe historical source locator: {binding.locator}")
    path = (root / Path(*locator.parts)).resolve(strict=True)
    path.relative_to(root)
    if _sha256(path) != binding.sha256:
        raise ValueError(f"historical source hash mismatch: {binding.locator}")
    return path


def _load_cases(path: Path) -> tuple[FormalObjectiveForkSituationCase, ...]:
    cases = tuple(
        FormalObjectiveForkSituationCase.model_validate_json(line, strict=True)
        for line in _bytes(path).decode().splitlines()
        if line.strip()
    )
    if not cases:
        raise ValueError(f"historical source is empty: {path}")
    return cases


def _group(case: FormalObjectiveForkSituationCase) -> str:
    match = _GROUP.search(case.task_cluster_id)
    if match is None:
        raise ValueError(f"cannot derive NewtonBench law group: {case.task_cluster_id}")
    return f"m{int(match.group(1))}"


def _stage(case: FormalObjectiveForkSituationCase) -> Literal["early", "middle", "late"]:
    value = case.study_id.rsplit("-", 1)[-1]
    if value not in {"early", "middle", "late"}:
        raise ValueError(f"unknown objective-fork stage: {case.study_id}")
    return value  # type: ignore[return-value]


def _baseline_actions(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
) -> dict[str, str]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for case in cases:
        for action_id in case.available_actions:
            values[_stage(case)][action_id].append(case.action_utility_estimates[action_id])
    if set(values) != {"early", "middle", "late"}:
        raise ValueError("historical population lacks a decision stage")
    return {
        stage: max(
            actions,
            key=lambda action_id: (
                math.fsum(actions[action_id]) / len(actions[action_id]),
                action_id,
            ),
        )
        for stage, actions in sorted(values.items())
    }


def _fit_member(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    *,
    alpha: float,
) -> OutcomeCalibratedTasteModel:
    rows = [
        grounded_situation_axis_action_features(case.situation, action_id)
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
    return OutcomeCalibratedTasteModel.create(
        feature_names=tuple(str(item) for item in vectorizer.get_feature_names_out()),
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


def _fit_policy(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    config: StudyConfig,
) -> ConservativeTastePolicy:
    groups = tuple(sorted({_group(item) for item in cases}))
    if len(groups) < 5:
        raise ValueError("conservative Taste requires at least five law groups")
    members = tuple(
        _fit_member(
            tuple(item for item in cases if _group(item) != heldout),
            alpha=config.ridge_alpha,
        )
        for heldout in groups
    )
    return ConservativeTastePolicy.create(
        members=members,
        member_heldout_group_ids=groups,
        baseline_actions=_baseline_actions(cases),
        intervention_margin=config.intervention_margin,
        minimum_member_agreement=config.minimum_member_agreement,
        source_case_ids=tuple(sorted(item.study_id for item in cases)),
        source_group_ids=groups,
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


def _score(
    case: FormalObjectiveForkSituationCase,
    decision: ConservativeTasteDecision,
) -> HistoricalDecision:
    best = max(case.action_utility_estimates.values())
    selector_regret = best - case.action_utility_estimates[decision.selected_action_id]
    baseline_regret = best - case.action_utility_estimates[decision.baseline_action_id]
    effect = baseline_regret - selector_regret
    tolerance = case.scorer_contract.practical_equivalence_tolerance
    comparison: Literal["win", "loss", "tie"]
    if effect > tolerance:
        comparison = "win"
    elif effect < -tolerance:
        comparison = "loss"
    else:
        comparison = "tie"
    return HistoricalDecision.create(
        study_id=case.study_id,
        law_group_id=_group(case),
        decision=decision,
        best_utility=best,
        selector_regret=selector_regret,
        baseline_regret=baseline_regret,
        paired_regret_reduction=effect,
        comparison=comparison,
    )


def execute(args: argparse.Namespace) -> dict[str, object]:
    root = args.workspace_root.resolve(strict=True)
    config_raw = _bytes(args.config.resolve(strict=True))
    config = StudyConfig.model_validate(yaml.safe_load(config_raw))
    populations = tuple(
        _load_cases(_bound(root, source.cases)) for source in config.historical_sources
    )
    cases = tuple(item for population in populations for item in population)
    if len({item.study_id for item in cases}) != len(cases):
        raise ValueError("historical conservative Taste cases overlap")
    groups = tuple(sorted({_group(item) for item in cases}))

    results: list[HistoricalDecision] = []
    for heldout in groups:
        training = tuple(item for item in cases if _group(item) != heldout)
        targets = tuple(item for item in cases if _group(item) == heldout)
        policy = _fit_policy(training, config)
        for target in targets:
            decision = decide_conservative_taste(
                policy,
                target.situation,
                target.available_actions,
                stage=_stage(target),
            )
            results.append(_score(target, decision))

    final_policy = _fit_policy(cases, config)
    effects = [item.paired_regret_reduction for item in results]
    selector = [item.selector_regret for item in results]
    baseline = [item.baseline_regret for item in results]
    comparisons = Counter(item.comparison for item in results)
    report: dict[str, object] = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "project_id": config.project_id,
        "analysis_scope": "historical-post-formal-v1-method-development",
        "case_count": len(cases),
        "law_group_count": len(groups),
        "source_case_counts": {
            source.source_id: len(population)
            for source, population in zip(config.historical_sources, populations, strict=True)
        },
        "selector_mean_regret": math.fsum(selector) / len(selector),
        "baseline_mean_regret": math.fsum(baseline) / len(baseline),
        "mean_paired_regret_reduction": math.fsum(effects) / len(effects),
        "comparison_counts": dict(sorted(comparisons.items())),
        "intervention_count": sum(item.decision.intervened for item in results),
        "selected_action_counts": dict(
            sorted(Counter(item.decision.selected_action_id for item in results).items())
        ),
        "ridge_alpha": config.ridge_alpha,
        "intervention_margin": config.intervention_margin,
        "minimum_member_agreement": config.minimum_member_agreement,
        "feature_contract": config.feature_contract,
        "validation": config.validation,
        "formal_evidence": False,
        "effect_claim_authorized": False,
        "claim_boundary": config.claim_boundary,
        "policy_sha256": final_policy.policy_sha256,
    }
    report["report_sha256"] = content_sha256(report)
    _publish(args.output, config_raw, final_policy, tuple(results), report)
    return report


def _publish(
    output: Path,
    config_raw: bytes,
    policy: ConservativeTastePolicy,
    results: tuple[HistoricalDecision, ...],
    report: dict[str, object],
) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        (temporary / "PLAN.yaml").write_bytes(config_raw)
        (temporary / "POLICY.json").write_text(
            policy.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (temporary / "DECISIONS.jsonl").write_text(
            "".join(item.model_dump_json() + "\n" for item in results),
            encoding="utf-8",
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
