#!/usr/bin/env python3
"""Compile verified objective branches into a development-only Taste library."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_precedents import (
    compile_counterfactual_taste_precedents,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--abstraction-input-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = compile_counterfactual_taste_precedents(
        manifest_id=args.manifest_id,
        project_id=args.project_id,
        source_run_id=args.source_run_id,
        state_root=args.state_root,
        abstraction_input_root=args.abstraction_input_root,
        ledger_root=args.ledger_root,
        evidence_root=args.evidence_root,
        output_root=args.output_root,
    )
    print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
