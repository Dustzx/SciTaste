# Contributing

## Workflow

1. Start from a tracked issue whose scope names one roadmap milestone.
2. Create a short-lived branch: `feat/<issue>-description`,
   `fix/<issue>-description`, or `docs/<issue>-description`.
3. Keep SciTaste control logic outside `third_party/autoresearchclaw`.
4. Add or update tests and decision-log fixtures with behavioral changes.
5. Run `make check` before opening a pull request.
6. Use a conventional commit subject (`feat:`, `fix:`, `docs:`, `test:`,
   `refactor:`, `chore:`).

## Definition of done

- milestone acceptance criteria are met;
- public behavior is documented;
- deterministic tests cover success and failure paths;
- decisions and state changes remain auditable;
- no secrets, generated outputs, or local configs are committed;
- the changelog is updated for user-visible changes;
- the pull request identifies specification clauses and deferred work.

## Dependency policy

SciTaste's default development and test path is first-party and does not require
AutoResearchClaw. AutoResearchClaw is an optional Git submodule pinned to an
audited release commit for baseline and compatibility work. Update it only in a
dedicated pull request containing upstream release notes, adapter compatibility
results, and a rollback commit. Do not edit its internals from a SciTaste feature
branch.

## Releases

Release from a clean `main` after CI passes. Tag `vMAJOR.MINOR.PATCH`; add a
changelog section, record the project-spec version, and archive test and benchmark
metadata (not credentials or large generated artifacts).
