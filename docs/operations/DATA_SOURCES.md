# External corpus policy

SciTaste ingests only user-provided local JSON/JSONL snapshots. It does not crawl,
download, or redistribute external papers, reviews, rebuttals, or datasets.
Unknown and restricted licenses are rejected by default.

## Source-specific rules

### OpenReview

OpenReview's current terms distinguish public comments/configuration records,
metadata, and article content. Public comments and configuration records are
CC BY 4.0, and metadata is dedicated under CC0 1.0. An article remains subject
to its author/venue license and the record's own `license` field. Import only
publicly readable records, preserve the forum/note/revision locator, and do not
deanonymize profiles.

Authoritative terms: <https://openreview.net/legal/terms>

### ARIES

The ARIES repository declares ODC-BY 1.0 for the dataset and Apache-2.0 for code.
That declaration does not automatically grant redistribution rights for every
underlying paper, S2ORC record, OpenReview text, cached model output, or derived
edit. Preserve the ARIES record ID and derivation type, and validate underlying
content rights before marking a manifest `permitted`.

Project and license files: <https://github.com/allenai/aries>

### CASIMIR

The dataset card labels the package MIT but describes a corpus containing paper
versions and reviews. Treat the package license as insufficient proof that every
included article can be redistributed. Prefer IDs, mappings, hashes, and derived
decision principles; admit full text only after per-record license review.

Dataset card: <https://huggingface.co/datasets/taln-ls2n/CASIMIR>

### F1000Research

The official F1000Research API exposes search results and versioned JATS XML,
and the platform describes its articles and associated peer-review material as
openly licensed under CC BY. Acquisition must use a bounded, no-redirect plan
and preserve the exact version locator and receipt. Raw article, review, reply,
and revision content stays in ignored project-owned outputs rather than Git.

Publisher subject membership is a sampling stratum, not an independently
validated domain label. Reviewer recommendations, author replies, later
versions, and publication status are observed decisions and consequences; none
is automatically a scientific-quality label, a preferred action, a reviewed
Taste abstraction, or a benchmark outcome. Structured people fields must be
removed before candidate compilation, and the remaining free text still needs a
release privacy review.

Authoritative resources: <https://f1000research.com/developers>,
<https://f1000research.com/faqs>, and
<https://f1000research.com/about/policies>

### Accepted papers

Acceptance is not a copyright license and is not itself evidence that a research
decision was good. Import article text only with an explicit compatible license.
Store acceptance, venue, date, citation trajectory, and reviewer outcome as
contextual metadata rather than a causal preference label.

## Intake workflow

1. Copy `configs/data/external_corpus.reviewed.example.yaml` and update each
   `reviewed_at` date after checking the authoritative locator.
2. Run `scitaste library audit --config MANIFEST --output OUTPUT`. This does not
   open source files or contact a remote service.
3. Keep snapshots outside Git, transform only the declared `content_scope`, and
   retain stable source locators.
4. Ingest with `scitaste library ingest`. Article text needs a complete permitted
   licence declaration on each record.
5. Human-review derived Taste Cases before setting `retrieval_eligible: true`.
   Eligible cases also require a derivation method and confirmation that personal
   data was removed. Other cases remain stored but quarantined from retrieval.

## Repository boundary

Allowed in Git:

- ingestion code and schema documentation;
- example manifests with no source data;
- tiny synthetic test fixtures;
- aggregate counts, rejection reasons, hashes, and license-review manifests.

Not allowed in Git:

- raw papers, reviews, rebuttals, profiles, or datasets;
- API responses or credentials;
- records with unknown/restricted redistribution rights;
- inferred Taste Cases lacking explicit alternatives, selected action, rationale,
  provenance, and labeling basis.
