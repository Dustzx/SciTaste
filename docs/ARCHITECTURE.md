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
  rhetorical-role taste retrieval, content-bound venue/archetype profiles,
  deterministic drafting, decomposed critics, and the state-integrated
  Communication Loop.
- `review`: structured concerns, stage-specific research obligations, action
  routing, and evidence-aware closure.
- `visual`: figure-need detection, claim-linked contracts, semantic object
  reconstruction, editable vector export, split visual criticism, and patches.
- `executor`: substrate-neutral protocol, first-party native executor, explicit
  mock, and optional AutoResearchClaw compatibility/baseline adapter.
- `benchmark`: evaluation-only fixed-pair suites, isolated augmentation
  conditions, robustness/transfer metrics, paired Base comparisons, and the
  matched-budget system-study planner/auditor.
- `evaluation`: typed recursive project, task, framework, comparison,
  statistical, approval, external-resource corpus/admission, and bounded
  failure-attribution contracts for external AutoResearch studies.
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
49. Venue Writing Taste is a content-bound advisory context, not a submission
    gate or acceptance predictor. Venue guidance cannot override scientific
    integrity, claim calibration, or scope; paper-archetype overlays may select
    appropriate evidence duties but cannot impose universal figure, table,
    experiment, or ablation quotas. Mechanical template compliance remains an
    independent deterministic contract.
50. Self-development is process evidence only. Every broad external-system
    superiority claim uses held-out child projects, SciTaste plus at least two
    real independent external systems in the same matched block, evidence-bound
    papers, frozen statistics, and an approval record over the exact design
    hash. Feedback after launch creates a new protocol version.
51. A title-level Scientific Taste claim is admitted only by a complete
    within-SciTaste matched causal contract containing no-Taste, component, and
    mismatched-Taste contrasts. Best-native external outcomes are always
    descriptive and model-confounded. Valid preregistered execution failures
    remain outcomes; missing or invalid records block the contract.

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
The read-only matrix-status projection may discover multiple project-owned
aggregates, but protocol identity is exact rather than name-based. It counts a
record only after the run manifest, cell checkpoint, request, aggregate/owned
record, and all checkpoint evidence bytes revalidate. Historical protocol
revisions stay visible as foreign sources, while conflicting exact-identity
records are excluded instead of selected by recency.

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

The integrated v3 boundary extends the single-step executor into a durable
project-owned loop. Content-addressed run files construct only the three reviewed
read-only handlers. A project/run lock, exclusive action claim, write-once
start/result/observation records, decision envelope, and predecessor-bound ledger
support exact recovery while rejecting symlink escape, content drift, stale
project or research state, and ambiguous non-replay-safe calls. The semantic
hotspot bridge may return accepted advice, rejection, bounded re-plan, or human
escalation, but it still cannot admit evidence or authorize a state transition.

A preregistered 12-task, three-seed internal GLM-5.3-Flash comparison exercises
that complete bridge and retains provider usage, price, latency, tool, blind
packet, and runtime-verification evidence below one ignored project run. Its
typed report fixes the scientific claim to false, even after a blind review is
returned. The current preliminary routing signal does not accept ADR-022;
independent review, main-workflow trigger policy, broader tasks, and external
replication remain distinct gates.

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
`SurfaceSession`. The initial stream records proposals with no execution
authority. This accepts the surface contract and trust boundary; the factory
itself does not authorize a controller or executor.

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

The application now implements the deterministic controller boundary without
turning it into an executor. One identity-only approval/rejection request must
resolve to an already audited proposal on the exact current surface and snapshot.
Its append-only result grants only the proposal kind's registered read-only or
approved-handoff boundary and always fixes state-mutation authority to false.
Duplicate requests and a second decision for one proposal fail closed. Pending
views subtract controlled receipts only after complete audit replay.

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

A registered `autoresearch-evaluation-landscape-v1` through `v4` projection adds Research
Synthesis Taste to this boundary. The receiver turns one content-addressed
literature artifact into a lifecycle matrix, separated evaluation lenses,
comparison-readiness lanes, and a protocol-gate rail. The policy controls visual
hierarchy, compression, and progressive disclosure without rewriting evidence.
The v4 contract independently records archival publication status, headline or
sensitivity eligibility, and adapter readiness; it requires at least two
accepted external headline candidates and forbids preprint-only systems from
silently occupying that lane. Its `hold` state can guide the next no-run design work but cannot freeze a
protocol or grant download, model, GPU, human-study, or execution authority.

Its evaluation layer is also data-only. Fingerprinted reports may compare the
number of fixed source views represented in one generated composition and record
environment-bound local latency. A dependency-free Chromium probe observes
focus, reflow, minimum target dimensions, locale network activity, and runtime
errors. These records deliberately contain no human-outcome field and cannot be
interpreted as task success, workload, comprehension, preference, usability, or
scientific effectiveness; those require the separate counterbalanced study.

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
rerun, while an invalid claimed completion fails closed. A separate write-once
finalization plan now verifies or safely archives incomplete paper/summary work
without overwriting a registered bundle.
This ADR establishes offline orchestration and artifact ownership, not a claim
that the mock executor or scripted semantic hook measures research effectiveness.
Proposal-only evidence advice, source generation, and bounded Tool Intelligence
now compose through one typed ledger. A deterministic post-evidence hotspot may
issue one registered read-only tool lease; its observation remains non-canonical
and cannot advance state. Live conditions remain double-gated engineering
probes, and complete AutoResearchClaw orchestration is an optional comparison
gate rather than a native product dependency.

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

Cross-run status is a read-only projection over those same authorities, not a
second resume mechanism. Its next execution batch is the first incomplete
task/seed/repetition block so operational scheduling retains the matched
four-condition structure. It cannot import a predecessor protocol cell, repair
an invalid checkpoint, launch a provider, or manufacture an external review.

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

### ADR-035: A durable selected-action result is a no-repeat recovery boundary

Status: accepted for the project-owned AutoResearchClaw compatibility path.

The selected-action wrapper already publishes an external executor result before
appending the controller decision or updating canonical state. Re-running the
provider after a crash in that interval would spend twice and could replace a
known successful outcome with a different one. Treating any partially populated
directory as reusable, however, would allow an unverified checkpoint or artifact
to acquire completion authority.

Each live run is serialized by an owned non-blocking run lock. Before a selected
action call, SciTaste publishes a content-addressed state snapshot and immutable
invocation that binds the action, original decision intent, project manifest,
and run directory. The durable result binds that invocation. Both bootstrap and
selected-action results record a versioned normalization of the complete work
tree, not only the files named by the current stage contract.

Explicit resume therefore distinguishes three cases. A recorded failed result
may be archived only after its executor, action, command, pin, return code or
timeout, failure reason, costs, and current normalized work tree all revalidate.
A recorded successful result is never called again: the adapter verifies the
same evidence plus the invocation and exact decision/state replay before final
registration. A hard-crashed `running` run enters this path only when such a
successful result exists. Missing, changed, malformed, or contradictory evidence
is an ambiguous external outcome and blocks automatic retry.

Recovery does not make AutoResearchClaw part of SciTaste's default runtime and
does not convert Stage 1--3 engineering evidence into a scientific-effectiveness
claim. It closes an accounting and provenance gap in the optional compatibility
adapter while the first-party native path remains the product default.

### ADR-036: External-call phase evidence separates safe preparation from unknown execution

Status: accepted for project-owned AutoResearchClaw bootstrap and selected actions.

An invocation and a terminal result close the most expensive recovery window,
but two materially different interruptions previously looked identical: a crash
after local preparation but before the executor boundary, and a crash after the
external call began but before a result was retained. Retrying the first is safe;
retrying the second can duplicate cost and nondeterministic work. A mutable phase
flag cannot be authoritative because it can be overwritten or advance without
its predecessor evidence.

Every new external attempt therefore owns three write-once, self-hashed,
predecessor-linked records: `prepared`, `call_started`, and `result_published`.
The stable identity contains project/run, a dedicated external-attempt number,
the invocation or bootstrap-manifest hash, an exact non-secret call-spec hash,
and the full pre-call work fingerprint. The start record is published after the
last local preflight. The returned `ExecutionResult` binds that start record;
the terminal phase also binds the exact result file, result ID/status, and full
post-call work fingerprint. File and directory entries are fsynced before later
authority is published.

Recovery treats the phase files as truth and ProjectRun fields only as a cache.
A cache may lag a valid chain and is repaired during normal finalization; it may
not lead or contradict the chain. A sole valid prepared record reuses the
original decision/invocation and can cross the call boundary once. A start with
no valid result remains blocked. A valid result written before its final phase
record is independently revalidated before that record is completed. Success
never calls again. Failure must independently reproduce its command, pin,
terminal evidence, error, cost, and full work tree before archive; only the next
provider attempt increments `external_call_attempt`. Metadata-only resumes
increment `resume_attempt` but not the external counter.

Manifest `1.2` declares phase-v1. Manifest `1.1` stays readable as a phase-less
legacy contract: exact results retain their existing recovery behavior, while
missing results remain ambiguous and no synthetic phase history is created.
Manifest `1.0` interrupted and failed runs remain read-only. This protocol does
not claim distributed exactly-once execution: the interval after `call_started`
and before a durable result is inherently unknowable without a provider-side
idempotency key. Descriptor-relative storage and crash-safe failed-attempt
rollover remain separate hardening work.

### ADR-037: Native source is proposal-only until deterministic admission

Status: accepted for registered and bounded provider-produced CPU source.

The isolation runner previously accepted only a registered source definition.
That kept execution real and bounded, but it offered no explicit boundary for
source proposed by a future semantic node. Allowing a model response to become a
file or command directly would merge content generation, policy, filesystem
mutation, and execution authority into one unauditable step.

SciTaste now separates those roles. A strict external proposal declares exact
source, experiment identity, expected metrics, rationale, runtime limits, and
registered or model-attributed provenance. Model attribution requires provider,
model, request hash, and response hash, but this component neither performs nor
independently verifies that provider call. A versioned deterministic policy may
restrict—but cannot expand—the platform import ceiling. AST admission rejects
unbounded or malformed source, disallowed/private imports and attributes,
dynamic execution/file builtins, dunder access, authority-expanding syntax, and
missing measurement literals.

One actual run publishes policy, proposal, admission, and root context records
atomically beneath `native_execution/context/code/`. Both semantic record hashes
and exact serialized bytes are bound. The original proposal is always retained;
only acceptance creates a byte-identical `admitted/experiment.py`. Rejection
fails the run before workflow stages while remaining inspectable. Resume
revalidates the external binding and every owned byte rather than re-admitting a
different source.

Acceptance upgrades the runner definition to schema `1.1` and carries the
proposal's complete expected metric set into runtime parsing. Replicates must
report exactly that set, closing the gap between a statically mentioned metric
and the values actually emitted by the isolated process. Legacy registered
definition `1.0` remains readable without this additive contract.

Static admission is defense in depth, not containment and not evidence that an
experiment is scientifically meaningful. Accepted source must still pass the
Bubblewrap availability probe, namespace/resource limits, exact output capture,
replicate schema, and independently derived metric checks. A provider-backed
proposer supplies that missing evidence through ADR-038 while remaining outside
the admission and execution authority described here.

### ADR-038: Provider-produced source crosses two independent gates

Status: accepted for one bounded Full Workflow CPU-experiment hook.

Model-produced code is materially different from ordinary semantic advice: even
a schema-valid response can contain invalid Python or an unsafe program. It also
creates an expensive recovery boundary before a source file exists. Treating the
model-node acceptance result as execution permission would collapse generation,
policy, filesystem publication, and process authority into a single model
decision.

SciTaste therefore registers `native-code-proposal` as an additive project-owned
model-node type without changing the built-in model-node registry. Its trusted
input fixes the objective, constraints, experiment identity, expected metric
set, runtime limits, and non-expandable admission policy. Its output contains
only UTF-8 source, a bounded rationale, and bounded assumptions. It has no path,
command, dependency, tool, action, budget, policy, metric, experiment identity,
state transition, or execution field. The provider profile and node policy both
deny tools and actions; a separate caller switch is required for live access.

Before provider access, the owning run writes a self-hashed generation-input
checkpoint containing the original project revision, stable invocation ID,
workflow/config/profile/policy bindings, and exact typed generation brief. The
existing model runtime then retains the fingerprinted request, exact decoded raw
response and hash, provider-returned model identity, token/latency/cost evidence,
recording hash, and chained ledger result. An interruption after a complete live
recording consumes that recording during resume; a possibly started call without
a complete response records unknown cost and is not repeated automatically.

Only an accepted, cost-admitted model result may be deterministically projected
into `generated.py` and a model-attributed proposal config. That projection binds
the request fingerprint and raw-response hash and is atomically published below
`native_execution/context/code_generation/result/`. It remains
`proposal_only=true` and `executable=false`. The independent ADR-037 AST gate
then retains the exact proposed bytes and creates an admitted path only on
acceptance. The ADR-019 Bubblewrap runner executes only that byte-identical
admitted path. Full Workflow rechecks the generation configuration at
finalization and reports generation telemetry separately from code admission and
native execution.

Offline scripted acceptance proves orchestration, evidence closure, rejection,
recovery, and isolation—not model quality. A real GLM-5.3-Flash engineering probe
returned a structured proposal and exact usage, but the provider's public pricing
evidence did not yet cover that model. The runtime consequently rejected the
response for unknown cost before source materialization; independent inspection
also found invalid Python. This negative result is retained rather than repaired
or executed because that historical probe did not configure the later repair
contract. Priced provider acceptance, live repair quality, runtime-failure repair,
and scientific-effectiveness comparison remain separate gates.

### ADR-039: Open research questions enter through a deterministic launch admission

Status: accepted for registered-scenario Full Workflow intake.

Full Workflow previously owned stage execution and finalization but began from
four externally referenced scenario fixtures. Adding only a free-text `question`
field would not close that gap: the executable budget and evidence requirements
could still diverge from the user's intent, while the run would not own the
inputs that determined its trajectory.

An optional strict `ResearchBrief` now declares the question, objective, project
identity, exact Discovery budget, required evidence types, success criteria,
constraints, and prohibited claims. Before any project mutation, deterministic
inspection loads every registered scenario, verifies identity/budget/evidence
closure, hashes five inputs, and creates a self-hashed `WorkflowLaunchPlan` bound
to the complete workflow configuration and run identity. Dry-run exposes that
same plan without writing output.

A formal run atomically copies the brief and four scenarios into `intake/`, then
all stages consume those project-owned copies. Resume may complete a missing copy
or plan only if every existing artifact still has its admitted content; completed
run repair only verifies and never backfills intake. Both the registered run and
final summary retain the brief and plan identities.

Two accepted planner modes retain deterministic execution authority. The direct
`deterministic-registered-inputs-v1` mode binds four caller-selected scenarios.
The committed open-question path uses
`deterministic-catalog-selection-v1`: a content-bound registry supplies complete
four-stage bundles, which are filtered before mutation by exact target domain,
Discovery budget, brief-authorized evidence types, and bounded keyword matches,
then ranked by match count and stable bundle ID. The exact catalog and selected
scenario bytes become run-owned inputs and are rechecked on resume.

Models retain `proposal-only` authority and cannot change budgets, authorize
evidence, select arbitrary execution, or mark a plan ready. Catalog selection is
more autonomous than caller-supplied paths but remains a closed registered-action
policy, not open-ended scenario synthesis. Model-grounded scenario generation,
research-quality comparison, and external review are separate later gates and
must not be inferred from a ready launch plan.

### ADR-040: Writing Taste is hierarchical and integrity-first

Status: accepted for deterministic assessment, precedent retrieval, and bounded
semantic advice.

Treating Writing Taste as a banned-word list or a single paper score collapses
different decisions and can turn persuasive editing into selective reporting.
SciTaste therefore separates twelve dimensions across paper, section, paragraph,
sentence, and phrase levels. Scientific integrity, claim calibration, and scope
precede narrative focus and anti-defensive style. A material limitation that
changes validity, interpretation, safety, ethics, or reproducibility remains in
scope even when it weakens the preferred story.

Writing Taste Cases add level, section, transition, claim-strength,
citation-density, dimension, and style metadata to the existing provenance
record. The `WRITING_DECISION` policy scores those fields alongside context,
venue, and rhetorical role. External style methods enter only as human-curated,
licensed precedents with an exact source and derivation method; they do not gain
policy authority.

A deterministic assessment reports observable antipatterns without claiming
scientific quality. The optional `writing-taste` model-node extension reviews
semantic strategy from a closed set of manuscript sections, claim IDs, evidence
IDs, headline candidates, and material limitations. Its output is typed advice.
Admission rejects manuscript drift, unknown references, incomplete section
orders, missing limitations, and attempts to demote a material limitation. The
node has no file mutation, evidence admission, tool, action, or execution field.
Evidence gaps continue through the Evidence Loop; prose alone cannot close them.

### ADR-041: Native source repair is one conditional proposal, not an iterative executor

Status: accepted for deterministic static-admission failures.

Silently rewriting rejected generated code would destroy negative evidence, while
an unrestricted retry loop could spend an unbounded budget and gradually escape
the reviewed task. SciTaste therefore permits one optional `native-code-repair`
invocation only when ADR-037 static admission has already produced a content-bound
rejection. An accepted first proposal creates no repair checkpoint, ledger entry,
provider call, or repair artifact.

Before the repair call, `REPAIR_INPUT.json` binds the exact generation record,
rejected source and admission fingerprints, typed generation brief, unchanged
policy, and deterministic violation set. The repair node can return only source,
rationale, assumptions, and a bounded change summary. It has no fields for an
experiment, metric, resource limit, import allowlist, path, tool, action, state
transition, execution, or retry count. Configuration schema fixes
`max_attempts=1`; provider/profile/policy/cost/live gates remain independent and
credential-free.

The replacement is projected into a separate `repair/result/` namespace with
its own model provenance. Original `generated.py` and its rejected verdict are
immutable. The identical controller-owned proposal metadata and admission policy
are applied again. Only an accepted `repaired.py` is copied byte-for-byte to the
ADR-019 Bubblewrap input. A second rejection is terminal and creates no admitted
path. Resume reuses a complete repair ledger/result and never performs another
completion; incomplete paid attempts follow the existing recorded-response and
unknown-cost rules.

This closes bounded recovery from deterministic syntax/import/AST/metric-marker
failures. It does not diagnose a sandbox/runtime failure, install a dependency,
change an environment, or establish that a model improves scientific code.
Priced live acceptance and comparative repair-quality evaluation remain required
before an effectiveness claim.

### ADR-042: Recursive self-development cannot evaluate itself as a headline task

Status: accepted for experiment-design admission; external runs remain pending.

SciTaste intentionally uses its own full lifecycle to develop the SciTaste
product and paper. This supplies realistic process evidence, but the resulting
project is statistically and temporally coupled to the method under study.
Treating it as an effectiveness task would allow design choices, retained
memory, selected failures, and manuscript revisions to confirm the preferred
claim.

The `evaluation` package therefore represents the product, its self-development
parent, and held-out formal child projects as different objects. A headline
full-lifecycle block must contain SciTaste and at least two real independent
external systems under matched model, starting information, permissions,
repair, and telemetry policies. Headline tasks must be held out, external to the
parent evidence, executable, and produce a final paper. The self-development
task may appear only as process evidence.

Scientific completeness and launch authority are independent. The deterministic
gate first checks external-system reality, task independence, comparison
fairness, estimand, power, failure handling, blinded review, judge validation,
and immutable feedback semantics. Execution additionally requires an explicit
human approval bound to the proposal hash. A later product change invalidates no
historical evidence, but it creates a new protocol rather than replacing
completed cells.

Failure attribution is similarly bounded. Same-state comparator success makes a
model limit a candidate; Base success followed by Full failure indicates a
framework-induced regression; sound but unrepresentable or unexecutable plans
indicate a framework limit; context and resource failures remain separate; and
ambiguous cases remain unresolved. This prevents weak model output from hiding
framework omissions and prevents framework failures from being assigned to a
model without a controlled comparison.

### ADR-043: External evaluation evidence has use-specific admission

Status: accepted for metadata and design admission; formal execution remains blocked.

A paper, repository, dataset, and runnable comparison condition are not the same
resource state. A single “available” flag would let citation evidence silently
become execution authority, or let a benchmark package license stand in for the
licenses and assets of every upstream task.

The `evaluation` package therefore loads one bounded, non-symlink, versioned
YAML corpus with byte and semantic hashes. Each benchmark or system binds its
official repository commit, publication identity, code license bytes, optional
dataset revisions, native interfaces, resource requirements, and atomic gate
evidence. Readiness is deterministically derived for four uses: `reference`,
`code_audit`, `task_source`, and `comparison_system`. Missing and blocked gates
fail closed; prose has no field that can declare formal readiness.

Experiment-design schema `1.1` binds the corpus semantic hash. Every headline
external framework binds a corpus resource and includes its admitted upstream
commit in `implementation_ref`; every headline task binds a benchmark resource.
The design gate re-derives feasibility before scientific completeness, and
human approval cannot override a failed resource gate. The current v2 corpus
permits reference and code audit of MLR-Bench, EXP-Bench, MLR-Agent, AI
Scientist-v2, and AutoResearchClaw, but deliberately admits none for task or
system execution yet.

### ADR-044: Generated interaction is project-owned navigation, not one global chat

Status: accepted for the loopback single-user interface.

SciTaste opens on a portfolio index and gives every project an independent home.
An independently initiated question creates a research workspace; follow-up
questions append immutable turns inside that workspace. Runs, papers, topics,
and turns remain distinct objects even when the interface links them. This avoids
both extremes of one unbounded global chat and one disconnected chat window per
sentence.

The loopback browser no longer asks the user to copy a bearer credential into
the main page. The server creates a memory-only credential and bootstraps an
HttpOnly, strict same-site cookie only after validating a loopback `Host`.
Cookie-authenticated mutations require exact same-origin provenance. Explicit
bearer authentication remains supported for programmatic clients and mandatory
outside loopback; the automatic session endpoint is unavailable there.

Every admitted generated document and its receiver-owned surface are archived
under the owning project's ignored `.generative-ui/` tree. The in-memory LRU is
only a performance cache: restart and eviction do not delete navigation history.
Topic manifests are atomically replaced, turn records are immutable, and raw
free questions are retained only as bounded inert local text for user-visible
continuity. They never become renderer code, model authority, or executor input
without passing the existing intent and proposal gates.

### ADR-045: Review closure is a state-derived proof, not a manuscript assertion

Status: accepted for project-owned paper revision and pre-submission review.

A reviewer request for evidence cannot be closed by adding a sentence to the
paper or hashing that paper as “evidence.” `evidence-paper-revision` remains a
proposal-only semantic node. Its accepted output crosses into a reader-facing
paper only through deterministic materialization, which replays the runtime
ledger, source paper trace, exact packet and reports, project-owned opening and
closing states, new evidence relations, completed experiment record, and result
bytes.

The materialized Stage 19 bundle retains `PAPER_REVISION_TRACE.json`. Each
author-response resolution declares whether it is prose-only, registered
evidence, registered experiment, contested, or an accepted limitation. An
addressed hard concern must bind the trace's exact closure proof and identities;
the original reviewer must bind the same proof when closing it. Round status
inspection repeats the checks rather than trusting stored status. Models may
draft a revision or review, but cannot create evidence, certify their own
closure, impersonate an independent expert, or issue an official venue decision.

### ADR-046: Experiment proposals are immutable project evidence, not launch configuration

Status: accepted for API/GPU prelaunch ownership; formal execution remains blocked.

Reusable files below `configs/evaluation/prelaunch/` describe candidate
protocols, but do not establish which exact proposal an individual research
project inspected or selected. Copying those files into ad hoc output folders
would also separate the resource gate, critic findings, and expanded cells from
the project revision shown to a user.

`ProjectRuntime` therefore publishes one project-owned evaluation directory
transactionally. Its self-hashed `EVALUATION.json` binds exact bytes for the
prelaunch manifest, external-resource corpus, deterministic gate report,
five-domain critic report, and complete cell plan. `PROJECT.json` retains a
content-bound summary and optional current-navigation identity. Opening a
project reports nested drift; selecting or projecting an invalid bundle fails
closed. The Generation-as-Content project home may display only this verified
summary and keeps its no-execution statement visible.

Publication, selection, scientific readiness, author approval, and launch are
distinct transitions. This implementation provides only the first two. It does
not contact an API, inventory a remote GPU host, acquire a benchmark, run a
cell, or elevate proposal data into executable authority. A future launch
service must revalidate the selected proposal hash, readiness, exact human
approval, current provider revision and price, local/remote resources, and every
task and comparator adapter before admitting work.

Verbose readiness checks are not themselves an information architecture. One
task can create parallel gate, cell-plan, and critic codes, so the receiver
derives seven stable decision domains without deleting the original
diagnostics. The projection is deterministic and self-hashed. Unrecognized
future codes are assigned to the temporal-integrity domain and disclosed, so a
new validator cannot silently disappear behind an outdated interface.

### ADR-047: Scientific results cross a separate project-owned admission gate

Status: accepted for API/GPU result registration; no formal run is implied.

Launcher completion, scientific evidence completeness, headline-analysis
eligibility, and effectiveness are different facts. SciTaste therefore does not
promote a run directory or an aggregate score directly into paper evidence. A
versioned result set binds every cell to the exact proposal, expanded plan,
resource corpus, execution telemetry, real or synthetic evidence class, and
content-addressed artifacts. External condition-blinded reviews and
preregistered primary contrasts are explicit typed records rather than prose.

`ProjectRuntime` copies an already existing result set into an immutable
`evaluation-results/<result-id>/` bundle only after deterministic inspection.
It replays that inspection whenever the result is opened, selected, projected
through Generation as Content, or queried by the lifecycle. Selecting a result
also selects its owning evaluation; selecting an incompatible evaluation clears
the current result instead of leaving a misleading cross-protocol alias.

A formal claim requires an authorized ready proposal, a complete
schema-1.3-or-newer claim-admission contract, budget compliance, real outcomes, valid
external attested blind reviews, and every exact preregistered contrast. A valid
failed execution remains in an `include-as-outcome` intention-to-run population;
missing, invalid, synthetic, or unplanned records fail closure. Native Taste
causality requires valid analyses for the no-Taste and mismatched-Taste controls
plus every declared component diagnostic. Schema 1.4 lets only the explicitly
confirmatory controls determine the headline conclusion. External matched
superiority requires at least two real
independent method comparators. Best-native evidence is model-confounded and
remains descriptive even when complete and positive. Pilot and internal-review
evidence cannot pass any formal claim gate. Even a valid formal project result
affects a paper only when a newly materialized paper manifest binds the exact
result and assessment hashes; independent review must then close against that
paper before the top-venue evidence loop is complete.

The binding is a physical `SCIENTIFIC_EVIDENCE_BINDING.json`, not optional
manifest prose. It is self-hashed and covers the exact result bundle, result
set, assessment, and every other paper artifact. `ProjectRuntime` rehashes this
proof during paper registration, opening, selection, project snapshot creation,
and lifecycle inspection. Review preparation already hashes every declared paper
file, so reviewers necessarily receive a packet tied to the same proof. Older
papers remain readable but cannot satisfy this gate without a newly materialized
revision.

### ADR-048: Model review identity is derived from the runtime ledger

Status: accepted for internal whole-paper review admission.

A structured review proposal and an operator-typed provider/model pair do not
prove which model invocation produced a paper review. New internal review
reports therefore name one project run and invocation. Admission verifies the
complete append-only model-node ledger, requires an accepted
`venue-paper-review` result, and checks that its immutable context, input,
request fingerprint, packet, paper bytes, profile, policy, and returned identity
remain mutually consistent.

The resulting report embeds a typed provenance record for the ledger entry,
result, recording, raw response, prompt, and profile. Reviewer identity is
derived from the returned response and cannot be supplied separately. A
rejected, failed, planned, cross-round, or identity-drifted invocation cannot be
promoted. Historical schema-1.0 reports retain their original self-hashes and
remain readable; absence of invocation provenance is preserved rather than
silently rewritten. This boundary establishes internal critique provenance but
does not make a model reviewer independent, expert, or an official venue
decision authority.

### ADR-049: Benchmark metadata and executable task bytes are separate gates

Status: accepted for task-package qualification; no acquisition or experiment
is implied.

A URL, repository commit, dataset revision, and task ID establish a candidate
scope but do not establish which bytes a system received. Conversely, finding a
local `task.md` does not prove its origin, license, independence from the parent
project, terminal signal, or allowed runtime acquisition. Treating either form
as an admitted task would make matched-system claims unauditable.

SciTaste therefore adds one local-inspection-only task-package manifest between
selection and prelaunch. It binds the metadata selection by both file and
semantic hash, one selected task identity, the complete bounded local file
inventory, owner approval and acquisition receipt, and content-addressed
evidence for license, acquisition, held-out/source-disjoint status, executable
signal, blinded-review endpoint, and runtime policy. Inspection follows no
symlinks, rejects undeclared bytes and drift, performs no network access, and
cannot authorize either acquisition or execution.

Qualification and ledger admission remain distinct. A clean local package may
propose updates to the selection and external-resource corpus, but it is not
prelaunch-bindable until those authoritative records carry the verified task
and task-source gates. The experiment proposal must then bind the admitted
package bytes, and explicit hash-bound owner approval remains a later launch
gate.

### ADR-050: External adapter feasibility precedes checkout and implementation

Status: accepted for static external-comparator translation review; runtime
adapters remain blocked.

An accepted research system and a pinned repository are necessary but not
sufficient comparison evidence. Before spending resources on a checkout or
wrapper, SciTaste records whether one selected task/model envelope can be
represented through the upstream system's native entrypoint without changing
its core. The static contract binds the upstream commit, shell-free argv shape,
credential allowlist, task and all-role model semantics, forbidden changes, six
adapter requirements, exact official source URLs, and a local audit hash.

This layer is intentionally earlier than adapter preflight. It neither imports
nor downloads upstream code, and even a clean result only permits implementation
and a later clean-checkout preflight. Pending evidence does not become verified;
a blocked native mismatch cannot be hidden by a compatibility alias or by
substituting a different coding agent. Both report schemas fix execution
authority to false.

For the current DeepSeek V4.1 package prepilot, exact-commit inspection finds
MLR-Agent and Agent Laboratory blocked on task/model/sandbox/telemetry mapping,
with artifact and recovery qualification pending. This means the proposal's
matched-external-comparator premise is infeasible as written. A common native
backbone can preserve the matched estimand, while a best-native-system design
answers a different, model-confounded systems question. Either change requires
a new immutable experiment proposal and author decision; no runtime adapter may
silently choose between them.

### ADR-051: Venue-review concerns become project-owned state obligations

Status: accepted for review-to-research-state routing; evidence collection and
closure remain later transitions.

The pure concern router demonstrates deterministic action selection, but a
paper-review loop is not auditable if its output never enters the owning
project. SciTaste therefore materializes one registered routing run from an
admitted review report and a ResearchState belonging to an existing project
run. Its self-hashed manifest binds the report, implementation commit, source
state file and semantic identity, routed state, routing record, concern IDs,
and newly opened obligation IDs. Publication uses a preparing run followed by
an immutable stage directory; interruption cannot leave a run falsely marked
complete.

Routing is not evidence. Every new obligation remains open, the bundle records
zero new evidence and zero model calls, and the project's scientific claims do
not advance. When an evidence-requiring paper-level concern names neither a
claim nor an evidence type, the obligation creator supplies a category-specific
required type instead of allowing arbitrary later evidence to close it. Formal
results must subsequently enter ResearchState with those matching types, after
which a content-bound paper revision and original-reviewer verification remain
necessary.

### ADR-052: Formal results close only evidence-matched review obligations

Status: accepted for project-owned result-to-state admission; no experiment is
authorized or implied.

An evaluation result bundle can be internally valid without proving that it was
the project's selected result, that it answers a routed reviewer concern, or
that the paper revision used its exact evidence. SciTaste therefore introduces
a separate immutable evidence-admission run after result registration and
selection. It revalidates the evaluation proposal, plan, result set, assessment,
all nested artifacts, source review routing, opening ResearchState, and a copy
of the project manifest at the admission revision.

Admission requires formal scope, exact-proposal execution authorization,
headline completeness, and positive preregistered primary contrasts against at
least two real external method implementations. It creates distinct evidence
types for comparative effectiveness and matched external baselines. Multi-task
validity appears only when at least two held-out matched-lane tasks are present.
Evidence with no claim relation may close a broad paper-level obligation but
cannot close a claim-specific obligation. Closure is restricted to the named
routing bundle so a new result cannot silently close matching historical
reviews, and prose-only concerns are never closed by evidence.

The transition also records the formal result as a completed experiment and can
derive `PaperRevisionClosureProof` objects from the exact opening/closing state
and result-record bytes. These proofs feed the existing proposal-only paper
revision path. Manuscript materialization, author response, original-reviewer
verification, and the two-expert pre-submission gate remain separate authority
boundaries. The implementation performs no provider call, GPU work, task
acquisition, paper mutation, or review self-certification.

### ADR-053: Acquisition approval and data movement are separate transactions

Status: accepted for bounded source acquisition; the first ten-brief request
has completed under exact-hash owner approval.

A review-ready source allowlist is not permission to move data, and a signed
download decision is not permission to ingest or execute it. SciTaste therefore
turns the acquisition boundary into three independently visible states:
deterministic inspection, an immutable owner approval bound to the exact
semantic request hash, and a separately switched download-only transaction.
Approval metadata is excluded from the request identity so the same approved
artifact proves precisely which pre-approval decision it signs.

The executor replays readiness and authorization immediately before transfer,
accepts only HTTPS sources already bound to allowlisted hosts and immutable
revisions, disables redirects, validates declared media types and byte ceilings,
and writes into a private staging transaction. It publishes the whole request
directory with observed per-file hashes and a self-hashed receipt only after all
items succeed. Existing transaction roots are never reused; transfer failure
removes staging and cannot leave a partial admitted dataset. The receipt fixes
both `authorizes_ingestion` and `authorizes_execution` to false.

This ADR closes the movement-control implementation gap, not the scientific
gate. Actual acquisition still requires the project's explicit exact-hash
decision. Task-package qualification, runtime preflight, experiment launch,
result selection, paper evidence binding, and independent review remain later
authority boundaries.

### ADR-054: Generated project pages use progressive disclosure and inline intervention

Status: accepted for the local Generation-as-Content receiver.

An evidence-complete project snapshot can contain dozens of runs and proposals,
but presenting every registered record at once is not a useful research
decision surface. The receiver therefore separates the decision layer from the
evidence vault. A generated progress page selects only a project decision brief
and a bounded heterogeneous evidence graph. Detailed run, acquisition,
evaluation, result, blocker, milestone, and activity views remain available
behind one native disclosure or through focused follow-up pages. This is a
presentation projection over the same validated bytes, not lossy evidence
admission.

The graph is server-composed and closed over content-addressed snapshot records;
the browser may only draw local SVG primitives and select an existing node.
Further exploration submits a bounded progress question and persists the result
as another immutable turn in the same project conversation. It cannot invent a
new evidence reference or change research state.

The permanent inspector rail is removed from the visual layout because an empty
control surface competes with decision content. The logical v1 shell region is
retained for archive-fingerprint compatibility, while proposal decisions and
artifact previews are rendered inline only after an explicit action. Approval
still produces only the existing deterministic, non-executable handoff; the
model and browser gain no tool or state-mutation authority.

The same presentation boundary gives the left drawer one stable information
role: project-scoped conversation history. Project switching remains in the
content toolbar, and fixed views plus advanced evidence selectors live behind
one toolbar disclosure. The drawer is closed by default; a desktop edge hover
may preview it without reflow, while click/focus/touch provide explicit,
accessible control and Escape closes it. The question composer belongs below
the evidence workspace, not inside navigation, and is text-entry-first rather
than a three-column settings form. A project home exposes four recurring
research-room launchers, each backed by a current server-issued next-step
candidate; it does not pre-create empty or inferred conversations. These rules
are receiver layout policy and introduce no new state, evidence, or execution
authority.

### ADR-055: Compute inventory is project-superordinate and secret-free

Status: accepted for shared API/GPU definitions and observations; scheduling is
not yet implemented.

GPU hosts and provider model identities are reusable infrastructure, not
artifacts owned by whichever project happens to use them first. Conversely, an
experiment proposal, its approval, results, and paper claims remain project
evidence. SciTaste therefore places a stable catalog in `configs/resources/`
and a machine-local runtime registry at `outputs/resources/`, as a sibling of
`outputs/projects/`.

The catalog stores typed capability and identity only: API endpoint, requested
model and expected served revision, dated public price ceiling, credential
environment-variable name, GPU device class, and a content-bound baseline
inventory. Remote GPU definitions may additionally bind an explicit SSH
alias/host/port/user, password environment-variable name, and bounded forward
topology so infrastructure does not depend on undocumented operator memory.
Passwords, keys, and raw authenticated responses are excluded.
Changing capacity enters as an immutable typed observation whose exact source
bytes and self-hashed record are retained. Official catalog observations may be
verified; owner reports remain reported until an independent probe replaces
them. Requested-versus-returned API identity and approximate-versus-exact disk
capacity are distinct fields rather than prose aliases.

Actual credentials may exist only in a mode-`0600`, Git-ignored local access
file below `outputs/resources/access/` or in the process environment. The
access inspector resolves only catalog-declared variable names, rejects
symlinks, permissive modes, duplicates, and unrelated variables, and emits no
value or secret hash. Its status partitions resources by binding presence while
retaining provider availability as a separate field. Credential presence is
therefore neither a connectivity observation nor execution authority.

Catalog inspection and observation registration perform no provider call,
remote login, project mutation, reservation, or workload. They cannot authorize
an experiment. The v2 catalog is a small hash-index over independent API, GPU
host, and checkpoint manifests. Catalog advancement archives the predecessor
registry and refuses to orphan observations. A typed project binding names each
resource role without copying infrastructure into the project evidence tree;
its source and record are immutable and bound to the catalog semantic hash.

A later allocation layer must atomically lease devices or API quota, reject
overlapping reservations, bind the lease into a project proposal, and reconcile
measured usage back to both the shared resource and project ledgers.

### ADR-056: Acquired starting briefs do not imply executable research tasks

Status: accepted after the first real MLR-Bench source acquisition.

An atomic download receipt proves byte identity and authorization scope. It
does not prove that the content supplies an empirical environment, objective
score, held-out population, or evidence-valid idea-to-paper endpoint. SciTaste
therefore adds a post-acquisition cohort inspector between movement and
task-package admission.

The inspector closes the task set over the selection, approved request, and
receipt; rehashes every local file; rejects missing, extra, symlinked, resized,
or modified bytes; and partitions each task's allowed scientific uses. It
distinguishes stagewise idea/proposal pilots, brief-only package prepilots,
formal empirical trajectories, and objective-progress tasks. Readiness in one
partition cannot satisfy another, and the report cannot authorize ingestion,
execution, provider calls, or GPU work.

The first real cohort validates this boundary. All ten official MLR-Bench
workshop briefs are exact and licensed as starting inputs, but none includes
runtime assets or a fixed objective score. They remain useful for low-cost
rubric and package-review calibration while being structurally barred from the
paper's empirical evidence-validity and objective-progress claims.

A project may register the self-hashed qualification as a canonical run
artifact. The Generation-as-Content receiver revalidates that artifact and
shows the allowed-use partition and blockers separately from the earlier
download-approval card. Rendering grants no new authority and cannot relabel a
brief-only cohort as a formal task population.

### ADR-057: Aggregate GPU memory cannot satisfy a single-device benchmark contract

Status: accepted for objective-progress candidate qualification; no workload is
authorized.

Benchmark identity, task identity, compute capacity, and experiment authority
are separate gates. SciTaste therefore binds an executable-source candidate to
an immutable benchmark corpus, official repository commit, shared compute
catalog semantic hash, API resource, GPU host, complete accepted-task
partition, and task-specific legal/asset/environment/test statuses. A task fits
only when its published per-device requirement is no greater than the selected
host's guaranteed memory per device. Device counts are not multiplied to create
fictional shared memory unless the upstream task defines and validates that
distributed execution.

The candidate arithmetic is also semantic rather than decorative: selected
tasks × conditions × seeds must equal the internal run-unit count, and that
count times the per-run ceiling must remain within the declared GPU-hour cap.
This accounting cannot substitute for a pilot-based power analysis. A four-task
slice is explicitly transfer/mechanism evidence with task as sampling unit and
cannot authorize a broad population claim.

Qualification is fail-closed. Metadata review may pass while acquisition,
preflight, and execution remain false. Platform terms, interactive credentials,
manual submissions, missing file hashes, unbuilt environments, unverified
provider/host observations, and absent 48 GB devices remain visible. The report
and CLI carry literal false authority fields and perform no network, provider,
SSH, or GPU action.

### ADR-058: Large dataset metadata is not download approval

Status: accepted for the first MLRC executable-task acquisition review; no
dataset body has been acquired.

A repository commit and task name do not determine the bytes needed by an
executable benchmark. SciTaste therefore derives a separate dataset-package
inventory from pinned preparation code and binds every provider object ID,
source URL, observed length, modification time or ETag, destination, task, and
license evidence. Inventory and request hashes are closed over the executable
candidate, external-resource corpus, and shared compute catalog. Asset/task
counts and compressed/unpacked/free-space arithmetic are recomputed rather than
trusted from prose.

Metadata readiness, owner-approval readiness, post-transfer qualification, and
execution authority are separate partitions. An initial transfer cannot claim
a content SHA-256 before bytes exist; it must record that hash in an atomic
receipt. Archive path traversal and expanded-size safety are likewise
post-transfer gates. A license conflict blocks owner-approval readiness even
when every source object is exact, unless a separate content-bound policy
preserves all applicable obligations for a narrower use scope. The report still
grants no network, download, ingestion, API, GPU, or execution authority.

Generation as Content may show the bounded task/size/license decision and link
to the content-addressed report. It does not inline 39 object records on the
project landing page and cannot mutate the request or approve a transfer.

### ADR-059: Large-package transfer is a hash-confirmed streaming transaction

Status: accepted for the acquisition control path; the real MLRC package is not
approved or acquired.

Multi-gigabyte benchmark packages cannot reuse the small-evidence downloader's
in-memory byte contract. SciTaste therefore binds owner approval to the exact
proposal, request file, inventory, and no-network gate report. Approval permits
only source preflight and download. A separate command must reconfirm both the
proposal and approval hashes and carry an explicit network switch.

The transfer validates response identity on the same connection that produces
the body, rejects redirects and content encoding, streams bounded chunks to
exclusive staging files, computes SHA-256 incrementally, and publishes only one
complete request directory. Exact per-object and aggregate lengths are required;
a failed object removes the complete staging transaction. Free-space checks use
the approved unpack envelope rather than only compressed download size.

The acquisition receipt is still not an extraction permit. A separate reader
rehashes every archive and inspects ZIP central directories without extraction.
Path escapes, symbolic links, encrypted or duplicate members, suspicious
compression, member-count excess, and task-level expanded-byte excess fail
closed. Even a safe report grants no ingestion, provider, GPU, or experiment
authority. This separation lets software readiness advance while rights and
post-acquisition checks remain independently visible.

### ADR-060: Acquisition license readiness is not ingestion clearance

Status: accepted for the first MLRC package; no transfer is approved.

One scalar license label cannot represent layered dataset rights. SciTaste now
binds the exact asset inventory to a separate policy containing a fixed academic
non-commercial use scope, reusable obligation profiles, a one-to-one asset map,
task closure, and literal false authority fields. The deterministic inspector
rejects inventory hash drift, missing or duplicate assets, task-order drift,
profile/license mismatch, unused profiles, unsafe use scope, and any acquisition
profile that remains blocked.

For Perception Test material, the conservative effective basis is upstream
CC-BY-4.0. A downstream MLRC Apache statement is retained as provenance but does
not erase upstream attribution or modification-notice duties. For Meta-Album,
the CC-BY-NC-4.0 transformed-release boundary composes with each source label;
redistribution and raw/derived dataset publication remain outside the policy.
This permits an owner to review a download for the paper's local academic use
without claiming general legal clearance.

AWA demonstrates why acquisition and ingestion are distinct. Official sources
describe freely redistributable images with one license record per image, not a
single Creative Commons variant. The policy can therefore make the exact archive
acquisition-review-ready while keeping ingestion false until acquired bytes
prove license-record presence and complete image coverage. The package proposal
hash binds the policy file, so weakening its scope or obligations invalidates
the owner decision. No policy inspection calls a network, creates dataset bytes,
approves a transfer, or authorizes extraction, ingestion, API, GPU, or experiment
execution.

### ADR-061: Claim admission is estimand-specific and failure-inclusive

Status: accepted through schema-1.4 prelaunch and schema-1.2 result assessment;
the current native v8 and external v7 proposals remain blocked and unapproved.

A comparison lane, cell count, or positive aggregate does not identify the
scientific claim it may support. SciTaste therefore binds one claim-admission
contract to an exact lane. The contract names one of three estimands—native
Taste causality, matched external superiority, or best-native external
description—plus the candidate, every comparator, contrast role, direction,
minimum effect, minimum distinct-task population, and failure treatment. The
cell plan copies the contract kind, lane, and hash so a result cannot be
assessed against a different interpretation.

Native Taste causality is within-system: every condition shares one API or GPU
backbone and an unconfounded execution envelope; no-Taste and mismatched-Taste
contrasts are mandatory and all other lane systems must appear in the closed
contrast set. External claims require at least two real method comparators.
Matched external evidence may support a separately named superiority claim;
best-native evidence must preserve per-system model identities and
`model_effects_confounded=true`, so it can close only a descriptive external
assessment. It can never become title, headline, or causal evidence by a result
serialization change.

Failure handling follows the estimand rather than a success-only convenience
sample. A planned real cell that executes and fails is a valid outcome and must
receive the frozen task-level treatment. A missing record, invalid telemetry,
synthetic evidence, absent external review, decision-rule drift, unplanned
contrast, or mismatched analysis artifact blocks completion. Every primary
contrast additionally hashes the exact candidate/comparator result records and
their success/failure states; declaring the expected unit count without that
input binding is insufficient. This separates a system's scientific failure
rate from evidence-pipeline corruption and prevents successful-only reporting.

The deterministic prelaunch critic understands these roles. It does not demand
external method comparators from a native ablation or a direct-agent control
from a best-native ecological slice. A one-seed prepilot receives a replication
advisory, while the same deficiency blocks a formal design. Remote inventory is
checked for host capacity before checkpoint transfer; checkpoint identity is
compared only after the proposal claims that remote checkpoint is verified.
These refinements remove false blockers without weakening any launch gate.

### ADR-062: Native Taste conditions are executable policies, not run labels

Status: accepted for offline structural acceptance; formal model-backed execution
remains pending.

A condition name in a manifest does not prove that two research trajectories
executed different mechanisms. SciTaste therefore defines one hash-bound,
closed six-profile matrix over four decision components: explicit utility,
Knowledge retrieval, Taste retrieval relation, and stage-specific Taste critics.
The Full Workflow loads the selected profile before project mutation, constructs
one condition runtime, and carries that controller and retriever consistently
through Discovery, Evidence, Communication, and Figure. The workflow hash binds
both matrix bytes and semantic fingerprint, and mid-run drift fails closed.

The critics penalize wrong-level commitment, missing prerequisites, premature
commitment under unresolved uncertainty, and communication over unsupported
claims. They are advisory score adjustments, not truth or safety authorities.
Hard budget feasibility, evidence integrity, writing integrity, visual validity,
code admission, and sandbox isolation remain active in every profile. Disabling
one of those gates would confound scientific validity with the Taste treatment
and is therefore rejected by the matrix schema.

The matrix also narrows causal interpretation. Full versus Base estimates the
complete explicit Scientific Taste bundle. Full versus the mismatched placebo is
the only v1 single-factor contrast: matched versus source-disjoint Taste context
with every other component fixed. Knowledge-only, Taste-only, and critic-only
arms diagnose sufficiency and mechanism; they do not identify marginal effects
from Full. A marginal claim requires a new leave-one-out or factorial contract.
The formal paired corpora must additionally match stage/role, case count,
retrieved-token budget, provenance tier, and outcome-information availability;
zero retrieval or unequal context exposure invalidates rather than favors a
cell.

The committed acceptance uses a deterministic controller and seed corpus. It
proves condition isolation, state continuity, and integrity-gate invariance, not
model quality or scientific effectiveness. A formal proposal must additionally
bind a model-backed Base decision policy, task-specific source-disjoint corpora,
candidate-set parity, and the fixed implementation commit before execution can
be considered.

### ADR-063: Required analyses and confirmatory conclusions are different sets

Status: accepted for schema-1.4 native prelaunch and schema-1.2 result admission;
no experiment is authorized.

Requiring every planned contrast to be present is an evidence-completeness rule;
requiring every contrast to favor Full is a scientific hypothesis. Conflating
them would turn three component-only arms into an invalid conjunction test for
the paper title and would encourage post-hoc omission of informative null or
adverse diagnostics. Schema 1.4 therefore assigns every contrast exactly one
inference role. Both roles remain preregistered, paired, content-addressed, and
mandatory to analyze.

For native Taste causality, Full--Base estimates the complete explicit bundle and
Full--mismatched-Taste estimates the value of matched rather than irrelevant
Taste context under the paired-corpus constraints. Those two contrasts are
`confirmatory`. Full against Knowledge-only, Taste-only, or critics-only changes
multiple components and is therefore `mechanism_diagnostic`; it cannot establish
an individual marginal contribution. A leave-one-out or factorial claim needs a
new contract. External-system superiority contrasts remain confirmatory within
their separately declared matched-backbone estimand.

Result admission still blocks on any missing, invalid, unpaired, drifted, or
unattested diagnostic. Once the complete evidence set is valid, only the
confirmatory subset is evaluated for headline support. Schema-1.2 assessments
publish required, valid, and supported confirmatory counts alongside required
and valid diagnostic counts, preventing prose from hiding either population.
Legacy schema-1.3 serialization omits the absent extension, preserving proposal,
claim, and analysis fingerprints and the validity of existing evidence.

### ADR-064: Model preference is bounded selection, not controller authority

Status: accepted for offline integration; real checkpoint execution and causal
evidence remain pending.

The base language model is part of the training-free Scientific Taste design, but
a provider call must not inherit the controller's authority. SciTaste therefore
admits a model only after deterministic budget checks have removed infeasible
actions. The backend sees a fixed candidate set and a canonical state projection.
Depending on the selected native condition, that projection may additionally
contain explicit utility assessments, matched or source-disjoint Taste precedents,
and stage-critic findings. The model returns one existing action; an unknown
action, request-identity drift, or fingerprint mismatch fails the run rather than
falling back to an apparently successful deterministic choice.

Every non-trivial model selection is durable evidence. `ResearchDecision` records
the request and context hashes, ordered candidate IDs and candidate-set hash,
prompt version, returned provider/model identity, selected action, response hash,
latency, semantic attempts, cache status, and usage. It deliberately does not turn
the model's prose into an execution command. Single feasible-action steps require
no preference call and remain explicit deterministic transitions.

The Full Workflow can bind one exact local-Transformers configuration to all four
stages. Workflow provider/model metadata must match that backend, the checkpoint
must be hash-pinned, configuration bytes and expanded semantics enter the workflow
fingerprint, and execution requires the existing explicit live-model switch before
project mutation. The dry run reports whether a checkpoint would load while
remaining mutation-free. This proves the software route and telemetry contract;
it does not prove checkpoint availability, model quality, candidate-generation
parity, matched/placebo corpus parity, or experimental effectiveness.
