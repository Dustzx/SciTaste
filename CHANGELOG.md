# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
semantic versioning.

## [Unreleased]

### Added

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

### Changed

- OpenAI-compatible backends now make bounded semantic-format repair attempts and
  record attempt count, latency, and raw-response hash.
- Resource feasibility now uses cumulative usage; `ADVANCE` is stage-contextual
  and `DROP` creates a terminal project state.
- The Bailian example backend now pins `qwen3.8-max` for the current opt-in smoke
  contract.

### Fixed

- CI now initializes the pinned AutoResearchClaw submodule before running the
  substrate verification test.
