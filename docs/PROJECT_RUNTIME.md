# Project runtime

`ProjectRuntime` makes a research project the writable ownership boundary instead
of treating `outputs/` as a collection of unrelated command directories. It
manages versioned `PROJECT.json` state, registered runs, paper bundles, current
navigation aliases, and a content-hashed `ProjectSnapshot` for catalogs and
future generated interfaces.

## Safety and concurrency

- Project IDs are lowercase kebab-case; run and paper directory IDs are one safe
  path segment. Owned locators are normalized POSIX-relative paths.
- Every mutation takes an OS file lock, requires the caller's
  `expected_revision`, increments `revision`, and atomically replaces
  `PROJECT.json`. A stale caller receives `ProjectRevisionConflictError` rather
  than silently overwriting a concurrent update.
- Project creation is prepared in a temporary sibling directory and renamed only
  after `PROJECT.json`, `README.md`, `STAGES.md`, `runs/`, `stages/`, and
  `papers/` exist.
- `stages/current`, `papers/current`, and `outputs/papers/latest` are replaceable
  only when they are symlinks. A user-owned real file or directory is never
  overwritten.
- A paper can be registered only after every declared file exists inside that
  paper bundle. Symlink escapes and path traversal are rejected.
- AutoResearchClaw remains unmodified. A registered run may designate an
  `upstream_run` stage path, while a self-development run may expose its own root.
- A first-party AutoResearchClaw bootstrap creates and verifies the Stage 1–2
  prerequisite inside a registered project run. Its immutable source receipt can
  feed a selected Stage 3 action without an unowned external run directory.
- The selected-action lifecycle copies that source into immutable inputs, runs
  against a separate working tree, binds both configuration contents, the source
  receipt, and the upstream pin, and registers only hashed verification evidence.

The manifest accepts extension fields so the existing FLOOR preacceptance and
SciTaste self-development records remain readable. Canonical fields stay strict;
unknown historical metadata is preserved during updates.

Registered run metadata may be finalized with `ProjectRuntime.update_run`. The
operation cannot change run identity and uses the same expected-revision guard;
the full workflow uses it to record completion/failure, the final-state locator,
and readable per-stage records.

Composable native Discovery is also a first-class project consumer. A new
`ProjectDiscoveryWorkflow` registers and selects one run, then reserves every
command against the current project revision before the executor is called.
Every successful command publishes an immutable step directory and advances a
self-hashed `DISCOVERY.json` head. The head binds command order, operation token,
reservation revision, input/output state identities, selected actions, state,
decision-log, and receipt hashes. Verification replays those bindings against
the canonical state decision/transition histories and rejects extra or linked
artifacts.

The pending reservation is intentionally durable. If execution fails before a
complete step is published, the run becomes `failed` and an explicit `--resume`
retries from the last verified state. If the complete step exists but the
project metadata commit was interrupted, resume reconstructs or verifies the
head and finalizes it without a second executor call. Invalid stage
preconditions and stale revisions fail before reservation and therefore create
no project mutation.

The initial `hypothesize` operation may additionally run the typed
`discovery-hypothesis` extension after project reservation. Its input is derived
from the registered landscape; source identifiers and probe types are closed
against that input. The provider receives no tool or action allowlist and its
result remains advisory until the normal TasteController independently admits
`SEARCH`, `FORM_INTUITION`, and `FORM_WORKING_HYPOTHESIS`. Known API cost is
written into both the model ledger and `ResearchState.resource_usage`.

Semantic identity is part of the pending reservation. A rejected response cannot
fall back to scenario content, and resuming with a different profile/policy/
backend identity fails. If semantic generation completed before a later executor
failure, resume validates and reuses the ledger entry without another provider
call. Project verification rehashes both the Discovery lineage and the complete
model-node ledger before trusting the state reference.

Every semantic reference is inherited by all successor states, although only
its originating manifest step introduces it. A metadata-only recovery records a
cumulative count and the last recovered command/ordinal on the run, so a
repaired head commit is visible after transient failure metadata has been
cleared.

A reproducible contradiction may opt into `discovery-reformulation`. The input
is derived from the exact predecessor state, includes the active parent and at
most forty observations, and requires a registered contradiction. A separate
binding and invocation ID are recorded for that command; the resulting reference
is appended to the state semantic history. Scenario budget admission uses prior
semantic cost plus the new response ceiling, and observed telemetry is checked
again before the proposal enters state.

After the revised active hypothesis receives reproducible support, `ideate` may
opt into `discovery-ideation`. The model sees the exact active hypothesis,
registered observations, research identity, and resource ceilings and returns
only typed problem/idea content. Each proposal must cite registered
reproducible evidence, target the active hypothesis, contain three to eight
distinct mechanisms, and keep every cost estimate within the project budget.
The normal controller/executor still owns problem formation and ideation
actions, and `portfolio-select` remains a separate deterministic operation. A
failure after semantic generation resumes from the accepted ledger entry
without a second provider call.

The initial operation may also bind `--native-knowledge-config`. Before semantic
generation, the project computes a deterministic query plan from that strict
provenance-bearing config; after reservation it copies the complete corpus and
plan into the owning run. The hypothesis node sees the scenario findings plus
the retrieved projections, but it cannot issue or alter `SEARCH`. The native
executor must reproduce the planned document IDs and scores before any step can
be committed. Every successor command must present the same config fingerprint,
so callers cannot swap evidence midway through a trajectory.

Independent verification reads only project-owned files. It rehashes the copied
Knowledge records and plan, reruns ranking, verifies the native record chain,
and reconciles each decision's pre-state, selected action, result, record hash,
and retrieval input. A completed step interrupted before metadata finalization
is committed without a second search. Partial attempt records remain truthful in
the append-only native chain while committed metadata identifies its verified
prefix/head.

The Phase 9 matched-study consumer uses `ProjectMatchedStudyRunner`. It registers
the study as one project run, exposes the run's `study/` directory through the
normal current-stage alias, and binds its protocol, plan, launcher configuration,
aggregate results, and cell checkpoints by hash. A subset execution remains
`partial`; only all planned successful cells produce `complete`. Failed and
partial runs may resume under their registered identity, while complete, running,
changed, or tampered runs fail closed. A project revision changed during a long
cell execution is not reacquired at finalization.

`substrate project bootstrap plan|execute|status` owns the prerequisite source;
`substrate project plan|execute|status` owns one selected AutoResearchClaw stage.
Both live paths are double-gated by their versioned workflow configuration and
explicit `--allow-live`. Failed attempts may resume only after immutable inputs
and registered identity revalidate; an already persisted successful bootstrap
or selected-action executor result is finalized without paying for the same call
again. Selected-action recovery independently reconstructs and checks its
controller decision, resource-charged state, summary, stage contract, and final
verification. Both paths serialize live work with an owned run lock and a
phase-v1 append-only call journal. `prepared` binds the exact request, command
specification, attempt number, configuration, pin, limits, and pre-call tree;
`call_started` is the last durable transition before crossing the executor
boundary; `result_published` binds the immutable result file, result
identity/status, and resulting full work tree. A pure prepared attempt can
continue with its original identity. A started call with no result is ambiguous
and cannot retry. A durable success is finalized without a call, while a durable
failure must independently verify before archive and the next external-attempt
number. `resume_attempt` counts recovery operations and is therefore deliberately
separate from `external_call_attempt`.

`model-node runtime plan|execute|replay|status|verify` provides the normal-project
boundary for bounded semantic advice. Each invocation binds the project revision,
typed input/context, trigger, profile, policy, backend/model, seed, and predecessor
ledger hash. Revision drift before a provider call prevents access; drift during
a call retains known usage but rejects the stale proposal. Runtime records remain
proposal-only and cannot mutate `ResearchState` or invoke tools.

The optional offline `run full` model advisory now consumes that same runtime
after evidence interpretation. Its stage bridge is content-bound to the
advisory config/profile, state snapshot, receipt, proposal, recording, and
ledger head. Resume reuses it only after runtime verification and performs no
second backend call. Live/paid full-workflow advice remains disabled until its
interruption accounting and paid-result finalization contract is implemented.

The authenticated generative workspace reads fresh `ProjectSnapshot` evidence
for its seven predefined views. Its inspection route can open only a regular,
content-addressed artifact already exposed by the active view. Proposal and
inspection records are hash-chained beneath the owning project and validated
against that project on every replay.

## CLI

Create and inspect a project:

```bash
.venv/bin/scitaste project init \
  --project-id my-research-project \
  --title "My research project" \
  --research-direction "Test a falsifiable research direction" \
  --target-domain machine-learning \
  --outputs-root outputs

.venv/bin/scitaste project status \
  --project-id my-research-project \
  --outputs-root outputs
```

The status response includes the current revision. Supply it when registering or
selecting a run:

```bash
.venv/bin/scitaste project run begin \
  --project-id my-research-project \
  --run-id 2026-09-04__local-qwen__full-scitaste__seed-07 \
  --provider local --model qwen3-vl-4b \
  --condition full_scitaste --seed 7 \
  --stage-path upstream_run --expected-revision 0 \
  --outputs-root outputs

.venv/bin/scitaste project run select \
  --project-id my-research-project \
  --run-id 2026-09-04__local-qwen__full-scitaste__seed-07 \
  --expected-revision 1 --outputs-root outputs
```

Paper generation materializes files beneath
`outputs/projects/<project-id>/papers/<paper-directory>/` first. Register its
`MANIFEST.json` contract, then explicitly select it:

```bash
.venv/bin/scitaste project paper register \
  --project-id my-research-project \
  --directory-name 2026-09-04__local-qwen__full-scitaste__stage-18 \
  --manifest /path/to/paper-manifest.json \
  --expected-revision 2 --outputs-root outputs

.venv/bin/scitaste project paper select \
  --project-id my-research-project \
  --directory-name 2026-09-04__local-qwen__full-scitaste__stage-18 \
  --expected-revision 3 --outputs-root outputs
```

All mutating commands support `--dry-run`. Dry-run validates IDs, schemas, and
the expected revision without creating or changing files.

Run selected matched-study cells inside an existing project with:

```bash
.venv/bin/scitaste study project-run \
  --config configs/experiments/matched_budget_local_pilot_v1.yaml \
  --launch-config path/to/reviewed-launchers.yaml \
  --project-id my-research-project --run-id phase9-local-pilot \
  --provider local --model Qwen3-VL-4B-Instruct \
  --condition autoresearchclaw --max-cells 1 --dry-run
```

The command derives its output directory from the project and run IDs rather
than accepting an unrelated `--output`. Resume is explicit with `--resume` and
requires an integrity-checked registered run whose status is `partial` or
`failed`.

Advance the explicit native discovery commands under the same ownership rule:

```bash
.venv/bin/scitaste project discovery advance \
  --project-id my-research-project \
  --run-id 2026-09-07__scitaste-native__discovery__seed-07 \
  --operation hypothesize --config path/to/discovery.yaml --seed 7 \
  --expected-revision 0 --outputs-root outputs

# Supply the revision returned above for each later operation.
.venv/bin/scitaste project discovery advance \
  --project-id my-research-project \
  --run-id 2026-09-07__scitaste-native__discovery__seed-07 \
  --operation probe --config path/to/discovery.yaml --seed 7 \
  --expected-revision 3 --outputs-root outputs

.venv/bin/scitaste project discovery verify \
  --project-id my-research-project \
  --run-id 2026-09-07__scitaste-native__discovery__seed-07 \
  --outputs-root outputs
```

Add `--native-knowledge-config path/to/discovery-knowledge.yaml` to the first
and every later `advance` call to keep one exact corpus binding for the run. It
can be combined with the command-compatible semantic flags; retrieval remains a
native executor action rather than a provider tool call.

The initial operation registers, selects, and finalizes the new run, so it
normally advances three project revisions. A later operation reserves and
finalizes against two revisions. Clients must consume the returned revision
rather than predicting it when other project writers may be active.

## Snapshot boundary

`ProjectSnapshot` uses project-relative locators and hashes the validated project
manifest, registered paper manifests, current selections, and warnings. It is a
read model, not an execution capability.

`ProjectSnapshotAdapter.build_binding(project_id)` reopens that authoritative
view and turns the project manifest, registered runs, current stage, paper
manifests, and declared paper files into project-relative, content-addressed UI
evidence. Missing entries, containment escapes, and nested symlinks fail closed.
Its evidence-manifest hash is intentionally distinct from
`ProjectSnapshot.snapshot_sha256`: the former includes artifact bytes displayed
by a surface, while the latter identifies runtime registry state. UI actions
still return to the deterministic controller and revision gate before mutation.

The first full lifecycle consumer is documented in
[`FULL_WORKFLOW.md`](FULL_WORKFLOW.md).
The project-owned matched-study consumer is documented in
[`MATCHED_BUDGET_STUDY.md`](MATCHED_BUDGET_STUDY.md).
