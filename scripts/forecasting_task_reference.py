"""Ordinary public forecast controls, not autonomous system or SOTA outcomes."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

METHODS = [
    "naive",
    "seasonal",
    "drift",
    "pooled_raw",
    "pooled_normalized",
    "pooled_balanced_raw",
    "pooled_level_normalized",
]
HORIZON, PERIOD, LAGS = 18, 12, 36


def fit(train, normalized):
    xs, ys = [], []
    for raw, length in zip(train["history"], train["history_length"], strict=True):
        history = raw[-int(length) :]
        for end in range(len(history) - HORIZON, LAGS - 1, -HORIZON):
            window, future = history[end - LAGS : end], history[end : end + HORIZON]
            center = float(window.mean()) if normalized else 0.0
            scale = max(float(window.std()), 1e-8) if normalized else 1.0
            xs.append(np.r_[((window - center) / scale), 1.0])
            ys.append((future - center) / scale)
    x, y = np.asarray(xs), np.asarray(ys)
    x_scale = np.sqrt(np.maximum(np.sum(x * x, axis=0), 1e-12))
    z = x / x_scale
    coefficient = np.linalg.solve(z.T @ z + 1e-3 * np.eye(LAGS + 1), z.T @ y) / x_scale[:, None]
    return coefficient, len(x)


def predict(history, length, method, coefficients):
    data = history[-int(length) :]
    if method == "naive":
        return np.full(HORIZON, data[-1])
    if method == "seasonal":
        return np.resize(data[-PERIOD:], HORIZON)
    if method == "drift":
        return data[-1] + np.arange(1, HORIZON + 1) * (data[-1] - data[0]) / (len(data) - 1)
    window = data[-LAGS:]
    if method in {"pooled_balanced_raw", "pooled_level_normalized"}:
        normalized = method == "pooled_level_normalized"
        coefficient, floor = coefficients[method]
        center = float(window.mean()) if normalized else 0.0
        scale = max(float(np.sqrt(np.mean(window * window))), floor) if normalized else 1.0
        return (np.r_[((window - center) / scale), 1.0] @ coefficient) * scale + center
    normalized = method == "pooled_normalized"
    center = float(window.mean()) if normalized else 0.0
    scale = max(float(window.std()), 1e-8) if normalized else 1.0
    return (np.r_[((window - center) / scale), 1.0] @ coefficients[method]) * scale + center


def fit_stable(train, normalized):
    """Same windows and per-series weights; separate normalized loss geometry.

    The scale floor uses training inputs only and scales with common unit changes.
    No rows are excluded using continuations, public forecasts or private labels.
    """
    windows = []
    for raw, length in zip(train["history"], train["history_length"], strict=True):
        history = raw[-int(length) :]
        ends = list(range(len(history) - HORIZON, LAGS - 1, -HORIZON))
        for end in ends:
            windows.append((history[end - LAGS : end], history[end : end + HORIZON], 1 / len(ends)))
    rms = np.asarray([np.sqrt(np.mean(window * window)) for window, _, _ in windows])
    positive = rms[rms > 0]
    floor = float(np.median(positive)) * 0.01 if len(positive) else 1.0
    xs, ys, weights = [], [], []
    for window, future, weight in windows:
        center = float(window.mean()) if normalized else 0.0
        scale = max(float(np.sqrt(np.mean(window * window))), floor) if normalized else 1.0
        xs.append(np.r_[(window - center) / scale, 1.0])
        ys.append((future - center) / scale)
        weights.append(weight)
    x, y, w = np.asarray(xs), np.asarray(ys), np.sqrt(weights)
    x, y = x * w[:, None], y * w[:, None]
    column_scale = np.sqrt(np.maximum(np.sum(x * x, axis=0), 1e-12))
    z = x / column_scale
    coefficient = np.linalg.solve(z.T @ z + 1e-3 * np.eye(LAGS + 1), z.T @ y)
    coefficient /= column_scale[:, None]
    return (
        (coefficient, floor),
        len(windows),
        {
            "input_only_training_rms_floor": floor,
            "degenerate_scale_floor_fraction": float(np.mean(rms < floor)),
            "window_weight": "1 / permitted rolling-window count of that training series",
            "loss": "squared error in transformed target units"
            if normalized
            else "squared original-unit error",
            "normalization_not_isolated_one_factor": True,
        },
    )


def metrics(history, length, truth, forecast, valid):
    scales = np.asarray(
        [
            np.mean(np.abs(row[-int(n) + PERIOD :] - row[-int(n) : -PERIOD]))
            for row, n in zip(history, length, strict=True)
        ]
    )
    error = forecast - truth
    mase = np.mean(np.abs(error), axis=1) / np.maximum(scales, 1e-8)
    return {
        "mean_mase": float(mase.mean()) if valid.all() else None,
        "median_mase": float(np.median(mase)) if valid.all() else None,
        "failure_fraction": float(np.mean(~valid)),
        "scale_floor_count": int(np.sum(scales < 1e-8)),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    coefficient = {}
    fits = []
    with np.load(a.data / "train.npz") as train:
        for name, normalized in [("pooled_raw", False), ("pooled_normalized", True)]:
            s = time.monotonic()
            coefficient[name], count = fit(train, normalized)
            fits.append({"method": name, "windows": count, "seconds": time.monotonic() - s})
        for name, normalized in [("pooled_balanced_raw", False), ("pooled_level_normalized", True)]:
            s = time.monotonic()
            coefficient[name], count, policy = fit_stable(train, normalized)
            fits.append(
                {
                    "method": name,
                    "windows": count,
                    "seconds": time.monotonic() - s,
                    "policy": policy,
                }
            )
    query = a.data / "QUERY.json"
    contexts = (
        json.loads(query.read_text())["contexts"]
        if query.exists()
        else {"discovery": "discovery.npz", "validation": "validation.npz"}
    )
    records = []
    for context, filename in contexts.items():
        with np.load(a.data / filename) as data:
            for method in METHODS:
                begun = time.monotonic()
                forecast = np.asarray(
                    [
                        predict(row, n, method, coefficient)
                        for row, n in zip(data["history"], data["history_length"], strict=True)
                    ]
                )
                valid = np.isfinite(forecast).all(axis=1)
                forecast[~valid] = 0
                seconds = np.full(len(forecast), (time.monotonic() - begun) / len(forecast))
                np.savez_compressed(
                    a.output / f"{context}--{method}.npz",
                    series_id=data["series_id"],
                    forecast=forecast,
                    valid=valid,
                    seconds=seconds,
                )
                if "future" in data:
                    records.append(
                        {
                            "context": context,
                            "method": method,
                            **metrics(
                                data["history"],
                                data["history_length"],
                                data["future"],
                                forecast,
                                valid,
                            ),
                            "seconds": float(seconds.sum()),
                        }
                    )
    result = {
        "scope": (
            "Ordinary public feasibility controls only; not modern forecast SOTA "
            "or autonomous research results"
        ),
        "records": records,
        "fit": fits,
        "wall_seconds": time.monotonic() - started,
        "global_fit_only_training_histories": True,
        "gpu_enabled": False,
        "methods": METHODS,
        "legacy_pooled_normalized_is_pathological_diagnostic": True,
    }
    (a.output / "PUBLIC_REFERENCE.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
