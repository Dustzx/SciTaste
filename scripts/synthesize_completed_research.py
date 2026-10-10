"""Produce one input-bound result registry from completed whole research episodes."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.evidence_synthesis import synthesize_research_evidence
from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "specification", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    spec = args.specification.resolve(strict=True)
    spec.relative_to(project / "evaluations")
    output = args.output.resolve()
    output.relative_to(project / "evaluations")
    result = synthesize_research_evidence(project, json.loads(spec.read_bytes()))
    output.mkdir(parents=True, exist_ok=False)
    retain_json(output / "RESULTS.json", {"specification_sha256": digest(spec), **result})
    print(
        f"Bound {result['assigned_episodes']} assigned episodes across "
        f"{result['distinct_task_ids']} task types; "
        f"formal assignments: {result['formal_task_assignments']}"
    )


if __name__ == "__main__":
    main()
