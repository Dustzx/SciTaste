# Venue-aware evidence-gap critic

SciTaste must not infer top-venue readiness from one favorable table, a large
test suite, or a fluent manuscript. The venue-gap critic compares the complete
claim--evidence portfolio with accepted nearest-neighbour papers and routes the
next scientific action under the project's real submission deadline.

The critic is available through:

```bash
scitaste evidence venue-gap \
  --manifest <project-owned-manifest.yaml> \
  --comparison-profile <accepted-paper-comparison.yaml> \
  --project-id <project-id> \
  --outputs-root outputs \
  --output <project-owned-assessment.json>
```

It reads the target venue and immutable milestones from `ProjectRuntime`. It
does not call a model, execute an experiment, predict acceptance, or predict an
oral decision. A model may help propose a manifest, but the compiler accepts
only explicit source-bound neighbours, observed evidence, and bounded candidate
actions.

## Reviewer questions

Every manifest must answer all of the following questions exactly once:

1. What is new relative to accepted nearest neighbours at the target venue?
2. Does the evaluation measure Scientific Taste rather than style or verbosity?
3. Does the proposed representation have a selective mechanism?
4. Do Taste-guided choices cause better downstream research outcomes?
5. Does the method improve complete idea-to-paper trajectories?
6. Are strong accepted or competitive baselines included under matched budgets?
7. Does the effect replicate across models and domains?
8. Is there objective, hidden, artifact-aware, or otherwise external validation?
9. Are abstention and failure boundaries established?
10. Is the result supported by an independent population and order-robust analysis?
11. What new scientific conclusion follows across experiments?

Evidence is separated into development signals and admitted headline evidence.
A negative development result changes the next experiment but does not by
itself contradict the paper's broad claim. An admitted contradiction does. The
assessment remains `not-yet-competitive` until every declared evidence contract
is covered; even then its strongest output is
`evidence-program-complete-for-review`, never “accepted” or “oral-ready.”

The optional comparison profile makes two previously implicit judgments
machine-checkable. First, every claimed innovation is located on a contribution
axis, tied to named accepted neighbours, and separated into its closest overlap
and a falsifiable difference. The assessment then labels its effect evidence as
proposed-only, development-only, admitted support, or contradicted. A new name
for an existing loop is therefore not counted as demonstrated innovation.
Second, the critic constructs an evidence-component matrix spanning task/domain
breadth, strong system baselines, objective evaluation, mechanism ablation,
expert validation, end-to-end trajectories, real-world cases, uncertainty,
failure analysis, and resource reporting. It reports both whether a component
is present and whether its direction supports or contradicts the paper claim.
There is intentionally no aggregate “ICLR score”: breadth cannot cancel a
failed central mechanism, and a single family cannot become independent
evidence merely by appearing in several table columns.

Action ranking favors high-importance gaps and evidence breadth, discounts work
that cannot finish before the paper deadline, and suppresses literature or
writing polish while empirical core gaps remain open. This prevents a sequence
of cheap local ablations from indefinitely outranking a decisive downstream or
end-to-end experiment.

The assessment also reports an evidence-portfolio breadth diagnostic. It counts
distinct admitted held-out/objective experiment families, separates supporting
and contradicting families, and compares their breadth with the reported
evidence components of accepted neighbours. This is deliberately not an
acceptance threshold: four weak tables are not better than one decisive study.
It is a guard against the opposite error--treating one favorable controlled
table as a complete ICLR argument when accepted neighbours combine task breadth,
strong baselines, ablations, objective or external validation, and case studies.

## SciTaste self-development snapshot

The current project-owned manifest and generated assessment are:

- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_GAP_MANIFEST_V12.yaml`
- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_COMPARISON_PROFILE_V11.yaml`
- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_GAP_ASSESSMENT_V22.json`

The comparison set contains ICLR main-track method, evaluation, and benchmark
papers: ScienceAgentBench and the 100+ researcher ideation study from 2025, plus
EXP-Bench, HeurekaBench, and TusoAI from 2026. They are not interchangeable
baselines. The benchmark papers establish task authenticity and coverage; the
ideation study establishes the standard for blind expert construct validation;
TusoAI establishes the method-paper pattern of strong systems and expert
baselines, ablations, held-out objectives, and real scientific case studies.
The current SciTaste position is `core-claim-contradicted`. A first frozen
NewtonBench block was invalidated rather than reported because required cost
telemetry was unavailable after independent scoring. The repaired, new-seed
formal-v2 block then completed 12 domains and 24 arms under matched budgets.
Learned Taste changed all 12 paired action trajectories, but the preregistered
primary endpoint was 1/12 for Native versus 2/12 for Base (paired difference
-0.083, bootstrap 95% interval [-0.333, 0.167], exact sign-test p=1). The result
therefore establishes behavioral intervention without downstream improvement.
The secondary RMSLE direction cannot replace the negative primary conclusion.
Mechanistically, the treatment selected `REFINE` at all 48 nonterminal decisions
(action entropy 0 bits), while Base used six action types (2.41 bits). The
current learned policy is therefore an action prior rather than a conditional
scientific policy in this environment.

This failure now changes the executable contract. A policy may enter a new H4
preparation only when its admitted episodes contain variation in observable
decision state, compare at least two actions within a state, and identify
different preferred actions in different states. Merely attaching several
action labels to one repeated context is rejected. Future interactive episodes
also record evidence status, evidence confidence, expected value of another
experiment, and trajectory phase, so the next policy can learn a selective
mapping instead of another global action prior. Historical formal-v2 remains a
valid negative result; it is not retroactively reclassified as support.

Two objective empirical families are currently admitted, below the four
reported evidence components in every registered accepted neighbour. The
framework consequently forbids venue-readiness language and exposes the missing
construct-validity, mechanism, end-to-end, strong-baseline, failure-boundary,
and narrative evidence separately. Both admitted families contain contradicting
evidence for central positive claims, so additional breadth cannot reverse their
direction. The next iteration must change and diagnose
the Taste mechanism on development data before any new independent confirmation;
adding another presentation table would not close the scientific gap.

The structured accepted-paper comparison reaches the same conclusion more
sharply. Five evidence components are formally present, but they contain only
two admitted objective families; four of six declared innovation claims are
contradicted, the recursive loop is development-only, and the evaluation
construct is still proposed-only. Strong system baselines, human/expert
construct validation, and admitted end-to-end trajectories are missing despite
appearing in a majority of the registered accepted neighbours. The resulting
next action is therefore a prefix-matched counterfactual action study: fork the
same observable research state across candidate actions, continue each branch
under a common rollout and budget, score hidden terminal outcomes, learn only
on development branches, and confirm on independent states. Another table over
the collapsed policy is explicitly lower priority.

This assessment is deliberately dynamic. Each admitted result updates the same
manifest and recompiles the matrix, so completed work disappears from the next
action queue and a local success cannot hide gaps elsewhere in the evidence
program.

The first objective counterfactual development run is documented in
`docs/research/OBJECTIVE_TASTE_BRANCHING.md`. Correcting the action semantics changed
the local outcome ranking: at one shared NewtonBench prefix, forced `PIVOT` reached
RMSLE 0.0000533 while forced `EXPERIMENT` reached 4.22049. Five other arms did not
expose that endpoint. SciTaste therefore records a local development signal and an
endpoint-coverage problem, not support for the paper's conditional-policy claim. The
counterfactual runner now emits a machine-readable adequacy assessment that always
blocks headline, generalization, and state-conditional-policy claims for a single
prefix. This is the intended interaction between experiment execution and the venue
critic: an interesting result changes the next experiment without automatically
changing the paper's evidence position.

The subsequent frozen formal-v4 population makes that feedback loop concrete. It
evaluated all seven actions at 12 held-out states from four task clusters and passed
the preregistered endpoint-coverage gate, but did not confirm the evidence-status
policy. Relative to static `PROBE`, the policy obtained a +0.0232 mean bounded-utility
difference with a task-cluster interval of [-0.1803, 0.2500] and a practical record of
one win, two losses, and nine ties. Static `EXPERIMENT` exceeded it by 0.0964 on
average, while the policy's selected outcome failed three times. The admitted lesson
is therefore a failure boundary: evidence status by itself is not a sufficient Taste
representation. This adds an independent, objective mechanism family to the evidence
portfolio, but its direction is contradicting; it cannot turn greater evidence breadth
into venue readiness. The next scientific action is representation revision followed
by a new disjoint confirmation—not manuscript polish or another view of the same
table.

The v9 assessment now routes the project to
`learn-content-conditioned-taste-policy`, replacing the already completed generic
counterfactual-study action. Valid negative evidence is admitted as a contradiction
even when it is not eligible to support a positive headline claim; otherwise a system
could hide a failed formal result merely by setting `headline_eligible=false`.

The comparison is now a binding gate rather than a warning string. A portfolio cannot
reach `evidence-program-complete-for-review` unless it contains at least two independent
admitted empirical families, has no contradicting admitted component, and covers every
evidence component reported by a majority of its registered accepted neighbours. The
current comparison still lacks admitted end-to-end trajectories, human or expert
validation, and strong system baselines. This guard prevents one controlled study from
being relabeled across several claims or table columns to simulate an ICLR-level
argument; it remains a necessary condition, never an acceptance or oral prediction.

V10 strengthens this from a paper-wide checklist into a claim--evidence argument graph.
The comparison profile now declares whether SciTaste is a method, benchmark, or combined
contribution and computes evidence-shape references separately from accepted methods and
accepted benchmarks. Every declared innovation has its own centrality, required evidence
components, and independent-family floor. Evidence counts for a claim only when the same
evidence ID is explicitly bound both to that claim and to the required component; unrelated
tables elsewhere in the paper cannot close it. A central claim remains incomplete when any
required component is absent, development-only, contradicting, or supported by too few
independent families.

Applied to the current method-and-benchmark paper, all five central claim arguments are
incomplete. Four are contradicted by admitted objective evidence, while the SciTasteBench
construct remains proposed-only. The accepted-paper evidence shape additionally requires
end-to-end trajectories, human/expert validation, objective or hidden evaluation,
statistical uncertainty, strong system baselines, and task/domain breadth; the current
portfolio lacks the first, second, and fifth of these. Thus the framework now reaches the
same conclusion the paper-level reading demands: several local result tables, including a
well-controlled one, do not constitute a complete ICLR argument.

V12 makes that comparison paper-specific and same-venue aware. It does not merely compare
SciTaste with an aggregate checklist: it emits one gap record for every accepted nearest
neighbour, including the neighbour's contribution type, the components currently supported
or contradicted, the missing or unadmitted components, and the independent supporting
families that make the comparison possible. It also requires at least two recent papers from
the target venue series before the evidence shape can be called complete. For an ICLR 2027
submission, the current set contains five ICLR 2025--2026 main-track neighbours, with ICLR
2026 as the latest completed edition.

No current neighbour row is component-shape matched. Relative to EXP-Bench, SciTaste lacks
admitted end-to-end trajectories, human/expert validation, and strong system baselines;
relative to HeurekaBench it lacks end-to-end trajectories and strong system baselines;
relative to the 100+ researcher ideation study it lacks human/expert validation and strong
system baselines; relative to ScienceAgentBench it additionally lacks admitted resource/cost
reporting; and relative to TusoAI it lacks end-to-end trajectories, a real-world case study,
and strong system baselines. Matching a row would still not assert equal novelty, rigor,
scale, or quality. The compiler records `quality_equivalence_claimed=false` by construction.
This is the embedded ability required for self-improvement: every new result is judged both
against the paper's own causal claim graph and against the actual evidence shape of recent
accepted papers, so a single controlled table cannot silently become a top-venue claim.

V14 also admits the latest direct-action development result without changing that venue
position. Separating evidence selection from a single recommended action raised mean bounded
objective utility from 0.2774 to 0.3820, preferred-action hits from 58.3% to 83.3%, and reduced
selected-action failures from 8.3% to zero. The strongest matched static action still scores
0.3850, however, and the frozen development contract required a further 0.02 superiority
margin. The result is therefore useful mechanism diagnosis but remains contradicting,
development-only evidence. All five central claim arguments remain incomplete, and the same
three portfolio-level gaps remain: admitted end-to-end trajectories, human/expert validation,
and strong system baselines.

V15 adds evidence-strength references instead of treating component names as equal proof. Every
accepted-paper row may bind source-reported counts for authentic tasks, source publications,
competitive systems, expert evaluators, scientific disciplines, mechanism ablations, random
seeds, and real-world cases. The compiler contrasts them with registered current-project counts
and emits `current-missing`, `below-accepted-reference`, or
`meets-or-exceeds-reference`. Count parity is explicitly diagnostic and never claims equal quality.

The present scale gap is large. EXP-Bench reports 461 authentic experiment tasks from 51 papers;
ScienceAgentBench reports 102 tasks from 44 publications, four disciplines, nine subject-matter
experts, and fifteen model--framework configurations; HeurekaBench contains 100 main questions,
compares three scientific agents, and validates its judge with eleven experts; TusoAI evaluates
eleven scientific applications, four mechanism ablations, three random seeds, and two real-world
cases. SciTaste currently registers zero peer-reviewed-workflow tasks, zero competitive external
systems, zero experts, one discipline, one seed per task/domain, two admitted negative mechanism
families, and zero real-world discovery cases. These counts do not prescribe an ICLR minimum, but
they make it impossible to mistake the current controlled NewtonBench table for comparable
paper-level evidence.

V16 makes the comparison an experiment-controller decision. Candidate actions now declare
which accepted-paper evidence components they can produce; their ranking records the exact
missing components and accepted papers made more comparable by that action. The compiler also
emits a single `evidence_program_decision` with a mode, next action, blocking central claims,
scale shortfalls, and an explicit paper-level-claim authorization bit. Under the current
admitted contradictions it selects `repair-contradicted-core-claim`, routes to
`learn-content-conditioned-taste-policy`, and sets
`paper_level_claims_authorized=false`. The subsequent matched end-to-end action is separately
linked to the three majority gaps: end-to-end trajectories, human/expert validation, and strong
system baselines. Thus accepted-paper comparison now changes resource allocation; it is not a
post-hoc paragraph appended to the paper.

V17 exposes the paper-level distance explicitly instead of requiring a reader to reconstruct it
from several matrices. The compiler assigns the first binding `competitiveness_band` across five
ordered checks: a source-bound same-venue comparison basis, admitted contradictions to central
innovations, complete claim-linked central arguments, accepted-neighbour component shape, and
accepted-neighbour scale references. These are categorical scientific blockers rather than a
weighted readiness score, and the selected band is copied into the evidence-program controller.

The refreshed V18 self-development assessment admits the expanded-source result as
development-only support and routes the next action to
`confirm-content-conditioned-taste-policy`. Its paper-level result remains
`central-claim-contradicted`: four of five central innovation claims have admitted contradictory
evidence, zero of five central claim arguments is complete, zero of five accepted ICLR neighbours
is component-shape matched, and zero of five is scale-reference matched. The new positive
expanded-source selector result is correctly retained as development evidence: it authorizes a
new independent confirmation population but cannot erase the earlier admitted contradiction or
close the end-to-end, expert-validation, and strong-baseline gaps. This is the framework-level
recognition that a favorable controlled table remains far below an ICLR paper evidence program.

V19 records the first prospectively frozen confirmation of that expanded selector. Formal v5
used four source-disjoint NewtonBench tasks, 12 target states, and 84 forced branches. Its branch
observation rate passed the frozen 85% floor, but one of 12 selector calls was rejected and the
protocol did not authorize retries, making the confirmation inadmissible. The intention-to-treat
diagnostic was also unfavorable: mean bounded objective 0.2044 versus 0.2559 for static `PROBE`,
task-cluster interval [-0.1296, -0.0003], and 25.0% versus 16.7% failure. The split remains closed
against policy updates, so it is registered only as development-level contradictory boundary
evidence rather than recycled into a second confirmation.

The evidence controller consequently replaces `confirm-content-conditioned-taste-policy` with
`rebuild-content-conditioned-taste-before-new-confirmation`. Paper-level claims remain
unauthorized and the overall competitiveness band remains `central-claim-contradicted`. This is
the intended behavior of the embedded top-venue critic: a positive development table triggers a
real independent test, and a failed or inadmissible test moves the project back to mechanism
development rather than disappearing from the manuscript or being patched post hoc.

V20 adds the subsequent comprehensive development replay and still refuses to interpret more
reference cases as stronger paper evidence. After endpoint-direction normalization and removal of
one duplicate observed prefix, the 11-state, seven-task-cluster replay scores 0.5429 bounded
utility versus 0.6808 for static `PROBE`, with 27.3% versus 9.1% failure. It is registered as a
development-only contradiction to the decision mechanism and abstraction claims. The paper-level
diagnosis is unchanged: zero of five central claim arguments is complete, zero of five accepted
ICLR neighbours is evidence-shape or scale matched, and admitted end-to-end trajectories,
human/expert validation, and strong system baselines remain missing. A local mechanism repair can
remove a central contradiction; it cannot by itself make the paper ICLR-comparable.

V22 registers the balanced observable-state replay and sharpens the mechanism diagnosis. Six
new cross-task precedents were frozen before their branch outcomes, exhaustively labelled over
seven actions, and evaluated on the same 11-state development population. Utility decreased to
0.4520 against 0.6808 for static `PROBE`, while failure increased to 36.4% against 9.1%. The
controller therefore rejects another confirmation and replaces source expansion with an
outcome-calibrated epistemic-state representation and abstention mechanism.

The same assessment compares this result with five verified ICLR 2025--2026 accepted papers:
EXP-Bench, HeurekaBench, the 100+ researcher ideation study, ScienceAgentBench, and TusoAI. It
still reports `central-claim-contradicted`, 0/5 complete central arguments, 0/5 accepted-neighbour
component-shape matches, and 0/5 scale-reference matches. Missing admitted portfolio components
remain end-to-end trajectories, human or expert validation, and strong system baselines. Thus
the top-venue critic changes the experiment controller before paper writing: one controlled
family, whether positive or negative, is explicitly incapable of authorizing an ICLR-level
claim.

The capability-driven research program v10 makes this decision a lifecycle gate rather than
an optional report. Its `evidence-admission` phase now requires the exact
`venue-competitiveness-assessment` alongside registered claim--result links, validity findings,
retained failures, and contradictions. The runtime accepts that phase only when the assessment
binds the current project snapshot, uses a recent same-venue comparison set, closes every
central claim argument, reports no admitted contradiction, matches the declared accepted-paper
evidence obligations, and emits `declared-evidence-program-review-comparable`. Otherwise paper
assembly is blocked and the project returns to the assessment's experiment or analysis action.
The gate deliberately does not predict acceptance or oral selection: it establishes that the
paper has a reviewable evidence program, not that reviewers must accept it.
