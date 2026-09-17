#!/usr/bin/env python3
"""Combine declared/reversed natural-pilot runs without treating order as independent data."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import yaml

CONDITIONS = ("base", "knowledge_rag", "taste_library", "taste_placebo")
CONTRASTS = (
    ("knowledge_rag", "base"),
    ("taste_library", "base"),
    ("taste_placebo", "base"),
    ("taste_library", "knowledge_rag"),
    ("taste_library", "taste_placebo"),
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], probability: float) -> float:
    return values[min(round(probability * (len(values) - 1)), len(values) - 1)]


def _cluster_interval(
    values: list[float], *, resamples: int, seed: int
) -> tuple[float, float]:
    rng = random.Random(seed)
    size = len(values)
    draws = [
        sum(values[rng.randrange(size)] for _ in range(size)) / size
        for _ in range(resamples)
    ]
    draws.sort()
    return _percentile(draws, 0.025), _percentile(draws, 0.975)


def _index_results(report: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        condition: {
            result["case_id"]: result
            for result in report["conditions"][condition]["results"]
        }
        for condition in CONDITIONS
    }


def analyze(
    suite_path: Path,
    declared_path: Path,
    reversed_path: Path,
    *,
    bootstrap_resamples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    reports = {
        "declared": _load_json(declared_path),
        "reversed": _load_json(reversed_path),
    }
    if reports["declared"]["suite_sha256"] != reports["reversed"]["suite_sha256"]:
        raise ValueError("candidate-order arms use different suites")
    for order, report in reports.items():
        if report["candidate_order"] != order:
            raise ValueError(f"{order} report declares {report['candidate_order']!r}")

    indexed = {order: _index_results(report) for order, report in reports.items()}
    case_ids = sorted(indexed["declared"]["base"])
    expected_ids = sorted(case["case_id"] for case in suite["cases"])
    if case_ids != expected_ids:
        raise ValueError("reported cases differ from the frozen suite")
    for order in reports:
        for condition in CONDITIONS:
            if sorted(indexed[order][condition]) != case_ids:
                raise ValueError(f"{order}/{condition} has incomplete cases")

    condition_summary: dict[str, Any] = {}
    for condition_index, condition in enumerate(CONDITIONS):
        per_case_order_consistent = [
            int(
                all(
                    indexed[order][condition][case_id]["correct"]
                    for order in reports
                )
            )
            for case_id in case_ids
        ]
        per_case_accuracy = [
            sum(
                int(indexed[order][condition][case_id]["correct"])
                for order in reports
            )
            / 2
            for case_id in case_ids
        ]
        lower, upper = _cluster_interval(
            per_case_accuracy,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed + condition_index,
        )
        token_usage = {"input_tokens": 0, "output_tokens": 0}
        for order in reports:
            for result in indexed[order][condition].values():
                usage = result.get("usage") or {}
                token_usage["input_tokens"] += usage.get("input_tokens") or 0
                token_usage["output_tokens"] += usage.get("output_tokens") or 0
        condition_summary[condition] = {
            "order_consistent_accuracy": sum(per_case_order_consistent)
            / len(case_ids),
            "accuracy_by_order": {
                order: sum(
                    int(result["correct"])
                    for result in indexed[order][condition].values()
                )
                / len(case_ids)
                for order in reports
            },
            "order_averaged_accuracy": sum(per_case_accuracy) / len(case_ids),
            "case_clustered_95pct_ci": [lower, upper],
            "order_inconsistent_case_count": sum(
                indexed["declared"][condition][case_id]["correct"]
                != indexed["reversed"][condition][case_id]["correct"]
                for case_id in case_ids
            ),
            "selected_action_changes_between_orders": sum(
                indexed["declared"][condition][case_id]["selected_action_id"]
                != indexed["reversed"][condition][case_id]["selected_action_id"]
                for case_id in case_ids
            ),
            "token_usage": {
                **token_usage,
                "total_tokens": token_usage["input_tokens"]
                + token_usage["output_tokens"],
            },
        }

    contrast_summary: dict[str, Any] = {}
    for contrast_index, (treatment, control) in enumerate(CONTRASTS):
        per_case_consistent_delta = [
            int(
                all(
                    indexed[order][treatment][case_id]["correct"]
                    for order in reports
                )
            )
            - int(
                all(
                    indexed[order][control][case_id]["correct"]
                    for order in reports
                )
            )
            for case_id in case_ids
        ]
        per_case_delta = [
            sum(
                int(indexed[order][treatment][case_id]["correct"])
                - int(indexed[order][control][case_id]["correct"])
                for order in reports
            )
            / 2
            for case_id in case_ids
        ]
        lower, upper = _cluster_interval(
            per_case_delta,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed + 100 + contrast_index,
        )
        contrast_summary[f"{treatment}_minus_{control}"] = {
            "order_consistent_accuracy_delta": sum(per_case_consistent_delta)
            / len(case_ids),
            "order_consistent_improved_cases": sum(
                value > 0 for value in per_case_consistent_delta
            ),
            "order_consistent_regressed_cases": sum(
                value < 0 for value in per_case_consistent_delta
            ),
            "order_consistent_unchanged_cases": sum(
                value == 0 for value in per_case_consistent_delta
            ),
            "order_averaged_accuracy_delta": sum(per_case_delta) / len(case_ids),
            "case_clustered_95pct_ci": [lower, upper],
            "improved_cases": sum(value > 0 for value in per_case_delta),
            "regressed_cases": sum(value < 0 for value in per_case_delta),
            "unchanged_cases": sum(value == 0 for value in per_case_delta),
        }

    preferred_a = sum(
        case["preferred_action_id"].endswith("-a") for case in suite["cases"]
    )
    return {
        "schema_version": "1.0",
        "analysis_scope": "natural_dual_ai_proxy_development_pilot",
        "suite_id": reports["declared"]["suite_id"],
        "suite_sha256": reports["declared"]["suite_sha256"],
        "case_count": len(case_ids),
        "decision_count": len(case_ids) * len(CONDITIONS) * len(reports),
        "candidate_orders": list(reports),
        "preferred_action_position_counts": {
            "declared_a": preferred_a,
            "declared_b": len(case_ids) - preferred_a,
        },
        "conditions": condition_summary,
        "contrasts": contrast_summary,
        "estimator": {
            "primary_metric": "accuracy requiring correctness under both candidate orders",
            "unit": "case",
            "candidate_orders_are_repeated_measurements": True,
            "secondary_interval": "case-clustered percentile bootstrap of order-averaged accuracy",
            "bootstrap_resamples": bootstrap_resamples,
            "bootstrap_seed": bootstrap_seed,
        },
        "claim_boundary": (
            "Development evidence only: labels are agreements between two AI reviewers, "
            "the 36 cases are unbalanced across decision families, raw and abstracted "
            "contexts are not token matched, and no human construct-validity study was run."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--declared", type=Path, required=True)
    parser.add_argument("--reversed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260917)
    args = parser.parse_args()
    analysis = analyze(
        args.suite,
        args.declared,
        args.reversed,
        bootstrap_resamples=args.bootstrap_resamples,
        bootstrap_seed=args.bootstrap_seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(analysis, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
