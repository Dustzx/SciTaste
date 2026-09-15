# Lifecycle Scientific Taste policy: formalization v1

Status: **paper-facing specification of the implemented estimator; no empirical
effect claimed**.

This document closes the mathematical gap between the current SciTaste paper
and the implementation in
[`episode_learning.py`](../../src/scitaste/taste/episode_learning.py). It defines
the exact v1 learning object, update rule, inference rule, abstention gate, causal
comparisons, and known limitations. A paper may cite these equations only for a
run whose policy configuration and source episodes are content-bound to this
implementation.

## 1. Learning object

At decision step \(t\), a persistent research state \(S_t\) exposes a finite,
typed feasible action set \(A_t=A(S_t)\). The executor and deterministic project
runtime remain outside the learned policy. The controller chooses

\[
a_t = \arg\max_{a\in A_t}
\left[U_0(a\mid S_t,K_t,B_t)+\Delta_{\pi}(a\mid S_t)\right],
\]

where \(U_0\) is the visible base-controller score, \(K_t\) is factual
knowledge, \(B_t\) is the remaining resource budget, and
\(\Delta_{\pi}\) is a bounded Taste adjustment. The policy cannot introduce an
infeasible action, mutate the budget, execute a tool, or admit its own result.

One candidate learning episode is

\[
e_i=(S_i,A_i,a_i,E_i,O_i,C_i,G_i,d_i,g_i,p_i),
\]

where \(E_i\) is pre-decision evidence, \(O_i\) contains delayed outcome
families, \(C_i\) contains action-specific causal-credit hypotheses and
confounders, \(G_i\) records transfer, failure, and reversal conditions,
\(d_i\) is the domain/stage/venue scope, \(g_i\) is a natural source-trajectory
group, and \(p_i\) is a frozen data partition. The selected action is not a
training preference until attribution review identifies a supported preferred
action \(a_i^*\), supported credit set, and confidence \(c_i\in(0,1]\).

This is a conditional pairwise policy over research actions. It is not a scalar
paper-quality score, a relevance retriever, a reward equal to executor success,
or a claim that later outcomes were caused by an earlier choice without
attribution review.

## 2. Partition and source-group admissibility

Only episodes in the configured development or calibration partitions may fit a
policy. Formal-held-out episodes are rejected before estimation. Every episode
must bind the current Idea revision and a source relationship, source group, and
partition. A source group cannot cross partitions.

Let \(I_g\) be the selected training episodes in source group \(g\). The
effective episode weight is

\[
q_i = \frac{c_i}{|I_{g_i}|}.
\]

Therefore

\[
\sum_{i\in I_g}q_i
=\frac{1}{|I_g|}\sum_{i\in I_g}c_i\le 1,
\]

so arbitrarily many decisions reconstructed from one paper, repository, review
round, or trajectory cannot create more than one effective training unit.

## 3. Pairwise observations

For each episode, the supported preferred action \(a_i^*\) is compared with
every recorded alternative \(b\in A_i\setminus\{a_i^*\}\). Its weight is split
equally across competitors:

\[
w_{ib}=\frac{q_i}{|A_i|-1}.
\]

The implemented feature map \(\phi(e_i,a)\) contains:

- action type;
- stage--action pair;
- domain--action pair;
- venue--action pair;
- action tag;
- stage--tag pair.

For feature \(f\), weighted wins and losses are

\[
W_f=\sum_i\sum_{b\ne a_i^*}
w_{ib}\,\mathbb{1}
\left[f\in\phi(e_i,a_i^*)\setminus\phi(e_i,b)\right],
\]

\[
L_f=\sum_i\sum_{b\ne a_i^*}
w_{ib}\,\mathbb{1}
\left[f\in\phi(e_i,b)\setminus\phi(e_i,a_i^*)\right].
\]

Features shared by both actions contribute neither a win nor a loss. One
pairwise comparison is counted for every preferred--competitor pair, but this
count is telemetry rather than an independent-sample count.

## 4. Posterior update

Each feature has the registered Beta prior
\(\theta_f\sim\mathrm{Beta}(\alpha_0,\beta_0)\). The fractional-count posterior
is

\[
\theta_f\mid\mathcal D
\sim\mathrm{Beta}(\alpha_f,\beta_f),\qquad
\alpha_f=\alpha_0+W_f,\quad
\beta_f=\beta_0+L_f.
\]

Define

\[
\mu_f=\frac{\alpha_f}{\alpha_f+\beta_f},\qquad
\ell_f=\log\frac{\mu_f}{1-\mu_f}.
\]

With

\[
\operatorname{Var}(\theta_f)=
\frac{\alpha_f\beta_f}
{(\alpha_f+\beta_f)^2(\alpha_f+\beta_f+1)},
\]

the implementation uses the delta-method log-odds variance

\[
v_f=\frac{\operatorname{Var}(\theta_f)}
{\mu_f^2(1-\mu_f)^2}.
\]

The v1 estimator is intentionally transparent and training-free with respect to
base-model weights. What is learned is the content-addressed posterior table,
not a new language model.

## 5. Action score and conservative uncertainty

For action \(a\) in state \(S\), let \(M(S,a)\) be supported features present
in both the state--action feature map and the learned posterior table. With
fixed, preregistered feature-kind weights \(\lambda_f\),

\[
s_{\pi}(a\mid S)=
\frac{\sum_{f\in M(S,a)}\lambda_f\ell_f}
{\sum_{f\in M(S,a)}\lambda_f}.
\]

The implementation weights action type by 1.0, stage--action and domain--action
by 2.0, venue--action by 1.5, tag by 0.5, and stage--tag by 1.0. These constants
are fixed design choices and must be ablated; they are not learned evidence.

Features produced by one episode are correlated. SciTaste therefore does not
sum their precision as if they were independent. It uses

\[
v(a\mid S)=\max_{f\in M(S,a)}v_f
\]

as a conservative action-level work variance. Effective support is the maximum
stage--action support when available, otherwise the maximum matched-feature
support.

For the two highest-scoring actions \(a_{(1)},a_{(2)}\), define

\[
m=s_{\pi}(a_{(1)}\mid S)-s_{\pi}(a_{(2)}\mid S),
\]

\[
\operatorname{SE}(m)=\sqrt{v(a_{(1)}\mid S)}+
\sqrt{v(a_{(2)}\mid S)},
\]

which is deliberately no smaller than the independent-variance expression. The
reported logistic-normal approximation is

\[
P(a_{(1)}\succ a_{(2)})\approx
\sigma\!\left(\frac{m}
{\sqrt{1+\pi\operatorname{SE}(m)^2/8}}\right),
\]

and the one-sided lower credible work margin is

\[
m_{\mathrm{low}}=m-z\operatorname{SE}(m).
\]

These are conservative decision gates, not calibrated Bayesian guarantees under
feature independence.

## 6. Exact abstention rule

The policy returns \(\Delta_{\pi}=0\) for every action if any of the following
holds:

1. current Idea identity is missing or differs from the fitted policy;
2. the configuration is the no-update control;
3. fewer than two feasible actions exist;
4. no feature is supported;
5. the domain is out of scope when cross-domain transfer is disabled;
6. either leading action has support below the frozen minimum;
7. either leading action lacks stage support when required;
8. pairwise probability is below the frozen threshold;
9. the lower credible work margin is non-positive.

When all gates pass, scores are centered over the feasible action set and scaled
so that

\[
|\Delta_{\pi}(a\mid S)|\le\Delta_{\max}.
\]

The base score, matched features, support, probability, margin, uncertainty,
adjustment, recommendation, and reason codes remain in the decision trace.

## 7. Causal controls

The fitted object alone does not establish that Scientific Taste improves a
decision. The registered controls intervene on one mechanism at a time:

- **no update:** identical prior and inference gates, no outcome observations;
- **shuffled credit:** accept a frozen upstream sample containing exactly one
  episode per independent source group, then use
  a label-independent permutation determined by a frozen seed inside each
  partition--stage--outcome/credit--effective-weight--action-menu block; this
  preserves the weighted preferred-action-type marginal while intentionally
  breaking its episode, domain, venue, and tag alignment;
- **success only:** admit only unambiguous supporting outcome credit;
- **failure only:** admit only unambiguous challenging outcome credit;
- **raw source RAG:** preserve source bytes and context budget without episode
  abstraction;
- **mismatched Taste:** preserve quality and token budget but violate frozen
  transfer scope;
- **policy off:** retain the identical native executor with every learned
  adjustment set to zero.

No-update and shuffled-credit are the primary delayed-credit controls.
Success-only and failure-only diagnose survivorship and failure-avoidance
explanations. Policy-on versus policy-off is the only title-level intervention
on objective research progress. Comparisons with external research systems are
ecological and cannot be pooled with that within-native estimate.

The earlier per-episode rotation implementation selected a non-identity label
inside each episode and did not preserve the preferred-action marginal; it is
not eligible for H3. The implemented v2 control fails closed unless every
frozen block has at least two independent source-group episodes, at least two
observed preferred action types, and exactly one candidate per action type.
The block includes supported credit family, direction, confidence, outcome
polarity, confounder-resolution stratum, and the exact effective episode weight.
It records the algorithm, block count, fixed-point count, and a canonical
donor/recipient ledger with block, source-group, original label, assigned label,
and weight. The ledger is self-hashed inside the policy. Fixed points from the
seeded random draw are retained and reported rather than optimized away.

This is a randomized training-label placebo, not a permutation p-value. H3
inference is performed on independent held-out source groups. Multiple shuffle
seeds must be frozen before outcomes are inspected and reported as a non-pooled
sensitivity analysis. The control deliberately changes contextual feature
associations; claiming that domain--action, venue--action, or tag features are
held fixed would be incorrect.

The exact one-per-group ranking rule, five frozen seeds, block variables, and
analysis rule are registered in
[`iclr2027_lifecycle_taste_h3_controls_v1.yaml`](../../configs/evaluation/programs/iclr2027_lifecycle_taste_h3_controls_v1.yaml).
The five policies are averaged within each held-out case for the shuffled
falsification contrast; they are not treated as five independent observations.

## 8. Falsifiable hypotheses

- **H1 (representation):** matched grounded episodes outperform equal-budget raw
  bytes from the same sources on held-out action quality.
- **H2 (specificity):** matched episodes outperform source-group-disjoint,
  quality- and token-matched out-of-scope episodes.
- **H2b (selection):** decision-grounded selection outperforms lexical selection
  from the identical hard-negative pool.
- **H3 (credit learning):** outcome-updated policy outperforms no-update and
  shuffled-credit policies on source-group-disjoint held-out decisions.
- **H4 (research outcome):** enabling the learned policy improves scorer-owned
  objective progress under an otherwise identical native executor and budget.

Failure of H1 rejects the claim that abstraction adds value beyond retrieval.
Failure of H2/H2b rejects contextual applicability. Failure of H3 rejects the
learned delayed-credit mechanism. Failure of H4 forbids the title-level
“Improving Autonomous Research” claim even if local preferences improve.

## 9. Algorithmic summary

```text
FIT(episodes, config):
  reject stale-Idea, missing-group, cross-partition, and formal-heldout episodes
  select episodes allowed by the registered update mode
  for shuffled credit, construct and hash the blocked label permutation
  divide attribution confidence by selected episodes in each source group
  for every preferred-versus-alternative pair:
      divide episode weight across alternatives
      add fractional wins/losses to features unique to each action
  form Beta posterior and log-odds variance for each observed feature
  persist source hashes, groups, partitions, config, posterior table, and hash

ASSESS(policy, state, feasible_actions, current_idea):
  map each feasible action to registered structured features
  compute weighted posterior log-odds and conservative work variance
  evaluate Idea, domain, stage, support, probability, and credible-margin gates
  if any gate fails: return exact reason-coded abstention and zero adjustments
  otherwise: center and clip adjustments, recommend the leading feasible action
```

Fit time is linear in the total number of preferred--alternative comparisons
times the bounded number of structured features. Assessment time is linear in
the number of feasible actions times their bounded feature count.

## 10. Claim and validity boundary

The implemented v1 policy has four important limitations that experiments must
not hide:

1. causal credit is reviewed input to the estimator, not identified by the Beta
   update itself;
2. feature extraction and feature-kind weights are hand specified;
3. the posterior factors do not model interactions beyond the registered
   structured conjunctions;
4. the uncertainty rule is a conservative operational gate, not a proof of
   calibrated uncertainty under correlated features.

AI reviewers may produce disclosed AI-supervised development episodes and
protocol vetoes. They do not become human reviewers by occupying the same role,
and an AI-only experiment cannot report human agreement or expert validity.
Natural human-written decisions and later outcomes can provide external targets
only when their construction avoids target leakage. Objective held-out scorers
remain the strongest non-human endpoint for H4.

Repository tests establish only that these equations are implemented as stated.
They do not establish H1--H4, scientific validity, benchmark admission, or ICLR
readiness.
