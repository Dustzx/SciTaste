# Roadmap

Status values: `done`, `in progress`, `next`, `planned`, `deferred`.

| Milestone | Status | Exit gate |
|---|---|---|
| Phase 0 — substrate control | done | official AutoResearchClaw release pinned; adapter and baseline dry-run work |
| Phase 1 — state/controller skeleton | done | nonlinear mock loop includes `PROBE` and `PIVOT`; unit/integration tests pass |
| Phase 2 — intrinsic calibration | done | reproducible Idea, Experiment, Evidence, Writing, and Review taste profiles |
| Phase 3 — taste library | done | knowledge/taste stores are independent; rights-scoped provenance, quarantine, and stage retrieval tested |
| Phase 4 — discovery loop | done | adaptive Hypothesis–Probe–Reformulate scenarios pass both integration cases |
| Phase 5 — evidence loop | done | claims update from evidence; gaps and contradictory-evidence pivots work |
| Phase 6 — communication loop | done | narrative/contracts/review obligations route to evidence and back to revision |
| Phase 7 — figures | next | figure contract produces editable, reviewed SVG/draw.io output |
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
- Done: a five-case `qwen3.7-plus` live smoke profile is archived as an aggregate
  manifest with hashes; secrets, exact recordings, and raw responses remain local.
- Done: local JSON/JSONL ingestion, explicit Knowledge/Taste routing, content
  hashing, per-library deduplication, idempotency, and reject-by-default license
  policy. No external source content is committed or downloaded automatically.
- Done: rights-scope auditing distinguishes metadata, public comments, derived
  annotations, and article text; article text needs per-record permission.
- Done: deterministic ARIES/CASIMIR projections and a real-source acceptance run
  imported 29 metadata/annotation Knowledge Documents and quarantined 25 observed
  revision cases. Direct OpenReview collection remains user-managed because its
  API challenged the unattended request.
- Ongoing data operation: expand the local corpus and human-verify selected cases.
  This changes library population, not the Phase 3 code or acceptance gate.

## Phase 4 completion

- Structured, source-linked literature landscape construction.
- Separate Research Intuition and falsifiable Working Hypothesis formation.
- Cheap diagnostic probe plans with reproducibility, stability, effect size,
  boundary, alternative-explanation, and disposition records.
- Stable contradictions persist as observations and can trigger first-class
  `REFORMULATE_HYPOTHESIS` decisions.
- Problem formation, style-normalized divergent ideas, controller-ranked idea
  selection, and multi-slot portfolios.
- Stable contradictory pilot evidence can produce a new problem and idea.
- Integration acceptance: weak intuition takes two probes and reformulates;
  strong prior evidence takes one sanity probe. Both finish at `PILOT` through
  the same loop implementation.

## Phase 5 completion

- Typed claim/evidence graphs and five claim states: supported, partially
  supported, unsupported, contradicted, and overclaimed.
- Evidence-gap planning ranks information value and always specifies a
  falsification test, counterfactual, matched baseline, and negative control.
- Interpretation keeps raw result, observation, interpretation, and claim update
  distinct; leakage, confounders, artifacts, mismatch, or instability prevent
  direct claim promotion.
- Unsupported claims route to evidence collection, uncertain results to
  reproduction, supported claims forward, and stable contradictions to pivot.
- Phase 4 `PILOT` state can resume into `PILOT → ANALYZE → EVIDENCE`; a stable
  contradiction retains its evidence and creates a traceable problem/new idea.
- Resource checks use cumulative project usage, and `DROP` is terminal.

## Phase 6 completion

- Evidence-linked Narrative Spine must pass a taste review before drafting.
- Section and paragraph contracts reference canonical claim/evidence IDs.
- Rhetorical-role retrieval supplies traceable writing precedents.
- Nine distinct critics cover substance, narrative, claim/evidence, redundancy,
  style, venue style, terminology, citation, and global coherence.
- Reviewer feedback becomes typed concerns and research obligations with
  stage-specific actions rather than an unconditional rewrite.
- Acceptance trajectory: a missing-baseline concern selects `ADD_BASELINE`, the
  existing Evidence Loop records matched-baseline evidence, the obligation
  closes, and the paper returns to `COMMUNICATION` for revision 2.

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
