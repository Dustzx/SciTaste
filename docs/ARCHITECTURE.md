# Architecture

## Boundary

```text
ResearchState → candidate ResearchAction set → TasteController
      ↑                                      ↓
      └──── outcome ← ResearchExecutor ← ResearchDecision
```

SciTaste owns the state, action ranking, transition, and decision log. An executor
returns observations and artifacts but cannot select the next global action.

## Phase 0-8 components

- `schema`: stable action and decision interchange models.
- `state`: the canonical state, nonlinear transition reducer, and atomic store.
- `taste`: deterministic, training-free ranking, intrinsic calibration,
  stage-aware precedent retrieval, and budget-aware utility.
- `backends`: fixed-candidate provider-neutral contract, scripted/replay modes,
  an explicitly invoked OpenAI-compatible HTTP adapter, and a lazy local-only
  Transformers adapter for text decisions.
- `data`: separate typed Knowledge and Taste stores with source provenance.
- `discovery`: structured landscape, intuition/hypothesis lifecycle, diagnostic
  probes, problem formation, normalized ideas, portfolio selection, and
  evidence-backed ideation.
- `evidence`: claim/evidence graphs, gap analysis, information-value experiment
  planning, interpretation critic, routing, and a state-integrated workflow.
- `writing`: evidence-gated narrative, section/paragraph contracts,
  rhetorical-role taste retrieval, deterministic drafting, decomposed critics,
  and the state-integrated Communication Loop.
- `review`: structured concerns, stage-specific research obligations, action
  routing, and evidence-aware closure.
- `visual`: figure-need detection, claim-linked contracts, semantic object
  reconstruction, editable vector export, split visual criticism, and patches.
- `executor`: substrate-neutral protocol plus mock and AutoResearchClaw adapters.
- `benchmark`: evaluation-only fixed-pair suites, isolated augmentation
  conditions, robustness/transfer metrics, paired Base comparisons, and the
  matched-budget system-study planner/auditor.
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
16. A licence declaration covers explicit content scopes, not an entire mixed
    source by implication; article text requires per-record permission.
17. Externally projected Taste Cases are quarantined from retrieval until human
    verification and personal-data review are recorded.
18. An evidence-bearing review obligation cannot close from prose alone; closure
    requires new, claim-linked evidence of the requested type.
19. Writing contracts and Narrative Spine references resolve against canonical
    claim/evidence IDs before a draft is accepted.
20. Figure entities, relations, panels, and target claims resolve before export;
    a figure with unresolved critic findings cannot become the final artifact.
21. Visual patching changes named semantic objects and persists old/new field
    values; it never relies on an untraceable whole-image rewrite.
22. An external executor's zero exit code cannot advance state unless its stage
    completion and required artifacts validate.
23. SciTaste session identity is stable across upstream run-ID changes and keeps
    both upstream identifiers for audit.
24. Missing executor cost telemetry is recorded as unavailable, never assumed to
    be zero in a matched-budget comparison.
25. Benchmark labels, scripted selections, and condition-excluded context never
    enter a backend request.
26. Self-referential dogfooding cases cannot enter headline benchmark metrics.
27. Unsupported metrics are reported as unavailable rather than synthesized from
    a weaker measurement contract.
28. A system-study cell is headline-eligible only with complete budget telemetry,
    real artifacts, and condition-blinded external panel review.
29. Synthetic study records may validate the evaluator but can never become
    headline evidence.
30. Disabled competitors and unresolved model/search snapshots remain explicit
    plan metadata, never silent substitutions.
31. A local-model backend may load only an explicitly configured local path; it
    cannot download a checkpoint or silently replace the pinned model revision.
32. Study adapters run without a shell in isolated cell directories; successful
    results require complete counters and runner-hashed in-cell artifacts.
33. Pilot protocols can validate execution mechanics but can never produce
    headline-eligible evidence.
34. Formal cells may contact only the declared model endpoint; hidden novelty,
    benchmark, code-search, or generated-experiment retrieval invalidates a cell.
35. Analysis and writing consume one content-hashed, successful selected-experiment
    projection; failed or superseded attempts remain provenance but cannot define
    the scientific result.
36. A task manuscript cannot expose internal task, generator, condition, document,
    case, action, cell, stage, adapter, or framework identifiers, and it must report
    the selected primary metric before the cell can pass artifact audit.
37. A formal manuscript must preserve the complete registered seed matrix and
    descriptive dispersion, contain each required section exactly once, cite only
    frozen registered sources, and resolve every referenced local figure.
38. Publication packaging is a deterministic post-audit projection: it may render
    Markdown into a self-contained TeX/PDF bundle but cannot add scientific prose,
    citations, measurements, or model calls.

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

### ADR-011: Rights scopes and quarantine-first external taste

Status: accepted. External sources declare whether records contain metadata,
public comments, derived annotations, or article text, and a licence must cover
that exact scope. Deterministic ARIES/CASIMIR projections preserve observable
alignment or metadata without promoting them into scientific quality judgments.
External Taste Cases default to retrieval-ineligible and enter controller memory
only after explicit human verification, derivation, and personal-data checks.

### ADR-012: Reviewer feedback routes through research obligations

Status: accepted. Review is decomposed into typed concerns before the controller
selects an action. Evidence-bearing concerns transition back to the existing
Evidence Loop, and only matching new evidence can close the obligation. The
updated state then returns to Communication for a contract-preserving revision.
This prevents a missing experiment or baseline from being treated as a wording
problem.

### ADR-013: Contract-first semantic vector reconstruction

Status: accepted. Figure generation begins with a claim-linked contract and may
request a conceptual draft from an executor, but the publication artifact is
rebuilt as named semantic objects. SVG and uncompressed draw.io exports therefore
remain editable, while communication and aesthetic criticism produce object-level
patches that can be replayed and audited from `ResearchState`.

### ADR-014: Immutable substrate with contract-validating compatibility layer

Status: accepted. AutoResearchClaw remains pinned and unmodified. SciTaste checks
the public stage contracts before and after a bounded subprocess call, imports
content-hashed artifacts, derives a stable session identity from the run
directory, and advances state only after execution succeeds. Optional prompt and
token bounds are explicit experimental conditions implemented in a process-local
bootstrap; omitting them preserves the original upstream invocation.

### ADR-015: Evaluation subsystem with condition-isolated requests

Status: accepted. SciTasteBench uses the existing fixed-candidate backend
boundary but owns separate cases, condition construction, metrics, and reports.
Base sees only the decision context; each augmented condition receives only its
declared information, while Full receives all declared signals. Condition and
content changes alter the request fingerprint, preventing cross-condition replay.
The initial synthetic suite is an engineering acceptance fixture, not evidence of
model quality. Matched-budget system outcomes remain a Phase 9 protocol.

### ADR-016: Preregistered matrix before system execution

Status: accepted. Phase 9 creates the full task/condition/seed matrix from one
content-hashed protocol before any run. The protocol owns the shared base model,
search snapshot, code revision, task assets, and resource ceilings. Execution
records are imported rather than fabricated by the evaluator, and blinded panel
reviews attach through opaque IDs. Incomplete telemetry, over-budget cells,
synthetic evidence, or internal review cannot support headline comparisons.

### ADR-017: Direct local inference stays behind the backend boundary

Status: accepted. Local Transformers inference is an optional, lazy dependency
that implements the same fixed-candidate contract as hosted providers. The
checkpoint path is explicit, network download is disabled, greedy decoding is
used for repeatability, and the reported model identity includes its upstream
revision. This makes one-GPU feasibility testing possible without coupling
Transformers or Qwen internals to the controller, state, or executor layers.

### ADR-018: External systems communicate through a cell result contract

Status: accepted. Matched-system execution is subprocess-based rather than
implemented inside the evaluator. Each condition receives the same serialized
cell/task/model/search/budget request and must emit a typed result with real
resource counters, outcomes, and artifact paths. The runner owns wall/GPU
allocation measurement, process-group timeout, path containment, content hashes,
and atomic resume state. This contract applies equally to first-party conditions
and future Sibyl or AI Scientist-v2 adapters, so no external framework internals
enter SciTaste's controller or evaluation schema.

### ADR-019: Frozen task substrate with isolated system augmentation

Status: accepted. The initial formal study starts pinned, unmodified
AutoResearchClaw at hypothesis generation from one content-addressed task
synthesis and continues through peer review. Base receives the shared
snapshot, Knowledge RAG adds structured factual cards, Taste Library adds
decision precedents, and Full receives both plus a persisted `TasteController`
action. A process-local bootstrap bounds output, disables hosted-model thinking
for predictable cost, records wire usage, and suppresses upstream retrieval that
would violate the snapshot. Experiments execute for real; fixed synthetic
generators improve internal control but remain an explicit external-validity
limitation.

The registered endpoint is peer review rather than paper revision. The initial
real preacceptance showed that revision retries can exhaust the common token
ceiling after a complete draft and review already exist. A common earlier
endpoint is therefore more comparable across conditions and delegates concern
closure to the separately blinded expert panel.

### ADR-020: Selected evidence and publication language are separate contracts

Status: accepted. After iterative refinement, the study adapter selects only a
successful execution, hashes its source and stdout, retains registered metrics and
bounded per-seed evidence, and writes one authoritative evidence projection before
analysis starts. Later prompts explicitly treat earlier failed attempts as
superseded implementation history. Internal provenance identifiers remain in the
task, trace, and manifests, while analysis and manuscript stages receive
condition-blind, publication-facing terminology. Final artifact audit rejects a
successful experiment described as non-executed, a missing selected primary metric,
or any internal identifier exposed in the task manuscript. Stage 14 runs as a
separate bounded subprocess and must pass this evidence check before any paper
tokens are spent. Stages 15--16 then run as a second bounded subprocess; the
outline must preserve the registered seed design before draft tokens are spent.
Stage 17 runs separately, and its draft must pass the same evidence and
publication-language contract before Stage 18 can spend peer-review tokens. Exact
registered identifiers are deterministically replaced in prose with before/after
hashes retained in a sanitization log. The
evidence contract also distinguishes CPU synthetic simulation from neural-model
inference; the gate rejects affirmative model-result claims while allowing
explicit limitations and corrections that deny such inference. This compatibility
logic remains outside the pinned AutoResearchClaw submodule. A process-local
sandbox wrapper additionally records the exact return code, metrics, bounded raw
output, output hashes, and executed-source hashes before upstream compaction. A
successful post-repair result without this source-verified trace is inadmissible;
metrics added by the adapter's format normalizer are independently recomputed from
the traced source values rather than expected to exist in the earlier raw parser.
Publication evidence retains primary-metric seed rows and descriptive dispersion;
analysis, outline, and draft audits reject a one-run `N=1` or
`Min=Max=Mean` summary when three registered seeds were executed.

### ADR-021: Audited manuscripts receive deterministic publication bundles

Status: accepted. Generic upstream writing instructions can conflict with a
small frozen study—for example, demanding unavailable figures, dozens of
references, or a single-run statistics table. The SciTaste prompt overlay makes
the authoritative evidence contract dominant and constrains each of the three
Stage 17 calls to its assigned, non-overlapping sections. Before peer review, the
adapter rejects duplicate or missing core sections, placeholders, invented or
unregistered citations, unresolved image paths, zero-dispersion summaries, and
omission of any registered per-seed value or method-level standard deviation.

Task assets may carry structured, source-verified citation metadata. Stage 7
projects only those entries into `references.bib` and `candidates.jsonl`, keeping
the no-live-search comparison frozen and identical across conditions. The
process-local offline control also skips upstream Crossref/arXiv citation
verification, preventing a bibliography from opening an undeclared network path.
Once the
manuscript passes the evidence and publication gates, a first-party offline
renderer creates `manuscript/main.md`, `main.tex`, `references.bib`, copied figure
assets, a hashed build record, and `main.pdf` when XeLaTeX is available. This
projection performs no LLM call and leaves the pinned AutoResearchClaw submodule
unchanged.
