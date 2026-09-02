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

### Changed

- OpenAI-compatible backends now make bounded semantic-format repair attempts and
  record attempt count, latency, and raw-response hash.
- Resource feasibility now uses cumulative usage; `ADVANCE` is stage-contextual
  and `DROP` creates a terminal project state.
