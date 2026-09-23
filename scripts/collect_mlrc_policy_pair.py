#!/usr/bin/env python3
"""Bind one adaptive MLRC policy-on/off development pair.

The receipt deliberately cannot become formal evidence.  It joins the policy
choice, model-proposed patch, bounded repair, and GPU objective so development
results do not survive only as unrelated output directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _verify_receipt(value: dict[str, Any], *, label: str) -> None:
    observed = value.get("receipt_sha256")
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    if observed != _content_sha256(unsigned):
        raise ValueError(f"{label} receipt hash differs")


def _score(result: dict[str, Any]) -> float:
    objective = result.get("objective")
    if not isinstance(objective, dict) or not isinstance(objective.get("score"), (int, float)):
        raise ValueError("successful MLRC result has no numeric objective")
    return float(objective["score"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--on-directive-receipt", type=Path, required=True)
    parser.add_argument("--off-directive-receipt", type=Path, required=True)
    parser.add_argument("--on-preparation-receipt", type=Path, required=True)
    parser.add_argument("--off-proposal", type=Path, required=True)
    parser.add_argument("--off-repair-receipt", type=Path, required=True)
    parser.add_argument("--on-result", type=Path, required=True)
    parser.add_argument("--off-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)

    paths = {
        "on_directive_receipt": args.on_directive_receipt.resolve(strict=True),
        "off_directive_receipt": args.off_directive_receipt.resolve(strict=True),
        "on_preparation_receipt": args.on_preparation_receipt.resolve(strict=True),
        "off_proposal": args.off_proposal.resolve(strict=True),
        "off_repair_receipt": args.off_repair_receipt.resolve(strict=True),
        "on_result": args.on_result.resolve(strict=True),
        "off_result": args.off_result.resolve(strict=True),
    }
    values = {name: _read(path) for name, path in paths.items()}
    for name in (
        "on_directive_receipt",
        "off_directive_receipt",
        "on_preparation_receipt",
        "off_repair_receipt",
        "on_result",
        "off_result",
    ):
        _verify_receipt(values[name], label=name)

    on_directive = values["on_directive_receipt"]
    off_directive = values["off_directive_receipt"]
    on_preparation = values["on_preparation_receipt"]
    off_proposal = values["off_proposal"]
    off_repair = values["off_repair_receipt"]
    on_result = values["on_result"]
    off_result = values["off_result"]
    if (
        on_directive.get("condition"),
        off_directive.get("condition"),
        on_result.get("condition"),
        off_result.get("condition"),
    ) != (
        "learned-policy-on",
        "learned-policy-off",
        "learned-policy-on",
        "learned-policy-off",
    ):
        raise ValueError("MLRC pair conditions differ from the policy on/off contract")
    if (
        on_directive.get("lifecycle_policy_weight"),
        off_directive.get("lifecycle_policy_weight"),
    ) != (1, 0):
        raise ValueError("MLRC pair does not bind policy weights one and zero")
    if on_directive.get("task_action_mapping_sha256") != off_directive.get(
        "task_action_mapping_sha256"
    ):
        raise ValueError("MLRC pair used different task-action maps")
    if on_directive.get("selected_action_type") == off_directive.get(
        "selected_action_type"
    ):
        raise ValueError("MLRC development pair collapsed to the same lifecycle action")
    if on_preparation.get("research_action_directive_sha256") != on_directive.get(
        "directive_sha256"
    ):
        raise ValueError("policy-on preparation differs from its lifecycle directive")
    if off_repair.get("proposal_sha256") != off_proposal.get("fingerprint"):
        raise ValueError("policy-off repair differs from its model proposal")
    for result in (on_result, off_result):
        if (
            result.get("status") != "succeeded"
            or result.get("formal_evidence_eligible") is not False
            or result.get("heldout_opened") is not False
        ):
            raise ValueError("MLRC pair requires successful development-only closed-heldout runs")
    shared_fields = (
        "manifest_sha256",
        "runtime_fingerprint",
        "repository_commit",
        "development_view_sha256",
    )
    for field in shared_fields:
        if on_result.get(field) != off_result.get(field):
            raise ValueError(f"MLRC pair differs on {field}")

    on_score = _score(on_result)
    off_score = _score(off_result)
    delta = on_score - off_score
    receipt = {
        "schema_version": "1.0",
        "study_id": "mlrc-perception-adaptive-policy-pair-development-v1",
        "task_id": "perception-temporal-action-loc",
        "evidence_role": "consumed-development-only",
        "formal_evidence_eligible": False,
        "adaptive_development_pair": True,
        "heldout_opened": False,
        "repository_commit": on_result["repository_commit"],
        "runtime_fingerprint": on_result["runtime_fingerprint"],
        "development_view_sha256": on_result["development_view_sha256"],
        "task_action_mapping_sha256": on_directive["task_action_mapping_sha256"],
        "arms": {
            "learned-policy-on": {
                "lifecycle_policy_weight": 1,
                "selected_action_type": on_directive["selected_action_type"],
                "directive_sha256": on_directive["directive_sha256"],
                "proposal_sha256": on_preparation["proposal_sha256"],
                "edited_paths": on_preparation["edited_paths"],
                "source_manifest_sha256": on_result["source_manifest_sha256"],
                "score": on_score,
                "wall_seconds": on_result["wall_seconds"],
                "repair_applied": False,
            },
            "learned-policy-off": {
                "lifecycle_policy_weight": 0,
                "selected_action_type": off_directive["selected_action_type"],
                "directive_sha256": off_directive["directive_sha256"],
                "proposal_sha256": off_proposal["fingerprint"],
                "edited_paths": [item["path"] for item in off_proposal["edits"]],
                "source_manifest_sha256": off_result["source_manifest_sha256"],
                "score": off_score,
                "wall_seconds": off_result["wall_seconds"],
                "repair_applied": True,
                "repair_kind": off_repair["repair_kind"],
            },
        },
        "paired_development_effect": delta,
        "development_preference": (
            "learned-policy-on"
            if delta > 0
            else "learned-policy-off"
            if delta < 0
            else "tie"
        ),
        "interpretation_boundary": (
            "This adaptive one-task development pair compares the executed consequences "
            "of two lifecycle-directed model proposals. It does not estimate a formal "
            "Taste effect, system superiority, or held-out generalization."
        ),
        "artifact_retention": {
            "compact_results_copied_to_project": True,
            "development_predictions_copied_to_project": True,
            "training_checkpoints_retained_on_execution_host": True,
            "training_checkpoints_copied_to_project": False,
            "checkpoint_manifests_bound_by_result_receipts": True,
        },
        "artifacts": {
            name: {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for name, path in paths.items()
        },
    }
    receipt["receipt_sha256"] = _content_sha256(receipt)
    args.output.mkdir(parents=True)
    (args.output / "PAIR_RESULT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
