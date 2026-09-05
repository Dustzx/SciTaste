# Parallel Task Board

Board revision: `2026-09-05.9`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Phase 9/core workflow and normal-workflow model integration | in progress | `main` | `/home/good/zfx/papers/SciTaste` | integrated W2/W3 foundations |
| 2 | Project-scoped model-node runtime and policy profiles | integrated; idle | `feat/model-node-runtime-v2` | `/home/good/zfx/papers/SciTaste-worktrees/model-nodes` | new assignment required |
| 3 | Evidence-native generative project workspace | integrated; idle | `feat/generative-ui-workspace-v2` | `/home/good/zfx/papers/SciTaste-worktrees/generative-ui` | new assignment required |

## Scheduling policy

- At most two child Epics run concurrently with the main integration line.
- A child assignment must satisfy the multi-package/one-to-two-day threshold in
  `docs/tasks/README.md`.
- Main does not interrupt an in-progress Epic for incidental cleanup.
- Children continue across their numbered work packages without waiting for a
  new token or per-commit review; only the final handoff enters main's merge
  queue.
- Shared-file changes and integration repairs stay on main unless explicitly
  reassigned as a new task revision.
- Completion means reviewed commits and acceptance evidence, not only an agent
  message saying the work is done.

## Current non-overlap

- Window 2 and Window 3 have no active owned paths. Their r2 Epics and hardening
  fixes are integrated; neither should continue until its assignment document
  receives a new token and scope.
- Main owns Phase 9/core workflow development, integration repairs, project
  catalog refreshes, common architecture/roadmap/changelog edits, full-suite
  checks, and GitHub synchronization.
- Main has connected the integrated model-node runtime to an opt-in offline
  evidence-stage `run full` hook. The actual immutable state, proposal, exact
  recording, ledger head, and stage checkpoint are bound, while state mutation
  and execution authority remain absent.
- Main has extended that hook to a double-gated GLM-5.3-Flash live condition.
  A pre-call evidence checkpoint and exact recorded-response recovery prevent a
  known paid response from being called or counted twice; ambiguous calls remain
  blocked rather than retried.
- The real seven-case GLM-5.3-Flash engineering probe remains intentionally
  blocked rather than promoted. Priced external measurement, independent review,
  and a registered effectiveness comparison remain later model-node gates.
