# Molecular gap extrapolation: prospective complete research task

This batch advances `task-freeze` and `taste-freeze`, then
`primary-experiments` in the project's canonical submission plan. It is not a
retained-result reanalysis. The raw source is QM9, distinct from the previously
exposed rMD17 force-prediction family. It contributes **one** research family,
not one task per molecule, property, treatment, seed or stage.

## Scientific question and endpoints

Can a researcher explain and improve electronic-gap prediction as molecular
structures become larger, rather than only improve a random-split validation
score? Researchers choose hypotheses, representations, estimators and controls.
Correct negative findings are valid; invariance itself, changing a kernel, or
fitting a regressor is not a claim of scientific novelty.

The subject is the B3LYP/6-31G(2df,p) HOMO–LUMO gap of relaxed QM9 geometries.
Only atomic numbers and Cartesian geometry are predictor inputs. No other
computed quantum property, Mulliken charge, target-derived feature or original
archive is available to the researcher. Coordinates are in Å; gaps are converted
from Hartree to eV with the fixed factor 27.211386245988.

After excluding the source's uncharacterized molecules, a label-blind SHA256
ordering of source IDs selects 6,000 fitting and 1,000 validation molecules with
at most eight heavy atoms, and 1,000 validation molecules with nine heavy atoms.
Separate confirmation contains 1,000 small and 3,000 nine-heavy-atom molecules.
All identities are disjoint. This measures molecular-size extrapolation within
QM9, **not** new chemical elements, unseen source datasets, measured experimental
chemistry, or the official random-split QM9 leaderboard. The public nine-atom
validation distribution is not an unseen domain; its labels may select a frozen
procedure but may not fit predictor parameters.

Primary endpoint: confirmation MAE (eV) on nine-heavy-atom molecules. Small-
molecule MAE, RMSE and 90th-percentile absolute error are separate diagnostics.
Every assigned system retains missing/failed confirmation. No scalar mixture of
paper quality and predictive accuracy is a primary score. An independent task
review checks authenticity, difficulty, boundaries and coverage before outcomes,
not whether SciTaste is likely to win.

## Common material and comparison

All genuine systems receive the same train, validation, brief, protocol and
executable ordinary controls: atom-count regression and geometry-kernel
regression. The research contribution must be evaluated against actual matched
controls, including a meaningful learned structural predictor when making strong
method claims; cheap reference controls are not SOTA or AutoResearch frameworks.
Using cached author results alone cannot satisfy research execution.

First assignment: SciTaste Native + source-reviewed Taste, pinned
AutoResearchClaw, and pinned MLR-Agent. Native without Taste is a matched
ablation, not an external system. The real upstream code owns stage progression,
tools and paper writing; session agents supply only emitted model requests.
Model identity and token/dollar usage remain unknown where unattested.

Each system gets the established four-hour / 80-response complete-task envelope,
two CPU threads, and the same installed dependencies. This is our prospective
resource-limited setting, not an accepted-paper default or a promise of research
sufficiency. Individual experiments/confirmation can consume at most 30 minutes
within that ceiling. Fitting the **subject** model is permitted; the controller
is not trained. No GPU or supplier API is needed for this batch. GPU tasks remain
assigned to `4090-2`, whose October 7 connection attempts timed out; do not use
the local GPU as a fallback.

Freeze all procedures, controls, hypotheses, fitting/selection rules and source
before confirmation inputs are mounted. Execute unchanged source offline, return
all predeclared procedure scores jointly once, then complete evidence-based
interpretation, paper, review and revision. MLR-Agent has no native post-paper
review loop; any common added review is explicitly augmented, not upstream.

## Data, experience and publication boundaries

Official data: https://doi.org/10.6084/m9.figshare.c.978904.v5 . Retain exact
Figshare item/file metadata, raw byte hashes, original exclusion list and license
declarations. Do not infer a dataset license from the article's prose license.
Data preparation, not a model-prediction result, fixes the split. Downloaded
resources are below the user's automatic 10-GB authorization threshold.

Task-aligned experience is derived from independent source evidence about
physical symmetries and representation/control choices. Task/confirmation
results must not be supplied to source-quality, abstraction or independent Taste
review nodes. A paper whose own experiments include QM9 cannot furnish held-out
QM9-derived experience merely by dropping its result table from an excerpt.
Previous inapplicable cases remain allowed to abstain; do not loosen applicability
to force uptake. New library versions are separate, outcome-independent artifacts.

Nearest accepted AutoResearch comparator is MLR-Bench (NeurIPS 2025 Datasets and
Benchmarks), whose actual methods use open-ended ideation, proposal, real coding
and paper stages and separate end-to-end paper judging from stepwise evaluation:
https://arxiv.org/html/2505.19955v3 . Our addition is a source-frozen executable
confirmation and fixed claim obligations; one family does not match its breadth,
and AI-only task/paper review is not calibrated human scientific validation.
SciTasteBench admission and positive Taste effectiveness are not established by
successful downloads, executable references or completion of this protocol.
