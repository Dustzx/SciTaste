#!/usr/bin/env python3
"""Bind a learned lifecycle-policy decision to one task-specific MLRC directive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.h4_state_probe import load_h4_state_probe_report
from scitaste.evaluation.task_patch_generation import BenchmarkResearchActionDirective
from scitaste.project.models import content_sha256

_DEFAULT_REPORT = Path(
    "outputs/projects/scitaste-self-development/evaluations/taste-policy-activation/"
    "adaptive-allocation-state-diverse-v11/e2-successor-v19-v9/"
    "H4_STATE_PROBE_REPORT.json"
)

# This closed mapping is task-specific and common to both arms.  It makes the
# lifecycle choice operational without exposing policy scores to the code model.
_TASK_ACTIONS = {
    "PROBE": (
        "mlrc-probe-classification-loss",
        "Make the smallest diagnostic change to the classification loss only; do not alter "
        "the architecture, feature pyramid, data, schedule, or scorer.",
    ),
    "PILOT": (
        "mlrc-pilot-boundary-objective",
        "Run a bounded boundary-objective change only; keep architecture, data, schedule, and "
        "scorer fixed.",
    ),
    "EXPERIMENT": (
        "mlrc-experiment-feature-pyramid",
        "Test the strongest architecture hypothesis by enabling the existing feature pyramid; "
        "do not alter losses, data, schedule, or scorer.",
    ),
    "ANALYZE": (
        "mlrc-analyze-error-target",
        "Use the visible development error pattern to change one targeted source mechanism; "
        "keep architecture, data, schedule, and scorer fixed.",
    ),
    "REFINE": (
        "mlrc-refine-current-mechanism",
        "Refine only the current best mechanism without widening the architecture, data, "
        "schedule, or scorer.",
    ),
    "PIVOT": (
        "mlrc-pivot-mechanism",
        "Replace the current mechanism with one distinct bounded mechanism while keeping data, "
        "schedule, and scorer fixed.",
    ),
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--condition",
        choices=("learned-policy-on", "learned-policy-off"),
        required=True,
    )
    parser.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report_path = args.report.resolve(strict=True)
    report_bytes = report_path.read_bytes()
    report = load_h4_state_probe_report(report_path)
    if not report.passed:
        raise ValueError("lifecycle policy state-probe report did not pass")
    initial = next(item for item in report.observations if item.probe_id == "initial")
    arm = initial.on if args.condition == "learned-policy-on" else initial.off
    if arm.selected_action_type == "STOP":
        raise ValueError("initial MLRC development action cannot be STOP")
    action_id, instruction = _TASK_ACTIONS[arm.selected_action_type]
    directive = BenchmarkResearchActionDirective.create(
        action_id=action_id,
        action_type=arm.selected_action_type,
        instruction=instruction,
    )
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    directive_path = output / "DIRECTIVE.json"
    _write_json(directive_path, directive.model_dump(mode="json"))
    receipt = {
        "schema_version": "1.0",
        "condition": args.condition,
        "probe_id": initial.probe_id,
        "probe_sha256": initial.probe_sha256,
        "policy_report_file_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "policy_report_sha256": report.report_sha256,
        "policy_observation_sha256": arm.observation_sha256,
        "lifecycle_policy_weight": arm.lifecycle_policy_weight,
        "selected_action_type": arm.selected_action_type,
        "task_action_mapping_sha256": content_sha256(_TASK_ACTIONS),
        "directive_sha256": directive.directive_sha256,
        "no_model_call_performed": True,
        "no_gpu_work_performed": True,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    (output / "RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
