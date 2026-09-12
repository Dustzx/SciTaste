# SciTaste repository guide

## Authority and scope

- Implement against `PROJECT_SPEC.md` and the workspace's full v1.1 specification.
- Work on one `docs/ROADMAP.md` phase at a time and preserve its exit gate.
- SciTaste selects research actions; executors only execute the selected action.
- Never put SciTaste control logic in `third_party/autoresearchclaw`.

## Development commands

```bash
git submodule update --init
python3.12 -m venv .venv
.venv/bin/pip install -c requirements/python312-dev-study.lock -e '.[dev,study]'
make check
make demo
```

## Change discipline

- Treat the submodule pin as immutable except in a dedicated dependency update.
- Keep public models backward-compatible or increment `schema_version` and add a
  migration.
- New controller decisions require deterministic tests and decision-log coverage.
- New execution backends implement `ResearchExecutor` and remain lazy imports.
- Do not commit secrets, configs, generated outputs, papers, datasets, or API
  responses.
- Update the roadmap, changelog, and relevant architecture record with material
  behavior changes.

## Parallel window coordination

- Multi-window work uses the canonical dispatch documents in `docs/tasks/`.
  The main window owns the board and task documents; child windows read their
  assigned absolute-path document before every task.
- Only cohesive, independently testable Epics expected to require at least half
  a focused day are dispatched. Small fixes remain on main because their
  coordination cost exceeds their parallelism benefit.
- Child windows use separate worktrees, stay inside assigned path ownership, and
  return clean feature-branch commits to main for review and integration.
