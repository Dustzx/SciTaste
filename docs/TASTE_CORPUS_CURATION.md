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

The implementation has two deliberately separate boundaries. The optional
`taste-abstraction` model node creates an untrusted proposal and records the
complete invocation. The offline
`scitaste.evaluation.taste_corpus_curation` compiler turns a fully reviewed
curation package into the two corpus files and pair qualification report consumed
by the native Taste preflight. Inspection and materialization never download
data, call a model, connect to a host, load a checkpoint, or authorize an
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

For model-assisted abstraction, `abstraction_input` binds a third file: the exact
UTF-8 projection shown to the model. Its bytes are preserved, including boundary
whitespace and terminal newlines. The model input omits the matched/placebo
relation and held-out task content; its runtime context contains no claims,
sections, candidate actions, metadata, tools, or action authority.
`build_taste_abstraction_input` constructs this projection so the experiment does
not depend on hand-copied text.

That projection is now produced by an explicit pre-model gate rather than by an
operator copying fields. `source-projection-plan` consumes the approved request,
download receipt, content-audit report, complete source-admission proposal, and
admitted/rejected ledger. It opens only those control artifacts. For every
admitted source, each selected JSON pointer must already occur in the audit and
must end in scalar data; selecting an object subtree, an unaudited field, an
external locator, a forbidden outcome subtree, or any rejected source fails.
The plan also fixes normalization, per-source and aggregate byte ceilings,
held-out identities, and the destination before source bytes are read.

A separate exact-hash approval and runtime switch are required to materialize
the projection. The output intentionally omits source, source-group, relation,
and condition identity from its model-visible payload. The same output hash is
recorded as both the raw-RAG source representation and the input to Taste
abstraction. This is the causal H1 invariant: downstream arms may change the
representation, but they cannot silently change the source evidence. The
receipt stops at `ready_for_tokenization`; an exact model-tokenizer count and a
separate abstraction-resource decision are still required before any provider
call.

Legacy schema-1.1 `TasteAbstractionCandidate` records convert the source into a closed decision:
context, evidence state, candidate actions, preferred and rejected actions,
decision principle, rationale, outcome summary, and confidence. Human-authored
candidates cannot attach a model trace. Model-assisted candidates must attach the
exact canonical entry from a project-owned `ModelNodeRuntime` ledger. The checker
verifies its complete chain and recording, live-mode profile, request and policy
fingerprints, exact source input, prompt and output schema, provider/model
identity, raw response, resource telemetry, zero tool authority, and equality
between the accepted proposal and reviewed candidate. A scripted or replay
fixture cannot qualify as historical model assistance. In either case the
candidate remains untrusted and cannot enter retrieval directly.

Formal schema-1.2 packages use the stronger
[`grounded-taste-abstraction`](GROUNDED_TASTE_DISTILLATION.md) node. Every
decision-bearing element names exact projection fields and verbatim support; the
principle must synthesize a scientific action with a distinct evidential or
justificatory role. Applicability conditions, failure conditions, a
decision-changing counterfactual probe, and deliberately discarded source detail
make transfer scope explicit. These boundaries are retained in the production
controller context rather than disappearing after curation.

The backward-compatible curation package accepts schema `1.1`, while formal H1/H2
construction requires schema `1.2` and tier `grounded-dual-human-verified`. It reports
`historical_model_invocation_count` separately from
`package_processing_performs_no_external_action`. The former describes how
candidates were produced; the latter describes only current inspection or
materialization. A deterministic migration preserves valid `1.0` packages while
removing their ambiguous historical no-call wording.

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

Schema-1.2 reviewers also attest that the element-level source trace and transfer
boundary are supported. Formal materialization fails if either attestation is
absent, even when the legacy five criteria pass.

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

The machine path is therefore:

1. content-audit and quality-qualify the complete frozen source population;
2. freeze and approve one common raw-RAG/abstraction source projection;
3. tokenize the exact projection under the selected model tokenizer;
4. construct `TasteAbstractionInput` and run `grounded-taste-abstraction` through the
   normal project-owned model-node runtime;
5. compile the accepted ledger entry with
   `scitaste evaluation taste-abstraction-candidate`;
6. collect two independent reviews, with adjudication only on a split; and
7. inspect and materialize the matched/placebo pair; and
8. freeze and replay the per-case, per-arm
   [SciTasteBench v3 treatment manifest](SCITASTEBENCH_V3_TREATMENT_MANIFEST.md)
   before compiling the benchmark suite.

Source reads/projection, model use, and human review require separate exact
approvals. The candidate compiler and package inspector do not perform those
actions.

## Current ICLR 2027 boundary

The implementation closes the software path between approved source acquisition
and `taste-corpus-pair` qualification. Sixteen pilot source files have been
downloaded but remain unopened under the download-only authority. Real content
audit, source-quality evidence, human reviews, field selection, projection,
tokenization, abstraction, and H1/H2 outcome review are still missing empirical
or human evidence; none is inferred from the executable contracts.
