# Compositional perturbation research: source and task contract

This is one authored, condition-held-out research task, not a new biological
ground-truth benchmark or a reproduction of an AutoResearch paper's scores.
Current execution and numerical outcomes belong to the project's canonical
experiment documents and immutable run receipts, not this source record.

## Scientific distinction

Given measured constituent single perturbations and fitting double conditions,
when does an expression predictor improve beyond additive composition and global
amplitude calibration? Competing explanations include amplitude bias, shared
residual structure, condition specificity and measurement variation. Better RMSE
alone cannot establish biological interaction or a new mechanism. Training-free
addition and parameter-fitting predictors are experimental subjects; SciTaste's
research controller is not trained for this task.

The primary endpoint is complete mean condition RMSE over 1,000 fixed readouts.
Control-centered Pearson delta, additive-relative MSE and residual correlation
remain separate. Undefined correlations remain null with their denominators.
Cells, genes, and pairs are within-task units, not independent research tasks.

## Primary sources and meaningful differences

- [Nature Methods 2025](https://doi.org/10.1038/s41592-025-02772-6),
  *Deep-learning-based gene perturbation effect prediction does not yet outperform
  simple linear baselines*: full Methods retained and read. Its measured double
  perturbations, strong additive control and amplitude-insensitive Pearson metric
  motivate this construct. It uses filtered 100/124 single/double conditions,
  62 fitting doubles and five splits, unlike this authored adaptation.
- [Author source archive](https://doi.org/10.6084/m9.figshare.24049200.v3): the actual
  614,079,631-byte file 44477939 has official MD5
  `f9c76065fafa43303dae3f80fe4587a8`, verified after a separately retained partial
  download. Extracted source contains 84,986 cells, 19,264 genes, 101 singles,
  125 doubles and control. This is not the paper's processed 100/124 population.
- [Nature Biotechnology 2026](https://doi.org/10.1038/s41587-026-03307-w),
  *Deep learning perturbation models can outperform baselines on calibrated
  metrics*: publication metadata obtained; full Methods/scorer unavailable in
  this acquisition. Neither a calibrated-scoring reproduction nor its exact
  interpretation is claimed.

The 2025 domain paper is a published prediction study, not an autonomous research
framework comparator. The nearest accepted system-evaluation constructs remain
AI-Researcher (NeurIPS 2025 main) and MLR-Bench (NeurIPS 2025 Datasets and
Benchmarks): genuine research-to-paper workflows and task-level evaluation.
This task adds scientific measurement/composition to that construct, not their
breadth, calibrated judgment or quality parity. Code execution and an extra
family count cannot establish publication-level novelty.

## Frozen data and information boundary

Canonical unordered condition groups are allocated by an input-name hash before
expression reading. Fitting contains control, all 101 singles and 49 doubles;
discovery and validation each contain 24 doubles; confirmation contains 28.
Every cell of one condition stays in one partition. Constituent genes, readout
genes, assay and K562 cell type are shared deliberately; none is unseen-domain
transfer. Cross-condition dependence and pretrained exposure remain unknown.

Targets are arithmetic condition means of the source's stored log1p expression,
not log1p raw-count pseudobulk. The 1,000 readouts are chosen by fitting-control
mean only. Source-wide differential-expression annotations and pretrained
embeddings are unused. Fitting/calibration parameters use fitting data alone;
public labelled splits may select complete configurations, never fit them.
Split-half variation uses alternating source rows within a condition and is not
an independent biological replicate or certified noise ceiling.

The source record reports GPL 3.0+ for its archive; article CC BY and reported
code MIT licenses are different. Local reconstruction does not approve raw or
derived redistribution, certify all upstream rights or authorize deployment.
Release code and source links only unless rights are separately resolved.

## Actual framework comparison and failure policy

The frozen cohort assigns genuine SciTaste Native, pinned AutoResearchClaw and
pinned MLR-Agent, with a separate prospectively matched Native OFF assignment.
The implementations own hypotheses, tools, experiments and writing. Session
suppliers only answer their actual model requests. Backbone identity, token
usage and session cost remain unknown; session results are not a formal API
ranking. Four hours/eighty replies are a disclosed whole-task ceiling, not an
accepted-paper convention or a required waiting period.

Submitted code declares all methods and one public-selected primary before one
READY boundary. Method identifiers use ASCII letters/digits/underscores. The
trusted runner snapshots source before redacted query release, executes it once
offline and records execution separately from scoring. All declared conditions
and controls remain; malformed, missing, invalid or undeclared root NPZ output
cannot yield a survivor primary score. Recovery never replaces an original
failed assignment or selects a private winner. Independent review and actual
author revision remain separate from predictive endpoints and scientific approval.

Canonical assets: `evaluations/scitastebench-perturbation-pack-20261008-v1/`.
Original conditional `TASK_REVIEW.json` and its bounded follow-up
`TASK_ADMISSION.json` are distinct source-bound records. Admission permits one
bounded comparison, with `formal=false`; it does not certify a benchmark release,
biological mechanism, strong modern-model comparison or top-venue quality.
