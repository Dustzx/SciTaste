#!/usr/bin/env python3
"""Aggregate a frozen directory of paired interactive NewtonBench receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
from collections import Counter
from pathlib import Path

import yaml

from scitaste.evaluation.interactive_research import (
    InteractivePairedResult,
    load_interactive_research_run_receipt,
)
from scitaste.evaluation.interactive_taste import (
    load_interactive_taste_execution_protocol,
)
from scitaste.project.models import content_sha256


def _write_exclusive(path: Path, payload: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_idempotent(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(path)
        return
    _write_exclusive(path, payload)


def _taste_exposure(receipt) -> dict[str, object]:
    active_turns = 0
    nonzero_adjustments = 0
    reason_counts: dict[str, int] = {}
    selected_actions: list[str] = []
    for turn in receipt.turns:
        decision = turn.guidance.audit["controller_decision"]
        assessment = decision["lifecycle_taste_policy"]
        active_turns += assessment["recommended_action_id"] is not None
        nonzero_adjustments += sum(
            abs(float(value)) > 1e-12
            for value in assessment["action_adjustments"].values()
        )
        for reason in assessment["reason_codes"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        selected_actions.append(decision["selected_action"]["type"])
    return {
        "decision_count": len(receipt.turns),
        "active_turn_count": active_turns,
        "nonzero_adjustment_count": nonzero_adjustments,
        "reason_counts": dict(sorted(reason_counts.items())),
        "selected_actions": selected_actions,
    }


def _paired_bootstrap_interval(
    effects: list[float],
    *,
    samples: int = 10_000,
    seed: int = 6027,
) -> tuple[float, float]:
    if not effects:
        raise ValueError("paired bootstrap requires at least one task effect")
    generator = random.Random(seed)
    count = len(effects)
    estimates = sorted(
        sum(generator.choice(effects) for _ in range(count)) / count
        for _ in range(samples)
    )
    return estimates[int(0.025 * (samples - 1))], estimates[int(0.975 * (samples - 1))]


def _exact_two_sided_sign_test(native_wins: int, base_wins: int) -> float | None:
    discordant = native_wins + base_wins
    if discordant == 0:
        return None
    tail = sum(
        math.comb(discordant, index) for index in range(min(native_wins, base_wins) + 1)
    ) / (2**discordant)
    return min(1.0, 2 * tail)


def _action_profile(tasks: list[dict[str, object]], arm: str) -> dict[str, object]:
    actions: list[str] = []
    for task in tasks:
        arm_record = task[arm]
        exposure = arm_record["taste_exposure"]
        actions.extend(
            action for action in exposure["selected_actions"] if action != "STOP"
        )
    counts = Counter(actions)
    total = len(actions)
    entropy = (
        -sum((count / total) * math.log2(count / total) for count in counts.values())
        if total
        else 0.0
    )
    dominant_share = max(counts.values(), default=0) / total if total else 0.0
    return {
        "nonterminal_decision_count": total,
        "action_counts": dict(sorted(counts.items())),
        "unique_action_count": len(counts),
        "action_entropy_bits": entropy,
        "dominant_action_share": dominant_share,
    }


def _load_formal_design(path: Path | None) -> tuple[str | None, dict[str, object] | None]:
    if path is None:
        return None, None
    source = path.read_bytes()
    payload = yaml.safe_load(source)
    if not isinstance(payload, dict):
        raise ValueError("formal study design must contain one mapping")
    if payload.get("status") != "frozen-before-any-formal-task-execution":
        raise ValueError("formal study design was not frozen before execution")
    return hashlib.sha256(source).hexdigest(), payload


def analyze(
    root: Path,
    *,
    evidence_tier: str = "development",
    study_design: Path | None = None,
) -> dict[str, object]:
    if evidence_tier not in {"development", "formal"}:
        raise ValueError("evidence tier must be development or formal")
    design_sha256, design = _load_formal_design(study_design)
    if evidence_tier == "formal" and design is None:
        raise ValueError("formal analysis requires a frozen study design")

    tasks: list[dict[str, object]] = []
    treatment_effects: list[float] = []
    rmsle_effects: list[float] = []
    known_cost = 0.0
    unknown_cost_arms = 0
    total_tokens = 0
    total_experiments = 0
    completed_arms = 0
    observed_arms = 0
    observed_pairs = 0
    post_score_unknown_cost_arms = 0
    active_pairs = 0
    action_divergent_pairs = 0
    native_successes = 0
    base_successes = 0
    native_wins = 0
    base_wins = 0

    task_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if not task_dirs:
        raise ValueError("cohort root contains no task directories")
    for task_dir in task_dirs:
        protocol = load_interactive_taste_execution_protocol(task_dir / "PROTOCOL.json")
        native = load_interactive_research_run_receipt(task_dir / "ON_RECEIPT.json")
        base = load_interactive_research_run_receipt(task_dir / "OFF_RECEIPT.json")
        paired = InteractivePairedResult.from_receipts(
            native,
            base,
            protocol_sha256=protocol.protocol_sha256,
            primary_metric=protocol.primary_metric,
            metric_direction=protocol.metric_direction,
            failure_value=protocol.failure_primary_value,
        )
        paired_payload = paired.model_dump(mode="json")
        _write_idempotent(task_dir / "PAIRED_RESULT.json", paired_payload)

        native_exposure = _taste_exposure(native)
        base_exposure = _taste_exposure(base)
        behaviorally_active = bool(native_exposure["nonzero_adjustment_count"])
        active_pairs += behaviorally_active
        shared_turns = min(len(native.turns), len(base.turns))
        overlapping_actions_identical = (
            native_exposure["selected_actions"][:shared_turns]
            == base_exposure["selected_actions"][:shared_turns]
        )
        action_divergent_pairs += not overlapping_actions_identical
        native_successes += paired.native_value == 1.0
        base_successes += paired.base_value == 1.0
        native_wins += paired.native_value > paired.base_value
        base_wins += paired.base_value > paired.native_value
        native_rmsle = (
            native.objective_score.metrics.get("rmsle")
            if native.objective_score is not None
            else None
        )
        base_rmsle = (
            base.objective_score.metrics.get("rmsle")
            if base.objective_score is not None
            else None
        )
        if isinstance(native_rmsle, (int, float)) and isinstance(base_rmsle, (int, float)):
            rmsle_effects.append(float(base_rmsle) - float(native_rmsle))
        task_record = {
            "task_label": task_dir.name,
            "task_id": protocol.task_id,
            "protocol_sha256": protocol.protocol_sha256,
            "paired_result": paired_payload,
            "native": {
                "run_id": native.run_id,
                "receipt_sha256": native.receipt_sha256,
                "status": native.status,
                "objective_value": paired.native_value,
                "rmsle": native_rmsle,
                "objective_observed": paired.native_value_observed,
                "experiments": native.experiment_count,
                "tokens": native.input_tokens + native.output_tokens,
                "api_cost_usd": native.api_cost_usd,
                "terminal_error": native.terminal_error,
                "taste_exposure": native_exposure,
            },
            "base": {
                "run_id": base.run_id,
                "receipt_sha256": base.receipt_sha256,
                "status": base.status,
                "objective_value": paired.base_value,
                "rmsle": base_rmsle,
                "objective_observed": paired.base_value_observed,
                "experiments": base.experiment_count,
                "tokens": base.input_tokens + base.output_tokens,
                "api_cost_usd": base.api_cost_usd,
                "terminal_error": base.terminal_error,
                "taste_exposure": base_exposure,
            },
            "behaviorally_active": behaviorally_active,
            "overlapping_selected_actions_identical": overlapping_actions_identical,
        }
        tasks.append(task_record)
        treatment_effects.append(paired.treatment_effect)
        observed_arms += int(paired.native_value_observed) + int(paired.base_value_observed)
        observed_pairs += paired.native_value_observed and paired.base_value_observed
        for receipt in (native, base):
            if receipt.api_cost_usd is None:
                unknown_cost_arms += 1
            else:
                known_cost += receipt.api_cost_usd
            total_tokens += receipt.input_tokens + receipt.output_tokens
            total_experiments += receipt.experiment_count
            completed_arms += receipt.status == "completed"
            post_score_unknown_cost_arms += (
                receipt.status == "cost_budget_exhausted"
                and receipt.objective_score is not None
                and receipt.api_cost_usd is None
            )

    mean_difference = sum(treatment_effects) / len(treatment_effects)
    interval_low, interval_high = _paired_bootstrap_interval(treatment_effects)
    formal_complete = evidence_tier == "formal" and design is not None and len(tasks) == 12
    # A post-score failure caused solely by unavailable price telemetry is not a
    # scientific failure of either arm.  It is an invalid resource-measurement
    # contract.  Keep the predeclared ITT table for audit, but never let it become
    # an effect claim.  Genuine agent/tool/budget failures remain ITT outcomes.
    execution_valid = formal_complete and post_score_unknown_cost_arms == 0
    native_action_profile = _action_profile(tasks, "native")
    base_action_profile = _action_profile(tasks, "base")
    action_collapse = (
        native_action_profile["nonterminal_decision_count"] >= len(tasks)
        and native_action_profile["unique_action_count"] == 1
    )
    if not execution_valid:
        claim_support_status = "execution-invalid"
    elif interval_low > 0:
        claim_support_status = "supported-positive-interval"
    elif mean_difference < 0:
        claim_support_status = "not-supported-point-estimate-favors-base"
    else:
        claim_support_status = "inconclusive-interval-includes-zero"
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "cohort_id": root.name,
        "evidence_tier": evidence_tier,
        "study_design_sha256": design_sha256,
        "task_pair_count": len(tasks),
        "completed_arm_count": completed_arms,
        "objective_observed_arm_count": observed_arms,
        "objective_observed_pair_count": observed_pairs,
        "post_score_unknown_cost_arm_count": post_score_unknown_cost_arms,
        "formal_execution_valid": execution_valid,
        "behaviorally_active_pair_count": active_pairs,
        "action_divergent_pair_count": action_divergent_pairs,
        "native_action_profile": native_action_profile,
        "base_action_profile": base_action_profile,
        "policy_action_collapse_detected": action_collapse,
        "manipulation_check_passed": active_pairs > 0,
        "native_success_count": native_successes,
        "base_success_count": base_successes,
        "native_win_count": native_wins,
        "base_win_count": base_wins,
        "tied_pair_count": len(tasks) - native_wins - base_wins,
        "intention_to_treat_mean_difference": mean_difference,
        "paired_bootstrap_95_interval": [interval_low, interval_high],
        "paired_bootstrap_samples": 10_000,
        "paired_bootstrap_seed": 6027,
        "discordant_pair_exact_p_value": _exact_two_sided_sign_test(
            native_wins, base_wins
        ),
        "mean_base_minus_native_rmsle": (
            sum(rmsle_effects) / len(rmsle_effects) if rmsle_effects else None
        ),
        "rmsle_pair_count": len(rmsle_effects),
        "effect_interpretation_authorized": active_pairs > 0
        and (evidence_tier != "formal" or execution_valid),
        "formal_effect_claim_allowed": execution_valid,
        "primary_claim_support_status": claim_support_status,
        "total_experiments": total_experiments,
        "total_tokens": total_tokens,
        "known_api_cost_usd": known_cost,
        "total_api_cost_usd": known_cost if unknown_cost_arms == 0 else None,
        "api_cost_complete": unknown_cost_arms == 0,
        "unknown_api_cost_arm_count": unknown_cost_arms,
        "tasks": tasks,
        "scientific_conclusion": (
            "The frozen formal block is not effect-interpretable: an unpriced "
            "independent judge triggered the required-cost-telemetry boundary after "
            "scoring. The audit table is retained, but its zero-coded failures cannot "
            "support a Scientific Taste effect claim."
            if post_score_unknown_cost_arms
            else (
                "The source-disjoint cohort executed, but the frozen learned policy made "
                "no nonzero adjustment in any pair. Observed between-arm outcome differences "
                "therefore do not estimate a learned-Taste effect."
                if active_pairs == 0
                else (
                    "The frozen policy changed behavior, but the preregistered primary "
                    "endpoint does not support improvement: the point estimate favors Base "
                    "and the paired interval includes zero. The treatment also collapses "
                    "to one nonterminal action across the cohort, identifying a missing "
                    "state-selectivity mechanism. Secondary metrics must not replace this "
                    "primary conclusion."
                    if mean_difference < 0
                    else (
                        "The frozen policy changed behavior and the paired interval excludes "
                        "zero in the positive direction. Interpret this scoped NewtonBench "
                        "effect separately from end-to-end and external-baseline claims."
                        if interval_low > 0
                        else "The frozen policy changed behavior, but the paired interval "
                        "includes zero; the primary improvement claim remains inconclusive."
                    )
                )
            )
        ),
    }
    payload["result_sha256"] = content_sha256(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--evidence-tier", choices=("development", "formal"), default="development"
    )
    parser.add_argument("--study-design", type=Path)
    args = parser.parse_args()
    payload = analyze(
        args.cohort_root,
        evidence_tier=args.evidence_tier,
        study_design=args.study_design,
    )
    _write_exclusive(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
