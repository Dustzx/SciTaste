#!/usr/bin/env python3
"""Compile a state-bound successor action from a real MLRC development pair."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scitaste.evaluation.task_patch_generation import BenchmarkResearchActionDirective
from scitaste.project.models import content_sha256


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("MLRC pair result must be a JSON object")
    observed = value.get("receipt_sha256")
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    if observed != content_sha256(unsigned):
        raise ValueError("MLRC pair result hash differs")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-development-effect", type=float, default=0.005)
    args = parser.parse_args()
    if args.minimum_development_effect <= 0:
        raise ValueError("minimum development effect must be positive")
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)

    pair_path = args.pair_result.resolve(strict=True)
    pair_bytes = pair_path.read_bytes()
    pair = _read(pair_path)
    if (
        pair.get("formal_evidence_eligible") is not False
        or pair.get("heldout_opened") is not False
        or pair.get("adaptive_development_pair") is not True
    ):
        raise ValueError("successor compilation accepts adaptive development evidence only")
    arms = pair.get("arms")
    if not isinstance(arms, dict):
        raise ValueError("MLRC pair arms are absent")
    on = arms.get("learned-policy-on")
    off = arms.get("learned-policy-off")
    if not isinstance(on, dict) or not isinstance(off, dict):
        raise ValueError("MLRC policy on/off arms are incomplete")
    effect = float(pair["paired_development_effect"])

    if abs(effect) < args.minimum_development_effect:
        action_id = "mlrc-analyze-inconclusive-policy-pair"
        action_type = "ANALYZE"
        instruction = (
            "Analyze why the two development arms are practically tied; do not change "
            "architecture, loss, data, schedule, or scorer until a discriminating "
            "task-grounded hypothesis is identified."
        )
        update = "abstain-and-analyze"
    elif effect < 0 and off.get("selected_action_type") == "PROBE":
        action_id = "mlrc-refine-supported-classification-probe"
        action_type = "REFINE"
        instruction = (
            "Refine only the classification-loss mechanism supported by the preceding "
            "development probe; preserve the architecture, data, schedule, scorer, and "
            "all unrelated source definitions."
        )
        update = "reverse-experiment-preference-and-refine-probe"
    elif effect > 0 and on.get("selected_action_type") == "EXPERIMENT":
        action_id = "mlrc-refine-supported-feature-pyramid"
        action_type = "REFINE"
        instruction = (
            "Refine only the feature-pyramid mechanism supported by the preceding "
            "development experiment; preserve losses, data, schedule, and scorer."
        )
        update = "retain-experiment-preference-and-refine"
    else:
        action_id = "mlrc-analyze-unmapped-policy-outcome"
        action_type = "ANALYZE"
        instruction = (
            "Analyze the observed policy-pair outcome before proposing another patch; "
            "do not repeat either action without a task-grounded explanation."
        )
        update = "abstain-on-unmapped-outcome"

    directive = BenchmarkResearchActionDirective.create(
        action_id=action_id,
        action_type=action_type,
        instruction=instruction,
    )
    args.output.mkdir(parents=True)
    (args.output / "DIRECTIVE.json").write_text(
        json.dumps(directive.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "1.0",
        "successor_id": "mlrc-perception-outcome-successor-development-v1",
        "evidence_role": "development-policy-update-only",
        "formal_evidence_eligible": False,
        "heldout_opened": False,
        "source_pair_file_sha256": hashlib.sha256(pair_bytes).hexdigest(),
        "source_pair_receipt_sha256": pair["receipt_sha256"],
        "task_id": pair["task_id"],
        "runtime_fingerprint": pair["runtime_fingerprint"],
        "development_view_sha256": pair["development_view_sha256"],
        "policy_on_action": on["selected_action_type"],
        "policy_on_score": on["score"],
        "policy_off_action": off["selected_action_type"],
        "policy_off_score": off["score"],
        "paired_development_effect": effect,
        "minimum_development_effect": args.minimum_development_effect,
        "update": update,
        "successor_action_type": action_type,
        "successor_directive_sha256": directive.directive_sha256,
        "task_bound_only": True,
        "cross_task_transfer_authorized": False,
        "no_model_call_performed": True,
        "no_gpu_work_performed": True,
        "interpretation_boundary": (
            "The successor is an adaptive development decision on the same MLRC task. "
            "It cannot enter formal evaluation, cross-task Taste memory, or the paper's "
            "confirmatory result tables without a new frozen population."
        ),
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    (args.output / "RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
