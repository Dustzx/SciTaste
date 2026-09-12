# Dataset license policy

SciTaste separates four questions that are commonly collapsed into one
`license` flag:

1. what the upstream source actually says;
2. which conservative obligation stack applies to the exact package;
3. whether an owner may review a local academic-research download request; and
4. whether acquired bytes may be ingested, redistributed, or published.

The first MLRC policy is
`configs/evaluation/acquisition/mlrc_first_preflight_license_policy_v1.yaml`.
It is bound to the exact 39-archive inventory by SHA-256 and maps every asset to
one of nine obligation profiles. It authorizes nothing.

## Resolved acquisition scope

For Temporal Action Localisation, the pinned Perception Test repository assigns
CC-BY-4.0 to non-software material. The MLRC task README calls the source data
Apache-2.0 after describing split changes, but that downstream statement is not
treated as permission to remove the upstream material license. The policy
therefore keeps CC-BY-4.0 attribution, citation, license-reference, and
modification-notice duties for all nine feature and annotation archives.

For Cross-Domain Meta Learning, the policy applies the Meta-Album
CC-BY-NC-4.0 release boundary together with each of the 30 source-dataset
labels already frozen in the inventory. Local non-commercial academic use is
reviewable; dataset redistribution and publication of raw or derived dataset
bytes remain outside scope. GPL/share-alike/permissive notice duties are
retained rather than flattened into one fictitious license.

AWA is intentionally not assigned a made-up Creative Commons version. The
official AwA2 page says its images were selected for free use and redistribution
and that individual license files are included. The pinned Meta-Album metadata
likewise says there is one license per image. That supports acquisition for the
declared local academic purpose, but not immediate ingestion: the acquired
`AWA_Mini.zip` must prove that image-license records exist and cover every
image. Failure leaves Meta-Learning blocked for ingestion.

## Deterministic inspection

```bash
scitaste evaluation dataset-package-license \
  --manifest configs/evaluation/acquisition/mlrc_first_preflight_license_policy_v1.yaml \
  --workspace-root . \
  --require-acquisition-ready
```

The current result is:

- 39/39 assets covered by nine profiles;
- 36 raw inventory `review_required`/`blocked` states resolved for the narrow
  acquisition scope;
- `acquisition_license_ready=true`;
- `ingestion_license_ready=false` because two AWA checks need acquired bytes;
- no network access, dataset file, approval, provider call, GPU work, or
  execution.

`--require-ingestion-ready` deliberately returns nonzero. The license policy is
part of the package request's proposal hash, so changing one profile, asset
binding, restriction, or evidence source invalidates the owner-facing request.

This is an engineering use-policy record, not legal advice. A later plan to
redistribute data, publish derived data, or use it commercially requires a new
policy and independent review.
