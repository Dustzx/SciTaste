"""Train-only ordinary controls; not foundation-model or research-agent results."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

METHODS = ("no_change", "additive", "scalar_amplitude")


def additive(query):
    parts = query["perturbation"]
    control, singles = query["control"], query["single_expression"]
    delta = np.zeros((len(parts), len(control)))
    for column in (0, 1):
        mask = parts[:, column] >= 0
        delta[mask] += singles[parts[mask, column]] - control
    return control + delta


def run(data, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with np.load(data / "train.npz", allow_pickle=False) as train:
        mask = (train["perturbation"] >= 0).all(axis=1)
        delta = additive(train)[mask] - train["control"]
        observed = train["expression"][mask] - train["control"]
        denominator = np.sum(delta**2)
        if denominator <= 0:
            raise ValueError("No fitting-double amplitude information")
        amplitude = float(np.sum(delta * observed) / denominator)
    fit_seconds = time.monotonic() - started
    contexts = (
        json.loads((data / "QUERY.json").read_text())["contexts"]
        if (data / "QUERY.json").exists()
        else {"discovery": "discovery.npz", "validation": "validation.npz"}
    )
    for context, filename in contexts.items():
        with np.load(data / filename, allow_pickle=False) as query:
            for method in METHODS:
                begin = time.monotonic()
                base = np.tile(query["control"], (len(query["condition_id"]), 1))
                prediction = (
                    base
                    if method == "no_change"
                    else base
                    + (1 if method == "additive" else amplitude) * (additive(query) - base)
                )
                elapsed = time.monotonic() - begin
                np.savez_compressed(
                    output / f"{context}--{method}.npz",
                    condition_id=query["condition_id"],
                    expression=prediction,
                    valid=np.ones(len(prediction), dtype=bool),
                    seconds=np.full(len(prediction), elapsed / len(prediction)),
                )
    (output / "RUN.json").write_text(
        json.dumps(
            {
                "fit_seconds": fit_seconds,
                "elapsed_seconds": time.monotonic() - started,
                "methods": list(METHODS),
                "train_only_amplitude": amplitude,
                "role": "Ordinary public controls; not research-system or novelty evidence",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.data, args.output)
