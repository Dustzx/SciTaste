"""Fixed label-conditioned molecular controls, not SOTA or autonomous researchers.

Only researcher exports are read. No gradient optimization or model API is used;
nearest-exemplar inference is nevertheless supervised by the training force labels.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.spatial.distance import cdist

METHODS = ("aligned_nearest", "shuffled_risk", "unaligned_nearest", "zero_force")


def descriptor(coords):
    i, j = np.triu_indices(coords.shape[1], 1)
    return np.linalg.norm(coords[:, i] - coords[:, j], axis=2)


def nearest_reference(train, query):
    train_coords, query_coords = train["coords"], query["coords"]
    if not np.array_equal(train["atomic_numbers"], query["atomic_numbers"]):
        raise ValueError("Reference preserves fixed source atom identities")
    train_desc, query_desc = descriptor(train_coords), descriptor(query_coords)
    # No learned scaling, label-based neighbor selection or validation tuning.
    distances = cdist(query_desc, train_desc, metric="sqeuclidean")
    nearest = distances.argmin(axis=1)
    risk = np.sqrt(distances[np.arange(len(query_coords)), nearest] / train_desc.shape[1])
    raw = train["forces"][nearest].copy()
    aligned = np.empty_like(raw)
    for row, exemplar in enumerate(nearest):
        a = train_coords[exemplar] - train_coords[exemplar].mean(axis=0)
        b = query_coords[row] - query_coords[row].mean(axis=0)
        u, _, vt = np.linalg.svd(a.T @ b)
        correction = np.diag([1.0, 1.0, np.linalg.det(u @ vt)])
        rotation = u @ correction @ vt
        aligned[row] = raw[row] @ rotation
    return aligned, raw, risk


def transformation_audit(train, query, predictions, risk):
    """Deterministic rigid transformation consistency, not a force-error score."""
    # Only 64 label-free queries are needed for this execution invariant. It is
    # not an additional task, experiment replication or molecular dynamics test.
    count = min(64, len(query["coords"]))
    angle = 0.731
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
    )
    transformed = {
        "coords": query["coords"][:count] @ rotation + np.array([0.23, -0.41, 0.17]),
        "atomic_numbers": query["atomic_numbers"],
    }
    rotated, _, new_risk = nearest_reference(train, transformed)
    return {
        "query_frames": count,
        "rotation_force_max_abs_deviation": float(
            np.abs(rotated - predictions[:count] @ rotation).max()
        ),
        "geometry_risk_max_abs_deviation": float(np.abs(new_risk - risk[:count]).max()),
        "expected_to_be_equivariant": True,
        "does_not_establish_accuracy_conservativity_or_stable_dynamics": True,
    }


def run(data, output):
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "status": "running",
        "reference_only": True,
        "parameter_search": False,
        "fitted_parameters": False,
        "supervision": "stored training geometries and their force vectors",
        "runs": [],
    }
    for path in sorted(data.glob("*-query.npz")):
        molecule = path.name.removesuffix("-query.npz")
        train_path = data / f"{molecule}-train.npz"
        with np.load(train_path, allow_pickle=False) as archive:
            train = {key: archive[key] for key in archive.files}
        with np.load(path, allow_pickle=False) as archive:
            query = {key: archive[key] for key in archive.files}
        started = time.monotonic()
        aligned, raw, risk = nearest_reference(train, query)
        inference_seconds = time.monotonic() - started
        audit = transformation_audit(train, query, aligned, risk)
        shuffled = risk[np.random.default_rng(2718).permutation(len(risk))]
        for method in METHODS:
            predictions = raw if method == "unaligned_nearest" else aligned
            scores = shuffled if method == "shuffled_risk" else risk
            if method == "zero_force":
                predictions, scores = np.zeros_like(raw), np.zeros(len(risk))
            predicted = output / f"{molecule}--{method}.npz"
            np.savez_compressed(
                predicted,
                frame_id=query["frame_id"],
                forces=predictions,
                risk_score=scores,
            )
            receipt["runs"].append(
                {
                    "molecule": molecule,
                    "method": method,
                    "prediction_file": predicted.name,
                    "prediction_sha256": hashlib.sha256(predicted.read_bytes()).hexdigest(),
                    "train_sha256": hashlib.sha256(train_path.read_bytes()).hexdigest(),
                    "query_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "training_configurations": len(train["coords"]),
                    "query_configurations": len(query["coords"]),
                    "shared_nearest_inference_seconds": inference_seconds,
                    "shared_compute_note": "all four controls reuse one neighbor computation",
                    "rigid_transform_audit": audit if method == "aligned_nearest" else None,
                }
            )
        with (output / "RUN.json").open("w") as stream:
            json.dump(receipt, stream, indent=2, allow_nan=False)
        print(
            json.dumps(
                {
                    "molecule": molecule,
                    "query_frames": len(query["coords"]),
                    "inference_seconds": inference_seconds,
                    "methods": len(METHODS),
                }
            ),
            flush=True,
        )
    if not receipt["runs"]:
        raise ValueError("No staged molecular query assets found")
    receipt["status"] = "completed"
    with (output / "RUN.json").open("w") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.data, args.output)
