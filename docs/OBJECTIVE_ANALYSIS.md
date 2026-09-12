# Preregistered objective analysis

SciTaste's H3 claim cannot be supported by manually entering an effect estimate
into a result manifest. The executable path is now:

1. freeze one `ObjectiveOutcomeContract` before formal outcomes exist;
2. bind the exact contract file in `AnalysisContract`;
3. record every planned cell, including failures;
4. score each successful cell with the task's content-bound scorer and freeze an
   `ObjectiveMeasurementSet`;
5. run `scitaste evaluation objective-analyze` to create the analysis report and
   completed result set; and
6. pass that result set through the existing project result-admission gate.

The objective contract fixes each task's metric/version, scorer bytes, direction,
raw range, starting score, target, and failure score. Scores are expressed as
normalized progress, where zero is the starting score and one is the target. A
failed cell receives the worst attainable normalized score declared before the
run; it cannot disappear from the analysis.

## Independent units and inference

The independent unit is a held-out task with a unique source-group identity.
Seed and repetition trajectories are paired within a task and averaged before
inference. Consequently, two tasks with four trajectories each produce two
independent observations, not eight. Tasks receive equal weight.

For every registered contrast, the analyzer reports the candidate-minus-control
effect, a task-clustered percentile-bootstrap confidence interval, and a
one-sided paired task sign-flip test against the preregistered minimum effect.
The sign-flip distribution is exact for the configured small-task regime and
uses a deterministic Monte Carlo approximation above that limit. Holm correction
is applied only to contrasts registered as confirmatory. Mechanism diagnostics
remain mandatory in the result bundle but cannot veto or establish the title
claim.

A schema-1.2 primary comparison records both the number of independent tasks and
the number of observed seed/repetition blocks. The formal claim is supported only
when every confirmatory interval clears its minimum effect and every Holm-adjusted
p-value is below alpha. Pilot reports are descriptive and can never set
`formal_effectiveness_established`.

## Command boundary

`objective-analyze` is a local, deterministic post-processing command. It reads
only files already named by the caller, rehashes the power analysis, objective
contract, task scorers, and score artifacts, and writes an immutable analysis
report plus a completed result set under the owning project. It refuses to
replace existing primary comparisons. Each schema-1.2 comparison also binds the
measurement-set bytes. Result admission reloads those measurements, reruns the
estimator, and requires the stored report and every statistic to match; a
self-consistent but hand-edited p-value is rejected. It performs no model call,
API spend, GPU work, task download, reviewer recruitment, or experiment launch.

This implementation makes the H3 analysis path executable; it does not supply
formal measurements. A new formal prelaunch manifest must bind the objective
contract, powered task count, frozen source commit, exact task assets, model
identity, and approved resource budget before any effectiveness claim is
eligible.
The excluded H3 pilot report feeds the separate
[`CLUSTERED_POWER_ANALYSIS.md`](CLUSTERED_POWER_ANALYSIS.md) planner. That path
powers independent held-out tasks and records seed/repetition blocks only in the
resource count.
