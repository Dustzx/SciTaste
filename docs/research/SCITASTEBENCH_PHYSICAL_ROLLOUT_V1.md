# Physical rollout from short-horizon evidence

Canonical deliverable: `task-freeze`, followed by the same actual-system
`primary-experiments` comparison. This is one scientific simulation family,
not a separate task for each trajectory, grid cell or prediction horizon.

## Open question and alternative explanations

When does short-horizon fitted dynamics remain useful for a whole physical
trajectory? The researcher must distinguish a constraint's physical content
from integration instability, coarse-grid closure, ordinary regularization,
and loss of useful structure through smoothing. Mean conservation alone cannot
certify dynamics; numerical stability alone cannot certify accurate physics.
A known solver outperforming a weak learner is feasibility, not novelty.
The task permits a justified negative finding or an empirically demonstrated
failure boundary; a regressor swap and the observation that errors accumulate
are not scientific contributions by themselves.

## Source and reconstruction

[PDEBench, NeurIPS 2022 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2022/hash/0a9747136d411fb83f0cf81820d44afb-Abstract-Datasets_and_Benchmarks.html)
provides numerical simulations, not experimental physical measurements.
Its methods/experiments and Burgers supplement were read before constructing
this candidate. The official data DOI is
[10.18419/darus-2986](https://darus.uni-stuttgart.de/dataset.xhtml?persistentId=doi%3A10.18419%2Fdarus-2986),
current metadata version 8.0, CC BY 4.0. Attribution follows the data source,
not the software repository's license.

The actual acquired file is `1D_Burgers_Sols_Nu0.01.hdf5`, 8,232,968,312 bytes,
official file identifier 281363 and MD5 `e6d9a4f62baf9a29121a816b919e2770`.
The pinned mirror revision is `97bf5bb5315b9a083b4f9fc03e5c84d35286d52c`,
with SHA-256 `646f59072348fff722ffe65b47eda755fe1fe106f1dd4a76887cdb89b885ce7b`.
Both checksums were computed on the full acquired file. The equation is
`u_t + (u^2/2)_x = (0.01/pi) u_xx`, periodic on `(0,1)`, not diffusion 0.01.

The file contains 10,000 × 201 × 1024 float32 states but 202 time coordinates.
The unused final coordinate is 2.01; state-aligned coordinates span 0 through 2.
The first build rejected this mismatch before split/future-state materialization;
it remains a failed v1. A distinct v2 explicitly retains that source peculiarity
and uses the first 201 aligned coordinates, without shifting or guessing labels.
Four-cell block means give 256 cells; every fourth frame gives dt=0.04.
Coarse-grid dynamics differ from the generating high-resolution discretization.

## Information and independence

Exact initial-field hashes group all source trajectories before any future state
is read. Group-hash selection assigns 600 fit prefixes through t=1, 100 public
discovery trajectories, 100 public validation trajectories, and 200 private
confirmation trajectories. Public trajectories include t=2. Therefore evaluation
tests new initial identities, not an unseen horizon, viscosity, equation or law.
Unknown cyclic/near duplicates and controller source exposure are retained limits.

Predictive and representation parameters fit training prefixes only. Public
discovery/validation can analyze causes and choose configurations, not supply
additional fitted future targets. Confirmation inputs provide initial fields and
requested times only. Training-based local dynamics and training-free numerical
solvers are experimental subjects; the SciTaste controller is not trained here.

## Outcomes and frozen execution

Each system freezes one public-selected `primary_method` before READY. Primary
outcome is late-window mean per-trajectory normalized RMSE. Early error, absolute
and tail error, mean conservation, Fourier-band error, energy changes, explicit
failures, fitting cost and actual inference time are reported separately.
A failed trajectory leaves the complete primary endpoint missing; no survivor
average or zero-imputed success. The normalization floor is explicit, and near-zero
signals remain an interpretation limit.

The evaluator freezes source before releasing redacted query fields, executes it
unchanged offline once, and scores all named methods on both horizons jointly.
Public fit/calibration assets are mounted so that replay is self-contained;
private future states and workspace caches are not. No post-READY repair or
best-private-procedure substitution is allowed. The versioned PDE confirmation
runner leaves already frozen, active geometry confirmation code unchanged.

## Accepted-work alignment and limits

[MLR-Bench, NeurIPS 2025 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html)
motivates a real research-to-paper comparison, not merely prediction accuracy.
PDEBench supplies subject data and diagnostic constructs, not an AutoResearch
baseline. This coarse subset is not its official full leaderboard. Modern neural
operator comparisons, broader equations/viscosities, calibrated novelty judgments,
and independent full-system evidence would be needed for stronger claims.
No task admission, formal release or top-venue readiness follows from successful
acquisition, a reference prediction, or an AI review alone.

Project-relative evidence, under `outputs/projects/scitaste-self-development/`:

- `evaluations/acquisitions/PDEBENCH_METADATA_20261008.json`
- `evaluations/acquisitions/pdebench-burgers-official-20261008-v1/`
- `evaluations/scitastebench-burgers-rollout-pack-20261008-v1/BUILD_FAILURE.json`
- `evaluations/scitastebench-burgers-rollout-pack-20261008-v2/PACK.json`
- `evaluations/scitastebench-burgers-rollout-pack-20261008-v2/TASK_REVIEW_REQUEST.json`
- `evaluations/scitastebench-burgers-rollout-reference-20261008-v2/PUBLIC_REFERENCE.json`
- `evaluations/scitastebench-burgers-rollout-reference-20261008-v2/SCORING_RECEIPT.json`

Current progress and next decisions belong to the existing project experiments
`CURRENT.md` / `PLAN.md`; numerical results remain in bound run artifacts.
