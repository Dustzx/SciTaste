# ICLR 2027 experiment matrix v1

Status: **corrected experiment-structure authority (2026-09-24)**. This
document separates independent-method comparison, causal attribution,
ablation, and diagnosis. The earlier version incorrectly treated SciTasteBench
as an internal-only instrument while naming it as a benchmark contribution:
it lacked other methods on the benchmark itself. Rows from different layers
may orient the reader but their estimates must not be pooled.

## The four evidence layers

| Layer | Scientific question | Systems or conditions | Primary carrier | Current status |
|---|---|---|---|---|
| A1. SciTasteBench decision-method comparison | Does SciTaste choose better next actions than *independently implemented* direct, reflection, and planning/search policies? | Real decision policies on identical outcome-hidden fork cases; no renamed SciTaste controls or one-shot imitations of complete frameworks | SciTasteBench representative and discriminative populations, separately | **Missing.** Existing Native, Raw/RAG, and memory rows are internal controls; no eligible independent-method result exists. |
| A2. Whole-agent method comparison | How competitive is SciTaste Native against real Auto Research systems on common complete tasks? | SciTaste Native and pinned runnable public systems, with matched-resource and best-native settings kept distinct | Unchanged external benchmark now; future agent-compatible SciTasteBench tasks only after interface and scorer validation | ResearchClawBench has an ecological point for a SciTaste-augmented ResearchHarness, **not** SciTaste Native. SciTasteBench has no whole-agent task mode. |
| B. Matched causal Taste effect | Does Scientific Taste improve an otherwise identical research agent? | ResearchHarness + SciTaste packet versus unmodified ResearchHarness | ResearchClawBench formal V7, 10 paired domains, same Qwen3.8-Max agent, Qwen3.7-Max scorer, tools, task bytes, seed, and ceilings | Complete formal null: 18.135 versus 17.290, paired `+0.845`, 95% interval `[-2.225, 4.765]`, 3/10 wins. This is an augmentation study, not a SciTaste Native system comparison. |
| C. Mechanism ablations | Which representation or policy component could cause an effect? | Raw/RAG, generic memory, matched Taste, mismatched Taste, no applicability gate, no abstention gate | SciTasteBench SA/D/L populations with identical target states and visible-token budgets | Partly complete, currently negative. These are ablations and negative controls, not independent Auto Research methods. |
| D. Diagnostics and robustness | Where, when, and for which models does the mechanism work or fail? | decision stage, domain, ambiguity, leverage, intervention rate, model family, budget, failure mode | task-level effects, selective-risk curves, progress--budget frontier, chronological learning curves | Partly complete. Existing formal results show adverse within-cohort decisions and an unequal development/test time ceiling; they do not isolate transfer or calibration as the cause. Model-family and new-population robustness remain missing. |

The recursive self-development project is a separate **case study**, not another
leaderboard layer. It establishes lifecycle completeness, defect discovery, and
artifact provenance. Because SciTaste is both developer and subject, it cannot
establish comparative effectiveness.

## What belongs in each paper result

### Required SciTasteBench decision-method result (not yet run)

Compare task-compatible direct, reflection, and planning/search policies with
SciTaste on the same source-disjoint, outcome-hidden fork cases. Bind each
policy's implementation, inputs, model, inference budget, development access,
and failure behavior before test opening. Report task-level regret, tie-aware
accuracy, failures, and cost. Native Base is a reference policy; Raw/RAG and
generic memory remain controls, not the competitive method set. If this result
does not exist, the current fork collection is a diagnostic instrument, not a
benchmark-backed method-comparison claim.

A separate SciTasteBench **whole-agent** comparison requires new tasks that
expose a complete problem and final scorer while allowing real systems to keep
their own research loops. No such track exists today. A fixed-menu adapter of
AI Scientist-v2, MLR-Agent, or another complete framework may be described only
as an adapted decision policy, never as the native framework. External official
benchmarks remain necessary even after this track is built.

### Main result 1: external Auto Research systems

Use the frozen ResearchClawBench public snapshot
`researchclawbench-leaderboard-20260923-v3`. Apply its preregistered inclusion
rule: a named autonomous-research agent must have scores for all ten selected
`_002` tasks, and standalone ResearchHarness model rows are excluded. Report
the SciTaste-augmented ResearchHarness at the point implied by the same ten
official scores, but mark it as a separately run system. The table answers
competitiveness only; it does not establish the standing of the independent
SciTaste Native executor.

The main paper should show the five highest public systems, the nearest public
systems around SciTaste, and SciTaste. The appendix should show all 14 eligible
public rows and all ten task scores. Public mean cost may be reported only for
public rows and must not be compared with SciTaste until SciTaste obtains a
closed, equivalent cost receipt.

### Main result 2: matched Taste effect

Use formal V7 only. The independent unit is the task/domain, not the 20 arms,
tool calls, or generated artifacts. Report the mean and median paired effects,
task wins, uncertainty interval, randomization result, and ten domain effects.
The positive mean does not authorize an improvement claim because the median is
negative, SciTaste loses seven tasks, and one Material result contributes
`+15.0` points.

This comparison is the current title-level causal estimate for the Taste
intervention. ResearchHarness Base is an internal control, not an external
method and not SciTaste Native.

### Ablation result

The following rows are components or negative controls:

- same-source Raw/RAG;
- generic outcome memory;
- target-applicable Taste;
- source-disjoint mismatched Taste;
- a direct decision *variant of the same SciTaste controller* without grounded Taste (internal control); an independently implemented direct policy belongs in A1 instead;
- Taste without applicability, reversal, uncertainty, or abstention gates;
- no update and shuffled delayed credit.

They test whether an observed effect comes from structured, applicable,
outcome-grounded experience rather than additional text, arbitrary memory, or
another model call. They must not be listed as competing Auto Research systems.

### Diagnostic result

Report the ten V7 domain effects and the SciTasteBench stage effects rather than
only aggregate mini-tables. Diagnostics should expose heterogeneity, selective
intervention, invalid claims, and resource trade-offs. They explain a result;
they do not create a replacement headline metric.

## Completed evidence

| Evidence object | Population | Result | Permitted claim |
|---|---:|---|---|
| ResearchClawBench public snapshot v3 | 14 public agents, 10 common `_002` tasks | ResearchHarness + SciTaste would lie below ResearchClaw (18.305) and above EvoScientist 0.0.4 (15.000), far below the leading five (34.103--38.256) | the augmented configuration has a real public-system point of reference; no causal rank or SciTaste-Native claim |
| ResearchClawBench formal V7 | 10 domains, 20 matched ResearchHarness arms | `+0.845`, interval crosses zero, 3/10 wins | conditional Taste did not establish an augmentation benefit |
| SciTasteBench formal Objective Fork | 10 task clusters, 30 states | Taste regret 0.1767 versus stage-static 0.1387 within the 120-second test cohort; development allowed 600 seconds | adverse paired diagnostic; not an isolated task-transfer estimate or cross-method comparison |
| SciTasteBench formal Outcome Learning | 5 earlier and 5 later groups, 15 later decisions | update 0.0413 versus no-update 0.0334 and shuffled 0.0427 | reviewed update does not beat both controls |
| Natural contrastive confirmation | 28 source-group-disjoint cases | matched Taste 46.4%, Raw 57.1%, Base 60.7%, mismatched Taste 67.9% | same-family matching is invalid; these are ablations, not system rankings |

## Missing evidence and execution priority

1. **Task-level publication artifact.** Generate a domain dumbbell/forest plot
   from the sealed V7 result and a complete appendix table. This consumes no new
   model or GPU budget.
2. **SciTasteBench independent-method comparison.** Qualify at least two real
   decision policies and a matched-contract, informative fork population before
   a benchmark-method claim. A whole-agent SciTasteBench track is a distinct
   construction project, not a label placed on the current fixed-menu cases.
3. **Mechanism repair on a new population.** Replace broad-family matching with
   target-content applicability and calibrated abstention. Develop only on
   consumed populations, then open one new frozen population. Do not rerun the
   failed confirmatory cases as confirmation.
4. **Second model-family sensitivity.** Repeat only SA/D mechanism contrasts,
   not the entire expensive lifecycle, with a second frontier family after the
   repair is frozen.
5. **SciTaste Native external run.** E2-v6 now passes every static handoff gate
   on the unchanged MLRC-Bench Temporal Action Localisation contract. Execute it
   only after a fresh state-diverse development cohort yields a behaviorally
   active adaptive-allocation policy and passes the target-domain state probe.
   This is required before the paper claims that the complete SciTaste
   framework, rather than a Taste packet on ResearchHarness, was evaluated end
   to end.
6. **Independent accepted-framework execution.** Agent Laboratory,
   AI-Researcher, DeepScientist, MLR-Agent, TinyScientist, AI Scientist-v2, and
   AutoResearchClaw may enter only after their pinned adapter passes task
   translation, licensing, sandbox, artifact, failure, budget, and telemetry
   gates. Public ResearchClawBench rows provide immediate ecological coverage;
   they do not waive these gates or become matched evidence.
7. **External integrity/generalization endpoint.** Add one unchanged external
   population such as EXP-Bench or MLR-Bench only when its task assets and
   scoring rights are executable. Do not combine its metric with
   ResearchClawBench or SciTasteBench.

Under the deadline route, priority 1 and the manuscript correction are
immediate. Priorities 2 and 3 address method credibility; priority 5 closes
the current system-identity gap. None is completed by enlarging an internal
control table or repackaging the consumed fork cohort.

## Hard reporting rules

- Benchmarks are task/evaluation sources; they are not method rows.
- ResearchHarness Base is a matched internal control; it is neither another
  Auto Research framework nor SciTaste Native.
- Raw/RAG, generic memory, mismatched Taste, and gate removals are internal
  controls or ablations. An independently implemented direct decision policy
  is a method baseline, not an ablation.
- Named frameworks belong on a task source only when their genuine control
  loops remain intact. Fixed-menu prompt imitations do not count.
- Named external systems are method rows only when their real implementation or
  an immutable public result is used. No surrogate or prompt imitation counts.
- Ecological best-native scores and matched causal effects remain in separate
  panels with separate captions.
- Development, formal, and post-hoc repair populations remain visibly distinct.
- No omnibus "SciTasteBench score" is computed across regret, learning,
  integrity, and end-to-end progress.
