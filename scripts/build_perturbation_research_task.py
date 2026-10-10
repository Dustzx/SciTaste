"""Materialize condition-held-out Norman research; never use published predictions.

Source preprocessing predates this split. Source-global DE annotations are never
used, and this is not the original papers' split, model comparison or population.
"""
# ruff: noqa: E501 -- Complete source-bound scientific contract and caveats.

import argparse
import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
from scipy import sparse

from scitaste.benchmark.graph_task_data import digest, retain_json

TASK_ID = "combinatorial-perturbation"
SEED = "scitastebench/norman-condition/v1/20261008"
BRIEF = """# What does improved combinatorial perturbation prediction establish?

Investigate prediction of unseen double-gene CRISPR-activation conditions in
Norman K562 cells when each constituent single perturbation is already observed.
Distinguish additive composition, global amplitude adjustment, transferable
nonadditive residuals and measurement noise. Construct actual informative
controls: a small vector error alone does not identify a genetic interaction.
Known additive/ridge models are controls, not discoveries by renaming them.

The scFoundation-reprocessed GSE133344 assay is the actual source, linked by
Nature Methods 2025 doi:10.1038/s41592-025-02772-6. The archive contains 84,986
cells, 19,264 readout genes, 101 single conditions, 125 double conditions and
control. These are actual archive counts, not that paper's filtered 100/124
population; this adaptation does not rerun its GEARS filtering. Source processing
and potential source/model-pretraining exposure predate our split. Source-global
DE, top-DE, nonzero annotations and pretrained embeddings are never inputs.
The 2026 doi:10.1038/s41587-026-03307-w warns that metric calibration and additive
saturation affect interpretations. This single cancer-cell assay cannot alone
validate broad combinatorial biology, novel mechanisms or biomedical deployment.

Before expression is read, canonical unordered perturbation conditions define
one deterministic partition: all singles/control and 49 doubles fit; 24 other
doubles discovery; 24 validation; 28 confirmation. All cells of a condition stay
together. Genes are shared across conditions by design, not unseen genes; cells,
genes, conditions and split halves are not independent research tasks. No new
assay/batch/cell type is held out. Source-normalized log1p expression is used as
stored. The 1,000 readout genes are ranked ONLY by mean fitting-control expression.
No private-expression-dependent feature selection or interaction threshold.

Each condition is a pseudobulk arithmetic mean of stored log1p cell values, not
log1p of summed raw counts. train.npz has condition_id[N], perturbation[N,2]
(single [gene,-1], ctrl [-1,-1]), expression[N,1000], cell_count[N], control[1000],
single_expression[101,1000], gene_names[101], readout_names[1000]. Discovery and
validation have the same query covariates plus their expression. Query contexts
omit expression; their single-gene means and control are fitting data, not target
measurements. All fitted parameters and representations use train only. Labelled
discovery/validation may choose fixed configurations but may not fit parameters.
Within-training condition crossfit is legal. Do not read original archive/private
labels/pack or fit on confirmation. Do not claim an independent assay replicate.

Primary is mean condition RMSE over the fixed 1,000 genes, separately on all
confirmation conditions. It measures this expression-prediction endpoint, not
interaction discovery. Secondary diagnostics are control-centered Pearson delta,
additive-relative error and correlation of predicted vs observed additive
residuals. Undefined zero-vector correlations are null with denominators retained.
Observed split-half cell variability is a measurement-noise diagnostic, not a
certified biological noise ceiling or independent dataset. Absolute improvement
and calibration/interaction explanations require appropriate actual controls.
reference.py provides no-change, additive and train-only scalar-amplitude controls;
none is a new AutoResearch method or modern foundation-model reproduction.

Retain all procedures, failures, costs, actual source, evidence-linked figures and
report/report.md. Freeze methods, exactly one publicly selected primary_method,
fit/selection rules, competing hypotheses and every source/helper in
submission/SUBMISSION.json; then write submission/READY once. Entrypoint accepts
--data DIRECTORY --output DIRECTORY, retrains from supplied train only, reads
QUERY.json and emits CONTEXT--METHOD.npz for every declared context/method, exactly
condition_id[N] int64, expression[N,1000] finite real, valid[N] booleans,
seconds[N] finite nonnegative inference cost. Keep public diagnostics nested;
do not place other NPZ files in output root. Any failed condition leaves the
complete primary null; never report a survivor average. Trusted confirmation
freezes source before query export and executes once, with no source repair,
private-winner selection or extra seed. Read actual feedback before final claims.
Raw/derived redistribution is not approved by this adaptation; reconstruct from
the attributable source. GPL3+ is the archive record's stated license, not an
assertion that every upstream asset has identical rights.
"""


def identity(name):
    return int(hashlib.sha256((SEED + ":" + name).encode()).hexdigest()[:15], 16)


def build(source, output):
    source = source.resolve(strict=True)
    archive = source / "norman-scfoundation.zip"
    h5ad = source / "source-h5ad/norman-scfoundation.h5ad"
    metadata_path = source / "scfoundation-correct-article-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    asset = next(f for f in metadata["files"] if f["id"] == 44477939)
    if (
        archive.stat().st_size != asset["size"]
        or hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest()
        != asset["computed_md5"]
        or digest(h5ad) != "20a67e0e9e1059b631f3d3fe56a78b5856c1609339ded37cf20f2d49af1b87d7"
    ):
        raise ValueError("Exact attributable source integrity differs")
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    public = output / "public" / TASK_ID
    private, target = output / "private", output / "target"
    for directory in (public, private, target):
        directory.mkdir(parents=True)
    with h5py.File(h5ad, "r") as handle:
        original = handle["obs/condition/categories"].asstr()[:]
        categories = np.array(["+".join(sorted(c.split("+"))) for c in original])
        if len(set(categories)) != len(categories):
            raise ValueError(
                "Canonical duplicate conditions need explicit grouping, not row splitting"
            )
        codes = handle["obs/condition/codes"][:]
        counts = np.bincount(codes, minlength=len(categories))
        singles = sorted(c for c in categories if "ctrl" in c and c != "ctrl")
        doubles = sorted((c for c in categories if "ctrl" not in c), key=identity)
        if len(singles) != 101 or len(doubles) != 125 or counts.min() < 40:
            raise ValueError("Unexpected actual assay population; do not resample silently")
        splits = {
            "fit": ["ctrl", *singles, *doubles[:49]],
            "discovery": doubles[49:73],
            "validation": doubles[73:97],
            "unseen_combinations": doubles[97:],
        }
        frozen_at = datetime.now(UTC).isoformat()
        retain_json(
            private / "SPLIT_FREEZE.json",
            {
                "frozen_at": frozen_at,
                "seed": SEED,
                "condition_assignments": splits,
                "before_expression_read": True,
                "all_cells_of_condition_grouped": True,
                "source_processing_predates_split": True,
                "archive_sha256": digest(archive),
                "h5ad_sha256": digest(h5ad),
                "source_record_license": metadata["license"],
            },
        )
        # Stream actual assay once; no target-dependent gene filtering or DE use.
        x = handle["X"]
        shape = tuple(int(n) for n in x.attrs["shape"])
        if shape != (84986, 19264) or x.attrs["encoding-type"] != "csr_matrix":
            raise ValueError("Require the declared original sparse assay")
        indptr = x["indptr"][:]
        sums = np.zeros((len(categories), shape[1]), dtype=np.float64)
        half_sums = np.zeros((2, len(categories), shape[1]), dtype=np.float64)
        half_counts = np.zeros((2, len(categories)), dtype=np.int64)
        for start in range(0, shape[0], 2048):
            end = min(start + 2048, shape[0])
            lo, hi = int(indptr[start]), int(indptr[end])
            block = sparse.csr_matrix(
                (x["data"][lo:hi], x["indices"][lo:hi], indptr[start : end + 1] - lo),
                shape=(end - start, shape[1]),
            )
            if not np.isfinite(block.data).all():
                raise ValueError("Nonfinite source expression")
            columns = np.arange(end - start)
            grouping = sparse.csr_matrix(
                (np.ones(end - start), (codes[start:end], columns)),
                shape=(len(categories), end - start),
            )
            sums += (grouping @ block).toarray()
            for half in (0, 1):
                mask = np.arange(start, end) % 2 == half
                half_group = sparse.csr_matrix(
                    (mask.astype(float), (codes[start:end], columns)),
                    shape=(len(categories), end - start),
                )
                half_sums[half] += (half_group @ block).toarray()
                half_counts[half] += np.bincount(codes[start:end][mask], minlength=len(categories))
            if end == shape[0] or end % 16384 == 0:
                print(
                    json.dumps(
                        {
                            "assay_cells_aggregated": end,
                            "total": shape[0],
                            "elapsed_seconds": time.monotonic() - started,
                        }
                    ),
                    flush=True,
                )
        means = sums / counts[:, None]
        lookup = {c: i for i, c in enumerate(categories)}
        control_index = lookup["ctrl"]
        selected = np.argsort(-means[control_index], kind="stable")[:1000]
        genes = handle["var/gene_name"].asstr()[:]
        single_names = sorted(c.replace("ctrl", "").strip("+") for c in singles)
        single_lookup = {g: i for i, g in enumerate(single_names)}
        single_values = np.stack(
            [means[lookup["+".join(sorted([g, "ctrl"]))]][selected] for g in single_names]
        )
        control = means[control_index, selected]
        inventory = {}
        for split, conditions in splits.items():
            rows = [lookup[c] for c in conditions]
            perturbation = []
            for c in conditions:
                parts = [single_lookup[g] for g in c.split("+") if g != "ctrl"]
                perturbation.append(parts + [-1] * (2 - len(parts)))
            arrays = {
                "condition_id": np.array([identity(c) for c in conditions], dtype=np.int64),
                "perturbation": np.array(perturbation, dtype=np.int64),
                "cell_count": counts[rows],
                "control": control,
                "single_expression": single_values,
                "gene_names": np.array(single_names),
                "readout_names": genes[selected],
                "expression": means[rows][:, selected],
            }
            inventory[split] = {"conditions": len(rows), "cells": int(counts[rows].sum())}
            if split in {"fit", "discovery", "validation"}:
                np.savez_compressed(
                    public / f"{'train' if split == 'fit' else split}.npz", **arrays
                )
            else:
                halves = half_sums[:, rows][:, :, selected] / half_counts[:, rows, None]
                np.savez_compressed(
                    private / f"{split}-labels.npz",
                    **arrays,
                    split_half_rmse=np.sqrt(np.mean((halves[0] - halves[1]) ** 2, axis=1)),
                )
                np.savez_compressed(
                    target / f"{split}-query.npz",
                    **{k: v for k, v in arrays.items() if k != "expression"},
                )
    claims = [
        {
            "claim_id": "prediction",
            "obligation": "All predeclared procedures/conditions/failures; actual RMSE vs strong additive control, not private selection",
        },
        {
            "claim_id": "learning_boundary",
            "obligation": "Fit only training, control-only readout choice; known constituent genes, no new assay",
        },
        {
            "claim_id": "scientific_explanation",
            "obligation": "Actually distinguish amplitude, additive composition and transferable residuals, or leave mechanism unknown",
        },
        {
            "claim_id": "measurement_scope",
            "obligation": "Cell variation/shared gene/pair/assay dependence; no biological interaction ground truth or deployment certificate",
        },
        {
            "claim_id": "reproduction",
            "obligation": "Complete unchanged source and condition IDs; original source/preprocessing/rights attributed",
        },
        {
            "claim_id": "cost_and_novelty",
            "obligation": "Actual resource accounting; known methods and one cancer assay do not establish SOTA/new discovery",
        },
    ]
    retain_json(
        public / "PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "inventories": inventory,
            "claim_rubric": claims,
            "confirmation_contexts": ["unseen_combinations"],
            "primary_endpoint": "mean_condition_rmse",
            "readout_gene_selection": "fit-control mean only",
            "subject_routes": ["training-free-additive", "parameter-fitting"],
            "formal_evidence_eligible": False,
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claim_rubric": claims,
            "role": "Source-bound independent review; not expert or venue certification",
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
            "primary_method": "REPLACE_WITH_PUBLIC_PRIMARY",
            "fit_policy": "REPLACE_WITH_TRAIN_ONLY_RULE",
            "selection_rule": "REPLACE_WITH_PUBLIC_RULE",
            "scope": "REPLACE_WITH_ACTUAL_LIMITS",
            "hypotheses": [
                {
                    "statement": "REPLACE_WITH_EXPLANATION",
                    "discriminating_prediction": "REPLACE_WITH_CONTROL",
                },
                {
                    "statement": "REPLACE_WITH_ALTERNATIVE",
                    "discriminating_prediction": "REPLACE_WITH_CONTROL",
                },
            ],
        },
    )
    retain_json(
        target / "QUERY.json",
        {
            "task_id": TASK_ID,
            "labels_released": False,
            "contexts": {"unseen_combinations": "unseen_combinations-query.npz"},
        },
    )
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "Original Norman GSE133344 / scFoundation processed archive: https://doi.org/10.6084/m9.figshare.24049200.v3 ; stated GPL3+ archive license, upstream rights not homogenized. Source-linked Nature Methods 2025 and Nature Biotechnology 2026; authored condition split and train-control readout selection, not their model rankings. No raw/derived redistribution approved.\n"
    )
    shutil.copy2(Path(__file__).with_name("perturbation_reference.py"), public / "reference.py")
    manifest = {
        "schema_version": "scitastebench.perturbation-task-pack.v1",
        "task_id": TASK_ID,
        "family": "norman-k562-combinatorial-perturbation",
        "frozen_at": frozen_at,
        "source_metadata_sha256": digest(metadata_path),
        "archive_sha256": digest(archive),
        "h5ad_sha256": digest(h5ad),
        "source_archive_md5_verified": True,
        "files": {
            p.relative_to(output).as_posix(): digest(p)
            for d in (public, private, target)
            for p in d.rglob("*")
            if p.is_file()
        },
        "discovery_files": sorted(p.relative_to(output).as_posix() for p in public.iterdir()),
        "transfer_files": sorted(p.relative_to(output).as_posix() for p in target.iterdir()),
        "confirmation_contexts": ["unseen_combinations"],
        "inventories": inventory,
        "task_families": 1,
        "formal_evidence_eligible": False,
        "quality_admitted": False,
        "research_outcomes_before_freeze": False,
        "source_exposure": "unknown",
        "build_seconds": time.monotonic() - started,
        "redistribution_approved": False,
        "split_half_scope": "deterministic alternating source-row split, not independent biological replicate",
    }
    retain_json(output / "PACK.json", manifest)
    print(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k not in {"files", "discovery_files", "transfer_files"}
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)
