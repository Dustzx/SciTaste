# Experiment design loop

SciTaste now distinguishes a research-plan proposal from an experiment that is
safe and scientifically justified to launch. The typed contract lives in
`scitaste.evaluation` and covers five non-interchangeable evaluation tracks:
decision mechanism, full lifecycle, experiment integrity, frontier progress,
and self-development.

## Recursive ownership

The SciTaste product is developed through the `scitaste-self-development`
project. That project may propose separate formal child projects for held-out
tasks. Each child binds one task, one real system, one protocol version, and its
evidence artifacts. Results can return to the parent as design evidence, but a
product change creates a new formal protocol; it cannot mutate an already
started comparison.

The self-development case is process evidence only. The design gate rejects it
if it enters a headline comparison.

## Completeness gates

`ExperimentDesignGate` requires the headline design to contain:

- SciTaste and at least two independent external systems;
- real implementations rather than mocks or renamed SciTaste conditions;
- an exact hash of the accepted-evaluation resource corpus, external-system
  resource IDs, immutable upstream commits, and task-to-benchmark bindings;
- a passed `comparison_system` resource report for every external system and a
  passed `task_source` report for every headline benchmark;
- held-out, non-self-referential tasks with retrievable assets and executable
  success signals;
- matched backbone, starting information, tool permissions, repair policy, and
  resource telemetry;
- a declared estimand, experimental unit, failure policy, power-analysis
  reference, blinded human review, and judge-validation reference;
- immutable feedback/version boundaries and evidence-bound paper generation.

The gate emits two statuses. `design_complete` means the scientific proposal
contains the required information. `execution_authorized` additionally requires
an explicit approval record whose hash matches the exact proposal bytes. This
prevents a completed planning object, a model-generated suggestion, or a stale
approval from launching API/GPU work.

The resource decision is derived from the versioned corpus in
[`research/data/autoresearch_evaluation_resources_v2.yaml`](research/data/autoresearch_evaluation_resources_v2.yaml).
Corpus prose cannot set `eligible=true`: `scitaste.evaluation` recomputes the
answer from use-specific gates. `reference` and `code_audit` permit citation and
read-only inspection only. `task_source` additionally requires a frozen
source-disjoint task manifest, task assets, upstream licenses, and executable
signals. `comparison_system` additionally requires license acceptance, an
unchanged-core adapter, task/model equivalence, sandboxing, complete telemetry,
native artifact mapping, and failure/resume tests. A `not_applicable` gate can
satisfy a requirement; a `blocked` or missing gate cannot.

The current corpus makes all five audited resources reference/code-audit
eligible, while both benchmark task sources and all three external comparison
systems remain blocked. Supplying an approval record cannot override these
scientific and operational blockers.

## Bounded failure attribution

`attribute_failure` records only counterfactuals that the design actually
observed. A same-state success from a comparator model makes a model limit a
candidate, not a certainty. A Native Base success followed by a Full SciTaste
failure is a framework-induced regression. A sound plan that the schema or
controller cannot represent or execute is a framework limit. Missing context,
tools, resources, or environment receive their own labels. Everything else
remains unresolved.

The accepted-paper basis for the external task stack is documented in
[`research/AUTORESEARCH_ACCEPTED_EVALUATION_AUDIT_V1.md`](research/AUTORESEARCH_ACCEPTED_EVALUATION_AUDIT_V1.md),
and the paper-level protocol is in
[`ICLR_2027_EVALUATION_PLAN.md`](ICLR_2027_EVALUATION_PLAN.md).
