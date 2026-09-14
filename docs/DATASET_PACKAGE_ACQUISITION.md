# Large dataset package acquisition

SciTaste treats large benchmark data as five different states:

1. exact source metadata is reviewable;
2. the exact proposal is legally and operationally ready for owner approval;
3. an explicitly approved transfer has produced content hashes atomically;
4. the downloaded archives have passed no-extraction safety qualification.
5. an independently approved mapping has projected the archives into disjoint
   development-only and scorer-only task data views.

None of these states authorizes ingestion, benchmark execution, API calls, GPU
work, or scientific claims. The current MLRC first-preflight request has now
completed state 3 under the project's standing owner policy: 39 objects totaling
3,761,168,137 bytes were atomically published and independently rehashed with no
size or SHA-256 mismatch. All 39 ZIPs subsequently completed state 4 under a
separate local-read approval. The Perception task's nine archives are now ready
for a state-5 owner decision; no archive has been extracted.

## Approval boundary

`dataset-package-approve` reruns the no-network package gate and refuses an
approval unless every integrity and license gate passes. The owner must confirm
both the proposal hash and the derived gate-report hash. The resulting immutable
JSON binds:

- the request, inventory, and gate-report hashes;
- the exact tasks, hosts, destinations, byte count, unpack ceiling, and free-space
  floor;
- the approving identity and timezone-aware timestamp;
- authority for network preflight and download only.

For a future review-ready request:

```bash
scitaste evaluation dataset-package-approve \
  --manifest path/to/request.yaml \
  --workspace-root . \
  --confirm-proposal-sha256 <proposal-sha256> \
  --confirm-gate-report-sha256 <gate-report-sha256> \
  --approved-by <owner> \
  --approved-at <timezone-aware-iso-8601> \
  --output path/to/APPROVAL.json
```

The MLRC request was approved by the checked-in standing policy for one frozen
transaction below decimal 10 GB. The Perception materials retain CC-BY-4.0 and
the Meta-Album packages use an explicit non-commercial obligation stack. AWA
remains closed for ingestion until its acquired per-image license records pass
two checks. See `docs/DATASET_LICENSE_POLICY.md`. A different request, changed
hash, or larger byte count requires its own applicable authority.

## Streaming transaction

`dataset-package-download` requires the approval artifact, reconfirms the
proposal and approval hashes, reruns the complete package gate, reloads the
content-bound inventory, verifies the free-space floor, and requires an explicit
`--allow-network-download` switch. Its default HTTPS transport:

- accepts only the exact credential-free HTTPS URL and never follows redirects;
- requests identity encoding and requires HTTP 200;
- compares Content-Length and Last-Modified on the body-producing connection;
- compares the whole-second HTTP-date representation when object metadata has
  finer timestamp precision;
- compares Google Drive's returned filename or the strong OpenML ETag opaque
  value as applicable, while rejecting weak or malformed ETags;
- streams one MiB chunks into exclusive mode-`0600` staging files while hashing;
- rejects short, long, or aggregate-byte drift;
- publishes the entire request directory and a self-hashed receipt only after
  every file succeeds.

Any failure deletes staging. Existing transaction destinations are never
overwritten. A successful receipt still says `authorizes_extraction=false` and
`authorizes_execution=false`. The real MLRC receipt is project-owned under
`outputs/projects/scitaste-self-development/evaluations/acquisitions/` and binds
all 39 content hashes. Two earlier attempts failed closed on HTTP representation
differences, removed their staging trees, and published no partial destination.

```bash
scitaste evaluation dataset-package-download \
  --manifest path/to/request.yaml \
  --approval path/to/APPROVAL.json \
  --workspace-root . \
  --confirm-proposal-sha256 <proposal-sha256> \
  --confirm-approval-sha256 <approval-sha256> \
  --allow-network-download
```

This command is intentionally not a downloader for arbitrary URLs. It can move
only objects frozen in the approved inventory.

## Archive qualification

After a successful transfer, `dataset-package-qualify` rehashes every local
file against the receipt and reads ZIP central directories without extracting
members. It rejects missing or changed files, invalid ZIPs, absolute or
traversing paths, backslashes and control characters, duplicate normalized
names, encrypted members, symbolic links, excessive member counts, zero-byte
compressed members, suspicious compression ratios, and per-task expanded-byte
ceiling violations.

```bash
scitaste evaluation dataset-package-qualify \
  --manifest path/to/request.yaml \
  --approval path/to/APPROVAL.json \
  --receipt path/to/RECEIPT.json \
  --workspace-root . \
  --output path/to/ARCHIVE_QUALIFICATION.json \
  --require-safe
```

A safe report is evidence for a later extraction proposal; it is not extraction
authority. The acquired MLRC package now has such a report: all 39 receipt hashes,
member paths, file types, and expanded-byte ceilings passed. For AWA, archive
safety still does not satisfy the separate per-image license-record coverage gate.

## Split-isolated task materialization

`dataset-materialization-request` closes the gap between a safe ZIP and data that
may enter an experiment. The Perception proposal binds all nine acquired asset
hashes, the archive qualification, the ingestion-license disposition, and the
task runtime spec. Its development view contains only six train/validation
archives (305,450,877 expanded bytes); its held-out view contains only the three
test archives (761,837,149 expanded bytes). The latter targets are required to
equal the task spec's complete hidden-path set, while none may occur in the
development view.

The current no-write inspection is owner-approval-ready with no blockers:

- proposal SHA-256: `13171500fc841e2ef91601f4d7de781607b4099f01d12896981c92879acff152`;
- request-file SHA-256: `4af83f201f0c9c5da6266921af336258dd6c23b5d62f8b089ff1e2764c4baf42`;
- gate-report SHA-256: `1df5af51b0289c9908461df8ddd3932083bd25e857393a2f2d7699047775bc5b`;
- compressed input: 698,506,926 bytes; expanded output: 1,067,288,026
  bytes; transaction ceiling: 2 GiB; required free-space floor: 4 GiB.

Review does not create authority. Approval must name and reconfirm both hashes:

```bash
scitaste evaluation dataset-materialization-approve \
  --manifest configs/evaluation/materialization/mlrc_perception_temporal_action_loc_v1.yaml \
  --workspace-root . \
  --confirm-proposal-sha256 13171500fc841e2ef91601f4d7de781607b4099f01d12896981c92879acff152 \
  --confirm-gate-report-sha256 1df5af51b0289c9908461df8ddd3932083bd25e857393a2f2d7699047775bc5b \
  --approved-by <owner> \
  --approved-at <timezone-aware-iso-8601> \
  --output outputs/projects/scitaste-self-development/evaluations/materialization-approvals/mlrc-perception-temporal-action-loc-v1.json
```

Only the separately loaded approval plus the explicit extraction switch can run
the atomic transaction:

```bash
scitaste evaluation dataset-materialize \
  --manifest configs/evaluation/materialization/mlrc_perception_temporal_action_loc_v1.yaml \
  --approval <approval-path> \
  --workspace-root . \
  --materialized-at <timezone-aware-iso-8601> \
  --allow-local-extraction
```

Extraction rehashes each source archive, streams every regular member with exact
count and expanded-byte bounds, publishes both views together, makes their files
read-only, and emits hashes compatible with `NativeExecutionProfile`. Failure
removes staging and publishes neither view. The resulting receipt still records
that no environment, model, GPU job, or benchmark ran. Environment reproduction,
the compiled NMS extension, scorer-baseline reproduction, and a reviewed Taste
guidance pair remain later gates.

## Test boundary

Automated tests use generated tiny ZIP files and an injected streaming
transport. They never contact Google Drive or OpenML and do not use API keys,
SSH, GPUs, or the registered Qwen checkpoint.
