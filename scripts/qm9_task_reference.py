"""Ordinary executable molecular-property controls, not research agents or SOTA."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.kernel_approximation import Nystroem
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ELEMENTS = (1, 6, 7, 8, 9)
METHODS = ("atom_counts", "geometry_trees", "geometry_kernel")


def descriptor(z, coords):
    """Element-resolved radial histograms: invariant but not information complete."""
    features = []
    pairs = [(a, b) for i, a in enumerate(ELEMENTS) for b in ELEMENTS[i:]]
    centers = np.linspace(0.5, 6.0, 12)
    for charges, positions in zip(z, coords, strict=True):
        keep = charges > 0
        charges, positions = charges[keep], positions[keep]
        counts = np.array([(charges == element).sum() for element in ELEMENTS], dtype=float)
        ii, jj = np.triu_indices(len(charges), 1)
        distances = np.linalg.norm(positions[ii] - positions[jj], axis=1)
        lo, hi = np.minimum(charges[ii], charges[jj]), np.maximum(charges[ii], charges[jj])
        blocks = []
        for a, b in pairs:
            values = distances[(lo == a) & (hi == b)]
            blocks.append(np.exp(-(((values[:, None] - centers) / 0.35) ** 2)).sum(axis=0))
        features.append(np.concatenate([counts, *blocks]))
    return np.asarray(features)


def run(data, output):
    output.mkdir(parents=True, exist_ok=False)
    with np.load(data / "train.npz", allow_pickle=False) as train:
        x = descriptor(train["atomic_numbers"], train["coords"])
        y = train["gap_ev"]
    estimators = {
        "atom_counts": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "geometry_trees": ExtraTreesRegressor(
            n_estimators=128, min_samples_leaf=2, random_state=2718, n_jobs=2
        ),
        "geometry_kernel": make_pipeline(
            StandardScaler(),
            Nystroem(gamma=1 / x.shape[1], n_components=512, random_state=2718),
            Ridge(alpha=0.01),
        ),
    }
    query = (
        json.loads((data / "QUERY.json").read_text()) if (data / "QUERY.json").exists() else None
    )
    targets = (
        query["contexts"]
        if query
        else [
            {"context_id": "small", "query_file": "small-validation.npz"},
            {"context_id": "large", "query_file": "large-validation.npz"},
        ]
    )
    results = []
    for method, estimator in estimators.items():
        started = time.monotonic()
        estimator.fit(x[:, :5] if method == "atom_counts" else x, y)
        for context in targets:
            with np.load(data / context["query_file"], allow_pickle=False) as target:
                features = descriptor(target["atomic_numbers"], target["coords"])
                predicted = estimator.predict(
                    features[:, :5] if method == "atom_counts" else features
                )
                name = f"{context['context_id']}--{method}.npz"
                np.savez_compressed(
                    output / name, molecule_id=target["molecule_id"], gap_ev=predicted
                )
                results.append(
                    {
                        "context": context["context_id"],
                        "method": method,
                        "prediction_file": name,
                        "mae_ev": float(np.abs(predicted - target["gap_ev"]).mean())
                        if "gap_ev" in target
                        else None,
                    }
                )
        print(
            json.dumps({"method": method, "duration_seconds": time.monotonic() - started}),
            flush=True,
        )
    (output / "RUN.json").write_text(
        json.dumps({"reference_only": True, "results": results}, indent=2)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.data, args.output)
