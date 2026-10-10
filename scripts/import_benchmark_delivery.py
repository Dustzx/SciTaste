"""Connect terminal ResearchClawBench runs to the existing measured paper lifecycle."""

import argparse
import json
from pathlib import Path

from scitaste.project.research_artifact import register_artifact
from scitaste.writing.benchmark_delivery import export_benchmark_delivery
from scitaste.writing.experiment_delivery import compile_experiment_writing_buffer


def deliver(*, project: Path, runs: list[Path], output: Path):
    artifact = export_benchmark_delivery(project=project, runs=runs, output=output)
    buffer = compile_experiment_writing_buffer(output, project=project)
    register_artifact(
        project=project,
        artifact=artifact,
        provider="deterministic",
        model="benchmark-delivery-importer",
        condition="historical-benchmark-delivery",
        status="terminal-results-imported-not-reexecuted",
    )
    return {
        "artifact": str(artifact),
        "observations": len(buffer.evidence),
        "new_experiments_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(deliver(project=args.project, runs=args.run, output=args.output)))


if __name__ == "__main__":
    main()
