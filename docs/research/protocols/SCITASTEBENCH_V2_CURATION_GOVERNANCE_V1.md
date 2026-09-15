# SciTasteBench v2 curation and local-model governance

Status: **design and software contract only**. No human/expert label, benchmark
result, checkpoint transfer, or GPU workload is authorized by this document.
The active operational route is the explicitly nonhuman AI-panel amendment in
`docs/research/AI_REVIEW_SUBSTITUTION_PROTOCOL_V1.md`.

## Scientific role

SciTasteBench v2 is Track A mechanism evidence. It asks whether Knowledge,
decision-precedent Taste, critics, and their composition change a fixed model's
choice between the same scientific actions. It is not an end-to-end AutoResearch
comparison and cannot replace blinded review of complete idea-to-paper packages.

The experimental unit is one natural scientific decision case. Provider calls,
candidate-order arms, conditions, and retries are repeated measurements of that
case and are never counted as independent samples.

## Natural case population

The formal population contains at least 120 headline cases from at least 120
canonical source groups, at least three domains, and all six decision families:
Idea, Experiment, Evidence, Writing, Review, and Visual. Each headline case has
one distinct source group; further decisions from the same work are secondary
measurements whose total effective weight remains at most one. Each case is
derived from a real, rights-compatible research decision such as an open
review/rebuttal exchange, an experiment change recorded in a repository, or an
explicitly licensed derived annotation. Cases from the same paper, repository,
review thread, or trajectory share one `source_group_id`.

Source-group identity is global rather than receipt- or campaign-local. F1000
versions use the normalized base DOI; ARIES and compatible OpenReview sources use
the exact forum identity. Both are domain-separated and hashed by
`scitaste.evaluation.source_identity`, while private alias registries map old
receipt-bound IDs without storing the raw DOI/forum. A formal acquisition must
exclude canonical IDs already assigned to development or segmentation
validation before source content is opened. Reissuing a receipt or changing a
campaign ID cannot make a consumed work eligible again.

The source bytes or permitted derived annotation are content-addressed and
rehash-verified before compilation. The
case record contains a bounded decision context and exactly two feasible actions,
but no preferred answer. Self-development cases and source groups used to build
the evaluated Taste precedents are excluded from headline cases. Split assignment
is by source group, never by paragraph or individual decision.

This is where reference quality enters the method. Topical retrieval may locate
candidates, but it does not itself create Taste. A separate curation process
extracts a decision precedent with its context, alternatives, observed
consequence, boundary conditions, and provenance. The evaluated case binds the
IDs and source groups of the matched precedents. A placebo binds different,
non-overlapping precedents; it cannot be a paraphrase of the matched principle.

## AI-panel proxy labels under the active amendment

Every candidate is assessed against one versioned, content-addressed rubric by
two conflict-screened AI reviewers with distinct reviewer, model, run, and raw-
response identities. Exact agreement, or protocol-valid adjudication by a third
identity-distinct AI reviewer after disagreement, makes the candidate eligible
for deterministic admission. Admission also requires receipt, normalization,
firewall, identity, split, provenance, and artifact-hash checks; a reviewer does
not receive state-transition authority.

These labels support an internal AI-panel measurement instrument only. Every
record and report must state `reviewer_kind=ai` and `not_human_review=true`.
They cannot be described as human preference, expert agreement, inter-annotator
agreement, or independent construct validation, and they do not authorize the
stronger *Improving Autonomous Research* title. A later human study is a separate
protocol and estimand; it must not reinterpret the AI-only runs after the fact.

The curation compiler verifies reviewer identity separation per case, action
identity, rubric and precedent-corpus hashes, canonical source/Taste group
disjointness, and the formal population floor before it emits an executable
suite. Until these checks pass, no model can be run on the formal split.

Public-source attribution and de-identification are different release modes.
Exact titles, coined methods, abstracts, affiliations, or URLs may identify a
public paper even after structured names are removed. A release policy must
either preserve lawful attribution and stop calling the record de-identified,
or publish a reviewed derived-text representation that passes re-identification
screening. Reviewer blindness alone does not establish privacy.

## Conditions and negative controls

All conditions receive the same decision context and action set:

1. `base`: no retrieved augmentation;
2. `knowledge_rag`: factual context only;
3. `taste_library`: matched abstracted decision precedents only;
4. `taste_critics`: critic feedback only;
5. `full_scitaste`: Knowledge, matched Taste, critics, and controller context;
6. `taste_placebo`: mismatched, source-disjoint Taste precedents.

Every model is evaluated once with the declared action order and once with the
reversed order. These are counterbalanced measurements, not new cases. A formal
report must retain the order arm and report position sensitivity; the two arms
must not be silently pooled before an order-effect diagnostic.

## Local Qwen robustness slice

The planned local model is exactly:

- checkpoint: `Qwen/Qwen3-VL-2B-Instruct`;
- local tree SHA-256:
  `8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1`;
- tree size: 4,266,653,057 bytes;
- decoding: deterministic, maximum 256 new tokens, 16,384-token context;
- role: second-model/small-model robustness only.

The portable non-secret runtime envelope is
`configs/backends/local_transformers_qwen3vl2b_scitastebench_v1.yaml`; the model
path and one assigned `cuda:N` device are supplied through environment variables
after allocation rather than hardcoded into a report.

At the 120-case floor, six conditions and two action-order arms produce 1,440
decisions but only 120 experimental units. One resident 2B model fits on one RTX
3090; up to eight independent workers may shard cases across the eight devices.
Tensor parallelism is neither needed nor allowed for this slice. The ceiling is
16 allocated GPU-hours across the block, with sampled active time, peak memory,
wall time, failures, retries, and output bytes recorded separately.

The read-only inventory in
`docs/research/data/gpu_host_3090_2_inventory_v1.yaml` observed eight free 24 GB
devices and 59,034,427,392 available root bytes. The checkpoint is not present on
that host. Transfer and execution remain blocked until an exact case suite,
licenses, a storage/archive plan, copied-checkpoint attestation, clean executable
commit, and owner-approved proposal hash exist.

## Analysis

The primary Track A contrast is paired AI-panel-proxy-aligned selection for Full
SciTaste versus Base. Confirmatory component contrasts are Taste versus Base and Full
versus Knowledge; placebo versus matched Taste tests whether benefit comes from
additional fluent context rather than the precedent match. Secondary outcomes
include wrong-level decision rate, confidence calibration, abstention/selective
accuracy, candidate-order sensitivity, and per-family transfer.

Inference is paired by case and clustered by `source_group_id`. The formal test
and interval are frozen after a source-disjoint natural pilot estimates event
rates and intra-source correlation. Failed requests remain incorrect under the
registered intention-to-run rule unless a predeclared provider-failure estimand
says otherwise. Seeds, calls, and two candidate orders do not inflate the sample
size.

## Software path

Inspect a candidate curation package without compiling or running it:

```bash
.venv/bin/scitaste benchmark curate \
  --package /path/to/scitastebench-v2-curation.yaml \
  --evidence-root /path/to/frozen-evidence-root
```

Add `--output /path/to/scitastebench_v2.yaml` only after the readiness report is
clean. Execute the two order arms as separate, recorded commands after a later
GPU proposal is approved:

```bash
.venv/bin/scitaste benchmark run --backend local-transformers \
  --suite /path/to/scitastebench_v2.yaml --config /path/to/qwen-config.yaml \
  --candidate-order declared --record /path/to/declared.jsonl \
  --output /path/to/declared

.venv/bin/scitaste benchmark run --backend local-transformers \
  --suite /path/to/scitastebench_v2.yaml --config /path/to/qwen-config.yaml \
  --candidate-order reversed --record /path/to/reversed.jsonl \
  --output /path/to/reversed
```

These commands describe the eventual path; this document grants no execution
authority.
