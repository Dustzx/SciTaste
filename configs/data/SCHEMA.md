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

Every source also declares a rights-bearing `content_scope`: `metadata`,
`public_comment`, `derived_annotation`, or `article_text`. A permitted licence
must list that value in `license.applies_to`; a blanket dataset licence therefore
cannot silently authorize every field in a mixed corpus. Article text always
requires a complete permitted `license` object on each record, even when the
source declaration is permitted.

Taste records may additionally declare `label_basis`, `extractor_version`,
`human_verified`, `outcome_horizon`, `source_action_id`, `derivation_method`, and
`personal_data_removed`. External taste records default to
`retrieval_eligible: false`. Enabling retrieval requires `human_verified: true`,
a `derivation_method`, and `personal_data_removed: true`. These fields distinguish
observed/human labels from inferred preferences and make later audits possible.
Acceptance or citation count must not be treated as a causal preference label.

OpenReview-style nested `{ "content": { "field": { "value": ... } } }` objects
are accepted. JSON containers may be arrays or use `records`, `items`, `data`, or
`notes`. Each output record carries a normalized SHA-256 content hash and license
metadata in its provenance. Duplicate content is skipped independently inside
the Knowledge and Taste libraries.

Run `scitaste library audit --config MANIFEST --output OUTPUT` before obtaining
large snapshots. It checks declared scope and licence without opening source
files or making network requests. `conditional` means article records still need
per-record licence declarations; `blocked` means ingestion must not proceed.

`scitaste library curate` provides deterministic, non-generative projections for
three official snapshot shapes:

- `aries-alignment`: observed human review/edit alignments become quarantined
  Taste Cases; they are not quality labels.
- `casimir-mapping`: forum/revision mappings become Knowledge Documents without
  paper or review text.
- `casimir-metadata`: title/forum/venue fields become metadata-only Knowledge
  Documents; authors, abstracts, and PDFs are excluded.

These projections prepare records for the normal licence-gated importer. They do
not download data or make a case eligible for retrieval.
