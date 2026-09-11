# Writing Taste

Writing Taste is the decision layer that determines **what scientific story the
registered evidence supports, how that story should be organized, and how it
should be expressed without weakening or inflating it**. It is larger than style
editing and larger than any single prompt or critic.

## Scope and precedence

SciTaste evaluates writing at paper, section, paragraph, sentence, and phrase
levels. Version 1 separates twelve dimensions:

1. scientific integrity;
2. claim calibration;
3. precision and scope;
4. scientific positioning;
5. narrative focus;
6. argumentative structure;
7. evidence prioritization;
8. global coherence;
9. reader guidance;
10. anti-defensive style;
11. venue fit;
12. voice and terminology.

The order is an authority rule, not a cosmetic preference. Persuasive framing
cannot override evidence, hide a material limitation, discard counterevidence,
expand a claim, or turn an engineering fixture into a scientific result.

## Reference-derived candidate layer

The auditable source study in
[`research/WRITING_TASTE_REFERENCE_STUDY_V1.md`](research/WRITING_TASTE_REFERENCE_STUDY_V1.md)
covers the complete set of 29 papers recognized by the official ICLR 2023--2026
Outstanding Paper and Honorable Mention announcements, plus six version- and
license-audited open-source writing projects. Its machine-readable record pins
paper locators, acquired PDF hashes, structural observations, evidence-carrier
counts, candidate principles, counterexamples, and transfer restrictions.

The reference study is currently a candidate layer with a `hold` promotion
decision. In particular, figure, table, experiment, and ablation counts remain
descriptive observations rather than quotas. A pure-theory Outstanding Paper
with no numbered figures or tables is retained as a boundary case. New
whole-paper rules require accepted non-award and negative controls, independent
human annotation, and archetype-specific error measurement before they can
become production Taste Cases or submission gates.

## Venue and paper-archetype layer

Writing Taste separates cross-venue scientific principles from venue-specific
guidance and mechanical submission rules. A venue is represented by a
co-located bundle:

```text
configs/writing/venues/<venue-version>/
├── submission.yaml   # template, anonymity, pages, statements, compilation
├── taste.yaml        # review constructs and writing/evidence guidance
└── provenance.yaml   # sources, corpus identity, transfer limits, missing controls
```

The first complete bundle is `iclr-2027`. Its profile contains five advisory
constructs distilled from the current official reviewer guide and fifteen
candidate principles from the registered ICLR award-paper reference study. The
profile pins its local provenance bytes, exposes its promotion decision, and
marks every principle `submission_gate: false`. Corpus principles stay
`candidate` while accepted non-award controls, negative examples, independent
annotations, and archetype-specific error measurements are missing.

Six overlays distinguish empirical method, empirical system, empirical analysis,
empirical discovery, theory--empirical, and pure-theory papers. Conditional
guidance is selected only when the paper archetype is declared. An unspecified
archetype receives cross-archetype guidance and an explicit unresolved condition;
it does not guess. This prevents systems expectations from leaking into pure
theory and prevents empirical papers from treating formal exposition alone as
evidence of a claimed real-world effect.

`VenueWritingTasteContext` binds the exact profile fingerprint, manuscript hash,
archetype, applied principles, omitted conditional principles, and overlay duties.
It is supplied as structured input to the proposal-only semantic Writing Taste
node and stored by venue paper builds as `VENUE_TASTE_CONTEXT.json`. The context
does not claim that a manuscript satisfies the principles. Deterministic template
readiness, general Writing Taste findings, whole-paper argument closure, semantic
review, and eventual human review remain separate records.

## Anti-defensive writing as one component

The positive-scope, strength-centered, and no-project-log principles were adapted
at the principle level from
[Adkid-Zephyr/anti-defensive-writing-Skill](https://github.com/Adkid-Zephyr/anti-defensive-writing-Skill)
at commit `b32067b3055d356e007c6986775fee069da3891a` under its MIT license. The
source text is not vendored or copied. Each derived Taste Case records the exact
source, commit, license, and derivation method.

SciTaste does not adopt absolute instructions such as hiding every unfavorable
result or withholding every weakness. Those rules conflict with scientific
integrity when a result or limitation changes validity, scope, safety, ethics, or
reproducibility. The integrated policy is:

- state supported scope positively;
- remove redundant anticipatory disclaimers;
- organize the paper around its strongest supported contribution;
- keep material limitations once, precisely, where they change interpretation;
- retain the complete evidence and failure history in the project record;
- route a real evidence gap to new evidence or a narrower claim, never to prose
  camouflage.

## Implemented architecture

```text
registered claims, evidence, limitations, and venue
→ Narrative Spine
→ section and paragraph contracts
→ hierarchical Writing Taste retrieval
→ deterministic Writing Taste assessment
→ optional proposal-only semantic Writing Taste node
→ decomposed claim/evidence and style critics
→ evidence action, contract revision, or bounded prose revision
→ human and venue review
```

`TasteCase` now indexes writing level, section type, rhetorical role, transition
pattern, claim strength, citation density, Writing Taste dimensions, and style
tags. `WRITING_DECISION` retrieval uses those fields while preserving provenance.

The deterministic assessor emits self-hashed findings and currently detects
project-status headings, project-log Results sections, process chronology,
defensive framing in high-attention sections, missing abstract contribution or
evidence cues, conclusion self-negation, and overloaded paragraphs. It is an
advisory writing signal, not a scientific-quality score.

### Whole-paper argument and carrier contract

`PaperArgumentContract` now makes paper-level integrity inspectable above the
section and paragraph layers. It records:

- one central question and bounded answer;
- headline, supporting, and boundary claims tied to registered
  `ScientificClaim` objects;
- planned, available, or unavailable reader-facing carriers such as result
  tables, figures, qualitative examples, ablations, proofs, algorithms, audit
  reports, and reproducibility artifacts;
- the story exposed by the title, abstract, introduction, first figure,
  headline Results, and conclusion;
- the question, claims, and primary carrier delivered by each section; and
- every material limitation together with its affected claims and disclosure
  locations.

The deterministic assessment keeps three failures distinct. An
`unsupported-claim` means the scientific claim is absent, provisional,
contradicted, or unsupported. `missing-evidence` means the claim lacks a
reciprocal registered support relation. `missing-presentation-carrier` means
support exists but no available primary table, figure, proof, or audit carrier
exposes it to the reader. A planned carrier remains a visible gap; it is never
silently treated as completed.

Carrier admission is type-aware without imposing universal figure or experiment
counts. An explanatory architecture diagram cannot replace empirical or audit
evidence for a headline system claim. Conversely, a pure-theory paper may bind a
claim to a formal statement and proof without being penalized for lacking an
empirical figure. Artifact locators are project-relative and may be rehashed;
the manuscript itself can also be content-bound so edits after review become
visible as drift.

`scitaste project paper build` accepts `--argument-contract` together with
`--argument-state`. Dry-run reports `paper_argument_preflight`; a formal build
stores `PAPER_ARGUMENT_CONTRACT.yaml` and the self-hashed
`PAPER_ARGUMENT_ASSESSMENT.json` beside Markdown, TeX, PDF, venue checks, and
surface Writing Taste checks. The argument result is deliberately advisory and
sets `scientific_quality_established=false`. The reference-derived principles
remain on hold as production quality gates until the registered controls and
human evaluation are complete.

Every ordinary manuscript bundle and venue-native submission bundle now owns a
`WRITING_TASTE_ASSESSMENT.json`. Project paper dry-runs expose the same
assessment before mutation, and registered paper manifests bind its record
hash and artifact locator. This makes Writing Taste inspectable beside the
source, TeX, PDF, mechanical manuscript assessment, and venue assessment; its
advisory verdict remains separate from `eligible_for_submission`.

The optional `writing-taste` model node handles the semantic decisions that
cannot be reduced to regular expressions. Its input contains only registered
sections, claim IDs, evidence IDs, headline candidates, and material
limitations. Its typed output may propose reframing, reordering, section naming,
claim narrowing, or an evidence request. Deterministic admission rejects unknown
references, a changed manuscript identity, an incomplete section order, or any
attempt to omit or demote a registered material limitation. The node cannot edit
files, mutate state, call tools, accept evidence, or execute an action.
When a content-bound venue context is present, the node may use only its applied
principles and archetype duties; candidate guidance remains hypothetical and
omitted archetype rules cannot be inferred by the model.

Two bounded profiles are provided:

- `profile_writing_taste_scripted_v1.yaml` for offline acceptance;
- `profile_writing_taste_zhipu_glm53_flash_v1.yaml` for opt-in live review with
  `glm-5.3-flash`.

The live profile admits up to 6,000 output tokens within an 8,192-token provider
generation ceiling. The limit is per semantic review invocation, not a global
development or manuscript length limit.

### Evidence-grounded full-paper drafting

The optional `evidence-paper-draft` node addresses long-form manuscript content
without relaxing evidence authority. Its input is a closed projection of the
paper question, intended contribution, claims and support states, registered
evidence, citations, venue-required sections, material limitations, numeric
tokens, and word budget. Its output contains a complete sectioned manuscript
proposal and explicit claim/evidence/citation/limitation references for every
paragraph. Deterministic admission rejects reference drift, unsupported claims
presented as empirical findings, missing headline claims, omitted limitations,
section-order drift, excess words, and any numeric token not authorized by the
input.

The trace sidecar retains internal identifiers for audit, while the Markdown
renderer rejects those identifiers in model-authored text and emits the title
contract expected by the venue builder. Citation references remain typed IDs in
the proposal and are deterministically rendered as `\\citep{<bibtex-key>}` only
after their registered BibTeX keys are found in the supplied bibliography. Names
such as run IDs, scenario IDs, and internal diagnosis labels therefore have no
reason to appear in a reader-facing manuscript unless they are intentionally
included as scientific content. The node is still proposal-only: it does not
run experiments, alter project state, claim independent review, or make a paper
submission-ready.

`scitaste project paper build-draft` is the deterministic ledger-to-paper bridge.
It revalidates the complete model-node chain, accepted typed result, current
proposal admission, project/run ownership, bibliography closure, and manuscript
identity. It then writes clean Markdown and a self-hashed `PAPER_DRAFT_TRACE.json`
into the ordinary venue pipeline, which builds TeX/PDF, runs manuscript and
submission gates, registers the full bundle under the project, and binds the
draft hashes into `PaperManifest`. No second model call occurs during this
materialization.

The registered `evidence-paper-revision` node consumes an admitted source draft,
a separately supplied target evidence projection, exact paper/packet/report
hashes, and typed reviewer concerns. It classifies the effective requirement
from both flags and concern category, so missing-evidence, missing-baseline,
analysis, method, and validity concerns cannot be downgraded to ordinary prose
by an inconsistent report. Text-only concerns may propose paragraph changes.
Evidence and experiment concerns stay in `pending_evidence` or
`pending_experiment` unless the input contains a self-hashed closure proof built
from a later project state; proof-backed revisions must integrate exactly the
new evidence into named revised paragraphs. The proposal never calls a tool,
writes a manuscript, submits a response, or closes review. Deterministic
materialization and the original reviewer remain separate downstream gates.
`project paper build-revision` now supplies the first gate: it revalidates the
accepted revision ledger and exact review inputs, verifies state-derived
evidence and completed experiment bytes, and produces a Stage 19 venue bundle
with `PAPER_REVISION_TRACE.json`. The author response and original-reviewer
verification must bind that same trace and closure proof; the revised prose is
never itself treated as empirical evidence.

The committed `deepseek-v4flash-paper-draft` and
`deepseek-v4flash-paper-revision` profiles each allow up to 32,768 output tokens
for their distinct long-form tasks. They are separate from short semantic-review
profiles and still require all live-execution gates; no API call is made merely
by loading or planning either profile.

## SciTaste self-iteration

The tracked SciTaste manuscript is the first dogfooding target. The initial
assessment correctly identified `Current Results`, `Artifact-level validation`,
and `End-to-end engineering preacceptance` as project-report headings, along with
project-status framing in the abstract, introduction, and conclusion. The source
was reorganized around two evaluation questions and positive evidence scope.

The second dogfooding pass adds a claim-linked overview figure and a result
summary table whose third column states the inference that each artifact cannot
support. Its whole-paper contract intentionally keeps the original programmatic
title while flagging that title's broader *learning* promise as an entry-point
scope risk until learned-policy or comparative effectiveness evidence exists.
This is a useful contract finding, not a prose defect to hide.

Passing the deterministic advisory means only that the registered surface
antipatterns are absent. Expert judgment, semantic model comparison, citation
verification, venue review, and the registered effectiveness study remain
separate evidence requirements.
