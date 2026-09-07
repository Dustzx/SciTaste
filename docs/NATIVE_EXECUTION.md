# SciTaste native execution

`scitaste-native` is SciTaste's first-party execution boundary. It is the
committed `run full` default and has no runtime dependency on AutoResearchClaw.
The optional upstream adapter remains available only through explicit baseline
and compatibility commands.

## Current capability boundary

| Capability | Current implementation | Evidence level |
|---|---|---|
| Local knowledge retrieval | Real lexical retrieval from a content-bound `KnowledgeLibrary` | implemented |
| Admitted Python experiment | Typed proposal, deterministic static admission, then Bubblewrap-isolated execution of one content-bound source | implemented, CPU/offline |
| Replicate metric extraction | Strict final machine record; means, dispersion, stability, and relation independently derived | implemented |
| Controller/state actions | First-party typed workflow operation plus action receipt | implemented, scenario-bound |
| Evidence/writing/figure components | Existing deterministic SciTaste components plus action receipt | implemented, scenario-bound |
| Model-attributed code proposal | Provider/model plus request/response hashes can be registered, but this boundary does not perform or verify the provider call | contract implemented |
| Provider-backed code generation | No first-party generator yet produces and binds the request, raw response, and extracted source | pending |
| Model-generated long-form content | Bounded proposal nodes exist, but no native generative handler has execution authority | pending |

This distinction is intentional. A workflow-component receipt is not described
as an open-ended experiment or model generation. The first real handler is local
Knowledge retrieval: it consumes the configured library, executes the query,
writes the exact ranked result, measures wall time, and returns the retrieved
document identities and scores. The registered experiment handler executes
exact source bytes and returns independently derived measurements; it never
copies the scenario's declared metric into the result.

## Project-owned action evidence

One Full Workflow run owns the following additional tree:

```text
runs/<run-id>/native_execution/
├── context/
│   ├── CONTEXT.json
│   ├── libraries/
│       ├── library_manifest.json
│       ├── knowledge/records.jsonl
│       └── taste/records.jsonl
│   ├── experiment/{EXPERIMENT.json,experiment.py} # legacy registered path
│   └── code/
│       ├── CODE.json
│       ├── {POLICY,PROPOSAL,ADMISSION}.json
│       ├── proposed.py
│       └── admitted/experiment.py                 # accepted proposals only
├── artifacts/<result-token>/
│   ├── retrieval.json              # retrieval actions
│   └── {stdout.txt,stderr.txt,metrics.json,execution.json} # experiment action
└── records/000001-<action-token>.json
```

`CONTEXT.json` binds the source configuration hash and every materialized library
file. Paths inside the library manifest are run-relative rather than
machine-specific absolute paths.

`experiment/EXPERIMENT.json` binds the external definition and source hashes,
the run-local source locator, primary metric, direction, support threshold, and
limits. Resume rejects drift in either the registered external source or its
run-local copy.

The default Full Workflow now uses `code/` instead. `PROPOSAL.json` binds exact
source bytes, experiment identity, expected metrics, runtime limits, rationale,
producer provenance, and a proposal-only authority label. `POLICY.json` records
the platform-bounded import allowlist and syntax/size ceilings.
`ADMISSION.json` records the AST statistics, imports, every deterministic
violation, and the accepted/rejected verdict. `CODE.json` binds both semantic
record hashes and exact serialized-file hashes. Only an accepted proposal gets
an `admitted/experiment.py`, and that file must be byte-identical to
`proposed.py`. Rejected proposals retain all four evidence records and the
proposed bytes, fail the run before any stage executes, and never create an
executable source.

Admission rejects source/config symlinks, invalid UTF-8 or syntax, oversized
source/AST/literals, imports outside a non-expandable platform ceiling, private
imports/attributes, dynamic evaluation and file-opening builtins, dunder access,
async/class/yield/global syntax, a missing measurement marker, and missing
declared metric literals. This static analysis is deterministic defense in
depth, not a security sandbox or a proof of scientific validity; Bubblewrap and
strict runtime measurement parsing remain mandatory after acceptance.
Accepted proposals construct native experiment definition `1.1`, which requires
the runtime metric set to match `expected_metrics` exactly; a source cannot pass
admission by mentioning a metric and then omit or add it in its output.

Every native action record contains:

- a contiguous sequence number and predecessor-record hash;
- project ID, state revision, and complete state hash before execution;
- the selected typed action and its hash;
- capability and exact `ExecutionResult`;
- hashes of every input and output artifact;
- a self-hash over the complete record.

The decision log stores the action-record locator and semantic record hash.
Stage resume verifies the record chain, current input/output bytes, and the exact
action/result identity bound by each reused decision. Missing, reordered,
cross-project, symlinked, or modified evidence fails closed.

## Composable Discovery Knowledge context

An opted-in project Discovery run owns a narrower context alongside its normal
immutable command steps:

```text
runs/<run-id>/native_execution/
├── context/
│   ├── DISCOVERY_KNOWLEDGE.json
│   ├── discovery_knowledge_plan.json
│   └── libraries/knowledge/records.jsonl
├── artifacts/<result-token>/retrieval.json
└── records/000001-<action-token>.json
```

The source config is strict, bounded, provenance-bearing, and hashed into the
run binding. Preview ranks the in-memory admitted records but writes nothing.
After project reservation, the complete corpus and deterministic plan are
materialized once. The semantic hypothesis input may include the retrieved
landscape projections, but the provider receives no tool authority; the normal
controller selects `SEARCH` and the native executor must return exactly the
planned identifiers and scores.

`project discovery verify` rehashes the context, reruns the ranker from the
copied records, validates the complete native record chain, and reconciles every
decision with its pre-state, selected action, result, record locator, and hash.
The same knowledge fingerprint is required on all successor commands. Exact
completed-step recovery reuses the published step and cannot issue a second
retrieval.

## Full Workflow configuration

The committed Full Workflow configurations declare:

```yaml
execution_backend: scitaste-native
native_knowledge_config: ../taste/library_seed_v1.yaml
native_code_proposal_config: ../experiments/native_code_proposal_support_v1.yaml
```

The workflow-config hash includes the bytes of `native_knowledge_config`, the
native code proposal, exact source, policy, proposal, and admission records—not
only their paths. At run creation each source is materialized once beneath the
owning run. Resume reuses the immutable copies and refuses source or
copied-record drift. The legacy `native_experiment_config` remains readable but
is mutually exclusive with `native_code_proposal_config`.

## Isolation and measurement contract

The current native runner accepts one registered Python file and invokes it as a
fixed argument vector; source-controlled text is never passed through a shell.
Bubblewrap unshares user, PID, mount,
IPC, UTS, cgroup, and network namespaces. The process runs as UID/GID 65534 with
only read-only system libraries and the registered source mounted. Host project
paths and GPU devices are absent. `/work` and `/tmp` are read-only, and CPU,
address-space, output-file, file-descriptor, process-count, core-dump, and wall
time ceilings are applied.

Read-only system userland remains mounted so Python can start; registered source
could invoke an installed binary, but that child inherits the same namespaces,
identity, filesystem restrictions, output ceilings, and process limits. Blocking
particular syscalls or binaries belongs to the later code-admission/seccomp gate.

Stdout and stderr are retained verbatim within configured byte limits. Success
requires zero exit status and exactly one final
`SCITASTE_MEASUREMENTS_JSON=<json>` line. That record must contain 1–100 uniquely
named replicates with identical, finite metric sets. The runner computes metric
means, primary-metric population dispersion, threshold agreement, reproducibility,
and support/contradiction itself and stores both raw replicate rows and derived
values in `metrics.json`. A prefilled aggregate without replicate rows is
inadmissible.

Evidence Workflow recognizes this result basis explicitly. It replaces the
scenario fixture's result ID, metrics, cost, observation, relation, stability,
and uncertainty with the measured values before interpretation. Other
scenario-bound workflow components remain clearly labeled as such.
Communication now renders the measured metric only through a self-hashed
evidence projection that revalidates canonical state, interpretation, the native
record, and the parsed replicate artifact. The audit draft retains internal trace
markers, while the registered project paper uses a clean reader-facing view. Rich
open-ended scientific writing remains pending; this closes the earlier
cross-stage truthfulness gap for registered native measurements.

If Bubblewrap is missing or its namespace probe fails, the configured experiment
returns `FAILED` with an execution artifact; SciTaste does not run it directly or
fall back to Mock. The committed Full Workflow therefore requires a working
Bubblewrap installation. `run full --dry-run` reports that preflight state.

`--backend mock` remains an explicit compatibility option. It disables native
action records and real local retrieval for that run; it is not an automatic
fallback when native execution fails.

## Next capability gate

This closes the typed proposal/static-admission gate for offline CPU source, not
autonomous code generation or broad scientific execution. The next milestone is
a first-party provider-backed proposer that durably binds its exact request, raw
response, extracted source, telemetry, and retry state before using this gate;
the model still must not receive shell, filesystem, controller, or execution
authority. Dataset mounts, package environments, GPU access, and multi-process
workloads need separate explicit profiles and resource accounting; none is
silently enabled by the current gate.
