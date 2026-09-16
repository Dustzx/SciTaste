# SciTasteBench four-layer protocol v1

Status: **current benchmark-design authority; execution remains separately
resource-bound**.

The machine-readable contract is
[`iclr2027_scitastebench_four_layer_v1.yaml`](../../configs/evaluation/programs/iclr2027_scitastebench_four_layer_v1.yaml).
It narrows SciTasteBench to the evidence needed for the SciTaste method paper.
It does not turn the paper into a standalone benchmark submission and does not
replace external objective AutoResearch tasks.

## Scientific object

Scientific Taste is evaluated as a causal chain:

```text
source quality
  -> grounded precedent abstraction
  -> context-sensitive scientific decision
  -> reviewed delayed-credit update
  -> objective research progress
  -> reviewed and revised research package
```

The benchmark therefore has four layers. **SA** tests source qualification and
abstraction against the same raw source bytes. **D** tests source-disjoint
scientific decisions. **L** tests delayed-outcome policy updating. **P** bridges
the mechanism to complete training-free and training-based projects scored by
external objective tasks. SA, D, and L explain *why* Taste works; P establishes
whether it improves research. No score is pooled across layers.

## Decision population and Taste ontology

Headline cases cover exactly six research-process **context families**:

1. problem and Idea value;
2. hypothesis refinement and falsifiability;
3. experiment design and confound control;
4. evidence interpretation and contradiction handling;
5. resource allocation, pivot, continue, or stop;
6. claim calibration and reviewer-concern closure.

Visual presentation and interface use remain product-supporting studies. They
may reveal useful failure modes but cannot replace a scientific-decision family.
One source group contributes at most one headline case. Target cases, precedent
sources, development cases, formal cases, and self-development evidence remain
group-disjoint in every role where leakage would answer the task.

Context is not the same as the judgment exercised. Every case is independently
assigned to the existing seven-family Scientific Taste ontology:
scientific-value, epistemic-discrimination, empirical-diagnosticity,
adaptive-allocation, inferential-discipline, transfer-and-correction, and
scientific-communication. The ontology is content-bound by
`834f70d9e745f582023685702772239a873feb184dc715f99904d7f52f44fe83`.
Results are stratified by both axes. For example, an experiment-design context
may primarily exercise adaptive allocation rather than empirical diagnosticity.
Conflating lifecycle stage with the underlying judgment would hide exactly the
cross-stage transfer that SciTaste claims to learn.

## Primary estimands

The paper reports five separate endpoints:

- **Abstraction Value Gain:** matched grounded Taste minus equal-token raw RAG
  from the same source bytes.
- **Transfer Specificity Gap:** matched Taste minus quality- and token-matched
  source-disjoint Taste outside its applicability scope.
- **Budgeted Decision Regret:** the registered optimal action utility minus the
  selected action utility, including objective value, information gain,
  resource cost, and invalid-claim risk.
- **Delayed-Credit Learning Gain:** outcome-updated policy minus no-update, with
  shuffled credit as the causal negative control.
- **Objective Research Progress per Budget:** SciTaste Native minus the same
  Native executor with the Taste policy disabled, under matched model, tools,
  task, token, API, wall-time, and compute budgets.

Pairwise accuracy, calibration, wrong-level decisions, and AI-panel preference
remain diagnostics. They are not relabelled as objective scientific progress.

## Behavioral attribution

Every P-layer result must retain the chain from policy state to action,
execution, and hidden outcome. A final score difference is not attributed to
Scientific Taste when the registered intervention produced no eligible action
change. The analysis reports both the intent-to-run effect and the mediated
effect among behavior-changing states without using the latter to discard
failures or abstentions.

This rule prevents a loaded but inactive memory or policy from being counted as
a treatment. It also distinguishes a genuine Taste effect from executor noise,
provider drift, or an unrelated repair.

## Development and formal releases

The first executable development release contains 36 natural cases: six per
decision-context family, coverage of all seven Taste judgment families, at
least three domains, and one headline case per source group.
Two identity-distinct AI reviewers label each outcome-blind case and a third
identity adjudicates only disagreement. These labels are an AI-panel proxy,
never human or expert validity. This release estimates failure rates, variance,
order sensitivity, and resource needs while exercising the complete SA--D--L
pipeline. It cannot support the title claim.

The formal floor remains 120 source-group-independent cases before a
development-informed power revision. The protocol, model identities, treatment
bytes, AI-panel identities, utility rubric, and analysis are frozen before the
hidden split opens. Strong-title admission additionally requires a positive,
complete P-layer objective contrast in both the registered workload coverage
and the paper's exact claim contract.

The existing 24-target Track-A pilot is not silently promoted: it covers only
four legacy families and includes Visual cases, so it cannot satisfy this
development release. Its sources and results remain consumed development
evidence.

## Full-process evaluation

P uses external task authority rather than SciTaste-authored answers:

- the T0 route executes training-free research with a hidden objective endpoint;
- the T1 route executes real task-model training through MLRC-Bench;
- MLR-Bench supplies stagewise and complete-package quality evidence;
- EXP-Bench supplies experiment-integrity diagnostics.

The primary causal comparison is SciTaste Native versus Native Base. Direct
agents and admitted external AutoResearch systems form a separately reported
ecological comparison. Self-development demonstrates usability, provenance,
defect discovery, and review-driven revision, but never enters the headline
effect estimate.

## Deadline rule

The two-day closure target is a complete 36-case development path plus one real
P-layer development pair, not a claim that formal evidence exists. Once those
runs reveal actual variance and failure rates, scale only the comparisons that
contribute to the five registered endpoints. B0 is complete and is not repeated.
