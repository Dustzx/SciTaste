#!/usr/bin/env python3
"""Compile one exact CodeScientist checkout into development Taste candidates."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.codescientist_population import compile_codescientist_population


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compile_codescientist_population(
        checkout=args.checkout,
        expected_commit=args.expected_commit,
        output_directory=args.output,
    )
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
