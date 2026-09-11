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

This request is valid under either future external comparison design because it
only acquires starting briefs. It does not resolve whether the experiment uses
a common backbone or best-native system configurations.

SciTasteBench v2 does not yet have an equivalent request. Its natural source
population, rights-compatible slice, source groups, expected storage, and human
curation plan are not sufficiently exact. Creating a plausible-looking GPU data
request now would weaken rather than advance the formal experiment, so the GPU
track remains `design_only` until those fields are frozen.
