## Title
SciTaste: Improving Autonomous Research through Scientific Taste

# Abstract

Autonomous research agents can search, code, experiment, and write, yet they
still need to decide which scientific move is worth making next. We formulate
this missing capability as **scientific taste**: a selective policy over
consequential research actions, learned from the state before a decision and
the evidence observed after it. We introduce **SciTaste**, an autonomous
research framework that converts source-grounded research records and executed
trajectories into decision episodes, transfers their outcome value only across
compatible scientific situations, and abstains when common action support or
uncertainty is insufficient. We evaluate SciTaste at three levels. First, the
SciTasteBench Agent track compares complete research frameworks from a common
task package to executable evidence and a final research product. Second,
unchanged community benchmarks test objective progress and complete
idea-to-paper validity outside our task definitions. Third, shared-prefix
objective forks provide causal ablations of the Taste mechanism against
same-backbone Base, equal-context retrieval, generic outcome memory, matched
and mismatched precedents, and a learned action-value baseline. **[RESULT SLOT:
insert the frozen complete-system, external-benchmark, and mechanism estimates
before making a positive effectiveness claim.]**

# Introduction

Research agents increasingly automate literature search, code generation,
experimentation, and paper writing
\citep{lu2024aiscientist,yamada2025aiscientistv2,tang2025airesearcher,
schmidgall2025agentlab}. Execution, however, does not determine which hypothesis
is discriminative, which experiment has the highest information value, when a
failure warrants repair rather than a pivot, or how strongly a result supports
a claim. These decisions determine what evidence will ever be collected.

Current systems encode such judgment implicitly in a foundation model, a
search policy, or free-form reflection. Retrieval supplies related facts;
reflection summarizes previous attempts; tree search allocates additional
execution. None of these mechanisms alone identifies why one scientific action
was preferable to its feasible alternatives, which later outcome should receive
credit, or where the preference should reverse. The same paper can support
opposite actions at different evidence states.

SciTaste treats judgment as a selective sequential decision problem. Its unit
of experience is a *decision episode* that separates the pre-decision state from
later evidence, preserves the feasible action menu and budget, assigns delayed
signed credit, and states the applicability boundary of the resulting lesson.
At run time, a typed scientific-situation representation retrieves cross-task
precedents. A common-support estimator transfers their action values only after
source-to-target action semantics have been fixed, while an uncertainty gate
abstains when the estimated preference is unsupported. The admitted decision is
compiled into a structured control packet consumed by the same executor used by
the no-Taste baseline.

This method creates two different empirical questions. The first is whether
SciTaste improves a *complete autonomous-research system* relative to real
alternative frameworks. The second is whether an observed improvement is
caused by the Taste policy rather than extra tokens, retrieved facts, a stronger
model, or a more favorable task. The former requires system-level tasks and
external benchmarks. The latter requires same-backbone interventions and
decision-level negative controls. We therefore treat objective forks as a
mechanism ablation, not as a substitute for complete-system comparison.

The paper makes three contributions:

- **Scientific Taste as an outcome-grounded policy.** We define a transferable
  research experience by its state, alternatives, delayed outcome, action
  semantics, applicability boundary, and uncertainty, rather than by a paper or
  trajectory as undifferentiated text.
- **SciTaste as a complete research framework.** The policy controls a native
  idea-to-evidence-to-paper workflow through an explicit intervention packet,
  allowing a matched policy-on/policy-off comparison without changing the
  generator, tools, task, or budget.
- **A three-level evaluation.** SciTasteBench compares complete research agents;
  community-owned benchmarks test external validity; objective forks and
  chronological feedback isolate contextual transfer, abstention, and outcome
  learning.

![SciTaste converts pre-decision scientific states and delayed outcomes into
cross-task precedents. The selective policy either emits one state-bound action
intervention for the native research loop or abstains; executed outcomes return
through a reviewed temporal boundary rather than directly rewriting the
policy.](assets/fig1-scitaste-control.pdf)

# Related Work

## Autonomous research systems

The AI Scientist family demonstrates increasingly complete idea-to-paper
automation \citep{lu2024aiscientist,yamada2025aiscientistv2}. AI-Researcher
combines literature acquisition, idea generation, implementation, and paper
composition with Scientist-Bench \citep{tang2025airesearcher}. Agent Laboratory
executes literature, experimentation, and reporting stages
\citep{schmidgall2025agentlab}. CycleResearcher couples research and review
models through iterative preference learning \citep{weng2025cycleresearcher}.
Search-oriented work instead studies how Greedy, MCTS, and evolutionary
policies navigate machine-learning solution spaces
\citep{toledo2025researchagents}. SciTaste is closest to this policy view, but
uses outcome-grounded scientific situations and selective cross-task transfer
rather than treating a code mutation operator as the learning unit.

## Research-agent evaluation

AAAR-1.0 evaluates equation inference, experiment design, and paper weakness
identification \citep{lou2025aaar}. ScienceAgentBench provides 102 executable
tasks from four scientific disciplines, while EXP-Bench focuses on experiment
integrity \citep{chen2025scienceagentbench,kon2026expbench}. MLRC-Bench uses
objective metrics on seven machine-learning research competitions, whereas
MLR-Bench evaluates 201 open-ended tasks across idea, proposal, experimentation,
and paper writing and explicitly audits invalid results
\citep{zhang2025mlrcbench,chen2025mlrbench}. These resources motivate our
external evaluation; they are not renamed as SciTasteBench tasks.

## Scientific judgment, retrieval, and feedback

Recent work learns paper- or proposal-level scientific taste from citation,
publication, or future evidence \citep{tong2026scientific,gong2026institutional,
tian2026foresci}. Kkanbu represents declared research preferences, while Sibyl
studies how experimental outcomes alter later behavior
\citep{zhang2026kkanbu,wang2026sibyl}. ReAct and Reflexion provide direct
reasoning-and-feedback baselines \citep{yao2023react,shinn2023reflexion}.
SciTaste targets a complementary object: the conditional value of an executable
next action under the current evidence state, including when a precedent should
not transfer.

# Problem Formulation

At decision time $t$, an autonomous researcher observes state $S_t$, remaining
resource budget $B_t$, and a finite feasible action set $A_t=A(S_t)$. Executing
action $a\in A_t$ under research environment $E$ produces delayed evidence and
terminal utility $Y$. A base controller supplies action scores $U_0(a\mid S_t)$.
SciTaste learns an auxiliary selective policy $\pi_T$ from earlier source-task
episodes and either recommends one action or abstains:

$$
a_t = \arg\max_{a\in A_t}
\left[U_0(a\mid S_t)+\lambda\Delta_T(a\mid S_t)\right],
$$

where $\lambda=0$ is the same-backbone Native Base and $\lambda=1$ enables the
Taste intervention. Model, task state, tools, and resource limits are identical
between these conditions. Policy abstention sets every $\Delta_T$ to zero and
is distinct from selecting a scientific `STOP` action.

The title-level estimand is downstream research progress under matched
resources, not agreement with an authored preference label. Decision regret is
a mechanism estimand used to explain that system effect.

# Method: Outcome-Grounded Scientific Taste

## Decision episodes and temporal supervision

An episode is

$$
e_i=(S_i,A_i,M_i,O_i,C_i,G_i,P_i),
$$

where $S_i$ is the outcome-hidden state, $A_i$ the feasible actions, $M_i$ their
executable semantics, $O_i$ later evidence, $C_i$ signed credit with declared
confounders, $G_i$ transfer and reversal conditions, and $P_i$ provenance and
temporal order. Human records provide ecologically realistic states but rarely
identify the utility of rejected alternatives. Executable forks provide
objective action utilities by replaying every action from the same prefix.
These sources retain separate authority: plausible reconstruction never becomes
objective supervision merely because it is fluent.

## Grounded scientific situations

The extractor $h$ maps selector-visible state to

$$
z=h(S)=(H,E,K,I,B,R),
$$

covering hypothesis structure, evidence relation, epistemic bottleneck,
identifiability, budget pressure, and terminal readiness. Every component cites
an exact span in the visible state; target outcomes are unavailable to $h$.
This representation is intentionally compact and falsifiable. It must beat raw
semantic retrieval and learned value baselines to justify its use.

## Semantic action alignment and common support

Actions with the same label can mean different things across tasks. Before any
source utility is exposed, an outcome-hidden mapper binds every target action to
one source action definition. A source is eligible only when this map is
complete, sufficiently confident, and covers the same target action set.
SciTaste compares all target actions using the same eligible source population;
missing or failed source branches receive their registered intention-to-treat
value.

Let $C(z)$ be the cross-task source cases satisfying these contracts and
$m_i(a)$ the mapped source action. For categorical situation kernel $k$ and
source utility $u_i$, cases from the same source task are first collapsed. The
estimated action value is

$$
\widehat V(a\mid z)=
\frac{\sum_g w_g(z)\,\overline{u}_{g,a}}
     {\sum_g w_g(z)},\qquad
w_g(z)=\max_{i\in g} k(z_i,z)^2.
$$

Replicate-level branch variance and between-task variation estimate uncertainty
in the paired best-minus-runner-up contrast. The policy intervenes only if the
state abstraction, source similarity, effective task support, practical margin,
and contrast precision all pass thresholds frozen on development data.
Otherwise it abstains.

## Typed intervention and outcome learning

An admitted estimate is compiled into a Taste Control Packet containing the
frozen action menu, cited current-state facts, selected precedents, explicit
source-to-target mappings, per-action support and opposition, and either one
recommended action or a zero-effect abstention. This packet is the only Taste
treatment accepted by the native executor and evaluation adapters; retrieved
prose without a state-bound action adjustment is not Full SciTaste.

Learning proceeds chronologically. Reviewed outcomes may add, remove, or change
credit on source episodes only after the relevant action and outcome are
closed. The updated memory is evaluated on later source-task-disjoint states.
A learning effect requires the correct update to outperform both no update and
shuffled credit, and requires a trace from changed policy state to changed
executed action and outcome.

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
system planes rather than independent paper contributions. The experimental
comparison attributes a scientific effect only when a Taste packet changes an
executed high-level action.

**[FIGURE SLOT: replace the current generic framework figure with a compact
native-loop diagram showing episode construction, selective policy,
intervention, execution, delayed credit, and the policy-on/off boundary.]**

# SciTasteBench

SciTasteBench is a full-system research-agent benchmark with a diagnostic
instrument, not a collection of SciTaste-only ablations.

## Agent track: complete autonomous research

Each task package freezes a research brief, starting code and data, allowed
tools, hidden evaluation interface, resource envelope, required artifacts, and
failure policy. A framework operates through its native loop from the common
starting package to executable evidence and a final research product. The
primary endpoint is scorer-owned research progress; evidence validity,
completion, invalid-result rate, wall time, tokens, GPU/API cost, and final
package quality are reported separately.

The primary comparison contains SciTaste Native, a direct ReAct-style agent,
and at least two independent published research systems whose unchanged-core
implementations pass task, model, sandbox, artifact, and telemetry equivalence.
AutoResearchClaw is retained as a real sensitivity system. AI Scientist-v2 or
Sibyl appears only if its actual implementation is runnable; no unavailable
system receives a proxy implementation or synthetic score.

## Diagnostic track: shared-prefix objective forks

At consequential points within task trajectories, the evaluator freezes the
state and a menu of two to five stable scientific actions. Every action is
executed from the same prefix with identical tools, remaining budget, scorer,
and paired randomization blocks. The evaluated selector sees no branch outcomes.
The primary diagnostic loss is objective action regret,
$u(a^*)-u(\hat a)$.

This track supplies the controlled ablations: Base, equal-context Raw/RAG,
stage/status kNN, generic outcome memory, a learned action-value predictor,
Matched Taste, and Mismatched Taste. Chronological cases additionally compare
correct update, no update, and shuffled credit. Because branch execution is
shared across selectors, these controls do not multiply the expensive research
work.

## Split and construct validity

Task clusters, rather than prefixes, branches, candidate orders, or model calls,
define independent units and cannot cross splits. Development estimates action
identifiability, task-cluster variance, and the smallest relevant effect before
the validation and hidden populations are frozen. Formal cases require complete
action support, replicate-level outcomes, an unchanged scorer, action-compliance
traces, source licenses or reconstructable locators, and outcome-hidden
construct review. Direction, Information, and Inference are coverage strata;
they are reported only where the task and action menu genuinely instantiate the
corresponding scientific decision.

# Evaluation

The evaluation separates four estimands that are often conflated in autonomous
research: complete-system competitiveness, external validity, the causal
contribution of Taste under a matched executor, and the behavior of the Taste
mechanism itself. Each research question therefore has a distinct comparison
and evidence carrier.

## Research questions

- **RQ1---Complete systems:** Does SciTaste outperform independent Auto Research
  frameworks on SciTasteBench-Agent under matched or explicitly best-native
  resource conditions?
- **RQ2---External validity:** Does SciTaste improve objective progress and
  evidence-valid research products on unchanged accepted benchmarks?
- **RQ3---Causal contribution of Taste:** Under the same backbone, executor,
  state, tools, and budget, does Full SciTaste outperform Native Base and
  equal-context Raw/RAG?
- **RQ4---Mechanism and learning:** Do matched precedents reduce action regret,
  do mismatched precedents fail, is abstention calibrated, and does correct
  delayed credit beat no update and shuffled credit?

## Systems and fairness

The matched block fixes the model revision, task information, tools, resource
limits, recovery policy, and scorer. It supports causal framework comparisons
only for systems that natively accept that envelope. A separate best-native
block uses each framework's recommended configuration and is reported as
ecological but model-confounded. Failed, timed-out, and invalid runs remain in
the intention-to-treat population.

The planned complete-system rows are Direct/ReAct, MLR-Agent, Agent Laboratory,
SciTaste Native, and qualified additional systems. AutoResearchClaw is a
sensitivity row. MLAB and MLR-Agent remain the official comparator rows on
their native MLRC-Bench and MLR-Bench evaluations.

## External benchmark portfolio

AAAR-1.0 provides a component check but cannot establish end-to-end research.
The primary objective endpoint uses the six untouched MLRC-Bench tasks; the
already consumed development task appears only in a seven-task descriptive
sensitivity analysis. MLR-Bench evaluates the complete idea-to-paper product on
a frozen source-disjoint subset with invalid-result accounting. The broad
cross-domain title is retained only if unchanged ScienceAgentBench tasks can be
run with the official execution assets; otherwise claims narrow to ML research
agents.

## Statistical analysis

Tasks are the generalization unit. Paired randomization tests and task-cluster
bootstrap intervals compare systems; seeds estimate within-task stability but
do not increase sample size. Development data freeze the smallest effect of
interest and required hidden population. Score--cost curves, invalid-run rates,
and intervention-to-action mediation accompany endpoint means. Multiple
mechanism contrasts are corrected as one registered family. Practical ties
remain in risk--coverage analysis rather than being converted into winners.

# Results

This manuscript reserves result locations without treating development runs as
evidence. Every table will be generated from a frozen result manifest; `--`
means not yet executed, not zero.

## Complete-system comparison on SciTasteBench-Agent

| Framework | Objective progress | Valid experiments | Valid final product | Cost | Failure rate |
|---|---:|---:|---:|---:|---:|
| Direct/ReAct | -- | -- | -- | -- | -- |
| Published system A | -- | -- | -- | -- | -- |
| Published system B | -- | -- | -- | -- | -- |
| AutoResearchClaw (sensitivity) | -- | -- | -- | -- | -- |
| SciTaste Native | -- | -- | -- | -- | -- |

**[RESULT SLOT RQ1: paired task-level effect, uncertainty, success/failure
counts, score--cost curve, and matched versus best-native interpretation.]**

## External objective progress and research-product validity

| Evaluation | Systems | Primary endpoint | Formal status |
|---|---|---|---|
| AAAR-1.0 | Full, Native Base, Raw/RAG | official component metrics | pending |
| MLRC-Bench, six untouched tasks | Full, Native Base, Raw/RAG, MLAB | normalized objective progress per cost | pending |
| MLR-Bench frozen subset | Full, Native Base, generic memory, MLR-Agent | evidence-valid final-package quality | pending |
| ScienceAgentBench | Full, Native Base, official baseline | executable success and cost | asset-blocked |

**[RESULT SLOT RQ2: external scores, task-cluster intervals, invalid runs,
resource use, and any scope narrowing forced by unavailable official assets.]**

## Causal effect and decision-level ablations

| Condition | Downstream task outcome | Action regret | Intervention coverage | Cost |
|---|---:|---:|---:|---:|
| Native Base | -- | -- | -- | -- |
| Equal-context Raw/RAG | -- | -- | -- | -- |
| Generic outcome memory | -- | -- | -- | -- |
| Learned action-value baseline | -- | -- | -- | -- |
| Mismatched Taste | -- | -- | -- | -- |
| Full / Matched Taste | -- | -- | -- | -- |

**[RESULT SLOT RQ3: Full--Base and Full--Raw matched effects plus the trace from
admitted packet to changed action and later score. RESULT SLOT RQ4: regret,
Matched--Mismatched specificity, abstention risk--coverage, action-order and
paraphrase invariance.]**

## Outcome learning

| Policy state | Later source-disjoint regret | Action-change rate | Downstream outcome |
|---|---:|---:|---:|
| No update | -- | -- | -- |
| Shuffled credit | -- | -- | -- |
| Reviewed delayed-credit update | -- | -- | -- |

**[RESULT SLOT: chronological learning curve and a concrete episode showing
outcome attribution, policy update, changed action, and changed evidence.]**

# Analysis

The final analysis will separate at least five explanations: better action
selection, higher abstention precision, generic context benefit, executor
compliance, and additional cost. Failure slices will cover decision axis,
domain shift, task budget, action-map confidence, abstention reason, and invalid
experiment type. A qualitative case study will show one beneficial transfer,
one harmful or mismatched transfer, and one correct abstention without exposing
hidden test content.

**[ANALYSIS SLOT: replace this paragraph with result-grounded findings and
examples after formal manifests close.]**

# Limitations

Scientific action value is conditional on an executor, task distribution, and
resource envelope; an objective fork does not reveal a universally optimal
research action. The six-dimensional situation representation is deliberately
small and may omit domain-specific facts. Action menus and semantic mappings
introduce construct error even when they are outcome-hidden. Natural scientific
records omit rejected alternatives, while executable forks are expensive and
cover only tasks with reproducible scorers.

System comparisons also face a fairness frontier. A shared backbone supports
causal comparison but can distort a framework designed for another model;
best-native execution preserves ecological validity but confounds system and
model effects. We report these estimands separately. AI-based construction or
review is disclosed as AI evidence and does not become human or domain-expert
validation.

Finally, self-development is useful for discovering defects and exercising the
lifecycle, but it cannot establish SciTaste's comparative effectiveness. The
paper's title-level claims require source-disjoint tasks and independent systems.

# Conclusion

SciTaste reframes scientific taste as a selective policy over consequential
research actions. It learns from pre-decision states and delayed outcomes,
aligns action semantics across tasks, and intervenes only when cross-task
support and uncertainty justify a preference. The evaluation deliberately
separates complete-system competitiveness, external validity, the causal effect
of Taste, and decision-level mechanism diagnostics. **[CONCLUSION RESULT SLOT:
insert only the strongest claims supported jointly by the frozen system,
external, and ablation results; narrow the title if cross-domain evidence is
absent.]**

# AI Use Statement

Generative AI tools were used for literature discovery, code generation,
debugging, experiment orchestration, and language editing. Model outputs were
not treated as scientific evidence by default. The authors remain responsible
for the manuscript, experiments, citations, and reported claims.

# Ethics Statement

Autonomous research systems can amplify incorrect claims, unsafe generated
code, licensing violations, and biases in scientific records. SciTaste limits
some risks through provenance, uncertainty-aware abstention, isolated execution,
and separation of proposal from evidence admission. These mechanisms do not
remove the need for domain-specific safety review or human responsibility.

# Reproducibility Statement

The release will bind task and source versions, model and provider identities,
prompts, action semantics, seeds, budgets, raw outcomes, failed runs, tokens,
cost, and analysis code. Complete-system and diagnostic results will be emitted
from immutable manifests. Formal targets, development tasks, precedent sources,
and self-development records remain disjoint by task cluster.
