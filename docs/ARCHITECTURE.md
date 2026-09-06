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
- `executor`: substrate-neutral protocol, first-party native executor, explicit
  mock, and optional AutoResearchClaw compatibility/baseline adapter.
- `benchmark`: evaluation-only fixed-pair suites, isolated augmentation
  conditions, robustness/transfer metrics, paired Base comparisons, and the
  matched-budget system-study planner/auditor.
- `model_nodes`: opt-in typed semantic advice, pinned structured backends,
  exact record/replay, and project-owned pilot orchestration whose resumable
  evidence remains engineering-only until independently accepted.
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
39. A model-node pilot may resume only a content-validated contiguous case chain;
    the selected ProjectRuntime run and its final metadata must agree with the
    manifest, report, recording, and verification hashes.
40. A non-successful executor result is logged but cannot advance canonical
    `ResearchState`.
41. Installing, importing, and running SciTaste's default integrated workflow
    cannot require an external research-framework package or submodule.
42. A native action record binds its predecessor, pre-execution state, selected
    action, declared inputs, produced artifacts, and result; reusable stage
    decisions must resolve to the same record identity.
43. A native measured experiment must run from content-bound source in an
    available isolation primitive, retain bounded raw output, and derive metrics
    from validated replicate rows; a declared scenario result cannot substitute
    for failed, unavailable, or malformed execution.
44. Communication may cite a native measurement only through a self-hashed
    projection that agrees with canonical state, its interpretation review, the
    decision-bound native record, and the independently parsed replicate artifact.
    Audit drafts retain internal trace markers; publication projections remove
    those identifiers without adding scientific content.
45. A registered executable study task binds its contract, kernel, canonical
    entrypoint, exact sandbox trace, sole machine-evidence record, and downstream
    diagnostic projection. Aggregate summaries cannot erase factor effects or
    failure boundaries, and analysis or writing that negates those observations
    fails before publication.
46. A composable discovery command consumes one exact state snapshot and a
    matching validated scenario, leaves that input unchanged, and publishes a
    new state plus the hash of its command-local decision log. Direct CLI use
    cannot bypass TasteController selection, executor success, or stage
    preconditions.
47. A durable discovery operation reserves one project/run/command/input-state
    identity before execution, publishes one immutable project-relative step,
    and advances a self-hashed run head only after full verification. A stale or
    invalid admission has no side effect; recovery never re-executes an already
    complete pending step.
48. A Discovery semantic node may propose only typed content grounded in its
    registered landscape or predecessor-state evidence. Its profile, policy,
    request, response, usage, and recording are project-ledgered before use; it
    cannot choose an action, call a tool, mutate state, or silently fall back
    after rejection. The normal controller/executor path remains the sole
    transition authority, and every accepted proposal remains in one ordered,
    cumulatively budgeted semantic history.

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

ADR-028 supersedes only its product-default interpretation: the pin remains the
audited optional baseline/compatibility dependency, not SciTaste's native
execution path.

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
Base/Full reports additionally classify paired recoveries, regressions, and
shared failures. Cross-model attribution is permitted only for identical suite
hashes and seeds; it labels differential Base failures as candidates and leaves
shared failures unassigned. These diagnostics do not establish causality or
replace the matched-budget study.

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
If an initial sandbox and its repaired sandbox both return successfully, the
mutable version directory can contain only the repaired bytes. Selection is
therefore keyed by equality between the archived source hashes and each
process-local trace, not by stdout length or metric count; records from a
different successful source version cannot be merged into the selected result.
Publication evidence retains primary-metric seed rows and descriptive dispersion;
analysis, outline, and draft audits reject treating one pipeline run as
statistical `N=1`, while exact reported dispersion is checked against the three
registered seed values so a genuine zero remains admissible. If an executor
emits seed-scoped condition blocks but labels its aggregate spread over cells,
the adapter retains the aggregate mean and deterministically computes the
population standard deviation over the complete registered seed vector; it does
not relabel the differently scoped spread as cross-seed uncertainty.
Audits classify these claims line by line: an unqualified `N=1` assertion is a
contradiction, whereas an explicit statement that a perspective incorrectly or
erroneously made that claim—or an instruction not to infer or derive it—is
retained as a scientifically useful correction or constraint. The same applies
when an N=1 collapse is explicitly prohibited, forbidden, rejected, or avoided.

Generated experiments must now finish stdout with one
`SCITASTE_EVIDENCE_JSON` record. The record carries the primary metric and the
complete condition-by-seed matrix; the adapter checks numeric finiteness and
recomputes each condition mean and population standard deviation before using
it. The redundant primary field is type-checked but is not authoritative: the
registered cross-method aggregate is recomputed as the arithmetic mean of the
verified condition means and labeled as derived provenance. This prevents a
generic stdout parser—or an executor that labels one baseline as primary—from
overriding the complete matrix. Older human-readable layouts remain importable
for provenance fixtures, but new formal runs receive the machine-record
requirement in generation and every repair prompt. Publication prompts consume
a deterministic rendering of this audited matrix rather than inferring table
structure from prose formatting.

If a generated outline promises a seed table without actually containing its
rows, the adapter appends a drafting checkpoint rendered from that same audited
matrix before rerunning the consistency gate. This is deterministic evidence
materialization, not a model-generated observation or a gate waiver. Likewise,
a draft reference to a nonexistent local image is removed together with its
adjacent caption rather than replaced by a fabricated asset. Existing local
images remain intact, and remote or path-escaping targets remain inadmissible.

The code-generation prompt continues to require the flat
`SCITASTE_BENCHMARK_CONTRACT` declaration. For compatibility with upstream
review-driven regeneration, the static gate may also read a literal nested
`CONTRACT_SPEC`: it maps only the known singular factor keys, `contract_id`, and
`scoring_methods` into the canonical schema, then compares every registered
field exactly. This is a representation normalization, not a contract repair;
missing or changed seeds, factor levels, sample count, methods, metrics, or
generator identity remain fatal, and the generated source is never rewritten to
manufacture compliance.

The machine matrix and the human-readable seed coverage are deliberately checked
independently. Human rows may spell an identifier as `Seed 7`, `seed=7`, or
`seed: 7`; aggregate phrases such as `total per seed: 648` are excluded before
the observed identifier set is compared with the registered seeds. The machine
record remains the value authority, while the independent rendering check makes
omitted or misleading stdout visible.

Seed discovery is line-shaped rather than a free-text search: accepted rows
start with a seed header or with a bracketed registered condition followed by a
seed assignment. This excludes sample-count summaries such as `Total/seed: 648`
without maintaining an open-ended list of prose exceptions. A condition-first
assignment row is also accepted when it contains an explicit balanced-accuracy
measurement. Identifier matches cannot stop before a decimal point, so a factor
effect such as `seed: 0.008292` is not misread as seed zero.

AutoResearchClaw's Stage 10 can replace an initially compliant file after code
review or topic-alignment review. Those regeneration branches reuse the stage
system prompt but construct a new user prompt. SciTaste therefore repeats the
canonical literal and machine-evidence requirements in the system prompt; all
initial, repaired, and regenerated source variants receive the same immutable
contract without modifying the pinned substrate.

Synthetic-scope claim classification is also line-local and polarity-aware.
Statements that the benchmark `does not`, `do not`, or `must not` measure an
internal model signal are limitations; the same internal-confidence or attention
phrases without a negation remain contradictory neural-evaluation claims.

### ADR-021: Audited manuscripts receive deterministic publication bundles

Status: accepted. Generic upstream writing instructions can conflict with a
small frozen study—for example, demanding unavailable figures, dozens of
references, or a single-run statistics table. The SciTaste prompt overlay makes
the authoritative evidence contract dominant and constrains each of the three
Stage 17 calls to its assigned, non-overlapping sections. Before peer review, the
adapter rejects duplicate or missing core sections, placeholders, invented or
unregistered citations, unresolved image paths, evidence-inconsistent dispersion,
and omission of any registered per-seed value or method-level standard deviation.

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

### ADR-022: Bounded model nodes for semantic autonomy

Status: proposed. SciTaste may use model nodes for semantic interpretation,
candidate-action proposal, and ambiguous fixed-candidate ranking. Deterministic
code continues to own feasibility filtering, typed-schema validation, evidence
status, resource budgets, tool allowlists, execution sandboxes, and state
transitions. A model response is advice until those gates accept it.

The node infrastructure now implements review parsing, interpretation threats,
and ambiguity-triggered action ranking. Nodes are opt-in, fingerprinted,
usage-metered, recorded for exact replay, and unable to silently switch provider
or model. Rejected output remains untrusted and has no executable proposal. New
Zhipu pilots use `GLM-5.3-Flash`; local and online nodes remain separate study
conditions. The compatible live transport, versioned self-development pilot,
and ProjectRuntime-owned plan/execute/resume/status path are now implemented.
Case-boundary checkpoints bind their predecessor and exact recording, while
project registration binds the final manifest/report/verification hashes.
When both final evidence files exist but their optimistic metadata update was
interrupted, resume may revalidate and register those exact files without a model
call; a half-published pair cannot be recovered automatically.
An explicit unpriced engineering mode can contact a real endpoint while forcing
the resulting proposal to be rejected for missing cost telemetry. Its exact
request and decoded response body are stored before semantic parsing, without
authorization headers, then hash-bound to the checkpoint or archived with the
failed attempt.

The reusable `ModelNodeRuntime` extends that boundary beyond the dedicated
pilot. It separates provider generation capability, per-node admission policy,
and cumulative project budget; publishes a project/run/revision-bound intent;
and advances a contiguous predecessor ledger for accepted, rejected,
not-applicable, failed, planned, cached, and replayed outcomes. Runtime
directories and evidence are regular-file/no-symlink boundaries. The project
revision is rechecked at the backend-call boundary and after return: pre-call
staleness prevents provider access, while mid-call staleness retains known usage
but rejects the resulting proposal. Completed publication survives interrupted
pending cleanup without repeating the model call.

The first normal-workflow consumer is implemented after deterministic evidence
interpretation. It projects the actual immutable state into
`interpretation-threat`, records the typed proposal through the project ledger,
and adds self-hashed input/result bridges to the evidence `STAGE.json`. Input and
output state hashes must match, and resume verifies the complete ledger head
before reuse. Scripted mode stays offline. Live mode additionally requires a
content-bound configuration gate and explicit caller authorization.

Before provider access, the workflow publishes the exact predecessor state,
evidence state, decision log, evidence summary, invocation identity, policy and
profile. A complete recorded live response can therefore be recovered and
accounted exactly once without another provider call. An already-published
ledger entry is returned idempotently; a possibly started call with no complete
response remains unknown-cost and is not repeated. A recovered pre-ledger
proposal is rejected after project-revision drift. This closes the paid-response
interruption gate, but does not authorize state mutation or establish model
benefit.

The first Tool Intelligence slice adds a typed `tool-plan` node over Knowledge
query, Evidence inspection, and registered-run comparison plus a
`structured-repair` node for four pinned output schemas. Complete controlled
profiles, target schemas, project/state identity, argument scopes, dependency
order, and budgets are deterministically checked and replay-bound. A provider
function call is never an admitted step; a schema-valid repair is not an
accepted target-node result. Both receipts remain advisory and non-executable,
so this implements controlled semantic proposals without accepting an executor
or changing this ADR's proposed status.

The 2026-09-05 project-owned GLM-5.3-Flash probe completed seven cases and
demonstrated schema parsing, exact recording, recovery, and enforcement on a
real provider response. The live proposal still violated token, latency, cost,
and action policy, while manual-intervention measurements and independent review
were absent. ADR-022 therefore remains proposed. It does not alter the
registered Phase 9 protocol and becomes accepted only after a fresh pilot clears
the recorded schema, safety, intervention, cost, and review gates.

### ADR-023: Project directories are revisioned ownership boundaries

Status: accepted. Generated research artifacts are owned by
`outputs/projects/<project-id>/`, not by disconnected top-level command runs.
`ProjectRuntime` validates backward-compatible project/run/paper schemas, uses
file locks plus optimistic revisions for mutations, writes manifests atomically,
and refuses to replace non-symlink navigation paths. Runs and papers are
registered before explicit current selection; historical paths remain unchanged.

The serialized `ProjectSnapshot` is the read boundary for catalogs and future
generated interfaces. It exposes project-relative locators and content hashes,
not filesystem mutation or executor authority. AutoResearchClaw continues to run
behind the existing adapter and may be referenced through a project-owned run;
no project-management logic is added to the pinned substrate.

### ADR-024: Generated interfaces are evidence-bound data, not executable code

Status: accepted. A generated SciTaste surface may select only receiver-owned
native components with closed data schemas. It cannot supply HTML, JavaScript,
URLs, callbacks, commands, tool names, or executor authority. User interactions
return typed proposals to the deterministic controller boundary; no surface
event changes project or research state directly.

Every surface cites a `SnapshotBinding` whose evidence manifest is hashed and
pinned to a ProjectRuntime revision. The trusted adapter resolves locators under
one project root and hashes the current project manifest, registered runs,
current stage, paper manifests, and declared paper artifacts. Renderer-facing
documents retain the binding while omitting server-owned proposal payloads. This
decision also permits an atomic, hash-chained audit stream only after each
surface revision or proposal receipt reproduces through the server-owned
`SurfaceSession`. The stream records proposals, never execution authority. This
accepts the contract and trust boundary; it does not authorize a controller or
executor.

The first-party project surface factory now accepts only a trusted
`ProjectRuntime` plus project ID, derives the overview from that authority, and
rechecks the binding before returning. Optional publication reloads the surface,
renderer, and replayed audit root in a staging directory, then uses an atomic
Linux no-replace rename; unavailable no-replace semantics fail closed.

The first receiver-owned application implements the closed component registry in
packaged HTML/CSS/JavaScript and exposes a small authenticated `/api/v1` over a
loopback-first standard-library HTTP server. Generated text reaches only text
nodes, while CSP forbids remote or dynamic renderer resources. The browser
receives fixed-shell projection data rather than server-owned proposal payloads.
Identity-only events are checked against a freshly built authoritative surface
and appended to a project-local replayable audit epoch; their receipt still has
execution authority `none`. Non-loopback plaintext exposure requires explicit
acknowledgement and does not claim TLS protection.

The evidence workspace composes project overview, run/stage, paper/evidence,
comparison, blocker, and pending-proposal views from fresh runtime snapshots.
Inspection may read only a content-addressed artifact already exposed by the
authoritative view and renders active formats inertly. Audit replay validates
that every surface, proposal, and inspection belongs to the expected project;
directory-descriptor-bound lock, temporary-write, and atomic replacement
operations prevent a checked audit path from being redirected during mutation.
Browser project/view changes clear stale selection catalogs before fetching the
new authoritative view.

Generation as Content extends this same accepted boundary rather than adding a
second renderer. Evidence-derived quick intents and bounded free questions
produce one snapshot-bound `WorkspaceIntent`; a deterministic or optional
structured planner returns only a closed `SurfacePlan` over server-issued
candidate IDs. The fixed receiver materializes the plan from authoritative
components. Model output cannot author visible facts, code, paths, URLs, tools,
or mutations, and it is rejected on identity, schema, evidence, byte, token,
latency, tool-call, or measured-cost failure. Generated deep links name exact
admitted surfaces retained in a bounded process-local cache and fail stale after
restart or eviction rather than silently regenerating different content.

### ADR-025: Full workflow stages extend one project-owned state

Status: accepted. The offline Phase 4--7 acceptance path is composed through one
registered `ProjectRun`. Discovery creates `ResearchState`; Evidence,
Communication, reviewer-driven evidence resolution, and Figure generation load
and extend that same history. Stage scenarios may provide reusable content, but
the full-workflow config owns and revalidates the canonical project identity.

Each logical phase has a named directory and `STAGE.json`; the selected paper is
packaged and registered beneath the same project. Completion and failure both
update registered run metadata through optimistic revisions. The completion
summary is durably written before the run may register it as its completion
artifact. The final trusted UI binding is created only after project, run, paper,
and artifact registration.
Stage completion records are self-hashed and bind the predecessor state, output
state, decision log, and required artifacts. Resume may reuse only the validated
contiguous prefix. An incomplete attempt is preserved under the owning run before
rerun, while an invalid claimed completion fails closed. Paper/finalization
overwrite recovery remains an explicit manual boundary.
This ADR establishes offline orchestration and artifact ownership, not a claim
that the mock executor or scripted semantic hook measures research effectiveness.
The offline proposal-only model-node bridge is implemented; live model advice
and complete AutoResearchClaw orchestration remain later gates.

### ADR-026: Matched-study resume requires content-bound project ownership

Status: accepted. A successful status field is insufficient authority to skip an
expensive Phase 9 cell. One self-hashed run manifest binds the protocol, planned
matrix, and launcher configuration. Each current cell attempt has a self-hashed
checkpoint over its exact request, rendered command, execution record, and every
evidence file used by that record. Resume revalidates the complete identity and
artifact bytes; coordinated edits to the aggregate and cell record remain
detectable through the separately retained checkpoint.

The aggregate result is a deterministic projection of integrity-checked cell
records, not an alternative authority. Orphaned aggregate records, changed
launchers, legacy unmanifested roots, missing checkpoints, and hash drift fail
closed. Failed attempts move to a numbered project-owned archive before retry,
and a process lock prevents two runners from interleaving the same output root.

`ProjectMatchedStudyRunner` registers this evidence tree as one `ProjectRun` and
holds the optimistic project revision across the long execution. A partial
selection cannot claim matrix completion, and a concurrent project writer causes
finalization conflict rather than a latest-revision retry. This decision improves
execution provenance only; synthetic cells, incomplete matrices, and missing
external blinded reviews remain ineligible for effectiveness claims.

### ADR-027: Selected substrate actions execute from immutable project inputs

Status: accepted. A raw path passed to the AutoResearchClaw adapter is not a
project lifecycle. A project-owned substrate action therefore imports the exact
source run and executor configuration before contacting a provider, publishes a
self-hashed manifest over those inputs and the pinned upstream commit, and runs
only in a separate working tree. The unmodified upstream repository remains
code, never the writable owner of SciTaste evidence.

For new SEARCH runs, the preferred source is itself a registered project run.
The bootstrap path publishes its request identity before the call, executes only
through exact Stage 2, validates every Stage 1–2 prerequisite, and issues a
self-hashed source receipt over both work and an immutable reusable copy. The
selected Stage 3 action binds that receipt and revalidates it before importing
the source. External source paths remain a compatibility boundary, not the
default ownership model. A successful executor result persisted before a local
finalization interruption may be recovered without another provider request.

A successful process exit is insufficient. The adapter requires fresh terminal
checkpoint and summary evidence for the exact selected stage, rejects escaping
or symbolic-link artifacts, validates cost records, and charges only the staged
increment over the imported cumulative cost. Timeout evidence remains available
for audit. Completion or failure is then bound to a self-hashed verification
record and registered through `ProjectRuntime`.

Live calls require both a versioned `live_enabled` setting and explicit caller
authorization. Resume is limited to failed runs with identical project, action,
seed, provider/model, workflow configuration, executor configuration, immutable
input hash, and substrate pin; prior mutable attempts are archived. This accepts
an online engineering lifecycle for the Stage 1–2 prerequisite and one selected
Stage 3 action. It is not yet a full Stage 1–18 orchestration path or evidence of
research-effectiveness gain.

### ADR-028: SciTaste native execution is the product default

Status: accepted for the execution boundary; capability parity is in progress.

SciTaste is an independent system, not an AutoResearchClaw plugin or wrapper.
The default integrated path uses the first-party `SciTasteNativeExecutor` and
must install, import, test, and run without the AutoResearchClaw package or Git
submodule. The pinned upstream remains unmodified and available only through
explicit `baseline` and `substrate` commands for reproducible comparison,
compatibility, and controlled ablations.

The first native slice covers the existing deterministic Phase 4--7 workflow
components behind one shared typed execution boundary. It preserves declared
scenario observations, emits no synthetic mock observation, records its
capability and result basis, and prevents failed/planned/skipped execution from
advancing state. This is an architectural independence gate, not an assertion of
open-ended autonomy or superiority.

The first non-receipt capability is now implemented for local Knowledge
retrieval. Full Workflow materializes a content-bound library inside its owning
run, executes the selected search, records ranked documents and measured wall
time, and binds every native action through a self-hashed predecessor chain.
Reusable stage decisions revalidate the corresponding action and result record.
This closes local retrieval provenance, not open-web search or experimental
execution.

The second non-receipt capability is registered CPU experiment execution.
Bubblewrap supplies separate mount, user, PID, network, IPC, UTS, and cgroup
namespaces; the fixed Python invocation is not routed through a shell and has no
host-project mount, GPU, or writable working filesystem and receives hard resource
ceilings. Exact source,
stdout, stderr, limits, return status, and independently parsed replicate metrics
are retained beneath the owning run and bound by the same action chain. Evidence
Workflow consumes this measured result instead of its scenario fixture. Missing
isolation, non-zero exit, timeout, output overflow, malformed records, and absent
primary metrics fail closed. This accepts a registered offline CPU execution
boundary, not autonomous code generation, arbitrary dependencies, GPU workloads,
or an effectiveness claim.

Native capability parity will replace scenario-bound operations incrementally:
rights-aware retrieval, code generation/admission, broader execution profiles,
evidence analysis, manuscript generation, and figure production. Each handler
must emit content-addressed artifacts and measured resource telemetry under the
existing project/state contracts. Whole-source copying from AutoResearchClaw is
rejected: it would obscure provenance, preserve the fixed-pipeline coupling, and
make SciTaste's own execution semantics harder to audit.

Phase 9 therefore separates two questions. Component ablations may keep one
fixed execution base to estimate the contribution of Knowledge RAG and Taste;
independent-system comparison evaluates SciTaste Native against
AutoResearchClaw and other pinned systems only after capability and budget
contracts are aligned. SciTaste may claim architectural independence now, but
may claim better research outcomes only after complete matched runs and blinded
external review.

### ADR-029: Local system studies use a bounded loopback model transport

Status: accepted for transport and failure evidence; full-cell feasibility is
not accepted.

The Phase 9 local pilot keeps the registered system adapter intact and supplies
its model dependency through a SciTaste-owned OpenAI-compatible bridge to one
explicit local Transformers checkpoint. The bridge binds only to loopback,
requires an ephemeral bearer, accepts a closed non-streaming message schema,
pins model aliases, limits request bytes/context/output, serializes inference,
and never logs request content. The wrapper verifies both the model
configuration and a complete names/sizes/bytes checkpoint digest before loading
weights, then reports local API cost as zero without discarding token usage.

This boundary is model transport, not a new research-system condition and not
an internalization of AutoResearchClaw. It allows the unchanged baseline stages
to be measured locally while SciTaste Native continues to replace its own
product-default capabilities under ADR-028.

One real RTX 3090 diagnosis/base run completed hypothesis generation and
experiment design but exhausted the 20,000-token pilot allowance before the
next code-generation request. The failed child retained exact usage, revealing
that the outer runner formerly discarded valid counters solely because the
process exited non-zero. The runner now parses a present result on every exit:
a schema-valid failed result preserves its evidence class and counters, whereas
a non-zero result claiming success is forcibly failed and loses its claimed
outcome/artifacts. Historical records are never rewritten. The local transport
is therefore admitted, but budget revision and a complete Stage 8--18 run remain
required before operational acceptance.

### ADR-030: Executable study diagnostics remain authoritative through publication

Status: accepted for evidence integrity; complete local-cell operational
acceptance requires a clean Stage 8--18 run.

The frozen task brief alone was insufficient for local small-model execution:
generated code could preserve the apparent contract while never calling a real
benchmark, or a generic code reviewer could rewrite the registered entrypoint.
Executable tasks may therefore declare one repository-relative asset by path,
SHA-256 digest, module, and entrypoint. The adapter copies that exact kernel and
a condition-invariant canonical runner into Stage 7, injects them process-locally
at code extraction and sandbox execution, and rejects any selected source whose
bytes, call site, main guard, contract, or source-verified execution trace differ.
No change is made inside the pinned AutoResearchClaw submodule.

The executable emits exactly one compact machine-evidence record. SciTaste
validates its registered condition/seed matrix, descriptive dispersion, packet
counts, factor levels, factor-effect ranges, failure threshold, reproduction
minimum, boundary counts, and reported boundary cells before projecting them
into analysis or writing. The internal record may retain kernel identifiers for
audit, while its publication projection uses reader-facing method and factor
names. Downstream prompts receive both the per-seed matrix and registered
diagnostics; deterministic checkpoints materialize missing evidence but do not
invent or revise prose.

Generic upstream warnings and debate perspectives remain useful criticism, not
evidence authority. A manuscript may describe limits of the registered grid,
but cannot turn untested additional levels into a claim that executed levels
were absent, flatten three seeds into statistical N=1, attribute synthetic rules
to neural-model internals, or deny an observed boundary. Those contradictions
fail at analysis, outline, and draft gates. Historical failed runs remain
immutable evidence of each exposed boundary defect and cannot be promoted after
the implementation changes.

### ADR-031: Discovery operations are immutable state transformations

Status: accepted for the deterministic native Discovery Loop.

The Phase 4 domain objects were complete before every required public operation
was usable: `hypothesize`, `probe`, `reformulate`, `ideate`, and
`portfolio select` still returned a reserved-command response. Treating the
monolithic `discover` demonstration as sufficient hid this product boundary.

Each operation now accepts the same validated `DiscoveryScenario`; all but the
initial hypothesis operation consume one exact `ResearchState`. Scenario and
state project identity, direction, domain, venue, stage, and operation-specific
preconditions are checked before execution. The existing TasteController still
ranks candidates, the selected action must succeed through ResearchExecutor,
and the transition reducer appends the canonical decision and state transition.
`probe` records support, contradiction, or inconclusive evidence and retains the
corresponding validate or re-probe decision; contradictions must be explicitly
carried into `reformulate` rather than silently rewritten.

No operation edits its input or appends into an ambiguous shared directory. It
publishes a new output tree containing the resulting state, its immutable
content-addressed snapshot, only the command-local decisions, and a receipt that
binds the canonical scenario digest, input/output state identities, decision and
executor-result identifiers, and decision-log SHA-256. Existing destinations
fail closed. The full `discover` command remains a convenience macro over the
same scientific semantics, not a second Idea-First or Evidence-First pipeline.

This acceptance is deliberately scoped to registered deterministic scenarios
and the mock executor. It removes public CLI placeholders and establishes a
composable provenance contract; open-ended retrieval, model-generated
hypotheses, and independently evaluated research quality remain later native
capability gates under ADR-028.

### ADR-032: Composable Discovery is owned by one recoverable project run

Status: accepted for deterministic native Discovery integration.

Standalone immutable command directories prove local state transformation but
do not establish durable project ownership: callers can scatter outputs, supply
the wrong predecessor, or race while registering the result afterward. Making
the monolithic Full Workflow the only owner would instead remove the explicit,
nonlinear interaction required by the Discovery Loop.

`ProjectDiscoveryWorkflow` therefore derives both predecessor and destination
from one `ProjectRuntime` run. Before execution, it validates scenario/project/
run/seed identity and reserves the command, ordinal, input state, operation
token, and project revision. After execution, it admits a step only when the
portable receipt, immutable snapshot, command-local decisions, executor-result
references, and complete state decision/transition prefix agree. A self-hashed
`DISCOVERY.json` provides the current head while historical step directories
remain immutable. The registered run stores that head hash and only becomes
complete after `portfolio-select` reaches `PILOT`.

Failure before step publication keeps the prior state and requires explicit
resume. Failure after a complete atomic step publication is distinguishable: a
resume reconstructs or verifies the pending head and commits project metadata
without another executor call. Per-run locking and optimistic project revisions
prevent two API workers from silently advancing the same run. This decision is
an ownership and recovery result for deterministic scenarios, not evidence of
open-ended autonomy, model quality, or scientific effectiveness.

### ADR-033: Adaptive Discovery content is proposal-only and project-ledgered

Status: accepted for bounded hypothesis, reformulation, and ideation content.

Fixed scenario seeds make the native loop reproducible, but they do not let the
system synthesize a new intuition or hypothesis from a registered landscape.
Calling a model before run reservation would solve the prose problem by creating
a larger provenance and accounting problem: provider cost, interrupted results,
and the content entering state would not share one recoverable identity.

`discovery-hypothesis` is therefore a domain extension of the durable model-node
runtime. The runtime accepts an additive typed registry while prohibiting
replacement of built-in nodes. The request contains project-derived research
identity, at most forty landscape findings, their exact source identifiers, and
a closed probe-type list. The response contains an intuition, one falsifiable
working hypothesis, alternatives, and uncertainty—no action, state, budget, or
executable tool field. Deterministic validation rejects unknown sources, probe
types, duplicate predictions, excess content, provider tool calls, or missing
cost telemetry.

The project reserves `hypothesize` before the model call. An accepted response is
recorded in the run's hash-chained model ledger and then referenced by the
Discovery command receipt, manifest step, and state executor context. The normal
TasteController still selects the three actions and ResearchExecutor must succeed
before publication. Semantic rejection publishes no Discovery state; a completed
response is reused after downstream interruption, and binding drift on resume is
rejected. The API cost is reflected in canonical resource usage.

This establishes adaptive, recoverable content generation—not open-ended
retrieval, direct tool autonomy, or scientific effectiveness. Those require
separate registered handlers and matched evidence.

The same decision applies after evidence changes. `discovery-reformulation`
receives one predecessor hypothesis and at most forty registered observations,
requires at least one contradiction linked to that parent, and must cite the
contradiction in its revised hypothesis proposal. The project assigns a stable
command-derived invocation identity, appends the accepted reference to state,
and checks cumulative scenario cost before reservation and after telemetry. The
controller still selects `REFORMULATE_HYPOTHESIS`; the provider cannot discard
the parent, erase its contradictory observation, or advance state.

After a reproducible observation supports the active hypothesis,
`discovery-ideation` may propose one problem and three to eight divergent idea
seeds. The input is the exact active hypothesis, registered observations,
research identity, and project resource ceilings. Deterministic admission
rejects unknown evidence or hypothesis identities, duplicate generators,
hypotheses, mechanisms, or validation steps, unsupported/negative/unbounded
cost and value fields, and any per-idea estimate above the project budget. The
response deliberately has no preferred idea, ranking, actual budget assignment,
action, tool, state, or execution field. Problem formation and idea generation
therefore consume bounded semantic content, while the TasteController remains
the sole portfolio selector.

Semantic configuration is also part of identity. Non-secret backend
configuration—including scripted response fixtures—is hashed into the binding,
while a backend factory maps that bound configuration to the actual
command-derived invocation ID. This avoids treating provider/model names alone
as sufficient replay identity.

### ADR-034: Discovery retrieval is planned before semantics and executed under controller authority

Status: accepted for bounded project-owned Knowledge retrieval.

Scenario-authored findings make a Discovery run deterministic, but they do not
prove that the first hypothesis was grounded in an executed retrieval. Letting a
model search directly would invert SciTaste's authority boundary: provider tool
behavior could change the evidence set, spend resources, or make a different
request during resume before the controller had selected an action.

An opted-in `DiscoveryKnowledgeBinding` therefore loads a strict local corpus
and deterministically ranks it during admission. After the project reserves the
operation, SciTaste copies the complete corpus and a self-hashed retrieval plan
into the run. A bounded hypothesis node may see the resulting landscape
projections, but only as content evidence. The normal TasteController still
selects `SEARCH`; `SciTasteNativeExecutor` performs it against the copied
KnowledgeLibrary and must reproduce the plan's document identities and scores.
The provider cannot change the query, call the executor, or advance state.

The reference persists in every successor state, and its source-config
fingerprint is required for every command and resume. Independent verification
rehashes the copied records and plan, reruns ranking, checks the native
predecessor chain, and reconciles each decision with its pre-state, action,
result, and execution record. A fully published pending step is finalized
without another retrieval. Records from a truthful partial attempt stay in the
append-only chain; registered metadata identifies the committed prefix rather
than erasing failure evidence.

This decision establishes deterministic local evidence acquisition for one
registered corpus. It does not claim open-web retrieval, provider tool autonomy,
automatic corpus curation, or improved scientific quality. Those remain
separate capability and evaluation gates.
