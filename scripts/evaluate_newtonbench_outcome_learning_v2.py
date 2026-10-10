#!/usr/bin/env python3
"""Evaluate conservative residual Outcome Learning on an opened population.

Version 2 leaves the registered v1 evaluator untouched.  It treats the
historical policy as the default, learns only the utility residual revealed by
newly reviewed outcomes, and permits an override only when leave-one-task-
group-out models agree and their lower predicted advantage clears a frozen
margin.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from evaluate_newtonbench_outcome_learning import (
    FileBinding,
    OutcomeLearningConfig,
    _bound,
    _bytes,
    _cluster_interval,
    _fit,
    _group,
    _load_cases,
    _select,
    _shuffled_targets,
    _stage,
)
from pydantic import Field
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge

from scitaste.evaluation.outcome_calibrated_taste import (
    OutcomeCalibratedTasteModel,
    grounded_situation_axis_action_features,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256


class ResidualOutcomeLearningConfig(OutcomeLearningConfig):
    """Closed development configuration for the residual committee."""

    schema_version: Literal["2.0"] = "2.0"
    historical_sources: tuple[FileBinding, ...] = Field(min_length=1)
    model_family: Literal["residual-jackknife-outcome-learning-v2"]
    residual_ridge_alpha: float = Field(gt=0.0, allow_inf_nan=False)
    minimum_committee_agreement: float = Field(ge=0.5, le=1.0)
    minimum_predicted_advantage: float = Field(ge=0.0, allow_inf_nan=False)


class _ResidualModel:
    def __init__(
        self,
        vectorizer: DictVectorizer,
        fitted: Ridge,
        source_groups: tuple[str, ...],
        target_sha256: str,
    ) -> None:
        self.vectorizer = vectorizer
        self.fitted = fitted
        self.source_groups = source_groups
        self.target_sha256 = target_sha256

    def score(self, case: FormalObjectiveForkSituationCase, action_id: str) -> float:
        row = grounded_situation_axis_action_features(case.situation, action_id)
        return float(self.fitted.predict(self.vectorizer.transform([row]))[0])

    def record(self) -> dict[str, object]:
        return {
            "source_groups": self.source_groups,
            "target_sha256": self.target_sha256,
            "feature_names": tuple(str(item) for item in self.vectorizer.get_feature_names_out()),
            "coefficients": tuple(float(item) for item in self.fitted.coef_),
            "intercept": float(self.fitted.intercept_),
        }


def _fit_residual(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    *,
    base: OutcomeCalibratedTasteModel,
    alpha: float,
    target_overrides: dict[tuple[str, str], float] | None = None,
) -> _ResidualModel:
    rows: list[dict[str, float]] = []
    targets: list[float] = []
    target_record: list[dict[str, object]] = []
    for case in sorted(cases, key=lambda item: item.study_id):
        case_targets: dict[str, float] = {}
        for action_id in case.available_actions:
            observed = (target_overrides or {}).get(
                (case.study_id, action_id), case.action_utility_estimates[action_id]
            )
            residual = observed - base.score(case.situation, action_id)
            rows.append(grounded_situation_axis_action_features(case.situation, action_id))
            targets.append(residual)
            case_targets[action_id] = residual
        target_record.append(
            {
                "study_id": case.study_id,
                "result_sha256": case.result_sha256,
                "residual_targets": case_targets,
            }
        )
    vectorizer = DictVectorizer(sparse=True, sort=True)
    design = vectorizer.fit_transform(rows)
    fitted = Ridge(alpha=alpha).fit(design, np.asarray(targets, dtype=float))
    return _ResidualModel(
        vectorizer,
        fitted,
        tuple(sorted({_group(case) for case in cases})),
        content_sha256(target_record),
    )


def _committee(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    *,
    base: OutcomeCalibratedTasteModel,
    alpha: float,
    target_overrides: dict[tuple[str, str], float] | None = None,
) -> tuple[_ResidualModel, ...]:
    groups = tuple(sorted({_group(case) for case in cases}))
    if len(groups) < 3:
        raise ValueError("residual committee requires at least three learning groups")
    return tuple(
        _fit_residual(
            tuple(case for case in cases if _group(case) != held_out),
            base=base,
            alpha=alpha,
            target_overrides=target_overrides,
        )
        for held_out in groups
    )


def _conservative_select(
    base: OutcomeCalibratedTasteModel,
    committee: tuple[_ResidualModel, ...],
    case: FormalObjectiveForkSituationCase,
    *,
    minimum_agreement: float,
    minimum_advantage: float,
) -> tuple[str, dict[str, object]]:
    base_action = _select(base, case)
    member_actions: list[str] = []
    member_advantages: list[float] = []
    for model in committee:
        scores = {
            action_id: base.score(case.situation, action_id) + model.score(case, action_id)
            for action_id in case.available_actions
        }
        candidate = max(scores, key=lambda action_id: (scores[action_id], action_id))
        member_actions.append(candidate)
        member_advantages.append(scores[candidate] - scores[base_action])
    counts = Counter(member_actions)
    candidate, votes = max(counts.items(), key=lambda item: (item[1], item[0]))
    agreeing_advantages = [
        advantage
        for action_id, advantage in zip(member_actions, member_advantages, strict=True)
        if action_id == candidate
    ]
    agreement = votes / len(committee)
    lower_advantage = min(agreeing_advantages)
    override = (
        candidate != base_action
        and agreement >= minimum_agreement
        and lower_advantage >= minimum_advantage
    )
    return (
        candidate if override else base_action,
        {
            "base_action": base_action,
            "candidate_action": candidate,
            "member_actions": member_actions,
            "agreement": agreement,
            "lower_predicted_advantage": lower_advantage,
            "override": override,
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def execute(args: argparse.Namespace) -> dict[str, object]:
    root = args.workspace_root.resolve(strict=True)
    config_raw = _bytes(args.config.resolve(strict=True))
    config = ResidualOutcomeLearningConfig.model_validate(yaml.safe_load(config_raw))
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

    base = _fit(historical, alpha=config.ridge_alpha)
    updated = _committee(learning, base=base, alpha=config.residual_ridge_alpha)
    shuffled = _committee(
        learning,
        base=base,
        alpha=config.residual_ridge_alpha,
        target_overrides=_shuffled_targets(learning),
    )

    decisions: list[dict[str, object]] = []
    effects_no_update: dict[str, list[float]] = defaultdict(list)
    effects_shuffled: dict[str, list[float]] = defaultdict(list)
    for case in sorted(evaluation, key=lambda item: item.study_id):
        no_update_action = _select(base, case)
        updated_action, updated_gate = _conservative_select(
            base,
            updated,
            case,
            minimum_agreement=config.minimum_committee_agreement,
            minimum_advantage=config.minimum_predicted_advantage,
        )
        shuffled_action, shuffled_gate = _conservative_select(
            base,
            shuffled,
            case,
            minimum_agreement=config.minimum_committee_agreement,
            minimum_advantage=config.minimum_predicted_advantage,
        )
        actions = {
            "no_update": no_update_action,
            "updated": updated_action,
            "shuffled": shuffled_action,
        }
        best = max(case.action_utility_estimates.values())
        regrets = {
            arm: best - case.action_utility_estimates[action_id]
            for arm, action_id in actions.items()
        }
        effect_no_update = regrets["no_update"] - regrets["updated"]
        effect_shuffled = regrets["shuffled"] - regrets["updated"]
        effects_no_update[case.task_cluster_id].append(effect_no_update)
        effects_shuffled[case.task_cluster_id].append(effect_shuffled)
        decisions.append(
            {
                "study_id": case.study_id,
                "task_cluster_id": case.task_cluster_id,
                "stage": _stage(case),
                "selected_actions": actions,
                "regrets": regrets,
                "updated_gate": updated_gate,
                "shuffled_gate": shuffled_gate,
                "updated_vs_no_update_regret_reduction": effect_no_update,
                "updated_vs_shuffled_regret_reduction": effect_shuffled,
                "target_outcomes_visible_at_inference": False,
            }
        )

    def mean(key: str) -> float:
        return math.fsum(float(item[key]) for item in decisions) / len(decisions)

    no_update_effects = [float(item["updated_vs_no_update_regret_reduction"]) for item in decisions]
    shuffled_effects = [float(item["updated_vs_shuffled_regret_reduction"]) for item in decisions]
    report: dict[str, object] = {
        "schema_version": "2.0",
        "study_id": config.study_id,
        "project_id": config.project_id,
        "analysis_scope": "opened-population-outcome-learning-development",
        "mechanism": "base-plus-residual-jackknife-conservative-override",
        "historical_case_count": len(historical),
        "learning_case_count": len(learning),
        "evaluation_case_count": len(evaluation),
        "learning_group_ids": config.learning_group_ids,
        "evaluation_group_ids": config.evaluation_group_ids,
        "minimum_committee_agreement": config.minimum_committee_agreement,
        "minimum_predicted_advantage": config.minimum_predicted_advantage,
        "updated_override_count": sum(bool(item["updated_gate"]["override"]) for item in decisions),
        "shuffled_override_count": sum(
            bool(item["shuffled_gate"]["override"]) for item in decisions
        ),
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
        "base_policy_sha256": base.model_sha256,
        "updated_committee_sha256": content_sha256([item.record() for item in updated]),
        "shuffled_committee_sha256": content_sha256([item.record() for item in shuffled]),
        "target_outcomes_visible_at_inference": False,
        "formal_evidence": config.formal_evidence,
        "effect_claim_authorized": config.effect_claim_authorized,
        "claim_boundary": config.claim_boundary,
    }
    report["report_sha256"] = content_sha256(report)
    _publish(args.output, config_raw, base, updated, shuffled, decisions, report)
    return report


def _publish(
    output: Path,
    config_raw: bytes,
    base: OutcomeCalibratedTasteModel,
    updated: tuple[_ResidualModel, ...],
    shuffled: tuple[_ResidualModel, ...],
    decisions: list[dict[str, object]],
    report: dict[str, object],
) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        (temporary / "PLAN.yaml").write_bytes(config_raw)
        (temporary / "BASE_POLICY.json").write_text(
            base.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        for name, committee in (("UPDATED", updated), ("SHUFFLED", shuffled)):
            (temporary / f"{name}_COMMITTEE.json").write_text(
                json.dumps([item.record() for item in committee], indent=2) + "\n",
                encoding="utf-8",
            )
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
        f"overrides={report['updated_override_count']} "
        f"updated-vs-no-update="
        f"{report['mean_updated_vs_no_update_regret_reduction']:.6f} "
        f"updated-vs-shuffled="
        f"{report['mean_updated_vs_shuffled_regret_reduction']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
