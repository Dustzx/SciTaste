# Cross-series forecasting research: source and protocol

This is one authored scientific-research task, not the complete M4 competition,
thousands of independent research tasks, or a certified benchmark release.
Current admission, system execution and numerical evidence live in the project
experiment CURRENT/PLAN and the linked immutable run artifacts.

## Source and research question

The Monash Time Series Forecasting Archive, accepted in the NeurIPS 2021 Datasets
and Benchmarks track, links the original M4 monthly archive through
[Zenodo version 3](https://zenodo.org/records/4656480). The CC BY 4.0 ZIP is
28,235,874 bytes, with metadata MD5 `1e304a80fbd6fa93a3ce8360bd3eafa2`
and observed SHA256
`473aa4fc814b625174be2b5615959f35f85f566fbed09c30acf44c350b2a1efe`.
It contains 48,000 competition series, nominal monthly frequency and 18-step
forecast horizons. This is real observational time-series data, not a synthetic
replacement or evidence that original pretraining exposure is absent.

The open-ended research question distinguishes input scale, cross-series pooling,
model capacity, seasonality and the usable recent history. A controller must form
alternative explanations, execute discriminating controls, select one procedure
using public evidence, reproduce all declared methods on new series, and write
an evidence-supported paper. Standard normalization or beating seasonal naive
alone is not an important new discovery.

## Identity and exposure

The first adaptation requires at least 72 observed history steps and caps them at
360. The last 18 original observations are reserved as futures. Exact float64
permitted-history identities are grouped and split by a fixed hash before future
numeric values are used. Raw future text is present in the source parser; this is
numeric outcome-blind assignment, not byte-blind source access or proof against
near duplicates/shared underlying drivers.

- 4,000 training histories: their reserved original futures are never fit labels.
- 500 discovery and 500 public validation histories/futures: public selection,
  not additional global-parameter fitting data.
- 1,000 confirmation histories: future labels stay in the trusted evaluator.

All arrays use opaque integer IDs and left-padded histories with authoritative
history lengths. No absolute calendar or sector labels are released. This measures
new-series identity generalization in a capped-history monthly subset, not unseen
temporal laws, certified structural breaks or cross-sector transfer.

## Fitting, frozen delivery and endpoints

Global parameters may be fit only from rolling windows inside training histories.
A declared fixed local estimator may use each query's observed history, but cannot
update global parameters across queries. Fitting refers to the experimental
subject; the autonomous research controller is not trained.

Before READY, declare every procedure and one public-selected `primary_method`.
The self-contained frozen program must emit every series for every method, with
finite 18-step forecasts, explicit validity and measured inference cost. All
procedures are executed unchanged offline and scored once jointly; no private
winner selection or post-READY repair is permitted.

Primary mean MASE divides each series' absolute error by its observed mean lag-12
absolute difference, with a declared 1e-8 floor. Median/tail MASE, separate legacy
sMAPE, validity and cost are diagnostics. Any declared failure leaves the complete
primary endpoint missing; no survivor average or silent output repair. Original-unit
absolute errors remain per series, not a cross-unit aggregate. This is not original
M4 OWA or a full leaderboard ranking. An input-only recent-change partition is a
fixed diagnostic, not a verified structural break or a new research task.

## Comparator and quality limits

The accepted archive's methods/experiments use multiple statistical and global
learned comparators and discuss scale-aware evaluation. Our ordinary naive,
seasonal, drift and pooled linear controls establish only executability. Independent
review rejected v1's scientific comparator: the standard-deviation floor can amplify
near-flat windows and confound a normalization claim. The original finite catastrophic
output and rejection remain unchanged; no clipping creates a success.

Before any framework assignment, v2 adds raw and level-normalized pooled ridge
controls with equal total rolling-window weight per training series. The latter
uses window RMS with a floor of 1% of the median positive training-window RMS;
all-zero training windows have an explicit fallback. No future outcome selects
this handling. Column-scaled ridge, loss weighting and target units also differ
from the legacy comparator, so this is not a pure one-factor normalization effect.
Common-unit rescaling is supported, not arbitrary independent per-series scaling.
Synthetic constant/near-flat/rescaling checks bound numerical behavior, not accuracy.

The independently reviewed v2 is admitted for one prospective genuine-framework
episode. The seven ordinary public controls are feasibility evidence only; the
legacy pathological procedure remains a diagnostic rather than the sole credible
comparator. No modern strong forecasting baseline or general-quality certification
follows from this admission. Both versions preserve identical task identities.

MLR-Bench's accepted research-to-paper evaluation is the nearest episode-level
comparison: predictive accuracy cannot certify novelty, soundness or paper
quality. Source acceptance does not certify this adaptation. Publication-level
claims additionally need strong objective-matched controls, useful tested insights,
faithful full-task framework comparisons and appropriately calibrated judgment.

Evidence entrypoints under `outputs/projects/scitaste-self-development/evaluations/`:

- `acquisitions/m4-monthly-official-20261008-v1/ACQUISITION.json`
- `scitastebench-m4-monthly-pack-20261008-v1/PACK.json`
- `scitastebench-m4-monthly-pack-20261008-v1/TASK_REVIEW_REQUEST.json`
- `scitastebench-m4-monthly-reference-20261008-v1/PUBLIC_REFERENCE.json`
- `scitastebench-m4-monthly-reference-20261008-v1/SCORING_RECEIPT.json`
- `scitastebench-m4-monthly-pack-20261008-v1/TASK_REVIEW.json`
- `scitastebench-m4-monthly-pack-20261008-v2/PACK.json`
- `scitastebench-m4-monthly-pack-20261008-v2/CONTROL_POLICY_CHECK.json`
- `scitastebench-m4-monthly-pack-20261008-v2/TASK_REVIEW.json`
- `scitastebench-m4-monthly-reference-20261008-v2/PUBLIC_REFERENCE.json`
