# Parallel Task Board

Board revision: `2026-09-07.13`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Phase 9 local-system execution and core workflow | in progress | `main` | `/home/good/zfx/papers/SciTaste` | integrated W2/W3 foundations |
| 2 | Tool Intelligence follow-on from `INNOVATION_MAP.md` | in progress; owner assigned | `feat/tool-intelligence-v1` | `/home/good/zfx/papers/SciTaste-worktrees/tool-intelligence` | integrated v1 foundation |
| 3 | Progress-first Generation as Content workspace | integrated; idle | `feat/generative-ui-intent-planner-v3` | `/home/good/zfx/papers/SciTaste-worktrees/generative-ui` | new assignment required |

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

- Window 2's Tool Intelligence v1 Epic is integrated at `3013bc4`; the project
  owner has assigned Window 2 a follow-on iteration from the Tool Intelligence
  section of `docs/INNOVATION_MAP.md`. Main does not edit that subsystem while
  the follow-on is active. Window 3's progress-first Generation as Content
  WP1--WP5 is integrated and remains idle.
- Main owns Phase 9 local-system execution, core workflow development,
  integration repairs, project catalog refreshes, common architecture/roadmap/
  changelog edits, full-suite checks, and GitHub synchronization.
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
- Main has integrated evidence-derived project progress, quick intents, bounded
  free questions, closed `SurfacePlan` composition, deterministic fallback, and
  the generated workspace receiver. Model-assisted plans require finite token,
  byte, latency, and measured-cost admission and never gain execution authority.
