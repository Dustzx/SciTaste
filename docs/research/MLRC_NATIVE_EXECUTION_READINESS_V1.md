# Independent SciTaste Native execution readiness v1

Status: **historical E2-v6 static handoff, superseded by later development
execution**. This document records the pre-execution state of policy v13; it is
not the current project status. See the project evidence ledger and
`docs/research/MLRC_VISION_MAINLINE_STATUS_V1.md` before launching another arm.

Subsequent real Perception development runs completed a four-arm research
comparison and a policy-ON/OFF pair. The latter favored policy OFF by 0.01062
task-score units on this one consumed task. Policy v19 is application-ready by
its support criterion, but no formal effect is established. Neither the old
v13 blocker nor the v19 readiness bit authorizes a formal launch.

## Experiment identity

This was the first static protocol intended to evaluate the first-party SciTaste
Native lifecycle rather than a Taste packet attached to ResearchHarness.

- Protocol: `configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v6.yaml`
- Benchmark: unchanged MLRC-Bench Temporal Action Localisation task at upstream
  commit `0d26417034811d2d4587646c4520cc305ea09dd6`
- Treatment: SciTaste Native with the learned adaptive-allocation policy
- Matched control: the same Native executor with policy weight zero
- Research/code agent: Bailian `qwen3.8-max-2026-09-02`
- Task model: LocPointTransformer, 768-dimensional input, 63 classes, trained
  from the fixed random initialization for 50 epochs plus five warmup epochs
- Objective: mean average precision over tIoU 0.1--0.5
- Compute ceiling: two sequential development arms, two RTX 3090s per arm,
  four aggregate GPU-hours; only after development closure, two formal arms and
  sixteen aggregate GPU-hours
- Agent ceiling per block: at most eight calls, 193,536 total tokens, USD 1.00,
  no retry

## What is ready

The v6 no-call inspection passes every static gate: exact bytes, accepted Idea,
program semantics, durable project controller, runtime, task initialization,
matched pair, intervention identity, model-selection boundary, resource
envelope, hidden-scorer firewall, and complete workflow.

Runtime v3 owns a distinct label-redacted inference projection containing
10,719 files and 749,807,339 bytes. The candidate sandbox receives no held-out
labels or scorer mount, candidate bytes freeze before hidden inference, and the
scorer requires the exact prediction hash. Its materialization made no model
call, GPU allocation, API call, or benchmark execution.

## Historical blocker at v13

Current policy v13 has sufficient observed support for adaptive allocation
(`4.99` versus the fixed support floor) but no eligible adaptive head. Its
readiness record therefore sets `policy_application_ready=false`, and no
outcome-blind MLRC state probe proves an active, feedback-sensitive ON/OFF
treatment. Replaying the current eligibility rule over the archived v12 and
v13 policy heads shows the same deeper issue: nearly every admitted episode has
the same coarse state (`four-plus` remaining experiments, zero failures, and
unknown progress), so the learned preference is a global `REFINE` prior rather
than a state-adaptive policy.

This is a scientific blocker, not missing infrastructure. Policy v12 happened
to pass an earlier readiness snapshot produced before the stricter
state-adaptation rule was introduced; under the current rule it also fails.
Selecting that stale snapshot would both use outdated semantics and be
outcome-dependent policy cherry-picking: E2-v5 never prospectively froze v12
for this untouched task. E2-v6 therefore binds the current v13 evidence and
refuses to spend API/GPU budget on an inert nominal treatment.

## Historical next action at v13

The runtime now records evidence status, confidence, remaining experiment value,
and trajectory phase, but the existing admitted episodes predate that richer
projection. Acquire a fresh prospective development cohort whose decisions
cover genuinely different observable states and actions, freeze the resulting
policy before MLRC execution, and run the outcome-blind target-domain state
probe. If it passes, the existing two-arm development block can launch without
another model-selection or runtime campaign. If the method is intentionally
defined to abstain, run and report that as system-completeness evidence only;
it cannot estimate a causal Taste effect because both arms would be behaviorally
identical.

The formal block remains downstream of a completed development pair and an
actual GPU baseline reproduction. No external framework is represented in this
matched pair; real public systems remain in the separate ecological comparison.
