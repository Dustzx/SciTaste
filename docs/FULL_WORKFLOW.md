# Project-owned full workflow

`scitaste run full` is the first-party offline composition of SciTaste's Phase
4--7 workflows. It is a real deterministic execution path, not a reserved CLI
or four disconnected demos. Discovery creates the initial `ResearchState`;
Evidence, Communication, reviewer-driven evidence collection, and Figure
generation each load and extend that same state history.

Run the committed acceptance case with:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project \
  --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-reviewed-draft \
  --seed 7 --output outputs
```

The default backend is `mock`. It executes the full controller, state,
criticism, revision, packaging, and project-management code without a model API.
Its output is integration evidence, not evidence that SciTaste improves research
effectiveness. `--dry-run` validates the configuration and prints the planned
project/run/paper identity without writing files.

## Project layout

One execution owns this tree:

```text
outputs/projects/<project-id>/
├── PROJECT.json
├── runs/<run-id>/
│   ├── full_run_summary.json
│   └── stages/
│       ├── discovery/
│       ├── evidence/
│       ├── communication/
│       └── figure/
├── stages/current -> ../runs/<run-id>/stages
├── papers/<paper-directory>/
│   ├── MANIFEST.json
│   ├── main.md
│   ├── main.tex
│   ├── main.pdf              # when XeLaTeX is available
│   ├── build.json
│   └── figures/{figure.svg,figure.drawio}
├── papers/current -> <paper-directory>
└── surfaces/<run-id>-snapshot-binding.json
```

Each stage contains `STAGE.json`, which states its purpose and points to its
local summary, decision log, and latest state. Paths recorded by the full-run
summary are run-relative rather than machine-specific absolute paths.

The paper is a registered, reviewed draft with `publication_ready: false`.
Markdown-to-TeX packaging is deterministic and performs no extra model call. If
`latexmk` with XeLaTeX is installed, compilation must succeed and `main.pdf` is
registered; otherwise `build.json` records `unavailable` and the Markdown/TeX
bundle remains complete.

## Revision and failure behavior

The workflow creates the project when it does not exist, otherwise it requires
the existing research identity to match. Every run ID must be new. Repeated
iterations in one project should use a new `--run-id` and
`--paper-directory`; historical runs and paper versions are never overwritten.

Project mutations use the same optimistic revisions and file locks as manual
project commands. A successful run is selected, marked complete, linked to its
final state and stage records, and owns the selected paper. If a later phase
fails, completed stage artifacts remain in place and the registered run is
marked `failed` with the exception type and bounded message for diagnosis.

After completion, `ProjectSnapshotAdapter` hashes the authoritative manifest,
run tree, current stage, paper manifest, and every declared paper artifact into
`surfaces/<run-id>-snapshot-binding.json`. That record can ground a trusted
Generative UI surface but has no execution authority.

## Configuration boundary

`configs/workflows/full_offline_v1.yaml` chooses the four typed scenario files
and owns the canonical project/publication identity. Scenario files contribute
phase-specific claims, evidence, narrative contracts, review feedback, and
figure contracts; their standalone demo project IDs are replaced and revalidated
against the full-workflow project. This permits reusable phase fixtures without
splitting the resulting project state.

AutoResearchClaw is not modified or invoked by this offline acceptance case. A
later live/full executor mode must preserve the same ProjectRuntime ownership,
state-continuity, evidence-binding, and failure-retention contracts.
