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
- A first-party AutoResearchClaw bootstrap creates and verifies the Stage 1–2
  prerequisite inside a registered project run. Its immutable source receipt can
  feed a selected Stage 3 action without an unowned external run directory.
- The selected-action lifecycle copies that source into immutable inputs, runs
  against a separate working tree, binds both configuration contents, the source
  receipt, and the upstream pin, and registers only hashed verification evidence.

The manifest accepts extension fields so the existing FLOOR preacceptance and
SciTaste self-development records remain readable. Canonical fields stay strict;
unknown historical metadata is preserved during updates.

Registered run metadata may be finalized with `ProjectRuntime.update_run`. The
operation cannot change run identity and uses the same expected-revision guard;
the full workflow uses it to record completion/failure, the final-state locator,
and readable per-stage records.

The Phase 9 matched-study consumer uses `ProjectMatchedStudyRunner`. It registers
the study as one project run, exposes the run's `study/` directory through the
normal current-stage alias, and binds its protocol, plan, launcher configuration,
aggregate results, and cell checkpoints by hash. A subset execution remains
`partial`; only all planned successful cells produce `complete`. Failed and
partial runs may resume under their registered identity, while complete, running,
changed, or tampered runs fail closed. A project revision changed during a long
cell execution is not reacquired at finalization.

`substrate project bootstrap plan|execute|status` owns the prerequisite source;
`substrate project plan|execute|status` owns one selected AutoResearchClaw stage.
Both live paths are double-gated by their versioned workflow configuration and
explicit `--allow-live`. Failed attempts may resume only after immutable inputs
and registered identity revalidate; an already persisted successful bootstrap
executor result is finalized without paying for the same call again.

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

Run selected matched-study cells inside an existing project with:

```bash
.venv/bin/scitaste study project-run \
  --config configs/experiments/matched_budget_local_pilot_v1.yaml \
  --launch-config path/to/reviewed-launchers.yaml \
  --project-id my-research-project --run-id phase9-local-pilot \
  --provider local --model Qwen3-VL-4B-Instruct \
  --condition autoresearchclaw --max-cells 1 --dry-run
```

The command derives its output directory from the project and run IDs rather
than accepting an unrelated `--output`. Resume is explicit with `--resume` and
requires an integrity-checked registered run whose status is `partial` or
`failed`.

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

The first full lifecycle consumer is documented in
[`FULL_WORKFLOW.md`](FULL_WORKFLOW.md).
The project-owned matched-study consumer is documented in
[`MATCHED_BUDGET_STUDY.md`](MATCHED_BUDGET_STUDY.md).
