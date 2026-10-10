"""Freeze a new source family using structures/IDs, never prediction outcomes."""
# ruff: noqa: E501, RUF001 -- Fixed scientific brief and claim obligations.

import argparse
import hashlib
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json
from scitaste.benchmark.qm9_task_data import TASK_ID

HARTREE_EV = 27.211386245988
SEED = "scitastebench/qm9-gap/v1/20261007"
ATOMS = {"H": 1, "C": 6, "N": 7, "O": 8, "F": 9}
SIZES = {
    "train": 6000,
    "small-validation": 1000,
    "large-validation": 1000,
    "small-query": 1000,
    "large-query": 3000,
}

BRIEF = """# How can electronic-property prediction survive molecular-size extrapolation?

Develop and empirically test an explanation of which structural information and
learning choices make electronic-gap prediction reliable when molecules become
larger. Propose your own competing hypotheses and discriminating experiments;
the author does not prescribe a model, preferred explanation or positive result.
An invariance demonstration, a better validation score, or swapping a regressor
is not itself a new scientific contribution. A rigorously supported failure
boundary or negative conclusion is valid. Do not claim SOTA from these controls.

## Real research material

QM9 provides relaxed geometries and DFT HOMO–LUMO gaps. Atomic numbers and
coordinates are the only permissible predictive inputs. Coordinates are Å and
gap_ev is eV, converted from source Hartree by 27.211386245988. These are computed
DFT values, not observed experimental chemistry. The supplied source exclusion
list removes uncharacterized molecules before any split or result is chosen.

train.npz contains 6,000 labelled molecules with <=8 heavy (non-H) atoms. Fit
representations, normalizers and predictor parameters only on that file.
small-validation.npz (1,000 <=8-heavy-atom molecules) and large-validation.npz
(1,000 nine-heavy-atom molecules) support experiment analysis and selection of a
procedure/hyperparameters, but not fitting predictive or representation parameters.
Validation is public exploratory evidence, not private confirmation. Larger
validation molecules mean that the larger-molecule distribution is not unseen.
Only distinct molecular identities contribute samples; transformations, atom
components, properties, seeds and framework stages are not separate research tasks.

Predictors can use geometry, atomic identities and derived descriptors; never
original GDB indices, file ordering or other quantum properties. All arrays are
padded to 29 atoms: atomic_numbers[N,29], coords[N,29,3], molecule_id[N]. Zero
atomic numbers mark padding and its positions must be ignored. IDs are opaque
identifiers for joining predictions, not features. Source molecular identities
and target gaps remain evaluator-private. Do not download original QM9 labels or
another project's artifacts. Public-source/model prior exposure is unknown.

reference.py supplies atom-count ridge, element-resolved radial histogram
ExtraTrees and Nyström kernel ridge as ordinary executable controls. They are
not AutoResearch systems, a competitive deep molecular architecture, or SOTA.
Compare to genuine matched controls and justify missing strong comparators when
making scientific claims. Angular/global information, inductive bias, selection
overfit, sample exposure and prediction cost are plausible competing explanations;
do not treat a gain as causal identification. Choose a focused experimental
program instead of running a large search or repeating until a positive result.

## Prospective confirmation and research delivery

Freeze all declared procedures, controls, competing hypotheses, discrimination
predictions, fit policy and selection rule as a self-contained submission before
the confirmation inputs are released. The same unchanged program is executed
on 1,000 unseen small and 3,000 unseen nine-heavy-atom molecules, fitted from the
same permitted train.npz. All methods are scored jointly once. Primary endpoint
is nine-heavy-atom MAE (eV); small-molecule MAE, RMSE and 90th-percentile absolute
error are separate diagnostics. This is a new authored size-extrapolation task
within QM9, not an official random-split leaderboard or another source domain.

Entry point: --data DIRECTORY --output DIRECTORY. QUERY.json describes the small
and large redacted query NPZs. Emit exactly small--METHOD.npz and large--METHOD.npz
for every frozen method, containing only molecule_id[N] and gap_ev[N]. Include
all helpers in the submitted file list; no workspace caches are mounted. Fit
only on train.npz; choose on public validations only. Never fit on query inputs
or private labels. Place auxiliary arrays inside output subdirectories, not at
top level. After every submitted source and SUBMISSION.json is final, write
submission/READY. No manual program repair or refreeze after this marker.

Inspect confirmation_feedback.json before your final scientific interpretation.
Retain failures and missing outcomes, not invented values or validation results
substituted for confirmation. Produce real code, measurements, informative
figures, a research paper and evidence-based critique/revision, with claims
bounded by the executed evidence. Extrapolation to larger molecules here does
not demonstrate universality, novel elements, dynamics, experimentally measured
band gaps, physical causal mechanisms or general autonomous research quality.
"""

CLAIMS = [
    {
        "claim_id": "prediction",
        "requirement": "Report target MAE in eV for all declared controls, including failure/missing outcomes.",
    },
    {
        "claim_id": "learning_boundary",
        "requirement": "Fit only on train; distinguish validation selection from fitting and target confirmation.",
    },
    {
        "claim_id": "scientific_explanation",
        "requirement": "Execute a control distinguishing the central explanation from a plausible alternative.",
    },
    {
        "claim_id": "structural_symmetry",
        "requirement": "Distinguish valid input symmetries from information loss and predictive superiority.",
    },
    {
        "claim_id": "scope",
        "requirement": "No unsupported official-QM9/SOTA, new-domain, new-element, dynamics, causality or measured-chemistry claim.",
    },
    {
        "claim_id": "cost_and_novelty",
        "requirement": "Separate actual fit/inference cost and ordinary engineering from scientific insight and novelty.",
    },
]


def build(source, output):
    acquisition = json.loads((source / "ACQUISITION.json").read_text())
    for row in acquisition["files"]:
        if digest(source / row["name"]) != row["sha256"]:
            raise ValueError("Official source bytes changed")
    excluded = {
        int(line.split()[0])
        for line in (source / "uncharacterized.txt").read_text().splitlines()
        if line.split() and line.split()[0].isdigit()
    }
    if len(excluded) != 3054:
        raise ValueError("Source exclusion list changed")
    rows, groups = [], set()
    with tarfile.open(source / "dsgdb9nsd.xyz.tar.bz2", "r:bz2") as archive:
        for member in archive:
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            lines = stream.read().decode().splitlines()
            count, metadata = int(lines[0]), lines[1].split()
            identifier = int(metadata[1])
            if identifier in excluded:
                continue
            # Canonical relaxed InChI supplied by QM9; group all identical strings.
            identity = lines[-1].split()[-1]
            if identity in groups:
                continue
            groups.add(identity)
            atoms = np.array(
                [ATOMS[line.split()[0]] for line in lines[2 : 2 + count]], dtype=np.int16
            )
            coords = np.array(
                [
                    [float(x.replace("*^", "e")) for x in line.split()[1:4]]
                    for line in lines[2 : 2 + count]
                ],
                dtype=np.float64,
            )
            gap = float(metadata[9]) * HARTREE_EV
            if count > 29 or not np.isfinite(coords).all() or not np.isfinite(gap) or gap < 0:
                raise ValueError("Invalid source structure or target")
            rank = hashlib.sha256(f"{SEED}:{identifier}".encode()).hexdigest()
            rows.append((rank, identifier, identity, atoms, coords, gap))
    small = sorted([r for r in rows if np.count_nonzero(r[3] != 1) <= 8])
    large = sorted([r for r in rows if np.count_nonzero(r[3] != 1) == 9])
    if len(small) < 8000 or len(large) < 4000:
        raise ValueError("Insufficient label-blind eligible structures")
    selected = {
        "train": small[:6000],
        "small-validation": small[6000:7000],
        "small-query": small[7000:8000],
        "large-validation": large[:1000],
        "large-query": large[1000:4000],
    }
    all_ids = [r[1] for values in selected.values() for r in values]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Molecular identities overlap")
    output.mkdir(parents=True, exist_ok=False)
    public, target, private = output / "public" / TASK_ID, output / "target", output / "private"
    for folder in (public, target, private):
        folder.mkdir(parents=True)
    mappings = {}
    for name, values in selected.items():
        z = np.zeros((len(values), 29), dtype=np.int16)
        coords = np.zeros((len(values), 29, 3), dtype=np.float64)
        ids = np.array([int(r[0][:15], 16) for r in values], dtype=np.int64)
        for i, row in enumerate(values):
            z[i, : len(row[3])], coords[i, : len(row[3])] = row[3], row[4]
        payload = {"molecule_id": ids, "atomic_numbers": z, "coords": coords}
        labels = np.array([r[5] for r in values])
        if name.endswith("query"):
            np.savez_compressed(target / f"{name}.npz", **payload)
            np.savez_compressed(
                private / f"{name.split('-')[0]}-labels.npz", molecule_id=ids, gap_ev=labels
            )
        else:
            np.savez_compressed(public / f"{name}.npz", **payload, gap_ev=labels)
        mappings[name] = [
            {"source_id": r[1], "molecule_id": int(identifier), "relaxed_inchi": r[2]}
            for r, identifier in zip(values, ids, strict=True)
        ]
    retain_json(private / "SOURCE_IDENTITIES.json", mappings)
    for name in ("train.npz", "small-validation.npz", "large-validation.npz"):
        shutil.copy2(public / name, target / name)
    retain_json(
        target / "QUERY.json",
        {
            "task_id": TASK_ID,
            "contexts": [
                {"context_id": "small", "query_file": "small-query.npz"},
                {"context_id": "large", "query_file": "large-query.npz"},
            ],
        },
    )
    (public / "TASK.md").write_text(BRIEF)
    shutil.copy2(Path(__file__).with_name("qm9_task_reference.py"), public / "reference.py")
    (public / "ATTRIBUTION.md").write_text(
        "QM9 computed DFT geometries/gaps, Ramakrishnan et al., Scientific Data 2014. Official Figshare items 1057646/1057644/1057641 declare CC0. https://doi.org/10.6084/m9.figshare.c.978904.v5 . New authored split, not official QM9 evaluation. No guarantee of absence from model pretraining.\n"
    )
    protocol = {
        "schema_version": "scitastebench.qm9-protocol.v1",
        "task_id": TASK_ID,
        "frozen_at": datetime.now(UTC).isoformat(),
        "primary_endpoint": "large-confirmation-mae-ev",
        "split_seed": SEED,
        "sizes": SIZES,
        "fit": "train only; validation selects procedures only",
        "identity_grouping": "source relaxed canonical InChI, first original archive member retained",
        "hartree_ev": HARTREE_EV,
        "claim_rubric": CLAIMS,
        "training_based_subject": True,
        "controller_training": False,
        "confirmation": "one joint packet after source freeze",
        "source_family": "qm9-gdb9-equilibrium",
        "previous_development_family": False,
        "scientific_quality_admitted": False,
        "formal_evidence_eligible": False,
    }
    retain_json(public / "PROTOCOL.json", protocol)
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "claims": CLAIMS,
            "review": "Use public evidence and frozen confirmation only; distinguish numerical support, control confounds, novelty and significance. No hidden labels in feedback.",
            "ai_review_is_not_human_gold": True,
        },
    )
    retain_json(
        public / "SUBMISSION.example.json",
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "entrypoint": "predict.py",
            "files": ["predict.py"],
            "methods": ["primary", "control"],
            "selection_rule": "REPLACE with actual prospective rule",
            "fit_policy": "REPLACE with actual policy",
            "scope": "REPLACE with actual scope",
            "hypotheses": [
                {
                    "statement": "REPLACE hypothesis one",
                    "discriminating_prediction": "REPLACE observable prediction",
                },
                {
                    "statement": "REPLACE alternative",
                    "discriminating_prediction": "REPLACE alternative prediction",
                },
            ],
        },
    )
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    retain_json(
        output / "PACK.json",
        {
            "schema_version": "scitastebench.qm9-pack.v1",
            "task_id": TASK_ID,
            "files": files,
            "discovery_files": [f"public/{TASK_ID}/{p.name}" for p in public.iterdir()],
            "transfer_files": [
                f"target/{p.name}" for p in target.iterdir() if not (public / p.name).exists()
            ],
            "confirmation_contexts": ["small", "large"],
            "source_commit": None,
            "source_family": "qm9-gdb9-equilibrium",
            "acquisition_sha256": digest(source / "ACQUISITION.json"),
            "raw_archive_sha256": digest(source / "dsgdb9nsd.xyz.tar.bz2"),
            "eligible_unique_molecules": len(rows),
            "excluded_source_ids": len(excluded),
            "sizes": SIZES,
            "outcome_independent_selection": True,
            "formal_evidence_eligible": False,
            "prediction_results_used_for_task_selection": False,
        },
    )
    print(
        json.dumps({"pack": str(output), "sizes": SIZES, "source_family": "qm9-gdb9-equilibrium"}),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)
