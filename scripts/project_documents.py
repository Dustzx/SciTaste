"""Publish bounded project summaries for Core and Generation as Content."""

import argparse
from pathlib import Path

from scitaste.project.documents import ProjectDocuments, publish_documents
from scitaste.project.runtime import ProjectRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Complete ProjectDocuments JSON revision; never an append-only log",
    )
    parser.add_argument(
        "--expected-index-sha256",
        help="Reject a stale revision instead of overwriting concurrent project summaries",
    )
    args = parser.parse_args()
    publish_documents(
        ProjectRuntime(args.outputs),
        ProjectDocuments.model_validate_json(args.input.read_text()),
        expected_index_sha256=args.expected_index_sha256,
    )


if __name__ == "__main__":
    main()
