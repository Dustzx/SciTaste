# Agent Laboratory best-native adapter audit v1

Audit date: 2026-09-12

Scope: static inspection of the official Agent Laboratory source at commit
`d9017d90e329112d2a80b7712f37ee9094d2cd27`. This record authorizes no
checkout, installation, provider call, data acquisition, generated-code
execution, or experiment.

## Native configuration

The pinned accepted system documents OpenAI `o1`, `o1-preview`, `o1-mini`,
`gpt-4o`, and `o3-mini`, plus the legacy DeepSeek `deepseek-chat` backend. Its
entrypoint defaults the main and literature-review backends to `o3-mini` and
propagates a phase-to-model mapping to the agents, experiment solver, and paper
solver. OpenAI's current model page resolves that alias to snapshot
`o3-mini-2025-01-31`; the deprecation schedule currently sets shutdown for
2026-10-23. It is therefore the reproducible published-code candidate for this
time-bounded prepilot, but a later formal proposal must recheck availability and
must never silently migrate the model. The project credential remains absent.

Official model evidence:

- <https://developers.openai.com/api/docs/models/o3-mini>
- <https://developers.openai.com/api/docs/deprecations#2026-04-22-legacy-gpt-model-snapshots>
- <https://developers.openai.com/api/docs/pricing>

Using `deepseek-flash` under this exact source would not be unchanged-core: the
release only documents `deepseek-chat`, and the current callable DeepSeek
identity is different. The best-native lane may legitimately use a different
model from SciTaste, but must set `model_effects_confounded=true` and cannot
attribute a system difference causally to Scientific Taste.

## Remaining adapter gates

- Task mapping is blocked. The native interface consumes a research topic plus
  phase-specific YAML notes rather than an immutable MLRC task package. A
  deterministic translation must prove that it neither adds privileged
  guidance nor drops starting evidence.
- Sandbox is blocked. Literature retrieval, dataset access, generated code,
  solver subprocesses, network access, and writable paths require an isolated
  policy accepted for every compared system.
- Telemetry is blocked. Native phase timing and cost prints do not yet close all
  provider calls, token classes, retries, experiments, interventions, failures,
  wall time, allocated GPU time, and active GPU time into one cell receipt.
- Artifact mapping is pending. Reports, source, experiment outputs, logs, state,
  and optional PDF must be projected without deleting failed attempts.
- Failure/resume is pending. Pickle state exists, but has not been bound to the
  exact task/model/policy/cell hash and a prespecified retry limit.

## Admission decision

Agent Laboratory remains a real accepted-method comparator candidate. It may
enter only a separately preregistered best-native ecological lane after the
above gates, current model identity, credential, and task assets pass. A thin
adapter may stage inputs, isolate execution, collect telemetry, and copy
artifacts; it must not modify the upstream research policy or silently replace
the model backend.
