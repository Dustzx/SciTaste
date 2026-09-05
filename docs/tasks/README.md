# Parallel Window Dispatch

This directory is the temporary coordination channel for independent Codex
windows. The main window owns and updates every dispatch document. A child
window reads its assigned document from the canonical main worktree before each
work session; it does not edit these files on its feature branch.

Canonical paths:

- board: `/home/good/zfx/papers/SciTaste/docs/tasks/BOARD.md`;
- Window 2: `/home/good/zfx/papers/SciTaste/docs/tasks/WINDOW_2.md`;
- Window 3: `/home/good/zfx/papers/SciTaste/docs/tasks/WINDOW_3.md`.

## Dispatch threshold and autonomy window

A task belongs in a child window only when it is an independently reviewable
engineering track that would normally occupy at least one to two focused working
days. It should own a coherent subsystem boundary, contain multiple ordered work
packages, require implementation plus tests and documentation, and end in
several self-contained commits with measurable acceptance gates.

One assignment token authorizes every numbered work package in that Epic. After
an internal work package passes its focused checks, the child commits it and
continues directly to the next package; it does not stop for a new token, main-
window acknowledgement, or integration review. It reports one consolidated
handoff only after the Epic exit gate is met, or earlier when a genuine scope,
security, dependency, destructive-operation, or cross-window ownership blocker
requires main-window authority. A fast implementation is acceptable, but
completion is judged against all work packages and exit evidence rather than
elapsed time.

Do not dispatch one-file fixes, formatting, catalog refreshes, isolated tests,
small documentation edits, merge-conflict cleanup, or exploratory commands.
The main window handles those directly or batches them into a later coherent
Epic. An idle child window is preferable to parallel work whose coordination
cost exceeds its implementation value.

## Ownership and isolation

Each child uses its assigned worktree and feature branch. It may edit only the
paths named in its task document. The main window owns cross-cutting files such
as `AGENTS.md`, `README.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, and
`CHANGELOG.md` unless the task explicitly delegates one of them.

Generated outputs, credentials, provider responses, datasets, and papers stay
outside Git. AutoResearchClaw remains immutable. A child must not obtain missing
authority by silently expanding its task scope.

Because the dispatch documents live in the main worktree, a child should read
them using the absolute paths above rather than a possibly stale feature-branch
copy. If the task revision or assignment token changes, the newest main-worktree
document wins.

## Required child-window startup

At the start of every child-window turn:

1. read the repository `AGENTS.md` in the assigned worktree;
2. read the complete assigned `WINDOW_N.md` from the canonical path;
3. confirm that its assignment token, branch, worktree, and base commit match;
4. inspect the named owned paths and current tests before editing;
5. stop and report a mismatch instead of switching another window's branch.

The user can initialize a window with one durable instruction:

```text
You are Window 2 (or Window 3). Before every task, read your canonical dispatch
document under /home/good/zfx/papers/SciTaste/docs/tasks/ completely and follow
its assignment, worktree, ownership, acceptance, and handoff requirements.
```

## Handoff contract

A completed child task reports to the main window:

- final commit SHA and branch;
- files and public behavior changed;
- exact tests run and their outcomes;
- any unverified behavior or retained blocker;
- migration, dependency, security, and compatibility notes;
- confirmation that the worktree is clean.

For a multi-package Epic, the handoff also lists the commit corresponding to
each work package. The child does not merge, push `main`, rewrite shared history,
or claim real
provider/effectiveness evidence from fixtures. The main window reviews the diff,
runs integration checks, performs cross-cutting documentation updates, merges,
and changes the board status.
