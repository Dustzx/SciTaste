# Project runtime

`ProjectRuntime` makes a research project the writable ownership boundary instead
of treating `outputs/` as a collection of unrelated command directories. It
manages versioned `PROJECT.json` state, registered runs, paper bundles, current
navigation aliases, and a content-hashed `ProjectSnapshot` for catalogs and
future generated interfaces.

## Safety and concurrency

- Project IDs are lowercase kebab-case; run and paper directory IDs are one safe
  path segment. Owned locators are normalized POSIX-relative paths.
- Every mutation takes an OS file lock, requires the caller's
  `expected_revision`, increments `revision`, and atomically replaces
  `PROJECT.json`. A stale caller receives `ProjectRevisionConflictError` rather
  than silently overwriting a concurrent update.
- Project creation is prepared in a temporary sibling directory and renamed only
  after `PROJECT.json`, `README.md`, `STAGES.md`, `runs/`, `stages/`, and
  `papers/` exist.
- `stages/current`, `papers/current`, and `outputs/papers/latest` are replaceable
  only when they are symlinks. A user-owned real file or directory is never
  overwritten.
- A paper can be registered only after every declared file exists inside that
  paper bundle. Symlink escapes and path traversal are rejected.
- AutoResearchClaw remains unmodified. A registered run may designate an
  `upstream_run` stage path, while a self-development run may expose its own root.

The manifest accepts extension fields so the existing FLOOR preacceptance and
SciTaste self-development records remain readable. Canonical fields stay strict;
unknown historical metadata is preserved during updates.

## CLI

Create and inspect a project:

```bash
.venv/bin/scitaste project init \
  --project-id my-research-project \
  --title "My research project" \
  --research-direction "Test a falsifiable research direction" \
  --target-domain machine-learning \
  --outputs-root outputs

.venv/bin/scitaste project status \
  --project-id my-research-project \
  --outputs-root outputs
```

The status response includes the current revision. Supply it when registering or
selecting a run:

```bash
.venv/bin/scitaste project run begin \
  --project-id my-research-project \
  --run-id 2026-09-04__local-qwen__full-scitaste__seed-07 \
  --provider local --model qwen3-vl-4b \
  --condition full_scitaste --seed 7 \
  --stage-path upstream_run --expected-revision 0 \
  --outputs-root outputs

.venv/bin/scitaste project run select \
  --project-id my-research-project \
  --run-id 2026-09-04__local-qwen__full-scitaste__seed-07 \
  --expected-revision 1 --outputs-root outputs
```

Paper generation materializes files beneath
`outputs/projects/<project-id>/papers/<paper-directory>/` first. Register its
`MANIFEST.json` contract, then explicitly select it:

```bash
.venv/bin/scitaste project paper register \
  --project-id my-research-project \
  --directory-name 2026-09-04__local-qwen__full-scitaste__stage-18 \
  --manifest /path/to/paper-manifest.json \
  --expected-revision 2 --outputs-root outputs

.venv/bin/scitaste project paper select \
  --project-id my-research-project \
  --directory-name 2026-09-04__local-qwen__full-scitaste__stage-18 \
  --expected-revision 3 --outputs-root outputs
```

All mutating commands support `--dry-run`. Dry-run validates IDs, schemas, and
the expected revision without creating or changing files.

## Snapshot boundary

`ProjectSnapshot` uses project-relative locators and hashes the validated project
manifest, registered paper manifests, current selections, and warnings. It is a
read model, not an execution capability.

`ProjectSnapshotAdapter.build_binding(project_id)` reopens that authoritative
view and turns the project manifest, registered runs, current stage, paper
manifests, and declared paper files into project-relative, content-addressed UI
evidence. Missing entries, containment escapes, and nested symlinks fail closed.
Its evidence-manifest hash is intentionally distinct from
`ProjectSnapshot.snapshot_sha256`: the former includes artifact bytes displayed
by a surface, while the latter identifies runtime registry state. UI actions
still return to the deterministic controller and revision gate before mutation.
