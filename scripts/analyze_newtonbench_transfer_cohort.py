#!/usr/bin/env python3
"""Aggregate a frozen directory of paired interactive NewtonBench receipts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

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


def analyze(root: Path) -> dict[str, object]:
    tasks: list[dict[str, object]] = []
    treatment_effects: list[float] = []
    total_cost = 0.0
    total_tokens = 0
    total_experiments = 0
    completed_arms = 0
    active_pairs = 0

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
        _write_exclusive(task_dir / "PAIRED_RESULT.json", paired_payload)

        native_exposure = _taste_exposure(native)
        base_exposure = _taste_exposure(base)
        behaviorally_active = bool(native_exposure["nonzero_adjustment_count"])
        active_pairs += behaviorally_active
        shared_turns = min(len(native.turns), len(base.turns))
        overlapping_actions_identical = (
            native_exposure["selected_actions"][:shared_turns]
            == base_exposure["selected_actions"][:shared_turns]
        )
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
        for receipt in (native, base):
            total_cost += receipt.api_cost_usd
            total_tokens += receipt.input_tokens + receipt.output_tokens
            total_experiments += receipt.experiment_count
            completed_arms += receipt.status == "completed"

    payload: dict[str, object] = {
        "schema_version": "1.0",
        "cohort_id": root.name,
        "evidence_tier": "development",
        "task_pair_count": len(tasks),
        "completed_arm_count": completed_arms,
        "behaviorally_active_pair_count": active_pairs,
        "manipulation_check_passed": active_pairs > 0,
        "intention_to_treat_mean_difference": sum(treatment_effects)
        / len(treatment_effects),
        "effect_interpretation_authorized": active_pairs > 0,
        "formal_effect_claim_allowed": False,
        "total_experiments": total_experiments,
        "total_tokens": total_tokens,
        "total_api_cost_usd": total_cost,
        "tasks": tasks,
        "scientific_conclusion": (
            "The source-disjoint cohort executed, but the frozen learned policy made "
            "no nonzero adjustment in any pair. Observed between-arm outcome differences "
            "therefore do not estimate a learned-Taste effect."
            if active_pairs == 0
            else "At least one pair passed the behavioral manipulation check; interpret "
            "the paired outcomes together with activation coverage."
        ),
    }
    payload["result_sha256"] = content_sha256(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = analyze(args.cohort_root)
    _write_exclusive(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
