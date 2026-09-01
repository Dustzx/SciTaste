# SciTaste

Scientific-taste-guided control for autonomous research.

SciTaste separates high-level research decisions from execution. The controller
observes a persistent research state, ranks candidate actions, records why an
action was selected, and delegates only that action to an execution substrate.
AutoResearchClaw is pinned as the first substrate; its fixed pipeline does not
own SciTaste's global trajectory.

## Current milestone

Phase 0/1, Phase 2 calibration, and Phase 4 Discovery Loop are implemented; the
Phase 3 library core is usable while external corpus expansion continues:

- canonical, versioned `ResearchState`;
- typed research actions and auditable decisions;
- nonlinear, decision-driven transitions including `PROBE` and `PIVOT`;
- deterministic training-free taste controller;
- atomic JSON persistence;
- framework-neutral executor protocol, deterministic mock, and a pinned
  AutoResearchClaw adapter;
- runnable nonlinear demo and tests;
- fixed-candidate intrinsic taste calibration with accuracy, confidence, Brier,
  and calibration metrics;
- exact request recording/replay plus an opt-in OpenAI-compatible live backend;
- physically and schematically separate Knowledge and Taste libraries;
- provenance-preserving taste cases and stage-aware precedent retrieval;
- intrinsic and retrieval-augmented controller modes with precedent IDs in the
  decision log;
- one adaptive Hypothesis–Probe–Reformulate loop with structured literature
  landscape, falsifiable hypotheses, diagnostic probes, problem formation,
  normalized mature ideas, portfolios, and evidence-backed ideation.

The milestone sequence and acceptance criteria live in
[`docs/ROADMAP.md`](docs/ROADMAP.md). The full project specification is tracked
by [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

## Quick start

Prerequisite: Python 3.11 or newer and Git submodules.

```bash
git submodule update --init --recursive
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/scitaste run demo --output outputs/demo --seed 7
.venv/bin/pytest
```

Inspect the generated `outputs/demo/research_state.json`,
`outputs/demo/decisions.jsonl`, and `outputs/demo/demo_summary.json` to see the
complete decision trail.

## Work without an API key

API access is optional for development and CI. Run the fixed offline calibration,
build the two libraries, and verify exact replay with:

```bash
.venv/bin/scitaste taste calibrate \
  --backend scripted --seed 7 \
  --output outputs/calibration \
  --record outputs/calibration/recording.jsonl
.venv/bin/scitaste taste calibrate \
  --backend replay --seed 7 \
  --replay outputs/calibration/recording.jsonl \
  --output outputs/calibration-replay
.venv/bin/scitaste library build --output outputs/library
```

The scripted fixture deliberately scores 4/5 so the report exercises incorrect
as well as correct judgments. It validates the evaluation pipeline, not a real
model's scientific taste.

## Opt-in live calibration

Provider examples are in `configs/backends/`. Put the secret in the environment,
never in YAML, then explicitly select the live backend and record the run:

```bash
export DASHSCOPE_API_KEY='...'
export BAILIAN_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
.venv/bin/scitaste taste calibrate \
  --backend openai-compatible \
  --config configs/backends/bailian.example.yaml \
  --record outputs/bailian-calibration/recording.jsonl \
  --output outputs/bailian-calibration
```

No live provider is contacted by tests, installation, library building, demo, or
dry-run commands. See [`docs/API_PROVIDERS.md`](docs/API_PROVIDERS.md) for the
recommended provider strategy and reproducibility controls.

## Offline Discovery Loop

Run the weak-intuition and strong-hypothesis scenarios through the same engine:

```bash
.venv/bin/scitaste discover \
  --config configs/experiments/discovery_weak.yaml \
  --output outputs/discovery-weak --seed 7
.venv/bin/scitaste discover \
  --config configs/experiments/discovery_strong.yaml \
  --output outputs/discovery-strong --seed 7
```

The first trajectory probes, is contradicted, reformulates, and probes again.
The second performs one sanity check before maturing an idea. `evidence-first-like`
and `idea-first-like` are computed descriptions of those trajectories, not
hard-coded execution modes.

## AutoResearchClaw baseline

The pinned substrate can be inspected without credentials:

```bash
.venv/bin/scitaste baseline run \
  --topic "Robust scientific agents" \
  --output outputs/baseline-smoke \
  --dry-run
```

For a real baseline run, copy `.env.example`, create an AutoResearchClaw config,
install it with `make install-substrate`, and pass the config with `--config`.
SciTaste never sends a baseline request unless the command is explicitly invoked
without `--dry-run`.

## Development

```bash
make install
make check
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch, issue, commit, review, and
release conventions.
