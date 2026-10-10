"""Outcome-blind QM9 staging and strict private scalar-property scoring."""

import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "molecular-gap-extrapolation"


def export_stage(pack, destination, *, submission=None):
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.qm9-release.v1",
    )


def regression_metrics(expected_ids, target, proposed_ids, predictions):
    expected_ids, target, proposed_ids, predictions = map(
        np.asarray, (expected_ids, target, proposed_ids, predictions)
    )
    if (
        expected_ids.ndim != 1
        or proposed_ids.ndim != 1
        or not len(expected_ids)
        or not np.issubdtype(proposed_ids.dtype, np.integer)
        or len(np.unique(proposed_ids)) != len(proposed_ids)
        or len(np.unique(expected_ids)) != len(expected_ids)
        or set(proposed_ids) != set(expected_ids)
        or target.shape != expected_ids.shape
        or predictions.shape != proposed_ids.shape
        or not np.isfinite(target).all()
        or not np.isfinite(predictions).all()
    ):
        raise ValueError("Require exact unique molecular IDs and finite scalar predictions")
    lookup = dict(zip(proposed_ids.tolist(), range(len(proposed_ids)), strict=True))
    aligned = predictions[[lookup[int(identifier)] for identifier in expected_ids]]
    error = aligned - target
    return {
        "mae_ev": float(np.abs(error).mean()),
        "rmse_ev": float(np.sqrt(np.mean(error**2))),
        "absolute_error_p90_ev": float(np.quantile(np.abs(error), 0.9)),
        "molecules": len(target),
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if receipt.get("phase") != "transfer" or not receipt.get("frozen_source"):
        raise ValueError("Need source-frozen confirmation")
    if receipt["pack_sha256"] != digest(pack / "PACK.json"):
        raise ValueError("Wrong confirmation pack")
    for name, expected in receipt["frozen_source"].items():
        path = (release.parent / "frozen_submission" / name).resolve(strict=True)
        path.relative_to((release.parent / "frozen_submission").resolve())
        if digest(path) != expected:
            raise ValueError("Frozen source changed")
    submission = json.loads((release.parent / "frozen_submission/SUBMISSION.json").read_text())
    manifest = json.loads((pack / "PACK.json").read_text())
    methods, contexts = submission["methods"], manifest["confirmation_contexts"]
    expected_files = {f"{context}--{method}.npz" for context in contexts for method in methods}
    actual_files = {p.name for p in predictions.glob("*.npz") if p.is_file()}
    if expected_files != actual_files:
        raise ValueError("Score all frozen procedures on both confirmation strata jointly")
    scores = []
    for context in contexts:
        with np.load(
            bound_file(pack, manifest, f"private/{context}-labels.npz"), allow_pickle=False
        ) as labels:
            for method in methods:
                path = predictions / f"{context}--{method}.npz"
                with np.load(path, allow_pickle=False) as proposed:
                    if set(proposed.files) != {"molecule_id", "gap_ev"}:
                        raise ValueError("Predictions contain only molecule_id and gap_ev")
                    metrics = regression_metrics(
                        labels["molecule_id"],
                        labels["gap_ev"],
                        proposed["molecule_id"],
                        proposed["gap_ev"],
                    )
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
        "scores": scores,
        "task_families": 1,
        "primary_context": "large",
        "primary_endpoint": "mae_ev",
        "pack_sha256": digest(pack / "PACK.json"),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": (
            "Prospective within-QM9 molecular-size confirmation; no SOTA/novelty certification"
        ),
    }
    destination = release.parent / "confirmation/RESULT.json"
    retain_json(destination, result)
    return destination


def target_assets(pack):
    manifest = json.loads((pack / "PACK.json").read_text())
    return [
        *[Path(name).name for name in manifest["transfer_files"]],
        "train.npz",
        "small-validation.npz",
        "large-validation.npz",
    ]
