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
.venv/bin/scitaste project paper build --help
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

A venue-native bundle additionally contains `main.md`, `main.tex`, `main.pdf`,
`references.bib`, `build.json`, `MANUSCRIPT_ASSESSMENT.json`, and
`SUBMISSION_ASSESSMENT.json`, together with exact hash-verified venue assets.
The submission assessment records the template fingerprint, citation closure,
anonymous-mode checks, required statements, main-text page count, and its own
content hash. These are packaging and compliance facts, not a publication or
scientific-quality verdict.

Trusted project interface bundles live under the same owner in `surfaces/`.
`outputs/INDEX.md` lists these bundles beside the project, and
`outputs/catalog.json` records their files and surface fingerprint. A surface is
a content-addressed view and proposal channel, not an executor or project-state
mutation endpoint.

Historical test and preacceptance directories are preserved as a dedicated,
non-retrieval project rather than left as unowned roots:

```text
outputs/projects/scitaste-legacy-output-archive/runs/<original-name>/
├── ARCHIVE.json
└── payload/                 # unchanged original content tree
```

Use `scripts/migrate_legacy_outputs.py outputs` for a read-only plan. Applying a
migration requires the additional `--apply --all-discovered` flags (or one or
more exact `--directory` values). The migrator hashes each physical content tree,
moves it atomically on the same filesystem, verifies the post-move hash, and
rewrites project symlinks that referenced the old root. `ARCHIVE.json` retains
the original locator and recovery map. It does not rewrite files inside the
payload, so embedded historical paths and evidence hashes keep their original
meaning. Re-run full archive verification at any time with:

```bash
.venv/bin/python scripts/migrate_legacy_outputs.py outputs --verify
```

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

An interactively advanced native Discovery run uses immutable command steps
under one mutable, self-hashed head:

```text
runs/<run-id>/discovery/
├── DISCOVERY.json
└── steps/
    ├── 001-hypothesize/
    ├── 002-probe/
    └── .../{research_state.json,state_snapshots/,decisions.jsonl,
            discovery_command.json}
```

`PROJECT.json` records the head hash, latest state, command count, final stage,
and any pending operation. `project discovery verify` rehashes the complete tree.
The command derives every path from project/run identity; it never creates an
unowned top-level stage directory.

When `hypothesize` uses bounded semantic generation, the same run also owns
`model_nodes/ledger/` and `model_nodes/recordings/`. The first Discovery step
stores a proposal-only reference to that ledger entry; `DISCOVERY.json`, the
command receipt, and `research_state.json` all bind the same entry, request,
proposal, and recording identities. The model-node directory is a sibling of
`discovery/`, never an unowned top-level output.

Later semantic commands append references to
`executor_context.discovery_semantics`; the original singular field is retained
as a backward-compatible pointer to the initial hypothesis proposal. Each
manifest step may introduce at most its command-compatible reference, invocation
IDs cannot repeat, and every successor state must retain the complete ordered
history and its cumulative known API cost.

The `discovery-ideation` entry is introduced only by an `ideate` step after a
supported active hypothesis. Its typed ledger proposal owns the problem and
divergent idea-seed content; the subsequent `portfolio-select` step owns the
controller's selection and never appears inside the semantic response.

When that run opts into native Knowledge retrieval, it also owns:

```text
runs/<run-id>/native_execution/
├── context/{DISCOVERY_KNOWLEDGE.json,discovery_knowledge_plan.json}
├── context/libraries/knowledge/records.jsonl
├── artifacts/<result-token>/retrieval.json
└── records/000001-<action-token>.json
```

The context receipt binds the original config hash, copied library hash,
deterministic plan, retrieved document IDs, and scores. Every Discovery state
inherits the same reference. Native records form an append-only action chain;
the run metadata records the committed head while preserving any truthful
partial-attempt records for later recovery and inspection.

For a native measured run, `stages/communication/evidence_projection.json`
binds the manuscript measurement to its predecessor state, interpretation,
native execution record, and raw replicate-derived metric artifact. `paper.md`
is the trace-rich audit draft; `paper.publication.md` removes internal
claim/evidence/obligation identifiers and is the source of the project-owned
`papers/<paper-directory>/main.md`, TeX, and optional PDF bundle.

The default native executor keeps cross-stage action evidence beside that stage
tree:

```text
runs/<run-id>/native_execution/{context,artifacts,records}/
```

`context/` contains the content-bound local Knowledge copy plus the registered
experiment definition/source. `artifacts/` contains exact handler outputs such as
ranked retrieval results and bounded experiment stdout, stderr, independently
derived metrics, and execution metadata. `records/` is the contiguous
predecessor-hashed action chain. Stage decision logs bind the record identities.
See [`NATIVE_EXECUTION.md`](NATIVE_EXECUTION.md).

A project-owned AutoResearchClaw source bootstrap has its own explicit boundary:

```text
runs/<bootstrap-run-id>/
├── bootstrap_manifest.json
├── inputs/autoresearchclaw-config.yaml
├── work/autoresearchclaw/             # exact Stage 1-2 executor output
├── source/autoresearchclaw/           # immutable verified reusable copy
├── substrate_bootstrap/{executor_result.json,source_receipt.json,
│   call_protocol/{prepared.json,call_started.json,result_published.json}}
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
├── substrate_action/{invocation.json,decisions.jsonl,executor_result.json,
│   research_state.json,substrate_summary.json,verification.json,
│   call_protocol/{prepared.json,call_started.json,result_published.json}}
└── failed_attempts/attempt-NNN/  # only after a resumable failed attempt
```

`inputs/` is immutable evidence; provider-backed mutation occurs only in
`work/`. `substrate project bootstrap status` rehashes the bootstrap work and
source, while `substrate project status` rehashes the selected-action input,
working tree, and evidence before reporting either run as verified. A successful
`invocation.json` is published before provider access and binds the exact state,
action, decision intent, and project manifest. `executor_result.json` binds that
invocation and the complete normalized work tree. Resume may finish missing
deterministic files in place, while an unknown, changed, or contradictory outcome
is retained and blocked rather than archived and called again.

The three call-protocol records are immutable and predecessor-hashed. They bind
the project/run identity, external-attempt number, request, exact non-secret call
specification, pre-call work fingerprint, call-start receipt, result file,
result identity/status, and final work fingerprint. Project metadata caches the
latest phase for navigation, but the files are authoritative and a cache that is
ahead of them is rejected.

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
