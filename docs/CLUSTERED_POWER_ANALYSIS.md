# Pilot-to-formal clustered power analysis

SciTaste does not treat a large cell count as a large scientific sample. H1/H2
are powered over held-out source groups and H3 is powered over held-out tasks.
Seeds, repetitions, reviewer assignments, candidate-order repeats, and multiple
cases inside one source group change cost or measurement reliability; they do
not increase the independent-unit count.

`scitaste evaluation clustered-power-plan` consumes an exact, self-hashed pilot
analysis report produced by `human-preference-analyze` or `objective-analyze`.
The pilot must be explicitly scoped as a pilot and excluded from the later
formal test. The power request binds both the pilot file hash and its semantic
report hash, the formal study identity, complete confirmatory family, alpha,
joint target power, independent-unit floor and ceiling, and resource geometry.

## Conservative planning rule

The effect target is a separately justified smallest effect of interest. The
observed pilot mean is reported but is never reused as that target, avoiding a
winner's-curse sample-size reduction. The pilot supplies independent-unit
dispersion only.

For each contrast, the planner uses the maximum of:

- the observed sample standard deviation;
- a preregistered upper percentile of the independent-unit bootstrap
  distribution of that standard deviation; and
- a justified nonzero dispersion floor.

The confirmatory family uses a Bonferroni planning bound for the formal Holm
procedure. If the desired joint power is `P` for `K` contrasts, each contrast is
planned at alpha `alpha / K` and marginal power
`1 - (1 - P) / K`. The normal-approximation unit count is

```text
ceil(((z_(1-alpha/K) + z_(marginal power)) * dispersion / effect margin)^2)
```

where `effect margin` is the smallest effect of interest minus the registered
claim minimum. The recommendation is never smaller than the registered formal
unit floor or the number required for the one-sided exact sign-flip test to have
sufficient p-value resolution. The largest requirement across the complete
confirmatory family becomes the fixed formal sample size.

This calculation is deliberately conservative and transparent. It does not
claim that a normal approximation is the final estimator: the formal H1/H2 and
H3 analyses retain their preregistered source-group/task bootstrap intervals,
sign-flip tests, and Holm decisions.

## Resource and stopping boundary

The report separately states independent units, generated trajectories, and
human judgments. Increasing `generation_blocks_per_condition_unit` multiplies
the trajectory count but cannot lower the powered task/source-group count. If
the recommendation exceeds the declared independent-unit ceiling, the command
emits the complete report with
`ready_for_formal_sample_size_freeze=false`; it does not silently reduce the
sample or trade tasks for seeds.

The formal size is fixed before formal outcomes. The planner authorizes no
sequential peeking, optional stopping, model call, API spend, GPU job, reviewer
recruitment, or experiment execution.

Example:

```bash
.venv/bin/scitaste evaluation clustered-power-plan \
  --request outputs/projects/<project>/evaluations/<pilot>/power/REQUEST.yaml \
  --evidence-root outputs/projects/<project> \
  --output outputs/projects/<project>/evaluations/<formal>/power/REPORT.json \
  --require-within-ceiling
```

No real SciTaste pilot has yet produced such a report. Consequently the current
project still has no defensible formal sample size; this implementation closes
the pilot-to-design computation path rather than fabricating power evidence.
