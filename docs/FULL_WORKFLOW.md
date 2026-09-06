# Project-owned full workflow

`scitaste run full` is the first-party composition of SciTaste's Phase 4--7
workflows. Its core path is deterministic and offline; an explicitly configured
evidence advisory may additionally use a bounded live model node. It is not a
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
  --paper-directory offline-full-seed-07-reviewed-draft \
  --seed 7 --output outputs
```

If the run stops during one of the four workflow stages, resume the same
registered run and publication identity with:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project \
  --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-reviewed-draft \
  --seed 7 --output outputs --resume
```

The committed default is `scitaste-native`. One first-party executor instance is
shared across Discovery, Evidence, Communication, nested reviewer evidence, and
Figure actions. It emits typed action receipts without inventing mock
observations; its Discovery `SEARCH` action now performs real local retrieval
against a content-bound project copy of the configured Knowledge Library. Its
registered Evidence experiment executes real CPU code through Bubblewrap and
independently derives metrics from the emitted replicate rows; Evidence then uses
those measured values rather than the scenario's result fixture. The remaining
deterministic workflow components perform bounded scenario operations.
`--backend mock` is an explicit compatibility/test mode. The native run validates
one registered offline experiment, but does not prove autonomous code generation,
broad experiment compatibility, model-generation quality, or effectiveness.
`--dry-run` validates the configuration and prints the planned executor and
project/run/paper identity plus Bubblewrap availability without writing files.

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

## Project layout

One execution owns this tree:

```text
outputs/projects/<project-id>/
├── PROJECT.json
├── runs/<run-id>/
│   ├── full_run_summary.json
│   ├── failed_attempts/stages/<stage>/attempt-NNN/  # when resumed
│   ├── model_nodes/{ledger,recordings,pending,attempts}/ # when opted in
│   ├── native_execution/{context,artifacts,records}/ # native action evidence
│   └── stages/
│       ├── discovery/
│       ├── evidence/model_advisory_input.json # pre-call, when opted in
│       ├── evidence/model_advisory.json  # result bridge, when opted in
│       ├── communication/
│       └── figure/
├── stages/current -> ../runs/<run-id>/stages
├── papers/<paper-directory>/
│   ├── MANIFEST.json
│   ├── main.md
│   ├── main.tex
│   ├── main.pdf              # when XeLaTeX is available
│   ├── build.json
│   └── figures/{figure.svg,figure.drawio}
├── papers/current -> <paper-directory>
└── surfaces/<run-id>-snapshot-binding.json
```

Each stage contains a self-hashed `STAGE.json`. It states the stage purpose and
records run-relative locators plus SHA-256 hashes for the input state, output
state, decision log, and required stage artifacts. Paths recorded by the
full-run summary are run-relative rather than machine-specific absolute paths.

The paper is a registered, reviewed draft with `publication_ready: false`.
Markdown-to-TeX packaging is deterministic and performs no extra model call. If
`latexmk` with XeLaTeX is installed, compilation must succeed and `main.pdf` is
registered; otherwise `build.json` records `unavailable` and the Markdown/TeX
bundle remains complete.

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
workflow configuration (including all four scenario files and the optional
advisory/profile binding). It reuses only
the contiguous completed prefix whose record, state continuity, project
identity, lifecycle position, and every declared file hash still validate. A
missing completion record means that stage is incomplete: its existing directory
is atomically moved to `failed_attempts/stages/<stage>/attempt-NNN/`, and that
stage plus every downstream stage is rerun. A malformed completion record or a
hash mismatch is treated as possible tampering and fails closed; it is not
silently archived or regenerated.

When model advice is enabled, evidence-stage reuse additionally revalidates the
self-hashed pre-call input record and advisory result, immutable predecessor and
evidence states, decision log, evidence summary, complete model-node ledger
totals/head, and exact response recording. A verified prefix therefore does not
call the backend again.

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

This recovery path deliberately covers workflow-stage interruption. If all four
stage records already validate, or a paper directory already exists, automated
finalization recovery refuses to overwrite it and requires manual inspection.
Completed runs cannot be resumed.

Native execution resume first validates its contiguous predecessor chain, every
bound Knowledge or experiment-source input, every action artifact, and the record
hash/action/result identity embedded in each reusable stage decision. Tampering
with the local Knowledge copy, registered experiment source, retrieval output, raw
process output, or derived metrics therefore blocks reuse before a stage can
advance. See `docs/NATIVE_EXECUTION.md` for the record contract.

After completion, `ProjectSnapshotAdapter` hashes the authoritative manifest,
run tree, current stage, paper manifest, and every declared paper artifact into
`surfaces/<run-id>-snapshot-binding.json`. That record can ground a trusted
Generative UI surface but has no execution authority.

## Configuration boundary

`configs/workflows/full_offline_v1.yaml` chooses the four typed scenario files,
a versioned native Knowledge seed, and one registered native experiment, and owns the canonical
project/publication identity. Scenario files contribute
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

AutoResearchClaw is not modified or invoked by this acceptance case. It remains
an optional baseline/compatibility adapter. The native path now owns local
retrieval plus one registered isolated CPU experiment and its metric extraction.
Open-web retrieval, generated-code admission, dataset/GPU profiles, and long-form
generation remain capability-parity work; they must preserve the same
ProjectRuntime ownership, state-continuity, evidence-binding, and
failure-retention contracts.
