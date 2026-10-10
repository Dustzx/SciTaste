#!/usr/bin/env python3
"""Evaluate chronological outcome learning against frozen and shuffled controls."""

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
    OutcomeCalibratedTasteModel,
    grounded_situation_axis_action_features,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_GROUP = re.compile(r"(?:^|-)m(\d+)(?:-|$)")
_MAX_INPUT_BYTES = 256 * 1024 * 1024


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)


class OutcomeLearningConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    historical_sources: tuple[FileBinding, ...] = Field(min_length=1)
    opened_population: FileBinding
    registration: FileBinding | None = None
    learning_group_ids: tuple[str, ...] = Field(min_length=2)
    evaluation_group_ids: tuple[str, ...] = Field(min_length=2)
    model_family: Literal["axis-ridge-outcome-learning-v1"]
    ridge_alpha: float = Field(gt=0.0, allow_inf_nan=False)
    shuffle_control: Literal["within-stage-cyclic-case-target-v1"]
    primary_endpoint: Literal["updated-minus-no-update-regret-reduction"]
    secondary_endpoint: Literal["updated-minus-shuffled-regret-reduction"]
    bootstrap_resamples: int = Field(ge=10_000, le=100_000)
    bootstrap_seed: int = Field(ge=0)
    chronological_order_frozen: Literal[True]
    formal_evidence: bool
    effect_claim_authorized: bool
    claim_boundary: str

    @model_validator(mode="after")
    def protocol_is_closed(self) -> OutcomeLearningConfig:
        validate_entry_id(self.study_id, field_name="Outcome Learning study_id")
        validate_project_id(self.project_id)
        if set(self.learning_group_ids) & set(self.evaluation_group_ids):
            raise ValueError("Outcome Learning update and evaluation groups overlap")
        if self.learning_group_ids != tuple(sorted(set(self.learning_group_ids))):
            raise ValueError("Outcome Learning update groups are not canonical")
        if self.evaluation_group_ids != tuple(sorted(set(self.evaluation_group_ids))):
            raise ValueError("Outcome Learning evaluation groups are not canonical")
        if self.formal_evidence:
            if self.registration is None or not self.effect_claim_authorized:
                raise ValueError("formal Outcome Learning requires a bound registration")
        elif self.registration is not None or self.effect_claim_authorized:
            raise ValueError("development Outcome Learning cannot authorize an effect claim")
        return self


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
        raise ValueError(f"unsafe Outcome Learning locator: {binding.locator}")
    path = (root / Path(*locator.parts)).resolve(strict=True)
    path.relative_to(root)
    if _sha256(path) != binding.sha256:
        raise ValueError(f"Outcome Learning input hash mismatch: {binding.locator}")
    return path


def _load_cases(path: Path) -> tuple[FormalObjectiveForkSituationCase, ...]:
    cases = tuple(
        FormalObjectiveForkSituationCase.model_validate_json(line, strict=True)
        for line in _bytes(path).decode().splitlines()
        if line.strip()
    )
    if not cases:
        raise ValueError(f"Outcome Learning source is empty: {path}")
    return cases


def _group(case: FormalObjectiveForkSituationCase) -> str:
    match = _GROUP.search(case.task_cluster_id)
    if match is None:
        raise ValueError(f"cannot derive NewtonBench group: {case.task_cluster_id}")
    return f"m{int(match.group(1))}"


def _stage(case: FormalObjectiveForkSituationCase) -> str:
    stage = case.study_id.rsplit("-", 1)[-1]
    if stage not in {"early", "middle", "late"}:
        raise ValueError(f"unknown Objective Fork stage: {case.study_id}")
    return stage


def _shuffled_targets(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
) -> dict[tuple[str, str], float]:
    """Rotate complete action-value vectors across situations within each stage."""

    by_stage: dict[str, list[FormalObjectiveForkSituationCase]] = defaultdict(list)
    for case in cases:
        by_stage[_stage(case)].append(case)
    targets: dict[tuple[str, str], float] = {}
    for stage, stage_cases in sorted(by_stage.items()):
        ordered = sorted(stage_cases, key=lambda item: item.study_id)
        if len(ordered) < 2:
            raise ValueError(f"shuffled-credit stage has fewer than two cases: {stage}")
        for index, recipient in enumerate(ordered):
            donor = ordered[(index + 1) % len(ordered)]
            if recipient.available_actions != donor.available_actions:
                raise ValueError("shuffled-credit action menus differ within stage")
            for action_id in recipient.available_actions:
                targets[(recipient.study_id, action_id)] = donor.action_utility_estimates[action_id]
    return targets


def _fit(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    *,
    alpha: float,
    target_overrides: dict[tuple[str, str], float] | None = None,
) -> OutcomeCalibratedTasteModel:
    rows = [
        grounded_situation_axis_action_features(case.situation, action_id)
        for case in cases
        for action_id in case.available_actions
    ]
    targets = np.asarray(
        [
            (target_overrides or {}).get(
                (case.study_id, action_id),
                case.action_utility_estimates[action_id],
            )
            for case in cases
            for action_id in case.available_actions
        ],
        dtype=float,
    )
    vectorizer = DictVectorizer(sparse=True, sort=True)
    design = vectorizer.fit_transform(rows)
    fitted = Ridge(alpha=alpha).fit(design, targets)
    target_record = tuple(
        {
            "study_id": case.study_id,
            "result_sha256": case.result_sha256,
            "targets": {
                action_id: (target_overrides or {}).get(
                    (case.study_id, action_id),
                    case.action_utility_estimates[action_id],
                )
                for action_id in case.available_actions
            },
        }
        for case in sorted(cases, key=lambda item: item.study_id)
    )
    return OutcomeCalibratedTasteModel.create(
        feature_names=tuple(str(item) for item in vectorizer.get_feature_names_out()),
        coefficients=tuple(float(item) for item in fitted.coef_),
        intercept=float(fitted.intercept_),
        ridge_alpha=alpha,
        source_case_ids=tuple(sorted(item.study_id for item in cases)),
        source_task_cluster_ids=tuple(sorted({item.task_cluster_id for item in cases})),
        training_population_sha256=content_sha256(target_record),
    )


def _select(model: OutcomeCalibratedTasteModel, case: FormalObjectiveForkSituationCase) -> str:
    return max(
        case.available_actions,
        key=lambda action_id: (model.score(case.situation, action_id), action_id),
    )


def _cluster_interval(effects: dict[str, list[float]], *, resamples: int, seed: int) -> list[float]:
    cluster_means = np.asarray(
        [math.fsum(effects[key]) / len(effects[key]) for key in sorted(effects)],
        dtype=float,
    )
    rng = np.random.default_rng(seed)
    bootstrap = cluster_means[
        rng.integers(0, len(cluster_means), size=(resamples, len(cluster_means)))
    ].mean(axis=1)
    return [float(np.quantile(bootstrap, 0.025)), float(np.quantile(bootstrap, 0.975))]


def execute(args: argparse.Namespace) -> dict[str, object]:
    root = args.workspace_root.resolve(strict=True)
    config_raw = _bytes(args.config.resolve(strict=True))
    config = OutcomeLearningConfig.model_validate(yaml.safe_load(config_raw))
    if config.registration is not None:
        _bound(root, config.registration)
    historical = tuple(
        case for binding in config.historical_sources for case in _load_cases(_bound(root, binding))
    )
    opened = _load_cases(_bound(root, config.opened_population))
    learning = tuple(case for case in opened if _group(case) in config.learning_group_ids)
    evaluation = tuple(case for case in opened if _group(case) in config.evaluation_group_ids)
    if len(learning) != 3 * len(config.learning_group_ids):
        raise ValueError("Outcome Learning update split is incomplete")
    if len(evaluation) != 3 * len(config.evaluation_group_ids):
        raise ValueError("Outcome Learning evaluation split is incomplete")
    if {item.study_id for item in learning} & {item.study_id for item in evaluation}:
        raise ValueError("Outcome Learning cases cross chronological boundary")

    no_update = _fit(historical, alpha=config.ridge_alpha)
    updated = _fit(historical + learning, alpha=config.ridge_alpha)
    shuffled_overrides = _shuffled_targets(learning)
    shuffled = _fit(
        historical + learning,
        alpha=config.ridge_alpha,
        target_overrides=shuffled_overrides,
    )

    decisions: list[dict[str, object]] = []
    effects_no_update: dict[str, list[float]] = defaultdict(list)
    effects_shuffled: dict[str, list[float]] = defaultdict(list)
    for case in sorted(evaluation, key=lambda item: item.study_id):
        actions = {
            "no_update": _select(no_update, case),
            "updated": _select(updated, case),
            "shuffled": _select(shuffled, case),
        }
        best = max(case.action_utility_estimates.values())
        regrets = {
            arm: best - case.action_utility_estimates[action_id]
            for arm, action_id in actions.items()
        }
        updated_vs_no_update = regrets["no_update"] - regrets["updated"]
        updated_vs_shuffled = regrets["shuffled"] - regrets["updated"]
        effects_no_update[case.task_cluster_id].append(updated_vs_no_update)
        effects_shuffled[case.task_cluster_id].append(updated_vs_shuffled)
        decisions.append(
            {
                "study_id": case.study_id,
                "task_cluster_id": case.task_cluster_id,
                "stage": _stage(case),
                "selected_actions": actions,
                "regrets": regrets,
                "updated_vs_no_update_regret_reduction": updated_vs_no_update,
                "updated_vs_shuffled_regret_reduction": updated_vs_shuffled,
                "target_outcomes_visible_at_inference": False,
            }
        )

    def mean(key: str) -> float:
        return math.fsum(float(item[key]) for item in decisions) / len(decisions)

    no_update_effects = [float(item["updated_vs_no_update_regret_reduction"]) for item in decisions]
    shuffled_effects = [float(item["updated_vs_shuffled_regret_reduction"]) for item in decisions]
    report: dict[str, object] = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "project_id": config.project_id,
        "analysis_scope": "opened-population-outcome-learning-development",
        "historical_case_count": len(historical),
        "learning_case_count": len(learning),
        "evaluation_case_count": len(evaluation),
        "learning_group_ids": config.learning_group_ids,
        "evaluation_group_ids": config.evaluation_group_ids,
        "mean_regret": {
            arm: math.fsum(float(item["regrets"][arm]) for item in decisions) / len(decisions)
            for arm in ("no_update", "updated", "shuffled")
        },
        "mean_updated_vs_no_update_regret_reduction": mean("updated_vs_no_update_regret_reduction"),
        "mean_updated_vs_shuffled_regret_reduction": mean("updated_vs_shuffled_regret_reduction"),
        "updated_vs_no_update_cluster_bootstrap_95_interval": _cluster_interval(
            effects_no_update,
            resamples=config.bootstrap_resamples,
            seed=config.bootstrap_seed,
        ),
        "updated_vs_shuffled_cluster_bootstrap_95_interval": _cluster_interval(
            effects_shuffled,
            resamples=config.bootstrap_resamples,
            seed=config.bootstrap_seed + 1,
        ),
        "updated_vs_no_update_comparison_counts": dict(
            sorted(
                Counter(
                    "win" if x > 0 else "loss" if x < 0 else "tie" for x in no_update_effects
                ).items()
            )
        ),
        "updated_vs_shuffled_comparison_counts": dict(
            sorted(
                Counter(
                    "win" if x > 0 else "loss" if x < 0 else "tie" for x in shuffled_effects
                ).items()
            )
        ),
        "policy_sha256": {
            "no_update": no_update.model_sha256,
            "updated": updated.model_sha256,
            "shuffled": shuffled.model_sha256,
        },
        "target_outcomes_visible_at_inference": False,
        "formal_evidence": config.formal_evidence,
        "effect_claim_authorized": config.effect_claim_authorized,
        "claim_boundary": config.claim_boundary,
    }
    report["report_sha256"] = content_sha256(report)
    _publish(args.output, config_raw, no_update, updated, shuffled, decisions, report)
    return report


def _publish(
    output: Path,
    config_raw: bytes,
    no_update: OutcomeCalibratedTasteModel,
    updated: OutcomeCalibratedTasteModel,
    shuffled: OutcomeCalibratedTasteModel,
    decisions: list[dict[str, object]],
    report: dict[str, object],
) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        (temporary / "PLAN.yaml").write_bytes(config_raw)
        for name, model in (
            ("NO_UPDATE_POLICY.json", no_update),
            ("UPDATED_POLICY.json", updated),
            ("SHUFFLED_POLICY.json", shuffled),
        ):
            (temporary / name).write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (temporary / "DECISIONS.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in decisions),
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
        f"study={report['study_id']} "
        f"updated-vs-no-update={report['mean_updated_vs_no_update_regret_reduction']:.6f} "
        f"updated-vs-shuffled={report['mean_updated_vs_shuffled_regret_reduction']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
