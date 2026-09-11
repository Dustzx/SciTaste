# MLR-Bench ten-brief qualification audit v1

Date: 2026-09-12

Status: exact local bytes acquired and inspected; eligible for bounded
stagewise/package prepilots, **not eligible for formal empirical end-to-end or
objective-progress claims**.

## What was acquired

The project owner authorized only the immutable request
`f1333432cb0585105ec4d6274e7d78b2d7d0694141256483467887ea6d27cc69`.
SciTaste downloaded the ten Markdown files selected from official MLR-Bench
commit `f728d571a992d71c8b526eeb4d9ab6bb5c8cc824`. The atomic receipt covers
31,345 bytes and has semantic SHA-256
`96975fdea75cd00c9496bb7625d4045a2a31d005cb4f0a5144f7e0d274e2c3b8`.
The raw files and approval remain ignored project output; their non-content
inventory is preserved in
[`data/mlr_bench_ten_brief_acquisition_inventory_v1.yaml`](data/mlr_bench_ten_brief_acquisition_inventory_v1.yaml).

The acquisition had no ingestion or execution authority. It performed no model
call, experiment, GPU work, Taste/Knowledge insertion, or paper revision.

## Finding from the actual bytes

All ten inputs are broad ICLR 2025 workshop descriptions or calls for work.
They define topic areas such as trustworthy language models, data practice,
deep learning for code, uncertainty, efficient foundation models, spurious
correlations, verification, and weight-space learning. They do not freeze a
task-specific hypothesis, dataset, starter implementation, runtime environment,
objective function, target score, or executable success criterion.

This does not make the files invalid benchmark inputs. It fixes their valid
scientific roles:

| Use | Decision | Reason |
|---|---|---|
| Stagewise idea/problem/proposal evaluation | eligible for a bounded pilot | every system can receive the exact same broad brief and be judged with the MLR-Bench research rubric |
| Brief-only research-package preference | eligible for a bounded prepilot | reviewers may compare the value and coherence of packages, provided generated empirical claims remain unsupported until executed |
| Evidence-valid empirical idea-to-paper comparison | blocked | no frozen assets or task-specific executable signal exists |
| Objective-progress comparison | blocked | no external objective score exists |
| Formal held-out estimate | blocked | source-group overlap and reviewer protocol are not yet verified |

The distinction matters for the SciTaste paper. A fluent package produced from
one of these briefs cannot establish that SciTaste chose better experiments or
produced more valid evidence. Using the files as though they were executable
research tasks would reproduce the exact paper-versus-evidence failure the
system claims to address.

## Claim and comparison consequence

The title-level causal claim should be estimated by randomized, matched-model
comparisons of SciTaste Native Base, Knowledge, Taste, critics, Full SciTaste,
and a mismatched-Taste placebo. It needs both expert-labeled decision cases and
at least one task population with real executable evidence.

External systems remain important for ecological validity, but the accepted
implementations do not currently share one unchanged model envelope. Their
best-native comparison must therefore retain `model_effects_confounded=true`
and cannot be used as the causal Taste estimate. MLR-Bench briefs may serve its
stagewise or package-review slice; EXP-Bench, MLRC-Bench, or another admitted
fixed environment must supply the executable/objective slice.

## Next evidence gate

1. Use a small, explicitly non-formal subset of these briefs to validate rubric
   discrimination, artifact blinding, cost, and reviewer burden.
2. Do not launch the former 100-trajectory v6 matrix from these bytes.
3. Acquire and qualify an executable task population separately, including
   code/data licenses, exact environment, objective signal, leakage audit, and
   failure policy.
4. Freeze a new dual-estimand proposal: matched within-SciTaste causal effect as
   primary; best-native external-system comparison as model-confounded
   secondary evidence.
5. Present its exact models, data, cell count, budget, and reviewers for owner
   approval before any API or GPU experiment.

The machine report is reproduced with `scitaste evaluation
acquired-task-cohort`. Its report SHA-256 is
`5595436d39804f978f6f8678664684b31ef2d437352a8fc17747f86a985d57da`;
the inspector always fixes ingestion, execution, provider calls, and GPU work to
false.
