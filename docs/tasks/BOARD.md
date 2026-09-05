# Parallel Task Board

Board revision: `2026-09-05.5`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Integration, Phase 9/core workflow, shared docs, final acceptance | in progress | `main` | `/home/good/zfx/papers/SciTaste` | Window 2/3 handoffs |
| 2 | Production pilot orchestration and project-owned evidence | integrated; awaiting next Epic | `feat/model-node-pilot-orchestration` | `/home/good/zfx/papers/SciTaste-worktrees/model-nodes` | `d08ee9f` on main |
| 3 | Trusted local generative-UI application boundary | integrated; awaiting next Epic | `feat/generative-ui-app-boundary` | `/home/good/zfx/papers/SciTaste-worktrees/generative-ui` | `372a0a9` on main |

## Scheduling policy

- At most two child Epics run concurrently with the main integration line.
- A child assignment must satisfy the half-day/coherent-subsystem threshold in
  `docs/tasks/README.md`.
- Main does not interrupt an in-progress Epic for incidental cleanup.
- Shared-file changes and integration repairs stay on main unless explicitly
  reassigned as a new task revision.
- Completion means reviewed commits and acceptance evidence, not only an agent
  message saying the work is done.

## Current non-overlap

- Window 2's model-node pilot orchestration Epic is integrated. Its next task
  requires a new assignment token; do not continue from the old branch.
- Window 3's receiver-controlled local UI/API Epic is integrated. Its next task
  requires a new assignment token; do not continue from the old branch.
- Main owns Phase 9/core workflow development, integration repairs, project
  catalog refreshes, common architecture/roadmap/changelog edits, full-suite
  checks, and GitHub synchronization.
