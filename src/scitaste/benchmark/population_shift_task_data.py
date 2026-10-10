"""Weighted probability outcomes for one authored ACS population-shift task."""

import json

import numpy as np
from sklearn.metrics import roc_auc_score

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "population-shift-calibration"


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
        release_schema="scitastebench.population-shift-release.v1",
    )


def population_metrics(labels, predicted):
    expected, ids = labels["person_id"], predicted["person_id"]
    n = len(expected)
    probability = predicted["probabilities"]
    target, weight = labels["target"], labels["weight"]
    if (
        not n
        or expected.ndim != 1
        or ids.ndim != 1
        or not np.issubdtype(ids.dtype, np.integer)
        or len(np.unique(expected)) != n
        or len(np.unique(ids)) != n
        or set(ids) != set(expected)
        or target.shape != (n,)
        or not set(np.unique(target)).issubset({0, 1})
        or weight.shape != (n,)
        or not np.isfinite(weight).all()
        or np.any(weight <= 0)
        or probability.shape != (n, 2)
        or not np.isrealobj(probability)
        or not np.isfinite(probability).all()
        or np.any(probability < 0)
        or np.any(probability > 1)
        or not np.allclose(probability.sum(axis=1), 1, rtol=0, atol=1e-8)
        or predicted["valid"].shape != (n,)
        or predicted["valid"].dtype != np.bool_
        or predicted["seconds"].shape != (n,)
        or not np.isrealobj(predicted["seconds"])
        or not np.isfinite(predicted["seconds"]).all()
        or np.any(predicted["seconds"] < 0)
    ):
        raise ValueError("Require full unique coverage and finite normalized binary probabilities")
    order = {int(value): i for i, value in enumerate(ids)}
    order = [order[int(value)] for value in expected]
    positive = probability[order, 1].astype(float)
    valid = predicted["valid"][order]
    complete = bool(valid.all())
    decision = positive >= 0.5

    def mean(values, mask=None):
        mask = np.ones(n, dtype=bool) if mask is None else mask
        return float(np.average(values[mask], weights=weight[mask])) if mask.any() else None

    groups = []
    for attribute, codes in (("sex", (1, 2)), ("race", tuple(range(1, 10)))):
        if labels[attribute].shape != (n,):
            raise ValueError("Invalid frozen source group codes")
        for code in codes:
            mask = labels[attribute] == code
            positives = mask & (target == 1)
            groups.append(
                {
                    "attribute": attribute,
                    "source_code": code,
                    "persons": int(mask.sum()),
                    "positive_labels": int(positives.sum()),
                    "weighted_brier": mean((positive - target) ** 2, mask) if complete else None,
                    "weighted_positive_rate": mean(decision, mask) if complete else None,
                    "weighted_target_prevalence": mean(target, mask),
                    "weighted_tpr": (
                        mean(decision, positives) if complete and positives.sum() >= 20 else None
                    ),
                    "tpr_scope": "At least 20 observed positives; not a calibrated fairness claim",
                }
            )
    return {
        "weighted_brier": mean((positive - target) ** 2) if complete else None,
        "unweighted_brier": float(np.mean((positive - target) ** 2)) if complete else None,
        "weighted_accuracy_at_half": mean(decision == target) if complete else None,
        "weighted_auc": (
            float(roc_auc_score(target, positive, sample_weight=weight))
            if complete and len(np.unique(target)) == 2
            else None
        ),
        "weighted_calibration_in_large": mean(positive - target) if complete else None,
        "weighted_target_prevalence": mean(target),
        "group_diagnostics": groups,
        "persons": n,
        "households": len(np.unique(labels["household_id"])),
        "declared_failure_fraction": float(np.mean(~valid)),
        "self_reported_cpu_seconds": float(predicted["seconds"].sum()),
        "partial_outcome_policy": (
            "Any failure leaves the complete primary missing; no survivor mean"
        ),
        "weight_scope": "Original person survey weights within this selected source population",
        "probability_score_is_not_fairness_or_causal_certification": True,
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
        source = (frozen / name).resolve(strict=True)
        source.relative_to(frozen.resolve(strict=True))
        if digest(source) != expected:
            raise ValueError("Frozen source changed")
    contract = json.loads((frozen / "SUBMISSION.json").read_text())
    primary = primary_method(contract)
    manifest = json.loads((pack / "PACK.json").read_text())
    contexts, methods = manifest["confirmation_contexts"], contract["methods"]
    expected_files = {f"{context}--{method}.npz" for context in contexts for method in methods}
    found = {p.name for p in predictions.glob("*.npz") if p.is_file() or p.is_symlink()}
    extras = sorted(found - expected_files)
    records = []
    for context in contexts:
        with np.load(
            bound_file(pack, manifest, f"private/{context}-labels.npz"), allow_pickle=False
        ) as labels:
            for method in methods:
                path = predictions / f"{context}--{method}.npz"
                failure = None
                prediction_sha = None
                try:
                    if extras:
                        raise ValueError("Undeclared NPZ outputs invalidate the output contract")
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("Missing or nonregular declared prediction")
                    prediction_sha = digest(path)
                    with np.load(path, allow_pickle=False) as proposed:
                        if set(proposed.files) != {
                            "person_id",
                            "probabilities",
                            "valid",
                            "seconds",
                        }:
                            raise ValueError("Unexpected probability output fields")
                        metrics = population_metrics(labels, proposed)
                    status = (
                        "scored"
                        if metrics["declared_failure_fraction"] == 0
                        else "scored-with-declared-failures"
                    )
                except Exception as exc:
                    # A malformed/missing method must not erase every other
                    # predeclared record or silently change the denominator.
                    # Untrusted NPZ parsing can also raise archive/codec errors,
                    # not merely ValueError. Frozen source/private asset loading
                    # stays outside this boundary and remains fail-closed.
                    failure = {"error_type": type(exc).__name__, "error": str(exc)}
                    status = "invalid-or-missing-output"
                    metrics = {
                        "weighted_brier": None,
                        "persons": len(labels["person_id"]),
                        "declared_failure_fraction": None,
                        "partial_outcome_policy": (
                            "Unscoreable complete output; no survivor score or zero imputation"
                        ),
                    }
                records.append(
                    {
                        "context": context,
                        "method": method,
                        "status": status,
                        "metrics": metrics,
                        "prediction_sha256": prediction_sha,
                        "output_failure": failure,
                    }
                )
    result = {
        "task_id": TASK_ID,
        "status": "scored-all-predeclared-procedures",
        "primary_method": primary,
        "primary_endpoint": "weighted_brier",
        "primary_scores": {
            row["context"]: row["metrics"]["weighted_brier"]
            for row in records
            if row["method"] == primary
        },
        "scores": records,
        "all_predeclared_method_context_records_retained": True,
        "missing_prediction_files": sorted(expected_files - found),
        "undeclared_npz_files": extras,
        "output_contract_valid": not extras
        and all(row["output_failure"] is None for row in records),
        "task_families": 1,
        "pack_sha256": digest(pack / "PACK.json"),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": "Authored selected-household ACS adaptation; not national inference or deployment",
    }
    destination = release.parent / "confirmation/RESULT.json"
    retain_json(destination, result)
    return destination


def target_assets(pack):
    manifest = json.loads((pack / "PACK.json").read_text())
    return [f"{context}-query.npz" for context in manifest["confirmation_contexts"]] + [
        "QUERY.json",
        "train.npz",
        "discovery.npz",
        "validation.npz",
    ]
