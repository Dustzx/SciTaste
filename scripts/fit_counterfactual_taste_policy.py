#!/usr/bin/env python3
"""Fit and freeze a development-only counterfactual Scientific Taste policy."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_policy import (
    fit_counterfactual_taste_policy,
    save_counterfactual_taste_policy,
)
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.interactive_research import (
    load_interactive_research_prefix,
    load_interactive_research_run_receipt,
)


def _load_state(root_value: str):
    root = Path(root_value)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"counterfactual state root must be a directory: {root}")
    result = CounterfactualActionSetResult.model_validate_json(
        (root / "RESULT.json").read_bytes(), strict=True
    )
    prefix = load_interactive_research_prefix(root / "PREFIX.json")
    receipts = tuple(
        load_interactive_research_run_receipt(root / action.value.casefold() / "RECEIPT.json")
        for action in sorted(CounterfactualResearchAction, key=lambda item: item.value)
    )
    return result, prefix, receipts


def run(args: argparse.Namespace):
    loaded = tuple(_load_state(item) for item in args.state_root)
    policy = fit_counterfactual_taste_policy(
        policy_id=args.policy_id,
        project_id=args.project_id,
        results=tuple(item[0] for item in loaded),
        prefixes=tuple(item[1] for item in loaded),
        branch_receipts=tuple(item[2] for item in loaded),
        fallback_action=CounterfactualResearchAction(args.fallback_action),
    )
    save_counterfactual_taste_policy(policy, args.output)
    return policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--project-id", default="scitaste-self-development")
    parser.add_argument("--state-root", action="append", required=True)
    parser.add_argument(
        "--fallback-action",
        choices=tuple(item.value for item in CounterfactualResearchAction),
        default=CounterfactualResearchAction.PROBE.value,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    print(run(build_parser().parse_args()).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
