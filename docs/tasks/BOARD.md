# Parallel Task Board

Board revision: `2026-09-05.7`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Phase 9/core workflow and child-Epic integration | in progress | `main` | `/home/good/zfx/papers/SciTaste` | W2/W3 final handoffs only |
| 2 | Project-scoped model-node runtime and policy profiles | dispatched; autonomous multi-package Epic | `feat/model-node-runtime-v2` | `/home/good/zfx/papers/SciTaste-worktrees/model-nodes` | dispatch token r2 |
| 3 | Evidence-native generative project workspace | dispatched; autonomous multi-package Epic | `feat/generative-ui-workspace-v2` | `/home/good/zfx/papers/SciTaste-worktrees/generative-ui` | dispatch token r2 |

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

- Window 2 owns the new runtime/profile track in `WINDOW_2.md`; it must not edit
  generative UI, full-workflow, or central coordination files.
- Window 3 owns the evidence-native workspace track in `WINDOW_3.md`; it must not
  edit model nodes, full-workflow, or central coordination files.
- Main owns Phase 9/core workflow development, integration repairs, project
  catalog refreshes, common architecture/roadmap/changelog edits, full-suite
  checks, and GitHub synchronization.
- Main's completed core slice produced a real seven-case GLM-5.3-Flash
  engineering probe with exact live-response retention. The run is intentionally
  blocked rather than promoted; priced external measurement and independent
  review remain the next model-node acceptance gate.
