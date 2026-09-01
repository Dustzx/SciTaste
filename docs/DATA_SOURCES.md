# External corpus policy

SciTaste ingests only user-provided local JSON/JSONL snapshots. It does not crawl,
download, or redistribute external papers, reviews, rebuttals, or datasets.
Unknown and restricted licenses are rejected by default.

## Source-specific rules

### OpenReview

OpenReview's current terms distinguish public comments/configuration records,
metadata, and article content. Public discussion records may have a platform-level
license, while an article remains subject to its author/venue license and the
record's own `license` field. Import only publicly readable records, preserve the
forum/note/revision locator, and do not deanonymize profiles.

Authoritative terms: <https://openreview.net/legal/terms>

### ARIES

The ARIES repository distinguishes code and dataset licensing. That declaration
does not automatically grant redistribution rights for every underlying paper,
S2ORC record, OpenReview text, cached model output, or derived edit. Preserve the
ARIES record ID and derivation type, and validate underlying content rights before
marking a manifest `permitted`.

Project and license files: <https://github.com/allenai/aries>

### CASIMIR

The dataset card declares a package license but describes a corpus containing
paper versions and reviews. Treat the card's license as insufficient proof that
every included article can be redistributed. Prefer IDs, mappings, hashes, and
derived decision principles; admit full text only after per-record license review.

Dataset card: <https://huggingface.co/datasets/taln-ls2n/CASIMIR>

### Accepted papers

Acceptance is not a copyright license and is not itself evidence that a research
decision was good. Import article text only with an explicit compatible license.
Store acceptance, venue, date, citation trajectory, and reviewer outcome as
contextual metadata rather than a causal preference label.

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
