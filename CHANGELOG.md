# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
semantic versioning.

## [Unreleased]

### Added

- Integrity-checked matched-study resume with self-hashed run/cell checkpoints,
  exact artifact revalidation, preserved failed attempts, output-root locking,
  and a ProjectRuntime-owned partial/complete execution boundary.
- Controlled `run full --resume` support with self-hashed stage checkpoints,
  contiguous-prefix reuse, preserved failed attempts, and fail-closed artifact
  integrity validation.
- A trusted ProjectRuntime-to-surface factory and `project surface build` CLI
  that transactionally publishes validated renderer and audit bundles without
  granting generated actions execution authority.
- Project output catalogs now list versioned trusted surface bundles beside each
  owning project and expose their content fingerprint and component files.
- A fail-closed OpenAI-compatible structured backend for bounded model nodes,
  including pinned provider/model identity, exact raw-response hashes, mandatory
  token/cost provenance, bounded retries, and an inert GLM-5.3-Flash example.
- A versioned SciTaste self-development model-node pilot runner with isolated
  deterministic/scripted/replay/live conditions, canonical reports, explicit
  external measurements, and blockers for every missing acceptance input.
- Phase 0/1 controller skeleton and nonlinear demo.
- AutoResearchClaw v0.5.0 as a pinned execution substrate.
- CI, contribution workflow, roadmap, architecture record, and issue templates.
- Phase 2 fixed-candidate intrinsic calibration, metrics, and versioned fixture.
- Provider-neutral preference backend contract with scripted, exact replay,
  recording, and opt-in OpenAI-compatible implementations.
- Example direct-provider configurations and an API provider strategy.
- Phase 3 Knowledge/Taste schemas, separate JSONL stores, provenance-preserving
  taste cases, stage-aware retrieval, and retrieval-augmented decisions.
- Phase 4 unified Hypothesis-Probe-Reformulate loop, structured landscape,
  diagnostic probes, problem/idea formation, portfolios, and evidence-backed
  ideation.
- Offline weak-intuition and strong-hypothesis discovery scenarios and acceptance
  tests.
- Aggregate manifest for the first Bailian/Qwen intrinsic calibration smoke run.
- Phase 3 local-only, license-gated corpus ingestion with provenance hashing,
  deduplication, rejection reporting, and separate Knowledge/Taste persistence.
- Phase 3 rights-scope auditing, per-record article licence enforcement,
  quarantine-first external Taste Cases, deterministic ARIES/CASIMIR projections,
  and a real-source aggregate acceptance manifest.
- Phase 5 claim/evidence graphs, gap analysis, experiment planning,
  interpretation criticism, routing, and state-integrated evidence workflow.
- Phase 6 evidence-gated Narrative Spine, hierarchical writing contracts,
  rhetorical-role retrieval, decomposed writing critics, structured reviewer
  concerns, research obligations, evidence-aware closure, and paper revision.
- Offline support, uncertainty, overclaim, contradiction, Phase 4 resume, and
  evidence-backed pivot acceptance scenarios.
- Phase 7 Figure Contract, figure-need assessment, visual-role retrieval,
  semantic reconstruction, editable SVG/draw.io export, ten-dimension visual
  criticism, and object-level patch history.
- A five-case visual-taste calibration suite and aggregate Bailian
  `qwen3.8-max` smoke-run manifest.
- Phase 7.5 AutoResearchClaw prerequisite/output validation, hashed artifact
  import, stable adapter sessions, wall-time accounting, bounded compatibility
  bootstrap, and one-action substrate workflow/CLI.
- A real qwen3.8-max AutoResearchClaw Stage 1–3 aggregate acceptance manifest and
  a regression-tested SciTaste self-iteration dogfooding case.
- Phase 8 SciTasteBench schemas, an independent six-family fixed-pair suite, five
  condition-isolated evaluation modes, robustness/transfer/calibration metrics,
  paired Base comparisons, exact backend replay support, and hashed reports.
- Phase 9 matched-budget protocol schemas, four-category task assets,
  deterministic/blinded run-matrix planning, six-dimensional budget and
  telemetry audits, expert-panel eligibility gates, and system-metric comparison.
- An opt-in, lazy, local-only Transformers preference backend with pinned model
  identity, greedy decoding, exact recording support, and a Qwen3-VL-4B example.
- An aggregate RTX 3090 Qwen3-VL-4B Base/Full SciTasteBench smoke record.
- Phase 9-B shell-free, isolated and resumable study-cell execution with bounded
  process groups, standard adapter results, runner-owned timing, artifact
  containment/hashing, and atomic per-cell checkpoints.
- Formal/pilot protocol scope enforcement and a 16-cell local Qwen3-VL-4B pilot
  plan that cannot become headline evidence.
- Content-addressed fixed-generator task contracts, a frozen no-live-search
  snapshot, and the pinned Bailian `qwen3.8-max-2026-09-02` formal protocol.
- Real four-condition adapters over unmodified AutoResearchClaw Stage 8–18,
  including isolated Knowledge/Taste augmentation, Full controller traces,
  wire-token/cost telemetry, frozen-network controls, and artifact audits.
- Formal-adapter contract gates for generated experiments, exact cumulative
  token ceilings, resumable/finalizable upstream runs, metric normalization, and
  bounded refinement-log retention.
- Idempotent formal-cell finalization and cumulative runner-owned wall/GPU
  accounting across failed or interrupted cell retries.
- A content-hashed selected-experiment evidence projection with registered metrics,
  bounded per-seed stdout evidence, source hashes, and publication consistency
  audit metadata.
- A pre-paper Stage 14 evidence gate and hash-logged exact identifier sanitizer,
  preventing a contradictory analysis from spending paper-generation tokens.
- A pre-review Stage 17 draft gate, preventing an evidence-inconsistent manuscript
  from spending peer-review tokens.
- A pre-draft Stage 16 outline gate and three-seed publication checks, rejecting
  a pipeline-run count misreported as statistical `N=1` while preserving genuine
  zero dispersion when the registered seed matrix supports it.
- Process-local source-verified sandbox traces for runtime-repaired experiments,
  preserving raw-output hashes and registered seed evidence that upstream omits;
  normalized metrics are rechecked against those traced raw values.
- Synthetic-execution semantics in the selected-evidence contract, with
  assertion-aware checks that prevent CPU simulations from being presented as
  language-model inference while retaining valid negations and limitations.
- Structured frozen-source bibliography projection for formal tasks, allowing
  writing stages to cite only registered sources without live search; offline
  cells also suppress upstream Crossref/arXiv citation verification.
- Publication-completeness gates for duplicate/missing sections, placeholders,
  invented citations, unresolved figures, complete per-seed matrices, and
  descriptive dispersion.
- A deterministic offline manuscript packager that emits Markdown, standalone
  TeX, bibliography, copied figure assets, a build record, and PDF when XeLaTeX
  is available, without an additional model call.
- A canonical `SCITASTE_EVIDENCE_JSON` stdout record for generated formal
  experiments, with exact condition/seed keys and internally verified mean and
  population-standard-deviation values.
- A pilot-scoped Zhipu GLM-5.2 matched-study protocol and launcher for
  cross-provider preacceptance without contaminating the registered Qwen study.
- A generated, project-centric output catalog, canonical
  `outputs/projects/<project-id>/` ownership boundary, global paper aliases,
  per-project current-run Stage browser, bilingual 23-stage reference, and
  stable naming rules for future runs.
- A same-provider Zhipu GLM-5.2 four-condition engineering preacceptance with
  real Stage 8–18 experiments and independently packaged Markdown/TeX/PDF
  manuscripts for Base, Knowledge RAG, Taste Library, and Full SciTaste.
- A project-level SciTaste self-development record linking the Phase 7.5 and
  Phase 9 dogfooding evidence, plus a proposed bounded model-node
  tool-intelligence decision with explicit alternatives, costs, safety gates,
  and acceptance criteria.
- Diagnostic Base/Full capability-boundary reports and same-suite, same-seed
  cross-model comparison with content-hashed CLI output.
- A provider-SDK-free Zhipu `glm-5.3-flash` example through the existing
  OpenAI-compatible backend.
- A typed ProjectRuntime with atomic scaffolding and manifests, optimistic
  revision locks, registered run/paper ownership, safe navigation aliases,
  content-hashed snapshots, backward-compatible legacy loading, and project CLI.
- Opt-in bounded semantic model nodes for review parsing, interpretation-threat
  analysis, and ambiguity-triggered action ranking, with strict typed outputs,
  cumulative cost gates, request-mutation detection, recording, and exact replay.
- A non-executable generative UI contract with 11 closed native-component
  schemas, revisioned evidence bindings, proposal-only interactions, a fixed-shell
  renderer projection, deterministic fixtures, and a trusted ProjectRuntime
  adapter that hashes project-owned runs, stages, papers, and artifacts. Accepted
  surface revisions and proposal receipts can be persisted in an atomic,
  hash-chained JSONL audit log and semantically replayed.
- A working `scitaste run full` offline composition that carries one
  `ResearchState` through Discovery, Evidence, Communication, reviewer-driven
  evidence resolution, and editable Figure generation inside one registered
  project run; it emits readable stage records and a registered
  Markdown/TeX/PDF paper bundle with an evidence-bound UI snapshot.

### Changed

- Communication and Figure workflows can now resume a compatible prior state,
  preserving hypotheses, experiments, claims, decisions, writing, and figures
  across the full project lifecycle. Registered run metadata can be finalized or
  failed under the same optimistic project revision guard.

- OpenAI-compatible backends now make bounded semantic-format repair attempts and
  record attempt count, latency, and raw-response hash.
- Resource feasibility now uses cumulative usage; `ADVANCE` is stage-contextual
  and `DROP` creates a terminal project state.
- The Bailian example backend now pins `qwen3.8-max` for the current opt-in smoke
  contract.
- The formal matched-budget endpoint is peer review (Stage 18); independent
  blinded reviewers, rather than condition-dependent revision retries, own the
  final concern-closure judgment.
- A clean, frozen-protocol Qwen3.8-Max base cell now passes the complete formal
  launcher with content-addressed paper, audit, trace, and upstream manifest.
- Fixed the formal generator instruction to use `numpy.random.default_rng` and
  added complete-condition parsing for `condition: mean=...` metric summaries.

### Fixed

- Pytest now imports test modules by package path, allowing independently
  developed feature suites to use the same test filename without collection
  collisions after branch integration.
- The Makefile now exposes the same pytest-cov coverage command used by CI.

- Study-cell resume now rewinds to the earliest missing publication stage;
  corrective `incorrectly asserted N=1` prose no longer trips the single-seed
  gate; formal prompts inject the contract-derived packet total and prohibit
  per-example model refitting.
- Condition-first `mean_balanced_accuracy` seed rows and explicitly superseded
  cached/fabricated-metric prose now pass evidence auditing; repeated manuscript
  image references no longer duplicate artifact-path entries.

- CI now initializes the pinned AutoResearchClaw submodule before running the
  substrate verification test.
- Outlines that merely promise a later evidence table now receive a deterministic
  checkpoint from the source-verified seed matrix before the draft gate; missing
  local draft images and their adjacent captions are removed rather than
  fabricated, while unsafe and remote image targets remain rejected.
- Interrupted study runners terminate their isolated child process group so an
  orphan cannot contaminate a later attempt for the same cell.
- Formal metric normalization now prefers complete successful execution evidence
  when an upstream repaired-run record omits stdout, and excludes dispersion
  values from primary-metric aggregation.
- Formal metric normalization now accepts a complete registered condition-score
  vector and derives the preregistered aggregate only when every condition is
  present and numeric.
- Formal metric normalization now accepts complete
  `condition: overall_<primary_metric>=...` summaries while still rejecting
  partial registered-condition vectors.
- Formal metric normalization and seed-evidence parsing now accept
  `Condition '<name>': primary metric ...` summaries and condition-scoped
  `Seed <n>: ...` rows. Adapter-derived aggregates remain admissible only when
  every source value is present in the source-verified raw trace.
- Formal seed-evidence parsing now accepts seed-scoped `Condition` blocks whose
  metric is emitted on the following `primary_metric: mean=...` line. It derives
  population cross-seed dispersion from the complete registered seed vector
  instead of mistaking an across-cell spread for cross-seed uncertainty.
- Legacy formal outputs using `condition=<name> mean_ba=<value>` rows are parsed
  under their enclosing seed blocks. Evidence fields lacking a complete seed
  vector are excluded, preventing similarly named factor-effect rows from being
  promoted to registered methods.
- When both an initial and runtime-repaired sandbox succeed, formal selection
  now pairs the retained mutable version directory with the sandbox trace whose
  executed-source hashes match it. Metrics and stdout are never borrowed from a
  successful but superseded source version.
- The three-seed analysis audit now recognizes `erroneously claimed N=1` as an
  explicit correction while continuing to reject unqualified single-seed
  assertions.
- Canonical machine evidence now overrides heuristic stdout metrics after its
  complete condition-by-seed matrix is verified. The cross-method primary
  aggregate is recomputed from registered condition means, and its derived
  provenance is recorded separately from directly observed condition metrics.
- Frozen-contract validation now accepts an AST-literal `CONTRACT_SPEC` only
  when its nested factor, seed, sample, method, metric, and generator values
  exactly normalize to the registered contract. The canonical declaration
  remains preferred, and any changed registered field is still rejected.
- Independent stdout seed-coverage validation now recognizes `seed=<id>` and
  `seed: <id>` condition rows while excluding aggregate phrases such as
  `examples per seed: 648` and `Total/seed: 648`. Identification is restricted
  to explicit seed rows instead of scanning arbitrary prose; machine evidence
  still supplies the authoritative condition-by-seed values.
- Seed-row discovery now accepts `Condition=<name> Seed=<id>
  BalancedAccuracy=<value>` records and rejects decimal factor-effect rows such
  as `seed: 0.008292` rather than truncating the decimal into an identifier.
- The immutable contract literal and canonical machine-evidence requirement now
  live in the Stage 10 system prompt as well as its initial user prompt. Upstream
  code-review fixes and topic-alignment regeneration therefore receive the same
  constraints instead of silently dropping them.
- Three-seed publication audits now classify `do not infer N=1` and `do not
  derive N=1` as prohibitions rather than affirmative single-seed claims.
- Single-seed audits now also recognize prohibited, forbidden, rejected, or
  avoided N=1 summaries as corrective language rather than evidence collapse.
- Synthetic-scope audits now recognize `do not` and `must not` limitations on
  internal model signals while retaining rejection of affirmative neural-model
  measurement claims.
- Formal analysis and paper prompts now treat the successful Stage 13 refinement
  as authoritative over superseded failures, while task manuscripts reject
  internal generator/provenance identifiers and missing selected primary metrics.
- Corrected finalization stage detection for quality gate, knowledge archive,
  publication export, and Stage 23 citation verification.
