"""Register an explicit project-bound CPU/API task without launching it."""

import argparse
import json
from pathlib import Path

from scitaste.executor.benchmark_task import prepare_benchmark_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "benchmark", "harness", "backend", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--max-rounds", type=int, default=40)
    parser.add_argument("--wall-seconds", type=int, default=1800)
    parser.add_argument(
        "--controller-owner",
        choices=("researchharness", "scitaste-native"),
        default="researchharness",
    )
    args = parser.parse_args()
    plan = prepare_benchmark_task(**vars(args))
    print(json.dumps({"task_id": plan["task_id"], "status": "prepared-not-executed"}))


if __name__ == "__main__":
    main()
