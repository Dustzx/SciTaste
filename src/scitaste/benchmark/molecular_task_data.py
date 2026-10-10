"""Source-bound molecular research assets and evaluator-private force endpoints.

Public source trajectories are not secret, independent observations. Release
receipts establish local freeze order, not process isolation or formal admission.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json

TASK_ID = "molecular-force-risk"
COVERAGES = (0.5, 0.8, 0.9, 1.0)
TIE_SEED = "molecular-force-risk/v1/ties/2718"


def force_metrics(labels, frame_ids, forces, risk_scores):
    """Score whole-frame forces and selective error; never treat atoms as tasks."""
    expected = np.asarray(labels["frame_id"])
    frame_ids, forces, risk_scores = map(np.asarray, (frame_ids, forces, risk_scores))
    target = np.asarray(labels["forces"])
    if (
        expected.ndim != 1
        or not len(expected)
        or not np.issubdtype(expected.dtype, np.integer)
        or len(np.unique(expected)) != len(expected)
        or frame_ids.ndim != 1
        or not np.issubdtype(frame_ids.dtype, np.integer)
        or len(np.unique(frame_ids)) != len(frame_ids)
        or set(frame_ids) != set(expected)
    ):
        raise ValueError("Require exact, unique evaluator frame coverage")
    if (
        target.ndim != 3
        or target.shape[0] != len(expected)
        or target.shape[2] != 3
        or forces.shape != target.shape
        or risk_scores.shape != (len(expected),)
        or not np.isfinite(target).all()
        or not np.isfinite(forces).all()
        or not np.isfinite(risk_scores).all()
    ):
        raise ValueError("Require finite per-frame force vectors and risk scores")
    lookup = dict(zip(frame_ids.tolist(), range(len(frame_ids)), strict=True))
    order = [lookup[int(frame)] for frame in expected]
    forces, risk_scores = forces[order], risk_scores[order]
    # Average components within each configuration, then configurations. Atoms
    # and force components are not independent experimental replications.
    error = np.abs(forces - target).mean(axis=(1, 2))
    tie_keys = np.array(
        [hashlib.sha256(f"{TIE_SEED}/{int(frame)}".encode()).hexdigest() for frame in expected]
    )
    ranking = np.lexsort((tie_keys, risk_scores))
    tail_count = max(1, int(np.ceil(0.05 * len(error))))
    worst = np.lexsort((tie_keys, error))[-tail_count:]
    selective = []
    for coverage in COVERAGES:
        count = max(1, int(np.ceil(coverage * len(error))))
        selective.append(
            {
                "coverage": coverage,
                "frames": count,
                "mae": float(error[ranking[:count]].mean()),
                "rejected_mae": float(error[ranking[count:]].mean())
                if count < len(error)
                else None,
                "worst_five_percent_retained_fraction": float(
                    np.isin(worst, ranking[:count]).mean()
                ),
                "uniform_selection_expected_mae": float(error.mean()),
            }
        )
    _, tie_counts = np.unique(risk_scores, return_counts=True)
    correlation = (
        float(spearmanr(risk_scores, error).statistic)
        if len(tie_counts) > 1 and np.ptp(error) > 0
        else None
    )
    # Evaluator-only chronology diagnostic: never a force-predictor feature.
    within_time = []
    fraction = (expected - int(expected.min())) / (int(expected.max()) - int(expected.min()) + 1)
    for bin_id in range(4):
        members = np.flatnonzero((fraction >= bin_id / 4) & (fraction < (bin_id + 1) / 4))
        if not len(members):
            continue
        ranked = members[np.lexsort((tie_keys[members], risk_scores[members]))]
        count = max(1, int(np.ceil(0.9 * len(members))))
        within_time.append(
            {
                "source_span_bin": bin_id,
                "frames": len(members),
                "coverage": 0.9,
                "accepted_frames": count,
                "geometry_selected_mae": float(error[ranked[:count]].mean()),
                "uniform_selection_expected_mae": float(error[members].mean()),
            }
        )
    return {
        "force_mae": float(error.mean()),
        "force_mae_unit": "kcal/mol/angstrom",
        "frames": len(error),
        "primary_selective_coverage": 0.9,
        "atoms_per_frame": target.shape[1],
        "selective_risk": selective,
        "worst_five_percent_frame_mae": float(np.sort(error)[-tail_count:].mean()),
        "worst_five_percent_frames": tail_count,
        "risk_error_spearman": correlation,
        "unique_risk_scores": len(tie_counts),
        "largest_risk_tie_fraction": float(tie_counts.max() / len(error)),
        "risk_tie_policy": f"label-blind SHA256({TIE_SEED}/frame_id), not chronology",
        "within_source_span_diagnostic": within_time,
        "uncertainty_estimate": None,
        "inference_scope": "finite source-index block; no independent-frame or dynamics claim",
    }


def score_molecule(pack, molecule, predictions, *, partition="confirmation"):
    pack = pack.resolve(strict=True)
    manifest = json.loads((pack / "PACK.json").read_text())
    if manifest.get("task_id") != TASK_ID or partition not in {"validation", "confirmation"}:
        raise ValueError("Invalid molecular pack or endpoint partition")
    context = next(row for row in manifest["contexts"] if row["molecule"] == molecule)
    if context["role"] == "confirmation" and partition != "confirmation":
        raise ValueError("Confirmation context exposes no validation endpoint")
    if context["role"] == "discovery" and partition != "validation":
        raise ValueError("Discovery context has a public validation endpoint only")
    labels_path = bound_file(pack, manifest, f"private/{molecule}-{partition}-labels.npz")
    with np.load(labels_path, allow_pickle=False) as labels:
        with np.load(predictions, allow_pickle=False) as predicted:
            if set(predicted.files) != {"frame_id", "forces", "risk_score"}:
                raise ValueError("Prediction packet must contain only frame_id/forces/risk_score")
            metrics = force_metrics(
                labels, predicted["frame_id"], predicted["forces"], predicted["risk_score"]
            )
    return {
        "task_id": TASK_ID,
        "molecule": molecule,
        "partition": partition,
        "metrics": metrics,
        "pack_sha256": digest(pack / "PACK.json"),
        "prediction_sha256": digest(predictions),
        "source_execution_verified": False,
        "scientific_claim_validation": False,
        "formal_evidence_eligible": False,
    }


def export_stage(pack, destination, *, submission=None):
    """Freeze explicit source bytes before allowing the target's redacted assets."""
    pack, destination = pack.resolve(strict=True), destination.resolve()
    if destination.is_relative_to(pack) or pack.is_relative_to(destination):
        raise ValueError("Research export must be separate from the authoring pack")
    manifest = json.loads((pack / "PACK.json").read_text())
    if manifest.get("task_id") != TASK_ID:
        raise ValueError("Wrong staged task identity")
    files = list(manifest["discovery_files"])
    frozen = {}
    if submission is not None:
        submission = submission.resolve(strict=True)
        if destination.is_relative_to(submission) or submission.is_relative_to(destination):
            raise ValueError("Source submission and target release must be separate")
        contract = json.loads((submission / "SUBMISSION.json").read_text())
        if contract.get("schema_version") != "1.0" or contract.get("task_id") != TASK_ID:
            raise ValueError("Invalid frozen submission identity")
        for key in ("selection_rule", "fit_policy", "risk_policy", "scope"):
            if (
                not isinstance(contract.get(key), str)
                or not contract[key].strip()
                or "REPLACE" in contract[key]
            ):
                raise ValueError(f"Specify {key} before confirmation release")
        methods = contract.get("methods", [])
        if (
            not isinstance(methods, list)
            or len(methods) < 2
            or any(not isinstance(m, str) or not m.replace("_", "").isalnum() for m in methods)
            or len(set(methods)) != len(methods)
        ):
            raise ValueError("Predeclare primary and key controls, with unique identifiers")
        hypotheses = contract.get("hypotheses", [])
        if (
            not isinstance(hypotheses, list)
            or len(hypotheses) < 2
            or any(
                not isinstance(h, dict)
                or any(
                    not isinstance(h.get(key), str) or not h[key].strip() or "REPLACE" in h[key]
                    for key in ("statement", "discriminating_prediction")
                )
                for h in hypotheses
            )
        ):
            raise ValueError("Freeze genuine alternative hypotheses and discriminating predictions")
        names = contract.get("files", [])
        if (
            not isinstance(names, list)
            or any(not isinstance(n, str) or not n for n in names)
            or len(set(names)) != len(names)
            or "SUBMISSION.json" in names
            or contract.get("entrypoint") not in names
        ):
            raise ValueError("Freeze an explicit file list containing the entrypoint")
        for name in ["SUBMISSION.json", *names]:
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Unsafe submission file path")
            path = submission / name
            path.resolve(strict=True).relative_to(submission)
            if path.is_symlink() or not path.is_file():
                raise ValueError("Freeze regular source files only")
            frozen[name] = path.read_bytes()
        if sum(map(len, frozen.values())) > 20_000_000:
            raise ValueError("Source snapshot exceeds 20 MB; omit weights/data caches")
        files += manifest["transfer_files"]
    payloads = [(Path(n).name, bound_file(pack, manifest, n).read_bytes()) for n in files]
    if len({n for n, _ in payloads}) != len(payloads):
        raise ValueError("Flat export filenames collide")
    # Check exact bytes again after reading, not merely the mutable source path.
    for relative, (_, content) in zip(files, payloads, strict=True):
        if hashlib.sha256(content).hexdigest() != manifest["files"][relative]:
            raise ValueError("Molecular asset changed during release")
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in frozen.items():
        path = destination / "frozen_submission" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    retained_at = datetime.now(UTC).isoformat()
    for name, content in payloads:
        with (destination / name).open("xb") as stream:
            stream.write(content)
    receipt = {
        "schema_version": "scitastebench.molecular-release.v1",
        "task_id": TASK_ID,
        "phase": "transfer" if submission else "discovery",
        "pack_sha256": digest(pack / "PACK.json"),
        "source_frozen_at": retained_at if submission else None,
        "released_at": datetime.now(UTC).isoformat(),
        "frozen_source": {
            name: digest(destination / "frozen_submission" / name) for name in frozen
        },
        "assets": {name: digest(destination / name) for name, _ in payloads},
        "execution_verified": False,
        "formal_evidence_eligible": False,
        "public_source_contamination": "unknown; staged access does not establish secrecy",
    }
    retain_json(destination / "RELEASE.json", receipt)
    return receipt


def confirm_submission(pack, release, predictions):
    """Score all declared procedures together, once per retained target release."""
    receipt = json.loads(release.read_text())
    if (
        receipt.get("task_id") != TASK_ID
        or receipt.get("phase") != "transfer"
        or receipt.get("pack_sha256") != digest(pack / "PACK.json")
        or not receipt.get("frozen_source")
    ):
        raise ValueError("Require a source-bound target release")
    root = (release.parent / "frozen_submission").resolve(strict=True)
    for name, expected in receipt["frozen_source"].items():
        source = (root / name).resolve(strict=True)
        source.relative_to(root)
        if digest(source) != expected:
            raise ValueError("Frozen source changed before scoring")
    contract = json.loads((root / "SUBMISSION.json").read_text())
    methods = contract["methods"]
    expected = {f"aspirin--{method}.npz" for method in methods}
    if {p.name for p in predictions.glob("*.npz")} != expected:
        raise ValueError("Submit exactly all predeclared primary/control prediction packets")
    results = [
        {
            "method": method,
            **score_molecule(pack, "aspirin", predictions / f"aspirin--{method}.npz"),
        }
        for method in methods
    ]
    destination = release.parent / "confirmation"
    destination.mkdir(exist_ok=False)
    retain_json(
        destination / "RESULT.json",
        {
            "status": "scored-all-predeclared-procedures",
            "scores": results,
            "release_sha256": digest(release),
            "source_execution_verified": False,
            "formal_evidence_eligible": False,
            "note": "Scoring validates predictions, not frozen-code execution or independence",
        },
    )
    return destination / "RESULT.json"
