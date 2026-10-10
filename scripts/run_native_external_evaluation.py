"""Prepare/consume a pinned upstream MLR-Bench review, without a paid API."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.native_external_evaluation import prepare, score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "score"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if any(
            item is None
            for item in (args.project, args.campaign, args.assignments, args.source, args.selection)
        ):
            parser.error("prepare requires project, campaign, assignments, source and selection")
        result = prepare(
            args.project,
            args.campaign,
            json.loads(args.assignments.read_text()),
            args.source,
            json.loads(args.selection.read_text()),
            args.output,
        )
    else:
        result = score(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 75 if result["pending_requests"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
