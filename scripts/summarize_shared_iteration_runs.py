"""Collect complete development trajectories without implying a formal comparison."""

import argparse
import hashlib
import json
from pathlib import Path


def summarize(runs, output):
    rows, contracts = [], []
    for run in runs:
        contract = json.loads((run / "CONTRACT.json").read_text())
        summary = json.loads((run / "ITERATIVE_SUMMARY.json").read_text())
        terminal = json.loads((run / "RESULT.json").read_text())
        contracts.append(contract)
        rows.append(
            {
                "run": str(run),
                "agent_role": contract["role"],
                "terminal_status": terminal["status"],
                "all_attempts": summary["attempts"],
                "best_identity_including_baseline": summary["best_observed_identity"],
                "best_score_including_baseline": summary["best_observed_value"],
                "execution_seconds": summary["known_execution_seconds"],
                "cost_complete": summary["cost_complete"],
                "api_liability_usd": summary["api_cost_ceiling_usd"],
                "source_file_sha256": {
                    name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                    for name in ("CONTRACT.json", "RESULT.json", "ITERATIVE_SUMMARY.json")
                },
            }
        )
    if len(rows) < 2:
        raise ValueError("At least two complete trajectories are required")
    same_task = all(item["task"] == contracts[0]["task"] for item in contracts)
    same_provider = all(
        item["backend_sha256"] == contracts[0]["backend_sha256"] for item in contracts
    )
    result = {
        "schema_version": "1.0",
        "scope": "consumed-task development trajectories",
        "same_declared_task_and_execution_budget": same_task,
        "same_provider_configuration_digest": same_provider,
        "trajectories": rows,
        "formal_framework_comparison": False,
        "taste_gain_established": False,
        "whole_idea_to_paper_loop": False,
        "limitations": [
            "Shared task/configuration does not establish a powered formal comparison.",
            "Methods were selected adaptively on a single consumed development task.",
            "Ten scorer replicas are not ten independent research-agent trials.",
            "Conservative API liability is not invoiced cost; execution seconds exclude planning.",
            "Higher proxy values do not validate a method's intended scientific mechanism.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run, args.output)
    print(
        json.dumps(
            {"trajectories": len(result["trajectories"]), "formal_framework_comparison": False}
        )
    )


if __name__ == "__main__":
    main()
