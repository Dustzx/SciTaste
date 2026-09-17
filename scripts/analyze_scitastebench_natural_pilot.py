#!/usr/bin/env python3
"""Combine declared/reversed natural-pilot runs without treating order as independent data."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

import yaml

LEGACY_CONTRASTS = (
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


def _paired_sign_test(improved: int, regressed: int) -> float:
    discordant = improved + regressed
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, index) for index in range(min(improved, regressed) + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * tail)


def _index_results(
    report: dict[str, Any], conditions: tuple[str, ...]
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        condition: {
            result["case_id"]: result
            for result in report["conditions"][condition]["results"]
        }
        for condition in conditions
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
    conditions = tuple(reports["declared"]["conditions"])
    if set(conditions) != set(reports["reversed"]["conditions"]):
        raise ValueError("candidate-order arms contain different conditions")
    registered_contrasts = tuple(suite.get("registered_contrasts") or ())
    contrasts = (
        tuple(
            (
                item["contrast_id"],
                item["treatment"],
                item["comparator"],
                item,
            )
            for item in registered_contrasts
        )
        if registered_contrasts
        else tuple(
            (f"{treatment}_minus_{control}", treatment, control, None)
            for treatment, control in LEGACY_CONTRASTS
        )
    )

    indexed = {
        order: _index_results(report, conditions) for order, report in reports.items()
    }
    case_ids = sorted(indexed["declared"]["base"])
    expected_ids = sorted(case["case_id"] for case in suite["cases"])
    if case_ids != expected_ids:
        raise ValueError("reported cases differ from the frozen suite")
    for order in reports:
        for condition in conditions:
            if sorted(indexed[order][condition]) != case_ids:
                raise ValueError(f"{order}/{condition} has incomplete cases")

    condition_summary: dict[str, Any] = {}
    for condition_index, condition in enumerate(conditions):
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
    for contrast_index, (contrast_id, treatment, control, registration) in enumerate(
        contrasts
    ):
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
        consistent_improved = sum(value > 0 for value in per_case_consistent_delta)
        consistent_regressed = sum(value < 0 for value in per_case_consistent_delta)
        improved = sum(value > 0 for value in per_case_delta)
        regressed = sum(value < 0 for value in per_case_delta)
        contrast_summary[contrast_id] = {
            "treatment": treatment,
            "comparator": control,
            "registration": registration,
            "order_consistent_accuracy_delta": sum(per_case_consistent_delta)
            / len(case_ids),
            "order_consistent_improved_cases": consistent_improved,
            "order_consistent_regressed_cases": consistent_regressed,
            "order_consistent_unchanged_cases": sum(
                value == 0 for value in per_case_consistent_delta
            ),
            "order_consistent_exact_p_two_sided": _paired_sign_test(
                consistent_improved, consistent_regressed
            ),
            "order_averaged_accuracy_delta": sum(per_case_delta) / len(case_ids),
            "case_clustered_95pct_ci": [lower, upper],
            "improved_cases": improved,
            "regressed_cases": regressed,
            "unchanged_cases": sum(value == 0 for value in per_case_delta),
            "order_averaged_exact_sign_p_two_sided": _paired_sign_test(
                improved, regressed
            ),
        }

    preferred_a = sum(
        case["preferred_action_id"].endswith("-a") for case in suite["cases"]
    )
    confirmation_reserve = "confirmation" in reports["declared"]["suite_id"]
    confirmation_supported = bool(
        confirmation_reserve
        and contrast_summary
        and all(
            item["order_consistent_accuracy_delta"] > 0
            and item["case_clustered_95pct_ci"][0] > 0
            for item in contrast_summary.values()
        )
    )
    return {
        "schema_version": "1.0",
        "analysis_scope": (
            "natural_dual_ai_proxy_independent_confirmation_reserve"
            if confirmation_reserve
            else "natural_dual_ai_proxy_development_pilot"
        ),
        "suite_id": reports["declared"]["suite_id"],
        "suite_sha256": reports["declared"]["suite_sha256"],
        "case_count": len(case_ids),
        "decision_count": len(case_ids) * len(conditions) * len(reports),
        "candidate_orders": list(reports),
        "preferred_action_position_counts": {
            "declared_a": preferred_a,
            "declared_b": len(case_ids) - preferred_a,
        },
        "conditions": condition_summary,
        "contrasts": contrast_summary,
        "mechanism_confirmation_supported": confirmation_supported,
        "formal_evidence_eligible": False,
        "estimator": {
            "primary_metric": "accuracy requiring correctness under both candidate orders",
            "unit": "case",
            "candidate_orders_are_repeated_measurements": True,
            "secondary_interval": "case-clustered percentile bootstrap of order-averaged accuracy",
            "bootstrap_resamples": bootstrap_resamples,
            "bootstrap_seed": bootstrap_seed,
        },
        "claim_boundary": (
            "Independent source-group-disjoint confirmation reserve, but not a formal "
            "benchmark release: labels are agreements between two AI reviewers, three "
            "decision-context families are absent, and no human construct-validity or "
            "public-release-rights claim is made."
            if confirmation_reserve
            else (
                "Development evidence only: labels are agreements between two AI reviewers, "
                "the 36 cases are unbalanced across decision families, and no independent "
                "construct-validity study was run. The contrastive suite token-matches raw, "
                "matched, and mismatched contexts when registered contrasts are present."
                if registered_contrasts
                else "Development evidence only: labels are agreements between two AI "
                "reviewers, the 36 cases are unbalanced across decision families, raw and "
                "abstracted contexts are not token matched, and no human construct-validity "
                "study was run."
            )
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
