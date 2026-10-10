"""Read-only case-quality audit for materialized SciTasteBench objective forks.

This does not select cases, change a frozen population, or authorize an effect
claim. It reports whether development and test used the same scoring/runtime
contract before anyone interprets their score difference as task transfer.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def _case_rows(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        raise ValueError(f"empty fork case file: {path}")
    return rows


def _contract(case: dict[str, Any]) -> dict[str, Any]:
    execution = case["execution_contract"]
    scorer = case["scorer_contract"]
    return {
        "scorer_sha256": scorer["contract_sha256"],
        "allowed_tools": execution["allowed_tools"],
        "resource_limits": execution["resource_limits"],
        "maximum_steps": execution["maximum_steps"],
        "timeout_seconds": execution["timeout_seconds"],
        "network_access": execution["network_access"],
        "seed_block_ids": execution["seed_block_ids"],
        "minimum_action_compliance_rate": execution["minimum_action_compliance_rate"],
    }


def summarize(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = _case_rows(path)
    contract = _contract(rows[0])
    if any(_contract(case) != contract for case in rows[1:]):
        raise ValueError(f"fork cases contain mixed scoring/runtime contracts: {path}")

    seen: set[tuple[str, str]] = set()
    gaps: list[float] = []
    no_objective = Counter[str]()
    case_with_no_objective = 0
    noncompliant = 0
    replicate_count = 0
    action_counts = Counter[int]()
    for case in rows:
        stage = case["study_id"].rsplit("-", 1)[-1]
        key = (case["task_cluster_id"], stage)
        if key in seen:
            raise ValueError(f"duplicate task/stage fork case: {key}")
        seen.add(key)
        actions = set(case["available_actions"])
        action_counts[len(actions)] += 1
        utilities = sorted(case["action_utility_estimates"].values(), reverse=True)
        if len(utilities) != len(actions) or len(actions) < 2:
            raise ValueError(f"incomplete action utility vector: {key}")
        gaps.append(utilities[0] - utilities[1])

        outcomes = case["replicate_outcomes"]
        expected_pairs = {
            (action, block) for action in actions for block in contract["seed_block_ids"]
        }
        observed_pairs = {(item["action_id"], item["seed_block_id"]) for item in outcomes}
        if len(outcomes) != len(expected_pairs) or observed_pairs != expected_pairs:
            raise ValueError(f"incomplete or duplicate action/seed support: {key}")
        replicate_count += len(outcomes)
        missed_here = False
        for item in outcomes:
            noncompliant += item["action_compliance"] != "compliant"
            if not item["objective_observed"]:
                no_objective[str(item["failure_code"])] += 1
                missed_here = True
        case_with_no_objective += missed_here

    summary = {
        "case_count": len(rows),
        "independent_task_clusters": len({item[0] for item in seen}),
        "action_count_distribution": dict(sorted(action_counts.items())),
        "continuation_count": replicate_count,
        "noncompliant_continuations": noncompliant,
        "top_action_exact_ties": sum(gap == 0 for gap in gaps),
        "top_two_gap_median": statistics.median(gaps),
        "top_two_gap_le_0_01": sum(gap <= 0.01 for gap in gaps),
        "top_two_gap_gt_0_05": sum(gap > 0.05 for gap in gaps),
        "continuations_without_observed_objective": sum(no_objective.values()),
        "no_objective_failure_codes": dict(sorted(no_objective.items())),
        "cases_with_unobserved_objective": case_with_no_objective,
        "gap_thresholds_are_exploratory_not_selection_rules": True,
    }
    return summary, contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development_cases", type=Path)
    parser.add_argument("test_cases", type=Path)
    parser.add_argument("--require-matched-contract", action="store_true")
    args = parser.parse_args()

    development, development_contract = summarize(args.development_cases)
    test, test_contract = summarize(args.test_cases)
    differences = {
        key: {"development": development_contract[key], "test": test_contract[key]}
        for key in development_contract
        if development_contract[key] != test_contract[key]
    }
    report = {
        "development": development,
        "test": test,
        "contract_differences": differences,
        "same_scoring_and_runtime_contract": not differences,
        "clean_same_contract_transfer_interpretation_allowed": not differences,
        "does_not_retroactively_exclude_cases": True,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 2 if args.require_matched_contract and differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
