# SciTaste repository guide

## Authority and scope

- Implement against `PROJECT_SPEC.md` and the workspace's full v1.1 specification.
- Work on one `docs/ROADMAP.md` phase at a time and preserve its exit gate.
- SciTaste selects research actions; executors only execute the selected action.
- Never put SciTaste control logic in `third_party/autoresearchclaw`.

## Development commands

```bash
git submodule update --init
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
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
