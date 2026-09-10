#!/usr/bin/env python3
"""Materialize a strict research-landscape source as project artifact JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.generative_ui.research_landscape import materialize_research_landscape


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    args = parser.parse_args()
    artifact = materialize_research_landscape(
        args.source,
        args.output,
        evidence_root=args.evidence_root,
    )
    print(json.dumps({"artifact_kind": artifact.artifact_kind, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
