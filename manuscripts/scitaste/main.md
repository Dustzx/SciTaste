## Title
SciTaste: Improving Autonomous Research through Scientific Taste

# Abstract

Autonomous research agents can search, code, experiment, and write, yet these
capabilities do not determine *which* scientific move is worth making next. We
study this missing capability as **scientific taste**: a contextual preference
over consequential research decisions, learned from what was known when a
choice was made and what happened afterward. We introduce **SciTaste**, which
reconstructs scientific records into decision episodes containing the state,
feasible alternatives, delayed outcome, and boundary of a transferable lesson.
The resulting preference policy intervenes in an existing research controller
only when its precedent is supported and applicable. This formulation predicts
that a useful abstraction must do more than sound scientific: matched Taste
should outperform both raw precedent and equally polished but mismatched advice.
We test that prediction on 36 natural review-to-revision decisions with hidden
dual-model proxy labels, two candidate orders, and 288 model decisions. Base,
raw-precedent, matched-Taste, and mismatched-Taste accuracy is 58.3%, 66.7%,
61.1%, and 66.7% when the two orders are averaged. Under the stricter convention
that a case is correct only when both orders are correct, the corresponding
scores are 50.0%, 55.6%, 47.2%, and 58.3%. Matched Taste therefore trails Base
and both controls despite using 3.3 times fewer input tokens than raw precedent.
The current abstraction compresses experience but does not yet isolate when a
lesson applies. A separate eight-task execution study finds a second failure:
the learned policy abstains at every eligible decision, so its 16 trajectories
cannot estimate a Taste effect. Revising the redundant uncertainty rule makes
the policy change two of five decisions in a subsequent development trajectory
and lowers RMSLE from 12.51 to 5.60, although neither arm recovers the target
law. Together these results close an outcome-to-policy iteration while showing
that selective transfer, rather than fluent abstraction, is the unresolved
core of scientific taste.

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

The contribution is a source-to-policy account of scientific judgment and a
falsifiable test of its central mechanism. We define a supervision unit that
preserves rejected alternatives and delayed outcomes, derive a signed and
source-balanced preference estimator with explicit abstention, and connect
decision-level evaluation to objective experimental progress under a matched
intervention. The first natural pilot is deliberately diagnostic: it shows that
an apparently relevant abstraction can be compact without being discriminative.
SciTasteBench measures that distinction, while complete research trajectories
test whether an admitted preference remains useful in an ecologically realistic
system. A better paper or a more fluent rationale is not evidence for better
taste unless the decision intervention is active and the matched precedent
beats its mismatched control.

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

Let $g(i)$ be the source group of episode $i$ and let $n_g$ be the number of
admitted training episodes from that group. Episode $i$ receives weight
$w_i=q_i/n_{g(i)}$, where $q_i\in[0,1]$ is its reviewed attribution weight. Thus
one prolific paper or trajectory cannot contribute more total mass merely by
exposing more intermediate decisions. For a semantic feature $f$---for example
a stage--action pair, domain--action pair, or abstract decision-state tag---the
weighted beneficial and harmful counts are

$$
W_f=\sum_i w_i\,\mathbb{1}[f\text{ wins in }i],\qquad
L_f=\sum_i w_i\,\mathbb{1}[f\text{ loses in }i].
$$

A closed alternative set is treated as one correlated observation: a feature is
credited at most once per episode, regardless of how many losing alternatives
were enumerated. With a $\mathrm{Beta}(\alpha_0,\beta_0)$ prior, the posterior is
$\mathrm{Beta}(\alpha_f,\beta_f)$ with $\alpha_f=\alpha_0+W_f$ and
$\beta_f=\beta_0+L_f$. We use its log odds
$\ell_f=\log\frac{\alpha_f}{\beta_f}$ and delta-method variance

$$
v_f=\frac{\alpha_f\beta_f}
{(\alpha_f+\beta_f)^2(\alpha_f+\beta_f+1)}
\left[\frac{1}{p_f(1-p_f)}\right]^2,
\quad p_f=\frac{\alpha_f}{\alpha_f+\beta_f}.
$$

For action $a$, matched features $F(S,a)$ are combined with fixed semantic
weights $\omega_f$,

$$
s(a\mid S)=\frac{\sum_{f\in F(S,a)}\omega_f\ell_f}
{\sum_{f\in F(S,a)}\omega_f},\qquad
V(a\mid S)=\max_{f\in F(S,a)}v_f.
$$

The maximum in $V$ is deliberately conservative: features derived from one
episode are correlated and must not manufacture sample size. For the two
highest-scoring actions $a_1,a_2$, SciTaste computes margin
$m=s(a_1)-s(a_2)$ and uncertainty
$\sigma=\sqrt{V(a_1)}+\sqrt{V(a_2)}$. We approximate their pairwise posterior
preference as

$$
P(a_1\succ a_2\mid S)\approx
\operatorname{sigmoid}\!\left(
\frac{m}{\sqrt{1+\pi\sigma^2/8}}
\right).
$$

The deployed rule applies a centered, bounded adjustment only if both actions
meet minimum support, the stage and domain are covered, and this probability
exceeds a frozen threshold. Otherwise every adjustment is zero and the
controller exposes the failed condition. We also record the more conservative
diagnostic $m-z\sigma$. An earlier implementation required both conditions;
the source-disjoint development cohort below showed that this made the
probability threshold redundant and prevented every intervention even after the
support criterion was met. We therefore version the decision rule rather than
silently changing old policies. Abstention remains essential: a system that
always voices a preference cannot distinguish learned judgment from confident
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

The evaluation asks whether an abstracted lesson improves a held-out scientific
choice, whether an admitted preference changes an actual research trajectory,
and whether evidence from that trajectory changes the future policy. These are
separate questions. A good local choice does not guarantee downstream progress,
and a better downstream score cannot be attributed to Taste when the policy did
not intervene.

## Natural scientific decisions

We construct a development population from natural paper reviews and subsequent
author records in computing, ecology, and public health. Each item contains the
article context and review available before a revision decision; the later
response is isolated during action construction. Starting from 81 eligible
records, a model proposes two feasible responses to the review. GLM-5.3-Flash
and Qwen3.8-Max then independently judge the pair after seeing the hidden later
record. They agree on 65 pairs. A deterministic coverage rule freezes 36 of
these agreements spanning six decision contexts and six observed judgment
families. Resource-allocation decisions remain represented by only one case and
adaptive-allocation Taste is absent. These are dual-AI proxy labels, not human
expert judgments.

Every target is paired with a source-group-disjoint precedent. The raw condition
receives its abstract, decision context, and later record. The matched-Taste
condition receives only the transferable principle reconstructed from a
precedent in the same judgment family, preferentially from another domain. The
placebo receives an equally formatted principle from a different judgment
family. Base sees no precedent. This comparison asks whether abstraction adds
the missing selection signal, rather than whether additional prose can influence
a model.

DeepSeek V4.1 Flash chooses between the frozen actions under all four conditions.
We present the actions in both declared and reversed order, yielding 288
decisions. Following the closest scientific-taste preference protocol, a case is
correct only if the model selects the preferred action under both orders
\citep{tong2026scientific}. We report this order-consistent accuracy as the
primary metric, with per-order accuracy, inconsistency, and token use as
diagnostics. Raw and abstracted contexts are intentionally faithful but not
token matched; token efficiency and decision quality must therefore be
interpreted together.

## Objective research trajectories

For downstream evaluation, only the lifecycle-policy weight changes. Model,
tools, hidden task, initialization, feasible actions, and resource budget remain
fixed while an external scorer measures the final result. We retain failed arms
in the denominator and record whether the policy actually changed a selected
action. Training-free law-discovery tasks exercise sequential hypotheses and
experiments; training-based machine-learning tasks will measure progress on a
frozen hidden objective. These are two workloads for the same policy, not two
versions of SciTaste.

Complete research trajectories additionally connect idea selection,
experimentation, evidence synthesis, paper construction, review, and
review-driven revision. They evaluate ecological usefulness and cost, but they
cannot replace either the local mechanism comparison or the matched downstream
intervention.

All treatment decisions are recorded before execution. Hidden labels remain in
an isolated scorer until actions are frozen, source groups cannot cross from a
target to its precedent, and failures remain in the denominator. Development
runs may change a future algorithm version but cannot be retroactively promoted
to confirmatory evidence.

# Results

## Abstraction compresses precedent but does not yet select it

The natural pilot does not support the current matched-Taste mechanism. Averaged
over candidate order, Base selects the proxy-preferred action on 58.3% of cases.
Raw precedent and the mismatched-Taste placebo both reach 66.7%, while matched
Taste reaches 61.1%. Requiring correctness in both orders yields the more
conservative result: 50.0% for Base, 55.6% for raw precedent, 47.2% for matched
Taste, and 58.3% for the mismatched placebo. Thus matched Taste is 2.8 points
below Base, 8.3 below raw precedent, and 11.1 below the placebo. Because this is
an unbalanced 36-case development set, these differences are descriptive rather
than a confirmatory significance test.

| Information shown with the target decision | Declared | Reversed | Correct in both | Order-inconsistent cases | Input tokens |
|---|---:|---:|---:|---:|---:|
| None (Base) | 58.3 | 58.3 | 50.0 | 6 / 36 | 71,700 |
| Raw matched precedent | 63.9 | 69.4 | 55.6 | 8 / 36 | 247,470 |
| Matched abstracted Taste | 63.9 | 58.3 | 47.2 | 10 / 36 | 74,902 |
| Mismatched abstracted Taste | 66.7 | 66.7 | 58.3 | 6 / 36 | 74,820 |

The abstraction is efficient: matched Taste uses 3.3 times fewer input tokens
than raw precedent. Compression, however, is not the scientific objective. A
useful Taste representation should preserve the reason a lesson applies and
reject an equally plausible lesson outside that boundary. Here the matched and
mismatched principles are statistically indistinguishable, and the mismatched
condition is numerically better. Matched Taste is also the most order-sensitive
condition, changing its selected action in 10 of 36 cases when the candidates
are reversed, compared with 6 for Base, 8 for raw precedent, and 6 for placebo.

This negative result narrows the method hypothesis. A judgment-family match is
too coarse to establish applicability, and a fluent transferable principle can
act as generic scientific advice. The next policy version must learn a
contrastive boundary: not only what succeeded in one record, but which state
feature makes the preference reverse. Increasing the number of retrieved
principles would not address the observed failure.

## Source-disjoint research trajectories

We executed a frozen cohort of eight NewtonBench physics families that were
disjoint from the source groups used to fit the policy: Bose--Einstein
distribution, Coulomb force, gravity, Hooke's law, magnetic force, Malus' law,
Snell's law, and sound propagation. DeepSeek V4.1 Flash acted as the research
agent. For each family, the policy-on and policy-off arms shared the hidden
environment, action set, model, tools, initialization, and resource ceiling;
only the policy weight changed. Failures were retained without replacement.

The cohort executed 16 trajectories, 358 physical experiments, and 321,898
model tokens at a recorded API cost of USD 0.1313. Twelve arms reached a scored
submission and four terminated for agent noncompliance. Counting every failed
arm as score zero, policy-on solved 0/8 tasks and policy-off solved 2/8, an
intention-to-treat difference of $-0.25$. This numerical difference is *not* a
Taste-effect estimate: the policy made zero nonzero adjustments in all eight
pairs, and selected-action sequences were identical for every overlapping
decision. The two arms therefore differed only through ordinary model sampling
after an experimentally inactive treatment.

| Cohort statistic | Observed value |
|---|---:|
| Source-disjoint task pairs | 8 |
| Completed arms | 12 / 16 |
| Physical experiments | 358 |
| Taste-active pairs | 0 / 8 |
| Policy-on solved | 0 / 8 |
| Policy-off solved | 2 / 8 |
| Recorded model tokens | 321,898 |

The failure is scientifically informative because it contradicts the weaker
assumption that passing a support-count threshold is sufficient for a usable
preference policy. The fitted action posterior preferred refinement, yet the
credible pairwise margin remained negative at every state. More repetitions of
the same inactive comparison cannot resolve the question.

## Closing the outcome-to-policy loop

Inspection of the frozen decision rule revealed that it required both a
pairwise posterior probability above 0.60 and a one-sided 95% lower margin above
zero. The second condition strictly dominated the first in this regime. We
materialized a new policy version from the *same eight training episodes*: no
task outcome from the source-disjoint cohort entered its corpus. The revised
rule uses a single posterior-probability threshold of 0.75 together with the
unchanged support and scope requirements; the conservative margin remains a
reported diagnostic.

We then executed a matched follow-up on the previously used Heat task. This is
a development loop-closure case, not a new held-out result. The revised policy
made nonzero adjustments at all four nonterminal decisions and changed the
selected action on two of five turns: the policy-on trajectory chose
`REFINE--REFINE--REFINE--REFINE--STOP`, whereas the zero-weight control chose
`REFINE--PILOT--PILOT--REFINE--STOP`. Both arms ran 24 experiments and failed
exact symbolic recovery. The policy-on hypothesis nevertheless obtained RMSLE
5.60 versus 12.51 for the control, using 36,265 total model tokens and USD
0.0138 in API cost.

This follow-up establishes the functional sequence that the inactive cohort
could not: observed failure led to an explicit algorithm revision, the revised
policy altered later research decisions, and those decisions changed the final
hypothesis and continuous error. It does not establish average improvement.
The task was a previously used development task, the sample contains one pair,
and the primary metric remains tied at zero. A new source-disjoint prospective
population is still required for an effectiveness estimate.

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

The natural pilot has only 36 cases and uneven coverage. Its preferred actions
are more often in the declared first position (23 versus 13), which is why both
candidate orders are required. GLM and Qwen agreement reduces single-model noise
but does not establish construct validity. Moreover, the raw precedent contains
substantially more tokens than either abstracted condition. The study can reject
the claim that the current matched abstraction is already selective, but it
cannot determine whether the gap comes from information loss, poor applicability
matching, or the proxy labels.

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

The formulation turns an appealing but vague property into a testable learning
problem. Its success condition is demanding by design: high-quality source
content must yield a grounded preference, the representation must distinguish
where that preference applies from where it does not, and an admitted preference
must improve evidence gathered under a matched budget. Our present results do
not satisfy that condition. They show efficient abstraction without selective
transfer, an inactive first policy, and one development case in which repairing
that inactivity changes the trajectory. This is precisely the kind of evidence
an iterative research system must use to revise both its algorithm and its
paper. The remaining test is whether contrastively learned boundaries improve
held-out decisions and active objective trajectories, rather than merely making
the system's advice more persuasive.

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
and cost telemetry, and failed runs. The natural pilot retains both candidate
orders and requires an order-consistent choice for its primary accuracy. A
case-resampled interval for the order-averaged diagnostic remains available in
the machine-readable analysis but is not used as the headline metric. The
reported trajectory pair is retained with both treatment arms and its
inactive-treatment diagnosis. Human construct validity and formal effectiveness
results are not yet reported.
