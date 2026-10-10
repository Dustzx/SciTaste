#!/usr/bin/env python3
"""Read-only integrity audit for a completed ResearchClawBench formal cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

PAIR_PARITY_FIELDS = (
    "benchmark",
    "benchmark_commit",
    "task_id",
    "visible_task_sha256",
    "model",
    "api_base",
    "api_key_env",
    "extra_body",
    "tools",
    "max_retries",
    "max_rounds",
    "max_runtime_seconds",
    "max_input_tokens",
    "max_output_tokens",
    "compact_trigger_tokens",
    "seed",
    "upstream_role_prompt_sha256",
    "target_study_visible_to_agent",
)
SCORING_PARITY_FIELDS = (
    "enabled",
    "judge_api_base",
    "judge_api_key_env",
    "judge_model",
    "status",
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    protocol_path = args.protocol.resolve(strict=True)
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a YAML mapping")
    root = args.study_root.resolve(strict=True)
    failures: list[str] = []
    task_reports: list[dict[str, Any]] = []

    expected_agent = protocol["agent"]
    expected_judge = protocol["judge"]
    expected_overlay = protocol["taste_control"]["receipt_requirements"]
    for registered in protocol["population"]["tasks"]:
        task_id = registered["task_id"]
        receipts: dict[str, dict[str, Any]] = {}
        arm_report: dict[str, Any] = {}
        overlay_dir = root / task_id / "taste-overlay"
        overlay_path = overlay_dir / "TASTE_CONTROL_OVERLAY.md"
        overlay_receipt_path = overlay_dir / "RECEIPT.json"
        overlay_receipt = _json(overlay_receipt_path)
        overlay_sha = _sha256(overlay_path)
        overlay_checks = {
            "task_id": overlay_receipt.get("task_id") == task_id,
            "file_hash": overlay_receipt.get("overlay_file_sha256") == overlay_sha,
            "byte_count": overlay_receipt.get("overlay_bytes") == overlay_path.stat().st_size,
            "byte_ceiling": overlay_path.stat().st_size
            <= int(expected_overlay["maximum_overlay_bytes"]),
            "treatment": overlay_receipt.get("treatment") == expected_overlay["treatment"],
            "render_format": overlay_receipt.get("render_format")
            == expected_overlay["render_format"],
            "principle_limit": overlay_receipt.get("mechanism_claim_count", 10**9)
            <= int(expected_overlay["maximum_mechanism_claims"]),
            "action_limit": overlay_receipt.get("conditional_action_count", 10**9)
            <= int(expected_overlay["maximum_conditional_actions"]),
            "no_unconditional_action": overlay_receipt.get(
                "unconditional_recommended_action_present"
            )
            is False,
            "native_fallback": overlay_receipt.get("native_fallback_required_when_abstaining")
            is True,
        }
        for name, passed in overlay_checks.items():
            _check(passed, f"{task_id}:overlay:{name}", failures)

        for condition in ("native-base", "full-scitaste"):
            arm_dir = root / task_id / condition
            receipt_path = arm_dir / "SCITASTE_SYSTEM_RUN_RECEIPT.json"
            score_path = arm_dir / "_score.json"
            _check(receipt_path.is_file(), f"{task_id}:{condition}:receipt-missing", failures)
            _check(score_path.is_file(), f"{task_id}:{condition}:score-missing", failures)
            if not receipt_path.is_file() or not score_path.is_file():
                continue
            receipt = _json(receipt_path)
            score = _json(score_path)
            receipts[condition] = receipt
            checks = {
                "completed": receipt.get("status") == "completed",
                "condition": receipt.get("condition") == condition,
                "task_id": receipt.get("task_id") == task_id,
                "task_hash": receipt.get("visible_task_sha256") == registered["visible_sha256"],
                "benchmark_commit": receipt.get("benchmark_commit")
                == protocol["benchmark"]["commit"],
                "model": receipt.get("model") == expected_agent["model"],
                "api_base": receipt.get("api_base") == expected_agent["api_base"],
                "target_hidden": receipt.get("target_study_visible_to_agent") is False,
                "score_hash": receipt.get("scoring", {}).get("score_sha256") == _sha256(score_path),
                "score_completed": receipt.get("scoring", {}).get("status") == "completed",
                "judge_model": receipt.get("scoring", {}).get("judge_model")
                == expected_judge["model"],
                "judge_api_base": receipt.get("scoring", {}).get("judge_api_base")
                == expected_judge["api_base"],
                "numeric_score": isinstance(score.get("total_score"), (int, float)),
                "treatment_hash": (
                    receipt.get("taste_overlay_sha256") == overlay_sha
                    if condition == "full-scitaste"
                    else receipt.get("taste_overlay_sha256") is None
                ),
            }
            for name, passed in checks.items():
                _check(passed, f"{task_id}:{condition}:{name}", failures)
            arm_report[condition] = {
                "checks": checks,
                "receipt_sha256": _sha256(receipt_path),
                "score_sha256": _sha256(score_path),
            }

        pair_checks: dict[str, bool] = {}
        if len(receipts) == 2:
            base = receipts["native-base"]
            full = receipts["full-scitaste"]
            pair_checks.update(
                {field: base.get(field) == full.get(field) for field in PAIR_PARITY_FIELDS}
            )
            pair_checks.update(
                {
                    f"scoring.{field}": base.get("scoring", {}).get(field)
                    == full.get("scoring", {}).get(field)
                    for field in SCORING_PARITY_FIELDS
                }
            )
        else:
            pair_checks["both_receipts_present"] = False
        for name, passed in pair_checks.items():
            _check(passed, f"{task_id}:pair:{name}", failures)
        task_reports.append(
            {
                "task_id": task_id,
                "overlay_checks": overlay_checks,
                "arms": arm_report,
                "pair_checks": pair_checks,
            }
        )

    resume_report: dict[str, Any] | None = None
    if "resume" in protocol:
        manifest_path = root / "RESUME_MANIFEST.json"
        manifest = _json(manifest_path)
        configured = {
            (item["task_id"], item["condition"]): item for item in protocol["resume"]["valid_arms"]
        }
        manifested = {
            (item["task_id"], item["condition"]): item for item in manifest["reused_arms"]
        }
        _check(configured.keys() == manifested.keys(), "resume:arm-set", failures)
        reuse_checks: list[dict[str, Any]] = []
        for identity, expected in configured.items():
            task_id, condition = identity
            arm_dir = root / task_id / condition
            observed = manifested.get(identity, {})
            checks = {
                "directory_is_symlink": arm_dir.is_symlink(),
                "manifest_receipt_hash": observed.get("receipt_sha256")
                == expected["receipt_sha256"],
                "manifest_score_hash": observed.get("score_sha256") == expected["score_sha256"],
                "file_receipt_hash": _sha256(arm_dir / "SCITASTE_SYSTEM_RUN_RECEIPT.json")
                == expected["receipt_sha256"],
                "file_score_hash": _sha256(arm_dir / "_score.json") == expected["score_sha256"],
            }
            for name, passed in checks.items():
                _check(passed, f"resume:{task_id}:{condition}:{name}", failures)
            reuse_checks.append({"task_id": task_id, "condition": condition, "checks": checks})
        resume_report = {
            "manifest_sha256": _sha256(manifest_path),
            "reused_arm_count": len(reuse_checks),
            "checks": reuse_checks,
        }

    result = {
        "schema_version": "1.0",
        "study_id": protocol["study_id"],
        "protocol_sha256": _sha256(protocol_path),
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "task_count": len(task_reports),
        "tasks": task_reports,
        "resume": resume_report,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(output)}, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
