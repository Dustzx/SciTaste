"""Prepare a source-bound executable study from the current registered project idea."""

import argparse
import json
from pathlib import Path

from scitaste.executor.project_task import prepare_project_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "task-path", "candidate-source", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--adapter", choices=("meta", "unlearning"), required=True)
    parser.add_argument("--study-question", required=True)
    parser.add_argument("--design-path", type=Path)
    parser.add_argument("--remote-resource", type=Path)
    parser.add_argument("--study-id")
    parser.add_argument("--comparison-id")
    parser.add_argument("--comparison-arm", choices=("treatment", "comparator"))
    result = prepare_project_task(**vars(parser.parse_args()))
    print(
        json.dumps(
            {
                "status": "prepared-not-executed",
                "project": result["project_id"],
                "idea": result["idea_revision"]["revision_id"],
            }
        )
    )


if __name__ == "__main__":
    main()
