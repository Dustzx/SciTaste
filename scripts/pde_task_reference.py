"""Ordinary public solvability controls, not autonomous research-system scores."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

METHODS = ["persistence", "finite_volume", "local_ridge", "mean_projected", "damped"]
DIFFUSION = 0.01 / np.pi


def features(u):
    shifts = [np.roll(u, k, axis=-1) for k in (-2, -1, 0, 1, 2)]
    return np.stack(
        [
            *shifts,
            shifts[1] ** 2,
            shifts[2] ** 2,
            shifts[3] ** 2,
            shifts[1] * shifts[2],
            shifts[2] * shifts[3],
            np.ones_like(u),
        ],
        axis=-1,
    )


def fit(train):
    state = train["state"].astype(float)
    dt = float(train["time"][1] - train["time"][0])
    dimension = 11
    xx, xy = np.zeros((dimension, dimension)), np.zeros(dimension)
    for start in range(0, len(state), 16):
        block = state[start : start + 16]
        x = features(block[:, :-1]).reshape(-1, dimension)
        y = ((block[:, 1:] - block[:, :-1]) / dt).reshape(-1)
        xx += x.T @ x
        xy += x.T @ y
    scale = np.sqrt(np.maximum(np.diag(xx), 1e-12))
    normalized = xx / (scale[:, None] * scale[None, :])
    coefficient = np.linalg.solve(normalized + 1e-4 * np.eye(dimension), xy / scale) / scale
    return coefficient


def fv_step(u, step, dx):
    right = np.roll(u, -1, axis=-1)
    speed = np.maximum(np.abs(u), np.abs(right))
    flux = (u * u + right * right) / 4 - speed * (right - u) / 2
    convection = -(flux - np.roll(flux, 1, axis=-1)) / dx
    diffusion = DIFFUSION * (right - 2 * u + np.roll(u, 1, axis=-1)) / (dx * dx)
    return u + step * (convection + diffusion)


def rollout(initial, times, x, method, coefficient):
    started = time.monotonic()
    u = initial.astype(float).copy()
    output, valid = [], np.ones(len(u), dtype=bool)
    initial_mean = u.mean(axis=1, keepdims=True)
    # A declared operational failure, not a hidden output repair.
    failure_bound = 10 * np.maximum(np.max(np.abs(u), axis=1), 1.0)
    clock, dx = 0.0, float(x[1] - x[0])
    for target in times:
        if method != "persistence":
            while clock < float(target) - 1e-10:
                if method == "finite_volume":
                    step = min(
                        float(target) - clock,
                        0.25 * dx / max(float(np.max(np.abs(u))), 1),
                        0.2 * dx * dx / DIFFUSION,
                    )
                    u = fv_step(u, step, dx)
                else:
                    step = min(float(target) - clock, 0.005)
                    with np.errstate(over="ignore", invalid="ignore"):
                        u += step * np.einsum("nxd,d->nx", features(u), coefficient)
                    if method in ("mean_projected", "damped"):
                        u += initial_mean - u.mean(axis=1, keepdims=True)
                    if method == "damped":
                        # Fixed smoothing; its useful effect is not a physical explanation.
                        rate = min(1.0, step * 2)
                        u = (1 - rate) * u + rate * (
                            np.roll(u, -1, axis=-1) + 2 * u + np.roll(u, 1, axis=-1)
                        ) / 4
                bad = (~np.isfinite(u).all(axis=1)) | (np.max(np.abs(u), axis=1) > failure_bound)
                valid &= ~bad
                u[~valid] = 0
                clock += step
        output.append(u.copy())
    prediction = np.stack(output, axis=1)
    prediction[~valid] = 0
    seconds = np.full(len(u), (time.monotonic() - started) / len(u))
    return prediction, valid, seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with np.load(args.data / "train.npz") as train:
        fit_start = time.monotonic()
        coefficient = fit(train)
        fit_seconds = time.monotonic() - fit_start
    query_path = args.data / "QUERY.json"
    contexts = (
        json.loads(query_path.read_text())["contexts"]
        if query_path.exists()
        else {"discovery": "discovery.npz", "validation": "validation.npz"}
    )
    records = []
    for context, filename in contexts.items():
        with np.load(args.data / filename) as query:
            times = query["time"] if query_path.exists() else query["time"][1:]
            for method in METHODS:
                predicted, valid, seconds = rollout(
                    query["initial"], times, query["x"], method, coefficient
                )
                np.savez_compressed(
                    args.output / f"{context}--{method}.npz",
                    trajectory_id=query["trajectory_id"],
                    state=predicted,
                    valid=valid,
                    seconds=seconds,
                )
                if "state" in query:
                    for horizon, mask in {
                        "early": times <= 1 + 1e-6,
                        "late": times > 1 + 1e-6,
                    }.items():
                        truth = query["state"][:, 1:][:, mask]
                        error = predicted[:, mask] - truth
                        rmse = np.sqrt(np.mean(error**2, axis=(1, 2)))
                        norm = np.maximum(
                            np.sqrt(np.mean(truth.astype(float) ** 2, axis=(1, 2))), 1e-8
                        )
                        records.append(
                            {
                                "context": context,
                                "horizon": horizon,
                                "method": method,
                                "normalized_rmse_mean": float(np.mean(rmse / norm))
                                if valid.all()
                                else None,
                                "failure_fraction": float(np.mean(~valid)),
                                "seconds": float(seconds.sum()),
                            }
                        )
    receipt = {
        "scope": "ordinary public solvability controls, not framework outcomes or SOTA",
        "records": records,
        "fit_seconds": fit_seconds,
        "wall_seconds": time.monotonic() - started,
        "diffusion": DIFFUSION,
        "ridge_regularization": 1e-4,
        "learned_substep_seconds": 0.005,
        "failure_bound": "10*max(initial_Linf,1)",
        "training_only": True,
        "gpu_enabled": False,
        "methods": METHODS,
    }
    (args.output / "PUBLIC_REFERENCE.json").write_text(
        json.dumps(receipt, indent=2, allow_nan=False)
    )
    print(json.dumps(receipt, allow_nan=False))


if __name__ == "__main__":
    main()
