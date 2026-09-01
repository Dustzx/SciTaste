# Roadmap

Status values: `done`, `in progress`, `next`, `planned`, `deferred`.

| Milestone | Status | Exit gate |
|---|---|---|
| Phase 0 — substrate control | done | official AutoResearchClaw release pinned; adapter and baseline dry-run work |
| Phase 1 — state/controller skeleton | done | nonlinear mock loop includes `PROBE` and `PIVOT`; unit/integration tests pass |
| Phase 2 — intrinsic calibration | in progress | reproducible Idea, Experiment, Evidence, Writing, and Review taste profiles |
| Phase 3 — taste library | in progress | knowledge/taste stores are independent; provenance and stage retrieval tested |
| Phase 4 — discovery loop | planned | adaptive Hypothesis–Probe–Reformulate scenarios pass both integration cases |
| Phase 5 — evidence loop | planned | claims update from evidence; gaps and contradictory-evidence pivots work |
| Phase 6 — communication loop | planned | narrative/contracts/review obligations can route back to experiments |
| Phase 7 — figures | planned | figure contract produces editable, reviewed SVG/draw.io output |
| Phase 8 — SciTasteBench | deferred | intrinsic/augmented evaluation is controlled and reproducible |
| Phase 9 — matched-budget study | deferred | baseline/system comparisons use identical tasks and budgets |

## Phase 2/3 progress

- Done: immutable fixed-candidate fixtures for Idea, Experiment, Evidence,
  Writing, and Review decisions.
- Done: provider-neutral backend contract, deterministic scripted backend,
  exact record/replay, retry policy, token usage, and an opt-in compatible API
  backend with no network calls in tests.
- Done: accuracy, Brier score, expected calibration error, confidence, and
  per-task reports.
- Done: separate typed Knowledge/Taste JSONL stores, provenance schema,
  stage/role-aware retrieval, and decision-log precedent IDs.
- Remaining Phase 2 gate: execute and archive at least one pre-registered live
  model profile; API credentials are intentionally user-supplied.
- Remaining Phase 3 corpus work: ingest and license-check selected OpenReview,
  ARIES, CASIMIR, and accepted-paper records. The current seed corpus comes only
  from the project specification and exists to test the pipeline.

## Project controls

- One milestone owner and one acceptance issue per phase.
- Weekly triage: blockers, risks, decisions, and evidence of exit criteria.
- Every architecture change receives an ADR in `docs/ARCHITECTURE.md` or a
  dedicated `docs/adr/` record once ADR count grows.
- Generated research artifacts stay outside Git; manifests and hashes may be
  committed when needed for reproducibility.
- The submodule update cadence is milestone-bound, not automatic.

## Known integration issue

A real AutoResearchClaw run requires a user-managed backend configuration and may
incur network/API/compute cost. CI and the default demo therefore exercise the
adapter in dry-run mode and use `MockExecutor` for behavioral acceptance.

Live taste calibration is also opt-in. Until credentials are provided, scripted
and replay backends support all implementation, regression, and integration work;
they must not be described as a real-model taste profile.
