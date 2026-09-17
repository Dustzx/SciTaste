#!/usr/bin/env python3
"""Build a decision-time-only derivative of a counterfactual Taste library."""

from __future__ import annotations

import argparse

from scitaste.evaluation.counterfactual_temporal_precedents import (
    derive_temporal_safe_counterfactual_precedents,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-id", required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--precedent-root", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    audit = derive_temporal_safe_counterfactual_precedents(
        audit_id=args.audit_id,
        manifest_id=args.manifest_id,
        precedent_root=args.precedent_root,
        state_root=args.state_root,
        output_root=args.output_root,
    )
    print(audit.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
