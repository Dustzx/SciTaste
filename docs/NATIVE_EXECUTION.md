# SciTaste native execution

`scitaste-native` is SciTaste's first-party execution boundary. It is the
committed `run full` default and has no runtime dependency on AutoResearchClaw.
The optional upstream adapter remains available only through explicit baseline
and compatibility commands.

## Current capability boundary

| Capability | Current implementation | Evidence level |
|---|---|---|
| Local knowledge retrieval | Real lexical retrieval from a content-bound `KnowledgeLibrary` | implemented |
| Registered Python experiment | Bubblewrap-isolated execution of one content-bound source with hard limits | implemented, CPU/offline |
| Replicate metric extraction | Strict final machine record; means, dispersion, stability, and relation independently derived | implemented |
| Controller/state actions | First-party typed workflow operation plus action receipt | implemented, scenario-bound |
| Evidence/writing/figure components | Existing deterministic SciTaste components plus action receipt | implemented, scenario-bound |
| Generated code execution | The isolation gate exists, but no model-generated source is admitted yet | pending |
| Model-generated long-form content | Bounded proposal nodes exist, but no native generative handler has execution authority | pending |

This distinction is intentional. A workflow-component receipt is not described
as an open-ended experiment or model generation. The first real handler is local
Knowledge retrieval consumes the configured library, executes the query, writes
the exact ranked result, measures wall time, and returns the retrieved document
identities and scores. The registered experiment handler executes exact source
bytes and returns independently derived measurements; it never copies the
scenario's declared metric into the result.

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
│   └── experiment/{EXPERIMENT.json,experiment.py}
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

## Full Workflow configuration

The committed Full Workflow configurations declare:

```yaml
execution_backend: scitaste-native
native_knowledge_config: ../taste/library_seed_v1.yaml
native_experiment_config: ../experiments/native_evidence_support_v1.yaml
```

The workflow-config hash includes the bytes of `native_knowledge_config`, the
native experiment definition, and the exact experiment source—not only their
paths. At run creation each source is materialized once beneath the owning run.
Resume reuses the immutable copies and refuses source or copied-record drift.

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

This closes the registered CPU experiment gate, not autonomous code generation
or broad scientific execution. The next milestone is a typed code-proposal and
static-admission boundary that can send approved source into this runner without
granting the model shell or filesystem authority. Dataset mounts, package
environments, GPU access, and multi-process workloads need separate explicit
profiles and resource accounting; none is silently enabled by the current gate.
