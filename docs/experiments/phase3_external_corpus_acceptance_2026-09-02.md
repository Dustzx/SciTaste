# Phase 3 external-corpus acceptance

This manifest records aggregate counts and hashes only. Source snapshots,
curated records, review text, article metadata, and generated library files stay
under ignored `outputs/` paths and are not committed.

## Source contract

- Run date: 2026-09-02 (Asia/Shanghai)
- ARIES source: official `alignment_human_eval.jsonl` release, ODC-BY 1.0
- CASIMIR sources: official `mapping_small_test.jsonl` plus a bounded metadata
  sample, with only revision mappings and bibliographic metadata projected
- Accepted-paper representation: title, forum, and venue metadata only; author
  lists, abstracts, PDFs, and article text excluded
- OpenReview direct API: not used because the endpoint returned a challenge
  verification response; no bypass was attempted
- Retrieval policy: all 25 external Taste Cases quarantined pending human
  scientific-taste verification

## Acceptance result

| Stage | Input | Accepted | Rejected |
|---|---:|---:|---:|
| ARIES human-alignment projection | 25 | 25 | 0 |
| CASIMIR revision-map projection | 25 | 25 | 0 |
| CASIMIR accepted-paper metadata projection | 10 | 6 | 4 |
| Rights-scoped ingestion | 56 | 54 | 0 |

The four rejected metadata projections lacked the title or venue fields required
by the metadata-only schema. Ingestion received the 56 successfully projected
records, imported 29 Knowledge Documents and 25 quarantined Taste Cases, and
deduplicated two repeated metadata records. The rights audit classified all
three local inputs as ready.

## Artifact hashes

| Local artifact | SHA-256 |
|---|---|
| ARIES raw sample | `b292a3d69657f5c88dcbf699a4e9d6b8c652fd3d12003cc85362a0698c82ffd0` |
| CASIMIR revision mapping | `26d04225f7288d13f3ec53024a635a177ca8a86489724ef88a56dbc39b767a3b` |
| CASIMIR bounded metadata sample | `d95ab188ff111c9996611ec59d69f85e5bd7b560c562f9e77b8ef3a50e9b4c67` |
| Curated ARIES records | `cfbf0b81ec60fd609736027901ee488a666923aa164532dfa89c23659af7cf20` |
| Curated CASIMIR mappings | `8a1a8fda748a90fbfdd6c72d1f1e9e6732ff99913d45322fb996780f5a263e1a` |
| Curated accepted-paper metadata | `cfc865b1c52f4c38d6dafe0326c9c5559fd21eeaa65d0d7bf652e31484702e57` |
| Final Knowledge Library | `038c4bf3a88b532ca2686ceae72b203c0ce311ce056ada5a76c6bdb449a5a71b` |
| Final Taste Library | `ff5c4b1686d3ef85467e368a17938751e16ea3fcf9e20a34737909e424a5f433` |

This run demonstrates source-shaped ingestion and rights controls. It is not a
claim that observed author revisions are scientifically optimal decisions; those
cases remain unavailable to the controller until a human verifies them.
