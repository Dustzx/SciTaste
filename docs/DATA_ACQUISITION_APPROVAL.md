# Data acquisition approval

SciTaste separates choosing data from downloading, ingesting, and executing it.
An acquisition request is an exact URL and destination allowlist with immutable
source revisions, per-file byte ceilings, license scope, retained evidence, and
an owner-approval hash. Inspecting the request performs no network operation.

The first bounded request is
`configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml`. It
contains only the ten MLR-Bench research-brief Markdown files at repository
commit `f728d571a992d71c8b526eeb4d9ab6bb5c8cc824`:

- one HTTPS source URL and one non-existing destination per brief;
- only `raw.githubusercontent.com` on the host allowlist;
- a 1-MiB ceiling per file and 10-MiB aggregate ceiling;
- MIT scope limited to the pinned repository brief file;
- no downstream dataset, checkpoint, code, or runtime asset;
- no redirects, overwrites, ingestion, experiment execution, or claim authority.

Inspect it with:

```bash
.venv/bin/scitaste evaluation acquisition-request \
  --manifest configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml \
  --workspace-root . --require-review-ready
```

The current request SHA-256 is
`f1333432cb0585105ec4d6274e7d78b2d7d0694141256483467887ea6d27cc69`.
It is ready for owner review but has `download_authorized=false`. Approval must
name this exact hash, owner, timezone-aware timestamp, and the
`download-only-no-ingestion` scope. The current repository request remains
unapproved; short acknowledgements or general permission to continue
development are not interpreted as acquisition approval.

The software path is deliberately split into three commands:

```bash
# 1. Inspect only: no network access and no file acquisition.
.venv/bin/scitaste evaluation acquisition-request \
  --manifest configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml \
  --workspace-root . --require-review-ready

# 2. Only after an explicit owner decision: create an immutable approved copy.
.venv/bin/scitaste evaluation acquisition-approve \
  --manifest configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml \
  --workspace-root . \
  --confirm-request-sha256 f1333432cb0585105ec4d6274e7d78b2d7d0694141256483467887ea6d27cc69 \
  --approved-by '<owner identity>' --approved-at '<timezone-aware ISO-8601>' \
  --output '<new approved-request path>'

# 3. A separate explicit action performs only the approved download transaction.
.venv/bin/scitaste evaluation acquisition-download \
  --manifest '<approved-request path>' --workspace-root . \
  --confirm-request-sha256 f1333432cb0585105ec4d6274e7d78b2d7d0694141256483467887ea6d27cc69 \
  --allow-network-download
```

The approval command cannot access the network and refuses to replace an
existing output. The downloader rechecks the evidence, approval hash, empty
destination, host allowlist, immutable source revision, media type, per-item
and aggregate byte ceilings, and the explicit execution switch. It refuses
redirects and publishes the files together with a self-hashed `RECEIPT.json`
only after the entire transaction succeeds. Any transfer or hash failure
removes the staging transaction. The receipt records observed content hashes
but grants neither ingestion nor experiment-execution authority.

## Standing download policy

On 2026-09-12 the project owner granted standing automatic approval for each
already frozen acquisition transaction whose aggregate ceiling is no greater
than 10,000,000,000 bytes (decimal 10 GB). The machine-readable policy is
`configs/evaluation/acquisition/standing_owner_download_policy_v1.yaml`.

The policy removes a conversational round trip; it does not weaken the request
gate. Each transaction still needs an exact semantic hash, scientific purpose
and claim boundary, verified acquisition licenses, pinned HTTPS sources, an
allowlisted host, bounded items, and an empty workspace-contained destination.
The executor still creates an immutable approved derivative and invokes the
atomic downloader as separate operations.

Automatic approval ends when the receipt is written. It grants no permission
to parse or inspect the content, extract an archive, ingest data, run downloaded
code, load a model, call an API, use a GPU or SSH host, involve human reviewers,
admit a benchmark, or make a scientific claim. Those actions retain their own
review and execution gates. A transaction above decimal 10 GB requires a new
explicit owner decision, and the policy never creates or expands an unfrozen
request.

## Structured benchmark metadata

Acquired InnovatorBench YAML and EXP-Bench CSV remain unopened after their
download receipts. Their format-aware control path first creates a no-read plan:

```bash
.venv/bin/scitaste evaluation acquisition-metadata-audit-plan \
  --approved-request '<approved request>' --receipt '<receipt>' \
  --output '<new plan path>'
```

The plan binds the exact acquisition chain and explicit byte, structural, and
table ceilings but keeps local content authority false. Only an explicit owner
decision can create its approval. When several acquired benchmark sources form
one scientific decision, their existing plans and receipts can first be bound
into one project-visible gate without opening any source body:

```bash
.venv/bin/scitaste evaluation acquisition-metadata-audit-plan-bundle \
  --project-id '<project ID>' --run-id '<project run ID>' \
  --project-root 'outputs/projects/<project ID>' \
  --plan '<first plan>' --plan '<second plan>' \
  --receipt '<first receipt>' --receipt '<second receipt>' \
  --output 'outputs/projects/<project ID>/runs/<project run ID>/metadata_audit_planning/BUNDLE.json'
```

The bundle replays every plan/receipt binding, verifies the current auditor
implementation hash, totals the exact item and byte ceilings, and grants no
content-read or downstream authority. Once registered as the run artifact, it
becomes the explicit next scientific-data gate in Generation-as-Content rather
than another generic acquisition card. Approval remains per exact plan:

```bash
.venv/bin/scitaste evaluation acquisition-metadata-audit-approve \
  --plan '<plan path>' --confirm-plan-sha256 '<exact semantic hash>' \
  --approved-by '<owner identity>' --approved-at '<timezone-aware ISO-8601>' \
  --output '<new approval path>'
```

Execution then requires the approved request, receipt, plan, approval, and a
separate `--allow-local-content-read` switch. It rehashes the inventory and
performs bounded YAML/CSV structural checks only. The report may enable a later
metadata-screen proposal; it cannot project task values, resolve URLs, ingest a
dataset, execute code, or start an experiment.

When that report passes, SciTaste still does not jump to a hand-written task
list. A second no-read plan binds the frozen scientific scope, the complete
audit population, and an allowlist mapping every required screen field to an
observed YAML path or CSV column:

```bash
.venv/bin/scitaste evaluation benchmark-metadata-projection-plan \
  --approved-request '<approved request>' --receipt '<receipt>' \
  --audit-report '<structural audit report>' --scope '<frozen metadata scope>' \
  --workspace-root . --projection-output-root '<new relative output root>' \
  --field 'source-paper-group=<observed path or column>' \
  --field 'benchmark-category=<observed path or column>' \
  --absent-field '<required concept absent from the audited source>' \
  --output '<new projection plan>'
```

An observed mapping must occur somewhere in the audited YAML population (or in
each audited CSV header) and terminate at scalar fields. Evidence absent from
the entire source must be declared explicitly with `--absent-field`; this is an
owner-visible missingness declaration, not a fabricated mapping. If an observed
YAML path is absent from an individual record, projection retains that record
and marks the field missing. The plan also requires every source URL, pinned
revision, and upstream task path—or the single CSV table identity—to match the
pre-inspection scope exactly; equal file counts cannot substitute a different
population. The command consults neither projected values,
formal outcomes, installed models, nor compute inventory, and it cannot select
a task. The plan fixes the exact source-byte total and refuses metadata
populations above 64 MiB. Projection requires a separate exact approval and
explicit read switch:

```bash
.venv/bin/scitaste evaluation benchmark-metadata-projection-approve \
  --plan '<projection plan>' --confirm-plan-sha256 '<exact plan hash>' \
  --approved-by '<owner>' --approved-at '<timezone-aware ISO-8601>' \
  --output '<new projection approval>'

.venv/bin/scitaste evaluation benchmark-metadata-project \
  --approved-request '<approved request>' --receipt '<receipt>' \
  --audit-report '<structural audit report>' --scope '<frozen metadata scope>' \
  --plan '<projection plan>' --approval '<projection approval>' \
  --workspace-root . --projected-at '<timezone-aware ISO-8601>' \
  --output '<planned output root>/POPULATION.json' \
  --allow-local-content-read
```

Materialization rehashes every source file and reproduces the complete audited
population through only those fields. It follows no locator and preserves CSV
formula-like cells as inert text. The population is ready only for a subsequent
screen-decision proposal; it grants no selection, asset acquisition, ingestion,
model, GPU, or experiment authority.

Before any real projection exists, the source-specific rules can be checked
against the frozen scopes without reading source content:

```bash
.venv/bin/scitaste evaluation benchmark-metadata-screen-rulebook \
  --rulebook configs/evaluation/screening/innovatorbench_metadata_screen_rulebook_v1.json \
  --scope docs/research/data/innovatorbench_task_metadata_scope_v1.yaml \
  --require-ready

.venv/bin/scitaste evaluation benchmark-metadata-screen-rulebook \
  --rulebook configs/evaluation/screening/expbench_metadata_screen_rulebook_v1.json \
  --scope docs/research/data/expbench_task_metadata_scope_v1.yaml \
  --require-ready
```

InnovatorBench has five scientific eligibility rules and one separately
declared capacity-allocation rule; EXP-Bench has six scientific eligibility
rules and no capacity exclusion. Once a projection is authorized and produced,
an outcome- and resource-blind decision package must cover every projected
record crossed with every eligibility rule. Screening is then explicit:

```bash
.venv/bin/scitaste evaluation benchmark-metadata-screen \
  --population '<projected POPULATION.json>' \
  --rulebook '<frozen rulebook>' --decisions '<complete decision package>' \
  --workspace-root . --screened-at '<timezone-aware ISO-8601>' \
  --output '<new benchmark_metadata_screening/REPORT.json>' \
  --allow-projected-metadata-read --require-allocation-proposal-ready
```

The switch permits reading the already bounded projection, not the acquisition
tree. Required external judgments must be separately hash-bound evidence; raw
benchmark files and control artifacts are forbidden as attachments. Missing
evidence becomes the rule's predeclared exclusion or unresolved disposition.
The report retains the full population partition and only opens a later powered,
seeded allocation proposal. It cannot select tasks, call a model, use compute,
or execute an experiment.

Once the complete screen and a real objective-H3 clustered-power analysis both
exist, the allocation plan is still identity-free and non-authorizing:

```bash
.venv/bin/scitaste evaluation benchmark-metadata-allocation-plan \
  --screening-report '<complete screening REPORT.json>' \
  --power-request '<clustered-power REQUEST.json>' \
  --power-report '<clustered-power REPORT.json>' --workspace-root . \
  --plan-id '<new plan id>' --random-seed '<precommitted integer>' \
  --cluster-field source-paper-group \
  --allocation-output '<project-relative benchmark_metadata_allocation/REPORT.json>' \
  --created-at '<timezone-aware ISO-8601>' \
  --output '<new benchmark_metadata_allocation_planning/PLAN.json>' \
  --allow-projected-metadata-read --require-ready
```

The plan replays the pilot evidence behind the power report and verifies that
distinct source groups can meet the powered sample size while covering every
non-empty declared stratum. It records only counts. No task identity is chosen
until the owner approves the exact plan hash:

```bash
.venv/bin/scitaste evaluation benchmark-metadata-allocation-approve \
  --plan '<allocation PLAN.json>' --confirm-plan-sha256 '<exact plan hash>' \
  --approved-by '<owner>' --approved-at '<timezone-aware ISO-8601>' \
  --output '<new allocation APPROVAL.json>'

.venv/bin/scitaste evaluation benchmark-metadata-allocate \
  --screening-report '<complete screening REPORT.json>' \
  --power-request '<clustered-power REQUEST.json>' \
  --power-report '<clustered-power REPORT.json>' \
  --plan '<allocation PLAN.json>' --approval '<allocation APPROVAL.json>' \
  --workspace-root . --allocated-at '<timezone-aware ISO-8601>' \
  --output '<the exact output bound by the plan>' \
  --allow-projected-metadata-read
```

The deterministic report chooses at most one task per source group, preserves
the selected, unsampled-eligible, excluded, and blocked partitions, and binds a
formal task-set hash. It does not inspect raw source content, download linked
assets, choose a model, allocate resources, call an API, use a GPU, or authorize
an experiment.

For formal objective-progress work, that report is no longer allowed to stop at
an advisory ledger. The subsequent prelaunch manifest must use schema 1.5, set
`integrity.task_freeze_semantics` to `benchmark_metadata_allocation`, bind both
the allocation report's file SHA-256 and `formal_task_set_sha256`, and list its
selected task and source-group identities in exact report order. Every execution
lane must use that same complete task population. The experiment critic replays
the allocation chain from the declared evidence root and rejects plan,
approval, power, screening, implementation, identity, source-group, or lane
drift. Cell-plan schema 1.3 then carries both task-set bindings into result
admission. A generic task policy document therefore cannot be relabelled as the
formal task freeze, and a hand-written convenient subset cannot replace the
powered allocation.

## Admitted source projection

For JSON scientific sources, passing content audit and human-governed source
admission still does not make the bytes model-visible. The next no-read command
freezes an exact terminal-field allowlist and an explicit exclusion set:

For H0, hash that representation before source selection so both selection arms
are committed to the same downstream treatment:

```bash
.venv/bin/scitaste evaluation source-projection-protocol \
  --field problem_context:problem_context=/observed/problem/pointer \
  --forbid-pointer /observed/outcome/pointer \
  --forbid-exact-string '<leakage sentinel>' \
  --held-out-source-group '<held-out source group>' \
  --outcome-information withheld
```

The resulting `representation_protocol_sha256` belongs in the H0
`reference-selection-plan` downstream envelope.

```bash
.venv/bin/scitaste evaluation source-projection-plan \
  --plan-id '<new plan id>' \
  --approved-request '<approved request>' --receipt '<receipt>' \
  --content-audit-report '<content audit report>' \
  --source-admission-proposal '<admission proposal>' \
  --source-admission-report '<admission report>' \
  --reference-selection-report '<optional frozen H0 report>' \
  --workspace-root . --projection-output-root '<new relative output root>' \
  --field problem_context:problem_context=/observed/problem/pointer \
  --forbid-pointer /observed/outcome/pointer \
  --outcome-information withheld \
  --created-at '<timezone-aware ISO-8601>' --output '<new plan path>'
```

Without the H0 option, the plan includes every admitted source and no rejected
source. With it, schema 1.1 includes exactly the union of both frozen arms;
quality-rejected prestige sources remain eligible only when audit, rights, and
isolation evidence all pass, and natural overlap is projected once while both
arm ledgers remain explicit. The plan binds all five base control artifacts plus
the H0 report when present and proves each selected pointer is an audited
terminal scalar field without external locator text. Creating it performs no
source read. Materialization requires another exact owner approval followed by
the explicit local switch:

```bash
.venv/bin/scitaste evaluation source-projection-approve \
  --plan '<plan>' --confirm-plan-sha256 '<exact plan hash>' \
  --approved-by '<owner>' --approved-at '<timezone-aware ISO-8601>' \
  --output '<new approval path>'

.venv/bin/scitaste evaluation source-projection-materialize \
  --plan '<plan>' --approval '<approval>' --workspace-root . \
  --materialized-at '<timezone-aware ISO-8601>' \
  --receipt-output '<new receipt path>' --allow-local-source-projection
```

The projector rechecks the complete acquisition inventory and strict JSON
bytes, then writes canonical UTF-8/NFC payloads atomically. Each receipt binds
one identical hash for the raw-RAG representation and the Taste-abstraction
input. It calls no tokenizer or model and authorizes no experiment; token parity
and provider use remain later gates.

This request is valid under either future external comparison design because it
only acquires starting briefs. It does not resolve whether the experiment uses
a common backbone or best-native system configurations.

SciTasteBench v2 does not yet have an equivalent request. Its natural source
population, rights-compatible slice, source groups, expected storage, and human
curation plan are not sufficiently exact. Creating a plausible-looking GPU data
request now would weaken rather than advance the formal experiment, so the GPU
track remains `design_only` until those fields are frozen.

## Large executable-task packages

Large benchmark archives use a stricter review object than the small immutable
brief downloader. The first package request is
`configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml`; it binds
the two MLRC tasks admitted for first preflight to 39 exact provider objects,
3,761,168,137 observed compressed bytes, a 16-GiB unpack ceiling, and a 32-GiB
free-space floor. Google Drive file IDs and OpenML object ETags are preserved
separately from the SHA-256 values that can exist only after first acquisition.

Inspect it without a download:

```bash
.venv/bin/scitaste evaluation dataset-package-request \
  --manifest configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml \
  --workspace-root . --require-metadata-review-ready
```

The exact request now binds a separate license policy. It conservatively keeps
CC-BY-4.0 on Perception Test materials and applies the Meta-Album
CC-BY-NC-4.0 release boundary together with every source-dataset duty. It does
not invent one AWA license: local academic acquisition is reviewable, while AWA
ingestion requires acquired per-image license records and complete coverage.
Consequently `--require-owner-approval-ready` now passes, but the request still
retains all network, download, ingestion, API, GPU, and execution authority as
false until the owner confirms the new proposal and gate hashes. A later
downloader must still recheck provider identity, stream atomically, compute
every archive hash, and qualify ZIP safety before extraction.
