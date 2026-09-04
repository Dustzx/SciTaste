# Output layout and naming

Generated outputs are intentionally Git-ignored. Use `outputs/INDEX.md` as the
human entry point and `outputs/catalog.json` for machine-readable discovery.
Refresh both files with:

```bash
.venv/bin/python scripts/catalog_outputs.py outputs
```

New raw studies should use
`outputs/runs/YYYY-MM-DD__study__provider-model__scope/`. Publication bundles
use `outputs/papers/YYYY-MM-DD__provider-model__condition__task__stage-NN/` and
contain a `MANIFEST.json`. The `outputs/papers/latest` link points to the newest
bundle.

Historical top-level directories are not renamed automatically. Cell requests,
execution records, resumable checkpoints, reports, and artifact manifests can
contain path-dependent identities or hashes. The catalog provides stable aliases
without invalidating that evidence.

Within a raw AutoResearchClaw run, `stage-16/outline.md` is an outline,
`stage-17/paper_draft.md` is the generated draft, and `stage-18/reviews.md` is
the review. A SciTaste publication bundle is easier to consume: `paper.md`,
`paper.tex`, and `paper.pdf` are the reader-facing manuscript, while
`peer_review.md`, `evidence.json`, and `audit.json` explain its acceptance state.
Stage 18 means that review feedback exists; it does not mean every concern has
been resolved or that the paper is publication-ready.
