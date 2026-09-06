# SciTaste

Scientific-taste-guided control for autonomous research.

SciTaste is an independent, first-party autonomous-research project. Its
controller observes persistent research state, ranks candidate actions, records
why an action was selected, and executes only that action through a replaceable
boundary. `scitaste-native` is the default integrated executor;
AutoResearchClaw is retained unmodified as an optional compatibility adapter and
fixed external baseline, never as a required runtime or owner of the trajectory.

## Current milestone

Phases 0 through 8, including the Phase 7.5 real-substrate gate, are implemented.
The Phase 9 matched-budget protocol is in progress; license-reviewed external
corpus expansion continues as a data operation:

The four enabled core conditions have passed a same-provider GLM-5.2 engineering
preacceptance on one frozen task. The complete 48-cell run and external blinded
review remain pending, so no effectiveness claim is made from that pilot.

- canonical, versioned `ResearchState`;
- typed research actions and auditable decisions;
- nonlinear, decision-driven transitions including `PROBE` and `PIVOT`;
- deterministic training-free taste controller;
- atomic JSON persistence;
- framework-neutral executor protocol, default first-party native executor,
  explicit deterministic mock, and an optional pinned AutoResearchClaw adapter;
- project-owned native action records with predecessor/state/action/input/output
  hashes, real local Knowledge Library retrieval, and a Bubblewrap-isolated
  registered CPU experiment with independently derived replicate metrics;
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
  normalized mature ideas, portfolios, and evidence-backed ideation;
- claim/evidence graphs, evidence-gap planning, interpretation criticism,
  cumulative resource accounting, and contradiction-driven pivots;
- local-only, license-gated ingestion for OpenReview-, ARIES-, CASIMIR-, and
  accepted-paper-shaped snapshots;
- rights-scope preflight, deterministic ARIES/CASIMIR curation, and quarantine of
  external Taste Cases until human verification;
- evidence-gated narrative and writing contracts, rhetorical-role taste
  retrieval, decomposed writing critics, reviewer obligations, and review-driven
  evidence collection returning to paper revision;
- claim-linked Figure Contracts, visual-role retrieval, semantic object
  reconstruction, editable SVG/draw.io export, split visual critics, and
  traceable object-level patches;
- a pinned, unmodified AutoResearchClaw adapter with prerequisite checks,
  contract-validated artifact manifests, stable session identity, runtime
  accounting, and a successful live Stage 1–3 vertical slice;
- an independent six-family SciTasteBench smoke suite with five isolated
  intrinsic/augmentation conditions, transfer and robustness diagnostics,
  paired comparisons, exact replay support, and content-hashed reports;
- a deterministic four-category matched-budget study planner with blinded expert
  review contracts, complete resource auditing, eligibility gates, and explicit
  readiness blockers;
- a typed, revision-guarded project runtime that owns runs, paper bundles,
  content-hashed snapshots, and safe current-artifact aliases;
- bounded, opt-in semantic model nodes whose typed advice remains behind
  deterministic feasibility, budget, evidence, and transition gates, plus a
  fail-closed compatible live backend, versioned self-development pilot, and
  durable project-owned runtime/CLI for layered profiles, execution, exact
  replay, restart-safe accounting, auditable resume, and verification;
- an opt-in `run full` evidence hook that projects the real immutable research
  state into `interpretation-threat`, binds its input/proposal/recording/ledger
  to the stage checkpoint, grants it no mutation or execution power, and exposes
  live GLM-5.3-Flash only behind configuration plus caller authorization with
  no-repeat paid-response recovery;
- evidence-bound generative UI contracts with a fixed trusted shell,
  proposal-only interactions, and a ProjectRuntime adapter that hashes the exact
  project artifacts exposed to a surface;
- a loopback-first authenticated local UI/API that renders the closed component
  registry as a navigable evidence workspace, restricts inspection to visible
  hashed artifacts, revalidates identity-only events, and persists project-bound
  proposal/inspection audits without invoking a controller or tool.

The milestone sequence and acceptance criteria live in
[`docs/ROADMAP.md`](docs/ROADMAP.md). The full project specification is tracked
by [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

## Quick start

Prerequisite: Python 3.11 or newer. The AutoResearchClaw submodule is optional
and needed only for its compatibility/baseline commands.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/scitaste run demo --output outputs/demo --seed 7
.venv/bin/pytest
```

Inspect the generated `outputs/demo/research_state.json`,
`outputs/demo/decisions.jsonl`, and `outputs/demo/demo_summary.json` to see the
complete decision trail.

## Finding generated outputs

Use `outputs/INDEX.md` as the human-readable entry point. The canonical unit is
`outputs/projects/<project-id>/`, which owns its runs, evidence, reviews, and
paper versions. `outputs/papers/` is only a global shortcut layer; the newest
bundle remains available at `outputs/papers/latest/`. Refresh the catalog after
an execution:

```bash
.venv/bin/python scripts/catalog_outputs.py outputs
```

The catalog groups paper versions beneath their project, explains every
`stage-NN` directory, and separates successful bundles from failed or resumable
raw runs. It also links each versioned trusted project-interface bundle under
the same project entry. See
[`docs/OUTPUT_LAYOUT.md`](docs/OUTPUT_LAYOUT.md) for the naming convention. Old
run directories remain in place so checkpoints and artifact hashes stay valid.

Create a managed project or inspect an existing one without searching through
top-level output directories:

```bash
.venv/bin/scitaste project init \
  --project-id my-project --title "My project" \
  --research-direction "A falsifiable research direction"
.venv/bin/scitaste project status --project-id my-project
```

Run and paper registration requires the current project revision, so concurrent
workers fail on stale state instead of overwriting one another. See
[`docs/PROJECT_RUNTIME.md`](docs/PROJECT_RUNTIME.md).

Generate a trusted, content-addressed project overview bundle with:

```bash
.venv/bin/scitaste project surface build \
  --project-id my-project --outputs-root outputs \
  --destination outputs/projects/my-project/surfaces/overview-v1
```

This emits declarative surface/renderer JSON plus a verified audit root; its
actions remain proposals and cannot execute tools or mutate project state.

Serve the current authoritative projects through the receiver-owned local UI:

```bash
export SCITASTE_UI_TOKEN='replace-with-a-long-local-secret'
.venv/bin/scitaste ui serve --outputs-root outputs
```

The default bind is `127.0.0.1:8765`. Project APIs require the bearer credential;
the fixed public shell contains no project state. Browser actions produce only
audited `proposal_pending` receipts with execution authority `none`. There is no
controller, tool, arbitrary file, or model endpoint. See
[`docs/GENERATIVE_UI.md`](docs/GENERATIVE_UI.md).

Run the complete offline Discovery → Evidence → Communication → Figure path in
one managed project and produce a registered Markdown/TeX/PDF paper bundle:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-reviewed-draft \
  --seed 7 --output outputs
```

A failed workflow-stage attempt can resume the same run with `--resume`.
Completed stage checkpoints are reused only after their state chain and declared
artifact hashes validate; partial stage directories are retained under that
run's `failed_attempts/` tree.

This validates end-to-end framework behavior with SciTaste's first-party
executor, including real local retrieval and one content-bound, no-network CPU
experiment. It is not yet autonomous code generation, a general experiment
platform, or an effectiveness result. A working Bubblewrap installation is
required; pass `--backend mock` only for explicit test compatibility. See
[`docs/FULL_WORKFLOW.md`](docs/FULL_WORKFLOW.md).
The native action evidence and current capability boundary are documented in
[`docs/NATIVE_EXECUTION.md`](docs/NATIVE_EXECUTION.md).

To exercise the same full path with a network-free, project-ledger-backed
semantic advisory, use
`configs/workflows/full_offline_model_advisory_v1.yaml`. The generated
`stages/evidence/model_advisory.json` is proposal-only and proves that the
evidence `ResearchState` was unchanged.

For Phase 9 executions, `scitaste study project-run` registers the matrix or
selected cells beneath an existing project instead of producing another
top-level output directory. Its resume path revalidates the protocol, launcher,
request, command, execution record, and artifact hashes before skipping a cell.
See [`docs/MATCHED_BUDGET_STUDY.md`](docs/MATCHED_BUDGET_STUDY.md).

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

Run the independent Phase 8 controlled benchmark offline with:

```bash
.venv/bin/scitaste benchmark run \
  --backend scripted --seed 7 \
  --output outputs/scitastebench-phase8-offline
```

This synthetic suite validates Base versus Knowledge RAG, Taste Library, Taste
Critics, and Full SciTaste comparisons; its programmed scores are not an
effectiveness claim. See [`docs/SCITASTEBENCH.md`](docs/SCITASTEBENCH.md).

Inspect the Phase 9 system-study matrix without launching any experiment:

```bash
.venv/bin/scitaste study plan --dry-run
```

The current 48-cell plan remains blocked from real execution until the provider
model revision and frozen search snapshot are resolved. See
[`docs/MATCHED_BUDGET_STUDY.md`](docs/MATCHED_BUDGET_STUDY.md).

Dry-run the non-headline, 16-cell local RTX 3090 pilot through the standard
launcher boundary:

```bash
.venv/bin/scitaste study run \
  --config configs/experiments/matched_budget_local_pilot_v1.yaml \
  --launch-config configs/experiments/study_launchers.example.yaml \
  --task diagnosis-friendly-v1 --dry-run
```

The committed launcher file is a template, not an implementation. Replace each
command with a real condition adapter before removing `--dry-run`; missing or
invalid adapters produce explicit failed cells rather than surrogate outputs.
See [`docs/EXTERNAL_SYSTEM_ADAPTERS.md`](docs/EXTERNAL_SYSTEM_ADAPTERS.md) for
the adapter and sandbox boundary.

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

## Local single-GPU model

The optional text-only Transformers backend runs preference calibration and
SciTasteBench directly from an existing local checkpoint. It never downloads a
model implicitly:

```bash
.venv/bin/pip install -e '.[local-gpu]'
export SCITASTE_LOCAL_MODEL_PATH=/absolute/path/to/Qwen3-VL-4B-Instruct
.venv/bin/scitaste benchmark run \
  --backend local-transformers \
  --config configs/backends/local_transformers_qwen3vl4b.example.yaml \
  --condition base --condition full_scitaste \
  --record outputs/qwen3vl4b-local/recording.jsonl \
  --output outputs/qwen3vl4b-local --seed 7
```

The example pins the official Qwen checkpoint revision. Keep one process alive
for a multi-case run so model weights load only once. The local backend is a
model-decision backend, not a replacement for a complete Phase 9 system
executor.

Compare two same-suite, same-seed benchmark reports without making a causal
capability claim:

```bash
.venv/bin/scitaste benchmark attribute \
  --primary-report outputs/model-a/benchmark_report.json \
  --comparator-report outputs/model-b/benchmark_report.json \
  --output outputs/model-a-vs-model-b
```

New Zhipu pilots use `configs/backends/zhipu_glm53_flash.example.yaml`. It uses
the existing OpenAI-compatible backend and therefore adds no provider SDK to the
default installation.

The bounded-model-node path also has a real-provider engineering configuration
at `configs/model_nodes/pilot_orchestration.zhipu_glm53_unpriced_probe.yaml`.
It is explicitly non-promotable: it records a live GLM-5.3-Flash exchange and
then fails closed when verified cost telemetry is unavailable. The first
project-owned run exercised exact response retention and deterministic rejection;
see `docs/experiments/zhipu_glm53_model_node_probe_2026-09-05.md`.

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

## Offline Evidence Loop

Run a supported claim or a stable contradictory result:

```bash
.venv/bin/scitaste evidence plan \
  --config configs/evidence/support_demo.yaml \
  --output outputs/evidence-support --seed 7
.venv/bin/scitaste evidence plan \
  --config configs/evidence/contradiction_demo.yaml \
  --state outputs/discovery-strong/research_state.json \
  --output outputs/evidence-pivot --seed 7
```

The second command explicitly resumes the Phase 4 `PILOT`, executes and analyzes
it, records evidence and interpretation, then pivots without discarding the
contradictory result. Plans include a falsification test, counterfactual, matched
baseline, and negative control.

## Offline Communication Loop

Run the evidence-backed writing and reviewer-driven research acceptance path:

```bash
.venv/bin/scitaste write \
  --config configs/writing/reviewer_experiment_demo.yaml \
  --output outputs/communication --seed 7
```

The deterministic draft is built from claim/evidence contracts and rhetorical
taste precedents. A missing-baseline review concern routes to the Evidence Loop;
matching new evidence closes the obligation and produces revision 2. This tests
research control and traceability rather than model prose quality. See
[`docs/COMMUNICATION_LOOP.md`](docs/COMMUNICATION_LOOP.md).

## Offline Figure Loop

Build the mechanism-figure acceptance fixture:

```bash
.venv/bin/scitaste figure build \
  --config configs/visual/mechanism_demo.yaml \
  --output outputs/figure-demo --seed 7
```

The scenario intentionally introduces misleading emphasis, records the visual
critic findings, applies one object-level patch, and exports editable SVG and
uncompressed draw.io artifacts. See [`docs/FIGURE_SYSTEM.md`](docs/FIGURE_SYSTEM.md).

## License-gated corpus ingestion

Copy `configs/data/external_corpus.example.yaml`, point it to local snapshots,
and mark a source `permitted` only after recording its license identifier and
authoritative terms URL:

```bash
.venv/bin/scitaste library audit \
  --config path/to/reviewed-manifest.yaml \
  --output outputs/corpus-audit
.venv/bin/scitaste library ingest \
  --backend local --config path/to/reviewed-manifest.yaml \
  --output outputs/external-library
```

No downloader is included. Unknown/restricted licenses, uncovered content scopes,
article text without per-record permission, and incomplete decision precedents
are rejected. External Taste Cases remain retrieval-ineligible until human
verification. See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

Supported deterministic projections can prepare official local snapshots without
claiming that observed revisions are good scientific decisions:

```bash
.venv/bin/scitaste library curate \
  --source-format aries-alignment \
  --input path/to/alignment_human_eval.jsonl \
  --output outputs/aries-curated
```

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
by the user without `--dry-run`. A bounded real-substrate smoke and the
`substrate execute` command are documented in
[`docs/AUTORESEARCHCLAW_INTEGRATION.md`](docs/AUTORESEARCHCLAW_INTEGRATION.md).
Provider-backed selected stages should first create their Stage 1–2 source with
`substrate project bootstrap plan|execute|status`, then use
`substrate project plan|execute|status` with `--source-project-run`. This keeps
the prerequisite, immutable input, mutable work, and exact completion evidence
under one project and supports audited recovery without modifying
AutoResearchClaw.

SciTaste development itself is also tracked as a dogfooding case for process
usability and auditability. It is deliberately excluded from independent
effectiveness claims; see
[`docs/cases/SCITASTE_SELF_ITERATION.md`](docs/cases/SCITASTE_SELF_ITERATION.md).
Its canonical local project record is
`outputs/projects/scitaste-self-development/`, alongside the research projects
that SciTaste produces.

## Development

```bash
make install
make check
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch, issue, commit, review, and
release conventions.
