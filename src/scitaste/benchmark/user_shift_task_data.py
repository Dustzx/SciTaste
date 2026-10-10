"""Natural reviewer-shift research with official WILDS metric semantics.

The source-frozen endpoint measures predictions, not research novelty or Taste
efficacy. Users are uncertainty units within ONE task, not independent tasks.
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

TASK_ID = "natural-reviewer-shift"
CLAIM_RUBRIC = [
    {
        "claim_id": "incremental_effect",
        "requirement": (
            "Measure both overall accuracy and the official 10th-percentile reviewer accuracy "
            "against a defensible same-data control; report tradeoffs, not a composite score."
        ),
    },
    {
        "claim_id": "competing_explanation",
        "requirement": (
            "Execute a matched discriminating control for the paper's own central explanation. "
            "Separate label-frequency effects, small-group selection noise and real robustness."
        ),
    },
    {
        "claim_id": "procedure_transfer",
        "requirement": (
            "Compare the unchanged frozen procedure and control on official unseen test users. "
            "All configurations, feature preprocessing and selection rules precede confirmation."
        ),
    },
    {
        "claim_id": "scope_revision",
        "requirement": (
            "Tie hypothesis changes and reviewer-response revisions to actual measurements. "
            "A bounded negative finding is valid; a new method name is not evidence of novelty."
        ),
    },
]


def export_stage(pack, destination, *, submission=None):
    return staged_export(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.user-shift-release.v1",
    )


def target_assets(pack, *, public_metadata=()):
    manifest = json.loads((pack / "PACK.json").read_text())
    if set(public_metadata) - {"PROTOCOL.json"} or len(set(public_metadata)) != len(
        public_metadata
    ):
        raise ValueError("Only explicitly declared public protocol metadata is admissible")
    # Keep legacy cohorts' five-file execution contract unchanged. New cohorts
    # explicitly opt in; never add metadata to transfer_files (export collisions).
    return [Path(name).name for name in manifest["transfer_files"]] + list(public_metadata)


def reviewer_metrics(labels, review_ids, probabilities):
    """Exact-ID five-class scoring, with WILDS' unweighted user percentile."""
    result = classification_metrics(
        {"node_id": labels["review_id"], "target": labels["label"]},
        review_ids,
        probabilities,
        5,
    )
    lookup = {int(i): j for j, i in enumerate(review_ids)}
    aligned = np.asarray(probabilities)[[lookup[int(i)] for i in labels["review_id"]]]
    correct = aligned.argmax(axis=1) == labels["label"]
    users, inverse, counts = np.unique(labels["user"], return_inverse=True, return_counts=True)
    accuracies = np.bincount(inverse, weights=correct, minlength=len(users)) / counts
    result.update(
        reviews=result.pop("nodes"),
        users=len(users),
        accuracy_10th_percentile=float(np.percentile(accuracies, 10)),
        reviewer_accuracy_median=float(np.median(accuracies)),
        smallest_reviewer_reviews=int(counts.min()),
        largest_reviewer_reviews=int(counts.max()),
        nll=float(
            -np.log(np.maximum(aligned[np.arange(len(correct)), labels["label"]], 1e-12)).mean()
        ),
    )
    return result


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if receipt.get("phase") != "transfer" or not receipt.get("frozen_source"):
        raise ValueError("Source-frozen transfer receipt required")
    if receipt["pack_sha256"] != digest(pack / "PACK.json"):
        raise ValueError("Release belongs to another source pack")
    for name, expected_hash in receipt["frozen_source"].items():
        path = (release.parent / "frozen_submission" / name).resolve(strict=True)
        path.relative_to((release.parent / "frozen_submission").resolve(strict=True))
        if digest(path) != expected_hash:
            raise ValueError("Submitted source changed after freeze")
    methods = json.loads((release.parent / "frozen_submission/SUBMISSION.json").read_text())[
        "methods"
    ]
    expected = {f"amazon--{method}.npz" for method in methods}
    actual = {p.name for p in predictions.iterdir() if p.suffix == ".npz" and p.is_file()}
    if actual != expected:
        raise ValueError("Joint predictions must cover exactly all predeclared controls")
    manifest = json.loads((pack / "PACK.json").read_text())
    scores = []
    with np.load(
        bound_file(pack, manifest, "private/query-labels.npz"), allow_pickle=False
    ) as labels:
        for method in methods:
            file = predictions / f"amazon--{method}.npz"
            with np.load(file, allow_pickle=False) as proposed:
                metrics = reviewer_metrics(labels, proposed["review_id"], proposed["probabilities"])
            scores.append(
                {"method": method, "metrics": metrics, "predictions_sha256": digest(file)}
            )
    destination = release.parent / "confirmation"
    destination.mkdir(exist_ok=False)
    retain_json(
        destination / "RESULT.json",
        {
            "status": "scored-all-predeclared-procedures",
            "task_id": TASK_ID,
            "task_families": 1,
            "scores": scores,
            "pack_sha256": digest(pack / "PACK.json"),
            "release_sha256": digest(release),
            "source_execution_verified": False,
            "formal_evidence_eligible": False,
            "scope": (
                "One deterministic user subset; not official full WILDS evaluation or paper novelty"
            ),
        },
    )
    return destination / "RESULT.json"
