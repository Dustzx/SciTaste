## Title
SciTaste: Improving Autonomous Research through Scientific Taste

# Abstract

Autonomous research systems increasingly know *how* to search, code, experiment,
and write, but still lack a persistent account of *which* scientific move is
worth making next. We study this missing capability as **scientific taste**: a
contextual preference over consequential research decisions, learned from what
was known when a decision was made and what happened afterward. We introduce
**SciTaste**, an autonomous-research system that reconstructs high-quality
scientific records into grounded decision episodes. Each episode preserves the
decision state, feasible alternatives, supporting evidence, delayed outcome,
and conditions under which the lesson should transfer or reverse. An
outcome-updated policy aggregates these episodes across source groups and
changes a base research controller only when its support and uncertainty gates
permit; otherwise it abstains. This representation separates scientific taste
from topical retrieval, final-paper scoring, and free-form self-reflection.
SciTaste integrates the policy into one persistent loop from problem selection
through experiments, evidence synthesis, paper construction, review, and
revision. We introduce SciTasteBench to evaluate held-out decision quality and
pair it with objective research tasks that measure whether better decisions
translate into better experimental outcomes. A completed live development pair
already exposes a useful failure mode: both matched arms executed 24
experiments, but the learned policy abstained at all five decision points and
both obtained zero task score. This null result validates the execution and
measurement path while rejecting an effectiveness claim for the current policy.
The resulting method makes scientific judgment an explicit, learnable, and
falsifiable component of autonomous research.

# Introduction

Recent research agents can generate ideas, modify code, run experiments, and
draft papers. The AI Scientist established an integrated idea-to-paper workflow,
and its successor searches a larger space of experimental trajectories
\citep{lu2024aiscientist,yamada2025aiscientistv2}. MLAgentBench and PaperBench
measure progress in iterative machine-learning experimentation and paper
replication \citep{huang2024mlagentbench,starace2025paperbench}. These systems
make a compelling case that much of the *execution* of research can be
automated.

Research is not only execution. Before running an experiment, a scientist must
decide whether the question is important, whether an observation is diagnostic,
whether an apparent gain deserves another replicate, whether a failure calls
for repair or a change of hypothesis, and whether the accumulated evidence is
strong enough to support a claim. Such choices determine what evidence is ever
collected. A flawless implementation of a weak experiment is still weak
science, and a longer trace of tool calls is not necessarily progress.

Most autonomous-research systems leave these decisions implicit in prompts or
in the state of a general-purpose language model. Retrieval supplies relevant
facts, reflection summarizes previous attempts, and a final judge scores an
idea or paper. None of these operations by itself identifies the transferable
lesson in a successful research choice. Published work usually shows the path
that survived, but hides the alternatives that were rejected, the information
available at the time, and the later evidence that should receive causal credit.
As a result, simply retrieving high-quality papers risks copying conclusions
rather than learning judgment.

SciTaste starts from a different unit of learning: the *decision episode*. An
episode asks what the researcher knew, what alternatives were feasible, which
action was selected, what evidence arrived afterward, and under what conditions
the same preference should transfer or reverse. This unit supports three
operations that raw retrieval cannot provide. It makes competing actions
explicit, links delayed outcomes to earlier choices, and exposes uncertainty
about whether a precedent applies to the current state.

The resulting policy is deliberately bounded. It does not replace the research
agent or train a new foundation model. Instead, it adjusts the ranking of an
already feasible action set. Evidence from one trajectory contributes at most
one source-group unit, harmful outcomes can decrease rather than increase a
preference, and an uncertain or out-of-scope policy abstains. This design makes
the intervention observable: the same research system can be run with and
without the learned adjustment while holding the model, tools, data, and budget
fixed.

Our central hypothesis is that outcome-grounded scientific taste improves both
local decision quality and downstream research progress. We evaluate the two
parts separately. SciTasteBench tests whether a system chooses well among
held-out scientific alternatives, transfers a lesson to the right context,
reverses it at a boundary, and knows when to abstain. Objective research tasks
then test whether the same policy changes experiments and improves scorer-owned
outcomes. A complete-system study measures the full path from idea to a
reviewed-and-revised paper; it is complementary to, not a substitute for, the
causal policy comparison.

This paper makes three contributions:

1. We formulate scientific taste as an outcome-updated policy over
   consequential decisions across a research lifecycle, rather than as a
   paper-level score or retrieved passage.
2. We develop a source-to-policy method that reconstructs alternatives and
   delayed outcomes, abstracts transferable lessons, assigns signed credit, and
   applies them through an uncertainty-aware controller.
3. We introduce an evaluation that connects held-out decision quality to
   objective experimental progress and complete idea-to-paper performance under
   matched resources.

The current live evidence is intentionally diagnostic. A matched training-free
development pair completed the experiment and hidden-scoring path, but the
policy abstained at every exposed decision and neither arm solved the task. The
result demonstrates a working causal interface while showing that an inactive
treatment cannot support the headline claim. We retain this failure because it
clarifies the empirical burden of scientific taste: recording precedents is not
enough; the learned preference must actually change a defensible decision and
survive objective evaluation.

![SciTaste turns scientific records and endogenous research outcomes into grounded decision episodes. The learned policy changes a feasible action ranking only when the precedent matches the current state and its uncertainty is sufficiently small. Execution, evidence admission, and review remain separate from the learned preference.](assets/fig1-scitaste-control.pdf)

# Related Work

## Autonomous research systems

The AI Scientist and AI Scientist-v2 demonstrate increasingly complete
idea-to-paper workflows \citep{lu2024aiscientist,yamada2025aiscientistv2}.
MLAgentBench evaluates agents that improve machine-learning systems, while
PaperBench evaluates paper replication \citep{huang2024mlagentbench,starace2025paperbench}.
SciTaste is compatible with such execution substrates but targets a different
abstraction: the policy that chooses among scientifically meaningful next
actions. This distinction matters experimentally. End-to-end quality can improve
because of a stronger model, better tools, more compute, or better judgment;
matched policy-on/policy-off runs isolate the last factor.

Reasoning-and-acting methods such as ReAct, Reflexion, and Tree of Thoughts
interleave thought, action, search, and feedback
\citep{yao2023react,shinn2023reflexion,yao2023tree}. Their traces can contain
useful experience, but a trace is not yet a scientific supervision unit.
SciTaste reconstructs the state and alternatives before the outcome, then asks
which part of the later outcome should change a future choice.

## Scientific judgment and taste

Recent work makes scientific taste an explicit learning target. Tong et al.
learn paper-impact signals from citations and community feedback, and Gong et
al. learn field-specific pitch evaluators from publication outcomes
\citep{tong2026scientific,gong2026institutional}. ForeSci evaluates temporally
grounded forward-looking judgments and shows that retrieving relevant evidence
does not guarantee a good decision \citep{tian2026foresci}. These works motivate
learning judgment while also exposing the limits of paper-level or socially
derived labels.

Kkanbu represents a user's declared taste as a structured object that can steer
a research loop, while Sibyl turns experimental outcomes and recurring failures
into later behavioral changes \citep{zhang2026kkanbu,wang2026sibyl}. SciTaste
builds on the shared premise that preferences and outcomes should affect future
research. Its focus is the joint problem of reconstructing heterogeneous
scientific decisions, assigning delayed signed credit, transferring the lesson
across contexts, and abstaining when transfer is unsupported.

## Retrieval, reflection, and outcome learning

Knowledge retrieval answers *what is known*. Scientific taste answers *which
move is appropriate now*. The distinction motivates separate stores. A
Knowledge Library contains claims, methods, data, and prior results; a Taste
Library contains reviewed decision episodes. Retrieval may efficiently propose
relevant precedents, but it does not decide that a precedent transfers. Raw
source retrieval is therefore a direct baseline for SciTaste: both conditions
see the same source content, while only SciTaste receives the reconstructed
decision, outcome, and boundary.

# Scientific Taste as Sequential Decision Making

Let $S_t$ denote the research state before decision $t$. It contains the active
question, hypotheses, observations, candidate explanations, evidence, open
review obligations, and remaining budget. The system exposes a finite feasible
set $A(S_t)$ and a base utility $U_0(a\mid S_t)$ supplied by the research
controller. SciTaste adds a bounded preference term,

$$
a_t = \arg\max_{a\in A(S_t)}
\left[U_0(a\mid S_t) + \lambda\,\Delta_\pi(a\mid S_t)\right],
$$

where $\lambda=0$ yields the matched native baseline and $\lambda=1$ enables
the learned policy. The action set, model, tools, observations, and budget are
unchanged between the two conditions. If the current state lies outside the
policy's supported scope, $\Delta_\pi(a\mid S_t)=0$ for every action.

The desired supervision cannot be represented by a final scalar reward alone.
We use an episode

$$
e_i=(S_i,A_i,a_i,E_i,O_i,C_i,G_i),
$$

where $E_i$ is the evidence available for the choice, $O_i$ is the later
outcome, $C_i$ assigns signed credit while naming confounders, and $G_i$
specifies transfer and reversal conditions. The target is not to imitate
$a_i$. It is to infer when the preference for $a_i$ over its alternatives is
supported by the outcome and applicable to a new state.

This formulation separates four quantities that are often conflated:

- source quality: whether the underlying record is trustworthy and informative;
- decision grounding: whether the state, alternatives, and evidence can be
  reconstructed without using future information;
- outcome attribution: whether later evidence supports beneficial or harmful
  credit for the earlier choice;
- contextual transfer: whether the credited lesson applies to the present
  decision rather than merely sharing vocabulary.

A useful scientific-taste method must improve decisions because of these
quantities, not because it sees more source text or an outcome label unavailable
to the baseline.

# Method

## From high-quality content to decision episodes

SciTaste begins with source admission, not retrieval ranking. Candidate sources
include research trajectories, paper revisions, reviewer exchanges, benchmark
solutions, and the system's own completed runs. Admission considers provenance,
scientific quality, temporal order, and whether the record contains enough
information to reconstruct a decision. Prestige and publication venue may be
recorded for analysis but are not used as the supervision label.

For an admitted source, the process miner identifies a consequential choice and
projects only information available before that choice. It then reconstructs a
closed set of plausible alternatives. An episode is rejected when the
alternatives are artificial, when the chosen action was forced, or when the
projection leaks the later outcome. These checks are important because a model
can otherwise produce a convincing but circular explanation of why the observed
path was best.

The episode stores both concrete and abstract views. The concrete view preserves
the exact state, action, and evidence for audit and reversal. The abstract view
expresses the transferable principle—for example, prefer an intervention that
separates two live explanations over another broad measurement—without retaining
task-specific names as the lesson itself. Retrieval uses the abstract view to
form a candidate pool, then rechecks each candidate against the concrete state.

## Delayed, signed outcome attribution

Scientific outcomes arrive at different horizons. An experiment may immediately
reveal a contradiction; an idea may be judged only after several experiments;
a writing choice may matter after review. SciTaste preserves these horizons
instead of collapsing executor success, task score, reviewer response, and
publication outcome into one reward.

Attribution asks a counterfactual question: under the same pre-decision state and
budget, would a feasible alternative plausibly have produced a better scientific
outcome? The answer may assign beneficial credit, harmful credit, or no usable
credit. Informative failures are not automatically harmful, and successful tool
execution is not automatically beneficial. Confounders and later decisions are
retained so that a terminal score is not indiscriminately copied onto every turn.

The current protocol uses two identity-distinct AI reviewers to assess the same
frozen episode; substantive disagreement invokes a third adjudicator. This is
scalable AI supervision, not expert ground truth. Deterministic checks enforce
source identity, temporal order, split isolation, and agreement with the frozen
packet. The review can reject an attribution but cannot rewrite the underlying
trajectory.

## Outcome-updated preference model

For each admitted episode, the selected action is compared with every meaningful
alternative. Beneficial credit records wins for features of the selected action;
harmful credit records losses. Features describe the decision family, lifecycle
stage, action type, domain, venue, state regime, and abstract tags. Run-local
identifiers remain provenance and are never treated as transferable features.

We estimate Beta posteriors over pairwise feature preferences. Source-group
weighting prevents many correlated decisions from one paper or trajectory from
dominating the policy. The score of an action is a fixed combination of matched
posterior log odds. Because those features are correlated, uncertainty is
bounded by the most conservative matched posterior rather than treating every
feature as an independent observation.

The policy changes the controller only when both candidates have sufficient
support, the relevant lifecycle stage is represented, the Idea and domain match,
the pairwise probability crosses its threshold, and a conservative credible
margin is positive. Otherwise it abstains and exposes the failed gate. This
behavior is central rather than defensive boilerplate: a scientific-taste system
that always expresses a preference cannot distinguish judgment from confident
language generation.

## One lifecycle, multiple decision families

The same mechanism applies to different scientific choices without pretending
that they share identical criteria. Problem selection emphasizes validity,
importance, and tractability. Experiment selection emphasizes diagnosticity,
confounding, and cost. Interpretation emphasizes evidence coverage and
alternative explanations. Adaptation emphasizes expected improvement under the
remaining budget. Communication emphasizes claim calibration and reader value.

SciTaste maintains a persistent state across these choices. Experiments update
evidence; evidence changes claims; reviewer feedback creates obligations; and a
revision may route back to analysis or experimentation. A model may propose an
action or artifact, but only the controller chooses among feasible actions and
only the project runtime admits measured evidence. Tool Intelligence supplies
bounded process observations, while Generation as Content exposes the same
state and allows a user to inspect or redirect decisions. They support the
lifecycle policy rather than constituting separate scientific contributions.

# Evaluation

Our evaluation asks four questions.

**Decision quality.** Does a grounded Taste episode improve held-out action
selection over no precedent, same-source raw retrieval, and an unstructured
reflection? Does it outperform a deliberately mismatched precedent while
abstaining when none applies?

**Learning from outcomes.** Does reviewed delayed credit improve future
decisions beyond a static episode library? We compare outcome-updated credit
with no update, shuffled credit, success-only updates, and failure-only updates.
This isolates learning from representation and diagnoses survivorship bias.

**Objective research progress.** When only the lifecycle-policy weight changes,
does SciTaste improve a scorer-owned task outcome under the same model, tools,
data, initialization, and resource budget? Training-free law-discovery tasks
exercise sequential hypothesis and experiment choices. Training-based ML tasks
measure whether those choices improve a frozen hidden objective. These are two
workload types for one SciTaste system, not different product variants.

**Complete-system performance.** Can SciTaste carry a research problem through
idea selection, experimentation, evidence synthesis, paper generation,
independent review, and review-driven revision? We compare evidence-valid
completion, objective progress, paper quality, unresolved reviewer obligations,
cost, and wall time against a direct-tool-agent baseline and reproducible
unchanged external systems. This ecological study measures practical capability;
it does not by itself identify the effect of Taste.

## SciTasteBench

SciTasteBench is a collection of source-group-disjoint decision episodes drawn
from natural research and review records. Each case exposes a pre-decision state,
a closed alternative set, provenance-bearing evidence, and a hidden outcome and
attribution. The benchmark samples problem choice, hypothesis refinement,
experiment design, interpretation, adaptation, review response, and claim
calibration. Splits are made by source group so that multiple decisions from one
paper or project cannot cross the train/evaluation boundary.

Primary metrics are closed-set decision accuracy or blinded preference,
calibration, selective risk under abstention, contextual transfer error, and
boundary-reversal accuracy. Results are clustered by source group. AI-panel
labels and natural outcomes are reported separately; neither is presented as
human-expert construct validity.

## Baselines and controls

The mechanism study uses four strong controls: no precedent, raw source
retrieval, pointwise language-model judging, and unstructured reflection. A
mismatched-Taste placebo tests whether any polished precedent helps. Credit
ablations test whether outcome updating matters. The downstream study compares
the full learned policy with the identical native system at zero policy weight.
Complete-system experiments add direct-tool-agent and reproducible accepted
AutoResearch systems, with matched-model and native-best settings reported
separately.

## Experimental discipline

All treatment decisions are recorded before execution. Hidden labels remain in
an isolated scorer until a candidate is frozen. Failures remain in the
denominator, and formal runs receive no manual repair. API tokens, monetary cost,
GPU time, wall time, storage, and retry counts are measured for every arm.
Development runs may reveal interface defects but cannot authorize a formal
effect claim.

# Results

## Development evidence

The present artifact contains one completed live matched development pair on a
training-free NewtonBench task. Both arms used DeepSeek V4.1 Flash as the
research agent, executed five decision turns, and completed 24 experiments. The
combined recorded API cost was USD 0.0131. The learned-policy arm abstained at
all five decisions, so its controller scores and chosen actions were identical
to the no-policy behavior. Both trajectories received a symbolic task score of
zero.

| Condition | Decisions with nonzero Taste adjustment | Experiments | Task score |
|---|---:|---:|---:|
| Learned policy on | 0 / 5 | 24 | 0 |
| Learned policy off | 0 / 5 | 24 | 0 |

This result closes the execution, telemetry, and hidden-scoring path, but it is
not evidence that Taste helps or hurts. The manipulation check failed: the
nominal treatment never became active. Treating the zero difference as a causal
estimate would therefore confuse a software condition label with a behavioral
intervention.

## What the null run teaches us

The policy had accumulated support for adaptive-allocation decisions, but its
posterior top-action margin still crossed zero in the target state. This is a
scientifically useful diagnosis. Simply adding more retrieved episodes or
lowering the uncertainty threshold would manufacture activity without
establishing that the preference is reliable. The next evaluation must acquire
independent, naturally varying decisions whose outcomes sharpen the relevant
comparison, then rerun the same manipulation check without changing the frozen
formal threshold.

The run also changes the order of work. It is unnecessary to repeat route
qualification or add a wider decorative grid. The immediate empirical program
is: complete the natural SciTasteBench decision set, estimate the decision-level
effect against raw retrieval and pointwise judging, and then execute the matched
objective pair once the policy is behaviorally active. Complete-system
experiments can proceed in parallel because they answer a different question
and do not require a positive policy effect to exercise the lifecycle.

## Claims not yet supported

No current result shows that SciTaste improves held-out scientific decisions,
objective research progress, or idea-to-paper quality. No human-expert study
validates the scientific-taste construct. The title states the target claim;
retaining it as an empirical conclusion requires the planned held-out decision
and objective-progress results. If those results remain absent or null, the
appropriate scientific conclusion is a grounded method with an unresolved or
negative effectiveness result, not a success claim inferred from system
complexity.

# Limitations

Outcome attribution is intrinsically difficult. Later success may reflect luck,
a stronger executor, or decisions made after the episode under review.
Conversely, a failed experiment may be highly informative. Independent review,
counterfactual alternatives, explicit confounders, and signed credit make these
assumptions inspectable but do not eliminate error.

The current estimator uses a fixed semantic feature vocabulary. It can combine
evidence across source groups but does not learn an unrestricted representation
of scientific similarity. This favors transparency and abstention at the cost
of weaker transfer. Cross-domain, temporal, and cross-model evaluation is
required before claiming general scientific judgment.

SciTasteBench depends on reconstructed decisions. Natural records often omit
rejected alternatives and intermediate uncertainty, while AI-assisted
reconstruction can introduce plausible but false counterfactuals. The benchmark
must therefore disclose source coverage, reconstruction confidence, reviewer
agreement, and contamination risk. AI-panel labels are scalable proxies, not a
replacement for expert validation.

End-to-end comparisons introduce model, tool, compute, and implementation
confounds. We separate matched-model from native-best comparisons and preserve
unavailable systems rather than imitating them, but ecological results will
still be specific to the tasks and resource envelope studied.

Finally, self-development creates circularity. Using SciTaste to improve its own
implementation is valuable for discovering failure modes and testing the
lifecycle, but those traces cannot establish external generalization or serve as
their own headline evaluation.

# Conclusion

SciTaste treats scientific taste as a learnable policy over the decisions that
shape a research trajectory. Its key move is to convert high-quality content
and endogenous outcomes into grounded episodes that retain the state,
alternatives, evidence, delayed result, signed credit, and boundary of a
scientific choice. A source-group-aware posterior then modifies a fixed
controller only when the lesson is supported and applicable.

This formulation turns an appealing but vague property of researchers into an
intervention that can fail. The first live matched run did fail its manipulation
check: the policy abstained throughout and neither arm solved the task. That
failure rules out a premature improvement claim while confirming that the
necessary causal interface and objective measurement path execute. The decisive
next evidence is not another software test or a larger configuration matrix; it
is held-out decision quality, active matched-policy effects on objective tasks,
and complete reviewed research trajectories. Those experiments determine
whether scientific taste becomes a genuine capability of autonomous research
rather than another name for retrieval or reflection.

# AI Use Statement

Generative AI tools were used for literature discovery, code generation,
debugging, experiment orchestration, and language editing. Model outputs were
not treated as scientific evidence by default. The authors remain responsible
for the manuscript, experiments, citations, and reported claims.

# Ethics Statement

Autonomous research systems can amplify incorrect claims, unsafe generated
code, licensing violations, and biases present in scientific records. SciTaste
reduces some risks through provenance, explicit uncertainty, bounded execution,
and separation of proposal from evidence admission. These mechanisms do not
remove the need for domain-specific safety review or human responsibility.

# Reproducibility Statement

The implementation records configuration and source hashes, seeds, model and
provider identities, action alternatives, decision traces, raw outcomes, token
and cost telemetry, and failed runs. The reported development pair is retained
with both treatment arms and its inactive-treatment diagnosis. Formal
effectiveness results are not yet reported.
