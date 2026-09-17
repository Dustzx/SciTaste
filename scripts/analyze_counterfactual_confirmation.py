#!/usr/bin/env python3
"""Analyze a frozen counterfactual Taste confirmation population."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.counterfactual_confirmation import (
    analyze_counterfactual_confirmation,
    save_counterfactual_confirmation_report,
)
from scitaste.evaluation.counterfactual_policy import CounterfactualTastePolicy
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.interactive_research import load_interactive_research_prefix


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: argparse.Namespace):
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    policy_source = args.policy.read_bytes()
    policy = CounterfactualTastePolicy.model_validate_json(policy_source, strict=True)
    lock_path = args.protocol.parent.parent / "formal_v3" / "policy_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if hashlib.sha256(policy_source).hexdigest() != lock["policy_file_sha256"]:
        raise ValueError("policy file differs from the frozen policy lock")
    if policy.policy_sha256 != lock["policy_sha256"]:
        raise ValueError("policy content differs from the frozen policy lock")

    population = []
    for root in args.state_root:
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"confirmation state root must be a directory: {root}")
        result = CounterfactualActionSetResult.model_validate_json(
            (root / "RESULT.json").read_bytes(), strict=True
        )
        prefix = load_interactive_research_prefix(root / "PREFIX.json")
        population.append((result, prefix))

    analysis = protocol["analysis"]
    admission = protocol["admission"]
    report = analyze_counterfactual_confirmation(
        report_id=f"{protocol['protocol_id']}-report",
        protocol_sha256=_sha256(args.protocol),
        policy=policy,
        population=tuple(population),
        expected_state_count=int(analysis["state_count"]),
        expected_task_cluster_count=len(protocol["tasks"]),
        minimum_objective_observation_rate=float(
            admission["minimum_objective_observation_rate"]
        ),
    )
    save_counterfactual_confirmation_report(report, args.output)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    print(run(build_parser().parse_args()).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
