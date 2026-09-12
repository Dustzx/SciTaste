# ICLR 2027 dual-estimand prepilot governance v1

Date: 2026-09-12

This protocol freezes two small, separate, non-launchable prepilot designs. It
authorizes no data acquisition, provider call, SSH connection, GPU action,
external checkout, human recruitment, or experiment. A later proposal may
launch only after the project owner reviews exact task bytes, models, costs,
runtime placement, reviewers, and every blocker and approves that proposal's
content hash.

## Why there are two proposals

The paper's title-level causal question and its ecological system-comparison
question are different estimands and cannot share a headline verdict.

1. The native-Taste proposal changes only SciTaste decision-policy components
   while holding executor, Qwen3-VL-2B checkpoint, task bytes, tools, repair
   policy, seed, and budget fixed. It estimates the causal contribution of
   Scientific Taste.
2. The external best-native proposal preserves the real model configuration of
   each accepted system. It estimates complete-system outcomes in an ecological
   setting, with model effects explicitly confounded. It cannot establish the
   causal value of Taste or broad external superiority.

No result, failure, review, or resource record may be moved between the two
proposals. A common task identifier does not make their estimands exchangeable.

## Native-Taste causal prepilot

The candidate is Full SciTaste. The five preregistered contrasts are against
Native Base, Knowledge only, Taste only, Critics only, and a source-disjoint
mismatched-Taste placebo. The Base contrast is the no-Taste control; the
mismatched condition tests whether merely adding retrieved scientific-looking
content explains the effect. All six conditions must be real first-party
executors before launch.

The bounded prepilot has two MLRC-Bench task candidates—Temporal Action
Localisation and Cross-Domain Meta Learning—one seed, one repetition, and
twelve planned trajectories. This is a gate- and failure-discovery block, not a
powered sample and not a formal claim. Both tasks must first be acquired under
their exact license policy, content hashed, isolated, baseline reproduced, and
shown to expose a condition-invariant objective scorer. The remote host must
attest the same Qwen3-VL-2B tree currently identified locally by SHA-256
`47f9c0e0e48a54c74fb0b2b0ffa7a182fed381d5ed49a0200872038d1c286d34`.

The primary pilot outcome is task-normalized objective progress. Blinded expert
package review is required as a secondary evidence-validity check; automated
model judgment remains diagnostic. Every Full-versus-control contrast is
reported. Formal task count and repetitions must follow a post-pilot power
analysis rather than copying this matrix.

## External best-native prepilot

The candidate is SciTaste Native; accepted comparators are Agent Laboratory and
TinyScientist. Each system receives its own statically supported native model:
SciTaste uses the registered DeepSeek candidate, Agent Laboratory uses its
documented `o3-mini` default, and TinyScientist uses its fixed
`gpt-4o-2024-08-06` registry entry. Model availability, revisions, credentials,
and prices must be authenticated before launch. The project currently has no
OpenAI credential and no DeepSeek credential binding, so this design is not
resource-ready.

The bounded prepilot uses the same two task candidates, one seed, one
repetition, and six trajectories. Its primary outcome is condition-blinded
independent expert preference for scientific value and evidence validity of the
complete package. Objective progress, failures, reproducibility, wall time,
tokens, cost, interventions, and active GPU use are secondary and never pooled
across systems without disclosure.

The lane must remain `best_native` with `model_effects_confounded=true`. Even a
positive SciTaste result is descriptive external-validity evidence only. It
cannot make the title claim, establish a scaffold effect, or be reported as a
matched-backbone comparison.

## Failure and missingness policy

The analysis population is intention-to-run: every preregistered
task-by-system-by-seed unit remains in the denominator. Runtime failure, timeout,
budget exhaustion, invalid artifact, unsuccessful experiment, and absence of a
publishable package are outcomes, not reasons to delete a cell. A valid failed
cell retains its telemetry, error code, raw logs, and reviewer-facing failure
package and receives the prespecified task failure floor where an objective
score is required.

Missing records, identity drift, incomplete telemetry, unauthorized repair,
lost artifacts, or broken blinding are invalid evidence and prevent
confirmatory completion. They are not converted to ordinary failures. Repairs
may fix only infrastructure or adapter defects under a prespecified attempt
limit; they may not change task meaning, model, tools, budget, research policy,
scorer, or condition. Every attempt remains retained.

## Leakage, review, and stopping

- Task sources must be disjoint from Taste examples and from any development or
  prompt-tuning source group. The mismatch placebo must draw from a separately
  frozen source group.
- Condition labels, system names, model names, costs, and failure causes are
  hidden from at least two conflict-checked independent reviewers until scores
  and adjudication are sealed.
- Stop before any external action on task/license drift, model-identity drift,
  missing credential, unexpected network need, sandbox failure, incomplete
  telemetry, or resource asymmetry.
- Stop after the single approved prepilot block. Inspect failures, variance,
  reviewer burden, and model-versus-framework attribution before proposing any
  powered formal study.
- A positive automated score, successful smoke test, or complete paper draft
  never upgrades either prepilot into formal ICLR evidence.
