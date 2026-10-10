"""Acquire published decision evidence; does not admit sources or propose results."""

import argparse
import json
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json
from scripts.build_graph_research_task import acquire

SOURCES = {
    "jtt": "https://proceedings.mlr.press/v139/liu21f/liu21f.pdf",
    "d3m": "https://proceedings.neurips.cc/paper_files/paper/2024/file/abbbb25cddb2c2cd08714e6bfa2f0634-Paper-Conference.pdf",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipts = {
        name: acquire(url, output / (name + ".pdf"), 30_000_000) for name, url in SOURCES.items()
    }
    retain_json(
        output / "RECEIPT.json",
        {
            "sources": receipts,
            "source_admitted": False,
            "task_content_supplied": False,
            "model_calls": 0,
        },
    )
    print(json.dumps({"status": "sources-acquired-not-admitted", "sources": list(receipts)}))


if __name__ == "__main__":
    main()
