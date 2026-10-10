# SciTaste repository guide

## Authority and scope

- Implement against `PROJECT_SPEC.md` and the workspace's full v1.1 specification.
- Work on one `docs/ROADMAP.md` phase at a time and preserve its exit gate.
- SciTaste selects research actions; executors only execute the selected action.
- Never put SciTaste control logic in `third_party/autoresearchclaw`.

## Development commands

```bash
git submodule update --init
python3.12 -m venv .venv
.venv/bin/pip install -c requirements/python312-dev-study.lock -e '.[dev,study]'
make check
make demo
```

## Deadline-critical validation discipline

- Standing user correction (2026-10-07): each work batch must follow the canonical
  project submission plan, not a convenient local engineering problem. Use the
  existing plan/context once to name the target work ID, its unmet acceptance
  criterion and the intended scientific deliverable. This is task selection, not
  another model call, test, preflight or per-tool approval gate.
- Advance the earliest unresolved claim-critical dependency. For self-development,
  `task-freeze` and `taste-freeze` currently precede `primary-experiments`; partial
  independent batches can proceed immediately when ready. Retained-data mini-studies,
  source-worker replay, interface completion and artifact counts cannot stand in
  for SciTasteBench main comparisons or matched Taste-effect evidence.
- Insert an engineering repair only when a concrete failure blocks the selected
  deliverable, or a mandatory safety/integrity boundary requires it. Report target,
  actual delivered evidence, remaining acceptance gap and next mainline action;
  never infer milestone completion from calendar date or a finished side task.

- Before training, evaluation, data audit, GPU launch/resume/queue or active
  waiting, read `/home/good/.codex/skills/experiment-autopilot/SKILL.md` fully.
  Use measured throughput, actually wait/check/continue authorized work, and keep
  concise project evidence. Pure status requests do not start new experiments;
  short local yields are not permission for frequent remote polling. Resource
  priority and scientific stop conditions take precedence over utilization.

- Standing user requirement (2026-10-01): continually benchmark scientific plans
  and outcomes against accepted AutoResearch work, not merely local engineering
  completion. At task-family selection, experiment freeze and result synthesis,
  reuse the source-bound literature ledger and record the nearest accepted work,
  actual evaluation construct, current gap and next evidence-producing action.
  Verify acceptance and track in official proceedings; distinguish methods,
  benchmarks and hybrids, and main track, Findings, demonstrations and workshops.
  A framework being runnable does not establish publication or baseline suitability.
- Read the relevant methods/experiments before freezing a scientific comparison;
  abstract-level comparisons are orientation only. Compare task authenticity and
  difficulty, scientific contribution, real system baselines, executable outcomes,
  judge calibration, research-to-paper quality and resource conditions. Counts or
  matching table layouts cannot establish comparable scientific quality.
- Keep this comparison lightweight and decision-relevant: refresh when a substantive
  design/result changes, not for every tool call; it is not another recurring test
  gate. Do not repeat experiments or demand human review merely to populate a
  checklist. AI-only adjudication proceeds with its limitations disclosed.
  Existing two UCI task families are narrow candidate data, not evidence that
  SciTasteBench already matches accepted benchmarks. See
  `docs/research/SCITASTEBENCH_TASK_DATA_V1.md` for current comparator implications.

- User resource constraint (2026-09-29): do not invoke Qwen model APIs, including
  Qwen through Bailian/DashScope. Latest user direction: use current-window spawned
  agents in place of model API calls during mainline improvement. September 30:
  GLM/DeepSeek resources are available, but the user's latest preference remains
  subagents first; do not make supplier calls merely to replace an available session
  role. Revisit provider validation after overall quality improves,
  with an explicit user-facing transition rather than silently resuming paid calls.
  The user authorizes subagent delegation for these model roles. Researchers and
  independent reviewers receive role-scoped inputs; use fresh context for independent
  review. Record session/subagent provenance, never fabricated provider receipts,
  token usage or model identity. Do not combine new session results with previous
  API cohorts as though the backbone were unchanged.
  For external-framework comparisons, the real pinned open-source implementation
  must own planning, stage transitions, tools, experiments and writing. Subagents
  may only supply the model responses requested by that implementation; never
  substitute a role-playing subagent for the external framework itself.
  This does not prohibit local/remote Qwen weights as
  experimental subjects. Preserve old Qwen results and configurations as history;
  their existence is not permission for new API calls.

- During an active feature-completion sprint, validate the changed path with
  syntax/type construction, Ruff on touched modules, `git diff --check`, and at
  most one representative no-call or bounded smoke execution.
- Do not repeatedly run the full repository test suite, coverage, wheel build,
  or duplicate Python-version matrices after each small change. Run them once at
  the final integration gate after the feature set is frozen; SciTaste currently
  targets Python 3.12.
- A cheap check is not automatically useful. Route optional verification through
  Tool Intelligence and skip it when its expected detection value does not exceed
  its time/resource cost.
- Never defer a check whose failure could expose credentials, corrupt or destroy
  project evidence, contaminate a formal split, or irreversibly consume a formal
  experiment assignment. Those safety and scientific-integrity gates remain
  fail-closed.

## Change discipline

- Treat the submodule pin as immutable except in a dedicated dependency update.
- Keep public models backward-compatible or increment `schema_version` and add a
  migration.
- New controller decisions require deterministic tests and decision-log coverage.
- New execution backends implement `ResearchExecutor` and remain lazy imports.
- Do not commit secrets, configs, generated outputs, papers, datasets, or API
  responses.
- Update the roadmap, changelog, and relevant architecture record with material
  behavior changes.

## Parallel window coordination

- Multi-window work uses the canonical dispatch documents in `docs/tasks/`.
  The main window owns the board and task documents; child windows read their
  assigned absolute-path document before every task.
- Only cohesive, independently testable Epics expected to require at least half
  a focused day are dispatched. Small fixes remain on main because their
  coordination cost exceeds their parallelism benefit.
- Child windows use separate worktrees, stay inside assigned path ownership, and
  return clean feature-branch commits to main for review and integration.
