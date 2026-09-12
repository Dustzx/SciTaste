# MLRC first-preflight acquisition audit v1

Status: **metadata review ready; not ready for download approval**. This audit
performed HTTP metadata and official-source inspection only. It did not retain
dataset bytes, create an acquisition destination, call a model provider, access
a GPU, or execute benchmark code.

## Decision

The first acquisition-review slice remains exactly the two tasks admitted by
the content-bound MLRC candidate gate:

| Task | Exact archives | Observed compressed bytes | Unpacked ceiling | Decision |
|---|---:|---:|---:|---|
| Temporal Action Localisation | 9 | 698,506,926 (0.651 GiB) | 4 GiB | retain, but resolve the derivative-data license conflict |
| Cross-Domain Meta Learning | 30 | 3,062,661,211 (2.852 GiB) | 12 GiB | retain, but resolve the AWA license variant and package obligations |
| Total | 39 | 3,761,168,137 (3.503 GiB) | 16 GiB | require at least 32 GiB free before an approved atomic transfer |

The exact machine-readable inventory is
[`mlrc_first_preflight_asset_inventory_v1.yaml`](data/mlrc_first_preflight_asset_inventory_v1.yaml).
The review-only request is
[`mlrc_first_preflight_assets_v1.yaml`](../../configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml).
Both bind the accepted MLRC repository commit, candidate manifest, external
resource corpus, and shared API/GPU catalog. All authority fields are false.

## Why the temporal package has nine archives

The pinned MLRC preparation script names nine action-localisation archives at
commit `0d26417034811d2d4587646c4520cc305ea09dd6`: video features, sound
features, and annotations for train, validation, and held-out test. Sound
features are not an accidental extra download. The pinned core configuration
sets `input_modality: multi`, and each path configuration supplies an
`mm_feat_folder`. Dropping the three sound archives would change the accepted
task rather than make acquisition more efficient.

The official [Perception Test repository](https://github.com/google-deepmind/perception_test/tree/3938d2f1ba3a6b502025741cea4cd73c7b3bdfaf)
states that software is Apache-2.0 and other materials are CC-BY-4.0. The
[pinned MLRC task README](https://github.com/yunx-z/MLRC-Bench/blob/0d26417034811d2d4587646c4520cc305ea09dd6/MLAgentBench/benchmarks_base/perception_temporal_action_loc/README.md)
instead calls the modified dataset Apache-2.0. The request therefore records
every Google Drive file ID, returned filename, content length, and last-modified
time, but keeps the task at `review_required` until the redistribution and
attribution scope is reconciled. The HTTP observations are source metadata, not
content hashes.

## Why the Meta-Album package has thirty archives

The pinned MLRC preparation script uses three source-disjoint sets of ten
Meta-Album Mini datasets: one dataset from each of ten domains in each set. It
downloads them through OpenML with `download_all_files=True`; the image ZIP,
not merely the small ARFF or Parquet index, is the executable input. The
inventory therefore records the exact 30 OpenML IDs, object URLs, object sizes,
ETags, last-modified times, and MLRC destination names.

The official [OpenML API documentation](https://openml.github.io/openml-python/main/generated/openml.datasets.get_dataset.html)
confirms that `download_all_files=True` is the auxiliary-file path intended for
datasets such as Meta-Album. The official [Meta-Album site](https://meta-album.github.io/)
describes the Mini construction and academic-use intent. Its pinned per-dataset
pages, however, expose materially different release licenses—CC0, MIT,
GPL-2.0, CC-BY variants, non-commercial and share-alike variants, BSD,
ImageNet terms, and an unspecified Creative Commons label for AWA. Consequently
the generic OpenML `CC BY-NC 4.0` metadata value is not treated as a sufficient
license decision. AWA remains blocked; other non-CC0 entries require their
attribution or redistribution obligations to be frozen before approval.

## Machine gate

Run the no-network inspection from the repository root:

```bash
.venv/bin/scitaste evaluation dataset-package-request \
  --manifest configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml \
  --workspace-root . \
  --require-metadata-review-ready
```

The current report has:

- `metadata_review_ready=true`;
- `ready_for_owner_approval=false`;
- `pending_content_hash_count=39`;
- no integrity blocker;
- license blockers for both tasks;
- pending pre-download identity recheck, first-acquisition SHA-256 receipts, and
  archive-safety qualification;
- `authorizes_network_preflight=false`, `authorizes_download=false`,
  `authorizes_ingestion=false`, `authorizes_api_calls=false`,
  `authorizes_gpu_work=false`, and `authorizes_execution=false`.

`--require-owner-approval-ready` deliberately returns nonzero. Closing the
license issues would permit an owner to review an exact transfer request; it
would not by itself approve the request or make either task executable.

The corresponding post-approval software path is now implemented and tested
without source access. It uses exact-hash approval, same-connection streaming
identity checks, atomic staging, incremental SHA-256 receipts, and a separate
no-extraction ZIP safety report. Its commands are documented in
[`DATASET_PACKAGE_ACQUISITION.md`](../DATASET_PACKAGE_ACQUISITION.md). This
implementation does not change the current gate result and did not acquire a
dataset byte.

## Required next evidence

1. Resolve the Perception Test/MLRC derivative-data license discrepancy with an
   authoritative clarification or a rights-preserving acquisition route.
2. Resolve the exact AWA license variant and freeze a 30-dataset attribution and
   obligation manifest.
3. After explicit hash-bound owner approval, use the now-tested streaming
   transaction to acquire atomically and record the
   SHA-256 of every archive. Then inspect ZIP paths and expanded-byte ceilings
   before extraction.
4. Only after package qualification, reproduce the pinned baseline and held-out
   scorer without API or agent intervention. An experiment proposal remains a
   later, separately approved object.
