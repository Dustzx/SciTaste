# Parallel Task Board

Board revision: `2026-09-05.4`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Integration, Phase 9/core workflow, shared docs, final acceptance | in progress | `main` | `/home/good/zfx/papers/SciTaste` | Window 2/3 handoffs |
| 2 | Production pilot orchestration and project-owned evidence | in progress | `feat/model-node-pilot-orchestration` | `/home/good/zfx/papers/SciTaste-worktrees/model-nodes` | `425badc` |
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

- Window 2 owns model-node pilot configuration, orchestration, CLI, and
  project-owned pilot evidence publication.
- Window 3 owns the receiver-controlled local UI/API application boundary.
- Main owns Phase 9/core workflow development, both merges, project catalog
  refreshes, common architecture/roadmap/changelog edits, full-suite checks, and
  GitHub synchronization.
