## Title
SciTaste: Improving Autonomous Research through Scientific Taste

# Abstract

Autonomous research systems can search literature, write code, execute
experiments, and draft papers, yet execution capability does not determine which
research step is worth taking. A fixed idea-to-paper pipeline can commit to a
weak problem, ignore contradictory evidence, spend its budget on an
uninformative experiment, or state a claim more strongly than its evidence
permits. We introduce **SciTaste**, a decision-centric framework that represents
autonomous research as repeated selection among typed actions under evidence and
resource constraints. SciTaste maintains persistent research state, separates
factual Knowledge from decision-precedent Taste, and uses a Taste Controller to
choose whether to probe, refine, reformulate, pivot, advance, or stop. A unified
Hypothesis--Probe--Reformulate loop governs discovery; evidence and reviewer
loops preserve support, contradiction, uncertainty, and open obligations; and
communication contracts bind claims to narrative, prose, and figures. Flexible
model outputs remain proposal-only behind deterministic schema, budget,
provenance, and execution gates. Across 1,134 unit and integration tests, a native
end-to-end fixture, content-bound local GPU inference, and one four-condition
controlled task, the implementation preserves action ownership, evidence
lineage, failure history, and publication provenance. These results establish an
evidence-grounded research-control substrate. A registered 100-trajectory
idea-to-paper prepilot separately specifies matched accepted-system comparisons
and condition-blinded expert preference over scientific value and evidence
validity. It has not been run and establishes no effectiveness result.

# Introduction

Recent autonomous research agents demonstrate that language models can
participate in broad portions of the machine-learning research lifecycle. The AI
Scientist generates ideas, implements experiments, writes manuscripts, and runs
an automated review loop \citep{lu2024aiscientist}. The AI Scientist-v2 removes
some template dependencies and uses an agentic tree-search process to manage
experiments \citep{yamada2025aiscientistv2}. Benchmarks such as MLAgentBench test
whether language agents can improve machine-learning systems through iterative
experimentation \citep{huang2024mlagentbench}, while PaperBench measures the much
harder task of reproducing complete research papers from detailed rubrics
\citep{starace2025paperbench}. Together, these systems show rapid progress in
research execution.

Execution competence, however, is not identical to research judgment. A
researcher must decide whether an observation is surprising enough to matter,
whether an apparent gain deserves another replicate, whether a contradiction
invalidates the method or reveals a better problem, and whether the current
evidence supports the paper's central claim. These decisions occur between the
visible stages of a pipeline. They determine which problem is pursued, what
budget is spent, and what evidence finally appears in the paper. A fixed stage
sequence can hide these choices inside prompts or implementation heuristics, so
that more tokens and more iterations appear to be progress even when they do not
increase scientific value.

SciTaste makes these choices explicit. It treats autonomous research as a
partially observed, resource-bounded control process. The state records the
research direction, provisional intuitions, falsifiable hypotheses, observations,
candidate ideas, experiments, claims, evidence relations, reviewer obligations,
writing state, and consumed resources. At each decision point, the controller
receives a finite set of typed research actions. It evaluates their expected
scientific value and risk, selects one action, records the alternatives and
rationale, delegates execution through a separate executor interface, and admits
the result only if its identity and evidence satisfy the transition contract.
This separation makes a research trajectory inspectable and makes nonlinear
behavior, including re-probing and pivoting, a normal property of the system
rather than an exception.

The term *taste* refers here to preferences over scientific decisions: which
failure is informative, which comparison is fair, which claim is important, and
which presentation choice makes the evidence legible. It does not mean a scalar
paper score or an unconstrained language-model opinion. SciTaste v1 is
training-free. It combines explicit decision criteria, stage-aware retrieval of
provenance-bearing decision precedents, independent critics, and deterministic
admission. Accumulated precedents change later decisions through explicit,
provenance-bearing selection rather than weight training.

The framework contributes four implementation-level ideas. First, it makes
research decisions, not task execution, the stable abstraction of an autonomous
research system. Second, it unifies idea-first and evidence-first discovery in a
Hypothesis--Probe--Reformulate loop, allowing a cheap diagnostic probe to alter
the problem before expensive development. Third, it turns evidence and reviewer
feedback into persistent graph structure that can trigger new experiments,
pivots, or writing revisions. Fourth, it applies the same taste and provenance
principles to communication and human interaction: paper sections are governed
by claim/evidence contracts, figures are planned around reader takeaways, and
generated interfaces expose only components grounded in the current project
snapshot.

The evaluation separates three questions. RQ1 asks whether the implementation
enforces action ownership, evidence provenance, bounded execution, and
publication contracts. RQ2 asks whether the four registered conditions can
complete the same controlled research task and retain comparable artifacts.
Artifact tests and the controlled task answer these integration questions. RQ3
asks whether independent experts prefer SciTaste Native's complete research
packages to those of real accepted AutoResearch systems under matched budgets;
a separate fixed-scorer lane tests objective progress. Both RQ3 lanes remain
unexecuted. Keeping these questions separate prevents engineering completion or
a model-judge rubric score from being counted as scientific-effectiveness
evidence.

![SciTaste control loop. Canonical scientific state is projected into a closed action set; the Taste Controller selects one action; bounded workers return a typed result; and deterministic admission alone may commit the next state. The diagram explains authority boundaries and is not an effectiveness result.](assets/fig1-scitaste-control.pdf)

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

Research-agent benchmarks reveal why this distinction matters. MLAgentBench
allows agents to inspect files, change code, run experiments, and iterate on a
set of machine-learning tasks; the reported success rates vary sharply by task
and expose long-horizon planning and hallucination as major challenges
\citep{huang2024mlagentbench}. PaperBench decomposes replication of twenty
research papers into thousands of author-informed rubric items and finds a large
gap between the strongest evaluated agent and expert human performance
\citep{starace2025paperbench}. These benchmarks primarily evaluate whether an
agent can accomplish a specified research or replication objective. SciTasteBench
instead targets local scientific choices, and the Phase 9 study evaluates the
downstream yield of different information and control conditions under a common
budget. The two views are complementary: execution benchmarks diagnose whether
an agent can carry out a plan, while SciTaste asks whether it selected an
appropriate plan, probe, interpretation, or claim in the first place.

Language-agent work on reasoning and reflection also motivates nonlinear
control. ReAct interleaves reasoning with external actions
\citep{yao2023react}; Reflexion uses feedback stored in episodic memory to
change later behavior \citep{shinn2023reflexion}; and Tree of Thoughts searches
over intermediate reasoning states \citep{yao2023tree}. SciTaste adopts the
general lesson that useful trajectories need not be linear, but specializes it
to scientific objects. A contradiction is attached to a claim or hypothesis,
an experiment consumes a registered resource budget, a pivot has an explicit
predecessor state, and a writing revision must close a reviewer obligation.
These domain contracts support stronger audit and evaluation than a free-form
reflection string.

Finally, retrieval-augmented generation usually retrieves topical information.
SciTaste deliberately separates a Knowledge Library from a Taste Library.
Knowledge records provide facts, methods, datasets, and prior results. Taste
records provide decision precedents such as why a pilot was informative, why a
baseline was unfair, or why a paper introduction exposed the wrong limitation.
Keeping the two stores independent allows evaluation to ask whether decision
precedents add value beyond more topical context and prevents a factual document
from being misreported as evidence of good judgment.

# Problem Formulation

Let a research state at decision step $t$ be $S_t$. It contains scientific
objects, their provenance, open obligations, and a resource ledger. The
controller receives a closed candidate set $A(S_t)$ of typed actions such as
SEARCH, FORM_WORKING_HYPOTHESIS, PROBE, REFORMULATE_HYPOTHESIS, IDEATE,
COLLECT_EVIDENCE, PIVOT, WRITE, or DROP. It selects an action

$$
a_t = \arg\max_{a \in A(S_t)} U(a \mid S_t, K_t, T_t, B_t),
$$

where $K_t$ is retrieved knowledge, $T_t$ is retrieved taste precedent, and
$B_t$ is the remaining budget. The utility is not treated as a learned oracle
in v1. It is a transparent combination of criteria appropriate to the action,
including problem validity, scientific importance, expected information gain,
claim relevance, feasibility, implementation risk, evidence tractability,
review attack surface, and venue fit. The controller logs candidate scores and
the selected rationale before execution.

Execution returns a typed result $R_t$. A transition function validates that
the result belongs to the selected action and predecessor state, that resource
usage is admissible, and that required evidence exists. Only then may the system
produce $S_{t+1}$. This yields two separate questions for every flexible model
or external system: Was its content a useful proposal? Does the deterministic
framework admit that proposal into project state? SciTaste never treats a model
response, generated program, or tool plan as transition authority by itself.

The optimization target is research yield under a fixed budget, not the number
of completed stages. A useful evaluation therefore holds the task, starting
evidence, model, and resource envelope constant and compares the quality of
decisions and final artifacts. Local metrics include expert agreement,
calibration, wrong-level decisions, and preference consistency. System metrics
include valid experiment rate, evidence completeness, unsupported-claim rate,
reviewer preference, useful pivots, time, token usage, and intervention burden.
The most important endpoint is whether independent experts prefer the resulting
research trajectory and paper under matched resources.

# Framework: SciTaste

## Persistent research state

SciTaste stores research as versioned typed state rather than relying on a chat
transcript as memory. The state includes the active direction and venue, a
resource budget, literature landscape, intuitions, working hypotheses,
observations, candidate and selected ideas, experiment history, claims, an
evidence graph, narrative and writing objects, reviewer concerns, and the full
decision history. State identifiers are content-derived, and transitions are
monotonic records: a later state can revise an interpretation or select a new
idea, but it cannot erase the evidence and decision that led to the change.

Every project lives under one ownership root with a manifest, registered runs,
papers, and navigation aliases. Mutations use file locks, optimistic revisions,
safe relative locators, and atomic replacement. This matters for both audit and
parallel development. A worker may produce evidence in a run directory, but it
cannot overwrite another run or update a stale project revision. Generated
interfaces pin the project revision and the hashes of displayed evidence, so a
view cannot silently mix old and new project states.

## Taste Controller

The Taste Controller owns action selection. It does not execute shell commands,
call arbitrary tools, or accept free-form state mutations. For each decision it
receives actions already valid for the current lifecycle position. The
controller may operate intrinsically from transparent criteria or augment the
decision with retrieved precedents. Decision logs retain the full candidate set,
feature-level scores, selected action, retrieved context identifiers, executor
result, observed outcome, and cost.

Scientific taste is decomposed by decision family. Idea taste evaluates whether
a problem is valid, important, novel, feasible, and likely to yield a clean
signal. Experiment taste emphasizes diagnosticity, matched controls, cost, and
failure interpretability. Evidence taste distinguishes support, contradiction,
uncertainty, leakage, compute mismatch, and implementation artifacts. Writing
taste evaluates claim strength, narrative function, terminology, redundancy,
and venue fit. Review and visual taste determine which concerns require new
evidence and which relationships deserve a figure. The decomposition makes a
decision criticizable: a human can disagree with one criterion without treating
the entire controller as an opaque score.

## Hypothesis--Probe--Reformulate discovery

Discovery begins with a research intuition rather than a polished idea. The
system converts the intuition into a falsifiable Working Hypothesis with
predictions and proposed probe types. A cheap probe then asks whether the
mechanism behaves as expected and records reproducibility, stability, boundary
conditions, and alternative explanations. The Taste Controller chooses whether
to validate, refine, re-probe, reformulate, pivot, drop, or advance.

This loop unifies two common research styles. When a strong initial hypothesis
is supported and the key risks are already bounded, the controller can perform
a sanity-check probe and quickly advance; the trajectory appears idea-first.
When literature or a pilot exposes an unexplained contradiction, the controller
can reformulate the hypothesis and derive a new problem before selecting an
idea; the trajectory appears evidence-first. Neither style is hard-coded as a
separate pipeline. They emerge from the evidence and expected value of the next
action.

After the hypothesis survives appropriate probes, SciTaste formulates the
explanation gap and generates a deliberately diverse idea portfolio. Generators
span representation changes, training objectives, inference-time mechanisms,
data or evaluation changes, system designs, and theory. Ideas are normalized to
a common representation and selected for complementary information value rather
than surface polish. Expensive development begins with a pilot whose failure can
still update the evidence graph.

## Evidence and reviewer loops

Claims and evidence are separate typed objects connected by explicit support or
contradiction relations. An experiment result is not copied into prose as a
conclusion. The evidence workflow checks the registered claim, expected and
observed outcomes, replicate stability, statistical uncertainty, confounders,
baseline and compute matching, leakage, implementation artifacts, and source
artifacts. The controller can then advance, refine, collect more evidence,
reformulate, pivot, or drop.

Reviewer feedback enters the same research state. Feedback is parsed into
atomic concerns and routed to research actions. A missing baseline produces an
experiment obligation; an overclaim can produce a writing revision; an unclear
mechanism can require analysis or a figure. An obligation closes only when its
required evidence is registered. The revised manuscript is therefore linked to
the action and evidence that addressed the review rather than merely containing
the sentence that a model decided to add.

## Taste-aware communication

Before drafting, SciTaste constructs a Narrative Spine containing the core
problem, overlooked failure, key observation, central insight, solution,
evidence chain, broader implication, and contribution order. The spine must pass
a taste review before writing. Sections and paragraphs then receive contracts
that specify rhetorical purpose, required claims and evidence, intended
takeaway, transitions, and word budget. Writing exemplars are retrieved by
rhetorical role rather than topic alone.

A whole-paper argument contract names the central question and bounded answer,
classifies claims, assigns their primary reader-facing evidence carriers, and
records what high-attention entry points promise. Its audit distinguishes an
unsupported claim from a supported claim whose table, proof, or audit artifact is
missing. Carrier roles are archetype-aware: formal statements and proofs suffice
for a pure-theory claim, while an explanatory architecture diagram cannot stand
in for empirical or audit evidence.

Independent critics check substance, narrative, claim--evidence alignment,
redundancy, style, terminology, citations, venue fit, and global coherence.
Figures similarly begin with a contract over the target claim, reader takeaway,
required entities and relations, panel plan, and forbidden emphasis. The figure
is reconstructed into editable SVG and draw.io artifacts and reviewed at the
object level. This design treats communication as a scientific decision problem:
the goal is not merely fluent text or attractive graphics but a faithful and
efficient mapping from evidence to reader understanding.

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

The first-party native executor supports project-owned retrieval and bounded
experiments. Retrieval copies a registered Knowledge and Taste library into the
run, records hashes, and returns source identities and scores. CPU experiment
source can be registered or produced by a bounded model node. Model-produced
source is first stored as an untrusted proposal with exact provider, model,
request, response, token, latency, and cost evidence. A deterministic AST and
import policy then decides whether a byte-identical admitted source may be
created. Only that admitted locator can enter a no-network Bubblewrap process
with time, memory, output, file, and process limits. The framework independently
parses a strict measurement envelope and derives aggregate metrics from explicit
replicates.

External agents, including the pinned AutoResearchClaw integration, use the same
executor boundary. They remain optional compatibility and baseline adapters.
SciTaste does not modify their source or allow their private state to replace the
canonical ResearchState. Provider-facing operations publish write-once
prepared, call-started, and result-published receipts. If a process crashes after
a complete response is recorded, resume can finish from that response without a
second paid call. If a call may have started but no complete result exists, the
run fails closed unless the provider offers a trustworthy idempotency or query
mechanism.

Flexible Tool Intelligence follows a similarly narrow contract. Model nodes may
rank a fixed action set, identify interpretation threats, propose an ordered plan
over closed read-only tool schemas, or suggest a repair against a declared
output schema. These objects remain advisory. A deterministic caller validates
tool names, arguments, dependencies, identity, budget, and output before any
authorized executor acts. The current narrow executor can issue one expiring,
single-use lease for a dependency-free step and invoke one registered
content-addressed read-only handler; its observation cannot mutate state or
admit itself as evidence. Generation as Content applies the same approach to
interaction: a model may select from server-issued intents and components, but
the bilingual receiver owns the shell, project access, rendering, and all
mutations.

# Evaluation Protocol

Evaluation has three levels. The first is software and evidence integrity. Unit
and integration tests exercise state transitions, project revisions, retrieval,
model-ledger recovery, source admission, sandbox output, writing projections,
paper packaging, and generated interfaces. Negative tests alter hashes, truncate
logs, introduce stale revisions, inject unsafe source, and interrupt operations
at durable boundaries. These tests establish that the implementation enforces
its contracts; they do not establish that its decisions are scientifically
better.

The second level is SciTasteBench, a fixed-candidate evaluation of local taste
decisions. Version 1 spans Idea, Experiment, Evidence, Writing, Review, and
Visual families. Each case presents a finite action set and keeps the expert
preference outside the backend request. Conditions expose the model to base
context, Knowledge retrieval, Taste precedents, independent critics, or the Full
SciTaste context. Metrics include preference accuracy, expert agreement,
confidence, Brier score, expected calibration error, wrong-level decisions,
per-family scores, temporal or domain slices, paraphrase consistency, and paired
changes relative to Base. Self-development examples are excluded from headline
scores.

The third level separates research-package preference from objective progress.
The registered API prepilot crosses SciTaste Native, a prompt-only control, and
three accepted-system candidates with ten MLR-Bench workshop-derived briefs and
two seeds (100 planned trajectories). Because these open-ended tasks have rubric
assessments rather than fixed task scores, the primary endpoint is blinded expert
preference for scientific value and evidence validity of the complete package;
a model judge is secondary. Task bytes and held-out checks, external adapters,
reviewers, and author approval remain blocked, and no trajectory has launched.

A separate lane admits only fixed-scorer tasks, such as qualified MLRC-Bench,
and is never pooled with package preference. Native Base, Knowledge, Taste,
critics, Full SciTaste, and shuffled-Taste placebo form the causal ablation. The
Qwen3-VL-2B/eight-RTX-3090 plan is robustness evidence, not a frontier-backbone
substitute.

The design emphasizes matched comparisons. Systems must not receive different
starting briefs, hidden information, tool access, model revisions, or retry
budgets. Knowledge context and Taste precedents remain isolated in the ablation
so their effects can be attributed. Failed or unavailable integrations are
reported as unavailable rather than replaced by a surrogate implementation. A
run that required manual continuation after an adapter fix can provide
engineering evidence but cannot enter duration or intervention comparisons.
Final acceptance requires every admitted cell to run from pinned commits without
manual continuation and requires blinded external review.

# Evaluation Results

The main evidence carriers and their interpretation boundaries are summarized
below. This table is a map to the detailed results, not an aggregation into a
single quality score.

| Carrier | Supported conclusion; excluded inference |
|---|---|
| Contract suite (1,134 tests; last registered combined coverage 83%) | Tested control and provenance contracts hold; scientific decisions are not thereby better |
| ICLR 2027 venue build | Implemented mechanical checks pass; acceptance, novelty, and correctness are not assessed |
| Native Full Workflow fixture (three replicates, delta 0.1) | The bounded experiment-to-paper path runs with provenance; general research yield is untested |
| RTX 3090 Qwen3-VL-2B run (4.27 GB peak) | One registered multimodal boundary executes; model quality and portability are untested |
| Four-condition single task | All conditions produce paper artifacts; causal and external-system comparisons remain unexecuted |
| 100-trajectory API prepilot contract | Systems, tasks, budgets, failure rules, and the expert-preference endpoint are explicit; no effectiveness result exists before execution and review |

## RQ1: Does SciTaste enforce its control and provenance contracts?

Across 1,134 unit and integration tests, the repository passes its complete
contract suite; the last separately registered coverage run reported 83 percent
combined statement and branch coverage. The suite
includes model backend and replay behavior, research state transitions, the six
decision families, project ownership, nonlinear discovery, evidence routing,
writing and review, figure generation, benchmark planning, local-model transport,
external-adapter recovery, Tool Intelligence, Generation as Content, native code
admission, and Full Workflow composition. Formatting and static checks pass, and
the package builds as a wheel without generated outputs, credentials, tests, or
the external submodule.

The manuscript itself now exercises a content-bound ICLR 2027 submission path.
The renderer verifies the official template archive and each admitted style
asset by hash, requires the long-form manuscript gate, checks citation closure,
anonymity, terminal disclosure order, and the AI-statement page limit, then
measures the main-text boundary from the compiled document. This draft compiles
to ten Letter-sized pages with a nine-page main-text boundary. That result is
venue-packaging evidence; it is not peer review or scientific acceptance.

The native Full Workflow has also completed a controlled offline integration
case from discovery through evidence, writing, review, figure generation, TeX,
and PDF packaging. In the provider-source variant, one scripted model-node entry
used 900 input and 1,250 output tokens, produced a 1,611-byte experiment, passed
deterministic admission, and executed three replicates inside Bubblewrap. The
measured synthetic correct-pivot delta was 0.1. This result demonstrates source
provenance, recovery, admission, isolation, measurement, and publication
plumbing. It is not an effectiveness result and is now explicitly classified as
an integration fixture rather than a reviewed research manuscript.

A second offline integration fixture exercises an explicitly registered dataset.
The workflow verifies its hash, copies it into the owning run, mounts only that
copy read-only at a derived dataset path, binds it to the native action record,
and reproduces the three-replicate measurement and complete paper package. A
separate local RTX 3090 acceptance first exposed only the admitted NVIDIA device
nodes inside Bubblewrap and verified restricted CUDA visibility. The subsequent
profile-1.1 acceptance additionally binds the complete local Python base, package,
and Qwen3-VL-2B checkpoint trees, mounts them read-only, and revalidates their
hashes after execution. Two text contracts and one synthetic-image contract all
returned their required bounded answer. Average generation latency was 0.58
seconds, peak allocated GPU memory was 4.27 GB, and child-process allocation was
7.54 GPU-seconds (0.00209 GPU-hours); complete pre/post resource verification made
end-to-end wall time 56.57 seconds. This is real execution-boundary evidence for
one local environment, not a model-quality or scientific-effectiveness result.

A real GLM-5.3-Flash engineering probe reached the provider and returned a
structured source response with measured token and latency telemetry. The
runtime rejected the response before materializing source because an auditable
price for the exact model was unavailable; independent inspection also found
invalid Python. No live code was admitted or executed. This negative result is
useful because it shows that schema validity, code validity, cost admission, and
execution authority are distinct gates.

## RQ2: Can the registered conditions complete one controlled research task?

One frozen diagnosis task has completed all four Phase 9 conditions through
experiment, analysis, manuscript packaging, and internal workflow review using a Zhipu model.
The task executes a registered 1,944-packet, three-seed factorial matrix. Across
the four conditions, the retained executions consumed 499,524 cumulative wire
tokens. The selected experiment reports method-specific failure-boundary counts
of 16 for majority vote, 0 for confidence-weighted vote, and 3 for the
position-aware probe, with a registered cross-method balanced accuracy of
0.923182.

Strict gates retained failures involving resume state, metric formats, packet
totals, statistical language, internal identifiers, and missing figures. A
replacement Full run preserved the experiment matrix, but manual continuation
excludes its duration from comparison with Base. Thus the four papers establish
workflow completion only; paper quality and the effect of Taste remain open.

## Scope of the findings

The current results support three claims. First, SciTaste is an integrated,
installable framework rather than a paper-only design: the controller, state,
libraries, loops, native executor, adapters, evaluation runner, paper builder,
and interface operate through common project contracts. Second, evidence and
failure provenance survive interruptions and corrective development; malformed
or ambiguous artifacts are retained rather than overwritten. Third, the
registered evaluation can run real models and experiments and produce auditable
papers under isolated conditions.

These observations establish implementation readiness, provenance preservation,
and completion of one controlled task. The causal effectiveness question requires
the held-out package-preference comparison, the objective-progress lane, native
ablations, and blinded expert judgments; all formal cells and external-system
adapters remain pending. The paper therefore assigns the reported measurements
to integration and failure-recovery claims, while reserving the research-yield
claim for future registered comparative evidence.

# Limitations

The most important limitation is empirical completeness. A single task and a
small synthetic decision suite cannot establish broad scientific judgment. The
MLR-Bench starting briefs must be frozen and audited as held out, real accepted-
system adapters must pass unchanged-core and resource-equivalence checks, and
every admitted trajectory must execute without manual continuation. External
reviewers must evaluate complete packages without seeing system, provider,
model, or condition labels. A separate qualified benchmark must supply the
objective-progress signal. Until then, any estimate of research-yield gain would
mix framework effects with task, model, adapter, and judge effects.

Scientific taste is also difficult to operationalize. The transparent v1
criteria improve auditability but may reflect the designers' preferences and may
not transfer across fields or venues. Retrieved Taste precedents can encode
historical bias, reward conventional work, or leak evaluation labels. The system
therefore preserves provenance and separates Taste from Knowledge, but those
mechanisms do not eliminate bias. Future learned preference models will require
held-out temporal and cross-domain evaluation plus calibration against diverse
experts.

The execution boundary is intentionally conservative. Native generated code is
limited to bounded Python experiments with a small standard-library import set.
Separate profiles admit content-bound read-only datasets and exact NVIDIA devices
under a GPU-hour ceiling. One profile also binds and executes a local Python,
package, and Qwen3-VL-2B environment on CUDA, but SciTaste does not yet construct
that environment portably or demonstrate it across hosts, checkpoints, cold
caches, multiprocessing workloads, or open-web access. Static source analysis is
defense in depth, not a containment proof, and Bubblewrap availability varies by
host. External providers may not expose reliable price, idempotency, or
response-query interfaces, which can force an ambiguous call to remain blocked.

The communication stack is not yet a fully autonomous long-form writer. The
deterministic ContractDrafter used in Full Workflow is an integration fixture,
and the main manuscript is maintained separately until a bounded long-form
generation and citation-verification path is accepted. Automated critics can
catch contract violations but cannot substitute for expert assessment of novelty,
correctness, or clarity. Similarly, generated project interfaces improve access
to evidence but do not themselves improve research decisions.

Finally, self-development evidence has a special risk of circular confirmation.
SciTaste's own implementation history is valuable for finding recovery defects
and testing project management, but it is excluded from headline metrics and is
not automatically promoted into the Taste Library. A successful self-run shows
that the framework can record its own development; it does not show that the
recording caused better science.

# Conclusion

SciTaste reframes autonomous research from a fixed sequence of generation tasks
into explicit scientific decision making under evidence and budget constraints.
Its persistent state, Taste Controller, Hypothesis--Probe--Reformulate loop,
evidence graph, reviewer obligations, communication contracts, and bounded
execution architecture make nonlinear research choices visible and testable.
Artifact validation and a four-condition single-task run establish system
readiness, complete experiment-to-paper execution, and recoverable failure
boundaries. The registered 100-trajectory package-preference prepilot specifies
one decisive external-system test of the broader hypothesis without claiming
its result. Its completion, the separate objective-progress and native-ablation
lanes, and blinded expert judgments will determine whether Taste-guided control
improves research yield under a fixed budget.

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
