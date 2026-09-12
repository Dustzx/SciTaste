# High-quality source abstraction for Scientific Taste

Scientific Taste is not equivalent to retrieving text from relevant papers. A
retriever can reduce lookup cost, but it cannot establish that a source records a
good scientific decision, that the decision was abstracted faithfully, or that a
matched and mismatched context differ only in task relation. SciTaste therefore
separates four operations:

1. acquire and freeze permitted source bytes;
2. verify why each source qualifies as high-quality evidence;
3. abstract a source-supported decision principle; and
4. independently review the abstraction before it becomes retrieval-eligible.

The no-run implementation is `scitaste.evaluation.taste_corpus_curation`. It
turns a fully reviewed curation package into the two corpus files and pair
qualification report consumed by the native Taste preflight. It never downloads
data, calls a model, connects to a host, loads a checkpoint, or authorizes an
experiment.

## Evidence chain

Every selected source binds two different files by SHA-256:

- `artifact` is the exact source content from which the decision was abstracted;
- `quality_evidence` establishes the declared provenance tier, for example an
  official archival venue record or official benchmark release record.

The curation package fixes the source group, relation arm, pair slot, research
stage, decision role, license, privacy handling, task domains, quality rationale,
and outcome-information policy before review. A self-declared venue name without
bound quality evidence is insufficient.

One `TasteAbstractionCandidate` converts the source into a closed decision:
context, evidence state, candidate actions, preferred and rejected actions,
decision principle, rationale, outcome summary, and confidence. Human-authored
candidates cannot attach a model trace. Model-assisted candidates must attach the
exact trace by path and hash. In either case the candidate remains untrusted and
cannot enter retrieval directly.

## Independent human gate

Every candidate requires exactly two primary human reviews. The candidate author
cannot be a reviewer; reviewer identities must be distinct; conflict clearance,
independence, blindness to the other review, and blindness to the matched/placebo
label are explicit attestations. Each reviewer checks:

- fidelity to the bound source;
- grounding of the candidate action set and choice;
- whether the principle generalizes beyond source wording;
- whether the decision represents defensible scientific value; and
- whether outcome information is handled according to the frozen policy.

An acceptance requires every criterion. Agreement needs no adjudicator. A split
decision requires exactly one distinct adjudicator; two rejections block the
candidate. Rejected sources are not silently dropped after review: changing a
source or abstraction creates new package bytes and new review hashes.

## Pair materialization

Inspect a package without writing corpora:

```bash
scitaste evaluation taste-corpus-curation \
  --package /path/to/curation-package.yaml \
  --evidence-root /path/to/frozen-evidence \
  --report /path/to/curation-report.json \
  --require-ready
```

After all human records exist, materialize an immutable pair:

```bash
scitaste evaluation taste-corpus-curation \
  --package /path/to/curation-package.yaml \
  --evidence-root /path/to/frozen-evidence \
  --output-dir corpora/task-pair-v1 \
  --require-ready
```

The command creates `matched_corpus.json`, `placebo_corpus.json`,
`pair_manifest.json`, and `qualification_report.json`. Before returning, it runs
the production Taste retriever and requires all seven parity dimensions plus
source-contamination checks. Any failure removes all files created by that
attempt, so a half-published pair cannot look ready. Existing targets are never
overwritten.

Only the compiler assigns `human_verified=true` and
`retrieval_eligible=true`. Generated provenance retains source, quality-evidence,
candidate, and accepted-review identities. The resulting qualification proves
the bound construction and retrieval behavior; it does not prove that Scientific
Taste improves outcomes, that reviewers were representative, or that an
experiment may begin.

## Current ICLR 2027 boundary

The implementation closes the missing transformation path between approved
source acquisition and `taste-corpus-pair` qualification. It does not fabricate
the task-specific source files or human reviews needed by the active native v10
prepilot. Those remain an empirical/human-resource gate and require an exact
source plan plus owner approval before acquisition.
