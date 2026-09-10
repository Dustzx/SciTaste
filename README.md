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
  hashes, real local Knowledge Library retrieval in both Full Workflow and
  composable Discovery, plus a proposal-only registered or model-produced CPU
  experiment that requires deterministic admission before Bubblewrap execution
  and independently derived replicate metrics; a rejected generated source may
  receive one separately ledgered source-only repair, which must pass the same
  admission policy and is never called when the first proposal is accepted;
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
- evidence-gated narrative and writing contracts, hierarchical Writing Taste
  retrieval, an integrity-first deterministic assessor, a proposal-only semantic
  writing review node, content-bound venue/archetype guidance, decomposed critics,
  reviewer obligations, and
  review-driven evidence collection returning to paper revision;
- claim-linked Figure Contracts, visual-role retrieval, semantic object
  reconstruction, editable SVG/draw.io export, split visual critics, and
  traceable object-level patches;
- a pinned, unmodified AutoResearchClaw adapter with prerequisite checks,
  contract-validated artifact manifests, stable session identity, runtime
  accounting, an append-only three-phase external-call protocol, no-repeat
  recovery for durable results, and a successful live Stage 1–3 vertical slice;
- an independent six-family SciTasteBench smoke suite with five isolated
  intrinsic/augmentation conditions, transfer and robustness diagnostics,
  paired comparisons, exact replay support, and content-hashed reports;
- a deterministic four-category matched-budget study planner with blinded expert
  review contracts, complete resource auditing, eligibility gates, and explicit
  readiness blockers;
- a typed, revision-guarded project runtime that owns runs, paper bundles,
  content-hashed snapshots, and safe current-artifact aliases;
- a strict open-question intake that turns a research brief into a self-hashed
  launch admission plan, deterministically selects an eligible registered
  four-stage bundle from a content-bound catalog, then executes only project-owned
  copies while keeping model planning proposal-only;
- bounded, opt-in semantic model nodes whose typed advice remains behind
  deterministic feasibility, budget, evidence, and transition gates, plus a
  fail-closed compatible live backend, versioned self-development pilot, and
  durable project-owned runtime/CLI for layered profiles, execution, exact
  replay, restart-safe accounting, auditable resume, and verification. The
  Tool Intelligence catalog can plan over three typed read-only capabilities,
  propose schema-pinned repairs, and run one admitted action through a durable,
  project-owned lease/claim/result/observation chain backed by content-addressed
  first-party handlers; observations cannot mutate state or admit themselves as
  evidence. Its registered GLM-5.3-Flash study is a narrow preliminary routing
  signal and remains non-scientific pending independent blinded review;
- an opt-in `run full` evidence hook that projects the real immutable research
  state into `interpretation-threat`, binds its input/proposal/recording/ledger
  to the stage checkpoint, grants it no mutation or execution power, and exposes
  live GLM-5.3-Flash only behind configuration plus caller authorization with
  no-repeat paid-response recovery;
- a Full Workflow Tool Intelligence hook that detects a deterministic
  post-evidence hotspot, binds one exact project evidence scope, and may execute
  one leased registered read-only handler while keeping its observation outside
  canonical evidence and state-transition authority; all configured model-node
  hooks share one type-checked ledger;
- a progress-first Generation as Content workspace with a fixed trusted shell,
  evidence-derived quick intents, bounded free questions, closed native layout
  planning, deterministic fallback, proposal-only interactions, and exact
  ProjectRuntime evidence binding. Its credential-free loopback shell opens a
  portfolio index, a stable home for every project, project-owned research
  topics, and one deep-linked page per immutable question or follow-up, plus
  fingerprinted structural/latency evaluation and a responsive browser probe
  explicitly separated from human usability evidence;
- content-bound native execution profiles that copy admitted datasets into the
  owning project run, mount them read-only, default-deny GPU access, and expose
  only explicitly verified NVIDIA devices with measured GPU-hour accounting;
- a three-part innovation model spanning Scientific Taste, Generation as Content,
  and bounded Tool Intelligence (see `docs/INNOVATION_MAP.md`);
- a loopback-first authenticated local UI/API that renders the closed component
  registry as a navigable evidence workspace, restricts inspection to visible
  hashed artifacts, revalidates identity-only events, and persists project-bound
  proposal, explicit controller-decision, and inspection audits. Controller
  approval grants only a bounded handoff; the UI cannot invoke a tool or mutate
  research state.

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

The project runtime also owns content-bound paper review rounds and an honest
idea-to-paper-to-review projection. `scitaste project lifecycle status` reports
eight evidence gates without inferring a percentage, while the project homepage
renders the same gates as an interactive lifecycle rail. See
[`docs/PAPER_REVIEW_LOOP.md`](docs/PAPER_REVIEW_LOOP.md).

Formal evaluation resources are prepared through provider-separated, hash-bound
no-run manifests. They distinguish method systems from Benchmark task sources,
record API or GPU ceilings, and remain unauthorized while any task, adapter,
model identity, remote inventory, human review, or explicit approval is missing.
See [`docs/EVALUATION_PRELAUNCH.md`](docs/EVALUATION_PRELAUNCH.md).

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
.venv/bin/scitaste ui serve --outputs-root outputs
```

The default bind is `127.0.0.1:8765`. The browser establishes a protected,
HttpOnly loopback session automatically, so the main interface has no credential
field. Explicit bearer credentials remain available for API clients and are
required outside loopback. The first page is a project index; each project owns
its home, research topics, ordered turns, runs, and papers. Browser actions first produce
audited `proposal_pending` receipts with execution authority `none`; explicit
approval/rejection then produces a separately audited deterministic handoff with
`state_mutation_authorized=false`. There is no tool, executor, arbitrary file,
or model endpoint. See
[`docs/GENERATIVE_UI.md`](docs/GENERATIVE_UI.md).

Run the complete offline Discovery → Evidence → Communication → Figure path in
one managed project and produce a registered Markdown/TeX/PDF paper bundle:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-integration-fixture \
  --seed 7 --output outputs
```

To start from an explicit research question and inspect the complete launch
admission before creating a project, use:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_open_question_offline_v1.yaml \
  --run-id open-question-seed-07 --seed 7 --output outputs --dry-run
```

Remove `--dry-run` to execute the admitted plan. The committed brief declares
the question, objective, exact budget, required evidence, success criteria,
constraints, and prohibited claims. A formal run copies the brief plus all four
scenario inputs into `runs/<run-id>/intake/` and reads those copies. The
deterministic catalog planner selects that complete registered bundle by domain,
budget, evidence authorization, and bounded keyword gates, and the catalog is
copied alongside it. This closes registered action selection and ownership; it
does not claim arbitrary scenario synthesis or scientific effectiveness.

A failed workflow-stage attempt can resume the same run with `--resume`.
Completed stage checkpoints are reused only after their state chain and declared
artifact hashes validate; partial stage directories are retained under that
run's `failed_attempts/` tree.

This validates end-to-end framework behavior with SciTaste's first-party
executor, including real local retrieval and one content-bound CPU proposal
that must pass deterministic static admission before no-network execution. The
run owns the proposed source, verdict, admitted source, and exact hashes. It is
not a general experiment platform or an effectiveness result. A working
Bubblewrap installation is required; pass `--backend mock` only for explicit
test compatibility. See
[`docs/FULL_WORKFLOW.md`](docs/FULL_WORKFLOW.md).
The native action evidence and current capability boundary are documented in
[`docs/NATIVE_EXECUTION.md`](docs/NATIVE_EXECUTION.md).

The short paper emitted by this acceptance workflow is deliberately classified
as an `integration-fixture`: it validates the publication machinery but is not a
research paper. Full Workflow writes a self-hashed `ASSESSMENT.json` and refuses
to register a structurally incomplete manuscript as a `research-working-draft`.
The substantive framework manuscript uses the specification title
**SciTaste: Learning Scientific Taste for Autonomous Research Decision Making**;
its tracked source is [`manuscripts/scitaste/main.md`](manuscripts/scitaste/main.md),
and now includes the required AI-use disclosure plus recommended ethics and
reproducibility statements. The ICLR 2027 venue builder binds the official
template archive and admitted assets by hash, checks citation closure and
anonymity, and compiles an 8-page main-text submission boundary. See
[`docs/COMMUNICATION_LOOP.md`](docs/COMMUNICATION_LOOP.md); passing that gate
does not mark the manuscript publication-ready or establish its headline claim.

To exercise the same full path with a network-free, project-ledger-backed
semantic advisory, use
`configs/workflows/full_offline_model_advisory_v1.yaml`. The generated
`stages/evidence/model_advisory.json` is proposal-only and proves that the
evidence `ResearchState` was unchanged.

To exercise provider-produced experiment source through the same safety
boundary without network access, use
`configs/workflows/full_offline_code_generation_v1.yaml`. The model runtime
records the typed exchange first; only an accepted response becomes a proposal,
and only separate AST admission creates the source consumed by Bubblewrap. A
double-gated GLM-5.3-Flash engineering config is also included, but remains
non-promotable while exact provider pricing is unavailable. See
[`docs/NATIVE_CODE_GENERATION.md`](docs/NATIVE_CODE_GENERATION.md).

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
.venv/bin/scitaste study status --outputs-root outputs
```

The plan is protocol-ready, but the current exact protocol has no reusable
completed cell or external review. `study status` is read-only: it scans
project-owned results, revalidates exact-protocol checkpoints and evidence, and
classifies older protocol revisions as historical rather than counting them
toward the 48-cell matrix. See
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
export SCITASTE_LOCAL_MODEL_PATH=/media/good/dxhismyson/weights/Qwen3-VL-2B-Instruct
.venv/bin/scitaste benchmark run \
  --backend local-transformers \
  --config configs/backends/local_transformers_qwen3vl2b.example.yaml \
  --condition base --condition full_scitaste \
  --record outputs/qwen3vl2b-local/recording.jsonl \
  --output outputs/qwen3vl2b-local --seed 7
```

The current example pins the complete local 2B checkpoint bytes; the older 4B
configs remain as historical study protocols. Keep one process alive
for a multi-case run so model weights load only once. The local backend is a
model-decision backend, not a replacement for a complete Phase 9 system
executor.

Phase 9 can also route the real first-party study adapter to that checkpoint
through a bounded loopback-only Chat Completions bridge. After creating a
`matched-study-pilot` project, inspect the exact one-cell command before removing
`--dry-run`:

```bash
export SCITASTE_LOCAL_MODEL_PATH=/absolute/path/to/Qwen3-VL-4B-Instruct
.venv/bin/scitaste study project-run \
  --config configs/experiments/matched_budget_local_pilot_v1.yaml \
  --launch-config configs/experiments/study_launchers_qwen3vl4b_local_v1.yaml \
  --project-id my-local-pilot --run-id diagnosis-base-seed-07 \
  --provider local-transformers \
  --model Qwen3-VL-4B-Instruct@ebb281ec \
  --run-seed 7 --evidence-scope local-single-gpu-engineering-only \
  --task diagnosis-friendly-v1 --condition autoresearchclaw \
  --max-cells 1 --dry-run
```

The launcher pins both the model configuration and every checkpoint file by
SHA-256, creates an ephemeral in-memory bearer token, binds only to loopback,
serializes GPU inference, and reports local API cost as exactly zero while
retaining token counts. The v1
pilot's 20,000-token ceiling has been shown insufficient for a full Stage 8--18
cell, so a successful dry-run or early-stage execution must not be reported as a
completed matched-system result.

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

The same native loop can be advanced as explicit, inspectable operations. Every
step reads the prior state without changing it and refuses to replace an existing
output directory:

```bash
.venv/bin/scitaste hypothesize \
  --config configs/experiments/discovery_weak.yaml \
  --output outputs/discovery-steps/01-hypothesize --seed 7
.venv/bin/scitaste probe \
  --config configs/experiments/discovery_weak.yaml \
  --state outputs/discovery-steps/01-hypothesize/research_state.json \
  --output outputs/discovery-steps/02-probe --seed 7
.venv/bin/scitaste reformulate \
  --config configs/experiments/discovery_weak.yaml \
  --state outputs/discovery-steps/02-probe/research_state.json \
  --output outputs/discovery-steps/03-reformulate --seed 7
.venv/bin/scitaste probe \
  --config configs/experiments/discovery_weak.yaml \
  --state outputs/discovery-steps/03-reformulate/research_state.json \
  --output outputs/discovery-steps/04-probe --seed 7
.venv/bin/scitaste ideate \
  --config configs/experiments/discovery_weak.yaml \
  --state outputs/discovery-steps/04-probe/research_state.json \
  --output outputs/discovery-steps/05-ideate --seed 7
.venv/bin/scitaste portfolio select \
  --config configs/experiments/discovery_weak.yaml \
  --state outputs/discovery-steps/05-ideate/research_state.json \
  --output outputs/discovery-steps/06-portfolio --seed 7
```

Each directory contains `research_state.json`, its immutable state snapshot,
`decisions.jsonl`, and `discovery_command.json`. The receipt binds the validated
scenario, input/output state identities, selected actions, executor results, and
the decision-log digest. `--dry-run` performs admission checks without creating
the destination. These offline commands use the deterministic mock executor and
do not claim open-ended model autonomy or research effectiveness.

For durable work, the same operations can advance inside one canonical project
run instead of creating caller-managed top-level directories. The project
identity must match the scenario, and each mutation requires the current project
revision:

```bash
.venv/bin/scitaste project discovery advance \
  --project-id discovery-weak-intuition \
  --run-id 2026-09-07__scitaste-native__discovery__seed-07 \
  --operation hypothesize \
  --config configs/experiments/discovery_weak.yaml \
  --seed 7 --expected-revision 0 --outputs-root outputs --dry-run

.venv/bin/scitaste project discovery verify \
  --project-id discovery-weak-intuition \
  --run-id 2026-09-07__scitaste-native__discovery__seed-07 \
  --outputs-root outputs
```

Remove `--dry-run` to execute, then use the returned `project_revision` for the
next `probe`, `reformulate`, `ideate`, or `portfolio-select` operation. The
workflow derives the predecessor state and destination from the registered run;
it does not accept an unrelated `--state` or `--output`. A failed or interrupted
operation requires `--resume`. If its complete immutable step already exists,
resume verifies and commits it without executing the command again.

The first command can optionally synthesize its intuition and falsifiable
hypothesis from the registered landscape through the same durable model-node
runtime:

```bash
.venv/bin/scitaste project discovery advance \
  --project-id scitaste-self-development \
  --run-id 2026-09-07__scitaste-native__bounded-semantic-discovery__seed-07 \
  --operation hypothesize \
  --config configs/cases/scitaste_bounded_semantic_discovery_iteration.yaml \
  --semantic-config configs/model_nodes/discovery_hypothesis_self_iteration_v1.json \
  --semantic-profile-set configs/model_nodes/discovery_semantic_profiles.example.yaml \
  --semantic-profile-id discovery-hypothesis-scripted \
  --seed 7 --expected-revision 0 --outputs-root outputs
```

To derive that semantic landscape from real project-owned retrieval, bind the
same local Knowledge config on the first command and every later command in the
run:

```bash
.venv/bin/scitaste project discovery advance \
  --project-id scitaste-self-development \
  --run-id 2026-09-07__scitaste-native__native-knowledge-discovery__seed-07 \
  --operation hypothesize \
  --config configs/cases/scitaste_semantic_reformulation_iteration.yaml \
  --native-knowledge-config configs/cases/scitaste_discovery_knowledge_v1.yaml \
  --semantic-config configs/model_nodes/discovery_hypothesis_native_retrieval_self_iteration_v1.json \
  --semantic-profile-set configs/model_nodes/discovery_semantic_profiles.example.yaml \
  --semantic-profile-id discovery-hypothesis-scripted \
  --seed 7 --expected-revision <current-revision> --outputs-root outputs
```

Dry-run computes the retrieval plan without creating a run. Execution copies
the admitted corpus beneath that run, and `project discovery verify` recomputes
the ranking and checks every native decision/record binding. The model receives
only the combined registered findings and cannot issue the search itself.

This shipped condition is an executable offline fixture, not a quality claim.
For a live backend, the profile, profile-set, backend configuration, and explicit
`--semantic-allow-live` gate must all agree. An enabled semantic node cannot
silently fall back to scenario prose: rejection or unavailable accounting fails
the pending operation before a Discovery state is published.

After a reproducible contradiction, `reformulate` can use the same opt-in flags
with `configs/model_nodes/discovery_reformulation_self_iteration_v1.json` and
profile `discovery-reformulation-scripted`. That node sees the exact predecessor
hypothesis and registered observations, must cite a parent contradiction, and
adds a second reference to `executor_context.discovery_semantics`. The
`REFORMULATE_HYPOTHESIS` decision is still made before content is applied by the
normal controller/executor path.

After the revised hypothesis has reproducible support, `ideate` can use
`configs/model_nodes/discovery_ideation_self_iteration_v1.json` and profile
`discovery-ideation-scripted`. Its typed response contains one problem and
three to eight divergent idea seeds, each with validation, cost, value, and risk
fields bound to the active hypothesis and registered observations. The node does
not rank or select ideas: `FORMULATE_PROBLEM`, `IDEATE`, and the later
`portfolio-select` decision remain in the normal controller/executor path. The
offline profile allows up to 4,096 output tokens for this larger structured
response while retaining the shared 50,000-token project ledger ceiling.

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

To package a substantive project manuscript for an exact venue template, use
`scitaste project paper build`. The initial ICLR 2027 contract requires the
official ZIP through `SCITASTE_ICLR2027_TEMPLATE`, emits both manuscript and
submission assessments, and registers the resulting paper under its owning
project only after all deterministic gates pass.

The ICLR configuration is a co-located venue bundle under
`configs/writing/venues/iclr-2027/`: `submission.yaml` owns mechanical rules,
while the content-bound `taste.yaml` and `provenance.yaml` supply advisory
review constructs and archetype-specific writing duties. Use
`--paper-archetype empirical-system` (or another declared archetype) to activate
conditional guidance. Paper builds auto-discover a sibling `taste.yaml`, persist
the exact `VENUE_TASTE_CONTEXT.json`, and keep it outside submission eligibility
and scientific-quality verdicts.

An optional whole-paper audit can be added with `--argument-contract` and
`--argument-state`. It distinguishes unsupported claims, missing registered
evidence, missing reader-facing evidence carriers, entry-point scope drift, and
content-changed artifacts. The resulting argument assessment is advisory and
does not convert mechanical submission eligibility into scientific quality.

After registration, `scitaste project paper review prepare` creates an exact
anonymous venue packet without making a model call. Structured reports,
responses, and original-reviewer verifications remain attached to that project
and paper revision. Internal models, independent models, and independent experts
have separate identities; model feedback can never satisfy the two-expert
pre-submission gate. The complete contract is documented in
[`docs/PAPER_REVIEW_LOOP.md`](docs/PAPER_REVIEW_LOOP.md).

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
under one project. Every new provider-facing attempt records write-once
`prepared`, `call_started`, and `result_published` receipts, so a pre-call crash
can continue safely, a started call with no result remains blocked, and a
durable result is never paid for twice. AutoResearchClaw remains unmodified.

SciTaste development itself is also tracked as a dogfooding case for process
usability and auditability. It is deliberately excluded from independent
effectiveness claims; see
[`docs/cases/SCITASTE_SELF_ITERATION.md`](docs/cases/SCITASTE_SELF_ITERATION.md).
The restart-safe end-of-run transaction is documented separately in
[`docs/cases/FULL_WORKFLOW_FINALIZATION_RECOVERY.md`](docs/cases/FULL_WORKFLOW_FINALIZATION_RECOVERY.md).
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
