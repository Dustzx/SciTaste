# SciTasteBench

SciTasteBench is an evaluation subsystem, not the SciTaste control framework. It
depends only on the fixed-candidate backend contract and can fail independently
without blocking research-state execution.

## Publication role and current status

SciTasteBench is the paper's internal measurement instrument for Scientific
Taste. It tests whether grounded decision experience improves scientific choices;
external suites such as MLRC-Bench separately test whether those choices produce
objective research progress. Neither role can substitute for the other.

The original natural construction pool contains 273 candidate review-to-revision
episodes from 81 source groups: 196 ARIES candidates from 42 groups and 77 F1000
candidates from 39 groups. Together they expose three observed domain or
publisher-subject strata, but those strata are not yet independently confirmed.
An independently acquired validation reserve now adds 84 candidate trajectories
from 47 source-group-disjoint works: seven natural ARIES dev review/reply cases
and 77 F1000 cases from forty previously unseen works. ARIES reply-to-edit
association is heuristic and explicitly not a human label. The combined local
construction inventory is therefore 357 candidates across 128 source groups,
but the original calibration sample and the new reserve remain separately
identified rather than being pooled after inspection.
The candidates are not benchmark items or gold outcomes. A source enters a
formal population only after the applicable domain, quality, privacy,
decision-family, grounded-abstraction, attribution, and decision-episode
integrity gates accept it. Missing human staffing is not one of those gates.
The active deadline route uses operationally final, identity-distinct AI
reviewers and records
`reviewer_kind=ai`, `not_human_review=true`; it does not claim human or expert
validity. A valid rejection closes its review node while keeping the source out;
malformed or incomplete evidence remains fail-closed.

Version 3 already specifies the title-critical H1/H2 conditions: same-source raw
evidence, same-source abstracted Taste, and source-disjoint mismatched Taste under
token and source-identity controls. AI-panel judgments are mechanism/proxy
measurements; held-out objective scorers own title authority. The lifecycle
evidence program extends this instrument with H2b
autonomous precedent selection and H3 reviewed delayed-credit learning. Their
software and evidence contracts do not authorize a paper claim until real
source-group-disjoint cases, treatments, splits, model identity, power, exact AI
panel identities, and objective claim-admission contracts are frozen.

Version 1 remains a synthetic engineering acceptance suite. It is useful for
testing metrics and condition isolation but is not publication-effectiveness
evidence. The historical Version 2 compiler retains a separate human-labelled
curation boundary: natural
cases contain no answer, source groups are disjoint from the evaluated Taste
precedents, rubric and precedent corpora are content-addressed, and at least two
independent human labels are compiled into the hidden expert distribution.
Model-generated labels are structurally inadmissible to that historical human
estimand. The active v2 AI-finality route is a distinct nonhuman estimand and
must not relabel its output as human evidence.

## Version 1 protocol

The initial suite contains eight independent synthetic decisions across all six
task families: Idea, Experiment, Evidence, Writing, Review, and Visual. Every
case presents exactly two fixed actions and keeps the expert preference outside
the backend request.

Each case is evaluated under five isolated conditions:

| Condition | Additional information visible to the backend |
|---|---|
| `base` | decision context only |
| `knowledge_rag` | retrieved factual context only |
| `taste_library` | retrieved decision principle only |
| `taste_critics` | independent critic feedback only |
| `full_scitaste` | knowledge, taste, critics, and controller state |

Formal v2 adds `taste_placebo`, which supplies mismatched source-disjoint Taste
precedents. It also runs declared and reversed candidate order as separate
content-bound arms. The order arms are repeated measurements of the same case,
not additional sample size.

The condition name and augmentation content are part of the request fingerprint.
Exact recordings therefore cannot be replayed under a different condition.

## Metrics

The report provides pairwise preference accuracy, expert agreement, mean
confidence, Brier score, expected calibration error, and wrong-level decision
rate. It also reports:

- per-family metrics;
- future-year, cross-venue, and cross-domain slices;
- role-normalized style invariance and paraphrase consistency;
- paired improvements, regressions, and unchanged cases relative to `base`.

Ranking correlation is explicitly unavailable because the v1 backend returns
one selection from a pair rather than a complete ranking. Research-yield and
matched-budget outcome measures belong to Phase 9 and are also marked
unavailable instead of being inferred from preference judgments.

## Headline eligibility

Every case declares whether it may enter headline metrics. Self-referential cases
are rejected if marked headline-eligible. The SciTaste self-iteration case is a
dogfooding record and is not part of this independent suite.

The committed synthetic selections are designed to exercise metric sensitivity,
including errors and condition deltas. Their scores are acceptance results for
the evaluation pipeline, not measurements of a real model or evidence that
SciTaste is effective.

## Running the suite

Offline deterministic acceptance:

```bash
.venv/bin/scitaste benchmark run \
  --backend scripted \
  --suite configs/benchmark/scitastebench_v1.yaml \
  --output outputs/scitastebench-phase8-offline \
  --seed 7
```

Run only selected conditions by repeating `--condition`; `base` is mandatory so
the comparison remains controlled:

```bash
.venv/bin/scitaste benchmark run \
  --backend scripted \
  --condition base \
  --condition full_scitaste \
  --output outputs/scitastebench-base-full
```

For a real model, select `--backend openai-compatible` for a provider or
`--backend local-transformers` for an existing local checkpoint, pass the
matching config, and use `--record` to preserve exact request/response pairs.
Tests and default commands never contact a provider or load a checkpoint.
Generated reports remain ignored; only aggregate acceptance manifests and hashes
are committed.

Inspect and compile a natural v2 curation package with:

```bash
.venv/bin/scitaste benchmark curate \
  --package /path/to/curation.yaml \
  --evidence-root /path/to/frozen-evidence \
  --output /path/to/scitastebench_v2.yaml
```

Compilation fails closed on missing or drifted natural-source/rubric/Taste
corpus bytes, inconsistent rubric versions, fewer than two labels, duplicate
reviewers, unnecessary or unresolved adjudication, source-group leakage, or
the formal 120-case/three-domain/six-family floor. The full scientific and GPU
contract is in
[`SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md`](research/protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md).

## Capability-boundary diagnostics

Every Base/Full report partitions headline cases into paired successes, system
recoveries, system regressions, and shared failures. This is diagnostic evidence:
a shared Base/Full failure is not automatically a model limitation, and a Full
recovery does not establish a hard model ceiling.

To distinguish model-specific candidates from shared suite failures, run the
identical suite and seed with a second model, then compare the two saved reports:

```bash
.venv/bin/scitaste benchmark attribute \
  --primary-report outputs/model-a/benchmark_report.json \
  --comparator-report outputs/model-b/benchmark_report.json \
  --output outputs/model-a-vs-model-b
```

The command rejects different suite hashes or seeds. A Base failure is labelled a
model-limit candidate only when the comparator succeeds on that identical case;
shared failures remain unassigned. The output remains a controlled diagnostic,
not a causal or effectiveness claim.
