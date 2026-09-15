# SciTaste complete AutoResearch program v3

Status: **complete planning contract; no execution authorized**.

The machine-readable authority is
[`iclr2027_scitaste_complete_autoresearch_program_v3.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_complete_autoresearch_program_v3.yaml),
with file SHA-256
`b7e2b78f7ebe96117b6e270c0813fe1e97bb53ac54980630103719fc990ca908`.
It is additive to lifecycle program v2 and does not rewrite v1, v2, historical
runs, model inventories, or the public Roadmap. It authorizes no download, API
call, GPU use, installation, or experiment.

## Main experiment, now separated into four jobs

| Layer | Question | Task source | Primary endpoint |
|---|---|---|---|
| E1 | Do abstraction, contextual match, autonomous selection, and reviewed delayed credit improve scientific decisions? | SciTasteBench | Operationally final, condition-blinded dual-AI endpoints; explicitly nonhuman proxies |
| E2 | Does SciTaste improve actual research progress? | An admitted scorer-owned executable route: currently v9-bound MLRC-Bench, or MLE-bench after exact resource registration | Hidden objective progress, retaining every failure |
| E3 | Can the system finish idea → proposal → experiment → evidence → paper → review-driven revision? | MLR-Bench | Evidence-valid complete package plus dual-AI paper review |
| E4 | Where does the executable experiment chain fail? | EXP-Bench | Hypothesis, design, implementation, execution, conclusion, and conjunctive success |

Benchmarks supply tasks and endpoints. They are not competitor methods. The
method matrix is separately fixed as SciTaste Native, Native Base, a direct-tool
agent realization for the full-lifecycle baseline, MLR-Agent, Agent Laboratory,
and DeepScientist. An external row runs only after its unchanged-core adapter,
task/model mapping, sandbox, telemetry, artifacts, failure/resume behavior, and
license obligations pass. Until then it remains visibly `blocked`; no prompt
wrapper or imitation may stand in for it.

## Two research paradigms

E1 and the Scientific Taste intervention are parameter-training-free. The
agent model is frozen; H3 may update only grounded episode memory,
action-specific delayed credit, routing statistics, and abstention state. It may
not fine-tune model weights or learn from formal held-out labels.

GPU use belongs primarily to E2--E4 experiment execution: generated candidate
methods may train models, evaluate checkpoints, and run benchmark workloads.
The research agent itself may be a hosted API model or a qualified local model.
Local inventory and newly downloadable models are candidates after task fit,
identity, conformance, and authorization checks; neither Qwen3-VL-2B nor one RTX
3090 is privileged or hard-coded into the main design.

The program binds the complete role inventory in
`configs/resources/assets/model_role_inventory_v1.yaml`, not a single
checkpoint. Research, coding, judging, embedding, and task-training roles are
selected separately; one model is not required to fill every role. The current
local and API assets are candidates, and the pool may expand with newly
downloaded models when the scientific task requires it.

## Compact causal design

SciTasteBench uses five named core conditions:

- `base`: task state only;
- `raw`: equal-budget evidence from the same source bytes;
- `matched`: source-grounded in-scope Taste without formal outcome update;
- `mismatched`: source-disjoint, quality- and token-matched out-of-scope Taste;
- `full`: autonomous selection, grounded Taste, critics, controller state, and
  reviewed delayed-credit memory.

H1 is Matched--Raw, H2 is Matched--Mismatched, and Full--Base is the bundled
system contrast. H2b changes only the selector inside Full, using the same
closed hard-negative pool. H3 changes only the parameter-free memory update
inside Full, with no-update as comparator and source-group-blocked shuffled
credit as its negative control. These two nested controls are scientifically
required; they are not a license to cross every toggle into an arbitrary grid.

Two independent, identity-distinct AI reviewers decide each operational E1
endpoint, with one distinct AI adjudicator only on disagreement. The same review
finality governs package review and paper revision. This removes human staffing
from the critical path but does not create human/expert validity. Only a held-out
objective scorer may support the title-level effectiveness claim.

Tool Intelligence and Generation as Content are not detached headline methods.
They are two cross-cutting ways to improve the same lifecycle Taste policy:
Tool Intelligence supplies endogenous process, cost, failure, and outcome
evidence; Generation as Content exposes the policy to exogenous user correction
and counterfactual intervention. A supporting ablation measures each incremental
effect while holding the other plane fixed. Their interaction is tested only on
a powered minimal 2x2 subset, not by multiplying the entire experiment matrix.
The Generation-as-Content effect requires authentic, prospectively locked user
interventions; AI stand-ins may exercise the software path but cannot establish
a human-intervention claim.

## Full automation boundary

Every end-to-end trajectory follows one fail-closed state machine:

```text
task acquisition proposal
  → quarantined, hashed assets
  → task admission and source-group split freeze
  → task-excluded model and unchanged-core system freeze
  → closed idea generation and pre-execution decision lock
  → experiment-plan freeze
  → development execution with complete failure/cost logs
  → candidate code/environment/checkpoint freeze
  → isolated hidden inference and scoring
  → evidence admission and contradiction accounting
  → evidence-linked paper assembly
  → two independent AI reviews (third AI only on disagreement)
  → review-driven revision
  → final dual-AI disposition and immutable package freeze
```

Hidden labels and scores stay scorer-only until candidate freeze. Formal manual
repair and human rescue are forbidden. Invalid, fabricated, timed-out,
over-budget, environment-failed, provider-failed, and safety-stopped runs remain
in the intention-to-run analysis. Paper generation cannot invent, repair, or
reinterpret missing experiment evidence.

## Model, budget, and expansion policy

Model selection uses task-excluded conformance cases and cannot inspect any
formal task identity, source group, output, review, reference paper, label, or
hidden score. Results are reported under two non-pooled estimands:

1. **Matched-model:** the same exact model, task information, tools, repair
   policy, wall time, API budget, and compute ceiling; systems unable to support
   that model are excluded from this estimand.
2. **Best-available:** each admitted unchanged-core system uses its strongest
   task-excluded-qualified native model under a common resource ceiling, with
   model and adapter confounding disclosed.

Task groups union source paper, repository, dataset, and task family. Model
selection, development pilot, Taste-update, formal held-out, and judge
calibration partitions are source-group-disjoint. Repetitions are nested
measurements, not extra independent tasks.

Execution expands in three gates: B0 validates the entire lifecycle on
task-excluded development inputs; B1 runs the smallest complete source-disjoint
formal block covering E1--E4, hidden scoring, failures, paper, dual review, and
revision; B2 scales only after B1 is complete and clustered power is frozen from
pilot variance, failure rate, and cost. This replaces a convenient
systems × tasks × seeds grid with only preregistered contrast-required cells.

## Present readiness

The scientific program and lifecycle contract are complete, but execution is
correctly closed. SciTasteBench has zero formally admitted natural cases; the
external task packages and external method adapters remain blocked; no primary
model, B0 evidence, power result, exact prelaunch manifest, or owner-approved
hash exists. The next artifact is one exact content-addressed B0 prelaunch
manifest—not another redesign of the experiment matrix.
