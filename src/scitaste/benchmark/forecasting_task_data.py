"""Complete, identity-bound outcomes for the authored M4 research adaptation."""

import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "cross-series-forecasting"


def primary_method(contract):
    method = contract.get("primary_method")
    if not isinstance(method, str) or method not in contract.get("methods", []):
        raise ValueError("Freeze one public-selected primary_method before READY")
    return method


def export_stage(pack, destination, *, submission=None):
    if submission is not None:
        primary_method(json.loads((submission / "SUBMISSION.json").read_text()))
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.forecasting-release.v1",
    )


def forecasting_metrics(labels, predictions):
    expected, ids = labels["series_id"], predictions["series_id"]
    truth, proposed = labels["future"], predictions["forecast"]
    n = len(expected)
    if (
        expected.ndim != 1
        or ids.ndim != 1
        or not n
        or not np.issubdtype(ids.dtype, np.integer)
        or len(np.unique(ids)) != n
        or len(np.unique(expected)) != n
        or set(ids) != set(expected)
        or truth.shape != (n, 18)
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
        or labels["history"].shape != (n, 360)
        or labels["history_length"].shape != (n,)
        or not np.issubdtype(labels["history_length"].dtype, np.integer)
        or np.any(labels["history_length"] < 72)
        or np.any(labels["history_length"] > 360)
        or not np.isfinite(labels["history"]).all()
    ):
        raise ValueError("Require full unique series coverage and finite, typed forecast outputs")
    lookup = dict(zip(ids.tolist(), range(n), strict=True))
    order = [lookup[int(i)] for i in expected]
    forecast = proposed[order].astype(float)
    valid = predictions["valid"][order]
    scales = np.asarray(
        [
            np.mean(np.abs(row[-int(length) + 12 :] - row[-int(length) : -12]))
            for row, length in zip(labels["history"], labels["history_length"], strict=True)
        ]
    )
    error = np.abs(forecast - truth.astype(float))
    mae = error.mean(axis=1)
    mase = mae / np.maximum(scales, 1e-8)
    denominator = np.abs(forecast) + np.abs(truth)
    smape = (
        200 * np.divide(error, denominator, out=np.zeros_like(error), where=denominator > 0)
    ).mean(axis=1)
    if not np.isfinite(mase).all() or not np.isfinite(smape).all():
        raise ValueError("Numerically unscoreable forecast; do not clip or silently repair")
    complete = bool(valid.all())
    # Fixed input-only diagnostic; not a discovered/private-outcome-selected partition.
    change = np.abs(
        labels["history"][:, -12:].mean(axis=1) - labels["history"][:, -24:-12].mean(axis=1)
    ) / np.maximum(scales, 1e-8)
    groups = []
    for name, mask in {
        "recent_change_at_least_one_scale": change >= 1,
        "other": change < 1,
    }.items():
        groups.append(
            {
                "group": name,
                "series": int(mask.sum()),
                "mean_mase": float(mase[mask].mean()) if complete and mask.any() else None,
            }
        )
    return {
        "mean_mase": float(mase.mean()) if complete else None,
        "median_mase": float(np.median(mase)) if complete else None,
        "p90_mase": float(np.quantile(mase, 0.9)) if complete else None,
        "mean_smape_percent": float(smape.mean()) if complete else None,
        "smape_scope": "Legacy diagnostic; zero/zero=0. Not an original M4 OWA/ranking.",
        "scale_floor": 1e-8,
        "scale_floor_count": int(np.sum(scales < 1e-8)),
        "declared_failure_fraction": float(np.mean(~valid)),
        "self_reported_cpu_seconds": float(predictions["seconds"].sum()),
        "series": n,
        "horizon": 18,
        "period": 12,
        "input_only_groups": groups,
        "recent_change_rule": (
            "abs(mean(last12)-mean(previous12))/max(seasonal_difference_scale,1e-8)>=1; "
            "not a certified structural break"
        ),
        "absolute_error_scope": (
            "Per-series original units; no meaningful cross-unit absolute-error aggregate claimed"
        ),
        "partial_outcome_policy": (
            "Any failure leaves the complete endpoint missing; "
            "no survivor average or zero-imputed success"
        ),
        "per_series": [
            {
                "series_id": int(expected[i]),
                "valid": bool(valid[i]),
                "mase": float(mase[i]) if valid[i] else None,
                "mae_source_units": float(mae[i]) if valid[i] else None,
                "seasonal_scale": float(scales[i]),
            }
            for i in range(n)
        ],
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if (
        receipt.get("phase") != "transfer"
        or not receipt.get("frozen_source")
        or receipt["pack_sha256"] != digest(pack / "PACK.json")
    ):
        raise ValueError("Need matching source-frozen confirmation")
    frozen = release.parent / "frozen_submission"
    for name, expected in receipt["frozen_source"].items():
        path = (frozen / name).resolve(strict=True)
        path.relative_to(frozen.resolve(strict=True))
        if digest(path) != expected:
            raise ValueError("Frozen source changed")
    contract = json.loads((frozen / "SUBMISSION.json").read_text())
    primary = primary_method(contract)
    manifest = json.loads((pack / "PACK.json").read_text())
    contexts = manifest["confirmation_contexts"]
    methods = contract["methods"]
    if {f"{c}--{m}.npz" for c in contexts for m in methods} != {
        p.name for p in predictions.glob("*.npz") if p.is_file()
    }:
        raise ValueError("Score every predeclared forecast procedure jointly")
    records = []
    for context in contexts:
        with np.load(
            bound_file(pack, manifest, f"private/{context}-labels.npz"), allow_pickle=False
        ) as labels:
            for method in methods:
                path = predictions / f"{context}--{method}.npz"
                with np.load(path, allow_pickle=False) as proposed:
                    if set(proposed.files) != {"series_id", "forecast", "valid", "seconds"}:
                        raise ValueError("Unexpected forecast output fields")
                    metrics = forecasting_metrics(labels, proposed)
                records.append(
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
        "primary_endpoint": "mean_mase",
        "primary_scores": {
            r["context"]: r["metrics"]["mean_mase"] for r in records if r["method"] == primary
        },
        "scores": records,
        "task_families": 1,
        "pack_sha256": digest(pack / "PACK.json"),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": (
            "Authored new-series capped-history M4 monthly adaptation; "
            "not official full M4 ranking or unseen temporal distribution"
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
