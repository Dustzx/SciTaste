## Title
SciTaste: Selective Transfer of Scientific Experience in Autonomous Research

# Abstract

Autonomous research agents can search, code, experiment, and write, yet still
must decide which scientific move is worth making. We formulate **scientific
taste** as a selective policy that knows both what to prefer and when a prior
lesson should not transfer. **SciTaste** reconstructs contrastive decision
episodes from scientific precedents, endogenous trajectories, and scoped human
corrections, then transfers them through explicit applicability and reversal
conditions. **SciTasteBench** tests this idea through shared-prefix action forks
and chronological outcome learning; an unchanged external benchmark tests the
same agent with and without the Taste intervention. Development selection
reduced regret by 58.5%, but a
preregistered test on 10 disjoint task configurations reversed the result:
regret increased from 0.1387 to 0.1767. Outcome updating also failed against no
update. On 10 ResearchClawBench domains, conditional Taste packets changed the
mean score from 17.290 to 18.135, but the $+0.845$ difference was inconclusive
(95% interval $[-2.225,4.765]$, $p=0.732$): SciTaste won 3/10 tasks, and one
$+15$ result dominated the mean. Relevant high-quality content is therefore
insufficient without reliable applicability and intervention calibration. We
release the matched instruments and identify selective transfer, rather than
retrieval volume, as the central unresolved problem for scientific agents.

# Introduction

Research agents increasingly automate literature search, code generation,
experimentation, and paper writing
\citep{lu2024aiscientist,yamada2025aiscientistv2,tang2025airesearcher,
schmidgall2025agentlab}. Execution, however, does not determine which hypothesis
is discriminative, which experiment has the highest information value, when a
failure warrants repair rather than a pivot, or how strongly a result supports
a claim. These decisions determine what evidence will ever be collected.

Current systems encode such judgment implicitly in a model, search policy, or
free-form reflection. Retrieval supplies facts, reflection summarizes attempts,
and tree search allocates execution, but none directly learns which feasible
action produced better evidence from the same state. The missing supervision is
counterfactual: what if the agent had analyzed, experimented, pivoted, or
stopped instead?

SciTaste treats this judgment as selective transfer from scientific experience.
Its unit of experience is a *decision episode*: the evidence available before a
consequential choice, its feasible alternatives, the action taken, the delayed
outcome, and the conditions under which the preference should reverse. Episodes
come from scientific precedents, the agent's own trajectory, or scoped human
corrections. Retrieval only finds candidates; a grounded policy must decide
whether they transfer, rank feasible actions, and abstain when an advantage is
unsupported. Its bounded control packet is consumed by the same executor as
the no-Taste baseline.

This creates two empirical questions: whether SciTaste improves a complete
research system, and whether any gain comes from Taste rather than extra text,
model strength, or task choice. The former needs external system tasks; the
latter needs same-backbone interventions and decision-level controls. Objective
forks are therefore mechanism tests, not substitutes for system comparison.

The paper makes three contributions:

- **Scientific Taste as conditional, outcome-grounded experience.** We turn
  strong precedents, endogenous trajectories, and scoped human corrections into
  contrastive decision episodes, then transfer them only when their triggers,
  blockers, and failure conditions match the live scientific state.
- **SciTaste as a complete research framework.** The policy controls a native
  idea-to-evidence-to-paper workflow through an explicit intervention packet.
  We isolate that packet on a fixed external harness without changing its
  generator, tools, task, or budget; evaluation of the independent native
  executor remains separate.
- **A two-track mechanism benchmark and a falsifiable transfer result.**
  SciTasteBench couples shared-prefix Objective Fork Judgment with chronological
  Outcome Learning. Its first sealed policy test fails to transfer, while the
  matched ResearchHarness augmentation yields an inconclusive $+0.845$-point mean gain on
  ResearchClawBench (95% interval $[-2.225,4.765]$) while losing 7 of 10 tasks.

![SciTaste turns shared-prefix counterfactual executions into task-disjoint action-value supervision. A grounded outcome-hidden state is featurized, a development-frozen policy scores the feasible actions, and a state-bound control packet changes the next action of the native research loop. Executed outcomes enter later training populations only across a registered temporal boundary.](assets/fig1-scitaste-control.pdf)

# Related Work

## Autonomous research systems

The AI Scientist family demonstrates idea-to-paper automation
\citep{lu2024aiscientist,yamada2025aiscientistv2}; AI-Researcher and Agent
Laboratory integrate literature, experiments, and reporting
\citep{tang2025airesearcher,schmidgall2025agentlab}. CycleResearcher learns from
research--review interaction, while search-oriented agents compare Greedy,
MCTS, and evolutionary policies \citep{weng2025cycleresearcher,
toledo2025researchagents}. SciTaste instead learns over outcome-grounded
scientific decisions, not code mutations or pipeline stages.

## Research-agent evaluation

AAAR-1.0 evaluates research components; ScienceAgentBench and EXP-Bench emphasize
executable tasks and experimental integrity \citep{lou2025aaar,
chen2025scienceagentbench,kon2026expbench}. MLRC-Bench uses objective competition
metrics, whereas MLR-Bench evaluates open-ended research packages
\citep{zhang2025mlrcbench,chen2025mlrbench}. ResearchClawBench covers complete
data-to-report trajectories in ten domains with hidden-target rubrics
\citep{xu2026researchclawbench}. We preserve it as an external system endpoint,
separate from SciTasteBench's decision-regret estimand.

## Scientific judgment, retrieval, and feedback

Recent work learns paper- or proposal-level taste from citation, publication,
or future evidence \citep{tong2026scientific,gong2026institutional,
tian2026foresci}; Kkanbu represents declared preferences and Sibyl studies
outcome-conditioned behavior \citep{zhang2026kkanbu,wang2026sibyl}. ReAct and
Reflexion are reasoning-and-feedback baselines
\citep{yao2023react,shinn2023reflexion}. SciTaste instead estimates the
conditional value of an executable next action. It combines contextual decision
making \citep{li2010contextual,dudik2011doubly} with matched continuations and
delayed scientific outcomes; its sparse ridge policy keeps attribution more
inspectable than an opaque selector.

# Problem Formulation

At decision time $t$, an autonomous researcher observes state $S_t$, remaining
resource budget $B_t$, and a finite registered action menu $A_t=A(S_t)$.
Executing $a\in A_t$ under environment $E$ produces evidence and a downstream
utility $Y_t(a)\in[0,1]$. A normal trajectory reveals only one value. During
benchmark construction we instead clone the prefix and execute every action
under paired randomization, yielding a matched vector
$\mathbf{Y}_t=\{Y_t(a):a\in A_t\}$. Let $M_t$ denote source-grounded
decision episodes available at time $t$. Scientific Taste is a selective policy

$$
\pi_T(S_t,A_t,M_t)\in A_t\cup\{\mathrm{ABSTAIN}\}.
$$

The policy first tests whether any precedent in $M_t$ applies to the live state
and intervenes only when the supported advantage over the native action is
sufficient. The learned realization uses
$\arg\max_{a\in A_t}\widehat Q_\theta(S_t,a)$, with $\widehat Q_\theta$ fitted
on task-disjoint development episodes and unable to observe target outcomes.
In the diagnostic track it selects an action directly. In the complete system
it emits conditional advice consumed by a fixed executor; abstention preserves
the executor's native plan. The matched no-Taste arm receives the same state,
menu, tools, model, and budget without that advice. `STOP` is an ordinary
scientific action, not missing output or a failed run.
For evaluation, `ABSTAIN` inherits the action and utility of the frozen native
policy at that state.

The title-level estimand is downstream research progress under matched
resources, not agreement with an authored preference label. Decision regret is
a mechanism estimand,
$\max_{a\in A_t}Y_t(a)-Y_t(\pi_T(S_t,A_t,M_t))$, used to test whether the policy
chooses better research moves before asking whether those moves improve a full
research product.

# Method: Selective, Outcome-Grounded Scientific Taste

## Decision episodes from matched continuations

An episode is

$$
e_i=(S_i,A_i,a_i,O_i,C_i,P_i),
$$

where $S_i$ is the outcome-hidden state, $A_i$ the feasible alternatives,
$a_i$ the chosen action, $O_i$ the delayed scientific outcome, $C_i$ explicit
applicability and reversal conditions, and $P_i$ provenance. The three channels
are scientific precedent, endogenous trajectory experience, and scoped human
correction. Channel identity remains explicit because their authority differs.

Matched forks provide the strongest supervision: continuations share prefix,
model, tools, budget, scorer, and seed, differing first in the forced action.
Failures retain their preregistered utility. Natural records can teach a
conditional precedent, but hide unchosen outcomes.

## From high-quality content to contrastive precedents

Quality signals identify sources; they do not constitute Taste. Because papers
omit many rejected paths, SciTaste retrieves source bundles and reconstructs a
bounded contrast: choice, plausible alternative, prior evidence, outcome, and
reversal condition. Claims remain source-anchored. The compiler emits triggers,
blockers, support, failure branches, and a native fallback---never an action
just because a source is prestigious or similar.

Thus Raw/RAG exposes source bytes, generic memory exposes past outcomes, and
Taste exposes a challengeable conditional preference. Their matched comparison
is a mechanism test, not a retrieval-budget comparison.

## Grounded scientific situations

The pinned extractor $h_\phi$ maps whitelisted selector-visible fields to

$$
z=h_\phi(S)=(H,E,K,I,B,R),
$$

covering hypothesis, evidence relation, epistemic bottleneck, identifiability,
budget, and terminal readiness. Each component cites an exact state span;
missing anchors or outcome-bearing requests are rejected. Case-bound model and
prompt identities prevent representation drift from masquerading as progress.

## Outcome-calibrated action value and selective intervention

For each action, frozen features $x_i(a)=f(z_i,S_i,a)$ combine situation--action
interactions, exact-anchor words, named state quantities, and observation
summaries. Every input is traceable to the pre-decision state; branch scores,
best-action labels, and post-decision evidence are excluded. We fit

$$
\widehat\theta_\alpha=
\arg\min_\theta\sum_{i}\sum_{a\in A_i}
\left(\theta^\top x_i(a)-\bar Y_i(a)\right)^2
+\alpha\lVert\theta\rVert_2^2,
$$

where $\bar Y_i(a)$ averages registered paired outcomes. Regularization is
chosen inside each training fold; outer leave-one-task-cluster-out evaluation
holds whole clusters out. The fixed model and tuning rule are then refit on all
development clusters, hashed, and opened once on the disjoint formal population.

This estimator realizes, but does not define, Taste. Unmatched precedents yield
bounded advice and human corrections remain scoped until outcomes support them.
The intervention rule compares advantage, uncertainty, and the native prior;
insufficient support, a blocker, or an invalid action forces abstention. Useful
Taste must improve both selection and intervention calibration.

## From a policy decision to a research action

The output binds the action menu, predicted utilities, selection, state and
model hashes, and outcome-hiding declaration. SciTaste Native compiles it into a
Taste Control Packet with current evidence, applicable precedents, conditions,
uncertainty, and abstention boundary. The executor accepts only registered
actions; an unjustified override leaves the native plan unchanged.

Outcome learning is chronological: a fork enters later training only after all
branches, including failures, are sealed. The confirmatory model is frozen, so
it tests transfer; updating is evaluated separately against no-update and
shuffled-credit controls.

# The SciTaste Research System

SciTaste Native owns a complete research loop rather than wrapping another
framework. It maintains one project state across literature grounding, idea and
hypothesis formation, experiment planning, isolated execution, evidence
admission, analysis, paper construction, review, and revision. Models propose
semantic actions and code; deterministic components retain authority over
feasibility, resource limits, artifact identity, evidence admission, and state
transition. AutoResearchClaw and other systems are optional comparison adapters,
not runtime parents.

The Taste policy enters only at registered consequential decisions. Generation
as Content exposes project state and accepts user interventions, while Tool
Intelligence decides how bounded tools should be invoked. These are supporting
system planes rather than independent paper contributions. Figure 1 shows the
policy-on/off boundary and the delayed update loop. The experimental comparison
attributes a scientific effect only when an admitted packet changes an executed
high-level action.

# SciTasteBench

SciTasteBench is the internal mechanism benchmark for Scientific Taste, not the
end-to-end system leaderboard. It contains two coupled tracks: Objective Fork
Judgment measures whether a policy selects a better executable next action, and
Outcome Learning measures whether reviewed delayed credit improves later
source-disjoint decisions. Complete autonomous-research competitiveness is
tested separately on unchanged external benchmarks.

![One diagnostic case freezes an outcome-hidden research prefix, executes every feasible action under paired resources, and scores the selector only after all continuations are sealed.](assets/fig2-scitastebench-objective-fork.pdf)

## Track 1: Objective Fork Judgment

The released diagnostic design uses NewtonBench scientific-law discovery tasks
because their hidden laws provide an executable, model-independent objective.
For each task, we capture early, middle, and late research prefixes. Their menus
represent direction (`EXPERIMENT`, `PIVOT`, `PROBE`), information acquisition
(`ANALYZE`, `PROBE`, `REFINE`), and inference/termination (`EXPERIMENT`,
`REFINE`, `STOP`). Every action is executed from the same prefix with identical
tools, remaining budget, scorer, and three paired randomization blocks. The
selector never sees branch outcomes.

The development and formal splits each contain 10 source-disjoint task clusters,
30 decision states, and 270 executed continuations. Formal tasks were selected
outcome-blind from 12 registered candidates using source completeness alone.

Source completeness, not outcome, selects the 10 formal tasks: a candidate is
included only when a valid prefix can be generated for all three stages. Failed
action continuations remain in the intention-to-treat population with utility
zero. The primary endpoint is task-cluster mean paired regret reduction against
a development-frozen stage-static policy. Uncertainty uses a 50,000-resample
task-cluster bootstrap and an exact cluster sign-flip test, both frozen before
formal outcomes are opened. The same executed branches support secondary
selectors and representation ablations without spending more API or GPU budget.

## Track 2: Outcome Learning

Outcome Learning orders task-disjoint forks chronologically. After an earlier
fork is sealed, its reviewed action utilities may update the policy used on a
later fork. The primary contrast is reviewed delayed-credit update versus no
update; shuffled-credit is a negative control that preserves update volume while
breaking outcome attribution. Earlier and later source groups cannot overlap,
and later outcomes are never visible during updating or selection. This track
therefore asks whether SciTaste learns transferable judgment rather than merely
replaying a strong static selector. It is reported separately from Objective
Fork Judgment and from external end-to-end system scores.

## Split and construct validity

Task clusters, rather than prefixes, branches, candidate orders, or model calls,
define independent units and cannot cross splits. Development selects the model
family and regularization rule; the formal population estimates only the frozen
comparison. Formal cases require complete action support, replicate-level
outcomes, an unchanged scorer, action-compliance traces, and content-bound
source and runtime identities. Direction, Information, and Inference are
coverage strata, not three independent samples. This structure prevents the 90
paired blocks or 270 continuations from being reported as 90 or 270 independent
scientific tasks.

# Evaluation

The evaluation separates four estimands that are often conflated in autonomous
research: external system competitiveness, the causal contribution of Taste on
a fixed research harness, objective-fork judgment, and outcome learning. Each
research question therefore has a distinct comparison and evidence carrier.

## Research questions

- **RQ1---External systems:** Where does a SciTaste-augmented research agent
  fall among public Auto Research systems on the same unchanged tasks under
  explicitly best-native, model-confounded conditions?
- **RQ2---Causal contribution of Taste:** Under the same backbone, executor,
  state, tools, and budget, does a conditional Taste packet improve
  ResearchHarness over its unmodified base?
- **RQ3---Objective Fork Judgment:** Does an outcome-calibrated grounded state
  reduce action regret beyond a stage-static policy, and which feature groups
  carry the effect?
- **RQ4---Outcome Learning:** Does reviewed delayed credit reduce later
  source-disjoint regret relative to no update and shuffled credit?

## Systems and fairness

The matched block fixes model, task information, tools, resource limits, and
scorer; failures remain in the intention-to-treat population. Unmodified
ResearchHarness and its SciTaste-augmented arm differ only by the task-visible Taste packet and
use one fixed Qwen3.8-Max revision. One fixed multimodal Qwen3.7-Max revision
runs the unmodified official scorer. Public best-native systems are ecological
context only because their models, budgets, dates, and judges differ.

## External benchmark portfolio

The matched augmentation study uses every official ResearchClawBench `_002` task at
commit `01bc2371`, one frozen task per domain. Each arm receives the same raw
data, related work, and instructions, produces code, figures, and a report, and
is scored by the hidden-target rubric. The population and treatment were fixed
before target outcomes were available; the separately reserved downstream
validation idea was screened out and never executed.
This study uses the official ResearchHarness in both arms; it does not substitute
for a future unchanged-benchmark run of SciTaste's independent native executor.
AAAR, MLRC-Bench, and MLR-Bench remain distinct component, objective-progress,
and package endpoints rather than being pooled with this score.

## Statistical analysis

Tasks are the generalization unit. Paired randomization tests and task-cluster
bootstrap intervals compare systems; seeds estimate within-task stability but
do not increase sample size. Both the frozen diagnostic and the ten-task
ResearchClawBench comparison use a 50,000-resample task bootstrap and exact
sign-flip test over their ten task effects. The system claim additionally
requires a mean gain of at least two official-score points, an interval above
zero, and wins on at least 60% of tasks. Secondary feature and selector
contrasts form one corrected family.

# Results

We order the evidence by the questions it resolves, not by execution stage or
artifact type. The unchanged external task suite tests downstream system value;
shared-prefix forks diagnose the decision mechanism; chronological updates test
learning from delayed outcomes. Public best-native submissions use different
models and budgets and therefore remain contextual evidence rather than rows in
either controlled comparison.

## End-to-end effect on unchanged external tasks

The formal augmentation study finished all 20 executions and all 20
official-score evaluations. It compares the same Qwen3.8-Max ResearchHarness
agent with and without SciTaste's source-grounded conditional control packet on
one frozen task from each of the ten official domains. The packet contained no
default action, exposed explicit triggers and blockers, and required fallback
to the native plan when no condition applied. The SciTaste-augmented arm averaged
18.135 official-score points versus 17.290 for unmodified ResearchHarness, a
paired gain of 0.845.
It won three tasks and lost seven, failing both the registered 60% win-rate and
minimum two-point effect criteria. The 95% task-bootstrap interval was
$[-2.225,4.765]$, and the exact two-sided sign-flip $p$-value was 0.732. The
broad improvement claim is therefore not authorized.

<!-- result-carrier: matched-external-system-effect -->
**Table 1: Matched downstream effect on the 10 unchanged ResearchClawBench
tasks.** The interval and test use tasks as independent units; W/T/L is for the
SciTaste arm.

| System | Score $\uparrow$ | Paired $\Delta$ [95% CI] $\uparrow$ | W/T/L | Exact $p$ | Registered criterion |
|---|---:|---:|---:|---:|---|
| ResearchHarness | 17.290 | reference | -- | -- | -- |
| ResearchHarness + SciTaste | **18.135** | $+0.845\;[-2.225,4.765]$ | 3/0/7 | 0.732 | not met |

The mean and win count lead to different qualitative impressions because the
distribution is highly heterogeneous. The packet gained 15.0 points on
Material, 5.5 on Neuroscience, and 3.0 on Life, but lost on every other domain,
including a 7.0-point loss on Math. Thus the positive mean is dominated by one
task while the median effect is negative. This pattern agrees with the
decision-level transfer failures and does not support a universal-benefit
interpretation. Per-task scores and public best-native context remain in the
immutable result artifact; the latter is not exchangeable with this matched
study.

This comparison isolates a bounded Taste intervention on an existing harness;
it is not yet a leaderboard result for SciTaste's independent native executor.
The final complete-system comparison must run SciTaste Native and independent
Auto Research systems on an identical task population before supporting a
system-superiority claim.

## Does Taste choose better research actions?

Nested leave-one-task-cluster-out development covered 30 decisions from 10
NewtonBench clusters. It reduced mean regret from 0.0628 to 0.0260 and selected
$\alpha=100$ in every fold. That estimate selected the policy and is not a test
result. On the source-disjoint formal population, the direction reversed.

<!-- result-carrier: objective-fork-mechanism -->
**Table 2: Frozen Objective Fork Judgment result.** Regret and failures are
lower-is-better; W/T/L compares the Taste action with the stage-static action at
the same outcome-hidden state.

| Selector | Mean regret $\downarrow$ | Paired reduction [95% CI] $\uparrow$ | Failure rate $\downarrow$ | W/T/L |
|---|---:|---:|---:|---:|
| Stage-static | **0.1387** | reference | **0.2778** | -- |
| Outcome-calibrated Taste | 0.1767 | $-0.0380\;[-0.0936,0.0120]$ | 0.3111 | 2/23/5 |

All 270 continuations, including failures, were sealed before extraction. The
negative point estimate is the sole registered analysis of this population and
is not replaced by a favorable development or post-hoc contrast. An
uncertainty-gated successor made zero overrides on a new population and exactly
matched the static policy (mean regret 0.1791): abstention prevented additional
harm but did not establish better judgment.

## Does delayed outcome feedback improve later decisions?

The chronological study used five earlier source groups for updating and five
later groups for 15 source-disjoint decisions. Mean regret was 0.0334 with no
update, 0.0413 with outcome update, and 0.0427 with shuffled credit. The update
therefore failed the registered requirement to beat both controls. A later
committee-gated repair remains a development hypothesis because it was designed
after these outcomes were opened.

## Relation to public Auto Research systems

A frozen public snapshot contains 14 named systems evaluated on the same ten
task identifiers, with mean scores ranging from 15.000 to 38.256. Those entries
use different models, budgets, configurations, submission dates, and possibly
scorer revisions. We retain that snapshot as an auxiliary artifact rather than
a main-text result; mixing it into Table 1 would falsely present an unmatched
leaderboard as a controlled system comparison.

# Analysis

The failure is not explained by one uniformly weak executor. Mean paired regret
reduction was $+0.0135$ at the middle decision, $-0.0301$ early, and $-0.0975$
late. Three late losses dominate the aggregate result. In the largest failure,
the policy chose `EXPERIMENT` rather than the frozen `STOP` baseline and incurred
regret 0.6667. Two other late choices of `EXPERIMENT` lost 0.3333 and 0.0044,
while one late intervention gained 0.0297. Thus the representation sometimes
recognizes a useful continuation, but does not calibrate when the improvement
is sufficiently supported to justify overriding a strong stage prior.

The transfer behavior also differs sharply from development selection. The
formal policy selected `PIVOT` on nine of ten early states, but its single
`PROBE` selection caused a 0.3012 regression. At the middle stage it selected
the baseline `ANALYZE` eight times and `REFINE` twice, producing one substantial
win and one substantial loss. The mechanism therefore needs two properties not
provided by dense ridge weights over sparse evidence: calibrated epistemic
uncertainty and an explicit intervention rule that falls back to the baseline
when estimated advantage is not supported across task clusters. This diagnosis
is post-hoc and is not counted as a successful ablation on the sealed test.

# Limitations

Scientific action value is conditional on an executor, task distribution, and
resource envelope; an objective fork does not reveal a universally optimal
research action. The typed situation representation and exact-anchor
vocabulary may omit domain-specific facts or inherit errors from the grounded
extractor. Fixed action menus introduce construct error even when they are
outcome-hidden. Natural scientific records omit rejected alternatives, while
executable forks are expensive and cover only tasks with reproducible scorers.

System comparisons also face a fairness frontier. A shared backbone supports
causal comparison but can distort a framework designed for another model;
best-native execution preserves ecological validity but confounds system and
model effects. We report these estimands separately. AI-based construction or
review is disclosed as AI evidence and does not become human or domain-expert
validation.

Finally, self-development is useful for discovering defects and exercising the
lifecycle, but it cannot establish SciTaste's comparative effectiveness. The
paper's title-level claims require source-disjoint tasks and independent systems.
The registered diagnostic is negative. A residual, committee-gated repair is
promising on two open development replays but has no sealed confirmation, and
the conditional ResearchHarness augmentation is complete but inconclusive
($+0.845$ points, 95% interval $[-2.225,4.765]$, 3/10 task wins). The present
study also does not execute the independent SciTaste Native lifecycle on this
external benchmark or isolate structured Taste from an equal-context raw or RAG
control. Accordingly this draft establishes a framework and falsifiable
evaluation design, not evidence that SciTaste improves autonomous research.

# Conclusion

SciTaste reframes scientific taste as outcome-calibrated selection among
consequential research actions. It learns from grounded pre-decision states and
matched delayed outcomes, then applies a development-frozen value policy to
task-disjoint decisions. SciTasteBench makes this claim falsifiable: a policy
that appeared strong under nested development selection failed on its first
sealed transfer population. This result rules out the original sparse selector
as sufficient evidence for scientific Taste. The subsequent residual,
committee-gated update operationalizes the required uncertainty-aware
intervention and improves two open chronological replays, but still requires
sealed confirmation. A conditional ResearchHarness intervention raises the
mean by 0.845 points but wins only three of ten tasks and does not meet its
preregistered effect, uncertainty, or win-rate thresholds. The next method
revision must therefore improve cross-domain applicability and intervention
reliability on a newly sealed population rather than reinterpret this null
result.

# AI Use Statement

Generative AI tools were used for literature discovery, code generation,
debugging, experiment orchestration, and language editing. Model outputs were
not treated as scientific evidence by default. The authors remain responsible
for the manuscript, experiments, citations, and reported claims.

# Ethics Statement

Autonomous research systems can amplify incorrect claims, unsafe generated
code, licensing violations, and biases in scientific records. SciTaste limits
some risks through provenance, isolated execution, explicit failure accounting,
and separation of proposal from evidence admission. These mechanisms do not
remove the need for domain-specific safety review or human responsibility.

# Reproducibility Statement

The release will bind task and source versions, model and provider identities,
prompts, action semantics, seeds, budgets, raw outcomes, failed runs, tokens,
cost, and analysis code. System and diagnostic results will be emitted
from immutable manifests. The ResearchClawBench execution archive, separate
score receipts, and frozen analysis bind all 20 arms and retain null and adverse
tasks. Formal targets, development tasks, precedent sources, and
self-development records remain disjoint by task cluster.
