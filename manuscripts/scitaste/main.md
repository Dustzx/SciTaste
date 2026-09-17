## Title
SciTaste: Improving Autonomous Research through Scientific Taste

# Abstract

Autonomous research agents can search, code, experiment, and write, yet these
capabilities do not determine *which* scientific move is worth making next. We
study this missing capability as **scientific taste**: a contextual preference
over consequential research decisions, learned from the information available
at the time of a choice and evidence observed afterward. We introduce
**SciTaste**, which reconstructs high-quality scientific records into decision
episodes containing the state, feasible alternatives, contemporaneous evidence,
delayed outcome, and boundary of a transferable lesson. Signed outcomes update
a source-balanced preference model; at inference time it perturbs an existing
research controller only when the relevant preference is sufficiently supported,
and otherwise abstains. This makes scientific taste distinct from retrieving a
similar passage, scoring a finished paper, or asking a model to reflect on its
own trace. We evaluate taste first as a held-out decision policy and then as an
intervention in objective research tasks and complete idea-to-revision
trajectories. An eight-task source-disjoint execution study exposes an important
failure mode: although the learned policy had passed its nominal support rule,
it abstained at every eligible decision. The resulting 16 trajectories and 358
experiments are valid system outcomes but not an estimate of a Taste effect.
We use that failure to revise a redundant uncertainty rule without adding the
evaluation outcomes to training. In a subsequent development trajectory the
revised policy changes two of five decisions and reduces RMSLE from 12.51 to
5.60, while both arms still fail exact symbolic recovery. These results show a
closed outcome-to-policy loop, not yet a general effectiveness claim.

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

The contribution is a source-to-policy account of scientific judgment. It
defines a supervision unit that preserves rejected alternatives and delayed
outcomes; derives a signed, source-balanced preference estimator with explicit
transfer and abstention; and connects decision-level evaluation to objective
experimental progress under a matched intervention. SciTasteBench is the
measurement instrument for the first link, while complete research trajectories
test whether the same mechanism remains useful in an ecologically realistic
system. This separation is essential: a better paper is not evidence for better
taste unless the decision intervention itself was active.

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

The evaluation follows the causal path implied by the method. At the local
level, held-out choices test whether grounded episodes outperform no precedent,
same-source raw retrieval, pointwise language-model judging, unstructured
reflection, and a mismatched-precedent placebo. Outcome-update controls replace
signed credit with no update, shuffled credit, success-only credit, or
failure-only credit. These comparisons separate learning from representation
and expose survivorship bias.

At the downstream level, only the lifecycle-policy weight changes. Model,
tools, data, initialization, action set, and resource budget remain fixed while
a hidden scorer measures the final task outcome. Training-free law-discovery
tasks exercise sequential hypothesis and experiment choices; training-based ML
tasks measure progress on a frozen hidden objective. They are workload regimes
for the same SciTaste policy, not separate versions of the system.

Complete research trajectories then connect idea selection, experimentation,
evidence synthesis, paper construction, review, and review-driven revision.
Evidence-valid completion, objective progress, paper quality, unresolved review
obligations, cost, and wall time are compared with a direct-tool-agent baseline
and reproducible external systems. This ecological study tests practical scope;
it cannot replace the matched policy intervention.

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
content must yield a grounded preference, that preference must transfer to the
right new state, and the resulting decision must improve evidence gathered under
a matched budget. Development executions currently establish the path but not
the effect. The decisive evidence is therefore held-out decision quality,
active matched-policy effects on objective tasks, and complete reviewed research
trajectories. Together they determine whether scientific taste is a genuine
capability of autonomous research rather than another name for retrieval or
reflection.

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
