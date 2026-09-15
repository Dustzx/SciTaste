# SciTaste idea and positioning memo v1

Date: 2026-09-15

Status: candidate research-positioning memo. It does not yet authorize a
manuscript claim or experiment and does not report an effectiveness result.

Project-owned self-iteration:
`outputs/projects/scitaste-self-development/runs/2026-09-14__scitaste-native__lifecycle-taste-idea-refinement-v1__seed-00/idea_refinement/REVISION.json`.
The current binding is structurally verified, remains `candidate`, and is not
selected for the paper.

## One-sentence thesis

> SciTaste learns Scientific Taste as a unified lifecycle meta-policy over
> consequential autonomous-research decisions by assigning delayed research
> outcomes and human corrections back to the choices that produced them.

This is the single candidate paper idea. Scientific Taste, Generation as
Content, and Tool Intelligence are not three innovations to stack. The learned
lifecycle policy is the research object; grounded precedents, Tool Intelligence,
and Generation as Content are its data, observation, and intervention
mechanisms. They belong in the paper only to the extent that they help learn or
evaluate that one policy.

## Does SciTaste have scientific taste today?

The precise answer is: **SciTaste has an explicit Taste substrate, but it does
not yet have a demonstrated, continually acquired scientific-taste capability.**
Five claims that are easy to conflate must be separated:

| Maturity level | Meaning | Current status |
|---|---|---|
| Taste prior | The underlying LLM already contains implicit research preferences from pretraining | Present but uncontrolled, unmeasured, and not a SciTaste contribution |
| Taste substrate | Typed `TasteCase`, library, retrieval, transfer deliberation, critics, controller, and outcome-gated admission contracts exist | Implemented |
| Operational Taste | A sufficiently broad, source-grounded set of precedents actually changes decisions across the research lifecycle | Only small curated/fixture evidence; not established for the self-development project |
| Learned Taste | Reviewed decision--outcome episodes estimate a reusable, abstaining lifecycle preference policy | Estimator, attribution review, admission, split, and inference contracts are implemented on authored fixtures; no natural self-project episode has completed the path |
| Generalised model Taste | A trained model or adapter improves held-out action judgment beyond raw RAG and in-context cases | Not implemented or evidenced |

The available offline acceptance assets include a small seed library of curated
communication, discovery, and review rules. They prove that the representation
can be loaded and used; they do not prove that SciTaste has learned scientific
judgment. In the self-development runs inspected on 2026-09-14, recorded native
decisions commonly contain an empty `retrieved_taste_cases` field. A controller
choosing actions from hand-authored utilities without a retrieved precedent is
a research policy, but it is not evidence that the system has acquired Taste.

Accordingly, repository completeness and scientific capability must use
different language:

> The Taste machinery and a first estimated-policy path exist. The initial
> training content is authored fixture data, not natural longitudinal evidence.
> The live experience-learning loop and the improvement claim remain unverified.

For the project, “overall scientific taste” should mean the conjunction of:

1. coverage across strategic, epistemic, experimental, adaptive, review, and
   communication decisions;
2. grounded acquisition from strong external research episodes;
3. transfer-aware application to a live project state;
4. correction from human intervention and real outcomes; and
5. held-out evidence that these mechanisms improve decisions and downstream
   research progress under matched resources.

SciTaste cannot claim overall Taste until all five are present. This definition
also prevents a fluent model response, a static prompt, or a manually written
rule from being counted as acquired scientific judgment.

## Stronger conceptual core

High-quality content does not itself contain an exportable Taste object. A
finished paper usually exposes the selected path while hiding rejected ideas,
failed experiments, reviewer-induced revisions, stopping decisions, and the
information available when each choice was made. Directly retrieving such a
paper therefore transfers conclusions or style more readily than judgment.

SciTaste's central technical problem is **long-horizon credit assignment over
research trajectories**:

> Given delayed, sparse, partially subjective, and execution-confounded research
> outcomes, determine which earlier consequential decisions should change and
> learn a policy that improves the next trajectory.

**Latent decision reconstruction** is a necessary input operator, not the whole
idea:

> Given a high-quality scientific episode, reconstruct which consequential
> choice was made, against which plausible alternatives, using what evidence,
> with what outcome, and under which conditions that preference should reverse.

This yields a sharper decomposition:

```text
quality signals identify candidate episodes, but do not define Taste
    -> source bundles recover decision context and alternatives
    -> grounded abstraction produces a contrastive, bounded precedent
    -> live-state deliberation decides whether the precedent transfers
    -> execution and human review reveal whether the applied judgment worked
    -> only outcome-bound, independently reviewed episodes update Taste
```

The learning target is consequently not “write like an excellent paper” or
“predict which paper will be cited.” It is the conditional preference

```text
P(research action | project state, available evidence, alternatives, budget)
```

together with an abstention/transfer policy. The policy must know both what to
prefer and when its precedent is inapplicable. This is the deepest distinction
from raw RAG, scalar impact prediction, static user-taste profiles, and generic
self-reflection.

The paper's primary hypothesis should therefore be stated causally:

> Under the same base model, information, tools, and budget, a lifecycle Taste
> policy updated from grounded trajectory outcomes and human corrections improves
> held-out research decisions and downstream research progress over a static
> controller, pointwise judgment, raw retrieval, and unstructured reflection.

Generation as Content and Tool Intelligence support this hypothesis in
different ways. GAC obtains otherwise-hidden human corrections and
counterfactual preferences; Tool Intelligence obtains otherwise-missing
action-cost and scientific-outcome observations. Neither counts as Taste until
its trace is bound into a reviewed decision episode, and neither should be a
co-equal paper claim unless its incremental effect is separately measured.

## Taste provenance: lifecycle coverage is not enough

Taste must be broad on two independent axes:

1. **decision coverage**: strategic, epistemic, experimental, adaptive, review,
   and communication choices; and
2. **source coverage**: external exemplars, contrasts and failures, expert
   corrections, community or institutional traces, and the project's own
   outcome-bound experience.

A system that covers every workflow stage but uses only one source, such as a
fixed user prompt, has broad control but narrow Taste. A system with millions of
citation labels but only paper-level impact judgments has broad source volume
but narrow decision coverage. Overall Taste requires both axes.

### Three Taste sources and three orthogonal system planes

For a conference-level method, the concrete sources compress into three Taste
channels:

1. **scientific precedent** from papers, artifacts, reviews, revisions, and
   community or institutional traces;
2. **endogenous experience** from live decisions, tools, experiments, failures,
   costs, and delayed research or review outcomes; and
3. **exogenous intervention** from human accept/reject/edit decisions,
   priorities, critiques, scopes, and counterfactual corrections.

These are information sources, not three owner modules. The system itself has
three orthogonal planes:

| Plane | Question answered | Role in Taste |
|---|---|---|
| Scientific Taste | What constitutes and applies scientific judgment? | Defines the episode, authority, memory, transfer, and research-action policy |
| Tool Intelligence | Where should bounded semantic agency replace a rigid rule or invoke a tool? | Intervenes across acquisition, deliberation, control, and outcome reflection |
| Generation as Content | How can a human understand and change the live research object? | Exposes evidence/alternatives and captures scoped external Taste intervention |

The corrected architecture is therefore cross-cutting:

```text
scientific precedent ----+
endogenous experience ---+-> acquire -> deliberate -> control -> evolve Taste
human intervention ------+                  ^             ^
                                            |             |
                              Tool Intelligence at semantic hotspots
                                            ^
                              Generation as Content at human hotspots
```

**Scientific Taste Core** is not meant to denote a separate intelligent agent.
It is the domain and governance contract that defines source validation,
episode identity, authority/conflict handling, quarantine, admission, transfer,
and permissible research actions. **Taste Controller** is its decision-authority
component. Both may call Tool Intelligence, but accepted semantic advice remains
inside their deterministic evidence, budget, identity, and state-transition
boundaries.

This interpretation is already partially present in the implementation:

| Taste lifecycle point | Tool-Intelligence-style semantic intervention | Current status |
|---|---|---|
| Discover contrastive sources | `ReferenceMiningNode` | Implemented as proposal-only `ModelNode` |
| Judge whether a source can teach Taste | `ReferenceQualityNode` | Implemented as proposal-only `ModelNode` |
| Distil a grounded, bounded precedent | `GroundedTasteAbstractionNode` | Implemented as proposal-only `ModelNode` |
| Assess whether precedents transfer to the live decision | `TasteDeliberationNode` | Implemented as proposal-only `ModelNode` |
| Concretise protected candidate templates | `CandidateGenerationBackend` in `TasteController` | Implemented, but uses a controller-specific backend path |
| Select among fixed budget-feasible actions | `PreferenceBackend` in `TasteController` | Implemented, but not unified with the durable `ModelNodeRuntime` |
| Diagnose an outcome and distil process Taste | `compile_process_taste_episode_candidate` plus reviewed outcome attribution | Deterministic quarantined-candidate compiler implemented; autonomous diagnosis and a natural live episode are not demonstrated |
| Admit a precedent or mutate canonical research state | No model node may own this authority | Deterministic/human boundary intentionally retained |

The named Tool Intelligence package is currently narrower than this conceptual
plane: its documentation calls it bounded execution intelligence, and its first
catalog focuses on tool planning, structured repair, cost-sensitive verification,
and durable read-only execution. The shared `ModelNode` substrate already extends
the same proposal-only pattern into Taste, review, and interpretation. The
conceptual cleanup should therefore broaden Tool Intelligence as the horizontal
bounded-semantic-agency plane while retaining its named execution runtime as one
subsystem, rather than pretending that the Taste nodes are unrelated machinery.

Within this broader plane, **Outcome-grounded Process Taste Miner** is one
post-action Tool Intelligence identity. It observes a consequential event,
decides which diagnostic evidence is missing, invokes bounded probes, separates
execution failure from scientific failure, proposes causal attribution,
recovers alternatives and a counterfactual, and emits a quarantined
`TasteEpisodeCandidate`.

Its role family can be expressed as:

```text
Tool Intelligence
  |- source miner/qualifier      what prior episode can teach this decision?
  |- semantic tool planner       what bounded tool action could help?
  |- cost-sensitive router       is a check worth its cost and risk?
  |- structured repairer         can an invalid bounded artifact be repaired?
  |- Taste deliberator           does a precedent transfer to this state?
  |- bounded action adviser      which feasible action is preferred?
  |- execution observer          what exactly ran and what was observed?
  `- process-Taste miner         what scoped lesson might this episode support?
```

A workflow invokes only the role needed at its current semantic hotspot. Tool
Intelligence must not admit its own Taste candidate: a tool reporting
`succeeded` does not establish scientific success, and a model-written
reflection does not establish its own causal interpretation. The Taste Core
waits for the required outcome horizon and independent evidence/review before
making the episode reusable.

#### Outcome-calibrated Taste evolution: ownership boundary

The conference contribution should be called **outcome-calibrated Taste
evolution**, not assigned wholesale to either Tool Intelligence or a generic
“Taste Control” block. It has three distinct responsibilities:

| Responsibility | Proper owner |
|---|---|
| Acquire outcomes, costs and diagnostics; classify the event; propose causal reflection, alternatives and counterfactuals | Tool Intelligence |
| Bind the exact decision and outcome, resolve evidence/authority conflicts, quarantine, independently review and admit the scoped precedent | Scientific Taste Core / Taste Memory |
| Retrieve applicable precedents and change a future research action | Taste Controller |

This division extends Tool Intelligence without violating its current identity
as bounded execution intelligence. Its durable leases, action/observation
ledgers, cost-aware routes, and advisory observations are the correct substrate
for the first responsibility. The existing `advisory_only`,
`canonical_evidence=false`, and `state_transition_authorized=false` guarantees
should remain: they ensure the producer of a reflection cannot certify its own
scientific correctness.

The complete endogenous loop is:

```text
Taste Controller chooses a research action
  -> Tool Intelligence plans/executes/observes and requests missing diagnostics
  -> Tool Intelligence emits a quarantined process-Taste candidate
  -> Taste Core joins delayed scientific/review outcomes and adjudicates scope
  -> an admitted precedent changes a later Taste Controller decision
```

Thus **outcome-grounded process Taste mining** is a first-class Tool
Intelligence role, while the combined loop delivers outcome-calibrated Taste
evolution. Calling all of Tool Intelligence a Taste miner, or calling Tool
Intelligence itself the Taste controller, would both overload the concept and
weaken the causal and safety boundary.

Generation as Content is correspondingly the **external Taste intervention
surface**. It should render the live state, evidence, candidate actions,
uncertainty, and predicted consequences, then capture typed human operations:

```text
accept / reject / edit / reprioritise
identify a missing alternative
challenge evidence or attribution
set applicability scope
state what observation would reverse the preference
```

These operations can immediately control the current project when authorised,
but they become general Taste only after scope and evidence are resolved. A
personal research preference remains user- or project-scoped; it cannot silently
override epistemic-core constraints.

### Source families and their authority

| Source family | Signal contributed | Principal risk | Proper role |
|---|---|---|---|
| High-quality papers and artifacts | Methods, comparisons, evidence standards, and claim calibration | Success-path and publication survivorship bias; rejected alternatives are hidden | Candidate episode discovery, not direct authority |
| Reviews, rebuttals, revisions, and editorial decisions | Explicit criticism, alternatives, and before/after correction | Reviewer inconsistency, venue incentives, and institutional bias | Contrastive supervision with source identity retained |
| Lab notes, experiment logs, code histories, and negative results | Pre-decision state, failures, pivots, costs, and timing | Noisy attribution and incomplete documentation | Highest-value process evidence when traces are intact |
| Expert or user intervention through GAC | Accept/reject/edit choices, priorities, and counterfactual corrections | Personal preference can be mistaken for scientific quality | Project- or user-scoped supervision; never override integrity constraints |
| Tool, experiment, and downstream research outcomes | Real feasibility, information gain, cost, and scientific consequence | Outcome bias, stochasticity, leakage, and delayed effects | Outcome calibration after causal review |
| Community and institutional traces | Citations, adoption, acceptance, replication, and longer-term impact | Prestige, popularity, field-size, and temporal confounding | Weak or delayed proxy; useful for triangulation, not a sole gold label |
| Cross-project comparative episodes | Transfer and repeated success/failure patterns | Domain mismatch and duplicated ancestry | Evidence for transfer boundaries and generality |
| Model self-reflection or synthetic counterfactuals | Cheap hypotheses about principles and alternatives | Self-confirmation and fabricated causal stories | Quarantined candidate generation only |

Source quality is therefore not a scalar prestige score. Admission should depend
on trace completeness, contrast availability, causal attribution, outcome
reliability, reviewer independence, and transfer scope. Conflicting sources
should remain visible rather than being averaged into one unexplained score.

### Taste also has authority layers

The source families instantiate different kinds of preference that must not be
collapsed:

1. **epistemic-core Taste**: validity, falsifiability, controls, evidence and
   claim calibration; this has the strongest authority;
2. **domain Taste**: what questions, methods, and effect sizes are meaningful in
   a field;
3. **project Taste**: objectives, available data, budget, risk, and current
   evidence state;
4. **user Taste**: personally valued directions and styles of exploration; and
5. **venue/communication Taste**: audience, genre, structure, and presentation.

User or venue preference may choose between scientifically valid alternatives,
but it must not make unsupported evidence valid. This distinction is essential
for comparing SciTaste with a static user-taste oracle.

## Failure is a Taste source, not a negative label

Reflection on failure is one of the most valuable Taste sources because it
reveals information that successful papers systematically omit. However,
`outcome = failure` does not imply `decision = bad`:

| Observed episode | Taste interpretation |
|---|---|
| A cheap, diagnostic experiment falsifies a plausible hypothesis | Good experimental and adaptive Taste; update the hypothesis, do not punish the probe |
| An experiment is confounded or cannot distinguish alternatives | Negative experimental precedent, even if its reported metric improves |
| Code, infrastructure, or a tool fails before producing scientific evidence | Primarily Tool Intelligence experience; scientific Taste remains unresolved |
| A sound direction is abandoned because its cost exceeds the project's budget | Contextual strategic/adaptive lesson, not a universal rejection |
| A result succeeds through leakage, cherry-picking, or overfitting | Bad scientific Taste despite a positive metric |
| A reviewer identifies an unsupported claim or missing decisive comparison | Potential review/communication/experimental correction, conditional on the critique being grounded |
| A stochastic run is null or ambiguous | No preference label until uncertainty is reduced |

Likewise, success is not automatically a positive Taste example. Outcome-based
reflection must assess at least:

```text
scientific validity
causal attribution to the selected action
information gained
resource efficiency
robustness or replication
downstream utility
outcome horizon and uncertainty
```

The current `TasteCase.outcome_summary` can narrate these considerations but
does not represent them as independently reviewable fields. The eventual
episode contract should add a typed decision assessment and preserve separate
labels for the hypothesis, experimental design, execution, adaptation, and
claim. This prevents one failed stage from contaminating every kind of Taste.

### Required failure-reflection sequence

```text
pre-action state and prediction
  -> candidate actions and selected action
  -> execution trace
  -> observed outcome and uncertainty
  -> failure-class attribution
  -> what remained scientifically valid
  -> corrected action or stopping rule
  -> counterfactual: what would reverse the lesson
  -> quarantine, independent review, and scoped admission
```

This turns failure from generic retrospective prose into a reusable decision
precedent. It also makes reviewer-driven iteration a genuine Taste-learning
channel: a review matters not because it is negative, but because a grounded
critique changes a decision boundary and the revision outcome later tests that
change.

## Motivation

Autonomous research has made rapid progress in literature search, code
generation, experiment execution, and paper production. Yet increasing the
number of executable actions does not answer which action is scientifically
worth taking. An agent can efficiently pursue an unimportant question, choose
an experiment that cannot distinguish competing explanations, continue after a
decisive negative result, or write a claim stronger than its evidence.

The missing object is the decision between stages. At different points in a
project, the consequential choice may concern:

1. **Strategic taste:** which problem or gap is important and tractable;
2. **epistemic taste:** which hypothesis is precise and falsifiable;
3. **experimental taste:** which comparison or probe is diagnostic and fair;
4. **adaptive taste:** whether evidence warrants continuing, narrowing,
   reformulating, pivoting, or stopping; and
5. **communication taste:** which claim is supported and which reviewer concern
   requires new evidence rather than better prose.

Three common substitutes are insufficient.

- **More execution/search** explores more candidates but can spend more compute
  around the wrong local objective.
- **Paper-level judges or community outcomes** estimate impact, acceptance, or
  likely empirical success, but do not explain what action should be taken in a
  partially observed project or when that judgment stops transferring.
- **Raw retrieval or free-form reflection** supplies facts or retrospective
  prose, but relevance is not a decision rationale and a successful outcome
  does not prove that the preceding decision was sound.

SciTaste therefore asks a narrower and testable question:

> Under matched information, model, tools, and budget, can grounded scientific
> decision precedents improve the next actions and downstream progress of an
> autonomous research system?

This is not only a conceptual gap. A controlled ideation study found that LLM
ideas could look more novel while being slightly less feasible, and the later
[Ideation--Execution Gap](https://arxiv.org/abs/2506.20803) study found that
ratings can deteriorate or reorder after researchers actually execute the
ideas. The decision policy therefore has to survive contact with experiments,
not only predict how a proposal or abstract will be received.

## Method object

The stable unit is a `TasteCase`, not a document chunk or scalar paper score:

```text
TasteCase = {
  pre-decision context,
  evidence available at the time,
  considered alternatives,
  selected action and rationale,
  observed outcome when admissible,
  source support,
  applicability conditions,
  failure conditions,
  counterfactual probe
}
```

The source must support the decision-bearing elements. Applicability and failure
conditions state where a precedent can and cannot transfer. The counterfactual
probe states what new observation would change the preferred action. This makes
Taste a falsifiable decision representation rather than an inspirational
summary.

The complete method is one causal chain:

```text
live decision gap
  -> contrastive source discovery
  -> content-grounded source qualification
  -> grounded contrastive decision distillation
  -> state-conditioned precedent selection
  -> typed research-action control
  -> execution and outcome observation
  -> outcome-gated memory admission
```

Retrieval only constructs a broad candidate pool. Final precedent selection must
check current facts against applicability and failure boundaries, preserve
relevant action tension, and avoid treating lexical overlap as judgment.
Project-generated reflections remain quarantined until their outcomes and causal
interpretations are independently checked.

## How SciTaste improves scientific taste

The important target is not attaching a “Taste” prompt to an agent. It is
improving the policy that chooses scientific actions. SciTaste should combine
three sources of learning signal:

1. **Precedent learning from high-quality content.** External papers, reviews,
   revisions, and research trajectories are qualified and compiled into
   source-grounded `TasteCase` records rather than retrieved as raw authority.
2. **Active experiential learning through Tool Intelligence.** The controller
   chooses probes, checks, and experiments whose expected information value
   justifies their cost. Their real outcomes create decision--outcome episodes
   from which later Taste can be learned.
3. **Interactive correction through Generation as Content.** Evidence-bound
   generated views expose alternatives, uncertainty, and planned actions to a
   human. Typed accept, reject, edit, prioritization, and review responses can
   provide preference, boundary, and counterfactual supervision.

The intended loop is:

```text
high-quality external precedents -------+
                                        |
human correction through generated UI -+-> Taste learner/memory
                                        |        |
tool and experiment outcomes -----------+        v
                                          Taste Controller
                                                 |
                                                 v
                                          Tool Intelligence
                                                 |
                                                 +----> new evidence/outcomes
```

Generation as Content is therefore a **teacher and intervention interface**, not
only a dashboard. Tool Intelligence is an **active evidence-acquisition policy**,
not only a safe tool wrapper. This unifies all three product ideas around
improving scientific judgment while preserving their distinct authority.

### Current implementation boundary

The minimum loop is structurally closed on authored fixtures but empirically
open on natural project trajectories.

- External-source qualification, grounded abstraction, deliberative selection,
  and outcome-gated `TasteMemory` contracts exist, but no natural source or
  project reflection has yet completed the formal admission path.
- Native execution writes the selected `ResearchDecision` and its actual
  executor outcome. Project-aware trajectory reconstruction now verifies the
  exact pre-decision state, alternatives, execution binding, source group, and
  dataset partition without manufacturing a scientific outcome label.
  Retrospective self-project logs remain audit-only, and prospective records
  still require delayed outcome collection.
- Deterministic process-candidate compilation, two independent attribution
  reviews with conditional adjudication, immutable admission, source-group-
  weighted policy estimation, held-out partition exclusion, exact-scope
  transfer checks, and uncertainty abstention are implemented. Their current
  positive examples are authored fixtures; the self-project has no naturally
  observed, independently reviewed training episode or held-out policy effect.
- Generation as Content can collect source-review returns, publish planning
  directives, alter the effective project program, and prepare grounded Taste
  abstraction inputs. Ordinary conversational feedback is not yet compiled into
  a candidate `TasteCase` or a learned preference update.
- Tool Intelligence can select direct, targeted-check, full-preflight, or owner
  routes and retain their observations, but its own contract correctly states
  that observations do not automatically become evidence, state, or Taste.
- `TasteMemoryAdmission` explicitly sets `authorizes_model_training=false`.
  The implemented lifecycle estimator updates a separate **system-level
  behavioural Taste policy** from admitted episodes; it does not update the base
  model's parameters.

The remaining gaps are scientific evidence and live-loop integration, not a
missing estimator: collect natural prospective episodes, obtain genuinely
independent attribution, execute held-out decisions, measure downstream
progress, and connect authorized runtime/GAC events to candidate preparation.

### Parametric Taste learning extension

If the paper intends to claim improvement of the **model's** scientific taste,
not only the agent's context-conditioned behaviour, SciTaste needs an additional
parametric path. Admitted `TasteCase` records naturally define contrastive
training examples:

```text
(pre-decision state, candidate actions,
 preferred action, rejected alternatives,
 source support, applicability/failure boundary, counterfactual state)
```

A lightweight Taste adapter or preference model can learn four coupled targets:

1. action preference under the observed state;
2. evidence-grounded rationale selection;
3. applicability and failure-boundary discrimination; and
4. counterfactual policy change when a decisive state fact changes.

The evaluation must separate the unchanged base model, same-source raw RAG,
in-context TasteCases, the trained Taste adapter, and adapter plus Taste memory
on source- and domain-disjoint decisions. This would distinguish SciTaste from
citation- or acceptance-supervised impact learning: the supervision concerns
process-level actions, alternatives, evidence, transfer, and observed outcomes.
It is a proposed method extension; it is not implemented or evidenced today.

## Related-work landscape

The paper needs separate method, taste, memory/evidence, and benchmark lanes.
A benchmark can provide tasks without being a competing system, and a preprint
must not be described as an accepted method.

### Scientific-taste and research-judgment work

| Work | Status and main object | What it establishes | Gap left for SciTaste |
|---|---|---|---|
| [AI Can Learn Scientific Taste](https://arxiv.org/abs/2603.14473) | 2026 preprint; citation/community-feedback preference learning | Trains a Scientific Judge on field/time-matched paper pairs and a Scientific Thinker to propose high-impact ideas | Defines Taste mainly as idea judgment/ideation for long-term impact; does not control contextual experiment, interpretation, pivot/stop, or claim actions; its own limitations call broader experimental-design taste open |
| [LLMs learn scientific taste from institutional traces](https://arxiv.org/abs/2603.16659) | 2026 preprint; publication-tier preference learning | Shows that institutional outcomes can train field-specific pitch evaluators | Learns institutional selection signals, not grounded action precedents or an autonomous research-control policy |
| [Predicting Empirical AI Research Outcomes](https://proceedings.neurips.cc/paper_files/paper/2025/hash/03f99ca79b87c513d0b502e737a41a41-Abstract-Conference.html) | NeurIPS 2025 method/benchmark hybrid; pairwise idea outcome prediction | Fine-tuning plus retrieval predicts which of two ideas will perform better | Predicts idea outcomes before execution; does not represent why a lifecycle action applies, update a persistent project, or control later scientific decisions |
| [ForeSci](https://arxiv.org/abs/2606.00644) | 2026 preprint; temporally controlled forward-looking research-judgment benchmark | Evaluates 500 tasks across four domains and four decision families, and identifies evidence--decision decoupling | Measures historical foresight rather than learning a reusable, outcome-updated policy over heterogeneous lifecycle actions; invalidates any claim that action-level research judgment or evidence/decision separation is new by itself |
| [An AI Scientist that Doesn't Drift](https://arxiv.org/abs/2608.07542) | 2026 workshop paper/preprint; user-taste graph oracle | A fixed user taste profile changes search direction and cross-stream reuse in one robotics loop | Transfers one researcher's declared preferences; does not acquire community-grounded, source-supported precedents or demonstrate a general multi-domain Taste policy |
| [Why LLMs Aren't Scientists Yet](https://arxiv.org/abs/2601.03315) | 2026 preprint; four end-to-end autonomous-research case studies | Reports weak experimental-design taste among six recurring failure modes | Diagnoses the problem but does not learn, apply, or causally evaluate a scientific-action policy |
| [Why AI R&D Benchmarks Need to Measure Research Judgment Separately](https://bpb-us-w2.wpmucdn.com/voices.uchicago.edu/dist/9/3887/files/2026/03/Position-Why-AI-RD-Benchmarks-Need-to-Measure-Research-Judgment-Separately.pdf) | NeurIPS 2025 workshop position paper | Distinguishes tactical research judgment from brute-force R&D execution | Motivates measurement but does not provide SciTaste's source-to-precedent method or a full controlled system |

These works invalidate any SciTaste claim to be the first formulation, learner,
or benchmark of “scientific taste.” They also sharpen SciTaste's opportunity:
move from paper-level social-outcome preference and static user preference to
evidence-conditioned action preference across the research lifecycle. ForeSci
also means that “research judgment as action selection” and evidence--decision
decoupling are motivation and evaluation foundations, not standalone SciTaste
novelties.

### Autonomous-research methods

| Work | Main contribution | Closest overlap | Remaining distinction |
|---|---|---|---|
| [The AI Scientist](https://www.nature.com/articles/s41586-026-10265-5) | Nature 2026 end-to-end idea, experiment-tree, manuscript, and review pipeline | Idea ranking, experiment journals, tree search, stopping, and final review | SciTaste must show that a separately represented precedent policy improves decisions beyond scaling search or the underlying model |
| [Co-Scientist](https://www.nature.com/articles/s41586-026-10644-y) | Nature 2026 hypothesis generation, debate, ranking, and evolution with expert and wet-lab validation | Explicit hypothesis ranking and iterative scientific refinement | Focuses on hypothesis generation/selection; SciTaste targets a common action representation across experiments, interpretation, stopping, and claims |
| [ResearchAgent](https://aclanthology.org/2025.naacl-long.342/) | NAACL 2025 iterative idea generation over an academic graph with review feedback | High-quality literature structure and iterative idea refinement | Uses literature to improve ideation; SciTaste distils source-grounded decision episodes and applies them after ideation as well |
| [AI-Researcher](https://proceedings.neurips.cc/paper_files/paper/2025/hash/0d904d300a105809a2114d727851e759-Abstract-Conference.html) | NeurIPS 2025 end-to-end multi-agent research and Scientist-Bench | Literature, ideation, implementation, validation, and paper generation | SciTaste targets the decision policy and transferable precedent representation, not another sequence of specialist roles |
| [DeepScientist](https://proceedings.iclr.cc/paper_files/paper/2026/hash/4f64494ecc3442f1c9261baa036378bc-Abstract-Conference.html) | ICLR 2026 long-horizon discovery using Bayesian optimization and Findings Memory | Progressive exploration/exploitation and real objective gains | Findings Memory records results; SciTaste asks how grounded decision precedents guide heterogeneous actions under transfer boundaries |
| [AI Research Agents for Machine Learning](https://proceedings.neurips.cc/paper_files/paper/2025/hash/328b81881da145412f2bc56c998dfb6a-Abstract-Conference.html) | NeurIPS 2025 search policies and operator sets for MLE-bench | Research as search over candidate solutions | Optimizes executable solution search; does not acquire or test scientific decision precedents across lifecycle roles |
| [CycleResearcher](https://proceedings.iclr.cc/paper_files/paper/2025/hash/0a48036026dc7946ef6033ae14719cc5-Abstract-Conference.html) | ICLR 2025 automated research/review preference training | Review-conditioned research improvement | Optimizes generated research and review models; it does not bind decisions to pre-action evidence, alternatives, transfer, and actual outcomes |
| [Agent Laboratory](https://aclanthology.org/2025.findings-emnlp.320/) | Findings of EMNLP 2025 staged human-assisted research | Full workflow and human feedback | Starts from a human idea and emphasizes stage execution; scientific action policy is not its stable learned object |
| [AutoResearchClaw](https://arxiv.org/abs/2605.20025) | 2026 preprint; debate, Pivot/Refine, self-healing, verification, HITL, cross-run evolution | Nonlinear control, failure learning, verified artifacts, and human intervention | These features are no longer independently novel for SciTaste; SciTaste must distinguish itself through grounded precedent acquisition, transfer-bounded selection, and causal Taste evaluation |
| [Sibyl-AutoResearch](https://arxiv.org/abs/2605.22343) | 2026 preprint; self-evolving scientific trial-and-error harness | Defines trial-to-behavior and trial-to-harness conversion, preserves positive/negative outcomes, and routes recurring failures into later behavior | Outcome-to-behavior conversion, failure registries, and harness evolution are not SciTaste novelties; SciTaste must show a learned decision object with grounded alternatives, explicit transfer/reversal boundaries, multi-source acquisition, and controlled effectiveness |
| [EviGraph](https://arxiv.org/abs/2608.04738) | 2026 preprint; typed evidence graph and downstream repair | Persistent claim-evidence structure and repair | Evidence graphs are not a SciTaste novelty; SciTaste's target is choosing the next action using acquired decision precedents |

### Evaluation resources

- [MLR-Bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html)
  evaluates stagewise and end-to-end open-ended ML research and shows that fluent
  outputs can coexist with invalid or fabricated experiment results.
- [EXP-Bench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c411f5b2d9c55f1685e72db224ad8b0e-Abstract-Conference.html)
  evaluates the question-to-conclusion experiment chain; its low complete-success
  rate motivates an integrity diagnostic, not another method baseline.
- [RE-Bench](https://proceedings.mlr.press/v267/wijk25a.html), PaperBench,
  InnovatorBench, InnoGym, and ScienceAgentBench provide complementary objective
  progress, replication, innovation, and execution tasks. None is itself a row
  in an accepted-system comparison unless a separately identified method
  implementation is admitted.

SciTasteBench should be presented as a measurement instrument within the method
paper. Its distinctive target is local, state-conditioned scientific action
quality plus downstream consequences. Until natural source-disjoint cases and
independent expert labels exist, it is a planned contribution rather than an
established benchmark.

## ICLR-level motivation and novelty stress test

### Motivation verdict

The motivation is conference-grade. Independent lines of work now establish a
coherent gap: scalable autonomous-research execution does not guarantee research
judgment; evidence can be correctly retrieved yet coupled to the wrong decision;
weak experimental-design Taste appears in real autonomous-research attempts; and
trial signals are often lost before changing later behavior. SciTaste does not
need to claim discovery of this problem. Its motivation is stronger when it
treats these results as convergent evidence that the unsolved target is a
learnable research-action policy.

### Novelty verdict

The conceptual direction and minimum estimator are implemented, but the current
evidence is **not yet ICLR-safe for an effectiveness claim**. Without natural
training episodes, independently reviewed attribution, and controlled held-out
results, a reviewer can still reasonably describe the system as a careful
combination of RAG, structured reflection, agent memory, model-node guardrails,
and human intervention whose new learned object has only been exercised on
fixtures.

| Candidate claim | Closest prior overlap | Verdict |
|---|---|---|
| Scientific Taste matters for autonomous research | RLCF Taste, kkanbu, ForeSci, empirical failure reports | Motivation, not novelty |
| Research judgment should be evaluated at the action level | ForeSci and research-judgment benchmark work | Not novel alone |
| Failures should change later behavior or the harness | Sibyl-AutoResearch, AutoResearchClaw, reflective agent memory | Not novel alone |
| A user can inject research Taste | kkanbu and HITL systems | Not novel alone |
| Models should be invoked only at bounded semantic hotspots | General tool/model-node and agent-safety design | Valuable engineering, not the primary scientific claim |
| Learn one Scientific Taste policy over consequential decisions across the full research trajectory | Explicit-Taste work focuses on idea/pitch judgment or selected user-taste handoffs; AutoResearch work has broader loops but does not make a unified Taste policy the learned object | Candidate central novelty; estimator implemented, but requires independent novelty challenge and controlled natural-data evidence |
| Reconstruct grounded decision episodes and assign delayed trajectory outcomes back to earlier decisions | Overlaps experience memory, reflection, and trial-to-behavior conversion | Supporting learning mechanism, not an independent headline |
| Show a causal effect beyond the same-source raw evidence, same model, same tools and same budget | Existing systems mostly report package or benchmark performance | Strong evaluation contribution if actually completed |

The novelty must not be defended as a conjunction of familiar components. It
must reside in one irreducible learned object:

> **A unified lifecycle Scientific Taste policy trained through long-horizon
> credit assignment over research trajectories.**

Grounding, transfer boundaries, outcome attribution, Tool Intelligence, and
human intervention are how SciTaste makes this policy trainable and safe; none
is a substitute for the policy itself. The minimum recognizable method should
have three supporting operators:

1. **Episode reconstruction** compiles a multi-artifact source bundle into the
   pre-action state, closed alternative set, decision, grounding, outcome and
   counterfactual boundary;
2. **boundary-aware Taste policy** scores or abstains over current actions using
   applicable precedents while rejecting matched-vocabulary but invalid-transfer
   cases; and
3. **outcome-attributed update** separates hypothesis, design, execution,
   adaptation and claim outcomes before changing the reusable policy.

All three operators now have deterministic repository implementations. That
establishes method availability, not scientific utility: current demonstrations
use authored fixtures, while the decisive prospective, source-disjoint and
downstream-effect evaluations remain unrun.

A parametric adapter is not logically mandatory for a systems paper, but some
learned or estimated policy is strongly preferable for ICLR. If the submission
remains entirely training-free, it must provide unusually strong natural-data,
cross-domain, matched-information, and end-to-end evidence to show that the
method is more than structured retrieval.

### Reviewer questions that the submission must close

1. Why is `TasteCase` not simply a verbose RAG chunk or reflection note?
2. How are hidden alternatives reconstructed without fabricating hindsight?
3. Who labels applicability, failure and counterfactual boundaries, and how
   reliable are those labels?
4. What exact operator generalises beyond the source episode rather than copying
   it?
5. Does matched Taste outperform the same source text, mismatched Taste, generic
   reflection and an outcome-memory baseline?
6. Does the same native executor make better objective progress, or only produce
   more persuasive decisions and papers?
7. Do gains survive source-, task-, domain-, time-, and model-disjoint tests?
8. Does continual update improve later decisions without propagating an
   incorrectly attributed success or failure?

Until these questions have empirical answers, the positioning is suitable for
guiding an ICLR submission but not yet sufficient to claim an ICLR-level result.

## One core contribution and its evidence

The ICLR paper should make one scientific contribution and separate its method
machinery from its evaluation evidence.

### Core: lifecycle Scientific Taste learning

SciTaste learns one contextual policy over problem choice, hypothesis
refinement, diagnostic experiments, interpretation, pivot/stop, review, and
claim calibration. It treats the complete research trajectory, rather than a
paper score or isolated judgment, as the unit from which delayed credit is
learned. The current training-free controller is the substrate and causal
baseline, not the completed contribution.

### Method machinery: grounded trajectory supervision

SciTaste introduces a source-to-policy method: content-grounded source
qualification, latent decision reconstruction, grounded contrastive
distillation, boundary-aware selection, and outcome-attributed memory evolution.
The same episode object can be proposed from scientific records, endogenous
Tool Intelligence traces, or scoped human intervention without erasing source
authority. Episode reconstruction, transfer-bounded selection, and
outcome-attributed update are components of the lifecycle-policy learner, not
three additive novelty claims.

### Evidence: causal evaluation from decisions to research outcomes

The evaluation should connect mechanism to consequence:

- same-source raw evidence versus grounded Taste tests representation;
- matched versus mismatched Taste tests contextual specificity;
- decision-grounded versus lexical selection tests autonomous application; and
- Full SciTaste versus the same native executor without Taste tests objective
  research progress on held-out tasks.

Content-grounded versus prestige-only source selection is valuable supporting
evidence, but need not become a fifth independent headline. Comparisons with
accepted autonomous-research systems test ecological competitiveness and should
remain separate from the within-system causal effect of Taste.

## Claims that must be retired

The manuscript must not claim any of the following:

- first to introduce or learn scientific taste;
- first to formulate or benchmark action-level/forward-looking research judgment;
- first nonlinear, self-correcting, or pivoting autonomous research loop;
- first to turn failed trials into later behavior or harness updates;
- first persistent or cross-run research memory;
- first typed evidence graph or evidence-grounded paper generator;
- first human-intervenable autonomous research system;
- improved research quality based only on repository tests, generated papers,
  model review scores, or the self-development case; or
- a benchmark contribution before the natural population is formally admitted,
  released, and independently validated. AI-panel admission alone supports only
  an internal measurement instrument.

Auditability, provenance, deterministic gates, Generation as Content, and Tool
Intelligence remain meaningful product and enabling-system properties. They
should not carry the paper's primary novelty unless supported by dedicated
comparative evidence.

## Claim-to-evidence contract

| Research claim | Decisive comparison | Primary evidence | Failure condition |
|---|---|---|---|
| Grounded decision representation adds value beyond retrieval | same admitted sources rendered as raw evidence versus TasteCase | condition-blinded AI-panel and natural-outcome proxies over the resulting action and claim calibration | no material advantage or grounding/transfer failures dominate |
| Taste must be context-specific | matched versus source-disjoint, quality- and token-matched Taste | paired AI-panel proxy, transfer error, and calibrated action selection | matched context is not better than mismatched context |
| SciTaste can select useful precedents without an oracle | deliberative versus lexical selection from the same hidden-label pool | AI-panel decision proxy plus applicability, reversal, and failure diagnostics | selection gains require oracle relation labels or extra context |
| Taste improves autonomous research | Full SciTaste versus Native Base with the same model, tools, starting state, and budget | task-level objective progress with failures retained | no task-level gain, invalid evidence, or gain explained by unmatched execution |
| SciTaste is competitive with established systems | separately admitted accepted systems on common tasks | explicitly nonhuman AI-panel package review and objective task scores | adapters or budgets are not comparable; model confounding is hidden |

The current H0/H1/H2a/H2b/H3 registry is useful protocol detail, but the paper
should tell the above three-part story rather than present five equally important
claims or a large cell inventory.

## Paper boundary and title

Before positive held-out mechanism and objective-progress results, use the
evidence-bounded title:

> **SciTaste: Grounded Scientific Taste for Autonomous Research**

The intended result-dependent title remains:

> **SciTaste: Improving Autonomous Research through Scientific Taste**

Under the active AI-only protocol, “Improving” remains unauthorized even if the
grounded-representation, contextual-selection, and held-out objective-progress
results are positive; those results can establish proxy and task-level effects
but not independent Scientific Taste construct validity. Escalating the title
requires a separate construct-validation study. The repository now estimates a
policy rather than only retrieving cases, but “Learning” should appear in a
submitted title only when that estimator is trained and evaluated on non-fixture
episodes.

## Three-minute report

Current autonomous-research systems are increasingly capable executors: they can
search, code, run experiments, recover from failures, and write papers. The
remaining bottleneck is not simply how to do more work, but how to choose the
scientifically valuable next action. Recent work already calls idea-impact
prediction and citation-trained ideation “scientific taste,” and other systems
already support pivoting, evidence graphs, user taste profiles, and cross-run
memory. SciTaste therefore does not claim those concepts first.

SciTaste's distinct hypothesis is that Scientific Taste can be learned as one
lifecycle meta-policy over consequential research actions. A trajectory exposes
multiple coupled decisions whose quality is only partially revealed by later
experiments, reviews, costs, failures, and final research outcomes. SciTaste
reconstructs those decisions as grounded precedents, assigns delayed credit
without collapsing execution failure into scientific failure, and updates the
policy only after scope and attribution are reviewed.

The paper then asks whether this representation changes behavior and outcomes.
We compare it with same-source raw RAG, mismatched precedents, and lexical
selection, then compare Full SciTaste with the same native executor without
Taste on held-out executable research tasks. External accepted systems provide
a separate ecological comparison. This makes the paper a focused method paper
about learning lifecycle Scientific Taste from research trajectories, with the
benchmark, interface, tool routing, and self-iteration case serving that central
claim rather than competing with it.
