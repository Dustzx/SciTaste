"""Build a real microscopy task with identity-only disjoint frame/reference splits."""
# ruff: noqa: E501 -- Frozen scientific protocol prose and source identifiers.

import argparse
import hashlib
import json
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

from scitaste.benchmark.microscopy_task_data import (
    BUDGETS,
    CLAIM_RUBRIC,
    TASK_ID,
    digest,
    reference_diagnostics,
    retain_json,
)

MODALITIES = {
    "confocal": "Confocal_BPAE_G",
    "widefield": "WideField_BPAE_G",
    "twophoton": "TwoPhoton_BPAE_G",
}
PARTITIONS = {"train": list(range(1, 11)), "calibration": list(range(11, 15))}

BRIEF = """# When does noise reduction preserve weak spatial information?

Develop a falsifiable account of when restoration improves an image and when
smoothing suppresses reproducible spatial information. Use real fluorescence
microscopy observations to form competing explanations, choose discriminating
controls, and develop a restoration procedure or a useful negative finding.
Confocal and wide-field BPAE F-actin images are development contexts; freeze the
procedure and all controls before two-photon confirmation. Established Gaussian
smoothing, denoising or a new method name alone is not a scientific contribution.
The question is open research: a narrowed, supported conclusion is admissible.

## What the observations support

This is ONE research task family with three modality contexts, not thousands of
independent tasks or a new biological study. Each context has20 nominal FOVs and
50 repeated512x5128-bit observations per FOV. Pixels and repeats are dependent.
Same integerFOV across modalities is not proof of same physical field; identity
across sources remains unresolved. Do not claim organism/specimen generalization
or independent cross-modality biological replicates. These public2019source images
may occur in model training; staging does not prove novelty or contamination absence.

Fit FOVs 1-10, calibrate 11-14, confirm 15-20, consistently across all modalities.
Development confirmationFOVs are UNUSED, including their reference images. Target
FOVs 15-20 appear only after code freeze. Unknown physical correspondence across
different source IDs remains a limitation, not a verified independence claim.

EachFOV has an identity-only deterministic16-capture input pool and34 DISJOINT
reference captures. Nested means use1/2/4/8/16 input captures. Reference halves
split each ordinal-adjacent pair by an identity-only hash bit,17 each. The34-frame mean remains
noisy, not biological ground truth. Officialavg50/circular source averages are
not inputs or targets because they overlap input observations. No preprocessing
registration or intensity renormalization is applied; values are original/255.

## Research and inference boundary

Train/calibration files provide images at all five budgets plus disjoint reference
halves. Predictor parameter fitting uses TRAIN FOVs only. Calibration may select
hyperparameters/procedures; performance on a selected calibration set is development,
not confirmation. Learned experimental subjects may be trained, but SciTaste itself
is not trained by this task. GPU experiments require remote4090-2, never localGPU.
No additional source images/references/labels may be retrieved.
Fit experimental subjects from scratch unless external pretraining provenance proves
no exposure to these source/confirmation fields. Original FMD pretrained checkpoints
are forbidden: the original source training held out onlyFOV19, not this new split.

The entrypoint accepts--data/--output and reads QUERY.json plus the named queryNPZ.
Each confirmation invocation sees one modality and ONE input-capture budget for
query FOVs. It must not use other query budgets, source archives, input raw pools,
capture/reference identities, private diagnostics or confirmation-reference values.
Train/calibration FOVs may contain all noise budgets. Same unchanged source runs
separately at each budget. Joint predictions are scored once after ALL methods and
budgets finish. Runtime isolation/output receipts, not scoring alone, establish
that higher-budget target information was unavailable to a lower-budget process.

This is static computational restoration, NOT adaptive acquisition, photon-dose,
exposure-time, bleaching optimization, online stopping or photon-efficiency research.
Numbers of averaged frames are not comparable physical dose across instruments.
Target training/calibration files refit the predeclared procedure after freeze;
weights need not transfer, and every adaptation must use allowed targetfit/calFOVs.

## Scientific evaluation and controls

Primary: mean perFOV PSNR versus the34-frame independent reference, separately
for every budget and modality. Secondary: mean perFOV SSIM (11x11Gaussian1.5,
population moments, range1), MSE, and perFOV paired comparisons. No pooling budgets
or modalities into an arbitrary scalar. Report six confirmationFOVs as six fields,
not pixel-count-powered significance or six research tasks.
Freeze the comparator, practical-effect criterion and interpretation of the FIVE
prespecified budget endpoints together; never choose the favorable budget afterward.
Do not claim a win by treating the curve as five independent chances for success.

Image-frequency diagnostics: fixed Gaussian1 minus Gaussian2 bandpass MSE and
agreement between reference halves, with fixed16pixel border crop. This is NOT
a validated biological/weak-feature fidelity endpoint. A method cannot claim
preserved biological structure using it alone. Report A/Breference MSE separately;
half-disagreement/4 is only a conditional reference-noise estimate assuming
stationary independent repeat noise. Any noise-corrected MSE, negative values and
reference disagreement remain visible; do not silently clip or discard FOVs.

Compare restoration at the SAME budget and reference/FOVs. Contrast conservative
noise reduction with deliberate oversmoothing, identity/raw average and strong
appropriate restoration references; choose your own evidence-discriminating controls.
Across-budget mean improvement is not evidence for a learned denoiser. More PSNR
does not prove structure fidelity or contribution novelty. The supplied fixed
Gaussian controls are execution anchors, not SOTA or autonomous system baselines.

## Deliverables

Run actual experiments, record which observation changes each hypothesis and what
alternative explanation remains. Produce an initial report and evidence critique,
then revise or give an evidence-supported stopping rationale without hidden labels.
Freeze SUBMISSION.json, full source files, primary/control IDs, selection and fit
policy, competing explanations and discriminating predictions before target release.
Emit <modality>--b<budget>--<method>.npz for EVERY declared method/control, containing
fov_id and restored[N,512,512] in[0,1]. Declare and retain inference clipping instead
of letting the scorer silently repair predictions. Complete a paper with real
results, methods, related work, evidence-supported conclusions and limitations.
Post-target exploratory tests cannot replace original confirmation or erase failure.

Data reuse is CC BY-SA4.0, code separately licensed. Retain source attribution,
modification notices and share-alike terms for redistributed derived image assets.
"""


def save_npz(path, **arrays):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)


def capture_split(modality, fov):
    keys = [
        (hashlib.sha256(f"{TASK_ID}/v1/{modality}/{fov}/{i}".encode()).hexdigest(), i)
        for i in range(50)
    ]
    order = [i for _, i in sorted(keys)]
    remaining = sorted(order[16:])
    left, right = [], []
    for a, b in zip(remaining[::2], remaining[1::2], strict=True):
        bit = (
            hashlib.sha256(f"{TASK_ID}/halves/v1/{modality}/{fov}/{a}/{b}".encode()).digest()[0] & 1
        )
        left.append(b if bit else a)
        right.append(a if bit else b)
    return order[:16], left, right


def registration_proxy(a, b):
    """Approximate integer phase-correlation shift, not subpixel registration proof."""
    a, b = (gaussian_filter(x, 2) for x in (a, b))
    cross = np.fft.fft2(a - a.mean()) * np.conj(np.fft.fft2(b - b.mean()))
    cross /= np.maximum(np.abs(cross), 1e-12)
    corr = np.fft.ifft2(cross).real
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    return [int(p if p <= 256 else p - 512) for p in peak]


def materialize_context(source, output, modality, source_name):
    metadata_path = source / f"private/{source_name}.json"
    metadata = json.loads(metadata_path.read_text())
    records = {(r["fov"], r["capture"]): r for r in metadata["frames"]}
    public, private = output / "public" / TASK_ID, output / "private"
    fovs = range(1, 21) if modality == "twophoton" else range(1, 15)
    plans = {fov: capture_split(modality, fov) for fov in fovs}
    retain_json(
        private / f"{modality}-SPLIT.json",
        {
            "modality": modality,
            "source_metadata_sha256": digest(metadata_path),
            "partitions": {**PARTITIONS, "confirmation": list(range(15, 21))},
            "frame_membership": {
                str(fov): {"input_pool": a, "reference_a": b, "reference_b": c}
                for fov, (a, b, c) in plans.items()
            },
            "retained_before_pixel_access": True,
            "selection_uses_image_values": False,
        },
    )
    rows, diagnostics = [], []
    for fov, (inputs, left, right) in plans.items():
        if len(set(inputs + left + right)) != 50 or len(left) != 17 or len(right) != 17:
            raise ValueError("Input and reference groups must exactly partition50 captures")
        frames = []
        for capture in range(50):
            row = records[fov, capture]
            path = source / row["relative_path"]
            path.resolve(strict=True).relative_to(source)
            if path.is_symlink() or digest(path) != row["sha256"]:
                raise ValueError("Raw image differs from retained inspection")
            with Image.open(path) as image:
                pixels = np.asarray(image)
                if (
                    pixels.shape != (512, 512)
                    or pixels.dtype != np.uint8
                    or hashlib.sha256(pixels.tobytes()).hexdigest() != row["pixel_sha256"]
                ):
                    raise ValueError("Original decoded capture mismatch")
                frames.append(pixels.copy())
        stack = np.stack(frames).astype(np.float64) / 255.0
        a, b = stack[left].mean(axis=0), stack[right].mean(axis=0)
        means = np.stack([stack[inputs[:budget]].mean(axis=0) for budget in BUDGETS])
        rows.append((fov, means.astype(np.float32), a.astype(np.float32), b.astype(np.float32)))
        brightness = stack.mean(axis=(1, 2))
        diagnostics.append(
            {
                "fov_id": fov,
                **reference_diagnostics(a, b),
                "approximate_integer_half_shift_yx": registration_proxy(a, b),
                "ordinal_mean_brightness_slope": float(np.polyfit(np.arange(50), brightness, 1)[0]),
                "first_last_quartile_brightness_delta": float(
                    brightness[-12:].mean() - brightness[:12].mean()
                ),
                "upper_clipped_fraction": float(np.mean(stack == 1)),
                "excluded": False,
            }
        )
    for name, ids in PARTITIONS.items():
        selected = [r for r in rows if r[0] in ids]
        save_npz(
            public / f"{modality}-{name}.npz",
            fov_id=np.array([r[0] for r in selected], dtype=np.int64),
            budgets=np.array(BUDGETS, dtype=np.int64),
            images=np.stack([r[1] for r in selected]),
            reference_a=np.stack([r[2] for r in selected]),
            reference_b=np.stack([r[3] for r in selected]),
        )
    query_ids = list(range(15, 21)) if modality == "twophoton" else PARTITIONS["calibration"]
    selected = [r for r in rows if r[0] in query_ids]
    for i, budget in enumerate(BUDGETS):
        save_npz(
            public / f"{modality}-query-b{budget}.npz",
            fov_id=np.array(query_ids, dtype=np.int64),
            images=np.stack([r[1][i] for r in selected]),
        )
    endpoint = "confirmation" if modality == "twophoton" else "validation"
    save_npz(
        private / f"{modality}-{endpoint}.npz",
        fov_id=np.array(query_ids, dtype=np.int64),
        reference_a=np.stack([r[2] for r in selected]),
        reference_b=np.stack([r[3] for r in selected]),
    )
    retain_json(
        private / f"{modality}-REFERENCE_QUALITY.json",
        {"fovs": diagnostics, "no_value_based_exclusions": True},
    )
    return {
        "modality": modality,
        "fitting_fovs": 10,
        "calibration_fovs": 4,
        "query_fovs": len(query_ids),
        "raw_captures_used": len(rows) * 50,
    }


def build(source, output):
    source = source.resolve(strict=True)
    if (
        json.loads((source / "SOURCE_INSPECTION.json").read_text())["status"]
        != "raw-source-inspected-not-task-materialized"
    ):
        raise ValueError("Require completed raw source inspection")
    critic_path = source / "PROTOCOL_CRITIQUE.json"
    if not critic_path.is_file():
        raise ValueError("Retain completed design critique before immutable task construction")
    output = output.resolve()
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("Never overwrite source acquisition/inspection")
    output.mkdir(parents=True, exist_ok=False)
    public, private = output / "public" / TASK_ID, output / "private"
    public.mkdir(parents=True)
    private.mkdir()
    for artifact in (
        Path(__file__),
        Path(__import__("scitaste.benchmark.microscopy_task_data", fromlist=["x"]).__file__),
    ):
        shutil.copy2(artifact, private / artifact.name)
    retain_json(
        private / "ENVIRONMENT.json", {"python": platform.python_version(), "numpy": np.__version__}
    )
    shutil.copy2(critic_path, private / "PROTOCOL_CRITIQUE.json")
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "# Source attribution and derivative notice\n\nYide Zhang et al., A Poisson-Gaussian Denoising Dataset with Real Fluorescence Microscopy Images (CVPR2019).\n"
        "Source: https://curate.nd.edu/articles/dataset/Fluorescence_Microscopy_Denoising_FMD_dataset/24744648 ; DOI10.7274/r0-ed2r-4052.\n"
        "Data: CC BY-SA4.0 https://creativecommons.org/licenses/by-sa/4.0/ . Source code license is separate.\n"
        "Modifications: selected three BPAE G-channel modalities, disjoint averaging/input pools, FOV splits, division by255, float32 export. Derived image assets retain attribution/share-alike.\n"
        "This is not the source benchmark's circular-average or official test protocol; no official numbers are reproduced.\n"
    )
    protocol = {
        "schema_version": "scitastebench.microscopy-research.v2",
        "task_id": TASK_ID,
        "contexts": MODALITIES,
        "fov_partitions": {**PARTITIONS, "confirmation": list(range(15, 21))},
        "capture_budgets": list(BUDGETS),
        "input_reference_overlap": False,
        "nested_input_pool_size": 16,
        "disjoint_reference_size": 34,
        "per_budget_target_process_isolation_required": True,
        "all_methods_and_budgets_scored_together": True,
        "primary": "per-budget meanFOV PSNR versus34disjointframe mean",
        "secondary": "SSIM/MSE; bandpass only unvalidated image-frequency diagnostic",
        "frame_pixel_task_independence": False,
        "cross_modality_physical_identity": "unresolved",
        "claim_rubric": CLAIM_RUBRIC,
        "formal_evidence_eligible": False,
    }
    retain_json(public / "PROTOCOL.json", protocol)
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claims": [
                "noise reduction vs smoothing distortion",
                "matched-budget contribution",
                "reference reliability",
                "procedure transfer",
            ],
            "falsification": "discriminating alternatives with real results, no compulsory positive winner",
            "prohibitions": [
                "PSNR means biological fidelity",
                "averaging benefit means learned restoration",
                "pixels are independent tasks",
                "engineer controls are frameworks",
            ],
            "reviewer_access": "development labels allowed; confirmation pixels/reference remain private",
            "reviewer_type": "AI-only, not independently calibrated human gold",
        },
    )
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "research.py",
            "files": ["research.py"],
            "methods": ["primary", "matched_control"],
            "selection_rule": "REPLACE with development-only selection",
            "fit_policy": "REPLACE with fitting/calibration and budget policy",
            "scope": "REPLACE with evidence-supported scope and limitations",
            "hypotheses": [{"statement": "REPLACE", "discriminating_prediction": "REPLACE"}] * 2,
        },
    )
    shutil.copy2(Path(__file__).with_name("microscopy_task_reference.py"), public / "reference.py")
    contexts = [
        materialize_context(source, output, name, source_name)
        for name, source_name in MODALITIES.items()
    ]
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    public_files = [name for name in files if name.startswith("public/")]
    transfer = [name for name in public_files if Path(name).name.startswith("twophoton-")]
    manifest = {
        "schema_version": "scitastebench.microscopy-pack.v1",
        "task_id": TASK_ID,
        "status": "candidate-materialized-not-formally-admitted",
        "created_at": datetime.now(UTC).isoformat(),
        "source_inspection_sha256": digest(source / "SOURCE_INSPECTION.json"),
        "methodological_critique_sha256": digest(critic_path),
        "contexts": contexts,
        "files": files,
        "discovery_files": [name for name in public_files if name not in transfer],
        "transfer_files": transfer,
        "independent_task_families": 1,
        "new_physical_observations": False,
        "formal_evidence_eligible": False,
        "data_license": "CC BY-SA4.0",
        "author_target_access": True,
    }
    retain_json(output / "PACK.json", manifest)
    print(
        json.dumps(
            {k: manifest[k] for k in ("task_id", "status", "contexts", "independent_task_families")}
        ),
        flush=True,
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
