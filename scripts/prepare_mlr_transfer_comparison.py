"""Freeze a new official MLR topic for three real research implementations."""

import argparse
from pathlib import Path

from scitaste.benchmark.open_research import prepare_campaign, prepare_native
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "output", "taste-library", "taste-profile"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--research-title", required=True)
    parser.add_argument("--wall-seconds", type=int, required=True)
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument(
        "--taste-proposal-context",
        choices=("reviewed-conditional-v1", "reviewed-inquiry-v1"),
        default="reviewed-conditional-v1",
        help="Freeze a reviewed proposal policy before any model response",
    )
    args = parser.parse_args()
    root, output = args.project.resolve(strict=True), args.output.resolve()
    prepare_campaign(
        root,
        output,
        task_id=args.task_id,
        wall_seconds=args.wall_seconds,
        max_requests=args.max_requests,
        arms=("scitaste-native", "autoresearchclaw", "mlr-agent"),
        native_paper_reserve_seconds=args.wall_seconds // 4,
        development_taste_library=args.taste_library,
        taste_profile=args.taste_profile,
        research_title=args.research_title,
        metadata_timeout_seconds=60,
        taste_proposal_context=args.taste_proposal_context,
    )
    prepare_native(
        root,
        output / "CAMPAIGN.json",
        root / "evaluations/acquisitions/researchharness-runtime-v1",
        output / "native-plan",
    )
    retain_json(
        output / "ASSIGNMENTS.json",
        {
            "scitaste-native": {
                "run": f"evaluations/{output.name}-native",
                "lifecycle": f"evaluations/{output.name}-native-lifecycle",
            },
            "autoresearchclaw": {"run": f"evaluations/{output.name}-arc"},
            "mlr-agent": {"run": f"evaluations/{output.name}-mlr-agent"},
        },
    )
    print(f"Frozen three actual systems on {args.task_id}: {output}")


if __name__ == "__main__":
    main()
