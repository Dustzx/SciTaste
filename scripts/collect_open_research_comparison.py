"""Observe, seal or score the assigned complete-research benchmark systems."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research_results import (
    observe,
    prepare_assessment,
    score_assessment,
)
from scitaste.model_nodes.session_exchange import SessionResponsePending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "prepare-assessment", "score"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reuse-assessment", type=Path)
    parser.add_argument(
        "--partial-terminal",
        action="store_true",
        help="Seal only completed manuscripts early; retain every assigned arm and pending status",
    )
    args = parser.parse_args()
    if args.action != "status" and args.output is None:
        parser.error("Assessment actions require --output")
    assignments = json.loads(args.assignments.read_text())
    if args.action == "status":
        result = observe(args.project, args.campaign, assignments)
    elif args.action == "prepare-assessment":
        result = prepare_assessment(
            args.project,
            args.campaign,
            assignments,
            args.output,
            partial_terminal=args.partial_terminal,
        )
    else:
        try:
            result = score_assessment(args.output, reuse=args.reuse_assessment)
        except SessionResponsePending as exc:
            print(json.dumps({"status": "awaiting-session-response", "request": str(exc)}))
            return 75
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
