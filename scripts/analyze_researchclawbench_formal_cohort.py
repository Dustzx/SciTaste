#!/usr/bin/env python3
"""Analyze the preregistered multi-domain ResearchClawBench system cohort.

The task, model, and execution units come from a frozen YAML protocol.  Missing
agent reports are retained as failed runs with the registered failure score;
missing judge output for a completed report blocks formal completion rather
than being silently imputed.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import statistics
from pathlib import Path
from typing import Any

import yaml

PARITY_KEYS = (
    "benchmark",
    "benchmark_commit",
    "task_id",
    "visible_task_sha256",
    "model",
    "api_base",
    "tools",
    "max_rounds",
    "max_runtime_seconds",
    "max_input_tokens",
    "max_output_tokens",
    "seed",
    "upstream_role_prompt_sha256",
    "target_study_visible_to_agent",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot compute a percentile over no values")
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _bootstrap_interval(
    deltas: list[float], *, resamples: int, seed: int, alpha: float
) -> tuple[float, float]:
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(deltas, k=len(deltas))) for _ in range(resamples)]
    return _percentile(means, alpha / 2.0), _percentile(means, 1.0 - alpha / 2.0)


def _exact_sign_flip_p(deltas: list[float]) -> float:
    observed = abs(statistics.fmean(deltas))
    extreme = 0
    total = 0
    for signs in itertools.product((-1.0, 1.0), repeat=len(deltas)):
        value = abs(
            statistics.fmean(sign * delta for sign, delta in zip(signs, deltas, strict=True))
        )
        extreme += value >= observed - 1e-12
        total += 1
    return extreme / total


def _load_arm(
    workspace: Path, failure_score: float, *, score_workspace: Path | None = None
) -> dict[str, Any]:
    receipt_path = workspace / "SCITASTE_SYSTEM_RUN_RECEIPT.json"
    if not receipt_path.is_file():
        return {"present": False, "workspace": str(workspace)}
    receipt = _read_json(receipt_path)
    status = str(receipt.get("status", "unknown"))
    score_root = score_workspace or workspace
    score_path = score_root / "_score.json"
    scoring_receipt_path = score_root / "SCORING_RECEIPT.json"
    if status == "completed" and not score_path.is_file():
        score = None
        score_status = "completed-report-missing-judge-score"
    elif status == "completed":
        score_record = _read_json(score_path)
        total = score_record.get("total_score")
        items = score_record.get("items")
        invalid_items = (
            not isinstance(items, list)
            or not items
            or any(
                not isinstance(item, dict)
                or str(item.get("reasoning", "")).strip()
                in {"Failed to parse scoring response.", "Scoring failed.", ""}
                for item in items
            )
        )
        scoring_receipt = (
            _read_json(scoring_receipt_path) if scoring_receipt_path.is_file() else None
        )
        invalid_receipt = score_workspace is not None and (
            scoring_receipt is None
            or scoring_receipt.get("status") != "completed"
            or scoring_receipt.get("source_receipt_sha256") != _sha256_file(receipt_path)
        )
        score = (
            float(total)
            if isinstance(total, (int, float)) and not invalid_items and not invalid_receipt
            else None
        )
        score_status = "scored" if score is not None else "invalid-judge-score"
    else:
        score = failure_score
        score_status = "registered-agent-failure"
    return {
        "present": True,
        "workspace": str(workspace),
        "status": status,
        "score_status": score_status,
        "score": score,
        "receipt": receipt,
        "receipt_sha256": _sha256_file(receipt_path),
        "score_sha256": _sha256_file(score_path) if score_path.is_file() else None,
        "scoring_receipt": (
            _read_json(scoring_receipt_path) if scoring_receipt_path.is_file() else None
        ),
    }


def _parity(base: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    if not base.get("present") or not full.get("present"):
        return {"all_matched": False, "checks": {}, "reason": "arm-missing"}
    checks = {key: base["receipt"].get(key) == full["receipt"].get(key) for key in PARITY_KEYS}
    return {"all_matched": all(checks.values()), "checks": checks}


def _markdown(result: dict[str, Any]) -> str:
    analysis = result["analysis"]
    lines = [
        "# ResearchClawBench multi-domain SciTaste system comparison",
        "",
        f"Status: **{result['status']}**. This report uses tasks, not repeated seeds, "
        "as the independent unit.",
        "",
        "| task | domain | Native Base | Full SciTaste | paired delta | parity |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in result["tasks"]:
        base_score = item["arms"]["native-base"].get("score")
        full_score = item["arms"]["full-scitaste"].get("score")
        delta = item.get("paired_delta")
        lines.append(
            f"| {item['task_id']} | {item['domain']} | "
            f"{base_score if base_score is not None else 'missing'} | "
            f"{full_score if full_score is not None else 'missing'} | "
            f"{f'{delta:+.3f}' if delta is not None else 'missing'} | "
            f"{'yes' if item['parity']['all_matched'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Registered primary analysis",
            "",
            f"- Complete paired tasks: {analysis['complete_pair_count']} / "
            f"{analysis['required_task_count']}",
            f"- Mean Full minus Base: {analysis.get('mean_paired_delta')}",
            f"- 95% task-bootstrap interval: {analysis.get('bootstrap_interval_95')}",
            f"- Exact two-sided sign-flip p-value: {analysis.get('exact_sign_flip_p')}",
            f"- Full/Base/tie task counts: {analysis.get('full_wins')} / "
            f"{analysis.get('base_wins')} / {analysis.get('ties')}",
            f"- Positive complete-system claim authorized: "
            f"{str(result['claim_authorized']).lower()}",
            "",
            "Failed or timed-out agents receive the preregistered failure score. A "
            "completed report without a judge score blocks the aggregate instead of being "
            "imputed. Costs and latency are reported separately from scientific quality.",
            "",
            "## Provenance",
            "",
            f"- Protocol SHA-256: `{result['protocol_sha256']}`",
            f"- Benchmark commit: `{result['benchmark_commit']}`",
            f"- Population rule: {result['population_selection_rule']}",
            "- `perceptual-visual-relexing` was not executed in this study and RRMOT was "
            "outside the experiment scope.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--score-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()

    protocol_path = args.protocol.resolve(strict=True)
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a YAML mapping")
    study_root = args.study_root.resolve(strict=True)
    score_root = args.score_root.resolve(strict=True) if args.score_root else None
    output_root = (args.output_root or study_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    tasks: list[dict[str, Any]] = []
    deltas: list[float] = []
    failure_score = float(protocol["execution"]["failure_score"])
    expected_model = protocol["agent"]["model"]
    expected_commit = protocol["benchmark"]["commit"]
    for registered in protocol["population"]["tasks"]:
        task_id = registered["task_id"]
        arms = {
            condition: _load_arm(
                study_root / task_id / condition,
                failure_score,
                score_workspace=(
                    score_root / task_id / condition if score_root is not None else None
                ),
            )
            for condition in ("native-base", "full-scitaste")
        }
        parity = _parity(arms["native-base"], arms["full-scitaste"])
        registration_checks = {}
        for condition, arm in arms.items():
            receipt = arm.get("receipt", {})
            registration_checks[condition] = {
                "task_hash": receipt.get("visible_task_sha256") == registered["visible_sha256"],
                "task_id": receipt.get("task_id") == task_id,
                "benchmark_commit": receipt.get("benchmark_commit") == expected_commit,
                "model": receipt.get("model") == expected_model,
                "target_hidden": receipt.get("target_study_visible_to_agent") is False,
            }
        scores = [arms[name].get("score") for name in ("native-base", "full-scitaste")]
        complete = (
            parity["all_matched"]
            and all(all(checks.values()) for checks in registration_checks.values())
            and all(score is not None for score in scores)
        )
        delta = float(scores[1] - scores[0]) if complete else None
        if delta is not None:
            deltas.append(delta)
        tasks.append(
            {
                "task_id": task_id,
                "domain": registered["domain"],
                "registered_visible_sha256": registered["visible_sha256"],
                "arms": arms,
                "parity": parity,
                "registration_checks": registration_checks,
                "complete": complete,
                "paired_delta": delta,
            }
        )

    required = int(protocol["population"]["required_task_count"])
    result_complete = len(deltas) == required == len(tasks)
    analysis: dict[str, Any] = {
        "primary_endpoint": protocol["analysis"]["primary_endpoint"],
        "required_task_count": required,
        "complete_pair_count": len(deltas),
    }
    claim_authorized = False
    if deltas:
        alpha = 1.0 - float(protocol["analysis"]["confidence_level"])
        interval = _bootstrap_interval(
            deltas,
            resamples=int(protocol["analysis"]["bootstrap_resamples"]),
            seed=int(protocol["analysis"]["bootstrap_seed"]),
            alpha=alpha,
        )
        full_wins = sum(delta > 0 for delta in deltas)
        base_wins = sum(delta < 0 for delta in deltas)
        ties = sum(delta == 0 for delta in deltas)
        mean_delta = statistics.fmean(deltas)
        win_rate = full_wins / len(deltas)
        analysis.update(
            {
                "mean_paired_delta": round(mean_delta, 6),
                "median_paired_delta": round(statistics.median(deltas), 6),
                "bootstrap_interval_95": [round(value, 6) for value in interval],
                "exact_sign_flip_p": round(_exact_sign_flip_p(deltas), 8),
                "full_wins": full_wins,
                "base_wins": base_wins,
                "ties": ties,
                "full_win_rate": round(win_rate, 6),
            }
        )
        claim_authorized = (
            result_complete
            and mean_delta >= float(protocol["analysis"]["minimum_claim_effect_points"])
            and interval[0] > 0
            and win_rate >= float(protocol["analysis"]["minimum_claim_win_rate"])
        )
    else:
        analysis.update(
            {
                "mean_paired_delta": None,
                "median_paired_delta": None,
                "bootstrap_interval_95": None,
                "exact_sign_flip_p": None,
                "full_wins": 0,
                "base_wins": 0,
                "ties": 0,
                "full_win_rate": None,
            }
        )

    result = {
        "schema_version": "1.0",
        "study_id": protocol["study_id"],
        "status": "formal-complete" if result_complete else "incomplete",
        "formal_evidence_complete": result_complete,
        "claim_authorized": claim_authorized,
        "protocol": str(protocol_path),
        "protocol_sha256": _sha256_file(protocol_path),
        "score_root": str(score_root) if score_root is not None else None,
        "benchmark_commit": expected_commit,
        "population_selection_rule": protocol["population"]["selection_rule"],
        "tasks": tasks,
        "analysis": analysis,
        "deferred_validation_project_executed": False,
        "rrmot_touched": False,
    }
    result_path = output_root / "RESULT.json"
    report_path = output_root / "REPORT.md"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "complete_pairs": len(deltas),
                "claim_authorized": claim_authorized,
                "result": str(result_path),
                "report": str(report_path),
            },
            indent=2,
        )
    )
    return 0 if result_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
