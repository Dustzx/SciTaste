"""Data-plane scoring for authored research tasks, not framework or paper grading.

Only the evaluator may mount the private directory. Reading predictions does not
execute a submitted program or establish artifact reproducibility.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recipe_groups(frame: pd.DataFrame, columns: list[str], tolerance: float = 0.5):
    """Connected components of near-identical recipes; age and target excluded."""
    from scipy.spatial import cKDTree

    values = frame[columns].to_numpy(dtype=float)
    parents = list(range(len(values)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    pairs = cKDTree(values).query_pairs(tolerance, p=np.inf)
    for first, second in sorted(pairs):
        a, b = root(first), root(second)
        parents[max(a, b)] = min(a, b)
    return pd.Series([f"recipe-{root(i):04d}" for i in range(len(values))]), len(pairs)


def prediction_metrics(labels: pd.DataFrame, predictions: pd.DataFrame) -> dict:
    required = {"row_id", "prediction"}
    if set(predictions.columns) != required or predictions.row_id.duplicated().any():
        raise ValueError("Predictions require unique row_id and prediction columns only")
    if labels.row_id.duplicated().any() or set(labels.row_id) != set(predictions.row_id):
        raise ValueError("Predictions must cover exactly the frozen evaluation rows")
    joined = labels.merge(predictions, on="row_id", validate="one_to_one")
    predicted = pd.to_numeric(joined.prediction, errors="raise").to_numpy(dtype=float)
    target = joined.target.to_numpy(dtype=float)
    if not np.isfinite(predicted).all() or not np.isfinite(target).all():
        raise ValueError("Nonfinite predictions or labels cannot be scored")
    joined["absolute_error"] = np.abs(predicted - target)
    return {
        "group_macro_mae": float(joined.groupby("group_id").absolute_error.mean().mean()),
        "row_mae": float(joined.absolute_error.mean()),
        "row_rmse": float(np.sqrt(np.mean((predicted - target) ** 2))),
        "rows": len(joined),
        "groups": int(joined.group_id.nunique()),
    }


def score_submission(pack: Path, task_id: str, predictions: Path) -> dict:
    """Score fixed labels, without emitting labels or per-row errors to the agent."""
    pack = pack.resolve(strict=True)
    manifest = json.loads((pack / "PACK.json").read_text())
    tasks = {task["task_id"]: task for task in manifest["tasks"]}
    task = tasks[task_id]
    relative = f"private/{task_id}/labels.csv"
    labels_path = (pack / relative).resolve(strict=True)
    labels_path.relative_to(pack)
    if digest(labels_path) != manifest["files"][relative]:
        raise ValueError("Frozen endpoint labels changed")
    metrics = prediction_metrics(pd.read_csv(labels_path), pd.read_csv(predictions))
    return {
        "task_id": task_id,
        "endpoint": task["primary_endpoint"],
        "direction": "minimize",
        "units": task["units"],
        "metrics": metrics,
        "predictions_sha256": digest(predictions),
        "labels_sha256": digest(labels_path),
        "score_scope": "experimental_endpoint_only",
        "paper_quality_scored": False,
        "independent_reproduction": False,
        "formal_evidence_eligible": False,
    }


def export_researcher_assets(pack: Path, task_id: str, destination: Path):
    """Copy an allowlisted candidate task, never raw-source or evaluator assets."""
    import shutil

    manifest = json.loads((pack / "PACK.json").read_text())
    task = next(t for t in manifest["tasks"] if t["task_id"] == task_id)
    sources = []
    for relative in task["researcher_files"]:
        path = (pack / relative).resolve(strict=True)
        path.relative_to((pack / "public" / task_id).resolve(strict=True))
        if digest(path) != manifest["files"][relative]:
            raise ValueError("Researcher input changed after freeze")
        sources.append(path)
    destination = destination.resolve()
    if destination.is_relative_to(pack.resolve()) or pack.resolve().is_relative_to(destination):
        raise ValueError("Researcher export must be separate from the authoring pack")
    destination.mkdir(parents=True, exist_ok=False)
    for source in sources:
        shutil.copy2(source, destination / source.name)
    return {"task_id": task_id, "files": [p.name for p in sources], "formal_release": False}


def review_evidence(pack: Path, task_id: str, predictions: Path) -> dict:
    """Generate standardized review observations from PUBLIC validation only."""
    manifest = json.loads((pack / "PACK.json").read_text())
    if task_id not in {t["task_id"] for t in manifest["tasks"]}:
        raise ValueError("Unknown task identity")
    public = pack / "public" / task_id
    for name in ("validation.csv", "PROTOCOL.json"):
        relative = f"public/{task_id}/{name}"
        if digest(public / name) != manifest["files"][relative]:
            raise ValueError("Public review input changed")
    labels = pd.read_csv(public / "validation.csv")
    predicted = pd.read_csv(predictions)
    metrics = prediction_metrics(labels, predicted)
    protocol = json.loads((public / "PROTOCOL.json").read_text())
    slices = (
        {
            "age_1_7": labels.age <= 7,
            "age_8_28": (labels.age > 7) & (labels.age <= 28),
            "age_over_28": labels.age > 28,
        }
        if "age" in labels
        else {
            "working_day": labels.workingday == 1,
            "nonworking_day": labels.workingday == 0,
            "morning_7_9": labels.hr.between(7, 9),
            "evening_16_19": labels.hr.between(16, 19),
        }
    )
    return {
        "task_id": task_id,
        "scope": "public-validation-only; not heldout feedback",
        "validation_sha256": digest(public / "validation.csv"),
        "predictions_sha256": digest(predictions),
        "metrics": metrics,
        "slices": {
            key: prediction_metrics(part, predicted[predicted.row_id.isin(part.row_id)])
            for key, mask in slices.items()
            if not (part := labels.loc[mask]).empty
        },
        "required_claims": protocol["claim_rubric"],
        "reviewer_instruction": "Compare the submission's claims to these measured observations "
        "and its executed controls. Report unsupported, contradicted or unresolved claims. "
        "Do not infer a mechanism from predictive error or propose a preferred positive answer.",
        "hidden_labels_or_scores_included": False,
    }


def summarize_claim_judgments(protocol: dict, judgments: list[dict]) -> dict:
    """Keep a fixed denominator; these supplied judgments are not calibrated gold."""
    required = {row["claim_id"] for row in protocol["claim_rubric"]}
    ids = [row["claim_id"] for row in judgments]
    if len(ids) != len(set(ids)) or set(ids) != required:
        raise ValueError("Each required claim slot must have exactly one judgment")
    allowed = {"supported", "contradicted", "insufficient"}
    for row in judgments:
        if row["status"] not in allowed or not row.get("reason"):
            raise ValueError("Claim judgment requires an allowed status and reason")
        if row["status"] != "insufficient" and not row.get("evidence_refs"):
            raise ValueError("Support or contradiction requires explicit evidence references")
    return {
        "required_claims": len(required),
        "counts": {
            status: sum(row["status"] == status for row in judgments) for status in sorted(allowed)
        },
        "judgments": judgments,
        "calibrated_gold": False,
        "evidence_refs_independently_verified": False,
        "scope": "required conclusions only; extra unsupported claims separately assessed",
    }
