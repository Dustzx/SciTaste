# Window 2 Dispatch: Tool Intelligence — Semantic Hotspot Execution

Assignment token: `W2-tool-intelligence-20260907-r2`

Status: `ready for main-window review`

## Handoff evidence

- new controlled-execution tests: `13 passed`
- focused branch coverage for `tool_execution.py`: `81%`
- complete model-node tests: `166 passed`
- repository check after initializing the already pinned AutoResearchClaw
  submodule: `830 passed`; Ruff format/check passed
- `git diff --check`: passed
- live model/provider calls: `0`
- external process/network/filesystem-write authority granted to handlers: `0`

The first repository run reached `782 passed, 48 failed` because a new worktree
had an empty submodule directory. After `git submodule update --init --recursive`
checked out the repository's existing `12d3fd8` pin, the unchanged full suite
passed. Neither AutoResearchClaw content nor the submodule pin changed.

Known limits are intentional and documented in `docs/TOOL_INTELLIGENCE.md`:
there is no automatic full-workflow trigger, lease consumption is process-local,
handler observations are not durably published or automatically admitted as
evidence, and project-owned locator adapters remain a main-window integration
task. This increment is engineering evidence, not an effectiveness result.

This assignment supersedes the completed proposal-only v1 dispatch. Tool
Intelligence v1 was integrated into `main` as `3013bc4`; its feature commit was
`ac19886914633a69a166c0ad88632fc4586f98f6`. Do not continue development from
that old feature head.

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/tool-intelligence-v2`
- branch: `feat/tool-intelligence-v2`
- base: `8f8e8fd6d2f7182ab88ac824945b3d1c1377cdc2`

Do not merge, push, or rebase. The main window owns integration. The primary
worktree contains unrelated uncommitted work and must not be cleaned, reset, or
overwritten.

## Objective

Advance Tool Intelligence from proposal-only plans to the smallest real,
policy-controlled execution loop. An accepted `ToolPlanNode` proposal may be
converted by deterministic code into one short-lived lease for one read-only
step. A registered deterministic handler may return a typed observation, but it
cannot mutate canonical state or turn its output into accepted scientific
evidence automatically.

The architectural unit is a **semantic hotspot**, not a general autonomous
planner: deterministic code follows its normal path, invokes a bounded model
node only for named semantic ambiguity, admits at most one fresh action, records
the observation and returns control to deterministic workflow code.

## Owned paths

- `src/scitaste/model_nodes/**`
- `tests/model_nodes/**`
- `docs/TOOL_INTELLIGENCE.md`
- this dispatch document

Do not edit CLI, full workflow, project-runtime ownership code, generative UI,
central roadmap/architecture/changelog/README, generated `outputs/`, credentials,
model weights, or `third_party/autoresearchclaw/**`. If integration needs one of
those paths, report the requirement to the main window rather than expanding
scope.

## Work packages

### WP1 — Semantic-hotspot and action-lease contracts

1. Define a strict semantic-hotspot trigger that records why deterministic code
   needs semantic help and the admissible tool scope.
2. Define a content-addressed, project/revision/state/profile/request/step-bound
   action lease. It authorizes exactly one use, expires, and cannot grant more
   authority than the v1 read-only profile.
3. Define typed tool observations and execution receipts with handler identity,
   input/output hashes, latency, status, and post-call project revision.

### WP2 — Deterministic single-step executor

1. Admit only an accepted `ToolPlanNode` result with no provider-native tool
   calls and an exact fresh project snapshot.
2. Permit only the next dependency-free step; do not execute a model-authored
   multi-step DAG in one call.
3. Resolve tools only through a closed deterministic handler registry. Enforce
   handler name/version/fingerprint, read-only declaration, output byte limits,
   lease expiry, one-use nonce, and project revision immediately before and
   after the handler call.
4. Preserve a rejected observation and resource/latency evidence when the
   project changes during execution. Never accept a stale observation.
5. Do not make a provider call, launch a process, access the network, write
   project artifacts, or mutate ResearchState.

### WP3 — Adversarial tests and documentation

Cover valid single-step execution plus rejected node result, mismatched project,
state, profile, request or step, stale pre-call revision, concurrent post-call
revision change, expired/reused lease, unregistered or mutable handler, handler
identity drift, handler exception, oversized/non-JSON output, and provider tool
call confusion. Prove rejected results never invoke handlers and observations
remain non-authoritative.

Document the semantic-hotspot architecture, authority flow, expected high-value
research scenarios, and remaining integration/effectiveness limits.

## Exit gate

The increment is complete only when the new focused tests and all existing
model-node tests pass, `make check` and `git diff --check` pass, documentation
matches behavior, and the branch contains one or a small number of cohesive
commits. This increment is engineering evidence only; it does not establish
scientific effectiveness or satisfy ADR-022.
