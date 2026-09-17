#!/usr/bin/env python3
"""Prepare grounded Taste abstraction inputs from counterfactual action sets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from scitaste.evaluation.counterfactual_abstraction import (
    build_counterfactual_taste_abstraction_input,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.interactive_research import load_interactive_research_prefix


def run(args: argparse.Namespace) -> tuple[Path, ...]:
    outputs = []
    for root in args.state_root:
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"counterfactual state root must be a directory: {root}")
        result = CounterfactualActionSetResult.model_validate_json(
            (root / "RESULT.json").read_bytes(), strict=True
        )
        prefix = load_interactive_research_prefix(root / "PREFIX.json")
        abstraction_input = build_counterfactual_taste_abstraction_input(result, prefix)
        target = args.output_root / result.study_id / "INPUT.json"
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write((abstraction_input.model_dump_json(indent=2) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        outputs.append(target)
    return tuple(outputs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> None:
    for path in run(build_parser().parse_args()):
        print(path)


if __name__ == "__main__":
    main()
