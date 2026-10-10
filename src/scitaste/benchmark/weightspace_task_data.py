"""Whole research on real trained weights with source-frozen confirmation.

Training blocks are units of replication; contexts/models/images are not new tasks.
Low-level prediction scoring never certifies scientific novelty or code execution.
"""

import json
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import (
    bound_file,
    classification_metrics,
    digest,
    retain_json,
)
from scitaste.benchmark.graph_task_data import export_stage as staged_export

TASK_ID = "weightspace-evidence-transfer"


def export_stage(pack, destination, *, submission=None):
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.weightspace-release.v1",
    )


def score_context(pack, context, predictions, *, release=None):
    manifest = json.loads((pack / "PACK.json").read_text())
    if context not in manifest["confirmation_contexts"]:
        raise ValueError("Unknown frozen confirmation context")
    query = json.loads(bound_file(pack, manifest, "target/QUERY.json").read_text())
    context_metadata = next(item for item in query["contexts"] if item["context_id"] == context)
    labels = bound_file(pack, manifest, "private/confirmation-labels.npz")
    with np.load(labels, allow_pickle=False) as actual:
        with np.load(predictions, allow_pickle=False) as proposed:
            metrics = classification_metrics(
                {"node_id": actual["image_id"], "target": actual["labels"]},
                proposed["image_id"],
                proposed["probabilities"],
                10,
            )
            lookup = dict(
                zip(proposed["image_id"].tolist(), range(len(proposed["image_id"])), strict=True)
            )
            aligned = proposed["probabilities"][[lookup[int(i)] for i in actual["image_id"]]]
            metrics["nll"] = float(
                -np.log(
                    np.maximum(aligned[np.arange(len(actual["labels"])), actual["labels"]], 1e-12)
                ).mean()
            )
            metrics["images"] = metrics.pop("nodes")
    return {
        "task_id": TASK_ID,
        "context": context,
        "training_block": context_metadata["training_block"],
        "lineage": context_metadata["lineage"],
        "metrics": metrics,
        "pack_sha256": digest(pack / "PACK.json"),
        "predictions_sha256": digest(predictions),
        "transfer_release_sha256": digest(release) if release else None,
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "scope": (
            "Prediction quality on unseen training blocks; not paper novelty or full-system score"
        ),
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if receipt.get("phase") != "transfer" or not receipt.get("frozen_source"):
        raise ValueError("A source-frozen transfer release is required")
    if receipt["pack_sha256"] != digest(pack / "PACK.json"):
        raise ValueError("Release belongs to another pack")
    for name, expected in receipt["frozen_source"].items():
        path = (release.parent / "frozen_submission" / name).resolve(strict=True)
        path.relative_to((release.parent / "frozen_submission").resolve())
        if digest(path) != expected:
            raise ValueError("Submitted source changed after freeze")
    submission = json.loads((release.parent / "frozen_submission/SUBMISSION.json").read_text())
    manifest = json.loads((pack / "PACK.json").read_text())
    methods = submission["methods"]
    contexts = manifest["confirmation_contexts"]
    expected = {f"{context}--{method}.npz" for context in contexts for method in methods}
    actual = {p.name for p in predictions.iterdir() if p.is_file() and p.suffix == ".npz"}
    if expected != actual:
        raise ValueError("Predictions must exactly cover every frozen context and declared method")
    scores = [
        {
            "method": method,
            **score_context(
                pack,
                context,
                predictions / f"{context}--{method}.npz",
                release=release,
            ),
        }
        for context in contexts
        for method in methods
    ]
    destination = release.parent / "confirmation"
    destination.mkdir(exist_ok=False)
    result = {
        "status": "scored-all-predeclared-procedures",
        "scores": scores,
        "task_families": 1,
        "independent_training_blocks": manifest["confirmation_blocks"],
        "shared_query_images_across_contexts": True,
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "note": (
            "All contexts scored jointly once; runtime execution evidence is a separate receipt"
        ),
    }
    retain_json(destination / "RESULT.json", result)
    return destination / "RESULT.json"


def target_assets(pack):
    manifest = json.loads((pack / "PACK.json").read_text())
    return [Path(name).name for name in manifest["transfer_files"]]
