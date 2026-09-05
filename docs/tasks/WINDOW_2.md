# Window 2 Dispatch: Project-Scoped Model-Node Runtime

Assignment token: `W2-model-node-runtime-20260905-r2`

Status: `integrated into main; Epic and hardening complete`

Integration review on 2026-09-05 accepted the Epic's scope and 124 passing
focused tests but reproduced three blockers before merge: nested runtime
directories could follow symbolic links outside the project, project revision
could change across a model call without rejecting the proposal, and interrupted
pending-marker cleanup could make a complete ledger permanently unverifiable.
Window 2 closed all three in `45ce9c3`; main independently reran 134 focused
tests and integrated the complete branch as merge commit `37ee0ba`. The merged
repository then passed 544 tests. Further work requires a new assignment token.

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/model-nodes`
- branch: `feat/model-node-runtime-v2`
- base: `main` containing this assignment token
- do not work in `/home/good/zfx/papers/SciTaste`

Create or switch to the named branch from the dispatch-bearing `main` before
editing. The prior pilot-orchestration Epic is integrated history, not the base
for an unrebased continuation.

## Objective

Build the production, project-scoped runtime that turns the existing bounded
node implementations into a reusable SciTaste subsystem outside the special
self-development pilot. It must make provider generation capacity visibly
different from deterministic proposal-admission budgets, persist every
invocation and cumulative resource effect across restarts, support exact replay,
and expose a narrow integration facade that main can later connect to the full
workflow without giving a model controller or executor authority.

This is one multi-package Epic. Continue from WP1 through WP4 without waiting for
main-window approval between commits. Do not stop after adding only configuration
models or a thin CLI.

## Owned paths

- `src/scitaste/model_nodes/`;
- one focused model-node CLI module and the smallest registrations required in
  `src/scitaste/cli.py`;
- `configs/model_nodes/` for non-secret runtime/profile examples;
- `tests/model_nodes/` and focused `tests/integration/` coverage;
- `docs/BOUNDED_MODEL_NODES.md`.

Do not edit generative UI, `full_workflow.py`, central roadmap/architecture/
changelog/README/task documents, AutoResearchClaw, generated `outputs/`, or
credentials.

## Work packages

### WP1 — Budget and capability profiles

1. Introduce a strict, versioned runtime/profile contract that distinguishes:
   provider generation envelope (request/output/context capability), node
   admission budget (input/output/total tokens, latency, tools and cost), and
   cumulative project budget. Preserve backward compatibility with existing
   backend and pilot configuration.
2. Allow the selected node/case to bind an explicit profile instead of relying
   on one backend-wide `max_output_tokens`. Validate incompatible ceilings and
   surface both effective limits in plan/status output and fingerprints.
3. Provide content-addressed examples for short structured semantic nodes and a
   deeper semantic-analysis profile. Do not label either as unrestricted code
   generation, guess provider pricing, or enable live calls by default.
4. Add tests proving that the 2,048-token self-development probe limit is local
   to that immutable configuration and cannot become a global SciTaste limit.

Commit WP1, run its focused tests, then continue automatically.

### WP2 — Durable `ModelNodeRuntime`

1. Add a project/run-owned runtime for normal node invocations. A registered
   invocation binds project and state revision, node/input/context, trigger
   reason, profile, policy, provider/model, seed, request fingerprint, and
   predecessor ledger hash before contacting a backend.
2. Persist accepted, rejected, not-applicable, failed, and planned outcomes.
   Accepted remains proposal-only and executable false. Known cost from every
   non-cached response—including rejected output—must advance the cumulative
   ledger; unknown cost blocks further acceptance under a priced policy.
3. Make interruption/resume and concurrent writers fail closed. Reuse only a
   verified contiguous ledger prefix. Archive incomplete paid attempts and bind
   exact live/record/replay evidence without storing authorization headers.
4. Support exact replay by request/profile/policy/state identity with no silent
   live fallback, provider alias, or cache substitution.

Commit WP2, run its focused tests, then continue automatically.

### WP3 — Narrow workflow facade and CLI

1. Expose an integration facade for the three implemented node types. It accepts
   an explicit immutable state projection and trigger; it returns a typed
   proposal/result plus ledger locator and never mutates `ResearchState`.
2. Add project-scoped plan, execute/resume, status/verify, and replay CLI paths.
   Planning/status/default execution are network-free. Live execution requires
   profile permission, backend permission, and caller opt-in.
3. Machine output must show the effective generation envelope separately from
   admission/cumulative budgets, invocation counts, cache/replay state, token/
   cost/latency telemetry, blockers, and project-owned evidence locators without
   raw responses or secret values.
4. Provide fixtures demonstrating review parsing, interpretation criticism, and
   ambiguity routing across more than one process lifecycle.

Commit WP3, run CLI/integration checks, then continue automatically.

### WP4 — Hardening and exit evidence

1. Cover corrupt ledger entries, stale project revision, changed profile/policy,
   partial publication, replay miss, backend identity drift, unknown cost,
   over-budget response, duplicate invocation ID, process restart, and concurrent
   writers.
2. Verify public-model compatibility or version/migration handling, deterministic
   serialization, no secret reflection, no import-time provider dependency, and
   no network access in tests.
3. Update `docs/BOUNDED_MODEL_NODES.md`, run Ruff, the complete model-node suite,
   integration tests, `make check`, and coverage for owned production modules.

## Epic exit gate

The Epic is complete only when all four work packages are committed, a normal
project (not the special pilot runner) can plan/execute/resume/verify/replay the
three bounded nodes through the new runtime, budget layers are unambiguous in
both schemas and CLI output, project evidence survives restart and tamper checks,
and every proposal remains non-executable.

No real provider call is authorized. Do not fabricate pricing, external review,
or effectiveness evidence.

## Autonomous handoff

Do not request a new task token after WP1, WP2, or WP3. Continue unless a genuine
cross-owned change or security/dependency decision blocks the Epic. At the final
handoff report each WP commit SHA, exact tests and coverage, remaining limits,
compatibility/dependency/security notes, and a clean worktree. Do not merge or
push `main`.

Previous integrated Epic: `W2-model-pilot-orchestration-20260905-r1`, branch
handoff `b3a9dd3`, integrated and subsequently hardened on main.
