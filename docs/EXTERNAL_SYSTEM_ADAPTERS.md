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

AI Scientist-v2 is the earlier adapter candidate because it exposes a Python
launch path, but its execution of LLM-written code requires a dedicated sandbox.
Sibyl follows later because its native operating model includes Claude Code,
agent teams, MCP services, and broad orchestration permissions. Neither is
required to start the four-condition local pilot, and neither receives a mock
score while unavailable.

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
