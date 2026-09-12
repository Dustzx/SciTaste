# H1/H2 human preference analysis

The H1/H2 pipeline has two distinct boundaries. `human-outcome-audit` verifies
that every reviewer saw condition-blinded, budget-matched outputs, that all
primary reviews were locked before the committed key was opened, and that the
opened conditions form the registered H1 and H2 contrasts.
`human-preference-analyze` then computes the effect; readiness to analyze is not
itself an effect.

The analysis command accepts the original locked-review set and blind opening,
not a caller-supplied outcome table. It reruns the integrity audit internally so
that forged `ready` flags or relabeled outcomes cannot enter inference.

A schema-1.1 human study binds its scope, exact post-pilot analysis contract, and
(for formal work) power-analysis bytes before outcome review. The analysis
contract fixes response coding, the independent unit, aggregation, missingness
ceiling, minimum source-group count, minimum effect, interval/test seeds, alpha,
and Holm family. Pilot and formal studies remain separate.

The primary response is coded as 1 when matched abstracted Taste is preferred,
0.5 for a tie, and 0 when the registered comparator is preferred. The engine
averages the two blinded reviewers within a case, averages cases within a source
group, and gives source groups equal weight. It never treats a reviewer rating,
candidate-order repeat, or case from the same source group as an independent
sample. It reports raw review counts, missingness, source-group effects, reviewer
diagnostics, source-group bootstrap intervals, paired source-group sign-flip
p-values, and Holm-adjusted H1/H2 decisions.

The joint title gate passes only for a formal study when both H1 and H2 clear
their preregistered minimum effect and adjusted alpha threshold. A pilot report
cannot pass the formal gate. The analyzer recruits no reviewer, opens no blind
key, invokes no model, spends no API budget, and allocates no GPU.

The shipped estimator is the design-based, source-group-clustered option already
described by the protocol. The final formal contract must be selected after the
pilot and before formal outcomes. If pilot diagnostics show that repeated
reviewer effects materially dominate despite randomized X/Y order, the formal
study must be frozen under a new contract with an appropriate crossed-effects
model; SciTaste must not silently switch estimators after opening outcomes.
The excluded pilot report feeds the separate
[`CLUSTERED_POWER_ANALYSIS.md`](CLUSTERED_POWER_ANALYSIS.md) planner, which uses
source-group dispersion but never the observed pilot mean as its effect target.
