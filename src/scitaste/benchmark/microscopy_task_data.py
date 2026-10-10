"""Disjoint-reference microscopy restoration endpoints, not biological ground truth.

The scorer accepts predictions only. Independent source execution is separately
bound by a runner, with one target query budget per isolated inference process.
"""

import json
import zipfile

import numpy as np
from scipy.ndimage import gaussian_filter

from scitaste.benchmark.graph_task_data import bound_file, digest, retain_json
from scitaste.benchmark.graph_task_data import export_stage as export_bound_stage

TASK_ID = "microscopy-structure-restoration"
BUDGETS = (1, 2, 4, 8, 16)
DEVELOPMENT = ("confocal", "widefield")
TARGET = "twophoton"
IMAGE_SIZE = 512

# Public task obligations, not an evaluator-selected scientific solution. The
# stable IDs enable claim-level assessment without rewarding an empty manuscript.
CLAIM_RUBRIC = [
    {
        "claim_id": "reconstruction_quality",
        "requirement": (
            "Compare actual restoration with defensible matched-budget controls; retain all "
            "five PSNR endpoints, SSIM and FOV-paired evidence. No favorable-budget selection "
            "or pooled arbitrary score."
        ),
    },
    {
        "claim_id": "competing_explanation",
        "requirement": (
            "Execute a discriminating control for noise reduction versus smoothing distortion "
            "or the paper's alternative explanation, at the same capture budget and fields. "
            "Established Gaussian controls alone do not establish contribution novelty."
        ),
    },
    {
        "claim_id": "reference_reliability",
        "requirement": (
            "Disclose disjoint but noisy reference halves, unresolved specimen identity and "
            "dependent budgets. Frequency proxies and PSNR cannot establish biological "
            "fidelity, independent pixels or photon-dose efficiency."
        ),
    },
    {
        "claim_id": "procedure_transfer",
        "requirement": (
            "Use the unchanged source-frozen fitting/calibration procedure and all declared "
            "controls on TwoPhoton. Require its joint confirmation packet, not development "
            "scores, and distinguish procedural refitting from zero-shot weights."
        ),
    },
    {
        "claim_id": "evidence_revision",
        "requirement": (
            "Tie a retained, revised or rejected explanation to actual measured development/"
            "confirmation evidence; preserve negative controls, failures and unresolved "
            "alternatives. Reviewer obedience or a new name is not scientific progress."
        ),
    },
]


def export_stage(pack, destination, *, submission=None):
    return export_bound_stage(
        pack,
        destination,
        submission=submission,
        task_id=TASK_ID,
        release_schema="scitastebench.microscopy-release.v1",
    )


def ssim(reference, restored):
    """Wang-style 11x11 Gaussian SSIM, population moments, range 1, valid interior."""
    kwargs = {"sigma": 1.5, "truncate": 3.5, "mode": "reflect"}
    x, y = np.asarray(reference, dtype=np.float64), np.asarray(restored, dtype=np.float64)
    mx, my = gaussian_filter(x, **kwargs), gaussian_filter(y, **kwargs)
    vx = np.maximum(gaussian_filter(x * x, **kwargs) - mx * mx, 0)
    vy = np.maximum(gaussian_filter(y * y, **kwargs) - my * my, 0)
    cov = gaussian_filter(x * y, **kwargs) - mx * my
    c1, c2 = 0.01**2, 0.03**2
    values = ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(values[5:-5, 5:-5].mean())


def bandpass(image):
    """Fixed image-frequency diagnostic; not segmentation/biological truth."""
    x = np.asarray(image, dtype=np.float64)
    return (gaussian_filter(x, 1.0) - gaussian_filter(x, 2.0))[16:-16, 16:-16]


def reference_diagnostics(a, b):
    pa, pb = bandpass(a), bandpass(b)
    pa, pb = pa - pa.mean(), pb - pb.mean()
    scale = float(np.linalg.norm(pa) * np.linalg.norm(pb))
    return {
        "half_reference_mse": float(np.mean((a - b) ** 2)),
        "conditional_reference_noise_floor": float(np.mean((a - b) ** 2) / 4),
        "bandpass_half_agreement": float(np.sum(pa * pb) / scale) if scale else None,
        "reference_independence_stationarity_verified": False,
    }


def score_restoration(pack, modality, budget, predictions, *, partition="confirmation"):
    pack = pack.resolve(strict=True)
    manifest = json.loads((pack / "PACK.json").read_text())
    if (
        manifest.get("task_id") != TASK_ID
        or budget not in BUDGETS
        or partition not in {"validation", "confirmation"}
        or (partition == "confirmation" and modality != TARGET)
        or (partition == "validation" and modality not in DEVELOPMENT)
    ):
        raise ValueError("Invalid microscopy endpoint")
    label_path = bound_file(pack, manifest, f"private/{modality}-{partition}.npz")
    with np.load(label_path, allow_pickle=False) as labels:
        ids, a, b = (labels[k] for k in ("fov_id", "reference_a", "reference_b"))
    if predictions.is_symlink() or predictions.stat().st_size > 100_000_000:
        raise ValueError("Prediction packet must be a bounded regular file")
    with zipfile.ZipFile(predictions) as archive:
        names = archive.namelist()
        if (
            set(names) != {"fov_id.npy", "restored.npy"}
            or len(names) != 2
            or sum(row.file_size for row in archive.infolist()) > 64_000_000
        ):
            raise ValueError("Unexpected or oversized decompressed prediction arrays")
    with np.load(predictions, allow_pickle=False) as packet:
        if set(packet.files) != {"fov_id", "restored"}:
            raise ValueError("Prediction packet contains unexpected fields")
        offered, restored = packet["fov_id"], packet["restored"]
    if (
        offered.ndim != 1
        or not np.issubdtype(offered.dtype, np.integer)
        or len(np.unique(offered)) != len(offered)
        or set(offered) != set(ids)
        or restored.shape != (len(ids), IMAGE_SIZE, IMAGE_SIZE)
        or not np.isfinite(restored).all()
        or np.any(restored < 0)
        or np.any(restored > 1)
    ):
        raise ValueError("Require exact FOV coverage and finite [0,1] restored images")
    order = {int(fov): i for i, fov in enumerate(offered)}
    rows = []
    for i, fov in enumerate(ids):
        image = np.asarray(restored[order[int(fov)]], dtype=np.float64)
        ra, rb = np.asarray(a[i], dtype=np.float64), np.asarray(b[i], dtype=np.float64)
        ref = (ra + rb) / 2
        mse = float(np.mean((image - ref) ** 2))
        mse_a, mse_b = (float(np.mean((image - r) ** 2)) for r in (ra, rb))
        diagnostic = reference_diagnostics(ra, rb)
        rows.append(
            {
                "fov_id": int(fov),
                "mse": mse,
                # Preserve exact-zero MSE separately instead of emitting invalid JSON infinity.
                "psnr_db": float(-10 * np.log10(mse)) if mse else None,
                "exact_zero_mse": mse == 0,
                "ssim": ssim(ref, image),
                "reference_a_mse": mse_a,
                "reference_b_mse": mse_b,
                "conditional_noise_corrected_mse": (
                    mse - diagnostic["conditional_reference_noise_floor"]
                ),
                "bandpass_mse": float(np.mean((bandpass(image) - bandpass(ref)) ** 2)),
                **diagnostic,
            }
        )
    return {
        "task_id": TASK_ID,
        "modality": modality,
        "input_capture_count": budget,
        "fov_count": len(rows),
        "mean_fov_psnr_db": (
            float(np.mean([r["psnr_db"] for r in rows]))
            if all(r["psnr_db"] is not None for r in rows)
            else None
        ),
        "mean_fov_ssim": float(np.mean([r["ssim"] for r in rows])),
        "mean_fov_mse": float(np.mean([r["mse"] for r in rows])),
        "mean_fov_bandpass_mse": float(np.mean([r["bandpass_mse"] for r in rows])),
        "fovs": rows,
        "prediction_sha256": digest(predictions),
        "reference_sha256": digest(label_path),
        "reference": "34 disjoint captures, two balanced17-frame halves; still noisy",
        "scientific_scope": (
            "static restoration, equal FOV weighting, repeated budgets not independent tasks; "
            "bandpass is an unvalidated spatial-frequency proxy, not biological fidelity"
        ),
        "source_execution_verified": False,
        "formal_evidence_eligible": False,
    }


def confirm_submission(pack, release, predictions):
    receipt = json.loads(release.read_text())
    if (
        receipt.get("task_id") != TASK_ID
        or receipt.get("phase") != "transfer"
        or receipt.get("pack_sha256") != digest(pack / "PACK.json")
        or not receipt.get("frozen_source")
    ):
        raise ValueError("Require source-frozen microscopy target release")
    root = (release.parent / "frozen_submission").resolve(strict=True)
    for name, expected in receipt["frozen_source"].items():
        path = (root / name).resolve(strict=True)
        path.relative_to(root)
        if path.is_symlink() or digest(path) != expected:
            raise ValueError("Frozen source changed")
    submission = json.loads((root / "SUBMISSION.json").read_text())
    expected = {
        f"{TARGET}--b{budget}--{method}.npz"
        for budget in BUDGETS
        for method in submission["methods"]
    }
    if {p.name for p in predictions.glob("*.npz")} != expected:
        raise ValueError("Joint score requires all and only declared budget/control packets")
    result = {
        "status": "scored-all-predeclared-procedures",
        "scores": [
            {
                "method": method,
                **score_restoration(
                    pack, TARGET, budget, predictions / f"{TARGET}--b{budget}--{method}.npz"
                ),
            }
            for budget in BUDGETS
            for method in submission["methods"]
        ],
        "release_sha256": digest(release),
        "source_execution_verified": False,
        "budget_isolation_verified": False,
        "formal_evidence_eligible": False,
        "note": "Scoring binds predictions, not execution, reference independence or biology",
    }
    destination = release.parent / "confirmation"
    destination.mkdir(exist_ok=False)
    retain_json(destination / "RESULT.json", result)
    return destination / "RESULT.json"
