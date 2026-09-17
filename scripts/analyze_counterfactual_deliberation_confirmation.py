#!/usr/bin/env python3
"""Analyze a frozen content-conditioned Taste confirmation after selector execution."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_deliberation_confirmation import (
    analyze_counterfactual_deliberation_confirmation,
    save_counterfactual_deliberation_confirmation_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("outputs"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_counterfactual_deliberation_confirmation(
        protocol_path=args.protocol,
        input_root=args.input_root,
        ledger_root=args.ledger_root,
        evidence_root=args.evidence_root,
    )
    path = save_counterfactual_deliberation_confirmation_report(report, args.output)
    print(path)


if __name__ == "__main__":
    main()
