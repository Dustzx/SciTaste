# Window 3 Dispatch: Progress-First Generative Research Workspace

Assignment token: `W3-generative-progress-20260906-r3`

Status: `integrated; idle`

Integration record: WP1--WP5 were delivered as `4a83d36`, `15bd30b`,
`0900ecb`, `55c9ba8`, and `72803f5`, reviewed on main, and merged by
`ea6a921`. Main added fail-closed finite-cost admission before final
verification. Window 3 must not continue without a new assignment token.

The user authorized Window 3 to self-dispatch this follow-on Epic. The previous
evidence-native workspace and its audit hardening were integrated into `main` as
merge commit `50062ae`. This Epic starts from current `main`; it must not
continue from the already-integrated feature-branch tip.

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/generative-ui`
- branch: `feat/generative-ui-intent-planner-v3`
- base: current `main` containing this assignment token
- do not implement product changes in `/home/good/zfx/papers/SciTaste`

Window 3 proceeds through every work package without waiting for approval
between commits. Main remains responsible for final review, merge, roadmap and
release records.

## Product order and objective

Implement project progress before open-ended generation. A user must first be
able to see what a real SciTaste project has completed, what evidence supports
that status, what is blocked or unavailable, where its current run and paper
live, and which next steps are merely candidates. Use
`scitaste-self-development` as the primary self-hosting acceptance case without
writing generated outputs or special-casing its ID.

Then add a visible generation-as-content interaction: evidence-derived quick
intents and a bounded free-question input both resolve to the same typed
`WorkspaceIntent`; a planner may select, order and group only server-owned
component candidates and may cite only evidence in the current project
snapshot. The generated result is a declarative `SurfacePlan`, never HTML,
JavaScript, commands, URLs, filesystem paths, controller decisions or research
state mutations.

The target experience is a fixed trusted shell whose project workspace changes
meaningfully with the user's research goal while remaining reproducible,
evidence-grounded, auditable and useful when no model provider is configured.

## Owned paths

- `src/scitaste/generative_ui/`, including packaged fixed receiver assets;
- the smallest UI CLI registration/configuration changes required in
  `src/scitaste/cli.py` and `src/scitaste/generative_ui/serve_cli.py`;
- `tests/generative_ui/` and focused `tests/integration/` UI/CLI coverage;
- `docs/GENERATIVE_UI.md`.

Do not edit `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`, README,
other task documents, model-node internals, `full_workflow.py`, project runtime,
AutoResearchClaw, credentials or generated `outputs/`. If a required behavior
cannot be implemented within these boundaries, fail closed and report the
integration seam to main.

## WP1 — Evidence-grounded project progress

1. Add a closed, versioned project-progress query and trusted component model.
   Progress must distinguish observed completion, current work, blocked/failed,
   unavailable and unknown; it must not turn absent evidence into completion or
   invent a numeric percentage.
2. Derive milestones, current run/stage, paper state, blockers, recent verified
   activity and next-step candidates from fresh `ProjectRuntime` records and
   content-addressed project evidence. Every visible progress claim cites its
   supporting evidence IDs.
3. Make project progress a first-class receiver view and the useful default
   after project selection. Preserve existing deep links and compatibility.
4. Test empty, legacy, partial, successful, failed, blocked, paper-bearing and
   self-development-shaped projects. No fixture may masquerade as real research
   evidence.

Commit WP1 and run focused model/workspace/receiver tests before continuing.

## WP2 — Unified quick and free-form intent contract

1. Define strict request/result contracts for evidence-derived quick intents
   and bounded free questions. Both paths produce the same canonical
   `WorkspaceIntent`, project/snapshot binding and deterministic fingerprint.
2. Quick intents must be generated from current project capabilities and state,
   not from a static universal menu. They remain usable without a provider and
   cover progress review, blocker diagnosis, run comparison, paper evidence and
   next-step review only when the required authoritative identities exist.
3. Free questions may express flexible goals, but untrusted text must never
   become renderer content, a query path, a command, a URL, or an execution
   payload. Ambiguous project-owned entities produce a typed clarification or
   bounded candidate set rather than a guessed binding.
4. Define a closed `SurfacePlan` that can select, order, group and emphasize
   only server-provided candidate component IDs. It cannot author component
   data, evidence, actions or authority. Validate and fingerprint the plan
   against the exact project snapshot and candidate catalog.

Commit WP2 and run contract, determinism and malicious-payload tests before
continuing.

## WP3 — Planner boundary and deterministic fallback

1. Add a narrow planner protocol with a deterministic implementation and an
   optional existing-provider integration seam. Provider output is untrusted
   `SurfacePlan` input and must pass the same closed validation. Do not couple UI
   safety to prompt instructions.
2. Prefer deterministic resolution for recognized intents. A configured model
   may classify long-tail free questions and compose allowed candidates; it may
   not create facts or component values. Provider outage, malformed output,
   timeout or refusal must return a useful typed fallback or explicit
   unavailable state.
3. Keep credentials server-side, lazy-load provider dependencies, impose input,
   output, token and timeout bounds, and avoid logging questions, credentials or
   unpublished evidence content. Tests use fakes; an explicitly configured GLM
   5.3 Flash smoke may be recorded separately without committing responses.
4. Bind planner identity/configuration class, normalized intent, candidate
   catalog, snapshot and resulting plan into provenance and fingerprints. Do
   not claim deterministic reproducibility for model generations.

Commit WP3 and run planner boundary/fallback tests before continuing.

## WP4 — Visible generation-as-content receiver

1. Add one accessible intent control with both an editable free-question input
   and evidence-derived quick-intent buttons. Clicking a quick intent and
   submitting equivalent text must traverse the same server-owned planning
   boundary.
2. Render the validated plan as a visibly generated/revised workspace using
   only registered native components. Show intent, planner mode, snapshot
   freshness, cited evidence and a concise server-owned explanation of why each
   component is present.
3. Preserve default deterministic navigation, browser history, project switch
   isolation and stale-tab rejection. Clear prior intent, entity candidates and
   generated layouts before admitting a newly selected project.
4. Make failure modes legible: clarification required, no matching evidence,
   provider unavailable, stale snapshot and rejected plan must never degrade
   into a blank page or fabricated answer.

Commit WP4 and run application, static receiver, accessibility and integration
tests before continuing.

## WP5 — Self-hosting proof, hardening and handoff

1. Exercise the progress and intent paths against the existing
   `scitaste-self-development` project read-only. Record only test/verification
   facts in documentation; do not edit `outputs/` or commit runtime responses.
2. Add adversarial tests for prompt/markup injection, forged component and
   evidence IDs, cross-project entities, duplicate plan entries, stale
   snapshots, oversized questions/provider responses, provider errors and
   attempts to smuggle commands, URLs, actions or executable authority.
3. Update `docs/GENERATIVE_UI.md` with the exact current/future boundary,
   progress semantics, intent lifecycle, model/fallback behavior, API examples,
   trust diagram, operator configuration and known limitations.
4. Run focused UI/CLI tests, Ruff, `node --check`, `make check`, owned-module
   coverage, `git diff --check` and wheel package-data inspection. Return a clean
   feature branch with logical WP commits.

## Exit gate

The Epic is complete only when the running local application visibly shows an
evidence-grounded progress view for real projects and lets a user either click
an applicable quick intent or ask a bounded free question to obtain a different
validated component arrangement. The same evidence and permission boundaries
must apply to deterministic and model-assisted planning. No path may execute a
proposal, tool, command, model-authored renderer or research-state change.

The final handoff reports every commit SHA, exact tests and coverage, package
verification, self-hosting observations, provider configuration status, known
browser/security limits and main-window integration seams. Do not merge, push
or rebase `main` after starting the feature branch.
