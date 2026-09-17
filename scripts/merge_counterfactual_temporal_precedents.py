#!/usr/bin/env python3
"""Merge verified temporal-safe counterfactual precedent libraries."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.counterfactual_temporal_precedents import (
    merge_temporal_safe_counterfactual_precedents,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merge-id", required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument(
        "--precedent-root",
        type=Path,
        action="append",
        required=True,
        help="Temporal-safe source root; repeat at least twice.",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    receipt = merge_temporal_safe_counterfactual_precedents(
        merge_id=args.merge_id,
        manifest_id=args.manifest_id,
        precedent_roots=tuple(args.precedent_root),
        output_root=args.output_root,
    )
    print(receipt.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
