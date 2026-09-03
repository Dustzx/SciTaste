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
| Phase 7 — figures | done | figure contract produces editable, reviewed SVG/draw.io output |
| Phase 7.5 — real substrate gate | done | pinned upstream Stage 1–3 run yields validated artifacts and a SciTaste transition |
| Phase 8 — SciTasteBench | done | intrinsic/augmented evaluation is controlled and reproducible |
| Phase 9 — matched-budget study | in progress | protocol/planner/auditor done; real matched runs and external expert review pending |

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

## Phase 7 completion

- Figure-need assessment precedes rendering and records why prose alone is
  insufficient.
- A typed Figure Contract binds purpose, target claims, reader takeaway,
  entities, relations, forbidden emphasis, panels, and retrieved references.
- Deterministic semantic reconstruction exports stable object IDs to editable
  SVG and uncompressed draw.io XML.
- Ten visual critics separate scientific communication from aesthetics and run
  both before and after patching.
- Object-level patches preserve field-level old/new values and rationales in
  `ResearchState`.
- Acceptance trajectory detects forbidden executor emphasis in two critic
  dimensions, deduplicates it to one patch, and clears all final findings.
- A five-case Bailian `qwen3.8-max` visual-taste smoke run passed the fixed
  candidate protocol; raw responses remain local and ignored.

## Phase 7.5 completion

- AutoResearchClaw remains an unmodified `v0.5.0` submodule.
- Supported action mappings now enforce upstream prerequisites and output
  contracts instead of trusting subprocess exit codes.
- Artifact manifests preserve path, type, size, file count, and SHA-256.
- Stable SciTaste session identity spans upstream run-ID changes in one run
  directory; both IDs remain visible.
- Failed execution does not advance canonical state; successful execution logs
  the decision, result, transition, artifacts, and measured wall time.
- A Bailian `qwen3.8-max` live slice completed Stages 1–3 and imported all three
  Stage 3 artifacts. API cost remains unavailable because upstream produced no
  cost log.
- SciTaste's own adapter decision is preserved as a dogfooding case, explicitly
  excluded from Phase 8 headline effectiveness evaluation.

## Phase 8 completion

- A versioned independent smoke suite covers Idea, Experiment, Evidence, Writing,
  Review, and Visual fixed-pair decisions.
- Base, Knowledge RAG, Taste Library, Taste Critics, and Full SciTaste conditions
  construct isolated, fingerprinted requests through one backend contract.
- Reports include pairwise accuracy, expert agreement, confidence calibration,
  wrong-level decisions, per-task metrics, three transfer slices, style
  invariance, paraphrase consistency, and paired changes from Base.
- Self-referential cases are schema-blocked from headline metrics; the SciTaste
  self-iteration case remains dogfooding only.
- Ranking correlation is unavailable under the pair-selection response contract,
  and Phase 9 system outcomes are explicitly deferred rather than approximated.
- Deterministic offline acceptance spans all conditions and stores content hashes;
  scripted scores verify the evaluator, not SciTaste effectiveness.

## Phase 9 progress

- A content-hashed protocol covers diagnosis-friendly, clear-hypothesis,
  new-formulation, and ambiguous-direction tasks.
- AutoResearchClaw, Knowledge RAG, Taste Library, and Full SciTaste are enabled;
  Sibyl and AI Scientist-v2 remain explicitly unavailable pending pinned adapters.
- Three seeds generate 48 deterministic cells with opaque blind-review IDs and
  identical GPU, experiment, wall-time, API-cost, search, and token budgets.
- The evaluator rejects missing cells, failed execution, missing telemetry,
  over-budget usage, inconsistent experiment counts, internal/missing review,
  and unresolved protocol readiness markers.
- System metrics and deltas against AutoResearchClaw are implemented. Synthetic
  fixtures can only produce `acceptance_only`; headline eligibility requires real
  executions and valid external expert panels.
- A pinned, local-only Qwen3-VL-4B Transformers backend passed a Base/Full
  SciTasteBench smoke run on one RTX 3090. This clears local decision-backend
  feasibility, not the full matched-system execution gate.
- A shell-free, resumable `study run` harness now isolates cells, terminates
  timed-out process groups, measures allocated GPU/wall time, validates adapter
  counters and outcomes, and independently hashes in-cell artifacts.
- A 16-cell Qwen3-VL-4B local pilot protocol is execution-ready and permanently
  non-headline; its four launcher commands remain explicit adapter work rather
  than synthetic substitutes.
- The formal protocol now pins `qwen3.8-max-2026-09-02`, a content-addressed
  no-live-search snapshot, and fixed-generator contracts for all four tasks.
- A first-party adapter runs unmodified AutoResearchClaw Stage 8–18 for the four
  core conditions. Knowledge and decision-precedent context remain isolated;
  Full additionally persists a real `TasteController` decision.
- Process-local controls disable hidden upstream retrieval, bound Qwen output,
  capture wire-token/cost telemetry, and reject generated experiment sources
  that violate the frozen-network policy.
- A real Qwen3.8-Max diagnosis/base preacceptance reached peer review with one
  valid generated experiment, a 0.828558 balanced-accuracy result, and a
  7,821-word paper draft. This validates one cell, not the four-condition or
  48-cell comparison.
- A clean commit-pinned formal base cell subsequently passed in one runner
  lifecycle with complete wall/GPU accounting, 138,157 provider tokens, one
  repaired real experiment, a 0.615945 registered aggregate, and Stage 18
  artifacts. The other 47 cells and external blinded reviews remain pending.
- The Knowledge RAG preacceptance exposed a Stage 12 failure/Stage 13 repair
  provenance ambiguity and internal identifier leakage into its draft. The adapter
  now projects one hashed successful experiment into analysis/writing, separates
  publication language from audit identifiers, and rejects contradictory or
  internal-ID-bearing manuscripts. Analysis is now a pre-paper gate so a known-bad
  synthesis cannot consume drafting tokens; the outline is checked before drafting,
  and the resulting draft is independently gated before peer review. Three-seed
  evidence and dispersion cannot be flattened into an `N=1` summary. The adapter
  also preserves source-verified raw sandbox traces when upstream runtime repair
  retains only parsed metrics. Formal drafts now also require a complete 3×3 seed
  matrix, real dispersion, unique core sections, registered citations, and resolved
  figures. Passing drafts are deterministically packaged as self-contained
  Markdown/TeX/PDF deliverables without another model call. A later clean attempt
  exposed and regression-tested the quoted condition-summary stdout form before
  spending paper tokens. Two further clean attempts exposed seed-scoped metric
  blocks and `condition=<name> mean_ba=<value>` rows before paper generation.
  Those layouts are regression fixtures, and new executions must emit one
  internally verified machine-readable evidence record. A clean rerun remains
  required. A fourth clean attempt emitted that record but exposed an ambiguous
  initial-versus-repaired sandbox pairing; source-hash-based trace selection now
  regression-tests that case. A fifth attempt passed experiment acceptance and
  produced a correct three-seed analysis, exposing only an overly narrow
  corrective-language matcher before outline generation; that analysis now
  replays cleanly. A sixth attempt exposed disagreement between heuristic stdout
  metrics and the complete machine matrix; canonical condition means now win,
  and the primary aggregate is deterministically recomputed. Attempts 4–6 all
  replay through experiment acceptance under the combined fixes. A seventh
  attempt emitted a complete source-verified matrix but used a semantically
  equivalent nested `CONTRACT_SPEC` after upstream review regeneration. Strict
  field-by-field normalization now accepts that representation without modifying
  generated source; the failed run remains a fixture, while its Stage 13 output
  passes the corrected experiment gate only in an isolated offline replay. A new
  clean end-to-end rerun remains required. An eighth invocation produced a
  source-verified 3×3 matrix and canonical contract but rendered its human rows
  as `seed=<id>`; the original seed scanner rejected them. The corrected scanner
  accepts assignment-style identifiers, rejects `per seed` sample-count text,
  and replays that Stage 13 output at a derived aggregate of 0.803657979. The
  invocation's unintended second selected seed cell was stopped after the shared
  parser issue was known, and the entire directory remains a failed fixture.
  A ninth single-cell attempt confirmed the runner cap, but Stage 10 alignment
  regeneration discarded the canonical declaration while retaining scattered
  factor values; the strict gate rejected it before analysis at 64,678 tokens.
  Contract and machine-evidence requirements now appear in the Stage 10 system
  prompt used by initial generation, code-review fixes, and alignment
  regeneration. The scattered-value output remains rejected rather than being
  retrospectively inferred as compliant.
  A tenth single-cell attempt verified that the regeneration-safe prompt retains
  the canonical declaration and produced a valid 3×3 machine matrix, but the
  free-text seed scanner mistook `Total/seed: 648` for an identifier. Explicit
  seed-row parsing now replays that experiment gate at a derived aggregate of
  0.8069381276; the original run remains failed and was not resumed.
  An eleventh single-cell attempt passed the experiment and Stage 14 analysis
  gates, then stopped before drafting because the outline instruction `Do not
  infer N=1` was read as an affirmative claim. Prohibitive `do not infer/derive`
  language is now accepted while unqualified N=1 claims remain rejected.
  A twelfth attempt passed the experiment gate but stopped after Stage 14 because
  `do not serve as direct measurements of ... internal confidence` was treated
  as affirmative model-signal language. Synthetic-scope auditing now recognizes
  `do not` and `must not` limitations while preserving positive-claim rejection.
  Interrupted and original artifacts are retained only as failure fixtures.
- Sibyl and AI Scientist-v2 are optional external integrations still to be
  implemented and acceptance-tested; no surrogate output is used while disabled.
- Pending before the exit gate: pass four-condition preacceptance, run all 48
  commit-pinned cells, audit their artifacts, and collect external reviews.

## Project controls

- One milestone owner and one acceptance issue per phase.
- Weekly triage: blockers, risks, decisions, and evidence of exit criteria.
- Every architecture change receives an ADR in `docs/ARCHITECTURE.md` or a
  dedicated `docs/adr/` record once ADR count grows.
- Generated research artifacts stay outside Git; manifests and hashes may be
  committed when needed for reproducibility.
- The submodule update cadence is milestone-bound, not automatic.

## Known integration issue

A real AutoResearchClaw Stage 1–3 slice has passed with a user-provided Bailian
key. Broader stages still require user-managed configuration and may incur
network/API/compute cost. CI therefore uses contract fixtures and dry-run rather
than contacting the provider.

Live taste calibration is also opt-in. Until credentials are provided, scripted
and replay backends support all implementation, regression, and integration work;
they must not be described as a real-model taste profile.
