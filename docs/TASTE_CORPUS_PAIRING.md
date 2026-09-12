# Matched and mismatched Taste corpus qualification

SciTaste's native causal comparison changes the relation of Scientific Taste
precedents to the held-out task while holding the rest of the decision path
fixed. A generic seed library is not admissible evidence for this comparison.

The upstream curation runtime is documented in
[`TASTE_CORPUS_CURATION.md`](TASTE_CORPUS_CURATION.md). It requires separately
bound source-quality evidence, an exact abstraction candidate, two independent
human reviews, and conditional adjudication before it can assign retrieval
eligibility. The pair qualifier below verifies the resulting corpora; it does not
construct or retroactively trust them.

The local-only qualifier is:

```bash
scitaste evaluation taste-corpus-pair \
  --manifest configs/evaluation/corpora/<pair>.yaml \
  --evidence-root . \
  --require-qualified
```

It reads two separately hash-bound corpus files and invokes the same production
retrieval policy used by the Taste controller. It performs no network request,
API call, SSH connection, checkpoint load, GPU work, or experiment execution.

## Required experimental match

Every pair must bind one held-out task identity and its exact domain tags,
source groups, and forbidden source-content hashes. The matched and placebo
arms must agree on:

- pair slots, research stage, decision role, and candidate-action cardinality;
- retrieval-eligible and human-verified case counts;
- nonzero retrieved count and retrieved pair slots for every qualification
  query;
- the per-query context-token ceiling;
- provenance and curation tiers; and
- whether outcome information is available or withheld.

The sole declared intervention is `source_domain_relation`: matched precedents
must overlap the task domain, while placebo precedents must be domain-mismatched.
Source content, source groups, and locators must be disjoint between the two
arms because a placebo cannot be a relabelled copy of the matched source.

## Contamination and provenance gates

Each precedent binds an external source-content SHA-256 and source-group identity
inside its provenance record. Qualification rejects:

- overlap with a held-out task source group or forbidden task-content hash;
- cross-corpus source-group, content-hash, or locator overlap;
- a case that is not both human-verified and retrieval-eligible; or
- missing license, derivation method, or personal-data-removal evidence.

The resulting report records every actual retrieval observation and all seven
parity dimensions. A report can be bound by the native condition preflight only
when `qualified=true`, every parity status is `verified`, and the report's two
corpus hashes equal the preflight hashes.

## SciTasteBench v3 treatment triplet

Matched/mismatched corpus qualification is necessary for H2, but it does not by
itself construct H1. SciTasteBench v3 therefore adds a per-decision mechanism
context containing three blinded renderings:

- raw excerpts and reviewed Taste abstractions from exactly the same sources;
- reviewed Taste abstractions from source-disjoint mismatched sources; and
- a frozen-tokenizer receipt represented by tokenizer identity, revision,
  artifact hash, observed token count, common ceiling, and truncation policy.

The schema rejects same-source drift in H1, any group/hash/locator overlap in
H2, held-out-source leakage, or unequal source count, token count, provenance,
curation, and outcome-information status. Retrieval-query, rendering-template,
and construction-receipt hashes are also bound. A curation package may claim
these conditions only as schema 2.0 / suite 3.0 and must bind the aggregate
treatment manifest hash. Historical suite 2.0 packages cannot relabel their
loose knowledge, Taste-library, or placebo text as this stronger evidence.

## Claim boundary

A qualified pair proves corpus construction, retrieval parity, and the declared
contamination checks for the bound bytes. It does not prove checkpoint behavior,
experimental effectiveness, statistical power, or external validity, and it
never grants execution authority. Formal corpus creation remains downstream of
explicit source-acquisition approval.
