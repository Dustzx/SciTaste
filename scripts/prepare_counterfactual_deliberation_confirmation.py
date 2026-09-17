#!/usr/bin/env python3
"""Freeze outcome-hidden selector inputs for a declared confirmation population."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_deliberation_confirmation import (
    prepare_counterfactual_deliberation_confirmation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    lock = prepare_counterfactual_deliberation_confirmation(
        protocol_path=args.protocol,
        state_root=args.state_root,
        output_root=args.output_root,
    )
    print(lock.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
