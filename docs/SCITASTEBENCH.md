# SciTasteBench

SciTasteBench is an evaluation subsystem, not the SciTaste control framework. It
depends only on the fixed-candidate backend contract and can fail independently
without blocking research-state execution.

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

For a real model, select `--backend openai-compatible`, pass a provider config,
and use `--record` to preserve exact request/response pairs. Tests and default
commands never contact a provider. Generated reports remain ignored; only
aggregate acceptance manifests and hashes are committed.
