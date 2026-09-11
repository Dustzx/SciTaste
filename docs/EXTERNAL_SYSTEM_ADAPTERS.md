# External system adapters

An external system is a complete autonomous-research implementation used as a
comparison condition, not a model API, retrieval source, Python dependency, or
code copied into SciTaste. Sibyl and AI Scientist-v2 fall into this category.

The local Qwen bridge is therefore not an external-system adapter. It is a
SciTaste-owned, loopback-only model transport that lets the existing first-party
study adapter call one content-bound local checkpoint through the narrow Chat
Completions subset it already consumes. It does not change AutoResearchClaw,
grant network access, or turn a local model response into a system outcome.

## Boundary

SciTaste owns the comparison protocol and supplies every system with the same:

- research task and seed;
- base-model declaration and revision;
- frozen search policy/snapshot;
- codebase declaration;
- GPU, experiment, wall-time, API-cost, search-query, and token ceilings;
- isolated output directory and standard result path.

An adapter translates this request into the external system's native CLI/config,
runs the pinned upstream version in its own environment, and projects native
outputs back into `LauncherResult`. The adapter cannot choose a more favorable
task, silently change models, omit failed attempts, or synthesize missing
telemetry. SciTaste hashes the returned artifact files itself.

```text
StudyCell request
      ↓
thin version-pinned adapter
      ↓
external system process/container
      ↓
native logs, experiments, manuscript
      ↓
LauncherResult + declared artifact paths
      ↓
SciTaste validation, hashing, audit, blind review
```

## Admission gate

Before an external condition can change from `disabled` to `enabled`, it needs:

1. official repository and immutable commit/tag;
2. recorded license obligations and acceptable use;
3. isolated Python/container environment and controlled network/filesystem scope;
4. a deterministic task/model/search mapping where the upstream permits it;
5. complete six-dimensional resource counters;
6. native artifact mapping without content fabrication;
7. timeout, failure, resume, and budget-overrun acceptance tests.

These requirements are now executable admission policy rather than a checklist
alone. The tracked corpus
[`research/data/autoresearch_evaluation_resources_v2.yaml`](research/data/autoresearch_evaluation_resources_v2.yaml)
binds official repositories, exact commits, code/data license evidence, native
interfaces, requirements, and unresolved gates. `evaluate_resource_feasibility`
derives readiness independently for citation, code audit, benchmark-task use,
and comparison-system use.

| Resource | Exact pin | Current admitted use | Formal blocker summary |
|---|---|---|---|
| MLR-Bench | `f728d571…` | reference, code audit | source-disjoint executable subset, task assets, and upstream licenses are not frozen |
| EXP-Bench | `db1b1f56…` | reference, code audit | per-task environments, data/checkpoints, licenses, and executable subset are not qualified |
| MLR-Agent | `f728d571…` | reference, code audit | unchanged-core adapter, matched task/model mapping, sandbox, telemetry, artifacts, and recovery tests are absent |
| AI Scientist-v2 | `96bd5161…` | reference, code audit | custom-license acceptance/disclosure, sandbox, mappings, telemetry, artifacts, and recovery tests are absent |
| AutoResearchClaw | `12d3fd80…` (`v0.5.0`) | reference, code audit | external-benchmark task/model equivalence, target sandbox qualification, and matched telemetry remain open |

Thus “present in the repository” and “formally comparable” are different
states. In particular, the existing AutoResearchClaw wrapper and artifact
mapping do not waive the remaining matched-comparison gates, and an unavailable
system is never replaced by a mock outcome.

AI Scientist-v2 is the earlier adapter candidate because it exposes a Python
launch path, but its execution of LLM-written code requires a dedicated sandbox.
Sibyl follows later because its native operating model includes Claude Code,
agent teams, MCP services, and broad orchestration permissions. Neither is
required to start the four-condition local pilot, and neither receives a mock
score while unavailable.

## Static adapter preflight

The adapter-preflight contract makes that distinction machine-checkable without
starting an external system:

```bash
.venv/bin/scitaste evaluation adapter-preflight \
  --manifest configs/evaluation/adapters/autoresearchclaw_mlr_v1.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v2.yaml \
  --source-root .
```

It verifies the corpus identity, local upstream commit and cleanliness,
first-party adapter bytes, and every content-addressed requirement artifact. A
report may propose verified requirement evidence for a future corpus revision;
its schema always fixes `authorizes_execution=false` and
`no_execution_performed=true`.

## Task-package qualification

Task metadata is not executable input. After a project owner separately
approves acquisition, every already-present benchmark package must pass a
second, read-only boundary:

```bash
.venv/bin/scitaste evaluation task-package \
  --manifest /path/to/task-package.yaml \
  --selection docs/research/data/mlr_bench_official_ten_candidate_v2.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v6.yaml \
  --source-root .
```

The manifest binds exactly one selected task, its complete local inventory, the
selection and upstream pins, owner approval and acquisition receipt, and six
content-addressed qualifications: input license, acquisition, held-out audit,
executable signal, review endpoint, and runtime policy. The inspector rejects
unregistered files, symlinks, path escape, byte drift, and cross-selection task
substitution. A clean report can propose a resource-ledger revision; it becomes
prelaunch-bindable only after the selection and resource corpus carry the same
verified evidence. It always reports `authorizes_download=false` and
`authorizes_execution=false`.

## Static translation feasibility

Before cloning a candidate system or writing a runtime wrapper, SciTaste can
inspect whether the selected task/model envelope is representable by its native
interface:

```bash
.venv/bin/scitaste evaluation adapter-contract \
  --manifest configs/evaluation/adapters/mlr_agent_deepseek_v41_contract_v1.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v6.yaml \
  --source-root .
```

This contract binds the exact external-system commit, shell-free native argv
shape, task and model translation semantics, allowed credentials, six adapter
requirements, official pinned sources, and a local audit hash. It is earlier
than `adapter-preflight`: even a fully verified translation must still pass a
clean local upstream checkout, first-party adapter hash, sandbox, telemetry,
artifact, and failure/resume acceptance tests.

The current MLR-Agent and Agent Laboratory contracts deliberately fail this
earlier gate for the DeepSeek V4.1 proposal. MLR-Agent lists a different
OpenRouter DeepSeek V3 model and delegates coding to another agent family;
Agent Laboratory documents `deepseek-chat`/DeepSeek V3 and accepts task meaning
through a research-topic/YAML interface rather than exact starting bytes. Both
also need matched sandbox and telemetry qualification. These findings are
recorded in
[`EXTERNAL_ADAPTER_COMPATIBILITY_AUDIT_V1.md`](research/protocols/EXTERNAL_ADAPTER_COMPATIBILITY_AUDIT_V1.md).
They block this exact matched-backbone design; they do not score either external
system and do not justify a pseudo-implementation.

The current AutoResearchClaw static report observes the exact clean
`12d3fd80…` upstream and verifies the existing artifact mapping and
failure/resume evidence. It remains **not ready for a matched adapter** because
MLR-Bench task mapping, official DeepSeek V4.1 Flash model mapping,
selected-task sandboxing, and matched telemetry acceptance tests are still
pending. This is the intended
state: retaining the unchanged upstream is useful evidence, but it is not a
substitute for the four task-specific qualifications.

Official sources:

- [Sibyl Research System](https://github.com/Sibyl-Research-Team/AutoResearch-SibylSystem)
- [AI Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2)

## Launcher contract

`study run` invokes commands from a separately reviewed launcher configuration.
Commands are argv arrays and are never interpreted by a shell. Supported
placeholders are `{cell_id}`, `{condition}`, `{seed}`, `{cell_dir}`,
`{cell_request}`, `{cell_result}`, and `{task_asset}`.

Only baseline runtime variables and names explicitly listed in
`pass_environment` enter the child process. This prevents unrelated credentials
from being inherited accidentally. The adapter reads the request path from
`SCITASTE_STUDY_CELL_REQUEST` and writes its result to
`SCITASTE_STUDY_CELL_RESULT`.

A per-cell working directory is an audit boundary, not an operating-system
sandbox. Systems that execute generated code must still run inside a dedicated
container or equivalent restricted environment; the configured command should
enter that sandbox rather than launch unsafe code directly on the host.

Successful results must provide all adapter-owned counters, a consistent
`StudyOutcome`, and at least one regular artifact file inside the cell directory.
Runner-owned wall and allocated-GPU time replace any self-reported values.
