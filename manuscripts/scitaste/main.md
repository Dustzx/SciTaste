## Title
SciTaste: Grounded Scientific Taste for Autonomous Research

# Abstract

Autonomous research systems can search literature, write code, run experiments,
and draft papers, but greater execution capacity does not determine which
research action is worth taking. Existing work learns paper- or idea-level
impact judgments, preserves a researcher's stated Taste, or routes trial lessons
into later workflow behavior. We introduce **SciTaste**, a method for learning
scientific taste as a common policy over consequential decisions throughout a
research trajectory. SciTaste represents each learning episode by the pre-decision state,
available alternatives and evidence, delayed outcomes, causal-credit hypotheses,
and conditions under which the preference should transfer or reverse. External
scientific precedents, tool and experiment outcomes, and human corrections share
this representation while retaining distinct authority. Two independent
attribution reviews are required before an episode updates an uncertainty-aware
pairwise policy; source-group weighting and development/held-out partitions limit
duplication and leakage. At inference, the policy applies only under explicit
Idea, domain, stage, support, and uncertainty constraints and otherwise abstains,
while deterministic provenance, budget, and execution gates retain final
authority. We evaluate this hypothesis through matched comparisons against
same-source raw retrieval, mismatched Taste, static and shuffled-credit policies,
and the same native research executor without learned Taste, followed by a
separate comparison with accepted autonomous-research systems. This formulation
makes delayed research judgment, rather than pipeline completion or paper-level
scoring, the object of learning and causal evaluation.

# Introduction

Autonomous research agents now generate ideas, implement experiments, draft
papers, and review them. The AI Scientist and its tree-search successor span this
workflow \citep{lu2024aiscientist,yamada2025aiscientistv2}; MLAgentBench and
PaperBench expose progress and persistent gaps in iterative experimentation and
paper replication \citep{huang2024mlagentbench,starace2025paperbench}. These
systems show rapid progress in research execution.

Execution competence, however, is not identical to research judgment. A
researcher must decide whether an observation is surprising enough to matter,
whether an apparent gain deserves another replicate, whether a contradiction
invalidates the method or reveals a better problem, and whether the current
evidence supports the paper's central claim. These decisions determine the
problem, budget, and final evidence but are often hidden between workflow stages,
allowing more iterations to resemble progress without increasing scientific
value.

SciTaste makes these choices explicit. It treats autonomous research as a
partially observed, resource-bounded control process whose stable unit is a
decision rather than a workflow stage. At each decision point, a persistent
state exposes a finite set of feasible typed actions. The system records the
available alternatives and evidence before one action is selected, delegates
execution through a separate interface, and admits the returned result only if
its identity and evidence satisfy the transition contract. This makes re-probing,
reformulation, pivoting, and stopping inspectable rather than hiding them inside
prompts.

The term *scientific taste* refers here to a conditional preference over such
actions: which problem, probe, interpretation, pivot, or claim is appropriate in
the current state, with the available evidence and budget. It is not a scalar
paper score, a topical passage, or an unconstrained language-model opinion.
Moreover, high-quality content is not itself a Taste label. A published paper
usually reveals the selected path while concealing rejected alternatives,
failed experiments, reviewer-induced revisions, and what was knowable when a
choice was made. Transferring judgment therefore requires reconstructing a
bounded decision episode and assigning later outcomes back to the earlier
choice without turning executor completion or prestige into reward.

SciTaste learns at the system-policy level. An episode closes the pre-decision
state, candidate set, selected action, grounding evidence, delayed outcome
families, confounders, causal-credit hypotheses, transfer conditions, and a
reversal probe. Scientific records, endogenous tool and experiment traces, and
typed human intervention can propose this same object, but none can admit its
own proposal. Two conflict-cleared reviewers independently assess decision and
outcome support, alternatives, credit, scope, and reversal; disagreement
requires a third adjudicator. Admitted episodes estimate factorized Beta
posteriors over pairwise action features with at most one unit of effective
weight per source trajectory. At inference, missing Idea identity, domain or
stage support, sample support, pairwise confidence, or a positive credible
margin causes explicit abstention with zero policy adjustment.

This paper makes three contributions: (i) a unified lifecycle Scientific Taste
policy and outcome-attributed episode contract; (ii) a source-to-policy method
combining decision reconstruction, independent attribution, source-group-aware
estimation, and uncertainty-bounded controller integration; and (iii) a causal
evaluation separating abstraction from raw retrieval, contextual match from
mismatched Taste, outcome learning from static or shuffled credit, and policy
effects from the same native executor without Taste. Accepted-system comparisons
remain separate ecological evidence.

The implementation path is complete enough to make these comparisons
executable, but the current positive examples use authored fixtures. Natural
prospective episodes, independent attribution, held-out policy effects, and
downstream objective-progress results remain pending. We therefore report
existing integration measurements only as implementation evidence and withhold
the stronger result-dependent title *SciTaste: Improving Autonomous Research
through Scientific Taste* until the registered causal gates are positive.

![SciTaste method. External scientific records, endogenous tool and experiment outcomes, and typed human interventions are reconstructed into grounded decision episodes. Independent attribution review admits source-group- and split-bound episodes to an uncertainty-aware pairwise policy. At the next decision, the policy adjusts the fixed controller only when Idea, domain, stage, support, probability, and credible-margin gates pass; otherwise it abstains. Workers remain bounded and deterministic admission alone can change project state.](assets/fig1-scitaste-control.pdf)

# Related Work

End-to-end research agents organize many familiar tools into a long-running
workflow. The AI Scientist established a compelling integrated path from idea
generation to paper review and demonstrated it across several machine-learning
subfields \citep{lu2024aiscientist}. Its successor expands the search over
experimental trajectories and demonstrates a workshop-level paper accepted
through peer review \citep{yamada2025aiscientistv2}. SciTaste shares the goal of
end-to-end autonomy but focuses on a different abstraction boundary. The
central object is not a sequence of agent roles or stages; it is a persistent
scientific state plus an explicit decision over the next research action.
External systems can execute an action, but they do not own the state transition
or silently determine the evidence accepted by the controller.

Several recent works make broad claims about scientific taste that SciTaste must
not appropriate. Tong et al. learn a paper-impact judge from citation and
community feedback and use it to train follow-up ideation
\citep{tong2026scientific}. Gong et al. train field-specific pitch evaluators
from publication-tier traces \citep{gong2026institutional}. These results show
that social outcomes can supervise idea- or paper-level evaluation; our target
instead is an evidence-conditioned policy over heterogeneous actions inside a
trajectory. ForeSci evaluates temporally bounded forward-looking judgments such
as bottleneck, agenda, method, and venue choices and shows that relevant evidence
need not yield the right decision \citep{tian2026foresci}. Action-level judgment
and evidence--decision separation are therefore evaluation foundations, not
SciTaste novelty.

The closest autonomous-research mechanisms also narrow the claim. Kkanbu stores
one user's declared Taste as a typed graph and changes the direction of an
otherwise matched robotics research loop \citep{zhang2026kkanbu}. Sibyl converts
trial outcomes and recurring failures into later behavior and harness changes
across planning, validation, claims, scheduling, and writing
\citep{wang2026sibyl}. Thus neither user-Taste injection nor outcome-to-behavior
routing is new by itself. SciTaste asks a different empirical question: can
multi-source decisions be reconstructed with their alternatives, receive
reviewed delayed credit, estimate one uncertainty-aware lifecycle policy, and
improve held-out choices without transferring outside support?

MLAgentBench and PaperBench primarily test whether an agent can execute an ML
improvement or reproduce a paper \citep{huang2024mlagentbench,starace2025paperbench}.
SciTaste's measurement instrument instead isolates local scientific choices and
then tests downstream objective progress. Execution and judgment are
complementary endpoints: an agent may carry out the wrong plan correctly.

ReAct, Reflexion, and Tree of Thoughts establish action--reasoning interleaving,
episodic feedback, and nonlinear search
\citep{yao2023react,shinn2023reflexion,yao2023tree}. SciTaste's distinction is
not reflection itself but scientific supervision that closes alternatives,
outcomes, causal credit, and transfer before changing a later action.

Finally, retrieval-augmented generation usually retrieves topical information.
SciTaste deliberately separates a Knowledge Library from reviewed Taste
episodes. Knowledge records provide facts, methods, datasets, and prior results;
Taste episodes bind a state and alternatives to an outcome-attributed
preference. Retrieval is only a pool-construction efficiency mechanism. The
policy must still test applicability, support, and uncertainty, and it must
abstain when no episode transfers. Keeping the stores independent makes
same-source raw RAG a direct control: any gain must come from grounded decision
structure and learned preference rather than additional source text.

# Problem Formulation

Let a research state at decision step $t$ be $S_t$. It contains scientific
objects, their provenance, open obligations, and a resource ledger. The
controller receives a closed candidate set $A(S_t)$ of typed actions such as
SEARCH, FORM_WORKING_HYPOTHESIS, PROBE, REFORMULATE_HYPOTHESIS, IDEATE,
COLLECT_EVIDENCE, PIVOT, WRITE, or DROP. It selects an action

$$
a_t = \arg\max_{a \in A(S_t)}
  \left[U_0(a \mid S_t,K_t,B_t) + \Delta_{\pi}(a \mid S_t)\right],
$$

where $K_t$ is factual knowledge, $B_t$ is the remaining budget, $U_0$ is the
fixed controller score, and $\Delta_{\pi}$ is a bounded adjustment from the
learned lifecycle Taste policy. The base score remains visible and budget
feasibility is never overridden. If policy support or scope is insufficient,
$\Delta_{\pi}=0$ for every action.

A candidate learning episode is

$$
e_i=(S_i,A_i,a_i,E_i,O_i,C_i,G_i),
$$

where $E_i$ grounds the decision, $O_i$ separates delayed outcome families,
$C_i$ proposes causal credit and confounders, and $G_i$ records applicability,
failure, and reversal conditions. The episode also freezes Idea revision,
source relationship, natural source group, and dataset partition before review.
Executor success is one observation inside $O_i$ and is not automatically a
scientific label. Two independent primary reviewers must agree on the preferred
action and share supported credit; a substantive split invokes a third
adjudicator. Formal-held-out episodes and self-effectiveness records cannot
train the policy.

For each admitted episode, the preferred action is compared with every recorded
alternative. Confidence weight is divided across alternatives and then across
episodes in the same source trajectory. The current estimator accumulates
weighted wins and losses for action, stage--action, domain--action,
venue--action, tag, and stage--tag features under Beta priors. An action score is
a fixed-weight average of the corresponding posterior log odds. Because
features extracted from one episode are correlated, inference uses the largest
matched posterior variance rather than counting features as independent data.
The policy recommends only if both leading actions have sufficient support,
required stage support is present, domain and Idea bindings match, the pairwise
probability crosses its threshold, and a conservative credible margin is
positive. Otherwise it returns an exact reason-coded abstention.

Execution returns a typed result $R_t$. A transition function validates that
the result belongs to the selected action and predecessor state, that resource
usage is admissible, and that required evidence exists. Only then may the system
produce $S_{t+1}$. This yields two separate questions for every flexible model
or external system: Was its content a useful proposal? Does the deterministic
framework admit that proposal into project state? SciTaste never treats a model
response, generated program, or tool plan as transition authority by itself.

The causal target is research progress under a fixed budget, not policy fit or
stage completion. Mechanism tests therefore hold source bytes, model, context,
tools, and budget constant while changing abstraction, match, selection, or
credit. The system test holds the native executor fixed while toggling the
learned policy. Local endpoints include condition-blinded expert action quality,
calibration, abstention, reversal, and transfer failures; system endpoints use
objective task progress with every failed trajectory retained. Complete-paper
preference and accepted-system comparisons are reported separately because they
introduce writing and implementation confounds.

# Framework: SciTaste

## Persistent research state

SciTaste stores research as versioned typed state rather than a chat transcript.
It retains the active direction, budget, hypotheses, observations, ideas,
experiments, claims, evidence relations, reviewer obligations, writing objects,
and full decision history. Content-derived state identities and monotonic
transitions preserve the evidence behind later revisions. Each project owns its
runs and papers under one manifest; optimistic revisions, safe locators, and
atomic updates prevent a worker or generated view from mixing stale project
states.

## Taste Controller

The Taste Controller owns action selection. It does not execute shell commands,
call arbitrary tools, or accept free-form state mutations. For each decision it
receives actions already valid for the current lifecycle position. The
controller first computes transparent fixed criteria, then may apply the bounded
adjustments of one hash-bound lifecycle policy. A missing or stale Idea binding,
unseen domain or stage, insufficient support, uncertain pairwise preference, or
nonpositive credible margin preserves the original scores. Decision logs retain
the full candidate set, base and adjusted scores, policy and Idea identities,
matched features, abstention reasons, selected action, executor result, observed
outcome, and cost.

Decision families expose different criteria: problem validity and importance;
experiment diagnosticity and cost; evidential support, contradiction, leakage,
and confounding; adaptation value; and claim or communication calibration. This
decomposition makes a preference criticizable without reducing all scientific
judgment to one opaque score.

## Grounded episode learning

SciTaste uses one supervision contract across three information channels.
External scientific records can propose precedents; Tool Intelligence can
propose an interpretation of a project decision and its delayed tool or
experiment outcomes; and Generation as Content can preserve a user's typed
accept, reject, edit, reprioritize, scope, or counterfactual correction. All
three produce a quarantined `TasteEpisodeCandidate`. Source identity is retained:
a personal preference cannot silently become a universal scientific rule, and a
model-generated reflection cannot certify its own credit assignment.

The process candidate compiler requires at least two closed alternatives,
pre-action state and evidence, explicit outcome horizon, outcome-family-specific
credit, confounders, applicability and failure conditions, and a reversal probe.
A human intervention may remain in an awaiting-outcome state until later
evidence is joined by a different attribution producer. Candidate inspection
rehashes every bound artifact and verifies the current Idea revision before
independent review.

Admission is intentionally separate from production. Exactly two independent,
conflict-cleared primary reviewers assess decision trace, outcome trace,
alternatives, credit, transfer scope, and reversal. Agreement admits an immutable
training episode at the lower review confidence; disagreement cannot be resolved
by the producer and requires an independent adjudicator. Source group and split
are frozen before review, all decisions from one source trajectory share a unit
weight ceiling, and formal-held-out records are excluded from training.

The first estimator is a transparent factorized Beta pairwise policy. Its
registered update modes are outcome-updated, no-update, success-only,
failure-only, and shuffled-credit. The latter four are causal controls, not
deployment shortcuts: they test whether reviewed delayed credit contributes
beyond static structure, survivorship-only learning, or the mere presence of
additional episodes. The model is content-addressed and does not change base-LLM
weights. It changes system behavior only through a bounded controller trace.

For endogenous experience, project-aware trajectory reconstruction begins from
a sampling plan frozen before outcome attribution. It replays exact decision-log
bytes, resolves the referenced pre-decision state, preserves the complete action
set, and binds the actual executor result without inventing a scientific reward.
Prospective comparative decisions can then await delayed review outcomes;
retrospective self-development logs remain development audits and cannot support
the paper's effectiveness claim.

## Hypothesis--Probe--Reformulate discovery

Discovery begins with a research intuition rather than a polished idea. The
system converts it into a falsifiable hypothesis, then records cheap probes with
stability, boundary conditions, and alternative explanations. The controller
may validate, re-probe, reformulate, pivot, drop, or advance. Supported initial
hypotheses yield an idea-first path; contradictions can reformulate the problem
before ideation, yielding an evidence-first path without a separate pipeline.
Surviving hypotheses produce a diverse, normalized portfolio selected for
complementary information value, followed by a pilot whose failure remains an
outcome rather than disappearing from the trajectory.

## Evidence and reviewer loops

Claims and evidence remain separate typed objects linked by support or
contradiction. The workflow checks outcomes, uncertainty, confounders, baseline
and compute matching, leakage, and source artifacts before changing state.
Reviewer feedback enters the same loop as atomic obligations: a missing baseline
requires evidence, an overclaim requires revision, and an unclear mechanism may
require analysis. Closure binds the concern to the action and evidence that
addressed it.

## Taste-aware communication

SciTaste treats communication as another evidence-bound decision family. A
narrative spine and whole-paper contract connect the central question and answer
to claims, sections, and their primary empirical, formal, or visual carriers.
Critics check claim--evidence alignment, coherence, citations, and venue fit;
review obligations can request new evidence instead of merely rewriting prose.
Generation as Content renders the same live evidence and alternatives for human
inspection and records typed interventions, but a generated view or correction
does not become reusable Taste without outcome and scope review.

# Trust and Execution Architecture

SciTaste separates four authorities. The controller chooses a research action.
An executor carries it out. A model node may propose bounded semantic content.
Deterministic validators decide whether the result can enter project state.
This architecture prevents a convenient model call from quietly gaining the
right to change a budget, choose a tool, execute a command, or promote its own
claim.

| Layer | May propose or perform | Authority it does not receive |
|---|---|---|
| Taste Controller | Select one typed research action | Shell, arbitrary tool, or evidence-admission authority |
| Model node | Produce bounded semantic content or source proposals | Action selection, budget mutation, or execution authority |
| Executor | Carry out the selected action inside its declared capability | Permission to redefine the action or accept its own evidence |
| Project runtime | Register immutable artifacts and guarded revisions | Scientific-quality judgment |
| Generated interface | Recompose verified evidence into a task-specific view | Hidden filesystem, controller, or tool access |

The native executor copies only registered, hash-bound context into an owning
run. Model-produced code remains an untrusted, telemetry-bearing proposal until
deterministic source admission succeeds; admitted code executes without network
access under time, memory, file, output, and process limits. External research
systems remain optional unchanged-core adapters and cannot replace canonical
SciTaste state. Durable provider receipts distinguish a completed response that
can be resumed from an ambiguous call that must fail closed.

Tool Intelligence uses the same negative authority. A model may rank fixed
actions, request bounded diagnostics, propose a closed tool plan, or repair a
declared schema, but deterministic code validates identity, arguments, budget,
and observations before an authorized executor acts. Its observation may
propose a Taste episode but cannot mutate state, admit evidence, or review its
own causal account. Generation as Content likewise lets a model recompose
server-issued project evidence while the receiver retains all project and tool
authority.

# Evaluation Protocol

The evaluation follows the causal chain from source representation to research
outcome. Repository tests and bounded execution receipts form an engineering
layer only: they establish that contracts run as specified, not that the chosen
scientific action is better. The confirmatory population excludes authored
fixtures and the SciTaste self-development project.

**Grounded representation and selection.** We construct natural, source-group-
disjoint decisions spanning problem choice, hypothesis refinement, experimental
design, interpretation, adaptation, review, and claims. Each case exposes a
closed action set while hiding expert preference from the model. Same-source raw
RAG versus grounded Taste isolates abstraction; matched versus source-disjoint
mismatched Taste tests contextual specificity; and deliberative versus lexical
selection uses the same hard-negative pool to test autonomous applicability.
Content-grounded versus prestige-only source qualification is supporting
evidence. Primary endpoints are condition-blinded expert preference over the
resulting action and claim calibration, with agreement, calibration, abstention,
reversal, and transfer-error diagnostics. This collection is a measurement
instrument inside the method paper; it is not called an established benchmark
before natural cases and independent labels are released.

**Outcome-attributed lifecycle learning.** Prospective sampling plans freeze
source trajectories and partitions before outcomes are reviewed. The primary
comparison fits the outcome-updated policy versus the same estimator with no
updates. Shuffled credit is the negative control; success-only and failure-only
variants diagnose whether gains reflect survivorship or failure avoidance rather
than joint delayed credit. Training and evaluation are source-group disjoint,
formal-held-out episodes never enter fitting, and each trajectory has at most one
unit of effective weight. Endpoints include held-out action preference,
calibration and abstention, boundary reversal, and performance under time-,
domain-, and model-transfer slices.

**Objective progress.** The title-level system comparison toggles the learned
policy while holding the SciTaste Native executor, model, starting state,
information, tools, repair rules, and budget fixed. It uses independently
qualified executable tasks with scorer-owned held-out data and retains every
failure. The primary endpoint is paired task-level objective progress; valid
experiment rate, unsupported claims, pivots, cost, and intervention burden are
secondary. This answers whether better local decisions change research outcomes
rather than merely sounding more persuasive.

**Ecological comparison.** A separate supporting lane compares complete
SciTaste packages with real accepted autonomous-research methods on common
full-lifecycle tasks. Agent Laboratory, AI-Researcher, and DeepScientist are
candidates only after their unchanged implementations, task mappings, models,
and budgets are disclosed and admitted. Complete-package review is blinded and
independent. Because model and architecture equivalence may be impossible, these
results are not pooled with the within-native causal estimate. Unavailable
systems remain unavailable; no surrogate implementation is substituted.

Sample sizes and repetitions are determined once from task-excluded conformance
pilots and power analysis rather than from a visually impressive cell count.
The primary backbone is selected for instruction/tool conformance and stable
identity before formal data are opened; provider and local-model robustness
runs remain non-pooled. At the time of writing, task acquisition, prospective
episodes, human review, model selection, power analysis, and execution authority
are not complete. No API or GPU formal run is reported below.

# Results: Current Evidence and Open Questions

The main evidence carriers and their interpretation boundaries are summarized
below. This table is a map to the detailed results, not an aggregation into a
single quality score.

| Carrier | Supported conclusion; excluded inference |
|---|---|
| Reviewed episode and policy fixtures | Reconstruction, dual-review admission, source-group weighting, update controls, and abstention execute; natural-data utility is untested |
| Retrospective self-project reconstruction | Exact decisions, alternatives, states, and executor outcomes can be recovered without creating reward labels; self-evidence is audit-only |
| Contract and integration suite | Control, provenance, recovery, execution, and paper paths are exercised; scientific decisions are not thereby better |
| Native Full Workflow fixture | The bounded experiment-to-paper path runs with provenance; general research yield is untested |
| RTX 3090 Qwen3-VL-2B acceptance | One registered local-model execution boundary works; model quality and cross-host portability are untested |
| Registered causal program | Representation, specificity, delayed credit, objective progress, and ecological comparison are separated; no formal result exists before execution and independent review |

## RQ1: Are the lifecycle-policy operators executable?

The implementation contains all three operators needed to test the candidate
method claim. First, project-aware reconstruction binds exact decision-log bytes
to the pre-decision state, recorded alternatives, selected action, and executor
outcome while explicitly creating no scientific label. Second, admission checks
the episode and current Idea bytes, excludes producer--reviewer conflicts,
requires two independent primary attributions, and conditionally requires a
third adjudicator. Third, a content-addressed factorized Beta estimator fits
pairwise preferences under source-group weights and split exclusions and applies
only through reason-coded uncertainty abstention. Outcome-updated, no-update,
success-only, failure-only, and shuffled-credit configurations run against the
same interface. These observations establish method availability on authored
fixtures, not correctness of reconstructed natural episodes or benefit on
held-out research.

The broader contract suite exercises model replay, research-state transitions,
project ownership, evidence routing, paper review and packaging, local-model
execution, external-adapter recovery, Tool Intelligence, Generation as Content,
native source admission, and Full Workflow composition. This software evidence
is useful for artifact reproducibility but is deliberately excluded from the
scientific-effectiveness estimate.

Separate integration receipts cover a full discovery-to-PDF fixture, a
content-bound dataset, restricted RTX 3090 inference with Qwen3-VL-2B, rejected
provider-generated code, and ICLR template compilation. They demonstrate that
the execution and publication boundaries are usable in real environments and
retain failures. We omit their synthetic task scores from the scientific result
because none tests learned Taste on natural held-out decisions.

## RQ2: Does learned lifecycle Taste improve research decisions?

This question is open. No current result compares the outcome-updated policy
with no-update or shuffled-credit controls on natural held-out episodes. No
independent reviewer set has yet established the correctness of reconstructed
alternatives, delayed credit, transfer scope, or reversals. Earlier generated
papers and one controlled integration task verify workflow completion only and
are excluded from this estimate.

## RQ3: Does decision improvement change objective research progress?

This question is also open. The native fixed-scorer path can freeze development
and held-out task surfaces, accept bounded model-authored patches, execute
scorer-owned tests without later model access, and retain failures. However, no
approved matched Full-versus-Base campaign has been run under the revised
lifecycle-policy thesis. Likewise, accepted external systems have not all passed
unchanged-core adapter and resource-equivalence review. Package quality,
objective progress, and ecological competitiveness therefore have no reported
effect size.

## Scope of the findings

The current evidence supports implementation claims only: SciTaste can preserve
exact research decisions and outcomes; compile independently reviewable learning
episodes; estimate a source-group-aware pairwise policy; abstain outside its
registered support; and compose these objects with a first-party research
executor, evidence graph, reviewer loop, paper builder, and interactive project
surface. It does not yet support that the policy learns correct scientific
judgment, generalizes, improves a research trajectory, or outperforms another
autonomous-research system. Those conclusions are reserved for the prospective,
blinded, held-out comparisons above.

# Limitations

The most important limitation is empirical completeness. Authored policy
fixtures and retrospective project traces cannot establish broad scientific
judgment. Natural episodes must be sampled before outcomes are known, their
hidden alternatives and causal credit must survive conflict-cleared independent
review, and their source groups must remain disjoint from evaluation. The matched
native objective-progress lane and accepted-system ecological lane must then run
without manual continuation. Until those studies close, any estimate of research
yield would mix framework effects with task, model, adapter, and judge effects.

Scientific taste is also difficult to operationalize. Outcome attribution can
reward luck, punish informative failures, or reproduce the incentives of a
particular field, venue, institution, or reviewer population. Source-group
weighting, explicit confounders, transfer conditions, reversal probes, and
abstention reduce obvious leakage but do not eliminate bias. The factorized
estimator also assumes a fixed feature vocabulary and does not yet learn semantic
transfer. It requires temporal, cross-domain, and cross-model evaluation against
diverse experts before broader generalization claims are credible.

The execution boundary is conservative: generated experiments have restricted
imports and run with content-bound data and explicit resource limits. The local
CUDA path is verified for one Qwen3-VL-2B environment, not across hosts or model
families; static admission is not a containment proof, and ambiguous provider
calls may remain blocked. The communication stack likewise cannot substitute
automated critique for expert novelty or correctness assessment, and a generated
project interface does not itself improve a research decision.

Self-development also risks circular confirmation. It is useful for defects and
process evidence but is excluded from headline metrics and policy training; a
successful self-run does not show that recording caused better science.

# Conclusion

SciTaste reframes scientific taste as an outcome-updated policy over
consequential actions throughout an autonomous-research trajectory. Its stable
learning unit preserves the pre-decision state, alternatives, evidence, delayed
outcomes, causal-credit review, and transfer or reversal boundary. A transparent
pairwise estimator limits source-trajectory weight and changes controller scores
only when Idea, domain, stage, support, probability, and uncertainty gates pass;
otherwise it abstains. This learned object integrates with persistent research
state, Tool Intelligence observations, Generation as Content interventions,
bounded execution, evidence, review, and paper production without granting any
producer authority to certify its own lesson.

The repository now implements the complete minimum method on authored fixtures
and can reconstruct exact project decisions without inventing rewards. Whether
the method captures scientific judgment is deliberately unresolved. Prospective
natural episodes, independent attribution, matched representation and credit
controls, held-out objective progress, and a separate ecological comparison with
accepted systems will determine whether the evidence supports escalating from
*Grounded Scientific Taste* to the result-dependent claim that SciTaste improves
autonomous research.

# AI Use Statement

Generative AI tools were used during this work for assisted literature discovery,
code generation, debugging, experiment orchestration, documentation, manuscript
drafting, and language editing. Their outputs were not accepted as evidence by
default: code and generated artifacts were checked through deterministic tests,
content hashes, source inspection, isolated execution where applicable, reruns,
and author review. Generative AI was not treated as an author or as the sole
source for scientific claims. The authors remain responsible for the manuscript,
the reported measurements, the cited sources, and any errors that remain.

# Ethics Statement

This systems work reports no human-subject experiment and makes no empirical
claim from private personal data. Autonomous research systems can nevertheless
amplify incorrect claims, unsafe generated code, licensing violations, privacy
leakage, and inherited bias in retrieved precedents. SciTaste addresses these
risks through provenance, explicit evidence scopes, fail-closed execution and
publication gates, separation of retrieved knowledge from evaluative precedent,
and human review for externally consequential actions. These controls reduce but
do not eliminate misuse or automation bias; deployment beyond the bounded
research setting requires domain-specific safety and governance review.

# Reproducibility Statement

The implementation records versioned configurations, seeds, content hashes,
model and provider identities, token and cost telemetry, stage artifacts,
interventions, and failure histories under project-owned manifests. The reported
engineering checks are backed by executable tests and self-hashed acceptance
records. The current causal evaluation is deliberately described as incomplete:
the paper specifies provider-separated, endpoint-matched prelaunch contracts and
exclusion rules so that the headline hypothesis can be assessed only after every
required cell and blinded expert judgment is available. Hardware- and provider-
specific results
remain scoped to their recorded environments rather than asserted as universally
reproducible.
