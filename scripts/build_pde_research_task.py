"""Construct initial-identity-separated physical rollouts from official PDEBench."""
# ruff: noqa: E501 -- Immutable scientific task and explicit evidence obligations.

import argparse
import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np

from scitaste.benchmark.graph_task_data import digest, retain_json
from scitaste.benchmark.pde_task_data import TASK_ID

SEED = "scitastebench/pdebench-burgers/v1/20261008"
SOURCE_SHA = "646f59072348fff722ffe65b47eda755fe1fe106f1dd4a76887cdb89b885ce7b"
SOURCE_MD5 = "e6d9a4f62baf9a29121a816b919e2770"
SOURCE_FILE = "1D_Burgers_Sols_Nu0.01.hdf5"
COUNTS = {"fit": 600, "discovery": 100, "validation": 100, "confirmation": 200}

BRIEF = """# When does a data-fit evolution rule remain physically useful?

Study how short-horizon fitting, integration stability, conservation and smoothing
interact when predicting an entire physical trajectory. Form your own competing
explanations and discriminating controls. A lower one-step error, conserved mean,
regressor swap, or rediscovering that autoregressive errors accumulate is not a
new scientific contribution. A measured failure boundary or justified negative
finding is allowed. Do not imply that a known numerical solver is your invention.

## Source and information boundaries

PDEBench (NeurIPS 2022 Datasets and Benchmarks) provides high-resolution numerical
solutions of periodic viscous Burgers dynamics, u_t+(u^2/2)_x=(0.01/pi)u_xx on
x in (0,1), t in [0,2]. These are simulation outputs, NOT physical measurements.
Source spatial resolution is 1024; this adaptation averages disjoint blocks of
four cells to 256 cells and takes every fourth stored timepoint (dt=0.04).
Cell averaging preserves a source discretized mean but changes the resolved
dynamics: applying the PDE directly to the averaged state is an approximate
coarse-grid model, not the exact data-generating solver. Do not hide this closure.

An initial-field identity hash groups exact duplicates before any future state
is read. Fit, discovery, validation and confirmation use distinct groups. The
fit pool has 600 complete prefixes through t=1. Public discovery and validation
each have 100 full trajectories through t=2. Confirmation has 200 different
initial fields; future states are private. Public late-horizon validation is
visible during selection, so confirmation is new-identity rather than an unseen
time distribution. Cyclic translations/near-duplicates and controller pretraining
exposure are not certified absent. Initial groups, not spatial cells or timesteps,
are within-task units; this is one research family.

train.npz: trajectory_id[N], initial[N,256], state[N,26,256], time[26], x[256].
discovery.npz and validation.npz use state[N,51,256] and time[51]. Inputs and
outputs are source cell averages in original units. Opaque IDs are joins only.
Fit predictive/representation coefficients on train prefixes only. Public
discovery/validation can analyze explanations and select fixed configurations,
but cannot refit learned coefficients or add late target states to training.
Per-query inference may use its initial field and the declared equation; never
fit from its withheld future. No source archive, other viscosity files, outside
solution tables, pretrained benchmark weights, or private identities are allowed.

reference.py provides ordinary persistence, known-equation finite-volume evolution,
and an inexpensive learned local evolution rule with mean-projection/damping
controls. These establish solvability, not research-agent scores or contemporary
FNO/transformer competitiveness. Parameter fitting is a training-based experimental
subject; numerical inference is training-free. This does not train the controller.
Strong subject comparators may be developed within the declared CPU allocation.

## Outcomes and scientific explanation

Freeze one primary_method selected from public evidence before READY. Primary
endpoint is mean per-trajectory normalized RMSE on the late horizon t>1; early
horizon and tail/absolute error are separate. Per-trajectory normalization is
sqrt(mean(error^2))/max(sqrt(mean(truth^2)),1e-8), over the stated time/space
window. A near-zero target makes relative error ill-conditioned; retain absolute
error and the floor. This authored metric is not the official full PDEBench score.

Measure conservation drift, mean-field error, resolved Fourier-band error,
energy growth, explicit failures and actual runtime separately. Conserving a
spatial mean can leave shocks, phase and amplitudes wrong. Damping may make a
rollout stable by erasing informative structure. Distinguish a physical constraint
from ordinary capacity, regularization, sampling exposure or numerical integration
effects using real matched controls. No combined physical-quality scalar.

Report trajectory-group variation and inspect full-horizon curves and informative
failures, not only a favorable final frame. Multiple times are not independent
experiments. The same source and one viscosity do not establish new physics,
viscosity extrapolation, general PDE solution or a domain-general scientific law.

## Frozen execution and delivery

Predict.py accepts --data DIRECTORY --output DIRECTORY. QUERY.json maps early
and late contexts to input NPZs containing trajectory_id, initial, time and x.
Produce exactly CONTEXT--METHOD.npz for every declared method/context with
trajectory_id[N], state[N,len(time),256], valid[N] boolean and seconds[N] finite
nonnegative measured-but-self-reported. Failed trajectories have valid=false and
finite placeholders; do not drop IDs or replace unstable outputs silently. If
any trajectory fails, the complete endpoint remains missing, with failures
reported. Survivor-only or imputed-zero averages are not a full primary outcome.

Include every needed source/helper in SUBMISSION.json, with primary_method,
methods, fit_policy, selection_rule, competing hypotheses/discriminating predictions
and scope. Write READY once only when the source is complete. The common evaluator
snapshots and runs it offline from initial fields and permitted public data, then
scores all predeclared procedures jointly once. Never repair/refreeze after READY,
choose a private winner, or claim success from public scores if confirmation fails.
Inspect actual confirmation_feedback.json before the manuscript. Deliver executed
code, measurements, evidence-linked scientific figures, paper, grounded critique
and justified revision; later claim narrowing cannot invent missing experiments.
"""


def file_checksums(path):
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(8_388_608):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def identity(key):
    return int(hashlib.sha256((SEED + ":id:" + key).encode()).hexdigest()[:15], 16)


def build(source, output, metadata):
    source, output = source.resolve(strict=True), output.resolve()
    started = time.monotonic()
    archive = source / SOURCE_FILE
    sha, md5 = file_checksums(archive)
    if (sha, md5) != (SOURCE_SHA, SOURCE_MD5):
        raise ValueError("Hub bytes and original author checksum disagree")
    meta = json.loads(metadata.read_text())
    version = meta["data"]["latestVersion"]
    record = next(r for r in version["files"] if r["dataFile"]["filename"] == SOURCE_FILE)
    if (
        record["dataFile"]["md5"] != md5
        or record["restricted"]
        or version.get("license", {}).get("name") != "CC BY 4.0"
    ):
        raise ValueError("Unexpected original source/rights binding")
    output.mkdir(parents=True, exist_ok=False)
    public, target, private = output / "public" / TASK_ID, output / "target", output / "private"
    for folder in (public, target, private):
        folder.mkdir(parents=True)
    with h5py.File(archive, "r") as f:
        tensor, x, stored_times = (
            f["tensor"],
            np.array(f["x-coordinate"]),
            np.array(f["t-coordinate"]),
        )
        # Original file has an unused t=2.01 coordinate but only 201 frames.
        # Accept this exact documented source case; never shift/guess frame labels.
        if len(stored_times) == 202 and np.isclose(stored_times[-1], 2.01, atol=2e-6):
            times = stored_times[:201]
        else:
            times = stored_times
        if (
            tensor.shape != (10000, 201, 1024)
            or len(x) != 1024
            or len(times) != 201
            or not np.allclose(times, np.linspace(0, 2, 201), atol=2e-6)
            or not np.allclose(np.diff(x), 1 / 1024, atol=2e-6)
        ):
            raise ValueError("Source layout/coordinates differ; do not silently adapt labels")
        initial = np.array(tensor[:, 0, :], dtype=np.float32)
        if not np.isfinite(initial).all():
            raise ValueError("Invalid initial states; no quality-based exclusion")
        groups = {}
        for index, row in enumerate(initial):
            key = hashlib.sha256(row.astype("<f4").tobytes()).hexdigest()
            groups.setdefault(key, []).append(index)
        ordered = sorted(
            groups, key=lambda k: hashlib.sha256((SEED + ":" + k).encode()).hexdigest()
        )
        if len(ordered) < sum(COUNTS.values()):
            raise ValueError("Not enough distinct initial groups")
        chosen, cursor = {}, 0
        for phase, count in COUNTS.items():
            chosen[phase] = ordered[cursor : cursor + count]
            cursor += count
        retain_json(
            private / "SPLIT_FREEZE.json",
            {
                "frozen_at": datetime.now(UTC).isoformat(),
                "source_sha256": sha,
                "identity_basis": "SHA256 exact full-resolution initial float32 fields, label blind",
                "groups": {
                    p: [
                        {
                            "initial_sha256": k,
                            "source_indices": groups[k],
                            "trajectory_id": identity(k),
                        }
                        for k in keys
                    ]
                    for p, keys in chosen.items()
                },
                "future_states_read_before_freeze": False,
                "cyclic_or_near_identity_certified": False,
            },
        )
        coarse_x, coarse_time = x.reshape(256, 4).mean(axis=1), times[::4]
        inventories = {}
        for phase, keys in chosen.items():
            indices = sorted(groups[k][0] for k in keys)
            by_index = {groups[k][0]: k for k in keys}
            # Read future states only after the complete label-blind assignment.
            states = np.stack(
                [
                    np.array(tensor[i, ::4, :], dtype=np.float32).reshape(51, 256, 4).mean(axis=2)
                    for i in indices
                ]
            )
            if not np.isfinite(states).all():
                raise ValueError("Invalid source trajectory; no outcome-based replacement")
            ids = np.array([identity(by_index[i]) for i in indices], dtype=np.int64)
            inventories[phase] = {
                "initial_groups": len(ids),
                "timepoints": 26 if phase == "fit" else 51,
                "cells": 256,
            }
            if phase != "confirmation":
                end = 26 if phase == "fit" else 51
                np.savez_compressed(
                    public / ("train.npz" if phase == "fit" else phase + ".npz"),
                    trajectory_id=ids,
                    initial=states[:, 0],
                    state=states[:, :end],
                    time=coarse_time[:end],
                    x=coarse_x,
                )
            else:
                for context, window in {"early": slice(1, 26), "late": slice(26, 51)}.items():
                    np.savez_compressed(
                        target / (context + "-query.npz"),
                        trajectory_id=ids,
                        initial=states[:, 0],
                        time=coarse_time[window],
                        x=coarse_x,
                    )
                    np.savez_compressed(
                        private / (context + "-labels.npz"),
                        trajectory_id=ids,
                        initial=states[:, 0],
                        state=states[:, window],
                        time=coarse_time[window],
                    )
    retain_json(
        target / "QUERY.json",
        {"task_id": TASK_ID, "contexts": {c: c + "-query.npz" for c in ("early", "late")}},
    )
    (public / "TASK.md").write_text(BRIEF)
    (public / "ATTRIBUTION.md").write_text(
        "PDEBench, NeurIPS 2022 Datasets and Benchmarks. Original dataset DOI: https://doi.org/10.18419/darus-2986\nCC BY 4.0; source metadata version 8.0. Author adaptation and coarse-grid task are not the official leaderboard.\nHub mirror pdebench/Burgers revision 97bf5bb5315b9a083b4f9fc03e5c84d35286d52c; original MD5 and mirror SHA256 both verified.\n"
    )
    rubric = [
        {"claim_id": k, "obligation": v}
        for k, v in (
            (
                "prediction",
                "Report all frozen methods on early and late confirmation; failures stay missing",
            ),
            (
                "learning_boundary",
                "Predictive coefficients fit early training prefixes only; selection/public future exposure disclosed",
            ),
            (
                "scientific_explanation",
                "Execute controls distinguishing constraints, stability, smoothing and learner/integration alternatives",
            ),
            (
                "physics",
                "Mean conservation is not complete dynamics; retain resolved-scale and energy diagnostics with coarse-grid scope",
            ),
            (
                "reproduction",
                "Frozen self-contained offline source executed from redacted initial fields",
            ),
            (
                "cost_and_novelty",
                "Measure fit/inference cost and limit conclusions; known PDE solver and error accumulation are not new discovery",
            ),
        )
    ]
    retain_json(
        public / "PROTOCOL.json",
        {
            "task_id": TASK_ID,
            "claim_rubric": rubric,
            "inventories": inventories,
            "primary_endpoint": "late normalized_rmse_mean",
            "confirmation_contexts": ["early", "late"],
            "subject_routes": ["parameter-fitting", "training-free-numerical"],
            "source_equation_diffusion": "0.01/pi",
            "source_type": "numerical simulation",
            "spatial_reduction": "four-cell block mean",
            "temporal_reduction": "every fourth source timepoint",
            "original_time_coordinate_entries": len(stored_times),
            "unused_source_time_coordinate": (
                float(stored_times[-1]) if len(stored_times) == 202 else None
            ),
            "selection_future_distribution_seen": True,
            "distinct_source_groups": len(groups),
        },
    )
    retain_json(
        public / "REVIEW_PROTOCOL.json",
        {
            "claim_obligations": rubric,
            "novelty_not_certified_by_score": True,
            "negative_findings_valid": True,
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
            "primary_method": "REPLACE",
            "selection_rule": "REPLACE public selector",
            "fit_policy": "REPLACE train-prefix rule",
            "scope": "REPLACE scientific scope",
            "hypotheses": [
                {
                    "statement": "REPLACE explanation",
                    "discriminating_prediction": "REPLACE observation",
                },
                {
                    "statement": "REPLACE alternative",
                    "discriminating_prediction": "REPLACE contrary prediction",
                },
            ],
        },
    )
    shutil.copy2(Path(__file__).with_name("pde_task_reference.py"), public / "reference.py")
    files = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
    manifest = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "source_family": "pdebench-periodic-burgers",
        "frozen_at": datetime.now(UTC).isoformat(),
        "source_sha256": sha,
        "source_md5": md5,
        "source_metadata_sha256": digest(metadata),
        "files": files,
        "discovery_files": [n for n in files if n.startswith("public/")],
        "transfer_files": [n for n in files if n.startswith("target/")],
        "confirmation_contexts": ["early", "late"],
        "inventories": inventories,
        "quality_admitted": False,
        "formal_evidence_eligible": False,
        "authoring_development_only": False,
        "research_outputs_observed_before_freeze": False,
        "source_independence_certified": False,
        "build_seconds": time.monotonic() - started,
    }
    retain_json(output / "PACK.json", manifest)
    print(
        json.dumps(
            {
                "pack": str(output),
                "inventories": inventories,
                "build_seconds": manifest["build_seconds"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "output", "metadata"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output, args.metadata)
