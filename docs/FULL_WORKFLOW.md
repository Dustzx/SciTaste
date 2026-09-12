# Project-owned full workflow

`scitaste run full` is the first-party composition of SciTaste's Phase 4--7
workflows. Its core path is deterministic and offline; explicitly configured
evidence advice, native-source generation, or Tool Intelligence may additionally
use bounded model nodes. It is not a
reserved CLI or four disconnected demos. Discovery creates the initial `ResearchState`;
Evidence, Communication, reviewer-driven evidence collection, and Figure
generation each load and extend that same state history.

Run the committed acceptance case with:

```bash
sudo apt-get install bubblewrap  # once on Debian/Ubuntu hosts
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project \
  --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-integration-fixture \
  --seed 7 --output outputs
```

If the run stops during one of the four workflow stages, resume the same
registered run and publication identity with:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project \
  --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-integration-fixture \
  --seed 7 --output outputs --resume
```

The committed default is `scitaste-native`. One first-party executor instance is
shared across Discovery, Evidence, Communication, nested reviewer evidence, and
Figure actions. It emits typed action receipts without inventing mock
observations; its Discovery `SEARCH` action now performs real local retrieval
against a content-bound project copy of the configured Knowledge Library. Its
admitted Evidence experiment executes real CPU code through Bubblewrap and
independently derives metrics from the emitted replicate rows; Evidence then uses
those measured values rather than the scenario's result fixture. Communication
admits that result only through a self-hashed projection that revalidates the
canonical state, interpretation, decision-bound native record, and parsed metric
artifact. Its measured writing path replaces the demo claim/evidence references
and turns the review into an explicit limitation acknowledgement rather than
executing the scenario's second prefilled experiment. The remaining deterministic
workflow components perform bounded scenario operations.
`--backend mock` is an explicit compatibility/test mode. The native run validates
one bounded offline experiment, but does not prove broad experiment compatibility,
model-generation quality, or effectiveness.
`--dry-run` validates the configuration and prints the planned executor and
project/run/paper identity plus Bubblewrap availability without writing files.

## Native Scientific Taste conditions

`native_condition_config` turns the first-party workflow into an exact treatment
runtime instead of treating `condition` as a reporting label. The committed
matrix at `configs/evaluation/native_taste_condition_matrix_v1.yaml` admits only
six profiles: Native Base, Native Knowledge, Native Taste, Native Critics, Full
SciTaste, and a mismatched-Taste placebo. It fixes utility-policy, Knowledge,
Taste-corpus relation, and Taste-critic switches for each profile. The same
controller/retriever policy is then passed through Discovery, Evidence,
Communication, and Figure rather than allowing each stage to construct a
different implicit controller.

Run the structural acceptance without contacting a provider or GPU:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_native_conditions_v1.yaml \
  --project-id native-condition-check \
  --run-id full-seed-07 --seed 7 --output outputs --dry-run
```

Dry-run reports the condition ID, role, exact component switches, matrix file
hash, semantic fingerprint, and integrity-gate invariant without creating a
project. A real offline acceptance materializes one content-bound Knowledge/Taste
library and selectively exposes it according to the chosen profile. Unknown
conditions, profile drift, missing required libraries, symlinks, oversize files,
and mid-run matrix changes fail closed.

Taste critics modify action ranking but never become hard evidence or safety
gates. Evidence obligations, writing-integrity criticism, visual criticism,
resource budgets, code admission, and sandbox isolation remain enabled for all
six profiles. Component-only arms measure sufficiency, Full--Base measures the
whole explicit Taste bundle, and Full--mismatched changes only corpus relation.
The committed workflow uses `provider: mock` and a deterministic controller: it
is an integration fixture, not evidence of model-backed effectiveness or a
formal experiment launcher.

## Open-question intake

The optional `research_brief` config field moves Full Workflow's entry boundary
from an implicit topic string to a strict research contract. The brief fixes one
question and objective, project identity, exact executable Discovery budget,
required evidence types, success criteria, constraints, and prohibited claims.
For example:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_open_question_offline_v1.yaml \
  --run-id open-question-seed-07 --seed 7 --output outputs --dry-run
```

Dry-run builds the same self-hashed `WorkflowLaunchPlan` used by execution and
reports its readiness, input hashes, authority boundary, and known limitations
without creating `outputs/`. Admission fails if brief/config identity differs,
the brief budget is not the executable Discovery budget, or any configured
Evidence/Communication requirement lies outside the brief's authorized evidence
types.

The committed config uses a content-bound `scenario_catalog`. Before mutation,
`deterministic-catalog-selection-v1` filters complete four-stage bundles by exact
domain, executable budget, authorized evidence types, and question/objective
keyword matches, then ranks ties by hit count and stable bundle ID. Dry-run
reports the selected and eligible bundle IDs. Directly configured scenarios
remain supported through `deterministic-registered-inputs-v1` for pinned
experiments.

On formal execution, the plan, exact brief, catalog, and selected scenario bytes
are published under the owning run before stage work begins. All four stages then
load the run-owned copies. Source drift between inspection and copy, copy drift,
plan drift, and resume-time tampering fail closed. A partially published intake
can be completed on explicit resume only when every existing byte still matches
its registered hash. Catalog selection admits only registered actions; it does
not generate arbitrary Discovery, Evidence, Communication, or Figure code. A
`ready` plan is an execution admission result, not an effectiveness or
publication claim.

An opt-in offline acceptance config also exercises a bounded semantic node in
the real evidence-stage path:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_model_advisory_v1.yaml \
  --project-id my-advisory-project \
  --run-id offline-advisory-seed-07 \
  --seed 7 --output outputs
```

After deterministic evidence interpretation, the hook projects an immutable
slice of the actual `ResearchState` and invokes `interpretation-threat` through
the normal project-owned model-node runtime. The committed backend is scripted,
costs zero, has no network or tool path, and exists to validate integration—not
model quality. Its accepted output remains a proposal: it cannot update claims,
select an action, execute a tool, or mutate state. The record proves this by
binding identical input/output state hashes.

Tool Intelligence is a separate optional post-interpretation hook:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_tool_intelligence_v1.yaml \
  --run-id offline-tool-intelligence-seed-07 \
  --seed 7 --output outputs
```

A deterministic claim-status policy first decides whether a registered hotspot
exists. If it does, the run publishes an immutable state/evidence request,
invokes the normal typed model ledger, admits at most one dependency-free tool
step, issues a single-use lease, and executes the registered read-only handler.
The committed case inspects one exact project-owned evidence record. The
observation and final decision remain `advisory_only`; they are neither canonical
evidence nor authority to advance `ResearchState`. Resume verifies and reuses the
model and tool ledgers without repeating a completed call.

The live engineering condition is separately configured and double-gated:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_zhipu_model_advisory_probe_v1.yaml \
  --run-id glm53-advisory-probe-seed-07 \
  --seed 7 --output outputs --allow-live-model-nodes
```

Both the content-bound advisory/profile/backend configuration and the caller
must enable live execution. Omitting `--allow-live-model-nodes` fails before a
project is created. The committed GLM-5.3-Flash condition has no verified price,
so it is an engineering probe: usage and the raw response are retained, cost is
unknown, and the proposal is deterministically rejected. It cannot support an
effectiveness claim.

Native experiment source has a separate optional generation hook:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_code_generation_v1.yaml \
  --project-id my-code-generation-project \
  --run-id generated-code-seed-07 \
  --seed 7 --output outputs
```

The scripted condition traverses the real model-node ledger, source extraction,
static admission, Bubblewrap experiment, measured-evidence projection, and paper
publication path without network access. The model controls only source,
rationale, and assumptions; the project controls experiment identity, metrics,
imports, limits, backend, and budget. The live engineering configuration uses
`full_zhipu_glm53_flash_code_generation_probe_v1.yaml`, requires
`--allow-live-model-nodes`, and is deliberately non-promotable until an auditable
price for that exact model is available. See `docs/NATIVE_CODE_GENERATION.md`.

An additional offline acceptance config exercises a real project-owned dataset
mount:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_dataset_v1.yaml \
  --run-id dataset-seed-07 --seed 7 --output outputs
```

The workflow verifies the registered dataset hash, copies the exact bytes into
`native_execution/context/resources/`, and mounts only that copy read-only at
the derived `/datasets/<dataset-id>` path. `--dry-run` validates the source data
and optional GPU identity without materializing a project. GPU access remains
disabled unless a separate profile explicitly admits device indices and a
GPU-hour ceiling. See `docs/NATIVE_EXECUTION.md`.

## Project layout

One execution owns this tree:

```text
outputs/projects/<project-id>/
├── PROJECT.json
├── runs/<run-id>/
│   ├── full_run_summary.json
│   ├── intake/{BRIEF.yaml,PLAN.json,SCENARIO_CATALOG.yaml}
│   ├── intake/scenarios/{discovery,evidence,communication,figure}.yaml
│   ├── finalization/PLAN.json          # write-once stage/paper input binding
│   ├── failed_attempts/stages/<stage>/attempt-NNN/  # when resumed
│   ├── failed_attempts/finalization/{paper,summary}/attempt-NNN/
│   ├── model_nodes/{ledger,recordings,pending,attempts}/ # when opted in
│   ├── native_execution/{context,artifacts,records}/ # native action evidence
│   │   ├── context/code_generation/ # generated-source evidence when opted in
│   │   ├── context/code/            # deterministic admission and admitted source
│   │   └── context/resources/       # profile plus copied datasets when opted in
│   └── stages/
│       ├── discovery/
│       ├── evidence/model_advisory_input.json # pre-call, when opted in
│       ├── evidence/model_advisory.json  # result bridge, when opted in
│       ├── communication/{evidence_projection.json,paper.md,paper.publication.md}
│       └── figure/
├── stages/current -> ../runs/<run-id>/stages
├── papers/<paper-directory>/
│   ├── MANIFEST.json
│   ├── main.md
│   ├── main.tex
│   ├── main.pdf              # when XeLaTeX is available
│   ├── build.json
│   ├── ASSESSMENT.json
│   └── figures/{figure.svg,figure.drawio}
├── papers/current -> <paper-directory>
└── surfaces/<run-id>-snapshot-binding.json
```

Each stage contains a self-hashed `STAGE.json`. It states the stage purpose and
records run-relative locators plus SHA-256 hashes for the input state, output
state, decision log, and required stage artifacts. Paths recorded by the
full-run summary are run-relative rather than machine-specific absolute paths.

The default paper is a registered `integration-fixture` with
`publication_ready: false`; it proves that evidence projection, reader-facing
sanitization, Markdown-to-TeX conversion, PDF compilation, figures, manifests,
and project registration compose correctly. It is not a reviewed research
manuscript and must not be presented as one.

`communication/paper.md` is the audit view and retains machine-readable
claim/evidence trace markers. `paper.publication.md` is the deterministic
reader-facing view: it removes internal trace and obligation identifiers but
cannot add prose, measurements, or claims. The registered `main.md`, `main.tex`,
and optional PDF are built from that reader-facing view. Markdown-to-TeX
packaging is deterministic and performs no extra model call. If
`latexmk` with XeLaTeX is installed, compilation must succeed and `main.pdf` is
registered; otherwise `build.json` records `unavailable` and the Markdown/TeX
bundle remains complete.

Every bundle includes `ASSESSMENT.json`, a self-hashed deterministic role and
completeness record. A configuration may request `research-working-draft`, but
publication then fails closed unless the manuscript has at least 2,500 counted
words, all required Abstract/Introduction/Method/Evaluation/Results/Limitations/
Conclusion sections, and no known placeholder marker. This is a minimum
classification gate, not a scientific-quality or peer-review judgment. The
substantive SciTaste framework manuscript is maintained separately at
`manuscripts/scitaste/main.md` and registered under the `scitaste-self-development`
project when its source and compiled bundle pass acceptance.

## Revision and failure behavior

The workflow creates the project when it does not exist, otherwise it requires
the existing research identity to match. Every run ID must be new. Repeated
iterations in one project should use a new `--run-id` and
`--paper-directory`; historical runs and paper versions are never overwritten.

Project mutations use the same optimistic revisions and file locks as manual
project commands. A successful run is selected, marked complete, linked to its
final state and stage records, and owns the selected paper. If a later phase
fails, completed stage artifacts remain in place and the registered run is
marked `failed` with the exception type and bounded message for diagnosis.

`--resume` accepts only a previously registered failed run with the same
provider, model, condition, seed, evidence scope, stage path, and content-hashed
workflow configuration (including the optional research brief, scenario catalog,
all four scenario files, and optional advisory, Tool Intelligence, or
source-generation profile bindings). It reuses only
the contiguous completed prefix whose record, state continuity, project
identity, lifecycle position, and every declared file hash still validate. A
missing completion record means that stage is incomplete: its existing directory
is atomically moved to `failed_attempts/stages/<stage>/attempt-NNN/`, and that
stage plus every downstream stage is rerun. A malformed completion record or a
hash mismatch is treated as possible tampering and fails closed; it is not
silently archived or regenerated.

When model advice or Tool Intelligence is enabled, evidence-stage reuse
additionally revalidates the self-hashed pre-call input record and advisory
result, immutable predecessor and evidence states, decision log, evidence
summary, complete model-node ledger totals/head, exact response recording,
and—where applicable—the controlled tool binding, lease, observation, and
decision ledger. A verified prefix therefore does not call the backend or tool
again. Multiple Full Workflow model-node hooks share one typed ledger;
historical receipts bind the exact prefix visible when they were issued, while
final verification covers the complete chain.

The input record is published before provider access and cannot be overwritten.
If a live response was durably recorded but the process stopped before ledger
publication, `--resume --allow-live-model-nodes` reconstructs the exact original
request, consumes that recorded response without provider access, and records
its original token/cost telemetry once. Because the project revision advanced
while failure/recovery metadata was written, the recovered proposal is
conservatively rejected as stale. If the ledger was already published, resume
returns that exact entry without another call. If a live call may have started
but no complete response exists, its cost remains unknown and resume refuses to
repeat it. An invalid input checkpoint fails closed instead of being archived.

Finalization has a separate write-once, self-hashed plan binding all four stage
records, the final state, publication manuscript, editable figures, workflow
configuration, and intended paper identity. If all four stages already validate,
`--resume` continues finalization without executing a stage again. An incomplete,
unregistered paper directory is moved intact beneath
`failed_attempts/finalization/paper/` before deterministic rebuilding. A
registered paper is reused only when every declared file hash, assessment,
source, figure, and manifest field still matches the plan; drift fails closed.
Likewise, a summary left before an interrupted completion-metadata update is
archived before a fresh revision-bound summary is published.

If the command stops after the run becomes complete but before its generated UI
snapshot binding is published, the same `--resume` command verifies the complete
run, plan, summary, paper, and project identity and writes only the missing
binding. It performs no model, retrieval, experiment, writing, or figure action.
An existing binding with different content is treated as tampering rather than
overwritten.

Native execution resume first validates its contiguous predecessor chain, every
bound Knowledge or experiment-source input, every generation/ledger/admission
binding, every action artifact, and the record hash/action/result identity
embedded in each reusable stage decision. Tampering with the local Knowledge
copy, generated or registered source, retrieval output, raw process output, or
derived metrics therefore blocks reuse before a stage can advance. See
`docs/NATIVE_EXECUTION.md` for the record contract.

The Communication stage independently repeats the relevant binding checks before
writing: exactly one successful registered experiment must resolve to one
interpretation review, one supporting evidence item, one supported claim, and one
hashed metrics artifact whose replicate rows reproduce the reported mean and
population dispersion. `evidence_projection.json` and both paper views are part
of the stage artifact manifest, so deleting or changing any of them blocks resume.

After completion, `ProjectSnapshotAdapter` hashes the authoritative manifest,
run tree, current stage, paper manifest, and every declared paper artifact into
`surfaces/<run-id>-snapshot-binding.json`. That record can ground a trusted
Generative UI surface but has no execution authority.

## Configuration boundary

`configs/workflows/full_offline_v1.yaml` chooses the four typed scenario files,
a versioned native Knowledge seed, and one typed native code proposal, and owns
the canonical project/publication identity. The proposal is inspected without
mutation during `--dry-run`; an actual run durably publishes its policy,
proposal, verdict, proposed source, and accepted source before constructing the
Bubblewrap runner. Scenario files contribute
phase-specific claims, evidence, narrative contracts, review feedback, and
figure contracts; their standalone demo project IDs are replaced and revalidated
against the full-workflow project. This permits reusable phase fixtures without
splitting the resulting project state.

`configs/workflows/full_offline_model_advisory_v1.yaml` adds the content-bound
`full_model_advisory_scripted_v1.yaml`. The live probe instead uses
`full_model_advisory_zhipu_glm53_unpriced_v1.yaml` and its content-addressed live
profile set. Loading rejects embedded credentials, unrestricted code generation,
tools, non-zero scripted cost, inconsistent live gates, and policy/profile/
backend identity drift. `--dry-run` reports the backend mode, both authorization
gates, and whether a real execution would contact a provider without creating a
project or accessing the network.

`configs/workflows/full_offline_tool_intelligence_v1.yaml` adds the
content-bound `full_tool_intelligence_scripted_v1.yaml`. Its controlled profile
names exact tools and evidence IDs; loading and dry-run reject permission,
backend, profile, trigger, budget, or authority drift. A profile valid for one
evidence identity is not silently generalized to another workflow result.

`configs/workflows/full_offline_code_generation_v1.yaml` replaces the registered
source proposal with a content-bound generation configuration and 8,192-token
provider envelope. Dry-run reports the generation/provider/admission/isolation
plan without creating a project. Execution checkpoints its complete trusted
brief before any backend access; only a cost-admitted ledger result is projected
into a model-attributed proposal, and that proposal still requires the same
deterministic admission and isolated runner. The GLM-5.3-Flash variant reads only
the `ZAI_API_KEY` environment variable and never stores credentials in YAML.

AutoResearchClaw is not modified or invoked by this acceptance case. It remains
an optional baseline/compatibility adapter. The native path now owns local
retrieval plus one admitted isolated CPU experiment and its metric extraction.
The same experiment can now originate from a first-party bounded provider-backed
proposer while remaining behind independent admission and isolation. Explicit
dataset and NVIDIA device profiles now provide a default-deny resource boundary.
Open-web retrieval, iterative code repair, portable package/model environment
construction, cross-host CUDA reproduction, and long-form generation remain
capability-parity work. One content-bound local Qwen3-VL-2B text/vision workload
has passed on the registered RTX 3090, but it is execution-boundary evidence and
not a model-quality result; subsequent work must preserve the same
ProjectRuntime ownership, state-continuity, evidence-binding, and
failure-retention contracts.
