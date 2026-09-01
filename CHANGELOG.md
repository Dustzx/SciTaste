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

### Changed

- OpenAI-compatible backends now make bounded semantic-format repair attempts and
  record attempt count, latency, and raw-response hash.
