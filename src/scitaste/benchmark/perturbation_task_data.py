"""Failure-inclusive outcomes for condition-held-out expression research.

Predictive accuracy is not a genetic-interaction discovery certificate. A metric
receipt does not establish execution; the outer runner must bind actual inference.
"""

import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "combinatorial-perturbation"


def primary_method(contract):
    method = contract.get("primary_method")
    if not isinstance(method, str) or method not in contract.get("methods", []):
        raise ValueError("Freeze one publicly selected primary before READY")
    return method


def export_stage(pack, destination, *, submission=None):
    if submission is not None:
        primary_method(json.loads((submission / "SUBMISSION.json").read_text()))
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.perturbation-release.v1",
    )


def correlation(left, right):
    left = left - left.mean(axis=1, keepdims=True)
    right = right - right.mean(axis=1, keepdims=True)
    denominator = np.linalg.norm(left, axis=1) * np.linalg.norm(right, axis=1)
    return [
        float(np.dot(a, b) / d) if d > 1e-12 else None
        for a, b, d in zip(left, right, denominator, strict=True)
    ]


def perturbation_metrics(labels, predictions):
    expected, ids = labels["condition_id"], predictions["condition_id"]
    n = len(expected)
    truth, proposed = labels["expression"], predictions["expression"]
    if (
        expected.ndim != 1
        or ids.ndim != 1
        or not n
        or not np.issubdtype(ids.dtype, np.integer)
        or len(np.unique(ids)) != n
        or len(np.unique(expected)) != n
        or set(ids) != set(expected)
        or truth.shape != (n, 1000)
        or proposed.shape != truth.shape
        or not np.isrealobj(proposed)
        or not np.isfinite(proposed).all()
        or not np.isfinite(truth).all()
        or predictions["valid"].shape != (n,)
        or predictions["valid"].dtype != np.bool_
        or predictions["seconds"].shape != (n,)
        or not np.isrealobj(predictions["seconds"])
        or not np.isfinite(predictions["seconds"]).all()
        or np.any(predictions["seconds"] < 0)
    ):
        raise ValueError("Require all unique conditions and finite typed expression outputs")
    lookup = dict(zip(ids.tolist(), range(n), strict=True))
    order = [lookup[int(i)] for i in expected]
    forecast, valid = proposed[order].astype(float), predictions["valid"][order]
    control, singles, parts = labels["control"], labels["single_expression"], labels["perturbation"]
    if (
        control.shape != (1000,)
        or singles.shape != (101, 1000)
        or parts.shape != (n, 2)
        or np.any(parts < 0)
        or np.any(parts >= 101)
    ):
        raise ValueError("Bound query must contain declared double perturbations and fitting means")
    additive = singles[parts[:, 0]] + singles[parts[:, 1]] - control
    error = np.mean((forecast - truth) ** 2, axis=1)
    reference_error = np.mean((additive - truth) ** 2, axis=1)
    rmses = np.sqrt(error)
    delta = correlation(forecast - control, truth - control)
    residual = correlation(forecast - additive, truth - additive)
    complete = bool(valid.all())
    if not np.isfinite(rmses).all() or not np.isfinite(reference_error).all():
        raise ValueError("Numerically unscoreable; no clipping or silent repair")

    def average_defined(values):
        defined = [v for v in values if v is not None]
        return float(np.mean(defined)) if complete and defined else None

    return {
        "mean_condition_rmse": float(rmses.mean()) if complete else None,
        "median_condition_rmse": float(np.median(rmses)) if complete else None,
        "mean_squared_error": float(error.mean()) if complete else None,
        "additive_reference_mse": float(reference_error.mean()),
        "ratio_to_additive_mse": float(error.mean() / reference_error.mean())
        if complete and reference_error.mean() > 1e-12
        else None,
        "mean_pearson_delta": average_defined(delta),
        "defined_pearson_delta_conditions": sum(v is not None for v in delta),
        "mean_additive_residual_correlation": average_defined(residual),
        "defined_residual_correlation_conditions": sum(v is not None for v in residual),
        "conditions": n,
        "readout_genes": 1000,
        "declared_failure_fraction": float(np.mean(~valid)),
        "self_reported_cpu_seconds": float(predictions["seconds"].sum()),
        "metric_scope": (
            "Same-assay expression prediction; undefined correlations null. Not "
            "genetic-interaction discovery, assay replication or calibrated biological truth."
        ),
        "partial_outcome_policy": (
            "Any failure leaves complete endpoint missing, not survivor average"
        ),
        "per_condition": [
            {
                "condition_id": int(i),
                "valid": bool(v),
                "rmse": float(r) if v else None,
                "pearson_delta": d if v else None,
                "additive_residual_correlation": c if v else None,
                "split_half_rmse": float(s),
            }
            for i, v, r, d, c, s in zip(
                expected, valid, rmses, delta, residual, labels["split_half_rmse"], strict=True
            )
        ],
        "split_half_scope": (
            "Alternating source cells, not independent biological replicates "
            "or a proven noise ceiling"
        ),
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if (
        receipt.get("phase") != "transfer"
        or not receipt.get("frozen_source")
        or receipt["pack_sha256"] != digest(pack / "PACK.json")
    ):
        raise ValueError("Require exact bound source-frozen release")
    frozen = release.parent / "frozen_submission"
    for name, expected in receipt["frozen_source"].items():
        path = (frozen / name).resolve(strict=True)
        path.relative_to(frozen.resolve(strict=True))
        if digest(path) != expected:
            raise ValueError("Frozen source changed")
    contract = json.loads((frozen / "SUBMISSION.json").read_text())
    primary = primary_method(contract)
    manifest = json.loads((pack / "PACK.json").read_text())
    expected_files = {
        f"{context}--{method}.npz"
        for context in manifest["confirmation_contexts"]
        for method in contract["methods"]
    }
    found = {p.name for p in predictions.glob("*.npz") if p.is_file() or p.is_symlink()}
    extras = sorted(found - expected_files)
    records = []
    for context in manifest["confirmation_contexts"]:
        with np.load(
            bound_file(pack, manifest, f"private/{context}-labels.npz"), allow_pickle=False
        ) as labels:
            for method in contract["methods"]:
                path = predictions / f"{context}--{method}.npz"
                try:
                    if extras:
                        raise ValueError("Undeclared root NPZ outputs invalidate the contract")
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("Require regular retained prediction")
                    with np.load(path, allow_pickle=False) as proposed:
                        if set(proposed.files) != {
                            "condition_id",
                            "expression",
                            "valid",
                            "seconds",
                        }:
                            raise ValueError("Unexpected prediction fields")
                        metrics = perturbation_metrics(labels, proposed)
                    failed = None
                except Exception as exc:
                    # Only untrusted model output parsing; frozen/private asset
                    # corruption above stays fail-closed, outside this catch.
                    failed = type(exc).__name__
                    metrics = {
                        "mean_condition_rmse": None,
                        "conditions": len(labels["condition_id"]),
                        "declared_failure_fraction": 1.0,
                        "failure": failed,
                    }
                records.append(
                    {
                        "context": context,
                        "method": method,
                        "metrics": metrics,
                        "prediction_sha256": digest(path)
                        if path.is_file() and not path.is_symlink()
                        else None,
                        "failure": failed,
                    }
                )
    result = {
        "task_id": TASK_ID,
        "status": "scored-all-predeclared-procedures",
        "primary_method": primary,
        "primary_endpoint": "mean_condition_rmse",
        "primary_scores": {
            r["context"]: r["metrics"]["mean_condition_rmse"]
            for r in records
            if r["method"] == primary
        },
        "scores": records,
        "all_predeclared_method_context_records_retained": True,
        "missing_prediction_files": sorted(expected_files - found),
        "undeclared_npz_files": extras,
        "output_contract_valid": not extras and all(row["failure"] is None for row in records),
        "task_families": 1,
        "pack_sha256": digest(pack / "PACK.json"),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": (
            "Condition-held-out same-K562-assay adaptation; not original published "
            "ranking or novel genetic-interaction certification"
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
