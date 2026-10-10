"""Materialize one staged molecular task from the inspected official rMD17 source.

No framework/model experiment runs here. Construction reads numerical labels only
to preserve them; split selection uses original trajectory indices, never outcomes.
"""
# ruff: noqa: E501 -- Frozen scientific protocol and primary-source URLs.

import argparse
import json
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scitaste.benchmark.molecular_task_data import TASK_ID, TIE_SEED, digest, retain_json

MOLECULES = ("ethanol", "malonaldehyde", "aspirin")
WINDOWS = {"train": (0.0, 0.50, 800), "calibration": (0.55, 0.70, 200), "query": (0.75, 1.0, 2000)}

BRIEF = """# When does geometric coverage predict force-field error?

Develop a falsifiable account of when geometric coverage identifies force-prediction
error and when predictor misspecification defeats it. Ethanol and malonaldehyde are
development contexts. Form competing explanations, execute informative matched
controls, choose a force predictor and risk-assessment procedure, and freeze their
code and selection policy before release of aspirin. A supported negative result
and appropriately narrowed explanation are admissible outcomes; mere renaming of
nearest-neighbor or established molecular uncertainty methods is not a contribution.

This is one scientific research task with three molecule contexts. The molecules,
atoms, coordinate components and sampled frames are not independent research tasks.
The observations are computed DFT references from the public rMD17 source, not
new experimental measurements or secret/uncontaminated test data.

## Information and experiment policy

Each molecule has 800 force-labeled fitting configurations and 200 separately
labeled calibration configurations: exactly 1,000 force-labeled configurations.
Calibration may select the predictor, geometry/risk mapping or stopping rule; do
not fit the force predictor on calibration labels and then report those same frames
as out-of-sample development evidence. Inner resampling uses fitting labels only.
All data transforms, force-predictor fitting and optimizer updates use the fitting
partition. A risk mapping may use the calibration partition, but performance of
that mapping on its calibration data is in-sample evidence and must be labeled so.
Do not request additional force labels or import the full source archive.

Development query files are the same 200 calibration geometries, not an additional
validation dataset. Development evidence can form/select hypotheses, not confirm
them. After code freeze, aspirin provides its fitting/calibration data and 2,000
later-index query geometries, with query forces never visible to the researcher.
Freeze ALL predeclared primary/control predictions before one joint score packet.
No target-feedback-driven parameter edits or replacement confirmation are allowed.

Coordinates are angstrom, forces kcal/mol/angstrom; atomic numbers and source atom
ordering are preserved. Force prediction and geometry/risk procedures can use coords
and atomic_numbers. In every exported NPZ, frame_id is the source archive's
old_indices value, not its randomized array row number: it is the explicit public
source-index coordinate. There is no separate old_indices array or private mapping
needed for temporal diagnostics. frame_id is not a force predictor input or a
source-label retrieval key. A temporal diagnostic using identity must
be explicitly separated from a geometry-only deployed procedure. The target refits
the predeclared procedure on its own allowed labels: this is procedure transfer,
not zero-shot weight transfer across different atom counts.

Sorting uses old_indices because stored source order is randomized. Source-index
windows [0,.50), [.55,.70), [.75,1) and their intervening gaps are frozen label-blind.
Sampling uses deterministic equally spaced ranks, not energy/error-based selection.
Gaps prevent adjacent split boundaries but do not prove statistical independence,
stationary dynamics, cross-trajectory transfer or a fixed physical time duration.
The source's original random-CV protocol is NOT this authored temporal protocol.

## Scientific endpoints and controls

Report per-configuration force-component MAE, averaged over configurations, in
kcal/mol/angstrom. Report primary selective MAE at .9 and secondary .5/.8/1.0, with
the same force predictions for competing risk selectors, uniform-selection expected
MAE and risk ties. Keep force-model accuracy, selective error and rigid-transform
consistency separate. No arbitrary sum, independent-atom CI or simulated dynamics
stability claim. Physical equivariance alone does not establish accuracy: zero
forces are equivariant too. Energy conservativity requires an actual energy-gradient
construction/check; it is not inferred from rotating stored vectors.

For a geometric-risk claim, hold the predictor fixed and compare geometry-based,
uninformative and genuinely discriminating alternative selectors. For a representation
or alignment claim, reuse identical exemplar selections and supervision where possible.
Prediction deterioration after a transformation is sensitivity evidence, not a
retrained-method comparison. Control quality and residual confounds must be assessed.

The supplied no-parameter-optimization nearest-exemplar/rigid-alignment reference is
label-conditioned, not label-free. It is an execution anchor, not a SOTA force field
or autonomous research-system baseline. Fitted neural experimental subjects, if
needed, execute on remote 4090-2 only; there is no local-GPU allocation or controller
training. Whole-framework budgets are assigned separately and commonly.

## Deliverables

Retain executed code, experiment/config/data/prediction identities and a concise
hypothesis log documenting which evidence changed the question or explanation.
Produce an initial report and evidence-based critique, then revise or justify an
evidence-backed stopping decision without target labels. Freeze SUBMISSION.json
and all source files before target release. The entrypoint accepts --data/--output
and emits aspirin--<method>.npz for EVERY declared method/control, containing only
frame_id, forces[N,21,3], risk_score[N]. Higher risk means greater expected error.
Prediction IDs must exactly cover the released target query identities once each.
Complete an evidence-grounded paper with method, related work, real development and
confirmation, alternative explanations and scope limitations. Reviews cannot turn
post-confirmation exploratory experiments into the original frozen evidence.
"""


def selected_indices(old_indices, low, high, count):
    """Index-only window and midpoint-rank sampling; no target-dependent edits."""
    width = int(old_indices.max()) - int(old_indices.min()) + 1
    u = (old_indices - int(old_indices.min())) / width
    pool = np.flatnonzero((u >= low) & (u < high))
    pool = pool[np.argsort(old_indices[pool], kind="stable")]
    if len(pool) < count:
        raise ValueError("Not enough configurations in frozen source-index window")
    ranks = np.floor((np.arange(count) + 0.5) * len(pool) / count).astype(np.int64)
    return pool[ranks], len(pool)


def save_npz(path, **arrays):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)


def materialize(source, destination, row):
    name = row["molecule"]
    path = source / f"rmd17_{name}.npz"
    if path.is_symlink() or digest(path) != row["sha256"]:
        raise ValueError("Inspected molecule source changed")
    public, private = destination / "public" / TASK_ID, destination / "private"
    with np.load(path, allow_pickle=False) as archive:
        ids = archive["old_indices"]
        charges, coords = (archive[k] for k in ("nuclear_charges", "coords"))
        if len(coords) != 100_000 or not np.isfinite(coords).all():
            raise ValueError("Unexpected molecular source shape or geometry")
        chosen, windows = {}, {}
        for partition, (low, high, count) in WINDOWS.items():
            indices, population = selected_indices(ids, low, high, count)
            chosen[partition] = indices
            windows[partition] = {
                "source_fraction": [low, high],
                "available_frames": population,
                "selected_frames": count,
                "selected_source_index_range": [int(ids[indices].min()), int(ids[indices].max())],
            }
        if len(np.unique(np.concatenate(list(chosen.values())))) != sum(
            len(indices) for indices in chosen.values()
        ):
            raise ValueError("Frozen molecular partitions overlap")
        retain_json(
            private / f"{name}-SPLIT.json",
            {
                "source_member_sha256": row["sha256"],
                "windows": windows,
                "source_indices": {key: ids[value].tolist() for key, value in chosen.items()},
                "retained_before_force_array_access": True,
                "label_based_selection": False,
            },
        )
        forces = archive["forces"]
        if forces.shape != coords.shape or not np.isfinite(forces).all():
            raise ValueError("Invalid revised force array")
        for partition in ("train", "calibration"):
            indices = chosen[partition]
            save_npz(
                public / f"{name}-{partition}.npz",
                frame_id=ids[indices],
                atomic_numbers=charges,
                coords=coords[indices],
                forces=forces[indices],
            )
        endpoint = "confirmation" if name == "aspirin" else "validation"
        indices = chosen["query" if name == "aspirin" else "calibration"]
        save_npz(
            public / f"{name}-query.npz",
            frame_id=ids[indices],
            atomic_numbers=charges,
            coords=coords[indices],
        )
        save_npz(
            private / f"{name}-{endpoint}-labels.npz",
            frame_id=ids[indices],
            forces=forces[indices],
        )
    return {
        "molecule": name,
        "role": "confirmation" if name == "aspirin" else "discovery",
        "atoms": len(charges),
        "source_member_sha256": row["sha256"],
        "fitting_frames": WINDOWS["train"][2],
        "calibration_frames": WINDOWS["calibration"][2],
        "total_force_labeled_frames": 1000,
        "query_frames": len(indices),
        "query_is_calibration": name != "aspirin",
        "windows": windows,
        "source_units": {"coords": "angstrom", "forces": "kcal/mol/angstrom"},
        "old_noisy_targets_exported": False,
        "split_independence_established": False,
    }


def build(source, output):
    source = source.resolve(strict=True)
    inspection_path = source / "SOURCE_INSPECTION.json"
    inspection = json.loads(inspection_path.read_text())
    if inspection["status"] != "source-members-inspected-not-task-materialized" or {
        row["molecule"] for row in inspection["members"]
    } != set(MOLECULES):
        raise ValueError("Require complete exact source inspection before task construction")
    output = output.resolve()
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("Pack must be separate from retained raw molecular sources")
    output.mkdir(parents=True, exist_ok=False)
    public, private = output / "public" / TASK_ID, output / "private"
    public.mkdir(parents=True)
    private.mkdir()
    contexts = [materialize(source, output, row) for row in inspection["members"]]
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "# Source attribution\n\nrMD17 v1, computed DFT reference configurations and forces; "
        "Christensen and von Lilienfeld, 2020. Official dataset CC0-1.0 declaration retained at acquisition.\n\n"
        "https://archive.materialscloud.org/record/2020.82\n"
        "https://doi.org/10.24435/materialscloud:wy-kn\n"
        "https://arxiv.org/abs/2007.09593\n\n"
        "SciTaste authors this staged research question and temporal data/feedback protocol, not the underlying observations. "
        "Public sources may have been seen by models or researchers; local release order does not establish secrecy.\n"
    )
    claims = [
        {
            "claim_id": "force_quality",
            "requirement": "Compare force MAE against actual matched controls, using identified predictions and units.",
        },
        {
            "claim_id": "risk_discrimination",
            "requirement": "Hold predictions fixed; compare selector error at fixed coverage and account for ties/temporal or predictor confounds.",
        },
        {
            "claim_id": "alternative_explanation",
            "requirement": "Run a control discriminating the central explanation from a genuine alternative; equivariance alone is insufficient.",
        },
        {
            "claim_id": "procedure_transfer",
            "requirement": "Use unchanged frozen fitting/selection/risk policy on aspirin, including controls; do not assert universal molecule or dynamics generalization.",
        },
        {
            "claim_id": "evidence_revision",
            "requirement": "Link a changed, narrowed or retained hypothesis to actual development/confirmation evidence, preserving adverse findings.",
        },
    ]
    retain_json(
        public / "PROTOCOL.json",
        {
            "schema_version": "scitastebench.molecular-research.v1",
            "task_id": TASK_ID,
            "research_task_families": 1,
            "split": "candidate-unassigned",
            "discovery_contexts": ["ethanol", "malonaldehyde"],
            "confirmation_context": "aspirin",
            "source_archive_sha256": inspection["source_archive_sha256"],
            "public_array_schema": {
                "frame_id": {
                    "shape": "[N]",
                    "dtype": "int64",
                    "source": "source NPZ old_indices, copied without remapping",
                    "meaning": "explicit original-trajectory source index, not stored source row",
                    "allowed_use": "identity matching, label-blind ties and separate temporal diagnostics",
                    "forbidden_use": "force predictor input or public source-label retrieval",
                    "separate_old_indices_required": False,
                },
                "coords": "float64[N, atoms, 3], angstrom",
                "atomic_numbers": "uint8[atoms], fixed source atom order",
                "forces": "float64[N, atoms, 3], kcal/mol/angstrom; absent from query",
            },
            "source_index_windows": WINDOWS,
            "primary_selective_coverage": 0.9,
            "secondary_selective_coverages": [0.5, 0.8, 1.0],
            "risk_tie_policy": {
                "method": "SHA256 of fixed seed and frame_id, not chronology",
                "seed": TIE_SEED,
            },
            "time_diagnostic": "four equal source-index span bins within query range; same predictions and per-bin selected risk versus uniform expectation",
            "selective_error_reporting": "accepted/rejected MAE, full-set worst5% MAE and retained fraction",
            "sampling": "midpoint-spaced ranks within source-index-sorted windows; labels not used",
            "labels_per_context": {
                "force_fitting": 800,
                "risk_calibration_and_selection": 200,
                "total": 1000,
            },
            "discovery_query": "same calibration frames; selection evidence, not a held-out scientific confirmation",
            "claim_rubric": claims,
            "confirmation": "source freeze before aspirin inputs; all method/control predictions together before one score packet",
            "framework_budget": None,
            "reference_is_system_baseline": False,
            "controller_training": False,
            "gpu_destination_if_needed": "remote 4090-2 only; no reservation or experiment launched",
            "formal_evidence_eligible": False,
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "required_claims": claims,
            "constructs": [
                "force accuracy",
                "conditional selective risk",
                "mechanism control",
                "procedure transfer",
                "evidence-driven revision",
            ],
            "evidence_chain": "claim -> data/window/config/code/prediction identity -> matched comparator -> metric/units -> scope",
            "judge": "AI-only; numerical/scope anchors and natural-claim calibration remain separate obligations",
            "confounds": [
                "trajectory correlation",
                "risk calibrator in-sample error",
                "geometry versus predictor misspecification",
                "symmetry versus accuracy",
                "different atom counts",
                "public-source contamination",
            ],
            "no_human_gold": True,
        },
    )
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "research.py",
            "files": ["research.py"],
            "selection_rule": "REPLACE with exact development selection rule",
            "fit_policy": "REPLACE with fitting/calibration supervision, transforms, stopping and seeds",
            "risk_policy": "REPLACE with predictor-conditioned risk mapping and deterministic tie handling",
            "scope": "REPLACE with supported conclusion population and limitations",
            "methods": ["primary", "key_control"],
            "hypotheses": [
                {
                    "statement": "REPLACE with explanation",
                    "discriminating_prediction": "REPLACE with predicted control outcome",
                },
                {
                    "statement": "REPLACE with competing explanation",
                    "discriminating_prediction": "REPLACE with distinguishing outcome",
                },
            ],
        },
    )
    shutil.copy2(Path(__file__).with_name("molecular_task_reference.py"), public / "reference.py")
    shutil.copy2(Path(__file__), private / "builder.py")
    from scitaste.benchmark import molecular_task_data

    shutil.copy2(Path(molecular_task_data.__file__), private / "scorer.py")
    shutil.copy2(inspection_path, private / "SOURCE_INSPECTION.json")
    retain_json(
        private / "DATA_QUALITY.json",
        {"contexts": contexts, "labels_drive_selection": False, "formal_quality_certified": False},
    )
    retain_json(
        private / "ENVIRONMENT.json", {"python": platform.python_version(), "numpy": np.__version__}
    )
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    transfer = sorted(name for name in files if name.startswith(f"public/{TASK_ID}/aspirin-"))
    discovery = sorted(
        name for name in files if name.startswith(f"public/{TASK_ID}/") and name not in transfer
    )
    retain_json(
        output / "PACK.json",
        {
            "schema_version": "scitastebench.molecular-task-data.v1",
            "task_id": TASK_ID,
            "created_at": datetime.now(UTC).isoformat(),
            "contexts": contexts,
            "research_task_families": 1,
            "discovery_files": discovery,
            "transfer_files": transfer,
            "files": files,
            "source_inspection_sha256": digest(inspection_path),
            "source_observations_newly_collected": False,
            "rights": "source CC0-1.0; source paper and unrelated software not relicensed",
            "formal_release": False,
            "framework_comparison_executed": False,
            "exposure": "authoring/reference access; prior public-source or model-training exposure unknown",
        },
    )
    return {
        "pack": str(output),
        "research_families": 1,
        "contexts": len(contexts),
        "formal_release": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))
