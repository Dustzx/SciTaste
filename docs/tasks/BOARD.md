# Parallel Task Board

Board revision: `2026-09-09.17`

| Window | Assignment | Status | Branch | Worktree | Depends on |
|---|---|---|---|---|---|
| Main | Bounded native mainline closure | implementation complete; repository acceptance in progress | `main` | `/home/good/zfx/papers/SciTaste` | external Phase 9 gates |
| 2 | Durable project-owned Tool Intelligence loop v3 | audited and integrated; main-workflow trigger integrated | `feat/tool-intelligence-v3` | `/home/good/zfx/papers/SciTaste-worktrees/tool-intelligence-v3` | independent review and broader tasks |
| 3 | Generation as Content UX evaluation v5 | audited and integrated; human study pending | `feat/generative-ui-ux-evaluation-v5` | `/home/good/zfx/papers/SciTaste-worktrees/generative-ui` | powered counterbalanced evaluation |

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

- Window 2's five v3 commits are audited and integrated on main as `12ad322`
  through `782d3af`. Window 3's four UX-evaluation commits are audited and
  integrated as `3b6bc97` through `f9adec8`. Focused combined verification
  passes 456 model-node, Generation-as-Content, and related CLI tests; Ruff and
  the complete repository suite pass with 938 tests. Node syntax checks and an
  isolated wheel-content check also pass.
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
- The earlier seven-case GLM-5.3-Flash engineering probe remains enforcement
  evidence only. The new registered 36-call comparison supplies priced,
  project-owned preliminary routing evidence, but independent blinded review,
  broader tasks, and external replication remain open; no scientific
  effectiveness claim is promoted.
- Main has integrated evidence-derived project progress, quick intents, bounded
  free questions, closed `SurfacePlan` composition, deterministic fallback, and
  the generated workspace receiver. Model-assisted plans require finite token,
  byte, latency, and measured-cost admission and never gain execution authority.
- Main has integrated the read-only structural/latency evaluator, responsive
  focus repair, and Chromium engineering probe. The recorded proxy and
  walkthrough evidence is explicitly not a human-usability result.
- Main now owns explicit native resource profiles: content-bound datasets are
  copied into the project and mounted read-only, while GPU access requires exact
  device admission and bounded accounting. The default remains no dataset/no GPU.
- Main has added a strict `ResearchBrief` and self-hashed Full Workflow launch
  plan. Dry-run performs mutation-free admission; formal execution copies and
  consumes five project-owned inputs. The v1 planner is registered-scenario based,
  with model authority limited to proposals and deterministic execution admission
  retained by SciTaste. Clean-commit acceptance passed 875 tests with one
  local-output-dependent UI skip and 83 percent combined coverage; the
  self-development project records revision 198.
- Main has extended that boundary with deterministic selection from a
  content-bound four-stage scenario catalog; the catalog and selected inputs are
  copied into the run and verified on resume.
- Main has integrated the deterministic UI proposal controller and Full Workflow
  Tool Intelligence hotspot. Approval yields only an audited bounded handoff;
  the evidence tool is leased and read-only, and its observation remains outside
  canonical state. Proposal-only source generation, evidence advice, and tool
  planning now compose through one typed ledger.
