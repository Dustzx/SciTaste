# SciTaste native execution

`scitaste-native` is SciTaste's first-party execution boundary. It is the
committed `run full` default and has no runtime dependency on AutoResearchClaw.
The optional upstream adapter remains available only through explicit baseline
and compatibility commands.

## Current capability boundary

| Capability | Current implementation | Evidence level |
|---|---|---|
| Local knowledge retrieval | Real lexical retrieval from a content-bound `KnowledgeLibrary` | implemented |
| Controller/state actions | First-party typed workflow operation plus action receipt | implemented, scenario-bound |
| Evidence/writing/figure components | Existing deterministic SciTaste components plus action receipt | implemented, scenario-bound |
| Generated code execution | No native isolated runner yet | pending |
| Open-ended metric extraction | No native handler yet | pending |
| Model-generated long-form content | Bounded proposal nodes exist, but no native generative handler has execution authority | pending |

This distinction is intentional. A workflow-component receipt is not described
as an open-ended experiment or model generation. The first real handler is local
Knowledge retrieval: it consumes the configured library, executes the query,
writes the exact ranked result, measures wall time, and returns the retrieved
document identities and scores.

## Project-owned action evidence

One Full Workflow run owns the following additional tree:

```text
runs/<run-id>/native_execution/
├── context/
│   ├── CONTEXT.json
│   └── libraries/
│       ├── library_manifest.json
│       ├── knowledge/records.jsonl
│       └── taste/records.jsonl
├── artifacts/<result-token>/retrieval.json
└── records/000001-<action-token>.json
```

`CONTEXT.json` binds the source configuration hash and every materialized library
file. Paths inside the library manifest are run-relative rather than
machine-specific absolute paths.

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
```

The workflow-config hash includes the bytes of `native_knowledge_config`, not
only its path. At run creation the source is materialized once beneath the owning
run. Resume reuses the immutable copy and refuses source or copied-record drift.

`--backend mock` remains an explicit compatibility option. It disables native
action records and real local retrieval for that run; it is not an automatic
fallback when native execution fails.

## Next capability gate

The next native executor milestone is a genuinely isolated, opt-in experiment
runner with no shell, network disabled by default, resource ceilings, exact
source/output capture, and independently parsed metrics. It must be explicitly
unavailable when the host cannot provide the isolation primitive. After that,
Evidence Workflow must consume the executor's measured result instead of a
scenario-declared result before the path can be called an open-ended native
experiment.
