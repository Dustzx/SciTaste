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
├── papers/
    ├── YYYY-MM-DD__provider-model__condition__stage-NN/
    └── current -> <selected paper version>
└── surfaces/
    └── <surface-version>/{surface.json,renderer.json,surface-audit.jsonl}
```

`PROJECT.json` has a monotonic `revision`. Every managed mutation supplies the
previous revision, preventing concurrent API workers or Codex worktrees from
silently overwriting each other's project metadata.

Each paper directory contains a `MANIFEST.json`. `outputs/papers/` is only a
cross-project alias layer; `outputs/papers/latest` points to the most recently
selected paper but does not own it.

Trusted project interface bundles live under the same owner in `surfaces/`.
`outputs/INDEX.md` lists these bundles beside the project, and
`outputs/catalog.json` records their files and surface fingerprint. A surface is
a content-addressed view and proposal channel, not an executor or project-state
mutation endpoint.

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

The default native executor keeps cross-stage action evidence beside that stage
tree:

```text
runs/<run-id>/native_execution/{context,artifacts,records}/
```

`context/` contains the content-bound local Knowledge copy, `artifacts/`
contains exact handler outputs such as ranked retrieval results, and `records/`
is the contiguous predecessor-hashed action chain. Stage decision logs bind the
record identities. See [`NATIVE_EXECUTION.md`](NATIVE_EXECUTION.md).

A project-owned AutoResearchClaw source bootstrap has its own explicit boundary:

```text
runs/<bootstrap-run-id>/
├── bootstrap_manifest.json
├── inputs/autoresearchclaw-config.yaml
├── work/autoresearchclaw/             # exact Stage 1-2 executor output
├── source/autoresearchclaw/           # immutable verified reusable copy
├── substrate_bootstrap/{executor_result.json,source_receipt.json}
└── failed_attempts/attempt-NNN/       # only after a resumable failed attempt
```

`source_receipt.json` binds both trees, the required Stage 1–2 artifacts, token
telemetry, truthful API-cost availability, and the pre-call manifest. A selected
action refers to this receipt by `source_project_run_id` instead of relying on an
unregistered historical path.

The selected AutoResearchClaw action then uses a separate boundary:

```text
runs/<run-id>/
├── substrate_manifest.json
├── inputs/{autoresearchclaw/,autoresearchclaw-config.yaml}
├── work/autoresearchclaw/
├── substrate_action/{decisions.jsonl,executor_result.json,research_state.json,
│                    substrate_summary.json,verification.json}
└── failed_attempts/attempt-NNN/  # only after a resumable failed attempt
```

`inputs/` is immutable evidence; provider-backed mutation occurs only in
`work/`. `substrate project bootstrap status` rehashes the bootstrap work and
source, while `substrate project status` rehashes the selected-action input,
working tree, and evidence before reporting either run as verified.

Normal bounded model-node calls belong to the selected project run:

```text
runs/<run-id>/model_nodes/
├── ledger/       # contiguous predecessor-bound outcome entries
├── recordings/   # exact record/replay evidence without authorization headers
├── pending/      # interruption markers
└── attempts/     # preserved incomplete or failed attempts
```

An opted-in full workflow first publishes
`runs/<run-id>/stages/evidence/model_advisory_input.json`, which binds the exact
predecessor state, evidence state, decision log, evidence summary, invocation
identity, policy, profile, and advisory configuration before provider access.
It then links the project-level ledger through `model_advisory.json`.
`STAGE.json` hashes both records; the result record binds the immutable state
snapshot, accepted proposal (if any), exact runtime receipt, and complete ledger
head. The paper remains under the same project's
`papers/<paper-directory>/` tree.

The generative workspace keeps project-wide UI evidence outside any one research
run because it may compare several runs and papers:

```text
outputs/projects/<project-id>/.generative-ui/audits/*.jsonl
```

Each audit chain is bound to that project and contains proposal-only or read-only
inspection receipts. It never owns controller approvals or executions.
