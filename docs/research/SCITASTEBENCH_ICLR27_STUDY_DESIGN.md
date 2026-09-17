# SciTasteBench and external validation: ICLR 2027 study design

Status: current scientific design; formal data have not been opened.  The revised
content-conditioned selector also failed its consumed-case development gate, so a
new confirmation population is not yet frozen.

SciTasteBench is the mechanism instrument for the SciTaste method paper. It is
not intended to make SciTasteBench itself the entire contribution, and it cannot
establish end-to-end autonomous-research utility by itself.

![SciTasteBench study design](../figures/scitastebench-study-design.svg)

## The three questions the paper must answer

1. Can high-quality research records be converted into compact, source-grounded
   decision principles with explicit applicability and reversal boundaries?
2. Do those principles improve a new scientific decision because they apply to
   its current evidence state, rather than because they add tokens or generic
   advice?
3. When a Taste-induced choice is executed, does it improve an externally scored
   research outcome under the same budget?

SciTasteBench answers the first two questions and tests feedback learning. Public
Auto Research tasks answer the third. A positive result in either evaluation is
insufficient without the other.

## Paper type and evidence boundary

The target submission is a **method paper with a new diagnostic instrument**, not
a benchmark paper with a small method attached.  SciTaste is the method;
SciTasteBench makes its otherwise vague central construct measurable.  This gives
the paper two coupled contributions without allowing either to validate itself:

- SciTasteBench tests whether the proposed mechanism learns grounded principles,
  transfers them only when their boundaries fit, abstains otherwise, and improves
  after delayed outcome credit;
- scorer-owned public tasks test whether those changed choices produce better
  autonomous-research outcomes outside the benchmark authors' definitions.

This division follows the strongest recent evaluation pattern.  Accepted
benchmark papers use broad, independently scored task populations: MLE-bench has
[75 competition environments](https://proceedings.iclr.cc/paper_files/paper/2025/hash/7e3767db483c942b883eb4f8cfb74e31-Abstract-Conference.html),
while EXP-Bench has
[461 experiment tasks from 51 papers](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c411f5b2d9c55f1685e72db224ad8b0e-Abstract-Conference.html).
Research-agent evaluations instead use a smaller number of expensive environments
with objective progress, time/compute curves, and retained failures, as in
[RE-Bench](https://proceedings.mlr.press/v267/wijk25a.html).  A 120-case internal
decision study alone therefore cannot justify an end-to-end Auto Research claim.

## What one SciTasteBench case contains

Each case is one natural, outcome-hidden research fork:

- the pre-decision scientific state;
- two or more feasible actions at the same level of abstraction;
- the visible budget and constraints;
- a scoring-only later record, isolated from the evaluated system;
- a panel distribution over actions and an explicit abstention judgment;
- one source-group identity that controls all train/development/test placement.

The six contexts are problem value, hypothesis falsifiability, experiment and
confounds, evidence interpretation, resource/pivot/stopping, and claim/review
response. The formal floor is 120 cases, 20 per context, across at least three
domains, after a separate 36-case development set. One source group contributes
at most one formal case.

The action menu must be diagnostic. A population in which almost every item asks
the system to “perform more analysis” cannot distinguish scientific taste from a
generic caution prior and is rejected before formal evaluation.

The floor of 120 is a coverage constraint rather than a claim that 120 is
automatically powered.  The final case count is revised once, using only the
development-set paired-regret variance and the smallest effect worth detecting.
Candidate-order repetitions are repeated measurements of the same case; they do
not inflate the independent sample count.

## Construction and release contract

The benchmark is incomplete until all of the following objects exist for every
formal case:

1. a source-licensed, de-duplicated decision episode and source-group identity;
2. an outcome-hidden state and feasible action set at a common abstraction level;
3. an isolated later-outcome record and a registered utility vector;
4. applicability and reversal boundaries that cite source spans;
5. a counterfactual twin that changes one decisive fact and should change either
   the chosen action or the correct abstention;
6. independent judgments with raw disagreements retained, not only an adjudicated
   label; and
7. a contamination probe, split assignment, and immutable content hash.

Formal targets, precedent sources, development cases, counterfactual twins, and
self-development records are split by source group.  Exact source text is released
only when its license permits it; otherwise the release must contain reproducible
source locators and a deterministic reconstruction recipe.  An AI-reviewed set is
reported as AI-reviewed and cannot be called expert- or human-labelled.

## The causal comparisons

All decision conditions use the same generator model, action menu, visible state,
and context budget.

| Condition | What is added | What it rules out |
|---|---|---|
| Base | nothing | standalone model ability |
| Equal-token raw | source evidence bytes | benefit from more factual context |
| Matched Taste | a grounded principle whose boundaries fit the target state | value of decision abstraction and transfer |
| Mismatched Taste | an equally strong principle outside its applicability boundary | generic “good research” advice and context priming |

The primary decision signature is not accuracy alone. It requires all of:

- lower decision regret for Matched than Base and equal-token raw;
- a positive Matched-minus-Mismatched specificity gap;
- calibrated abstention when no precedent satisfies its boundaries;
- a correct action flip on counterfactual twins that change a decisive boundary
  fact while preserving topic and wording style;
- invariance to action presentation order.

The earlier family-plus-hash matcher failed the independent 28-case reserve:
Matched underperformed Mismatched. That is retained as a falsification of the old
selector. The revised selector must first pass on consumed development cases and
then be evaluated once on a newly frozen, source-disjoint split.

## Learning from outcomes

Feedback learning compares no update, reviewed delayed-credit update, and
shuffled-credit update on later source-disjoint decisions. A credible learning
result requires the reviewed update to beat both controls. It must also retain a
trace from the changed policy state to a changed eligible action, executed work,
and the later outcome. More memory or different prose without an action change is
not credited as learning.

## External Auto Research evaluation

At least one external objective benchmark is mandatory. The minimum defensible
ICLR portfolio uses two complementary external endpoints:

| Evaluation | Endpoint | Primary comparison | Role |
|---|---|---|---|
| MLRC-Bench | objective task improvement and progress per GPU/API budget | Full SciTaste vs same-backbone Native Base | whether Taste improves executable research |
| MLR-Bench official briefs | blinded evidence-aware preference over the complete research package | Full, Native Base, direct agent, runnable external system | whether the whole idea-to-paper product is better |

EXP-Bench is a valuable experiment-integrity analysis, but the locally acquired
package currently contains task metadata rather than the upstream runtime assets
and scorer. It enters the headline only if an unchanged official runnable subset
is qualified in time; it must not be imitated with a SciTaste-authored scorer.

MLRC-Bench is the immediate objective route because its competition score directly
measures improvement over a supplied baseline under a compute limit.  Its own
study reports only [9.3% of the baseline-to-top-human gap closed by the strongest
tested agent](https://arxiv.org/abs/2504.09702), which makes it both difficult and
diagnostic.  MLR-Bench complements rather than replaces this result: package
quality and review cannot prove that the proposed method improved a hidden task
score.

The external-system comparison and the internal causal comparison have different
purposes. Full versus Native Base, under the same backbone and budget, attributes
an effect to Taste. Agent Laboratory, MLR-Agent, or another accepted runnable
system establishes competitiveness. A best-native external comparison is useful
but model-confounded and is labelled accordingly.

Consequently the smallest defensible external comparison contains three roles,
not a large Cartesian grid: Full SciTaste, same-model Native Base, and one real
runnable external method.  Repetitions are added only when the development pair
shows stochastic variance large enough to change the conclusion.  Benchmark
adapters may translate files and telemetry, but may not reimplement a blocked
method or substitute a new scorer.

## Evidence buffer

Engineering runs, parser fixes, consumed development splits, and adapter smoke
tests remain in the evidence ledger.  They may change the method and disclose a
failure, but their effect sizes cannot enter the main result table.  A result
moves into the manuscript only after the exact method, split, model, budget,
scorer, failure policy, and analysis are frozen before outcomes are opened.  A
method revision after seeing a split consumes that split.

This buffer is why the current negative 28-case result is useful without becoming
the paper's headline: it falsifies family-plus-hash matching and forces a
content-conditioned selector, while reserving a new population for the first
valid estimate of that revised selector.

## What belongs in the manuscript

Development runs guide the method and remain in the evidence ledger. They do not
fill the main result table. The paper should contain:

- this design figure and a benchmark datasheet summary;
- one main SciTasteBench mechanism table with uncertainty and negative controls;
- one external objective-progress table;
- one complete-package comparison with cost and failure accounting;
- ablations for raw versus abstracted reference, matched versus mismatched
  transfer, no-update versus shuffled credit, and Native Base versus Full;
- failure slices by decision context, domain shift, abstention, and budget.

There is deliberately no omnibus “SciTaste score.” Local mechanism validity,
feedback learning, external objective progress, package quality, and resource use
are separate estimands. Pooling them would make a favorable result impossible to
interpret.
