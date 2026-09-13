# SciTasteBench v3 Treatment Manifest

## Purpose

SciTasteBench v3 estimates two title-critical mechanism contrasts:

- H1 changes only representation: matched abstracted Taste versus same-source raw RAG;
- H2a changes only source-domain relation: matched versus source-disjoint mismatched Taste.

A context object alone cannot establish either contrast. Before compilation, every
rendered context must be connected to exact source identities, reviewed Taste
corpora, construction protocols, and an observed token sequence. The reference
treatment manifest is the immutable bridge between those materials and the
benchmark cases that later enter blinded review.

## Closed identity chain

Schema `1.0` contains one exact case population. Each case records the complete
three-arm `MechanismContextBundle` and one canonical construction record per arm.
The construction receipt binds:

- the rendered-context hash and ordered source artifact IDs;
- the exact supporting artifact IDs;
- tokenizer identity, revision, artifact bytes, and observed token count;
- the token-sequence hash;
- the retrieval-query and neutral rendering-template bytes.

The manifest itself is semantically hashed. SciTasteBench curation binds the
manifest file hash and refuses compilation unless its case IDs and complete
mechanism contexts exactly equal those embedded in the curation package.

## Required supports

The manifest requires content-addressed roles for the source-projection receipt,
Taste curation package and readiness report, matched and mismatched Taste corpora,
corpus-pair qualification, tokenizer, retrieval query, neutral render template,
and an arm-specific tokenization trace.

Inspection reopens only those declared local control/evidence files. It then:

1. validates every file against its declared SHA-256 and rejects symlinks or
   escaped paths;
2. replays the self-hashed source-projection receipt and checks every context
   source against its source ID, group, locator, and source-content hash;
3. parses matched and mismatched Taste corpora, checks their relation, and binds
   abstracted contexts to corpus provenance, curation tier, provenance tier, and
   outcome-information policy;
4. parses the formal-ready curation report and qualified, contamination-free
   corpus-pair report and checks their corpus/package identities;
5. parses the arm-specific token IDs and checks the rendered-context hash,
   tokenizer identity, exact token count, and token-sequence hash;
6. compares the manifest population and contexts with the complete v3 curation
   package.

Use the local no-run inspector before compiling a suite:

```bash
scitaste benchmark treatment-status \
  --manifest <reference-treatment-manifest.json> \
  --evidence-root <immutable-evidence-root>

scitaste benchmark curate \
  --package <scitastebench-v3-curation.yaml> \
  --evidence-root <immutable-evidence-root> \
  --output <scitastebench-v3.yaml>
```

## Claim boundary

This contract makes treatment identity replayable; it does not establish that
the source material is scientifically good, that a named reviewer performed the
recorded review, or that Taste improves decisions. Those claims require the real
content-authorized source chain, independent reviewers, powered execution, locked
blind opening, and the registered H1/H2 analysis. The manifest grants no
acquisition, model/API/GPU, recruitment, or experiment authority.
