"""Summarize existing public control predictions, without fitting or private scoring."""

import argparse
import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json
from scitaste.benchmark.perturbation_task_data import correlation


def summarize(pack, controls):
    public = pack / "public/combinatorial-perturbation"
    manifest = json.loads((pack / "PACK.json").read_text())
    run = json.loads((controls / "RUN.json").read_text())
    records = []
    for context in ("discovery", "validation"):
        labels_path = public / f"{context}.npz"
        relative = labels_path.relative_to(pack).as_posix()
        if digest(labels_path) != manifest["files"][relative]:
            raise ValueError("Frozen public evidence changed")
        with np.load(labels_path, allow_pickle=False) as labels:
            for method in run["methods"]:
                path = controls / f"{context}--{method}.npz"
                with np.load(path, allow_pickle=False) as predicted:
                    if not np.array_equal(predicted["condition_id"], labels["condition_id"]):
                        raise ValueError("Public condition IDs differ")
                    rmse = np.sqrt(
                        np.mean((predicted["expression"] - labels["expression"]) ** 2, axis=1)
                    )
                    delta = correlation(
                        predicted["expression"] - labels["control"],
                        labels["expression"] - labels["control"],
                    )
                    values = [v for v in delta if v is not None]
                    records.append(
                        {
                            "context": context,
                            "method": method,
                            "conditions": len(rmse),
                            "mean_condition_rmse": float(rmse.mean()),
                            "mean_pearson_delta": float(np.mean(values)) if values else None,
                            "defined_pearson_conditions": len(values),
                            "prediction_sha256": digest(path),
                        }
                    )
    result = {
        "pack_sha256": digest(pack / "PACK.json"),
        "run_sha256": digest(controls / "RUN.json"),
        "new_fits": 0,
        "new_inference_runs": 0,
        "private_labels_read": False,
        "role": (
            "Public ordinary feasibility/strong-control outcomes, "
            "not research-system scores or quality admission"
        ),
        "records": records,
    }
    retain_json(controls / "PUBLIC_RESULTS.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.pack, args.controls)
