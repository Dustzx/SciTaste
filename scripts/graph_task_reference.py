"""Fixed, low-cost scientific controls; not autonomous researchers or SOTA models.

This file is copied verbatim into the public research bundle. It accepts only the
redacted graph interface and never reads source archives or evaluator labels.
"""

import argparse
import hashlib
import json
import time
import warnings
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

METHODS = ("features", "neighbors", "shuffled_messages", "label_diffusion")


def row_operator(edges, nodes):
    """Undirected, deduplicated, no self-loops; isolated rows remain zero."""
    edges = np.asarray(edges, dtype=np.int64)
    source = np.concatenate([edges[:, 0], edges[:, 1]])
    target = np.concatenate([edges[:, 1], edges[:, 0]])
    keep = source != target
    adjacency = sparse.csr_matrix(
        (np.ones(keep.sum()), (source[keep], target[keep])), shape=(nodes, nodes)
    )
    adjacency.data[:] = 1
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    return sparse.diags(1 / np.maximum(degree, 1)) @ adjacency


def metrics(labels, probabilities):
    result = {"accuracy": float(accuracy_score(labels, probabilities.argmax(axis=1)))}
    if probabilities.shape[1] == 2:
        result["roc_auc"] = float(roc_auc_score(labels, probabilities[:, 1]))
    return result


def run(data, output):
    if output.exists():
        raise ValueError("Reference output must be new; retain earlier attempts")
    output.mkdir(parents=True)
    receipt = {"runs": [], "status": "running", "reference_only": True}
    for path in sorted(data.glob("*.npz")):
        with np.load(path, allow_pickle=False) as archive:
            graph = {key: archive[key] for key in archive.files}
        x, y, train = graph["x"], graph["y"], graph["train_mask"]
        classes = int(graph["num_classes"])
        if np.any(y[train] < 0) or set(np.unique(y[train])) != set(range(classes)):
            raise ValueError("Training partition must cover declared classes")
        operator = row_operator(graph["edges"], len(x))
        permutation = np.random.default_rng(2718).permutation(len(x))
        for method in METHODS:
            started = time.monotonic()
            messages = []
            if method == "label_diffusion":
                # Training-free here means no optimized model parameters. It is
                # still supervised inference, conditioned on training labels.
                seeds = np.zeros((len(x), classes))
                seeds[np.flatnonzero(train), y[train]] = 1
                probabilities = seeds.copy()
                for _ in range(20):
                    probabilities = 0.8 * (operator @ probabilities) + 0.2 * seeds
                prior = np.bincount(y[train], minlength=classes) / train.sum()
                empty = probabilities.sum(axis=1) == 0
                probabilities[empty] = prior
                probabilities /= probabilities.sum(axis=1, keepdims=True)
                fitted_parameters, iterations, width = False, 20, 0
            else:
                # Same ego features; shuffle only messages, not ego features or
                # labels. This preserves message-feature marginals but not the
                # distribution of aggregated messages or a causal intervention.
                if method == "features":
                    features = x
                else:
                    messages_x = x[permutation] if method == "shuffled_messages" else x
                    features = np.concatenate([x, operator @ messages_x], axis=1)
                scaler = StandardScaler().fit(features[train])
                features = scaler.transform(features)
                estimator = LogisticRegression(C=1.0, max_iter=300, tol=1e-5)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    estimator.fit(features[train], y[train])
                messages = [str(item.message) for item in caught]
                probabilities = estimator.predict_proba(features)
                fitted_parameters, iterations, width = (
                    True,
                    estimator.n_iter_.tolist(),
                    features.shape[1],
                )
            predicted = output / f"{path.stem}--{method}.npz"
            np.savez_compressed(
                predicted, node_id=np.arange(len(x), dtype=np.int64), probabilities=probabilities
            )
            validation = graph["val_mask"]
            result = {
                "graph": path.stem,
                "method": method,
                "duration_seconds": time.monotonic() - started,
                "data_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "prediction_file": predicted.name,
                "prediction_sha256": hashlib.sha256(predicted.read_bytes()).hexdigest(),
                "fitted_parameters": fitted_parameters,
                "iterations": iterations,
                "feature_width": width,
                "warnings": messages,
                "validation": metrics(y[validation], probabilities[validation])
                if validation.any()
                else None,
            }
            receipt["runs"].append(result)
            (output / "RUN.json").write_text(json.dumps(receipt, indent=2, allow_nan=False))
            print(
                json.dumps({k: result[k] for k in ("graph", "method", "duration_seconds")}),
                flush=True,
            )
    receipt["status"] = "completed"
    (output / "RUN.json").write_text(json.dumps(receipt, indent=2, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.data, args.output)
