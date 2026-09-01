# Architecture

## Boundary

```text
ResearchState → candidate ResearchAction set → TasteController
      ↑                                      ↓
      └──── outcome ← ResearchExecutor ← ResearchDecision
```

SciTaste owns the state, action ranking, transition, and decision log. An executor
returns observations and artifacts but cannot select the next global action.

## Phase 0-5 components

- `schema`: stable action and decision interchange models.
- `state`: the canonical state, nonlinear transition reducer, and atomic store.
- `taste`: deterministic, training-free ranking, intrinsic calibration,
  stage-aware precedent retrieval, and budget-aware utility.
- `backends`: fixed-candidate provider-neutral contract, scripted/replay modes,
  and an explicitly invoked OpenAI-compatible HTTP adapter.
- `data`: separate typed Knowledge and Taste stores with source provenance.
- `discovery`: structured landscape, intuition/hypothesis lifecycle, diagnostic
  probes, problem formation, normalized ideas, portfolio selection, and
  evidence-backed ideation.
- `evidence`: claim/evidence graphs, gap analysis, information-value experiment
  planning, interpretation critic, routing, and a state-integrated workflow.
- `executor`: substrate-neutral protocol plus mock and AutoResearchClaw adapters.
- `cli`: thin composition root; domain behavior stays in the packages above.

## Invariants

1. Every selected action belongs to the supplied candidate set.
2. Every transition references a logged decision.
3. State revisions increase monotonically.
4. State snapshots are content-addressed and atomically replaced.
5. Ties are deterministic for a fixed seed.
6. `STOP` is the only action that completes a project.
7. Backend-specific details do not enter taste utility or state schemas.
8. Intrinsic calibration performs no retrieval; augmented decisions log every
   retrieved taste-case identifier.
9. Knowledge documents cannot be inserted into the Taste store, and taste cases
   cannot be inserted into the Knowledge store.
10. Live backends read secrets from environment variables and are never selected
    implicitly or by test fallback.
11. Idea-First and Evidence-First are post-hoc trajectory descriptions; no mode
    switch selects a separate discovery pipeline.
12. Applying a decision deep-copies state, so domain updates reacquire objects
    from the new state rather than mutating stale pre-transition references.
13. Raw results, observations, interpretations, and claims are separate records;
    a metric improvement never directly promotes a claim.
14. Budget feasibility uses cumulative consumption, not each action against the
    original total in isolation.
15. External ingestion is local-only and license-deny-by-default; raw corpora are
    outside Git.

## Architecture decision records

### ADR-001: Pydantic JSON models

Status: accepted. Persistent and boundary-crossing models use Pydantic v2 for
validation and forward-compatible JSON serialization.

### ADR-002: Reducer-style transitions

Status: accepted. `apply_transition` returns a deep copy rather than mutating the
input, making replay and rollback predictable.

### ADR-003: Pinned substrate submodule

Status: accepted. AutoResearchClaw is pinned at v0.5.0 (`12d3fd8`) and loaded
lazily through an adapter. SciTaste remains importable and testable without
installing the substrate package.

### ADR-004: Deterministic controller before LLM controller

Status: accepted. Phase 1 uses explicit utility reasoning and stable tie-breaking.
Phase 2 can add fixed-prompt backends without changing the controller contract.

### ADR-005: Exact recording/replay before live-provider dependence

Status: accepted. A live request is fingerprinted from its complete fixed
candidate contract and can be recorded once, then replayed only when the request
matches exactly. Offline development therefore remains possible without silently
changing the experimental condition.

### ADR-006: Knowledge and taste are different data products

Status: accepted. Factual documents and decision precedents use different schemas,
files, retrieval queries, and runtime type checks. Taste cases preserve the source,
the rejected alternatives, and the reason one action was preferable.

### ADR-007: One adaptive discovery loop

Status: accepted. Both weak and strong starting beliefs enter the same
Hypothesis-Probe-Reformulate engine. Evidence strength, probe stability, and
contradiction determine whether another probe or reformulation occurs. A stable
contradiction remains an observation and is eligible to seed a new problem.

### ADR-008: Strict live schemas with bounded semantic repair

Status: accepted. Transport retries cover transient HTTP failures. Separately, a
schema-incomplete model response receives a bounded format-repair retry against
the same provider and model. The backend never silently falls back to another
experimental condition.

### ADR-009: Evidence status is derived and validity-gated

Status: accepted. Claim status is recomputed from typed evidence relations,
coverage, reliability, and stated strength. Stable contradiction routes to
`PIVOT`; unresolved validity threats route to `REPRODUCE`. Evidence plans include
anti-confirmation-bias controls before execution.

### ADR-010: License-gated local corpus ingestion

Status: accepted. SciTaste does not download Phase 3 corpora. A local manifest
must explicitly classify each source's license; unknown/restricted records are
rejected, and a permitted declaration requires an identifier and terms locator.
Knowledge and Taste records remain separately normalized, deduplicated, and
stored.
