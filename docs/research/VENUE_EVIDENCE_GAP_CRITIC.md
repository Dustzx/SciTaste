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

## SciTaste self-development snapshot

The current project-owned manifest and generated assessment are:

- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_GAP_MANIFEST_V1.yaml`
- `outputs/projects/scitaste-self-development/planning/iclr2027/VENUE_GAP_ASSESSMENT_V1.json`

The comparison set contains the ICLR 2025 main-track ScienceAgentBench paper and
the ICLR 2026 main-track EXP-Bench and TusoAI papers. The first two show the
scale and validation expected of benchmark work; TusoAI shows the breadth,
baseline strength, ablations, and real case studies expected of a method paper.
The current SciTaste position is `not-yet-competitive`: the natural decision
studies are development evidence, the first downstream cohort had an inactive
treatment, and the single repaired trajectory cannot establish an average
effect. The critic therefore ranks an artifact-verifiable matched-budget
idea-to-paper comparison above additional manuscript polish.

This assessment is deliberately dynamic. Each admitted result updates the same
manifest and recompiles the matrix, so completed work disappears from the next
action queue and a local success cannot hide gaps elsewhere in the evidence
program.
