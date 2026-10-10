"""Exercise event capture on historical traces, explicitly without prospective status."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.project.research_artifact import register_artifact
from scitaste.taste.benchmark_capture import BenchmarkDecisionCapture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "events", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    for path in (args.events, args.output):
        path.resolve().relative_to(project)
    raw = args.events.read_bytes()
    capture = BenchmarkDecisionCapture(
        args.output,
        source_binding={
            "events": args.events.resolve().relative_to(project).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        mode="historical-replay",
    )
    for line in raw.decode().splitlines():
        capture.observe(json.loads(line))
    result = capture.finish(terminal_status="historical-replay-complete")
    register_artifact(
        project=project,
        artifact=args.output / "DISPOSITION.json",
        provider="deterministic-replay",
        model="historical-event-pairing",
        condition="historical-observations-not-prospective",
        status="replayed-not-admitted",
    )
    print(
        json.dumps(
            {
                "completed": len(result["completed_observations"]),
                "unresolved": len(result["unresolved_tool_call_ids"]),
                "mode": result["mode"],
                "new_api_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
