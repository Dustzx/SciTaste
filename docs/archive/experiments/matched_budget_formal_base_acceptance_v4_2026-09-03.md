# Matched-budget formal base acceptance v4

Date: 2026-09-03

## Result

One clean, commit-pinned formal cell completed in a single `study run` launcher
lifecycle. Unlike earlier engineering preacceptance attempts, no manual stage
resume or result reconstruction was used, so runner-owned wall/GPU allocation,
provider usage, outcome audit, and artifact hashes cover the complete cell.

Identity:

- protocol SHA-256:
  `20ee06e9da9400a60d51732a774da4761af273f5ee4bad95d1804004405eaf30`;
- plan SHA-256:
  `9ad62ac659fdf5849ca7003ff767f15fa36a6d37f7a068d8702f115309201d06`;
- cell: `cell-9a5e1d3ce415d11ea385`;
- task/condition/seed: `diagnosis-friendly-v1`, `autoresearchclaw`, 7;
- SciTaste implementation pin:
  `5d0376eea2e7e617cce18a2b476a3aa985f6fb66`;
- AutoResearchClaw pin:
  `12d3fd809fa9658e91a0328c3280a0e462c78386`;
- local ignored output:
  `outputs/formal-base-acceptance-v4-2026-09-03/run/`.

The study record is `succeeded` with evidence class `real`:

- wall time and one-GPU allocation: 0.1704041409 hours (about 10.22 minutes);
- one selected experiment;
- 138,157 exact provider tokens;
- estimated API cost USD 0.373915;
- zero live-search queries;
- 7,516-word paper draft and completed Stage 18 peer review.

The generated experiment initially used invalid `np.default_rng` syntax. The
single registered Stage 13 repair corrected the runtime defect without changing
the frozen task contract. Its selected execution returned zero and reported:

- majority vote balanced accuracy: 0.564858;
- confidence-weighted vote: 0.654686;
- position-aware probe: 0.628291;
- registered arithmetic aggregate: 0.615945.

The mechanical outcome audit records one useful numerical result, three proposed
ideas, one valid idea, two discarded ideas, evidence sufficiency 1.0, thirteen
mechanically supported claim sections, and 34 upstream simulated-review concerns
opened with none closed. These counters establish pipeline completeness; they do
not substitute for independent scientific-quality review.

## Retained evidence

- `paper.md`: SHA-256
  `97d3c9d507c1fc3d34de815c09cfed65db1c9bc465b07e10ac2aa0d2f1ec26fb`;
- `outcome_audit.json`: SHA-256
  `0169f103391d7fbc04a7e81eb6e6bd1ce5448d6df030fcc279635125119b5992`;
- `condition_trace.json`: SHA-256
  `9e3f72667e5a8d6186aad9e2da7b4365eb1f9e966aa8f5b66a0409bec129f8c2`;
- `upstream_artifact_manifest.json`: SHA-256
  `990b93698869aa0abdeaa660cd3fc6f938fa1abdcff64d577decc11391c46d99`.

The upstream manifest contains 97 content-addressed files and records the pinned
unmodified AutoResearchClaw commit.

## Interpretation and remaining gate

This clears the real-execution acceptance gate for one base cell. It does not
establish a SciTaste advantage: Knowledge RAG, Taste Library, and Full SciTaste
have not yet been run under this exact protocol hash, and 47 of 48 cells remain.
The evaluator must therefore return `incomplete`, not `eligible`.

The benchmark is deterministic synthetic CPU work. A GPU is reserved and charged
equally by the matched-budget harness, but this cell does not demonstrate useful
RTX 3090 computation. External validity, the four-condition comparison, all
three repetitions, and two condition-blinded independent reviewers per cell are
still required before any headline result.

## Four-condition extension finding

An attempted continuation to the other three conditions was stopped after the
Knowledge RAG cell exposed another valid metric representation:
`condition: mean=...` lines in stdout with no structured metric object. Offline
audit recovered all three registered values (0.809026, 0.839988, and 0.806441)
and the registered aggregate 0.818485. A budget-continuing manual resume then
completed a 7,432-word paper and peer review at 155,940 cumulative tokens and
estimated API cost USD 0.43116. Its condition trace contains the two registered
knowledge document IDs and no Taste IDs or controller decision, confirming
condition isolation.

Because its analysis stages were manually resumed after the runner marked the
first attempt failed, this Knowledge RAG artifact is adapter preacceptance, not a
comparable formal timing observation. Taste Library and Full SciTaste were not
run. The parser now accepts this representation only when every registered
condition is present and numeric. The repeated `np.default_rng` runtime repair
was traced to a typo in SciTaste's own prompt and corrected to
`numpy.random.default_rng` before the next protocol freeze.
