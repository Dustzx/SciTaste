# SciTasteBench independent validation reserve v2

Status: **source reserve acquired and compiled; AI review and protocol rebinding pending**.

This reserve removes the data shortage identified by
`scitastebench_segmentation_validation_reserve_audit_v1.yaml`. It does not
retroactively alter the exposed twenty-item calibration sample and does not
authorize provider contact.

## Exact local inventory

| Compatible calibration stratum | Original unseen groups | New disjoint groups | Available for validation | Required |
|---|---:|---:|---:|---:|
| ARIES computing reviews | 3 | 7 | 10 | 10 |
| F1000 ecology/public-health reviews | 0 | 40 | 40 | 10 |

The F1000 transaction made 93 official XML requests and downloaded 14,746,145
bytes. All forty acquired works are canonically disjoint from all forty works in
the first receipt. Local compilation produced 77 candidates across all forty
new source groups.

The ARIES transaction downloaded the exact 198,981,013-byte official
`review_replies.jsonl` object. A deterministic compiler joined it only to the
receipt-bound upstream dev split, paper edits, and source/revised S2ORC parses.
It observed 102 eligible dev groups and selected seven with a fixed predeclared
hash rank, one review/response candidate per group. Their reply-to-edit
association is heuristic; `human_alignment_created=false` and
`human_review_performed=false` are part of the result contract.

## Authority boundary

The source-count floor is now met, but three steps still precede the bounded GLM
segmentation calibration:

1. two identity-distinct AI quality reviews plus a separate AI privacy review,
   all disclosed as nonhuman;
2. a prospective protocol version that binds both new reserve campaigns and
   proves source-group disjointness from every consumed sample;
3. a new Git freeze and content-addressed execution authorization.

The current machine-readable decision is
`scitastebench_segmentation_validation_reserve_audit_v2.yaml`. Its
`data_reserve_sufficient=true` means only that enough independent source groups
exist; effectiveness, construct validity, formal benchmark admission, and human
validity all remain false.
