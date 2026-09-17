#!/usr/bin/env python3
"""Analyze an accepted development-only counterfactual Taste selector run."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_deliberation_analysis import (
    analyze_counterfactual_deliberations,
    save_counterfactual_deliberation_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("outputs"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_counterfactual_deliberations(
        study_id=args.study_id,
        input_root=args.input_root,
        ledger_root=args.ledger_root,
        evidence_root=args.evidence_root,
    )
    path = save_counterfactual_deliberation_report(report, args.output)
    print(path)


if __name__ == "__main__":
    main()
