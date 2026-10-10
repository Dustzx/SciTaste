"""Freeze an external benchmark assignment and provision SciTaste's native entry."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.open_research import prepare_campaign, prepare_native
from scitaste.executor.research_harness import (
    adaptive_harness_binding,
    competitive_harness_binding,
    default_harness_binding,
    handoff_harness_binding,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--wall-seconds", type=int, required=True)
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--native-paper-reserve-seconds", type=int, default=0)
    parser.add_argument(
        "--native-tool-policy",
        choices=("atomic", "adaptive", "source-bound", "competitive"),
        default="atomic",
        help="Explicit new-assignment harness; existing frozen plans never change",
    )
    args = parser.parse_args()
    root, output = args.project.resolve(strict=True), args.output.resolve()
    contract = prepare_campaign(
        root,
        output,
        task_id=args.task_id,
        wall_seconds=args.wall_seconds,
        max_requests=args.max_requests,
        arms=("scitaste-native",) if args.native_only else ("scitaste-native", "autoresearchclaw"),
        native_paper_reserve_seconds=args.native_paper_reserve_seconds,
    )
    prepare_native(
        root,
        output / "CAMPAIGN.json",
        root / "evaluations/acquisitions/researchharness-runtime-v1",
        output / "native-plan",
        research_harness_binding={
            "atomic": default_harness_binding,
            "adaptive": adaptive_harness_binding,
            "source-bound": handoff_harness_binding,
            "competitive": competitive_harness_binding,
        }[args.native_tool_policy](),
    )
    print(
        json.dumps(
            {
                "campaign": str(output),
                "task": contract["task_id"],
                "assigned_arms": contract["arms"],
                "native_tool_policy": args.native_tool_policy,
            }
        )
    )


if __name__ == "__main__":
    main()
