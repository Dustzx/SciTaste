# Writing Taste Reference Study v1

## Decision status

This study replaces the earlier intuition-led treatment of whole-paper writing
quality with an auditable candidate reference library. It does **not** establish
that the listed patterns cause acceptance, predict reviewer scores, or should be
enforced as universal rules. Its immediate decision is `hold`: use the findings
to design annotations and paper contracts, but do not promote new hard gates
until negative controls and independent judgments are available.

The machine-readable source record is
[`data/writing_taste_reference_corpus_v1.yaml`](data/writing_taste_reference_corpus_v1.yaml).
It pins the paper population, PDF hashes, extraction measurements, open-source
project commits and licenses, candidate principles, counterexamples, and the
promotion gate.

## Why the earlier synthesis was insufficient

The previous Writing Taste iteration correctly identified several surface
failures in the SciTaste draft, including project-report headings and defensive
self-negation. It did not yet justify a theory of strong paper writing because:

1. examples were selected informally rather than by a declared population rule;
2. paper archetypes were not separated, so empirical conventions could be
   misapplied to theory papers;
3. figure and experiment completeness were discussed without corpus-level
   measurements or counterexamples;
4. open-source writing projects were referenced without consistently auditing
   their corpus, version, license, and transfer boundary;
5. only positive examples were considered, which is insufficient to estimate
   whether an assessor distinguishes strong from weak writing;
6. the SciTaste manuscript was checked for local antipatterns rather than for
   end-to-end claim--evidence closure.

This study addresses items 1--4 and makes items 5--6 explicit next work rather
than silently treating them as solved.

## Research questions

The study asks five narrower questions.

- What recurring argument structures appear across officially recognized ICLR
  papers rather than only within one subfield?
- Which structures are conditional on empirical, systems, discovery, mixed, or
  pure-theory work?
- What scientific duty do figures, tables, algorithms, proofs, and real-world
  tests perform in those structures?
- Which open-source writing practices have sufficient provenance and licensing
  to inform SciTaste, and which must remain comparison-only?
- Against those observations, what is missing from the current SciTaste paper?

## Sampling protocol

### Positive population

The positive population is the complete set of 29 papers named as Outstanding
Paper or Honorable Mention in the official ICLR award announcements from 2023
through 2026:

- ICLR 2023: 4 Outstanding Papers;
- ICLR 2024: 5 Outstanding Papers and 11 Honorable Mentions;
- ICLR 2025: 3 Outstanding Papers and 3 Honorable Mentions;
- ICLR 2026: 2 Outstanding Papers and 1 Honorable Mention.

The population rule was chosen before cross-paper synthesis. No paper was
removed because it contradicted a preferred rule. This matters because the
award committees explicitly valued a mixture of conceptual insight, practical
impact, writing, and experimental rigor rather than a single paper form. The
2026 process also records expert consultation and acknowledges the subjectivity
of award selection.

Official selection sources:

- [ICLR 2023 Outstanding Paper announcement](https://blog.iclr.cc/2023/03/21/announcing-the-iclr-2023-outstanding-paper-award-recipients/)
- [ICLR 2024 Outstanding Paper and Honorable Mention announcement](https://blog.iclr.cc/2024/05/06/iclr-2024-outstanding-paper-awards/)
- [ICLR 2025 Outstanding Paper and Honorable Mention announcement](https://blog.iclr.cc/2025/04/22/announcing-the-outstanding-paper-awards-at-iclr-2025/)
- [ICLR 2026 Outstanding Paper and Honorable Mention announcement](https://blog.iclr.cc/2026/04/23/announcing-the-iclr-2026-outstanding-papers/)

The current target-venue construct is taken from the
[ICLR 2027 Reviewer Guide](https://iclr.cc/Conferences/2027/ReviewerGuidelines).
Reviewers are asked to identify the paper's question, motivation and placement,
claim support and rigor, and significance. Clarity, correctness, experimental
rigor, reproducibility, and novelty are considered strengths, but the guide
explicitly recognizes different objectives and does not require a leaderboard
result. SciTaste's writing model should therefore preserve distinct constructs
instead of compressing them into a generic quality score.

### Missing comparison populations

Award recognition is a strong positive signal, not a causal label for writing
quality. Two comparison populations remain required:

1. accepted non-award ICLR papers, stratified by archetype and review score;
2. rejected or deliberately perturbed papers containing known coherence,
   evidence, positioning, and presentation faults.

Until these are annotated, the present corpus can support pattern discovery and
counterexamples but not thresholds, acceptance prediction, or false-positive
claims.

## Extraction protocol

Each paper received a structural and targeted reading pass covering the title,
abstract, introduction, contribution statement, section progression, primary
result carriers, discussion/limitations, and appendix role. The study records
an original paraphrase of the paper's evidence arc and the role of its primary
carriers. It does not copy source prose.

PDFs were converted using `pdftotext -layout`. A reproducible mechanical pass
counted unique Arabic-numbered Figure, Table, and Algorithm labels. The PDF
SHA-256 values in the corpus file bind these measurements to the acquired
versions. The PDFs and extracted text remain temporary research inputs and are
not committed.

These counts have strict limitations:

- they include appendices;
- they miss unnumbered panels, theorem environments, and extraction failures;
- they measure quantity, not argumentative quality;
- different versions can have different pagination and appendices;
- they must not be converted into minimum-count rules.

## Corpus-level observations

The 29 PDFs contain 910 pages, 301 distinct figure labels, 178 table labels, and
31 algorithm labels under the extraction method above. Median counts are 9
figures and 5 tables. Twenty-eight papers contain at least one numbered figure;
25 contain at least one numbered table.

Those aggregate numbers are less important than the exceptions:

- *Transformers are Inherently Succinct* contains no numbered figures, tables,
  algorithms, or empirical experiments. Its evidence is a formal chain of
  definitions, separation results, complexity consequences, and proofs.
- *Robust agents learn causal world models* is also pure theory but uses causal
  diagrams to make its objects and assumptions legible.
- *Amortizing intractable inference in large language models* contains only
  three numbered figures, while formal objectives and task tables carry much of
  its empirical argument.
- *The mechanistic basis of data dependence and abrupt learning* uses no
  numbered tables; controlled curves and a minimal mechanistic model are the
  appropriate carriers.
- *Never Train from Scratch* and *SAM 2* use many tables because their central
  obligations include systematic comparison across settings.

The supported conclusion is therefore not “top papers have many figures.” It
is: **top papers make their principal claims inspectable through an appropriate
set of primary evidence carriers, and carrier choice depends on the claim and
paper archetype.**

## Paper-by-paper evidence arcs

The table below is intentionally compact. Detailed URLs, hashes, counts,
carrier types, and boundary notes are in the corpus file.

| ID | Recognition | Archetype | Distilled evidence arc |
|---|---|---|---|
| 2023-vtm | Outstanding | Empirical method | Unified task need → visual-token method → broad task evaluation → support/training sensitivity |
| 2023-gnn-biconnectivity | Outstanding | Theory + empirical | Counterexample to existing expressivity view → formal characterization → new procedure → controlled validation |
| 2023-dreamfusion | Outstanding | Empirical method | Text-to-3D gap → score-distillation method → perceptual and quantitative evidence → seed/guidance/failure analysis |
| 2023-emergence-maps | Outstanding | Empirical discovery | Navigation phenomenon → neuron and memory diagnostics → alternative-explanation controls → map decoding |
| 2024-diffusion-generalization | Outstanding | Theory + empirical | Memorization/generalization transition → inductive-bias hypothesis → adaptive-basis mechanism → synthetic validation |
| 2024-unisim | Outstanding | Empirical system | Heterogeneous data problem → unified simulator → interaction/application tests → joint-training failure control |
| 2024-never-train-scratch | Outstanding | Empirical analysis | Comparison fairness problem → matched setup → successive fairness questions → scale/pretraining controls |
| 2024-protein-walk-jump | Outstanding | Empirical method | Discrete generation problem → sampling method → in-silico screening → wet-lab validation |
| 2024-vit-registers | Outstanding | Empirical discovery | Artifact detection → causal hypothesis → minimal intervention → downstream and qualitative verification |
| 2024-amortized-inference | Honorable Mention | Empirical method | Motivating sampling case → posterior formulation → amortized method → four-task evaluation |
| 2024-nash-stochastic | Honorable Mention | Theory + empirical | Estimable equilibrium loss → formal properties → convergent algorithms → targeted empirical comparison |
| 2024-beyond-wl | Honorable Mention | Theory + empirical | Coarse-measure limitation → quantitative definition → unified characterization → theory-aligned tests |
| 2024-flow-matching-geometries | Honorable Mention | Theory + empirical | Geometric generation gap → closed-form construction → scalable implementation → cross-geometry evaluation |
| 2024-one-video | Honorable Mention | Empirical method | Data-efficiency question → dataset characterization → tracking-based method → ablation and downstream comparison |
| 2024-meta-continual | Honorable Mention | Theory + empirical | Unified Hessian view → Meta-CL reinterpretation → variance-reduced method → multi-setting tests |
| 2024-kv-compression | Honorable Mention | Empirical system | Attention-structure diagnosis → adaptive policy → quality/memory tradeoff → latency and profiling overhead |
| 2024-contamination | Honorable Mention | Theory + empirical | Auditability problem → statistical test → power/false-positive analysis → public-model audit |
| 2024-causal-world-models | Honorable Mention | Pure theory | Necessity question → formal tasks and shifts → necessity theorems → interpretations and assumption limits |
| 2024-abrupt-learning | Honorable Mention | Empirical discovery | Controlled task → abrupt transition → progress-measure diagnostics → minimal mechanistic model |
| 2024-data-selection | Honorable Mention | Theory + empirical | Selection problem → asymptotic theory → counterintuitive predictions → synthetic and real validation |
| 2025-safety-alignment | Outstanding | Empirical discovery | Shallow-alignment diagnosis → vulnerability link → deep-alignment counterfactual → mitigation and attack tests |
| 2025-learning-dynamics | Outstanding | Theory + empirical | Pedagogical phenomenon → SFT/DPO decomposition → empirical verification → mechanism-derived intervention |
| 2025-alphaedit | Outstanding | Theory + empirical | Editing interference → null-space constraint → multi-model comparisons → retention, limits, and cases |
| 2025-data-shapley | Honorable Mention | Theory + empirical | Valuation cost problem → one-run estimator → runtime/fidelity tests → usefulness cases |
| 2025-faster-cascades | Honorable Mention | Theory + empirical | Cascade tradeoff → optimal deferral → speculative hybrid → cost/quality/speed frontiers |
| 2025-sam2 | Honorable Mention | Empirical system | Image/video task unification → model/data-engine co-design → zero-shot evaluation → scale/component ablations |
| 2026-transformers-succinct | Outstanding | Pure theory | Alternative expressivity measure → definitions → separation theorems → verification consequence |
| 2026-multiturn-lost | Outstanding | Empirical discovery | Deployment/evaluation gap → paired sharding protocol → broad factorial tests → aptitude/reliability decomposition |
| 2026-polar-express | Honorable Mention | Theory + empirical | Deep-learning numerical requirements → minimax approximation → finite-precision algorithm → convergence/training tests |

## Open-source project audit

Open-source projects are not treated as evidence of conference acceptance.
They contribute reusable workflow ideas only when provenance and legal use are
clear. All versions below were inspected on 2026-09-09.

| Project | Pinned commit | License status | SciTaste use |
|---|---|---|---|
| [anti-defensive-writing-Skill](https://github.com/Adkid-Zephyr/anti-defensive-writing-Skill) | `b32067b3055d356e007c6986775fee069da3891a` | MIT | Adapt positive-scope, non-chronological story, and experiment-duty principles; reject concealment of material weakness or counterevidence. |
| [embodied-ai-paper-writer](https://github.com/OpenGHz/embodied-ai-paper-writer) | `6d30f1bbd6d6ed9d2c2814b052bbfbb3a2ff87c9` | MIT | Study its explicit 63-item roster, task-routed playbooks, figure roles, and corpus-to-rule method; do not transfer robotics-specific numerical thresholds. |
| [academic-paper-writing-skill](https://github.com/ldwww-divesss/academic-paper-writing-skill) | `0dcd6856573ae96a1e80342d5df1224752bb0d28` | MIT | Adopt source-map, preference hierarchy, tension-resolution, write-first evidence planning, and whole-paper audit methodology with attribution. |
| [paper-writing-guide](https://github.com/write-with-ai/paper-writing-guide) | `d60cd06fc330a4b7f715f17b321e5535fc4bf6bc` | No license file observed | Cite for comparison only; do not copy or import rules. Its single-center and question-organized framing must be independently supported by the paper corpus. |
| [nature-writing-skill](https://github.com/SyntaxSmith/nature-writing-skill) | `c1a8716047b6304d922b9528a18421203e3e7acc` | No license file observed | Study the corpus-to-routed-playbook organization only; do not copy text or transfer Nature-specific voice to ICLR. |
| [releasing-research-code](https://github.com/paperswithcode/releasing-research-code) | `a5b2c85490435108e306d38c64a0d2a558f110e6` | MIT | Use as a separate artifact-completeness reference for training/evaluation entry points and result reproduction, not as a paper-writing score. |

Three lessons follow from this audit.

First, a public GitHub repository is not automatically a reusable normative
source. No-license repositories remain comparison-only. Second, a large corpus
claim is only as useful as its roster and inclusion policy: the embodied-AI
project exposes its roster, but mixes award winners, finalists, workshops,
notable papers, and adjacent papers, so its numeric style thresholds remain
domain hypotheses. Third, the strongest transferable method is not a sentence
template; it is a provenance pipeline that preserves source, scope, conflicts,
and exceptions.

## Distilled candidate principles

The synthesis yields fifteen candidates. They are phrased as diagnostic
questions and design obligations, not stylistic commandments. Supporting and
boundary paper IDs are recorded in the corpus file.

### 1. One scientific center

The paper should have one central answer. Other contributions support, extend,
operationalize, or bound that answer. This does not prohibit several technical
components; it prohibits several unrelated centers of gravity.

### 2. Promise--delivery contract

The title, abstract, and introduction promise a question and answer. The method,
proofs, results, and conclusion must visibly deliver them at the same scope. A
strong introduction is therefore a contract with downstream evidence, not an
isolated prose artifact.

### 3. Question-driven evidence progression

Empirical results should be ordered by the uncertainties they resolve. The run
order, development history, test-suite layout, and artifact inventory are not a
scientific narrative.

### 4. Every important claim has a primary carrier

A reviewer should be able to name what they inspect first to verify a claim: a
theorem, controlled comparison, table, curve, qualitative panel, audit, or
real-world test. Prose interprets the carrier; it does not replace it.

### 5. Visual completeness is type-conditioned

The correct obligation is to provide the figures, tables, formal statements, or
other carriers demanded by the claims. The corpus decisively rejects universal
figure and ablation quotas. Pure theory may need no experiment; a systems paper
may need model, data, latency, quality, and failure evidence.

### 6. Mechanistic stories climb a diagnostic ladder

A mechanistic claim should progress from phenomenon to discriminating
diagnostics and then to an intervention or novel prediction. Correlation alone
does not earn mechanistic language.

### 7. Set up a fair contest

Comparative claims must expose and match the resources that could explain the
result: data, compute, model scale, tuning, evaluation access, and preprocessing.
This is scientific validity, not optional rhetorical polish.

### 8. Stress the central claim, not the appendix

Robustness, sensitivity, scale, seed, and ablation studies should target the
failure modes and alternative explanations of the central claim. A long pile of
standard ablations can still leave the important uncertainty unresolved.

### 9. Close the world interface

When the contribution crosses into a system or application, evaluate the point
where it touches users, hardware, data, or downstream tasks. Proxy-only evidence
cannot silently support a real-world claim.

### 10. Every visual has an argumentative duty

A figure or table must make a scientific relation, comparison, mechanism, or
boundary easier to verify. Its takeaway should be expressible in one sentence,
and the text should explain why the observed pattern matters rather than
redescribe every mark.

### 11. Main-text evidence comes first

The evidence required to believe the headline claim belongs in the main text.
Appendices deepen derivations, settings, robustness, and reproducibility; they
must not rescue a central argument absent from the paper body.

### 12. Boundaries appear once, precisely, and honestly

Limitations that alter validity, scope, safety, ethics, or reproducibility remain
visible. They should be stated precisely where they change interpretation, not
repeated as defensive self-negation. This resolves the tension between
anti-defensive writing and scientific integrity.

### 13. Theory exposes a proof chain

Definitions, intuition, main results, proof dependencies, consequences, and
assumptions should form a navigable chain. Benchmark and ablation expectations
must not be projected onto a contribution whose actual evidence is formal.

### 14. Reproducibility is part of the claim

The paper and repository together should expose the data, procedure, settings,
compute, and evaluation path needed to recreate the principal result. A passing
test suite is useful artifact evidence but is not a substitute for the
experiment supporting the scientific claim.

### 15. High-attention entry points agree

The title, abstract, introduction, first explanatory carrier, headline result,
and conclusion should expose the same question, answer, terminology, and scope.
This is the whole-paper coherence constraint missing from a collection of local
sentence critics.

## What is not supported

The study explicitly rejects the following shortcuts:

- “Every strong paper needs at least N figures/tables/ablations.”
- “More experiments imply a stronger paper.”
- “An accepted or awarded paper proves that each of its stylistic choices is
  causal or universally good.”
- “A high automated score establishes scientific quality.”
- “Limitations should be hidden to make the paper more persuasive.”
- “A single writing skill or prompt can be imported as Writing Taste.”
- “Repository completeness, prose fluency, and claim validity are one metric.”

## Gap map for the current SciTaste manuscript

The current source is `manuscripts/scitaste/main.md`. It has approximately 4,800
assessor-tokenized words, an explicit framework and evaluation protocol, zero
embedded figures, and one table. That table assigns architecture ownership; it
does not carry an experimental result. The Results section reports one completed
controlled task and integration evidence in prose. The registered 48-cell study,
blinded expert paper evaluation, independent Writing Taste annotations, and
comparative effectiveness analysis remain pending.

Against the candidate principles, the highest-value gaps are:

| Priority | Missing carrier or closure | Why it matters | Honest current action |
|---|---|---|---|
| P0 | Headline effectiveness evidence | The title and motivation imply improved research decision making, but the completed evidence establishes control, provenance, and one-task execution rather than improved research yield. | Keep the claim bounded or complete the matched 48-cell study and blinded review. |
| P0 | Main results table/curves | Key outcomes, conditions, uncertainty, and exclusions are difficult to audit in prose. | Define the registered table/plot contracts now; populate only from completed evidence. |
| P0 | Whole-paper claim--carrier map | The paper names four contributions but does not expose one inspectable carrier per contribution. | Add a typed map from headline claims to theorem/test/table/figure/evidence IDs. |
| P1 | Fig. 1 scientific overview | The controller/executor boundary, nonlinear loops, and persistent state are central but currently require several paragraphs to reconstruct. | Build an editable figure from the existing visual contract without inventing results. |
| P1 | Comparative architecture table | Related systems are discussed narratively, but the exact distinction among pipeline ownership, state, contradiction handling, and provenance is not inspectable. | Add a sourced, carefully scoped comparison after verifying every cell. |
| P1 | Failure-recovery case figure | Recovery and fail-closed behavior are meaningful engineering contributions but are listed as events. | Show one evidence-preserving failure/recovery trajectory with artifact IDs and boundaries. |
| P1 | Ablation of the claimed decision layer | The present single-task run does not isolate which Taste components matter. | Execute only after the matched protocol and component interventions are frozen. |
| P2 | Independent writing-quality validation | A deterministic assessor passing its own rewrite demonstrates surface consistency, not expert Writing Taste. | Annotate accepted, rejected/perturbed, and SciTaste drafts; measure agreement and errors by archetype. |

This gap map changes the near-term writing plan. The next paper iteration should
not merely add polished paragraphs. It should first define a claim--carrier
matrix, figure/table contracts, and the evidence required to populate them.
Unavailable results stay visibly pending; empty registered shells are preferable
to invented values.

## Promotion and validation plan

The candidate principles can enter production only through the following steps.

1. Add accepted non-award and negative/perturbed comparison sets.
2. Define an annotation manual that separates scientific integrity, global
   coherence, evidence completeness, reader guidance, and local style.
3. Obtain independent human annotations, adjudicate disagreements, and preserve
   the rejected interpretations.
4. Measure false positives and false negatives separately for pure theory,
   theory--empirical, empirical method, empirical discovery, and systems papers.
5. Promote only validated principles into typed, provenance-bearing Taste Cases.
6. Keep corpus counts descriptive and outside submission eligibility gates.
7. Evaluate whether the model-assisted semantic node improves agreement over
   deterministic checks without gaining evidence or mutation authority.

The immediate implementation target is consequently a research-facing contract,
not another regex: paper archetype, central question and answer, headline claim
IDs, primary evidence carriers, expected figure/table roles, unresolved evidence
obligations, and entry-point consistency. Enforcement should distinguish
`missing evidence`, `missing presentation carrier`, and `unsupported claim`
rather than treating all three as writing defects.

## Limitations of this study

- Award selection combines research contribution and presentation; it is not a
  writing-only label.
- The 2023--2026 window may overrepresent recent LLM, vision, and system norms.
- Structural targeted reading does not yet provide sentence-level rhetorical
  annotation.
- Mechanical carrier counts include appendices and can be affected by PDF
  extraction.
- The open-source project audit establishes provenance and transfer limits, not
  project effectiveness.
- No independent annotator has yet reviewed the evidence arcs or candidate
  principles.

These limitations are reasons to hold rule promotion, not reasons to discard the
reference library. The study's purpose is to turn future Writing Taste changes
into explicit, reviewable decisions instead of untraceable prompt intuition.
