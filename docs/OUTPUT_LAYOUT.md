# Output layout and naming

Generated outputs are intentionally Git-ignored. A research project is the
primary ownership boundary: its runs, experiments, evidence, reviews, and paper
versions stay together. Use `outputs/INDEX.md` as the human entry point and
`outputs/catalog.json` for machine-readable discovery.
Refresh both files with:

```bash
.venv/bin/python scripts/catalog_outputs.py outputs
```

The canonical hierarchy is:

```text
outputs/projects/<project-id>/
├── PROJECT.json
├── README.md
├── STAGES.md
├── runs/
│   └── YYYY-MM-DD__provider-model__condition__seed-NN/
├── stages/
│   └── current -> ../runs/<current-run>/upstream_run
└── papers/
    ├── YYYY-MM-DD__provider-model__condition__stage-NN/
    └── current -> <selected paper version>
```

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
