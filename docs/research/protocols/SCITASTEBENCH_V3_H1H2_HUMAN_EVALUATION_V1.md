# SciTasteBench v3 H1/H2 human evaluation protocol v1

Status: **scientific design frozen; recruitment and execution not authorized**.
The machine-readable contract is
`configs/evaluation/human_review/scitastebench_v3_h1h2_human_protocol_v1.yaml`.
The outcome rubric and reviewer interaction contract are separately frozen in
`scitastebench_v3_outcome_rubric_v1.yaml` and
`scitastebench_v3_reviewer_interface_v1.yaml` in the same directory.

## What humans establish

H1 asks whether an abstracted, reviewed scientific precedent improves a
decision beyond access to the same source as raw RAG. H2 asks whether the
benefit depends on a matched precedent rather than an equally sized,
source-disjoint mismatch. Neither question can use a model judge as its primary
outcome: the central construct is expert scientific judgment, and a judge that
shares training data or style preferences with the tested model can make the
comparison circular.

The protocol therefore separates three roles:

1. **Source-fidelity reviewers** decide whether a proposed Taste abstraction is
   supported by its source, states its boundary conditions, and avoids turning
   an observed action into universal advice. They decide corpus admission only.
2. **Case-reference labelers** verify that both actions in a natural decision
   case are feasible and retain the expert action distribution. This supports
   diagnostic accuracy and calibration, not the primary H1/H2 outcome.
3. **Condition-outcome reviewers** compare condition-anonymized decisions. Their
   pairwise preference is the primary endpoint.

A person cannot review a source group they authored or curated. Reviewers are
pseudonymous in research artifacts, conflict-screened per source group, and
qualified by relevant research experience rather than agreement with SciTaste's
authors.

## Blinding and presentation

For each reviewer, the two outputs appear as `X` and `Y` in independently
randomized order. Model, provider, condition, system, retrieval, and file-path
identities are hidden. Formatting, visible context, and output budget are
matched. The blind key is opened only after all primary judgments for that block
are locked.

Source attribution remains visible when it is necessary for rights compliance
or source-fidelity review; it is absent from condition-outcome review unless it
is part of the matched information available to both arms. Reviewers select
`X`, `tie`, or `Y` and provide a bounded rationale. The rationale is not treated
as a hidden additional vote.

`cannot-assess` is not a fourth ordinal outcome. It records missingness when a
reviewer cannot make a defensible comparison. The assignment remains in the
locked review set and cannot be replaced after outcomes are visible.

## Executable lock and unblinding boundary

`scitaste.evaluation.human_outcomes` implements the study boundary rather than
leaving it as an instruction to an operator. A public study manifest contains
only case/output bindings, reviewer pseudonyms, matched presentation budgets,
and the commitment hash of a private blind key. It cannot reveal a condition,
model, provider, system, retrieval mode, or generation trace.

Each case has H1 and H2 blocks with exactly two distinct assigned reviewers.
Every block must present the same byte-identical output pair to both reviewers,
although its X/Y order may differ. The private key is bound to the public
assignment hash before review. A blind opening is valid only when it binds the
complete locked review set and occurs after its final lock; the key itself must
predate the first locked review. After opening, the inspector verifies one
shared matched-Taste output across H1/H2 and three distinct condition outputs
per case. Individual votes and missingness records are retained; this layer
does not compute or declare an effect.

The boundary is available as `scitaste evaluation human-outcome-audit`. Without
an opening it reports whether the study is safe to unblind; with an opening it
reports whether exact individual outcomes are ready for the preregistered
analysis. It performs no recruitment, model call, GPU work, or experiment.

## Disagreement and adjudication

Admission and outcome evaluation have different semantics. A split decision on
whether a source abstraction may enter the corpus receives one independent
adjudicator. A tied reference-action vote receives an adjudicator only when the
case compiler requires a single reference action. Original votes are retained.

Condition-outcome disagreement is never adjudicated away. Both reviews remain
measurements in the H1/H2 analysis, because forcing consensus after reviewers
see the same pair would understate scientific uncertainty and create a path for
post-outcome intervention.

## Estimation and power

The independent unit is a held-out source group, not a reviewer, candidate
order, model call, or retry. H1 and H2 use the ordinal `X/tie/Y` judgments with
reviewer as a crossed measurement factor and source-group-clustered inference.
The exact model is frozen after the excluded pilot and before formal outcomes
are opened. Both title-critical contrasts must pass; their tests use a Holm
correction and 95% intervals.

No formal case count is fixed here. The excluded pilot estimates review time,
disagreement, source-group variance, reviewer variance, and presentation
leakage. Those observations feed a simulation-based power analysis. Inventory,
available reviewer hours, and a convenient rectangular cell matrix cannot choose
the scientific sample size.

## First source-fidelity pilot

If the sixteen-file AAAR acquisition is approved and its content audit passes,
every admitted pilot source receives exactly one model abstraction and two
independent source-fidelity reviews. A semantic failure is retained and is not
regenerated until it looks acceptable. A recorded provider response is never
retried. This pilot is excluded from the formal test and cannot become a Taste
training set merely because reviewers accept it.

Before any call, a new resource record must bind the actual admitted source
hashes, projection token counts, provider model identity, prompt/schema hashes,
one-call-per-source ceiling, maximum total tokens and currency, and a task-
excluded conformance result. Before any person is contacted, a separate
approval must bind compensation, consent, domain coverage, conflict roster,
interface/rubric hashes, maximum reviewer hours, and stopping rules.

The pilot stops without opening the formal split if critical fidelity errors
remain after a rubric revision, condition identity leaks through presentation,
the reviewer pool lacks domain/conflict coverage, or the powered design exceeds
the approved resource envelope.

## Automated judging

An automated judge may be reported only as a secondary calibrated measure. It
must be validated against a held-out set of locked human judgments, with
agreement, calibration, order sensitivity, and systematic disagreement reported.
It cannot replace missing primary reviews, choose the final sample, resolve a
human disagreement, or supply the paper's title-level effectiveness claim.

## Human-subject and data handling

Reviewers receive informed-consent, compensation, retention, and withdrawal
terms before participating. Compensation is independent of label and agreement.
Public artifacts retain pseudonymous identity hashes and qualification/conflict
evidence, never personal contact details. Whether local institutional review is
required must be resolved before recruitment rather than inferred from the fact
that reviewers are evaluating research outputs.
