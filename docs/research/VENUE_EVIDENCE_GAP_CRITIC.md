# Venue-aware evidence-gap critic

SciTaste must not infer top-venue readiness from one favorable table, a large
test suite, or a fluent manuscript. The venue-gap critic compares the complete
claim--evidence portfolio with accepted nearest-neighbour papers and routes the
next scientific action under the project's real submission deadline.

The critic is available through:

```bash
scitaste evidence venue-gap \
  --manifest <project-owned-manifest.yaml> \
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

- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_GAP_MANIFEST_V3.yaml`
- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_GAP_ASSESSMENT_V4.json`

The comparison set contains the ICLR 2025 main-track ScienceAgentBench paper and
the ICLR 2026 main-track EXP-Bench and TusoAI papers. The first two show the
scale and validation expected of benchmark work; TusoAI shows the breadth,
baseline strength, ablations, and real case studies expected of a method paper.
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

Only one objective empirical family is currently admitted, below the four
reported evidence components in every registered accepted neighbour. The
framework consequently forbids venue-readiness language and exposes the missing
construct-validity, mechanism, end-to-end, strong-baseline, failure-boundary,
and narrative evidence separately. The next iteration must change and diagnose
the Taste mechanism on development data before any new independent confirmation;
adding another presentation table would not close the scientific gap.

This assessment is deliberately dynamic. Each admitted result updates the same
manifest and recompiles the matrix, so completed work disappears from the next
action queue and a local success cannot hide gaps elsewhere in the evidence
program.
