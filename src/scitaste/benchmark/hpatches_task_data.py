"""Strict scene-aware scoring for the authored, source-frozen geometry task."""

import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "confidence-guided-geometry"


def primary_method(contract):
    """Require a pre-result deployed procedure, not a private-score winner."""
    method = contract.get("primary_method")
    if not isinstance(method, str) or method not in contract.get("methods", []):
        raise ValueError("Declare one primary_method among methods before READY")
    return method


def export_stage(pack, destination, *, submission=None):
    if submission is not None:
        primary_method(json.loads((submission / "SUBMISSION.json").read_text()))
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.hpatches-release.v1",
    )


def corner_errors(truth, proposed, shapes, valid):
    """All failed estimates stay in the denominator with infinite error."""
    errors = np.full(len(truth), np.inf)
    for index in np.flatnonzero(valid):
        scale = np.max(np.abs(proposed[index]))
        if not scale:
            continue
        proposal = proposed[index] / scale
        # Homographies are projective: H and any nonzero scalar times H must
        # receive the same score, including a tiny but otherwise valid matrix.
        if np.linalg.det(proposal) == 0:
            continue
        height, width = shapes[index]
        corners = np.array(
            [[0, 0, 1], [width - 1, 0, 1], [width - 1, height - 1, 1], [0, height - 1, 1]]
        ).T
        expected, predicted = truth[index] @ corners, proposal @ corners
        if (np.abs(expected[2]) < 1e-10).any() or (np.abs(predicted[2]) < 1e-10).any():
            continue
        error = np.linalg.norm(expected[:2] / expected[2] - predicted[:2] / predicted[2], axis=0)
        if np.isfinite(error).all():
            errors[index] = error.mean()
    return errors


def corner_auc(errors, threshold):
    errors = np.sort(np.asarray(errors, dtype=float))
    if not len(errors) or threshold <= 0 or np.isnan(errors).any() or np.any(errors < 0):
        raise ValueError("Need nonempty nonnegative corner errors and a positive threshold")
    recall = np.arange(1, len(errors) + 1, dtype=float) / len(errors)
    errors, recall = np.r_[0.0, errors], np.r_[0.0, recall]
    end = np.searchsorted(errors, threshold, side="right")
    x, y = np.r_[errors[:end], threshold], np.r_[recall[:end], recall[end - 1]]
    return float(np.trapezoid(y, x) / threshold)


def geometry_metrics(labels, scene_ids, predictions):
    expected, identifiers = labels["pair_id"], predictions["pair_id"]
    size = len(expected)
    if (
        expected.ndim != 1
        or identifiers.ndim != 1
        or not size
        or not np.issubdtype(identifiers.dtype, np.integer)
        or len(np.unique(expected)) != size
        or len(np.unique(identifiers)) != len(identifiers)
        or set(expected) != set(identifiers)
        or labels["homography"].shape != (size, 3, 3)
        or labels["shape1"].shape != (size, 2)
        or scene_ids.shape != (size,)
        or predictions["homography"].shape != (size, 3, 3)
        or predictions["valid"].shape != (size,)
        or predictions["valid"].dtype != np.bool_
        or predictions["seconds"].shape != (size,)
        or not np.isrealobj(predictions["homography"])
        or not np.isrealobj(predictions["seconds"])
        or not np.isfinite(predictions["homography"]).all()
        or not np.isfinite(predictions["seconds"]).all()
        or np.any(predictions["seconds"] < 0)
        or not np.isfinite(labels["homography"]).all()
        or np.any(labels["shape1"] < 2)
    ):
        raise ValueError("Require full unique pair coverage and finite, typed geometry outputs")
    lookup = dict(zip(identifiers.tolist(), range(size), strict=True))
    order = [lookup[int(identifier)] for identifier in expected]
    valid = predictions["valid"][order]
    errors = corner_errors(
        labels["homography"], predictions["homography"][order], labels["shape1"], valid
    )
    scene_results = [
        {
            "scene_id": int(scene),
            "pairs": int(np.sum(scene_ids == scene)),
            "corner_auc_5px": corner_auc(errors[scene_ids == scene], 5.0),
            "corner_auc_1px": corner_auc(errors[scene_ids == scene], 1.0),
        }
        for scene in np.unique(scene_ids)
    ]
    return {
        "corner_auc_5px": corner_auc(errors, 5.0),
        "corner_auc_1px": corner_auc(errors, 1.0),
        "declared_failure_fraction": float(np.mean(~valid)),
        "geometric_failure_fraction": float(np.mean(~np.isfinite(errors))),
        "self_reported_cpu_seconds": float(predictions["seconds"].sum()),
        "pairs": size,
        "scene_groups": len(scene_results),
        "per_scene": scene_results,
        "independent_research_tasks": 1,
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if receipt.get("phase") != "transfer" or not receipt.get("frozen_source"):
        raise ValueError("Need source-frozen confirmation")
    if receipt["pack_sha256"] != digest(pack / "PACK.json"):
        raise ValueError("Wrong confirmation pack")
    for name, expected in receipt["frozen_source"].items():
        source = (release.parent / "frozen_submission" / name).resolve(strict=True)
        source.relative_to((release.parent / "frozen_submission").resolve(strict=True))
        if digest(source) != expected:
            raise ValueError("Frozen source changed")
    submission = json.loads((release.parent / "frozen_submission/SUBMISSION.json").read_text())
    primary = primary_method(submission)
    manifest = json.loads((pack / "PACK.json").read_text())
    contexts, methods = manifest["confirmation_contexts"], submission["methods"]
    expected_files = {f"{context}--{method}.npz" for context in contexts for method in methods}
    if expected_files != {path.name for path in predictions.glob("*.npz") if path.is_file()}:
        raise ValueError("Score every frozen procedure on both change types jointly")
    scores = []
    for context in contexts:
        with (
            np.load(bound_file(pack, manifest, f"private/{context}-labels.npz")) as labels,
            np.load(bound_file(pack, manifest, f"target/{context}-query.npz")) as query,
        ):
            if not np.array_equal(labels["pair_id"], query["pair_id"]):
                raise ValueError("Private labels and redacted queries have different joins")
            for method in methods:
                path = predictions / f"{context}--{method}.npz"
                with np.load(path, allow_pickle=False) as proposed:
                    if set(proposed.files) != {"pair_id", "homography", "valid", "seconds"}:
                        raise ValueError("Unexpected prediction fields")
                    metrics = geometry_metrics(labels, query["scene_id"], proposed)
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
        "primary_endpoint": "corner_auc_5px",
        "primary_method": primary,
        "primary_scores": {
            row["context"]: row["metrics"]["corner_auc_5px"]
            for row in scores
            if row["method"] == primary
        },
        "task_families": 1,
        "pack_sha256": digest(pack / "PACK.json"),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": "Planar inference on authored HPatches groups; not a full matching leaderboard",
    }
    destination = release.parent / "confirmation/RESULT.json"
    retain_json(destination, result)
    return destination


def target_assets(pack):
    manifest = json.loads((pack / "PACK.json").read_text())
    # Calibration is permitted only on the already released public pairs.
    # Replaying that frozen policy requires these files, never private truth.
    return [
        Path(name).name
        for name in [*manifest["discovery_files"], *manifest["transfer_files"]]
        if name.endswith(".npz") or Path(name).name == "QUERY.json"
    ]
