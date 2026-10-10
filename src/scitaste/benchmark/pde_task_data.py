"""Complete-trajectory endpoints for the authored PDEBench research adaptation."""

import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "stable-physical-rollout"


def primary_method(contract):
    method = contract.get("primary_method")
    if not isinstance(method, str) or method not in contract.get("methods", []):
        raise ValueError("Freeze one public-evidence-selected primary_method before READY")
    return method


def export_stage(pack, destination, *, submission=None):
    if submission is not None:
        primary_method(json.loads((submission / "SUBMISSION.json").read_text()))
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.pde-release.v1",
    )


def rollout_metrics(labels, predictions):
    ids, expected = predictions["trajectory_id"], labels["trajectory_id"]
    truth, proposed, valid = labels["state"], predictions["state"], predictions["valid"]
    n = len(expected)
    if (
        expected.ndim != 1
        or ids.ndim != 1
        or not n
        or not np.issubdtype(ids.dtype, np.integer)
        or len(np.unique(ids)) != n
        or len(np.unique(expected)) != n
        or set(ids) != set(expected)
        or proposed.shape != truth.shape
        or truth.ndim != 3
        or valid.shape != (n,)
        or valid.dtype != np.bool_
        or predictions["seconds"].shape != (n,)
        or not np.isrealobj(proposed)
        or not np.isrealobj(predictions["seconds"])
        or not np.isfinite(proposed).all()
        or not np.isfinite(truth).all()
        or not np.isfinite(predictions["seconds"]).all()
        or np.any(predictions["seconds"] < 0)
        or labels["initial"].shape != (n, truth.shape[2])
    ):
        raise ValueError("Require full unique trajectory coverage and finite typed outputs")
    lookup = dict(zip(ids.tolist(), range(n), strict=True))
    order = [lookup[int(i)] for i in expected]
    proposed, valid = proposed[order], valid[order]
    error = proposed.astype(float) - truth
    rmse = np.sqrt(np.mean(error**2, axis=(1, 2)))
    norm = np.maximum(np.sqrt(np.mean(truth.astype(float) ** 2, axis=(1, 2))), 1e-8)
    initial = labels["initial"].astype(float)
    mass_error = np.sqrt(np.mean(error.mean(axis=2) ** 2, axis=1))
    initial_mean = initial.mean(axis=1)
    mass_drift = np.max(np.abs(proposed.mean(axis=2) - initial_mean[:, None]), axis=1)
    energy = np.mean(proposed**2, axis=2)
    energy_with_initial = np.concatenate([np.mean(initial**2, axis=1)[:, None], energy], axis=1)
    # Positive change is descriptive, not a proof of physically invalid dynamics.
    energy_growth = np.max(np.maximum(np.diff(energy_with_initial, axis=1), 0), axis=1)
    spectrum = np.fft.rfft(error, axis=2, norm="ortho")
    bands = {"low": (1, 5), "middle": (5, 17), "high": (17, spectrum.shape[2])}
    complete = bool(valid.all())
    result = {
        "normalized_rmse_mean": float(np.mean(rmse / norm)) if complete else None,
        "rmse_mean": float(np.mean(rmse)) if complete else None,
        "normalized_rmse_p90": float(np.quantile(rmse / norm, 0.9)) if complete else None,
        "conserved_value_rmse_mean": float(np.mean(mass_error)) if complete else None,
        "mass_drift_max": float(np.max(mass_drift)) if complete else None,
        "energy_growth_max": float(np.max(energy_growth)) if complete else None,
        "declared_failure_fraction": float(np.mean(~valid)),
        "self_reported_cpu_seconds": float(predictions["seconds"].sum()),
        "trajectories": n,
        "timepoints_per_trajectory": truth.shape[1],
        "normalization_floor": 1e-8,
        "partial_outcome_policy": (
            "Any declared failure leaves the complete endpoint missing; "
            "no survivor average or zero imputation"
        ),
        "per_trajectory": [
            {
                "trajectory_id": int(expected[i]),
                "valid": bool(valid[i]),
                "normalized_rmse": float(rmse[i] / norm[i]) if valid[i] else None,
            }
            for i in range(n)
        ],
    }
    for band, (start, end) in bands.items():
        result[f"fourier_{band}_rmse"] = (
            float(np.sqrt(np.mean(np.abs(spectrum[:, :, start:end]) ** 2))) if complete else None
        )
    return result


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if receipt.get("phase") != "transfer" or not receipt.get("frozen_source"):
        raise ValueError("Need source-frozen confirmation")
    if receipt["pack_sha256"] != digest(pack / "PACK.json"):
        raise ValueError("Wrong confirmation pack")
    frozen = release.parent / "frozen_submission"
    for name, expected in receipt["frozen_source"].items():
        source = (frozen / name).resolve(strict=True)
        source.relative_to(frozen.resolve(strict=True))
        if digest(source) != expected:
            raise ValueError("Frozen source changed")
    contract = json.loads((frozen / "SUBMISSION.json").read_text())
    primary = primary_method(contract)
    manifest = json.loads((pack / "PACK.json").read_text())
    contexts, methods = manifest["confirmation_contexts"], contract["methods"]
    expected_files = {f"{c}--{m}.npz" for c in contexts for m in methods}
    if expected_files != {p.name for p in predictions.glob("*.npz") if p.is_file()}:
        raise ValueError("Score every frozen procedure/horizon jointly")
    scores = []
    for context in contexts:
        with np.load(bound_file(pack, manifest, f"private/{context}-labels.npz")) as labels:
            for method in methods:
                path = predictions / f"{context}--{method}.npz"
                with np.load(path, allow_pickle=False) as proposed:
                    if set(proposed.files) != {"trajectory_id", "state", "valid", "seconds"}:
                        raise ValueError("Unexpected prediction fields")
                    metrics = rollout_metrics(labels, proposed)
                scores.append(
                    {
                        "context": context,
                        "method": method,
                        "metrics": metrics,
                        "prediction_sha256": digest(path),
                    }
                )
    result = {
        "task_id": TASK_ID,
        "status": "scored-all-predeclared-procedures",
        "primary_method": primary,
        "primary_endpoint": "normalized_rmse_mean",
        "primary_scores": {
            r["context"]: r["metrics"]["normalized_rmse_mean"]
            for r in scores
            if r["method"] == primary
        },
        "scores": scores,
        "task_families": 1,
        "pack_sha256": digest(pack / "PACK.json"),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": (
            "Authored coarse-grid new-identity PDEBench adaptation; "
            "not the original leaderboard or unseen temporal distribution"
        ),
    }
    destination = release.parent / "confirmation/RESULT.json"
    retain_json(destination, result)
    return destination


def target_assets(pack):
    manifest = json.loads((pack / "PACK.json").read_text())
    return [
        Path(name).name
        for name in [*manifest["discovery_files"], *manifest["transfer_files"]]
        if name.endswith(".npz") or Path(name).name == "QUERY.json"
    ]
