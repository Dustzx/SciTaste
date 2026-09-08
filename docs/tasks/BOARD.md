# Parallel Task Board

Board revision: `2026-09-08.15`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Open-question intake and workflow launch autonomy | acceptance in progress | `main` | `/home/good/zfx/papers/SciTaste` | restart-safe Full Workflow |
| 2 | Durable project-owned Tool Intelligence loop v3 | delivered; review pending | `feat/tool-intelligence-v3` | `/home/good/zfx/papers/SciTaste-worktrees/tool-intelligence-v3` | main integration review |
| 3 | Generation as Content UX evaluation v5 | delivered; review pending | `feat/generative-ui-ux-evaluation-v5` | `/home/good/zfx/papers/SciTaste-worktrees/generative-ui` | main integration review |

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

- Window 2's Tool Intelligence v2 single-step leased executor is integrated at
  `00b006b`; its v3 durable-loop handoff is queued for review. Window 3's
  English/Simplified-Chinese receiver is integrated at `1b233da` and `1afaede`;
  its v5 UX-evaluation handoff is also queued. Neither handoff is treated as
  integrated before main-window review.
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
- Main now owns explicit native resource profiles: content-bound datasets are
  copied into the project and mounted read-only, while GPU access requires exact
  device admission and bounded accounting. The default remains no dataset/no GPU.
- Main has added a strict `ResearchBrief` and self-hashed Full Workflow launch
  plan. Dry-run performs mutation-free admission; formal execution copies and
  consumes five project-owned inputs. The v1 planner is registered-scenario based,
  with model authority limited to proposals and deterministic execution admission
  retained by SciTaste.
