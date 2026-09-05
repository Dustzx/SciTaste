# Window 3 Dispatch: Evidence-Native Generative Project Workspace

Assignment token: `W3-evidence-workspace-20260905-r2`

Status: `integrated into main; Epic and hardening complete`

Integration review on 2026-09-05 accepted the four-work-package implementation
and its 480-test branch result but reproduced two blockers before merge: a valid
audit chain copied from project B could appear in project A, and the audit writer
did not bind the checked parent directory through lock/temp/replace operations.
Stale browser catalogs on project switch are also part of the required fix.
Window 3 closed these issues in `c319e3e`; main independently reran 163 focused
tests plus the JavaScript syntax check and integrated the complete branch as
merge commit `50062ae`. The merged repository then passed 544 tests. Further
work requires a new assignment token.

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/generative-ui`
- branch: `feat/generative-ui-workspace-v2`
- base: `main` containing this assignment token
- do not work in `/home/good/zfx/papers/SciTaste`

Create or switch to the named branch from the dispatch-bearing `main` before
editing. The prior application-boundary Epic is integrated history, not the base
for an unrebased continuation.

## Objective

Turn the secure local UI boundary into an evidence-native research workspace
that demonstrates “generation as content”: the server composes the most useful
trusted view from current project evidence, while the receiver lets a user move
fluidly among projects, runs, stages, blockers, papers, artifacts, comparisons,
and pending proposals. Generated content remains typed data inside fixed native
components; neither the browser nor generated layout receives execution,
filesystem, renderer-code, or controller authority.

This is one multi-package product Epic. Continue from WP1 through WP4 without
waiting for main-window approval between commits. Do not stop after one new page,
component, or API route.

## Owned paths

- `src/scitaste/generative_ui/` including fixed packaged assets;
- one focused UI CLI module and the smallest registrations required in
  `src/scitaste/cli.py`;
- `tests/generative_ui/` and focused `tests/integration/` coverage;
- `docs/GENERATIVE_UI.md`.

Do not edit model nodes, `full_workflow.py`, central roadmap/architecture/
changelog/README/task documents, AutoResearchClaw, generated `outputs/`, or
credentials.

## Work packages

### WP1 — Authoritative workspace/query model

1. Add closed, versioned server-owned view/query contracts for project list,
   overview, run/stage explorer, paper/evidence view, run comparison, blocker
   view, and pending-proposal history. Client input may select only validated
   project-owned IDs and predefined view purposes; it cannot submit components,
   fields, layout, evidence, filters, or renderer definitions.
2. Compose each view from a fresh `ProjectRuntime` snapshot and content-addressed
   evidence. Return explicit empty/unavailable states rather than inventing
   stages, metrics, paper content, or project health.
3. Add deterministic presentation summaries that explain what a stage produced,
   why a run is blocked/failed, and where the current paper/evidence lives using
   typed source fields—not model-authored prose.
4. Bind workspace/view identity, project revision, query selection, and every
   displayed evidence hash into the surface fingerprint.

Commit WP1, run its focused tests, then continue automatically.

### WP2 — Navigable generation-as-content receiver

1. Expand the fixed receiver into an accessible, responsive workspace with
   project switcher, view navigation, stage/run selection, evidence detail,
   blocker drill-down, comparison controls, and visible freshness/provenance.
   Use only receiver-owned DOM construction and the closed component registry.
2. Preserve browser navigation/back-forward state using validated identity-only
   URLs or history state. Reload and deep-link resolution must revalidate server
   evidence and fail closed on stale or unknown identity.
3. Add conditional refresh with ETag or an equivalent content fingerprint so
   unchanged views are cheap and changed project revisions invalidate stale
   actions. Do not add a model-generated renderer or arbitrary client query.
4. Make proposal state understandable: pending means recorded advice awaiting a
   later deterministic controller boundary, never “approved” or “executed.”

Commit WP2, run application/receiver tests, then continue automatically.

### WP3 — Safe evidence and artifact inspection

1. Add a narrow content-addressed inspection path only for artifacts already
   present in the authoritative selected view. Rehash on access, enforce project
   containment, regular-file/no-symlink semantics, media allowlists, and byte
   limits; changed or missing artifacts invalidate the view.
2. Render text, JSON, Markdown source, images, and PDF metadata/preview through
   fixed receiver behavior. Treat HTML/script-like bytes as inert text; never
   execute artifact scripts, serve active HTML, or expose a general download or
   filesystem endpoint.
3. Record proposal/inspection events in the existing project-owned hash chain,
   preserve restart duplicate protection and concurrency ordering, and expose a
   read-only verified pending-proposal history.
4. Ensure project switching cannot leak an artifact, event, or audit locator
   from another project.

Commit WP3, run security/integration tests, then continue automatically.

### WP4 — Product hardening and exit evidence

1. Test realistic projects containing successful, failed, blocked, legacy,
   no-paper, paper-bearing, multi-run, and changed-artifact states. Include
   hostile identifiers/content, stale tabs, forged selection, oversized files,
   MIME confusion, symlink/race attempts, corrupted audit, restart, and
   concurrent events.
2. Verify keyboard navigation, focus/error states, readable bilingual stage
   labels where the repository already defines them, narrow/mobile layout, CSP,
   no remote resources, and absence of unsafe DOM sinks.
3. Verify unauthenticated requests reveal no project metadata; non-loopback bind
   remains explicit; errors/logs never expose bearer tokens, unpublished content,
   or arbitrary filesystem paths.
4. Update `docs/GENERATIVE_UI.md`, run Ruff, all generative-UI and CLI integration
   tests, `make check`, coverage for owned production modules, and a wheel
   package-data inspection.

## Epic exit gate

The Epic is complete only when a user can securely navigate at least the seven
registered workspace views against real `ProjectRuntime` fixtures, inspect only
content-addressed visible artifacts, understand run/stage/paper/proposal state,
survive restart/concurrency/tamper tests, and never cross the proposal-only trust
boundary. Static mockups or synthetic fixture screenshots alone do not pass.

No real provider call, controller approval, tool execution, or external network
service is authorized.

## Autonomous handoff

Do not request a new task token after WP1, WP2, or WP3. Continue unless a genuine
cross-owned change or security/dependency decision blocks the Epic. At the final
handoff report each WP commit SHA, exact tests and coverage, package verification,
remaining browser/security limits, compatibility/dependency notes, and a clean
worktree. Do not merge or push `main`.

Previous integrated Epic: `W3-generative-ui-app-20260905-r1`, branch handoff
`03573f5`, integrated and subsequently hardened on main.
