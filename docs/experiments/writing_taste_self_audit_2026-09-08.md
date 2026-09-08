# Writing Taste self-audit — 2026-09-08

## Role

This is a deterministic dogfooding record for the tracked SciTaste manuscript.
It validates that the Writing Taste assessor detects and clears its declared
surface antipatterns. It is not evidence that the manuscript has expert-level
writing quality or that Writing Taste improves acceptance probability.

## Before

- source: `manuscripts/scitaste/main.md` at repository `HEAD` before this iteration;
- manuscript SHA-256:
  `d628d729920738931ae2ddeb53fabc0055230d3726280cf0e951dca64a80342d`;
- deterministic findings: 7 warnings and 2 informational findings;
- detected project-report headings: `Current Results`,
  `Artifact-level validation`, and `End-to-end engineering preacceptance`;
- detected high-attention project-status framing: Introduction and Conclusion;
- detected project-log Results vocabulary: repository snapshot, test suite, and
  passing tests;
- detected Abstract self-negation: `we therefore make no claim`;
- detected Abstract length signal: 265 words;
- detected out-of-place negative scope framing: `What the evidence supports`.

## Intervention

The manuscript was reorganized around explicit evaluation questions:

1. whether SciTaste enforces its control and provenance contracts;
2. whether the registered conditions complete one controlled research task.

The Abstract now states the strongest supported engineering result before the
separate matched-budget research question. The Introduction distinguishes
integration questions from causal effectiveness. Results headings name the
question answered instead of the development status, and the conclusion closes
on the registered empirical decision rather than a defensive disclaimer.

Material limitations remain in the manuscript. The rewrite changes their
placement and positive scope; it does not remove the pending 48-cell study,
blinded expert review requirement, adapter-continuation exclusion, unavailable
systems, or the distinction between integration and effectiveness.

## After

- manuscript SHA-256:
  `15b075258fee42735eea7038b8f9bb9e8418856f5895e118bb636efd142edd29`;
- word count under the assessor tokenizer: 4,796;
- deterministic findings: 0 warnings and 0 informational findings;
- integrity gate: pass;
- style advisory: pass;
- scientific quality established: false.

The record SHA-256 for the after-assessment is
`6d1e47d436356db1e9f2d67c3282b9f2b84bc5efe9182a6eac09faa72f0767a6`.

## Remaining evidence

- execute the semantic `writing-taste` node under a recorded profile and compare
  its findings with independent expert annotations;
- evaluate false positives and false negatives across accepted, rejected, and
  deliberately perturbed papers;
- calibrate section- and venue-specific precedents;
- implement a bounded long-form writer that consumes contracts and accepted
  revision plans without gaining evidence or file-mutation authority;
- rebuild the ICLR 2027 paper bundle after the source and reference set stabilize.
