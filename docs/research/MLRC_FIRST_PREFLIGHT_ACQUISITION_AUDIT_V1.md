# MLRC first-preflight acquisition audit v1

Status: **ready for exact owner review; not approved or downloaded**. This audit
performed HTTP metadata and official-source inspection only. It did not retain
dataset bytes, create an acquisition destination, call a model provider, access
a GPU, or execute benchmark code.

## Decision

The first acquisition-review slice remains exactly the two tasks admitted by
the content-bound MLRC candidate gate:

| Task | Exact archives | Observed compressed bytes | Unpacked ceiling | Decision |
|---|---:|---:|---:|---|
| Temporal Action Localisation | 9 | 698,506,926 (0.651 GiB) | 4 GiB | acquisition-ready under upstream CC-BY-4.0 duties |
| Cross-Domain Meta Learning | 30 | 3,062,661,211 (2.852 GiB) | 12 GiB | acquisition-ready for local academic use; AWA ingestion checks remain |
| Total | 39 | 3,761,168,137 (3.503 GiB) | 16 GiB | require at least 32 GiB free before an approved atomic transfer |

The exact machine-readable inventory is
[`mlrc_first_preflight_asset_inventory_v1.yaml`](data/mlrc_first_preflight_asset_inventory_v1.yaml).
The review-only request is
[`mlrc_first_preflight_assets_v1.yaml`](../../configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml).
Both bind the accepted MLRC repository commit, candidate manifest, external
resource corpus, and shared API/GPU catalog. All authority fields are false.
The request additionally binds
[`mlrc_first_preflight_license_policy_v1.yaml`](../../configs/evaluation/acquisition/mlrc_first_preflight_license_policy_v1.yaml),
which covers all 39 assets with nine obligation profiles.

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
instead calls the modified dataset Apache-2.0. The license policy does not allow
that downstream statement to relicense upstream material: all nine data,
feature, and annotation archives retain CC-BY-4.0 attribution, citation,
license-reference, and modification-notice duties. That closes acquisition
review for this non-commercial project without making any redistribution claim.
The HTTP observations are source metadata, not content hashes.

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
the generic OpenML metadata value is not treated as a substitute for the
per-dataset evidence. The policy instead applies the Meta-Album CC-BY-NC-4.0
release boundary together with each source label, retaining attribution,
notice, non-commercial, and share-alike duties as applicable. Redistribution
remains prohibited by the request.

The official AwA2 source and pinned Meta-Album metadata do not identify one
truthful CC variant for AWA; they state that licensing is per image. The policy
therefore allows only local academic acquisition and requires the acquired Mini
archive to prove that per-image license records exist and cover every image
before ingestion. This is a post-acquisition qualification, not an approval
blocker or a fabricated license identity.

## Machine gate

Run the no-network inspection from the repository root:

```bash
.venv/bin/scitaste evaluation dataset-package-request \
  --manifest configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml \
  --workspace-root . \
  --require-metadata-review-ready
```

The current report has:

- license-policy file SHA-256
  `d88c818ceacae51ac51a5db2266a10a8224a973dcb7cd596094ed1c09a93a27d`;
- request proposal SHA-256
  `c0b37f72588c9a89a5c4247f139c8b0595571cf639846066b7d7c538c5138ed4`;
- derived gate-report SHA-256
  `a19506613ac6ae645e2dfc595633ec3670b657f106fd06632d84d897547b9744`;
- `metadata_review_ready=true`;
- `ready_for_owner_approval=true`;
- `pending_content_hash_count=39`;
- no integrity blocker;
- no acquisition-scope license blocker;
- two AWA per-image license checks still pending before ingestion;
- pending pre-download identity recheck, first-acquisition SHA-256 receipts, and
  archive-safety qualification;
- `authorizes_network_preflight=false`, `authorizes_download=false`,
  `authorizes_ingestion=false`, `authorizes_api_calls=false`,
  `authorizes_gpu_work=false`, and `authorizes_execution=false`.

`--require-owner-approval-ready` now returns zero. That permits an owner to
review the exact transfer request; it does not approve the request or make
either task executable.

The corresponding post-approval software path is now implemented and tested
without source access. It uses exact-hash approval, same-connection streaming
identity checks, atomic staging, incremental SHA-256 receipts, and a separate
no-extraction ZIP safety report. Its commands are documented in
[`DATASET_PACKAGE_ACQUISITION.md`](../DATASET_PACKAGE_ACQUISITION.md). This
implementation now supports the review-ready request and did not acquire a dataset
byte.

## Required next evidence

1. Present the exact proposal and gate hashes for owner review; do not infer
   approval from this audit.
2. After explicit hash-bound owner approval, use the now-tested streaming
   transaction to acquire atomically and record the
   SHA-256 of every archive. Then inspect ZIP paths and expanded-byte ceilings
   before extraction.
3. Before ingesting AWA, verify that its per-image license records exist and
   cover every image; retain all source and Meta-Album attribution records.
4. Only after package and license qualification, reproduce the pinned baseline and held-out
   scorer without API or agent intervention. An experiment proposal remains a
   later, separately approved object.
