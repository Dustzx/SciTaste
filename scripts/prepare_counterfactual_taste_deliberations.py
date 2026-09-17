#!/usr/bin/env python3
"""Prepare outcome-hidden leave-one-task-cluster-out Taste deliberations."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_deliberation_policy import (
    prepare_counterfactual_deliberation_inputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--precedent-root", type=Path, required=True)
    parser.add_argument(
        "--target-precedent-root",
        type=Path,
        default=None,
        help=(
            "Optional frozen target manifest. The precedent root may then contain additional "
            "development cases without changing the evaluated target population."
        ),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--maximum-selected-cases", type=int, default=3)
    parser.add_argument("--maximum-candidate-cases", type=int, default=None)
    parser.add_argument(
        "--exclude-case-id",
        action="append",
        default=[],
        help=(
            "Exclude an explicitly superseded case from both the source and target "
            "populations; repeat as needed."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for path in prepare_counterfactual_deliberation_inputs(
        project_id=args.project_id,
        state_root=args.state_root,
        precedent_root=args.precedent_root,
        target_precedent_root=args.target_precedent_root,
        output_root=args.output_root,
        maximum_selected_cases=args.maximum_selected_cases,
        maximum_candidate_cases=args.maximum_candidate_cases,
        excluded_case_ids=tuple(sorted(set(args.exclude_case_id))),
    ):
        print(path)


if __name__ == "__main__":
    main()
