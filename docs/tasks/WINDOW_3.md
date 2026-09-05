# Window 3 Dispatch: Trusted Generative-UI Application Boundary

Assignment token: `W3-generative-ui-app-20260905-r1`

Status: `integrated; awaiting next Epic`

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/generative-ui`
- branch: `feat/generative-ui-app-boundary`
- base: the main commit containing this dispatch document
- do not work in `/home/good/zfx/papers/SciTaste`

## Objective

Build the first usable local application boundary for the trusted generative
interface: a receiver-owned browser shell plus authenticated, loopback-first API
that reads authoritative projects, builds current surfaces, and accepts only
identity-only proposal events. It must remain impossible for generated content
or a browser client to execute tools, inject renderer code, or mutate research
state.

This is a product-boundary Epic, not a static mockup or a few generated HTML
files.

## Owned paths

- `src/scitaste/generative_ui/` for application/session/API/rendering additions;
- a new focused CLI module beneath `src/scitaste/` and the smallest necessary
  registrations in `src/scitaste/cli.py`;
- receiver-owned static assets in a package-data path, with any necessary
  `pyproject.toml` packaging declaration;
- `tests/generative_ui/` and focused `tests/integration/` coverage;
- `docs/GENERATIVE_UI.md`.

Do not edit common roadmap, architecture, changelog, README, model-node code,
full workflow code, AutoResearchClaw, or generated `outputs/`.

## Required behavior

1. Provide a local application/service object around `ProjectRuntime`,
   `ProjectSurfaceFactory`, `SurfaceSession`, and `SurfaceAuditLog`. Every request
   must resolve a canonical project ID and current trusted server-owned surface;
   client-authored surfaces, components, proposal payloads, or evidence are
   invalid.
2. Provide a receiver-owned HTML/CSS/JavaScript shell that renders the closed
   component registry. Untrusted text must use text nodes/`textContent`; no
   `innerHTML`, dynamic script, evaluated markup, remote asset, model-generated
   renderer, or command-bearing field is allowed.
3. Expose a small versioned JSON API for project discovery, current project
   surface retrieval, and proposal-event submission. Event input remains the
   existing identity-only `SurfaceEvent`; success returns only the existing
   proposal-pending receipt with execution authority `none`.
4. Authenticate API and non-public asset requests with a configured bearer token
   or equivalently narrow local session credential. Compare secrets safely; do
   not accept credentials in query strings, persist them, or include them in
   logs/errors. Bind to loopback by default and require an explicit unsafe-mode
   acknowledgement before a non-loopback bind.
5. Revalidate project revision, evidence hashes, surface fingerprint, and event
   identity at interaction time. Stale tabs, changed artifacts, duplicate event
   IDs, cross-project identities, and forged receipts must fail closed.
6. Persist accepted proposal receipts in a project-owned hash-chained audit log
   without granting execution authority. Concurrent requests must not lose or
   reorder accepted events. Define and test the behavior after a process restart.
7. Add a CLI entry point for serving the local application with explicit outputs
   root, host, port, and credential-source configuration. Help/dry-run/config
   validation must not open a listening socket.
8. Keep project/artifact locators contained. Do not add a general filesystem or
   arbitrary artifact-download endpoint. If artifact viewing is included, it
   must be allowlisted from current content-addressed evidence and rehashed on
   access.

Prefer the existing dependency set. If a new server dependency is genuinely
necessary, isolate it behind an optional extra, justify it in the handoff, and
ensure importing core SciTaste still works without that extra.

## Tests and acceptance

At minimum test:

- a real `ProjectRuntime` fixture renders through the packaged fixed shell;
- HTML/script-like evidence is displayed inertly and cannot alter the DOM model;
- unauthenticated, malformed, cross-project, stale, duplicated, and tampered
  requests are rejected without state mutation;
- valid proposal submission returns `proposal_pending`/`none`, extends a
  replayable audit chain exactly once, and never invokes a controller or tool;
- project/artifact changes between GET and POST invalidate the old event;
- restart recovery retains duplicate-event protection and audit integrity;
- concurrent valid events serialize without lost records;
- default host is loopback and non-loopback configuration is fail-closed;
- package builds include all fixed renderer assets.

Run focused tests, Ruff for owned files, a wheel/package-data check, and the
complete `make check`. Do not make real provider calls or execute proposals.

## Handoff

Return a clean feature branch with cohesive commits and the standard handoff
fields from `docs/tasks/README.md`. Document the exact trust boundary that still
separates a proposal receipt from controller approval and execution. Do not merge
or push `main`.

Handoff `03573f5` was reviewed and integrated through main commit `372a0a9`.
Do not start another assignment from this document until its token and status
are replaced.
