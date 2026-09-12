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
