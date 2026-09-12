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

## Admitted source projection

For JSON scientific sources, passing content audit and human-governed source
admission still does not make the bytes model-visible. The next no-read command
freezes an exact terminal-field allowlist and an explicit exclusion set:

```bash
.venv/bin/scitaste evaluation source-projection-plan \
  --plan-id '<new plan id>' \
  --approved-request '<approved request>' --receipt '<receipt>' \
  --content-audit-report '<content audit report>' \
  --source-admission-proposal '<admission proposal>' \
  --source-admission-report '<admission report>' \
  --workspace-root . --projection-output-root '<new relative output root>' \
  --field problem_context:problem_context=/observed/problem/pointer \
  --forbid-pointer /observed/outcome/pointer \
  --outcome-information withheld \
  --created-at '<timezone-aware ISO-8601>' --output '<new plan path>'
```

The plan includes every admitted source and no rejected source. It binds all
five upstream control artifacts and proves each selected pointer is an audited
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
