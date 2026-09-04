# Output layout and naming

Generated outputs are intentionally Git-ignored. A research project is the
primary ownership boundary: its runs, experiments, evidence, reviews, and paper
versions stay together. Use `outputs/INDEX.md` as the human entry point and
`outputs/catalog.json` for machine-readable discovery.
Refresh both files with:

```bash
.venv/bin/python scripts/catalog_outputs.py outputs
```

New projects and their current run/paper selections should be managed through
the revision-guarded runtime rather than by editing symlinks manually:

```bash
.venv/bin/scitaste project status --project-id <project-id> --outputs-root outputs
.venv/bin/scitaste project run begin --help
.venv/bin/scitaste project paper register --help
```

See [`PROJECT_RUNTIME.md`](PROJECT_RUNTIME.md) for creation, registration,
selection, dry-run, and optimistic-concurrency examples.

The canonical hierarchy is:

```text
outputs/projects/<project-id>/
├── PROJECT.json
├── README.md
├── STAGES.md
├── runs/
│   └── YYYY-MM-DD__provider-model__condition__seed-NN/
├── stages/
│   └── current -> ../runs/<current-run>/<registered-stage-path>
└── papers/
    ├── YYYY-MM-DD__provider-model__condition__stage-NN/
    └── current -> <selected paper version>
```

`PROJECT.json` has a monotonic `revision`. Every managed mutation supplies the
previous revision, preventing concurrent API workers or Codex worktrees from
silently overwriting each other's project metadata.

Each paper directory contains a `MANIFEST.json`. `outputs/papers/` is only a
cross-project alias layer; `outputs/papers/latest` points to the most recently
selected paper but does not own it.

Historical test and preacceptance directories are not renamed automatically. Cell requests,
execution records, resumable checkpoints, reports, and artifact manifests can
contain path-dependent identities or hashes. The catalog provides stable aliases
without invalidating that evidence.

Within a raw AutoResearchClaw run, `stage-16/outline.md` is an outline,
`stage-17/paper_draft.md` is the generated draft, and `stage-18/reviews.md` is
the review. The paper bundle beneath its project is easier to consume: `paper.md`,
`paper.tex`, and `paper.pdf` are the reader-facing manuscript, while
`peer_review.md`, `evidence.json`, and `audit.json` explain its acceptance state.
Stage 18 means that review feedback exists; it does not mean every concern has
been resolved or that the paper is publication-ready.

Framework self-development and other non-paper projects still receive their own
`outputs/projects/<project-id>/` root. They may leave `completed_stages` empty and
must declare alternate milestone semantics in `PROJECT.json` and `STAGES.md`
rather than pretending that project-management decisions completed
AutoResearchClaw stages.

The offline `scitaste run full` composition uses a named, human-readable stage
tree beneath its registered run:

```text
runs/<run-id>/stages/{discovery,evidence,communication,figure}/
```

Every directory has a `STAGE.json` explaining what it completed. Its paper is
owned by the same project and contains `main.md`, `main.tex`, `build.json`, an
optional compiled `main.pdf`, and editable SVG/draw.io figure files. See
[`FULL_WORKFLOW.md`](FULL_WORKFLOW.md).
