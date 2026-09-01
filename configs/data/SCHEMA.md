# Local corpus ingestion schema

`external_corpus.example.yaml` is a manifest, not a download configuration. Each
source path must point to a local `.json` or `.jsonl` snapshot. Before changing a
license status to `permitted`, record both its identifier and authoritative terms
URL in `license.identifier` and `license.locator`.

Every input object declares `record_kind`, or inherits `default_record_kind`:

- `knowledge`: factual material with `title` and `content` (aliases include
  `full_text`, `text`, and `paper_text`).
- `taste`: an annotated decision precedent. It must include `stage`,
  `context_summary`, `candidate_actions`, `preferred_action`,
  `decision_principle`, and `why_preferred`. Raw review prose is therefore not
silently promoted into a taste case.

Taste records may additionally declare `label_basis`, `extractor_version`,
`human_verified`, `outcome_horizon`, `source_action_id`, `derivation_method`, and
`personal_data_removed`. These fields distinguish observed/human labels from
inferred preferences and make later audits possible. Acceptance or citation count
must not be treated as a causal preference label.

OpenReview-style nested `{ "content": { "field": { "value": ... } } }` objects
are accepted. JSON containers may be arrays or use `records`, `items`, `data`, or
`notes`. Each output record carries a normalized SHA-256 content hash and license
metadata in its provenance. Duplicate content is skipped independently inside
the Knowledge and Taste libraries.
