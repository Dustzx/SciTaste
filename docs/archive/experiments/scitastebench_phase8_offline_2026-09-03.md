# SciTasteBench Phase 8 offline acceptance

- Date: 2026-09-03
- Suite: `scitastebench-independent-smoke` v1.0
- Backend: deterministic `offline-scripted-v1`
- Seed: 7

## Scope

This run validates condition isolation, request fingerprinting, six-family
coverage, metric calculation, paired comparisons, robustness slices, and report
hashing. The selections are synthetic fixtures. The values below are not a real
model profile and must not be cited as an effectiveness result.

## Aggregate result

| Condition | Pairwise accuracy | Expert agreement | Wrong-level rate | Style invariance | Paraphrase consistency |
|---|---:|---:|---:|---:|---:|
| Base | 0.375 | 0.4200 | 0.625 | 1.0 | 0.0 |
| Knowledge RAG | 0.625 | 0.6025 | 0.375 | 0.0 | 0.0 |
| Taste Library | 1.000 | 0.8950 | 0.000 | 1.0 | 1.0 |
| Taste Critics | 0.750 | 0.7200 | 0.250 | 1.0 | 1.0 |
| Full SciTaste | 1.000 | 0.8950 | 0.000 | 1.0 | 1.0 |

Full SciTaste has five paired improvements, zero regressions, and three unchanged
cases relative to Base. This expected fixture behavior proves that paired deltas
and wrong-level diagnostics respond correctly; it does not estimate a causal
augmentation effect.

All three transfer slices contain three cases and are reported separately. The
suite covers Idea, Experiment, Evidence, Writing, Review, and Visual tasks.

## Reproduction

```bash
.venv/bin/scitaste benchmark run \
  --backend scripted --seed 7 \
  --output outputs/scitastebench-phase8-offline
```

Generated output:

- `outputs/scitastebench-phase8-offline/benchmark_report.json`
- `outputs/scitastebench-phase8-offline/benchmark_manifest.json`

## Integrity

| Artifact | SHA-256 |
|---|---|
| Versioned suite file | `1cbba1cdea7913bd480fe3b0bc2bfb6b763a96f2a80dbec088650eccb5aa8b28` |
| Canonical validated suite payload | `bbf4811a70a8625d8012c3e6cb6c7a0c99e9a7ead570f2504906e33377e291bf` |
| Generated report | `5b34f228ac8225871249040d46b29bb3265862671c313e5618b6aa86cfde9a1d` |
| Generated manifest | `71296b619367e8b6dd2045087ce6f05152e94c3cb3f242c51665f6ba6c8515e4` |

The self-iteration dogfooding case is not present in this suite. Ranking
correlation and Phase 9 system-outcome metrics are recorded as unavailable.
