# External adapter compatibility audit v1

Audit date: 2026-09-11

Scope: static, no-download, no-execution review of the exact MLR-Agent and Agent
Laboratory commits selected by the SciTaste DeepSeek V4.1 package prepilot. This
record evaluates whether a thin first-party adapter can preserve upstream core
behavior while enforcing the matched task, model, sandbox, telemetry, artifact,
and failure/resume contract. It is not an adapter acceptance result.

## Fixed comparison envelope

- callable API model: `deepseek-flash`;
- observed/catalog model version: `DeepSeek-V4.1-Flash`;
- identical starting research-brief bytes per matched block;
- no unregistered runtime task assets;
- common information, tool, repair, token, cost, wall-time, and intervention
  policies;
- complete native artifacts and failure-inclusive telemetry;
- no edits to external-system core logic.

## MLR-Agent at `f728d571a992d71c8b526eeb4d9ab6bb5c8cc824`

Official sources inspected:

- [`README.md`](https://raw.githubusercontent.com/chchenhui/mlrbench/f728d571a992d71c8b526eeb4d9ab6bb5c8cc824/README.md)
- [`run_mlr_agent.py`](https://raw.githubusercontent.com/chchenhui/mlrbench/f728d571a992d71c8b526eeb4d9ab6bb5c8cc824/run_mlr_agent.py)
- [`mlrbench/llm/llm.py`](https://raw.githubusercontent.com/chchenhui/mlrbench/f728d571a992d71c8b526eeb4d9ab6bb5c8cc824/mlrbench/llm/llm.py)
- [`mlrbench/agent/experiment_runner.py`](https://raw.githubusercontent.com/chchenhui/mlrbench/f728d571a992d71c8b526eeb4d9ab6bb5c8cc824/mlrbench/agent/experiment_runner.py)

Static findings:

- Task mapping is blocked for the current envelope. The pipeline accepts
  `<task directory>/task.md`, but the CLI derives a hard-coded task-directory
  prefix from selected model/coding-agent names and has no DeepSeek branch.
  A thin adapter can stage exact bytes, but it cannot use the published CLI for
  this model without a separately reviewed bootstrap and acceptance test.
- Model mapping is blocked. The fixed model registry does not contain
  `deepseek-flash`; its listed DeepSeek option is the different OpenRouter model
  `deepseek/deepseek-chat-v3-0324`. The experiment stage delegates to one of
  Claude Code, Codex, or Gemini rather than the same declared reasoning model,
  so all model roles are not matched.
- Sandbox qualification is blocked. The experiment instructions permit dynamic
  dataset/model downloads and generated-code execution, which conflicts with
  the frozen task/runtime policy until isolated network and filesystem controls
  are demonstrated.
- Matched telemetry is blocked. Some LLM wrappers expose token counts, but the
  end-to-end pipeline does not demonstrate complete aggregation across
  literature, coding-agent, retries, experiments, costs, and interventions.
- Artifact mapping is pending. The repository documents Markdown output and
  stage-native files, but a complete failure-inclusive research-package
  inventory has not been accepted.
- Failure/resume is pending. No exact-cell, content-addressed checkpoint and
  retry boundary has been demonstrated for this selected task/model envelope.

Conclusion: do not construct an apparently matched DeepSeek V4.1 MLR-Agent cell
by renaming a V3/OpenRouter model or replacing the coding subsystem. A different
common backbone or an explicitly disclosed non-matched sensitivity lane would
require a new proposal.

## Agent Laboratory at `d9017d90e329112d2a80b7712f37ee9094d2cd27`

Official sources inspected:

- [`README.md`](https://raw.githubusercontent.com/SamuelSchmidgall/AgentLaboratory/d9017d90e329112d2a80b7712f37ee9094d2cd27/README.md)
- [`ai_lab_repo.py`](https://raw.githubusercontent.com/SamuelSchmidgall/AgentLaboratory/d9017d90e329112d2a80b7712f37ee9094d2cd27/ai_lab_repo.py)
- [`experiment_configs/MATH_agentlab.yaml`](https://raw.githubusercontent.com/SamuelSchmidgall/AgentLaboratory/d9017d90e329112d2a80b7712f37ee9094d2cd27/experiment_configs/MATH_agentlab.yaml)
- [`agents.py`](https://raw.githubusercontent.com/SamuelSchmidgall/AgentLaboratory/d9017d90e329112d2a80b7712f37ee9094d2cd27/agents.py)

Static findings:

- Task mapping is blocked. The native interface receives a research topic and
  phase-specific notes from YAML rather than an exact `task.md` package. A
  deterministic, loss-audited translation has not been demonstrated.
- Model mapping is blocked. The release documents `deepseek-chat`
  (`deepseek-v3`), not `deepseek-flash` / `DeepSeek-V4.1-Flash`. Renaming the
  configured model would not prove the served model or all-phase compatibility.
- Sandbox qualification is blocked. The workflow searches external resources,
  generates and executes data/experiment code, and writes a research tree. The
  matched network/filesystem/tool boundary has not been accepted.
- Matched telemetry is blocked. Phase time/step statistics and some cost
  reporting do not establish complete provider, token, retry, experiment,
  intervention, and failure counters under the SciTaste contract.
- Artifact mapping is pending. Native report, source, experiment log, state, and
  optional PDF files need a failure-inclusive immutable projection.
- Failure/resume is pending. Native pickle state saves exist, but they have not
  been shown to bind the exact SciTaste cell, task/model bytes, attempt number,
  and replay policy.

Conclusion: Agent Laboratory remains a real accepted-method candidate, but not
an admitted matched DeepSeek V4.1 comparator. The unresolved items must remain
visible instead of being replaced with a pseudo-implementation.

## Decision effect

The historical DeepSeek V4.1 prepilot cannot truthfully clear its requirement for
two accepted, matched external method comparators. This is an experiment-design
constraint exposed by SciTaste's adapter gate, not evidence that the systems are
low quality and not evidence about SciTaste effectiveness. The next decision is
to either obtain a genuinely common supported backbone and issue a new immutable
proposal, or redesign the external comparison as a separately labelled
best-native-system evaluation with model effects explicitly confounded. No paid
call, task download, GPU action, or upstream checkout was performed for this
audit.
