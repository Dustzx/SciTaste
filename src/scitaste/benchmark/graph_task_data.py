"""Staged graph research assets and evidence checks, independent of agent policy.

Release receipts establish local order and hashes, not secrecy of public datasets,
process isolation, conceptual correctness or a new formal benchmark population.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, roc_auc_score

TASK_ID = "graph-evidence-transfer"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retain_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def bound_file(pack, manifest, relative):
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Pack paths must be relative and contained")
    path = (pack / relative).resolve(strict=True)
    path.relative_to(pack.resolve(strict=True))
    if digest(path) != manifest["files"][relative]:
        raise ValueError("Frozen graph asset changed")
    return path


def export_stage(
    pack,
    destination,
    *,
    submission=None,
    task_id=TASK_ID,
    release_schema="scitastebench.graph-release.v1",
):
    """Freeze submitted source BEFORE making transfer inputs available locally.

    Does not launch or certify execution. The experiment runner must execute the
    frozen source under its separate resource and network policy.
    """
    pack = pack.resolve(strict=True)
    manifest = json.loads((pack / "PACK.json").read_text())
    if manifest.get("task_id") != task_id:
        raise ValueError("Staged task identity mismatch")
    destination = destination.resolve()
    if destination.is_relative_to(pack) or pack.is_relative_to(destination):
        raise ValueError("Export must be separate from the authoring pack")
    if submission is not None:
        submission = submission.resolve(strict=True)
        if destination.is_relative_to(submission) or submission.is_relative_to(destination):
            raise ValueError("Transfer export and submission must be separate")
    sources = [bound_file(pack, manifest, name) for name in manifest["discovery_files"]]
    frozen = []
    if submission is not None:
        contract = json.loads((submission / "SUBMISSION.json").read_text())
        if contract.get("task_id") != task_id or contract.get("schema_version") != "1.0":
            raise ValueError("Submission identity mismatch")
        for key in ("selection_rule", "fit_policy", "scope"):
            if (
                not isinstance(contract.get(key), str)
                or not contract[key].strip()
                or "REPLACE" in contract[key]
            ):
                raise ValueError(f"Submission needs {key}")
        methods = contract.get("methods", [])
        if (
            len(methods) < 2
            or len(set(methods)) != len(methods)
            or any(
                not isinstance(name, str) or not name.replace("_", "").isalnum() for name in methods
            )
        ):
            raise ValueError("Predeclare primary procedure and key control method identifiers")
        hypotheses = contract.get("hypotheses", [])
        if len(hypotheses) < 2 or any(
            not all(
                isinstance(row.get(k), str) and row[k].strip() and "REPLACE" not in row[k]
                for k in ("statement", "discriminating_prediction")
            )
            for row in hypotheses
        ):
            raise ValueError("Supply competing explanations and discriminating predictions")
        files = contract.get("files", [])
        if not files or len(set(files)) != len(files) or contract.get("entrypoint") not in files:
            raise ValueError("Freeze an explicit file list containing the entrypoint")
        if "SUBMISSION.json" in files:
            raise ValueError("SUBMISSION.json is automatically retained")
        for name in ["SUBMISSION.json", *files]:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or name == "":
                raise ValueError("Unsafe submission path")
            source = submission / relative
            source.resolve(strict=True).relative_to(submission)
            if source.is_symlink() or not source.is_file():
                raise ValueError("Freeze regular source files only")
            frozen.append((name, source.read_bytes()))
        if sum(len(content) for _, content in frozen) > 20_000_000:
            raise ValueError("Source snapshot exceeds 20 MB; exclude model/data caches")
        sources += [bound_file(pack, manifest, name) for name in manifest["transfer_files"]]
    payloads = []
    for source in sources:
        content = source.read_bytes()
        if (
            hashlib.sha256(content).hexdigest()
            != manifest["files"][source.relative_to(pack).as_posix()]
        ):
            raise ValueError("Asset changed during release")
        payloads.append((source.name, content))
    if len({name for name, _ in payloads}) != len(payloads):
        raise ValueError("Export filenames collide")
    destination.mkdir(parents=True, exist_ok=False)
    # Hash exactly the retained bytes, not a concurrently mutable input path.
    hashes = {}
    for name, content in frozen:
        path = destination / "frozen_submission" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
        hashes[name] = digest(path)
    retained_at = datetime.now(UTC).isoformat()
    for name, content in payloads:
        with (destination / name).open("xb") as stream:
            stream.write(content)
    receipt = {
        "schema_version": release_schema,
        "task_id": task_id,
        "phase": "transfer" if submission else "discovery",
        "pack_sha256": digest(pack / "PACK.json"),
        "snapshot_retained_at": retained_at if submission else None,
        "released_at": datetime.now(UTC).isoformat(),
        "frozen_source": hashes,
        "assets": {p.name: digest(destination / p.name) for p in sources},
        "execution_verified": False,
        "formal_evidence_eligible": False,
        "public_source_contamination": "unknown; release is not proof of first exposure",
    }
    retain_json(destination / "RELEASE.json", receipt)
    return receipt


def classification_metrics(labels, node_ids, probabilities, classes):
    """Strict complete-coverage scorer with correct binary ranking endpoint."""
    node_ids, probabilities = np.asarray(node_ids), np.asarray(probabilities)
    expected = np.asarray(labels["node_id"])
    if not np.issubdtype(node_ids.dtype, np.integer) or node_ids.ndim != 1:
        raise ValueError("Prediction IDs must be a one-dimensional integer array")
    if len(np.unique(node_ids)) != len(node_ids) or set(node_ids) != set(expected):
        raise ValueError("Prediction IDs must exactly cover evaluator nodes")
    if probabilities.shape != (len(node_ids), classes):
        raise ValueError("Wrong probability dimensions")
    if (
        not np.isfinite(probabilities).all()
        or np.any(probabilities < 0)
        or np.any(probabilities > 1)
        or not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-6)
    ):
        raise ValueError("Require finite normalized class probabilities")
    target = np.asarray(labels["target"])
    if len(target) != len(expected) or len(np.unique(expected)) != len(expected):
        raise ValueError("Invalid evaluator labels")
    lookup = dict(zip(node_ids.tolist(), range(len(node_ids)), strict=True))
    aligned = probabilities[[lookup[int(node)] for node in expected]]
    result = {
        "accuracy": float(accuracy_score(target, aligned.argmax(axis=1))),
        "nodes": len(target),
    }
    if classes == 2:
        result["roc_auc"] = float(roc_auc_score(target, aligned[:, 1]))
    return result


def score_graph(pack, graph, predictions, *, release=None):
    manifest = json.loads((pack / "PACK.json").read_text())
    spec = next(row for row in manifest["graphs"] if row["graph_id"] == graph)
    labels_path = bound_file(pack, manifest, f"private/{graph}-labels.npz")
    with np.load(labels_path, allow_pickle=False) as labels:
        with np.load(predictions, allow_pickle=False) as predicted:
            metrics = classification_metrics(
                labels, predicted["node_id"], predicted["probabilities"], spec["classes"]
            )
    release_sha = None
    if release is not None:
        receipt = json.loads(release.read_text())
        if receipt["pack_sha256"] != digest(pack / "PACK.json") or receipt["phase"] != "transfer":
            raise ValueError("Transfer receipt does not bind this pack")
        for name, expected in receipt["frozen_source"].items():
            source = (release.parent / "frozen_submission" / name).resolve(strict=True)
            source.relative_to((release.parent / "frozen_submission").resolve(strict=True))
            if digest(source) != expected:
                raise ValueError("Submitted source changed after transfer release")
        release_sha = digest(release)
    return {
        "task_id": TASK_ID,
        "graph": graph,
        "endpoint": spec["endpoint"],
        "metrics": metrics,
        "pack_sha256": digest(pack / "PACK.json"),
        "predictions_sha256": digest(predictions),
        "transfer_release_sha256": release_sha,
        "execution_binding_verified": False,
        "score_scope": "predictions only; not research contribution or source execution",
        "formal_evidence_eligible": False,
    }


def confirm_submission(pack, release, predictions):
    """One locally retained score packet for ALL predeclared transfer procedures.

    This is an evaluator operation. No labels/feedback should be mounted into a
    researcher process. The runtime still owes proof of frozen-code execution.
    """
    receipt = json.loads(release.read_text())
    if receipt.get("phase") != "transfer" or not receipt.get("frozen_source"):
        raise ValueError("A real source-bound transfer release is required")
    submission = release.parent / "frozen_submission/SUBMISSION.json"
    if digest(submission) != receipt["frozen_source"]["SUBMISSION.json"]:
        raise ValueError("Frozen submission contract changed")
    methods = json.loads(submission.read_text())["methods"]
    expected = {f"tolokers--{method}.npz" for method in methods}
    actual_predictions = {
        path.name for path in predictions.iterdir() if path.is_file() and path.suffix == ".npz"
    }
    if actual_predictions != expected:
        raise ValueError("Submit exactly all predeclared method/control predictions together")
    # Validate the packet before consuming the local one-shot scoring slot. Do
    # not emit partial scores if any member fails the input contract.
    scores = [
        {
            "method": method,
            **score_graph(
                pack, "tolokers", predictions / f"tolokers--{method}.npz", release=release
            ),
        }
        for method in methods
    ]
    destination = release.parent / "confirmation"
    destination.mkdir(exist_ok=False)
    result = {
        "status": "scored-all-predeclared-procedures",
        "scores": scores,
        "auxiliary_files": {
            path.name: digest(path)
            for path in predictions.iterdir()
            if path.is_file() and path.suffix != ".npz"
        },
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
        "note": (
            "One score packet per retained release; public-source exposure "
            "and execution isolation remain separate."
        ),
    }
    retain_json(destination / "RESULT.json", result)
    return destination / "RESULT.json"


def evaluate_anchor_judgments(anchor_root, judgments):
    """Evaluator-only comparison to numerical/scope anchors, not human gold."""
    cases_path = anchor_root / "calibration/CASES.json"
    expected_path = anchor_root / "calibration/PRIVATE_EXPECTED.json"
    cases = json.loads(cases_path.read_text())["cases"]
    expected = json.loads(expected_path.read_text())["expected"]
    rows = json.loads(judgments.read_text())["judgments"]
    ids = [row["case_id"] for row in rows]
    if (
        len(ids) != len(set(ids))
        or set(ids) != set(expected)
        or set(ids) != {c["case_id"] for c in cases}
    ):
        raise ValueError("Judge must cover each frozen anchor exactly once")
    labels = ("supported", "contradicted", "insufficient")
    if any(row["label"] not in labels or not row.get("reason") for row in rows):
        raise ValueError("Require an allowed verdict and evidence-based reason")
    confusion = {truth: {predicted: 0 for predicted in labels} for truth in labels}
    for row in rows:
        confusion[expected[row["case_id"]]][row["label"]] += 1
    return {
        "case_count": len(rows),
        "underlying_validation_contexts": 2,
        "matched": sum(row["label"] == expected[row["case_id"]] for row in rows),
        "confusion": confusion,
        "cases_sha256": digest(cases_path),
        "expected_sha256": digest(expected_path),
        "judgments_sha256": digest(judgments),
        "judge_provenance": (
            "fresh-context session subagent; actual provider model identifier unverified"
        ),
        "tokens": None,
        "cost": None,
        "human_gold": False,
        "paper_judge_validated": False,
        "formal_evidence_eligible": False,
        "scope": (
            "elementary numeric/scope discrimination and paraphrases only; "
            "not novelty, mechanism or paper quality calibration"
        ),
    }
