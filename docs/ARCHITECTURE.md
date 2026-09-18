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
52. SciTasteBench decision episodes preserve the prospectively recorded action
    menu and selected action exactly. Delayed outcomes and uncertainty-aware
    attribution join later, AI review remains explicitly nonhuman, source groups
    cannot cross evidence tiers/splits/roles, and self-development trajectories
    never establish external validity. Held-out target projections expose neither
    the selected action nor outcome/attribution labels.

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
contract. The later ADR-041 runtime-repair path does not retroactively alter that
negative record. Priced provider acceptance, live repair quality, and
scientific-effectiveness comparison remain separate gates.

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

Status: accepted for deterministic static-admission and bounded isolated-runtime failures.

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

The same one-attempt envelope may instead be configured exclusively for an
isolated-runtime failure. SciTaste accepts only a verified native execution
record whose admitted source hash matches the generated proposal and whose
failure is a nonzero exit, timeout, or measurement-contract error. The repair
input adds that record identity, bounded error, stderr hash/excerpt, and
Tool-Intelligence route. Resource and launcher failures are not mislabeled as
code failures. The original `code/` context and failed execution remain
immutable; the replacement is independently admitted beneath
`code-runtime-repair/`, then the failed Evidence stage is replayed and later
stages continue. Recovery also reuses an exact successful experiment record,
preventing a post-execution interruption from paying for the same action twice.

Local reversible repair follows `direct_path`; live paid repair requires both
the configured repair mode and explicit caller opt-in. Neither route schedules a
standalone preflight, and final reporting reads the execution-time availability
record instead of probing the environment again. This mechanism does not install
a dependency, alter an environment or experiment identity, exceed one repair,
or establish that a model improves scientific code. Priced live acceptance and
comparative repair-quality evaluation remain required before an effectiveness
claim.

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

For the historical DeepSeek V4.1 package prepilot, exact-commit inspection finds
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
the current native v10 and external v7 proposals remain blocked and unapproved.

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
it does not prove checkpoint availability, model quality, matched/placebo corpus
qualification, or experimental effectiveness.

### ADR-065: Native-path readiness is proven from Git objects, not worktree intent

Status: accepted for no-run preflight; experiment readiness remains false.

An implementation reference and a passing integration test do not by themselves
show that every experimental condition uses the claimed model path. The native
condition preflight therefore binds the workflow, condition matrix, preference
backend, checkpoint, controller, workflow composition, and decision trace to one
exact source commit. Inspection reads those bytes with `git show` and verifies the
workflow-to-matrix and workflow-to-backend relations plus the provider, model, and
checkpoint identity chain. A later dirty worktree cannot satisfy an older claim.

Readiness is deliberately factored. The current v2 record verifies the shared
condition runtime, bounded candidate generation, fixed-candidate model selection,
identity enforcement, and durable telemetry. It separately reports real
checkpoint execution and matched/placebo corpora as unresolved. Corpus parity is
a closed seven-dimension contract, and Full versus placebo may differ only in
source/domain relation. The report contains no launcher and permanently sets
`authorizes_execution=false`; static path verification cannot substitute for
owner approval or empirical evidence.

### ADR-066: Candidate autonomy is template-bounded and separately traced

Status: accepted for offline integration; model execution and effectiveness
evidence remain pending.

A fixed candidate set prevents an unconstrained model from inventing tools, but
it also leaves all option construction inside handwritten workflows. SciTaste
therefore inserts a candidate-concretization call before preference selection.
The workflow supplies the executable template set; the same condition-bound
backend must return one proposal for every feasible template. The response can
specialize the description and rationale, while action identity, type, cost,
value, preconditions, tags, and protected parameters remain immutable. Only an
existing `SEARCH` action may receive a bounded query refinement. Its result limit
and domain scope remain fixed, so generation can improve information targeting
without silently increasing authority or resources.

Generation and selection are distinct evidence-producing operations. A durable
generation trace binds request and context identity, ordered templates, admitted
candidates, rationales, override keys, backend/model identity, raw-response hash,
attempt count, latency, cache state, and usage across all repair attempts. Exact
template coverage, response identity, safe overrides, and raw-response integrity
are deterministic admission conditions. Any violation fails the decision; there
is no hidden deterministic fallback. Single-option transitions bypass both calls.

The full native workflow reuses one resident pinned backend for both operations
and exposes the two capabilities separately in dry-run and completion summaries.
This closes the software candidate-generation gap while preserving the causal
condition boundary. It does not qualify paired Taste corpora, attest a remote
checkpoint, authorize GPU use, or show that generated candidates improve research
outcomes.

### ADR-067: Native Taste placebo evidence requires a separately qualified corpus pair

Status: accepted for offline integration; formal task-specific corpora remain
unacquired.

The matched and mismatched arms are separate, content-bound corpus files. A
local-only pair contract invokes production retrieval and verifies stage/role,
eligible count, retrieved count, context budget, provenance tier, curation tier,
and outcome-information parity. It also rejects held-out source reuse and any
source-group, content-hash, or locator overlap between arms.

The native path preflight accepts a verified corpus claim only when its Git-bound
qualification report proves all seven dimensions and repeats both corpus hashes.
This tooling does not authorize source acquisition or experimental execution.

### ADR-068: Taste experience is reviewed abstraction, not retrieved content

Status: accepted for offline integration; formal source acquisition and human
curation remain pending.

Retrieval solves transport and ranking, not scientific judgment. A source becomes
Scientific Taste only through a content-bound transformation that states the
decision context, considered actions, preferred action, principle, justification,
and observed outcome boundary. SciTaste stores the source artifact and separate
quality evidence, rather than accepting a self-declared venue or a search score as
proof of source quality.

An abstraction candidate is untrusted regardless of whether a human or model
authored it. Model assistance requires a bound trace. Exactly two independent,
conflict-cleared humans inspect the exact candidate hash for source fidelity,
action grounding, generalization, scientific value, and outcome handling. The
candidate author cannot review it; agreement needs no adjudicator, a split needs
exactly one, and rejection cannot be hidden by dropping the source after review.

Only the curation compiler can set `human_verified` and `retrieval_eligible`. It
then invokes the production retriever and the ADR-067 paired-corpus gate before
publishing immutable corpus artifacts. Failed publication removes the whole
attempt, and every output remains no-run with `authorizes_execution=false`. This
closes the software route from high-quality references to auditable Taste
experience without claiming that the presently missing human corpus exists or
that the resulting Taste is effective.

### ADR-069: Scientific design precedes resource admission

Status: accepted for ICLR 2027 evidence planning; acquisition and experiments
remain unauthorized.

Available checkpoints, API credentials, and GPU hosts are mutable capacity
observations. They cannot define the paper's claims, choose its controls, or turn
an available benchmark into a scientifically appropriate one. SciTaste therefore
stores the ICLR evidence program separately from its resource corpus and inspects
four ordered states: scientific coherence, acquisition-proposal readiness,
experiment readiness, and hash-bound owner authorization.

The scientific layer requires three confirmatory contrasts: reviewed abstracted
Taste versus raw retrieval from the same sources, matched versus source-disjoint
mismatched Taste under parity, and Full SciTaste versus Native Base on held-out
objective progress. It also assigns each external artifact one type. Benchmarks
provide decision, objective-progress, full-lifecycle, or integrity tasks;
accepted systems provide method comparators. A benchmark placed in the system
candidate set fails coherence even if its paper is highly ranked.

Operational evidence is an additive overlay. Resource corpus v9 pins
DeepScientist and InnovatorBench while preserving their unresolved license,
equivalence, asset, adapter, sandbox, telemetry, and resume gates. A conformance
pilot may later choose one capable primary model and a non-pooled robustness
provider, but no inventory entry can rewrite H1--H3. Formal sample size and
replication remain unset until an excluded pilot supports a power analysis, and
the self-development case remains process evidence outside every headline
population estimate.

### ADR-070: Proposal review is exact, complete, and non-authorizing

Status: accepted for the first ICLR 2027 source/method review package.

Scientific coherence alone does not specify what an owner is being asked to
approve. SciTaste therefore binds one evidence program and resource corpus to
exactly every selected task-source proposal and accepted-method adapter proposal.
Missing, additional, drifted, semantically mismatched, or already-authorized
children fail the package closed. The report separately exposes proposal-review
readiness, code-use viability, adapter-implementation readiness, and experiment
readiness; none implies another.

The first package requests 20 pinned InnovatorBench task configs and one pinned
EXP-Bench metadata table under an 8 MiB aggregate ceiling. It neither requests
the InnovatorBench archive nor repeats the acquired MLR-Bench briefs. Reference
admission uses publication identity and immutable source identity, while code
audit additionally requires a code license. Consequently AI-Researcher remains
a valid accepted-method reference but cannot be checked out or adapted until its
code-use rights are clarified.

Every package and report fixes download, repository checkout, API, GPU, human,
and execution authorization to false. Owner approval of a child acquisition
request must occur through that request's separate hash-bound transaction; a
review package can never act as a launch manifest.

### ADR-071: Title-level Taste evidence uses an explicit three-arm mechanism contract

Status: accepted for offline protocol integration; formal corpus and blind
reviews remain uncollected.

The historical `knowledge_rag`, `taste_library`, and `taste_placebo` conditions
do not establish the ICLR H1/H2 estimands. Knowledge RAG does not prove that its
raw evidence came from the Taste sources, and loose placebo text does not prove
source disjointness or token parity. Those conditions retain their old meaning
and hashes.

SciTasteBench v3 introduces `raw_source_rag`,
`matched_abstracted_taste`, and `mismatched_taste`. Each held-out decision binds
all three rendered contexts and their source groups, locators, content hashes,
retrieval-query and rendering-template hashes, frozen tokenizer identity and
artifact, observed token count, common ceiling and truncation policy, treatment
construction receipt, evidence tiers, and outcome-information status. Raw and
matched Taste arms use
the exact same sources; matched and mismatched arms are fully source-disjoint;
held-out task sources cannot enter any arm. The request uses a neutral context
header so the treatment name is not shown to the decision model.

H1 and H2 are directional registered contrasts with representation and
source-domain relation, respectively, as their only permitted differences. The
runner emits them by contrast identity instead of treating every effect as a
Base delta. Agreement with pre-existing expert action labels is retained as a
diagnostic. It cannot complete a protocol whose primary endpoint is independent
condition-blinded expert preference over the produced decision and claim
calibration. Evidence-program alignment therefore reports formal collection
readiness separately and always leaves confirmatory evidence incomplete until a
later blind-review artifact is attached. None of these checks authorizes data,
model, GPU, reviewer, or experiment activity.

### ADR-072: Reviewer feedback compiles into an approval-aware project DAG

Status: accepted for native offline orchestration; real follow-up work and
independent verification remain unperformed.

Routing concerns into obligations is necessary but insufficient for autonomous
research iteration: a flat set does not state which concerns need prose, new
analysis, method change, or experiments, nor when the paper may be revised.
SciTaste therefore compiles every concern-bearing report in one review round
through a cumulative content-hash-linked routing chain. The resulting immutable
plan separates no-run experiment design from owner-approved execution, method
proposal from validation, and evidence production from obligation closure. All
branches must close before paper revision; response and original-reviewer
verification are explicit downstream dependencies.

The plan is a coordination artifact, not evidence of completion. It binds the
round, reports, routed states, source commit, completion artifact types, and
project interfaces while retaining `authorizes_execution=false` and
`scientific_evidence_established=false`. Generation-as-Content may visualize the
same verified DAG and offer navigation, but it cannot skip dependencies or turn
an approval marker into an API/GPU/tool authorization.

### ADR-073: Reviewer experiment requests bind registered estimands before resources

Status: accepted for native offline orchestration; acquisition, execution, and
human review remain unauthorized.

A review concern such as “add effectiveness evidence” is too underspecified to
launch safely. Choosing a convenient available model or benchmark at that point
would allow mutable inventory or reviewer wording to redefine the paper's
scientific question. SciTaste therefore inserts a deterministic design compiler
between the review DAG and every experiment proposal. Its input is an explicit
concern mapping plus the immutable evidence program; it never maps free text by
keyword or model guess.

Each objective has a program-derived closed study set. Title effectiveness is
the union of studies reciprocally linked to title-critical claims. External
baseline evidence is the separately interpreted ecological comparison.
Cross-task generalization is the complete non-process evidence program. A title
overclaim is a conditional author decision: retain the target title only while
submission is blocked on H1--H3, or narrow it before submission. The compiler
cannot make that edit itself.

Multiple concerns may reuse one study, but cannot duplicate its execution. The
project-owned package binds the review plan, mapping bytes, program bytes, five
unique estimands, conditions, task sources, accepted systems, endpoints, and
experimental units. It deliberately records no primary model, fixed sample
size, repetitions, or compute allocation. Copied inputs and deterministic
recompilation are rehashed on inspection. All download, API, GPU, recruitment,
and execution authorities remain false, so design completeness cannot be
mistaken for empirical evidence.

### ADR-074: Experiment activation is a resource join, not a launch permission

Status: accepted for the ICLR 2027 no-run activation boundary; owner decisions
and all external actions remain unperformed.

An exact study design is still insufficient to launch. Data proposals may cover
only metadata, an accepted method may lack a usable adapter or code license, an
API alias may be rolling or unverified, and an available checkpoint may be too
weak or scientifically inappropriate for the paper. Treating a resource list as
readiness would convert availability into scientific selection.

SciTaste therefore compiles a second, review-bound activation record. It joins
the five unique H1/H2/H3/E1/D1 studies to the exact evidence-review package,
compute catalog, and project resource binding. Every task and accepted system is
covered exactly once. The resulting record exposes per-study blockers, data
scope, adapter viability, model identity and pricing gaps, human-review status,
and the absence of a powered sample or compute allocation.

DeepSeek V4 Flash and GLM-5.3-Flash remain candidates rather than selected
models. DeepSeek now has a public dated revision, but neither rolling alias has
an approved authenticated temporal-window observation; GLM pricing is also
unbound. Qwen checkpoints remain
diagnostic assets. The primary model may be frozen only after a task-excluded
conformance pilot, whose observations cannot enter the formal test.

The only current owner-decision-ready action is review of 21 pinned metadata
files under an 8 MiB ceiling. The activation artifact records that decision as
unapproved and unperformed. It cannot authorize downloads, repository checkout,
API calls, GPU work, reviewer recruitment, or execution. Generation-as-Content
may render this state and navigate to its evidence, but cannot mutate the gate.

### ADR-075: Rolling API models are sentinel-bracketed temporal strata

Status: accepted for ICLR 2027 experiment preparation; no live identity window
has been opened.

An API alias is neither a reproducible checkpoint nor automatically unusable.
SciTaste separates the callable ID, the provider's public revision disclosure,
and the exact temporal window in which calls occur. DeepSeek V4 Flash currently
has a public dated revision; GLM-5.3-Flash currently has only a callable family
identity. The latter can participate only as a shorter temporal-only stratum.

Every pilot and formal window is bracketed by task-excluded identity sentinels,
with additional sentinels after a bounded number of calls. The ledger retains
the requested and returned model, endpoint, interface, provider request ID,
timestamps, byte hashes, status, usage, and raw request/response. Missing or
changed identity aborts the window. A later window, revision, or provider is a
new stratum and cannot be pooled into the same confirmatory estimate.

The static protocol only establishes how a future call could become admissible.
It cannot attest a live identity, approve spend, select the primary model, or
authorize API calls. Conformance data remains excluded from formal tests and
candidate selection must precede formal outcomes.

### ADR-076: Self-reflection is quarantined until outcome and independent review

Status: accepted for training-free continual Taste learning; real longitudinal
review and effectiveness evidence remain absent.

An executed action is not automatically a good precedent. Its outcome may be
delayed, confounded, incorrectly attributed, or local to one research state.
Immediately retrieving a self-authored explanation would create recursive
confirmation bias: one mistaken interpretation could influence later actions and
then cite those actions as corroboration.

`TasteMemory.reflect` therefore records an exact executed-decision hash and
actual-outcome hash as a quarantined `TasteCase`. The case is neither human
verified nor retrieval eligible. Promotion requires bounded content-bound
decision and outcome records with observation identities, exactly two distinct
primary human reviews of the decision trace, outcome trace, alternatives,
principle, and
transfer scope, and one distinct adjudicator only when the primaries split. The
reflection author cannot review the case, reviews cannot predate the outcome,
and every review binds the exact case and outcome bytes.

Admission updates only the local memory record. It does not train a model,
authorize execution, or establish effectiveness. A negative outcome can still
produce useful Taste when the resulting principle and transfer scope are sound;
success alone is insufficient. Formal human identity and recruitment evidence
remain project-owned study artifacts rather than claims inferred from a typed
manifest.

### ADR-077: Model-assisted Taste abstraction is ledger-bound and relation-blind

Status: accepted for implementation; real source acquisition, API generation,
and human review remain pending.

The same-source H1 contrast is invalid if an abstraction can be hand-filled,
condition-aware, or detached from the model response that produced it. SciTaste
therefore exposes a dedicated `taste-abstraction` model node. It sees one exact
UTF-8 source projection, source identity, decision role, stage, domains, and the
declared outcome-information boundary. The matched/placebo relation, held-out
task content, unrelated project state, tools, and action authority are excluded.

An accepted response still has no retrieval trust. Candidate compilation requires
the canonical project-owned runtime entry and verifies the complete hash chain and
recording. Curation rechecks the live profile, prompt and output schema, request,
policy and profile fingerprints, source bytes, provider/model identity, raw
response, usage, zero-authority boundary, and exact proposal-to-candidate equality.
Scripted and replay fixtures are engineering evidence only. Two independent human
reviews, plus adjudication only on a split, remain the sole admission route.

Curation schema 1.1 separates historical model invocation count from the fact
that package inspection performs no external action; valid 1.0 records migrate
deterministically. This closes the executable transformation path but does not
claim that a task-specific corpus, real model response, valid human judgment, or
H1 effect currently exists.

### ADR-078: One CPython 3.12 control environment

Status: accepted for repository development and CI.

SciTaste supports the CPython 3.12 minor line rather than maintaining a duplicate
3.11 compatibility matrix. `.python-version` and CI select 3.12.14, while one
checked-in constraints file fixes the Linux development and study dependency
resolution. Local development uses the repository-owned `.venv` instead of a
cross-project interpreter.

Formal GPU/API conditions remain separately content-bound because CUDA, model,
and provider environments are measured experimental resources. Historical
3.11 runtime inventories and receipts are not rewritten; they are evidence of
past execution, not declarations of current repository support.

### ADR-079: Download authority does not imply permission to parse source content

Status: accepted for bounded acquired-JSON audit; no real source body has been
read through this path.

An acquisition receipt proves the bytes moved under a download-only decision.
Parsing those bytes can expose copyrighted text, personal data, external
locators, outcome information, and fields that were invisible during metadata
selection. SciTaste therefore requires a second owner authorization before a
local parser opens any acquired JSON source.

The authorization binds the exact approved request file, self-hashed receipt,
ordered item set, source project, auditor implementation hash, and explicit
depth, container, node, and string ceilings. Creating it does not read the
acquired bodies. The content auditor
requires a separate runtime switch, revalidates that complete chain, rejects
unregistered or symlinked files and byte drift, and parses strict UTF-8 JSON with
duplicate-key and non-finite-number rejection. Its only semantic output is a
content-addressed inventory of normalized field shapes, designated paper-ID
observations, and external locators that were counted but never followed.

Passing this audit means only that an exact record may enter a later rights,
quality, and source-isolation admission proposal. The report performs and
authorizes no projection, ingestion, model call, human review, or experiment.
This prevents possession of data from silently becoming permission to expose it
to a model or to promote an observed paper action as Scientific Taste.

### ADR-080: High-quality source admission is a three-argument frozen ledger

Status: accepted for the audit-to-abstraction boundary; no real AAAR source has
been admitted.

Structural validity is not scientific quality. A valid JSON record may have
unclear reuse rights, weak or untraceable scientific reasoning, or overlap with
the held-out decision whose outcome SciTaste later evaluates. A single quality
score would obscure these distinct failure modes and encourage replacing failed
sources after seeing downstream results.

SciTaste therefore freezes the complete content-audited population and compiles
three independent arguments per source: rights and attribution, high-quality
scientific decision evidence, and isolation from held-out case groups and the
self-development effectiveness study. The quality argument requires exactly two
distinct, conflict-cleared human reviewers who are blind to each other and to
downstream outcomes; the curator cannot review the source. Every review binds the
exact source-content and quality-evidence hashes.

The resulting ledger includes both admitted and rejected sources. Reaching the
predeclared minimum only makes a separate projection proposal possible. The
compiler never reads source bodies, recruits reviewers, projects fields, calls a
model, or authorizes execution. This preserves source selection as a scientific
design decision rather than a retrieval heuristic optimized on later outcomes.

### ADR-081: Benchmark metadata needs a format-aware read gate before task screening

Status: executable from project-level audit-plan bundling through deterministic
powered allocation; real acquired metadata remains unopened until the exact
audit plans receive owner approval.

Experiment-task configuration files and benchmark tables cannot use the AAAR
paper-record identity assumptions. SciTaste therefore separates their first
read from both task projection and scientific selection. A no-read plan binds
the approved request, acquisition receipt, exact item inventory, auditor
implementation, accepted media formats, and independent byte, depth, node,
path, string, row, and column ceilings. The plan itself grants no content
authority. Several plans may be compiled into one self-hashed project bundle
only when their exact receipts, request hashes, item sets, byte ceilings, and
auditor implementation identities still replay. The bundle is the canonical
Generation-as-Content decision surface for this transition; it does not merge
the underlying approvals or grant read authority.

After an exact plan approval and explicit local-read switch, the structured
metadata auditor accepts only YAML and CSV. YAML parsing rejects anchors,
aliases, explicit tags, duplicate keys, multiple documents, non-string mapping
keys, and structural-limit overflow. CSV parsing requires a non-empty unique
header, consistent row width, and bounded rows, columns, and fields; formula-like
cells and external locators are counted but never evaluated or followed. Both
paths first rehash the complete acquired inventory and emit only schema paths,
headers, counts, and safety facts—not task text or projected values.

Passing this audit means that a separate, source-specific metadata-screen
proposal may be written. SciTaste first binds every required screen concept to
paths or columns observed by the audit, while the source values remain closed.
A same-sized replacement population is insufficient: every request source URL,
pinned revision, and upstream task path (or the single CSV table identity) must
exactly replay the pre-inspection scope.
A concept with no source mapping must instead be declared as absent and remain
an explicit later-screen blocker; a path missing from one YAML record is kept as
record-level missingness. The approved projector then rehashes the same source
inventory and emits every record through only those fields. It reports the
aggregate missing-source-field count, binds the exact audited byte total, and
refuses a source population above 64 MiB. It cannot drop a record, inspect
formal outcomes, consult installed models or compute, evaluate formula-like CSV
cells, or follow a locator. This complete-population artifact is the input to a
later source-overlap, license, signal, environment, reproducibility, and safety
screen—not a selected subset.

This closes an otherwise consequential provenance gap in the older
`task_selection` contract: a structurally valid hand-written task list could not
prove that inconvenient tasks had not been removed after observing available
resources or expected performance. Projection approval remains distinct from
structural-read approval because the latter intentionally grants no field-value
access. Neither action chooses tasks, downloads runtime assets, ingests data,
calls a model, allocates compute, or establishes an experimental result.

Screening is now a separate complete-population compiler rather than an alias
for task selection. Its rulebook is frozen before the structural content read, covers every
scope exclusion code, and classifies each rule as either scientific eligibility
or post-eligibility allocation. Only the declared capacity code may occupy the
latter role. A valid decision package contains the Cartesian product of all
projected record IDs and all eligibility rules; its evidence fields and
assessment authority must exactly match the frozen rule. Missing projected or
bound evidence cannot be silently treated as a pass. The report preserves every
eligible, excluded, and unresolved record and becomes allocation-proposal-ready
only when at least one record is eligible and none remains unresolved.

The screening compiler reads only the already approved projection plus
explicitly hash-bound assessment evidence. It rejects the raw acquisition tree
and all control artifacts as evidence attachments, replays source, scope,
rulebook, decision, implementation, and chronology bindings, and records that
formal outcomes and current model, compute, and host inventories were not
consulted. Even a complete passing screen performs no seeded allocation and
grants no task-selection, asset, ingestion, API, GPU, or execution authority.
This makes scientific eligibility invariant to the resources that happen to be
available when the formal experiment is eventually launched.

Allocation is a separate, exactly approved compiler rather than a capacity rule
hidden inside screening. Its no-selection plan binds the complete screening
report, population, rulebook and decision hashes; an independently replayed
objective-H3 clustered-power request and report; the formal study identity;
the deterministic algorithm version; the destination; and an owner-reviewed
random seed. The plan contains per-stratum counts but no selected record or
source-group identity. It blocks when the screen is incomplete, implementation
identity has drifted, the power result is not formal-freeze-ready, required
allocation fields are absent, a source group spans balance strata, distinct
source groups cannot satisfy power, or the powered sample cannot cover every
non-empty stratum.

Only an approval bound to the exact plan file and semantic hashes permits the
allocation compiler to choose one representative per source group without
replacement. The frozen algorithm gives every non-empty stratum one unit, then
uses proportional residual capacity with deterministic largest-remainder ties.
Its report retains the complete partition: selected tasks, unsampled eligible
records, scientific exclusions, and unresolved records. It records the formal
task-set hash and can be replayed through screening and pilot-power evidence,
but it cannot download or ingest task assets, select a model, allocate API/GPU
resources, launch a study, or establish a result. Repetitions within a task
remain trajectories, not independent sample-size units.

### ADR-082: Raw RAG and Taste abstraction share one admitted source projection

Status: accepted and executable; no acquired source has been projected through
this path.

The H1 contrast is invalid if raw retrieval and Taste abstraction silently use
different source fields. Source admission alone cannot prevent that error: it
decides which sources qualify, while an operator could still copy different
subsets into the two treatments or leak outcome and condition identity during
prompt construction.

SciTaste therefore inserts a content-addressed projection freeze between source
admission and tokenization. A no-read plan binds the approved acquisition,
receipt, content audit, complete admission proposal, admitted/rejected report,
the exact audited terminal JSON pointers, forbidden subtrees and identities,
normalization, byte ceilings, and destination. Rejected sources and fields not
observed by the content auditor cannot enter the plan; object-subtree selection
is forbidden because it would bypass field-level review.

Materialization requires an owner approval bound to the complete plan and the
current projector implementation plus an explicit runtime switch. It rehashes
the full raw inventory, reparses strict JSON, applies only the allowlist, checks
that forbidden held-out and treatment identities and external locator text are
absent, and publishes all projections atomically. The receipt records the same
projection hash for raw RAG and abstraction input. It grants no tokenization,
model, reviewer, or experiment authority; model-specific token counts remain a
separate prerequisite for an abstraction resource proposal.

### ADR-083: H3 inference is task-level executable evidence, not supplied prose

Status: accepted and executable for frozen objective measurements; no formal H3
effect has been measured.

Earlier result admission could verify the hash, interval, and declared conclusion
of a supplied primary-comparison artifact, but it did not compute that comparison.
It also counted every task/seed/repetition tuple as an analysis unit. Treating
repeat trajectories as independent samples would understate uncertainty and make
the title claim easier to pass without adding held-out scientific problems.

SciTaste now binds a separate objective-outcome contract into the prelaunch
analysis. The contract freezes task-specific scorer bytes, metric direction and
bounds, normalization anchors, failure floors, source-group identities, task
weighting, interval/test methods, random seeds, alpha, and the confirmatory
multiplicity family. Successful scores require content-bound score artifacts;
failed cells receive their preregistered task floor.

The analyzer pairs systems within each task/seed/repetition block, averages those
blocks within task, and performs inference across equally weighted held-out tasks.
It emits task-clustered bootstrap intervals, paired task sign-flip p-values, and
Holm-adjusted confirmatory decisions. Diagnostic contrasts remain reported but
outside the title-claim family. Schema-1.2 comparisons expose task count and block
count separately, and result admission rechecks that distinction. Pilot analysis
cannot establish effectiveness. Every v1.2 comparison binds the measurement set;
result admission reloads it and the objective contract, reruns the estimator, and
requires the persisted report and comparison records to match exactly. The
analyzer performs no experiment, model, API, GPU, or human action.

### ADR-084: H1/H2 analysis begins only after locked blind opening

Status: accepted and executable for a post-pilot frozen design; no real H1/H2
effect has been measured.

The human-outcome audit deliberately stopped at an unblinded outcome ledger. A
`ready_for_primary_analysis` flag established ordering and integrity, not a
scientific effect. Treating the two reviewer judgments or multiple cases from a
single source as independent samples would also inflate the apparent population.

Schema-1.1 human studies therefore bind a separate post-pilot analysis contract
and, for formal work, power-analysis bytes before outcomes. The executable
design-based estimator codes matched-Taste preference as one, ties as one half,
and comparator preference as zero; averages reviewers within case and cases
within source group; and gives held-out source groups equal weight. It retains
missingness and disagreement, enforces the frozen missingness ceiling, reports
reviewer diagnostics, and computes source-group bootstrap intervals plus paired
source-group sign-flip tests. Holm correction covers H1 and H2, and both must pass
the formal joint title gate.

This engine does not choose the final model before pilot variance is observed.
If the pilot shows material crossed-reviewer dependence, a new formal contract
must name a suitable crossed-effects estimator; post-unblinding estimator changes
are forbidden. Analysis performs no recruitment, model/API call, GPU work, or
experiment and cannot turn pilot outcomes into formal evidence.

### ADR-085: Formal power belongs to independent scientific units, not cells

Status: accepted and executable for excluded pilot reports; no formal sample
size has been established.

Counting task/seed/repetition cells as independent would make a convenient
compute budget look like broader scientific evidence. Choosing the observed
pilot effect as the powered target would additionally shrink the formal study
after a lucky pilot. Both behaviors are prohibited.

SciTaste now accepts only a self-hashed pilot H1/H2 or H3 analysis report as the
dispersion source. H1/H2 uses held-out source groups and H3 uses held-out tasks.
The effect target is a separately justified smallest effect of interest, never
the pilot mean. Planning dispersion is the maximum of the observed standard
deviation, a frozen upper bootstrap percentile, and a justified nonzero floor.
A Bonferroni bound supplies conservative joint-family planning for the formal
Holm procedure, and the exact sign-flip p-value resolution supplies an
additional finite-sample floor.

The resulting report exposes independent units separately from generation
trajectories and human judgments. Repetitions may improve reliability but only
increase the cost projection. If the recommended units exceed the declared
ceiling, the plan remains non-ready rather than substituting more seeds or
dropping a confirmatory contrast. Formal sample size is fixed before outcomes;
the planner authorizes no optional stopping, execution, model/API/GPU use, or
human recruitment.

### ADR-086: Formal Taste is grounded contrastive distillation, not a reviewed summary

Status: accepted and executable at the construction boundary; no real source has
yet produced a formal grounded abstraction.

A binary source-fidelity review of a fluent decision summary is too weak to
identify the Scientific Taste intervention. It cannot show which source evidence
supports each element, distinguish a contrastive decision principle from generic
advice, or state when transfer should fail.

SciTaste therefore keeps the legacy abstraction readable but requires a stronger
schema for formal work. `grounded-taste-abstraction` traces context, evidence,
alternatives, choice, principle, and any available outcome to exact verbatim
excerpts in the canonical source projection. Deterministic admission checks those
excerpts and requires the principle to synthesize a scientific-action role with
a distinct evidence, justification, limitation, or outcome role. The proposal
also names applicability and failure conditions, a counterfactual that would
change the action, and discarded source-specific details.

Schema-1.2 corpus curation requires every candidate and source projection to use
this contract and adds two independent-review attestations for grounding and
transfer scope. Materialized Taste cases preserve the boundary in the controller
context and bind a grounding hash in provenance. Formal SciTasteBench v3 rejects
any weaker curation tier, so a legacy reviewed summary cannot silently enter H1
or H2. This gate proves treatment construction only; usefulness remains a powered
blinded outcome question.

### ADR-087: Taste selection deliberates over transfer boundaries after broad retrieval

Status: accepted and executable at the software boundary; no real selector
effect has been measured.

Stage-, domain-, and text-weighted retrieval is an efficient candidate generator,
but it cannot establish that a precedent applies to the current scientific
decision. Treating its top results as Scientific Taste would leave the method
vulnerable to the same oracle and topicality failures as curated RAG.

SciTaste therefore freezes 2--20 grounded, transfer-bounded broad candidates and
an exact projection of current decision facts and actions. The proposal-only
`taste-deliberation` node assesses every case, cites exact fact IDs for at least
two applicability conditions, reports triggered failure conditions, and maps
the precedent to current actions without seeing outcomes, relation labels, or
held-out task content. Deterministic admission rejects unknown references,
unsupported applicable verdicts, failure-triggered selections, repeated source
identities, and avoidable one-sided action coverage. It never falls back to the
lexical ranking after a failed proposal.

Only an accepted live project-ledger entry compiles into the controller input.
State, action, candidate, score, source, or case-content drift invalidates the
trace; the final research decision records both the broad pool and selected set.
The ICLR evidence program adds a matched H2b selector contrast against the
unchanged lexical retriever, because the oracle-controlled H2a relevance contrast
cannot prove autonomous selection. Real cases, applicability labels, provider
calls, blinded decisions, and powered outcomes remain separate evidence gates.

### ADR-088: Scientific Reference quality is content-grounded, not prestige-ranked

Status: accepted and executable at the qualification boundary; no real quality
effect has been measured.

Venue, author, and citation metadata are useful for broad discovery but cannot
show whether a source exposes a transferable scientific decision. Using those
signals as final quality would confound reputation, final success, and the
decision evidence SciTaste claims to learn from.

SciTaste therefore gives a prestige-blind `reference-quality` model node one
canonical content projection and requires exact source grounding for five
dimensions: evidential rigor, decision traceability, alternative visibility,
failure-boundary visibility, and transfer potential. Qualification requires
every dimension to be strong and the union of cited evidence to contain a
complete contrastive decision episode. Missing evidence yields a valid
rejection; the node cannot infer prestige or grant admission.

An accepted live ledger compiles into a content-free qualification receipt.
Source-admission schema 1.1 binds that receipt and projection but still requires
two independent human assessments of the same dimensions, blinded to prestige,
the model assessment, other reviewers, and downstream outcomes. Rights and
source-group isolation remain separate gates. The ICLR program registers H0
against prestige-only source selection from the same broad pool, while H1 holds
the admitted source set fixed to isolate abstraction. Real content access,
model calls, reviewers, and outcomes remain independently authorized work.

### ADR-089: Reference discovery optimizes contrastive decision coverage before quality

Status: accepted and executable at the no-action planning and cohort-freeze
boundary; no real search connector has been run.

A relevance-ranked or prestige-ranked top-k list is structurally biased toward
supportive, successful, and repeatedly cited work. It can omit null results,
failed approaches, transfer boundaries, and genuine alternatives before the
content-quality method has any chance to inspect them. A hand-curated source
manifest has the same reproducibility gap when its search and stopping process
is not explicit.

SciTaste therefore compiles each current decision and its evidence gaps into six
closed query families: direct, alternative/comparator, negative/null,
failure/limitation, replication/reappraisal, and cross-domain transfer. The
model may propose bounded wording but cannot invoke a search tool. Deterministic
validation requires all registered decision patterns, contrastive evidence
roles, and domain facets and rejects prestige-ranking directives.

Completed metadata batches enter a deterministic set-cover compiler. Marginal
required coverage is primary, new source-group identity is secondary, and a
stable hash resolves remaining ties. Citation count and venue are retained only
as optional discovery metadata and are absent from priority. Held-out, self-
development, rights-blocked, or isolation-unknown candidates are ineligible.
The compiler requires registered coverage plus consecutive no-new-coverage
batches before declaring saturation. Its content-free receipt authorizes
nothing; every selected item remains an unqualified candidate for the separate
Reference Quality gate.

### ADR-090: Real reference search separates adaptive planning from deterministic admission

Status: accepted and exercised on the self-development project; source quality
and downstream effects remain unmeasured.

A model-written narrative query and a relevance-ranked top-k list were not a
sufficient implementation of Scientific Reference Mining. The first live run
demonstrated the failure concretely: broad provider matches were assigned the
query's domain labels, new paper identities prevented meaningful saturation,
and DOI/title disagreement could enter the selected cohort. Re-running search
until an attractive bibliography appeared would have mixed method repair with
a different evidence sample.

SciTaste now keeps only query wording adaptive. The accepted ledger must contain
short executable queries covering six contrastive families and registered
metadata anchors. A separate first-party connector executes a fixed OpenAlex and
Crossref schedule, forbids source-body fields, bounds request and transaction
bytes, and atomically retains every URL and response hash. Identity conflicts,
administrative records, weak title anchoring, duplicate titles, and ungrounded
domain facets fail deterministic admission. Query-family and conjunctively
grounded-domain coverage are part of readiness; venue and citation data remain
outside priority.

Selector revisions are evaluated by replaying the complete frozen transaction.
Replay receipts bind the source receipt, require zero network calls, and fail if
any recorded request is unused. Receipt schema 1.3 additionally binds the exact
NEED, PROPOSAL, CONFIG, RUN, REPORT, normalized request URL, and response bytes.
The accepted self-iteration v7 therefore shows that the connector and cohort
compiler close on content-bound real metadata; it does not show that selected
sources teach good judgment. Content-grounded Reference Quality, independent
reviewers, Taste abstraction, and matched outcome evaluation remain separate
authorization and evidence gates.

### ADR-091: Formal objective tasks inherit the powered allocation without reinterpretation

Status: accepted and executable at prelaunch, cell-plan, and result-admission
boundaries; no formal benchmark allocation or H3 outcome has been produced.

A content-addressed task-policy document can state selection rules, but it does
not prove that a later experiment used the tasks selected by the powered,
outcome-blind allocation. Allowing prelaunch to list arbitrary task IDs after
the allocation would reopen researcher degrees of freedom precisely where
resource availability or pilot familiarity becomes visible.

SciTaste therefore reserves prelaunch schema 1.5 for formal objective progress.
Its integrity contract names `benchmark_metadata_allocation`, binds the exact
allocation report file and semantic task-set hashes, and carries an explicit
source group for every task. The evaluation critic replays the complete
screening, clustered-power, allocation-plan, owner-approval, and allocation
chain, then requires exact ordered equality between selected records, manifest
tasks, source groups, and every lane population. Formal objective proposals
using the legacy policy-document semantics fail closed.

Cell-plan schema 1.3 copies both allocation bindings into its own canonical
hash, and result admission checks them again against the prelaunch contract.
This establishes identity continuity; it does not authorize source reading,
asset download, model/API use, GPU work, human review, or experiment execution.

### ADR-092: H0 selects quality and prestige arms from one immutable pool

Status: accepted and executable at planning, approval, deterministic selection,
replay, and project-surface boundaries; no formal H0 treatment or outcome has
been produced.

A prose instruction to compare “good” references with “prestigious” references
does not identify a causal contrast. It permits different candidate pools,
arbitrary prestige formulas, unmatched domains, unequal context, forced arm
separation, and post-outcome source replacement. It can also leak citation
signals into the quality policy or human quality judgments into the prestige
policy.

SciTaste therefore binds the complete metadata-mined population, its replayed
report, the source-admission report, and a one-to-one candidate/source identity
map before selection. The quality selector receives a dedicated view containing
only content-grounded admission, decision patterns, evidence roles, domains, and
source groups. It greedily closes registered scientific coverage using a frozen
hash tie-break. The prestige selector receives a different view containing only
downstream eligibility, publication year, citation count, balance stratum, and
source group. It ranks age-normalized citations inside the exact
decision-pattern × evidence-role × domain quotas induced by the quality
selection. Required strata without enough observed prestige signals fail
closed.

The plan also binds the held-out decision set, representation and execution
protocol hashes, equal sources per arm, and exact per-source and total context
ceilings. A second artifact records owner approval of that exact plan. The
report retains both selected lists, both unselected ledgers, strict stratum
parity, and natural cross-arm overlap. Overlap is not prohibited because doing
so would alter either policy; it is an observed property of the policy contrast.
Replay reopens only bounded control JSON, verifies upstream byte and semantic
hashes, recompiles the mining report, and reproduces the selection.

Generation-as-Content shows the strongest registered comparison state and its
next gate without converting selection into an effectiveness claim. None of the
four stages reads raw source bodies, materializes treatments, calls a model,
recruits reviewers, runs an experiment, or authorizes those actions.

### ADR-093: H0 arm identity continues through one common source projector

Status: accepted and executable at protocol hashing, projection planning,
approval, materialization, receipt, and replay boundaries; no real H0 source body
has been opened by this decision and no H0 outcome exists.

Freezing quality and prestige source lists is insufficient if the downstream
projector accepts only content-quality admissions. Such a projector silently
deletes the deliberately quality-blind prestige comparator. Conversely, a
separate prestige reader would create a second representation pipeline and make
field, outcome, serialization, and context differences indistinguishable from
the source-selection effect.

SciTaste therefore hashes the complete common representation protocol before H0
selection and requires the selector's downstream envelope to bind it. The
schema-1.1 projection plan replays the reference-selection chain, requires the
same source-admission file and semantic identity, and carries the exact quality
and prestige source lists plus their natural-overlap ledger. Its item population
is exactly the ordered union of both arms. Quality sources must be content
admitted; prestige sources may be quality rejected but must remain independently
audit-, rights-, and isolation-qualified in both the selection view and the
admission report.

One existing canonical projector then writes every union source once. The
receipt retains both logical arm ledgers, the protocol hash, exact upstream
binding, and overlap rather than duplicating shared bytes. Planning reads no
source body; materialization still requires exact approval and grants no
tokenizer, model, API, human-review, GPU, or experiment authority. Schema 1.0
hash semantics remain unchanged for non-H0 admitted-source projections.

### ADR-094: H1/H2 contexts compile only from a replayable treatment manifest

Status: accepted and executable at the local treatment-inspection and benchmark-
compilation boundary; no real H1/H2 treatment or outcome has been produced.

SciTasteBench v3 already required same-source raw/abstracted arms, a source-
disjoint mismatched arm, common protocol hashes, matched observed token counts,
and a construction receipt. Its curation path nevertheless treated the bound
treatment manifest as opaque bytes. A one-line file and arbitrary receipt hashes
could therefore pass structural validation even though no source projection,
Taste corpus, or tokenization trace supported the contexts.

The v3 compiler now accepts only a typed, self-hashed manifest containing the
complete case population, all three mechanism contexts, and one canonical
construction record per case and arm. Supporting files have explicit scientific
roles and content hashes. The inspector replays the self-hashed projection
receipt; matches source ID, group, locator, and content hash; checks matched and
mismatched corpus provenance and evidence tiers; parses formal-ready curation and
qualified pair reports; and validates each exact token-ID sequence against the
rendered context and tokenizer identity. Compilation then requires exact case and
context equality between the manifest and curation package.

This is an identity and provenance gate, not evidence of treatment quality or a
causal effect. It opens only declared local evidence files and grants no source
acquisition, model/API/GPU use, reviewer recruitment, experiment execution, blind
opening, or title claim.

### ADR-095: Formal H1/H2 review opens a precommitted generation ledger

Status: accepted and executable at generation-record, reviewer-manifest,
post-lock blind-opening, and analysis-admission boundaries; no real H1/H2 output,
human judgment, or effect has been produced.

The earlier blind-review contract committed X/Y ordering and prevented condition
relabeling after review, but its generation-trace fields could contain arbitrary
hashes. Consequently, a statistically correct H1/H2 analysis could still review
outputs that did not come from the compiled v3 cases and exact treatment
contexts. Treatment construction and outcome identity were separately valid but
not continuous.

SciTaste therefore adds a private, self-hashed treatment-generation ledger. Each
record binds a held-out case and source group, one of the three registered
conditions, seed and candidate order, the reconstructed benchmark request
fingerprint, treatment-construction receipt, provider/model identity, execution
trace bytes, output bytes, and generation time. Every case must contain exactly
one complete triplet with common runtime identity; one ledger cannot mix models.
The public schema-1.2 study commits the formal v3 suite and treatment-manifest
file and semantic hashes plus the ledger hash without exposing condition
mapping. The schema-1.1 opening may reveal the ledger only after the entire
primary review set is locked.

Analysis admission reloads the suite and treatment manifest, requires the exact
formal case population and mechanism contexts, reconstructs every request, and
checks that each reviewer-visible X/Y byte binding resolves to the committed
condition record. Formal schema-1.1 studies remain readable for historical
inspection but cannot enter the title gate. The ledger records prior execution;
it authorizes no model/API/GPU use, human recruitment, experiment, or claim.

### ADR-096: Blinded H1/H2 packages compile from timestamped exact recordings

Status: accepted and executable at offline materialization and CLI boundaries;
no model call, reviewer contact, blind opening, or H1/H2 outcome was performed.

The generation ledger closes identity continuity only if its hundreds of records,
reviewer artifacts, comparisons, and blind-key entries are built consistently.
Hand-authored files would shift the mismatch risk from the audit stage into
package preparation and make condition leakage through filenames likely.

SciTaste therefore compiles the package directly from one bounded,
timezone-stamped `benchmark run --record` JSONL. For a fixed seed and candidate
order, all three mechanism requests for every exact v3 case must occur once.
The compiler accepts an exact Base row, rejects foreign and duplicate requests,
and fails on missing timestamps, response/request drift, absent arms, or mixed
provider/model identities. Formal rows retain hash-verified raw response bytes,
not only a normalized rationale. Formal preparation additionally requires a
formal v3 suite whose treatment-manifest bytes and complete contexts match.

The atomic output separates `reviewer/outputs`, `public`, and `private`. Reviewer
filenames and structural fields are opaque and omit conditions, provider, and
model. The two preassigned reviewer pseudonyms receive deterministically
randomized and counterbalanced X/Y ordering. A cryptographic blinding secret is
mixed into opaque IDs and X/Y assignment, so the documented algorithm and a
default randomization seed cannot be enumerated to recover conditions. Private
per-record traces, the secret, key, and generation ledger remain condition-bearing
and must not be released until review lock. The compiler packages already
authorized execution evidence; it grants no authority to generate it or to
recruit reviewers.

### ADR-097: Formal human outcomes compile through reviewer-specific blind sessions

Status: accepted and executable at offline session, browser interaction,
submission collection, and review-lock boundaries; no reviewer has been
recruited and no real H1/H2 judgment has been collected.

A condition-hidden study manifest and opaque output files are not yet a usable
human endpoint. Asking operators to assemble forms or transcribe responses would
omit the committed case context, invite assignment drift, expose other-reviewer
state, and leave no byte-level connection between what a reviewer saw and the
review set opened for analysis.

SciTaste therefore compiles one self-contained offline HTML session per
preassigned reviewer. The compiler rechecks the exact formal suite commitment,
rubric, interface, assigned comparisons, and output bytes, then embeds only the
shared decision context and condition-free X/Y decisions. The viewport keeps
context, pair, and response controls simultaneously navigable; local draft state
never becomes research evidence. Final export requires complete responses,
rationales, missingness reasons, and explicit independence, conflict, and
blinding attestations.

The collection compiler accepts exactly two non-overlapping sessions and two
complete exports, verifies the original assignment partition, fixes the lock
time, and writes a schema-1.1 review set that binds all four source files.
Treatment-bound formal studies reject legacy unbound review sets before blind
opening. Browser timestamps and attestations remain human-reported evidence,
not cryptographic proof of identity. These tools grant no consent, recruitment,
compensation, model, API, GPU, experiment, or blind-opening authority.

### ADR-098: Formal blind opening replays collection before private evidence access

Status: accepted and executable; no real reviewer outcome or private formal
opening exists yet.

A schema-1.1 review set content-addresses its reviewer sessions and submissions,
but checking only that those four files still have the recorded hashes does not
prove that the review rows were compiled from their contents. A manually
assembled review set could otherwise retain valid file bindings while changing
a preference, rationale, duration, or lock time.

SciTaste now uses the same pure in-memory collection compiler both when locking
and when opening. The opening command first verifies the public study and visible
bytes, reloads the exact committed suite, replays both sessions and submissions
at the recorded lock time, and requires full equality with the locked review
set. Private key and generation-ledger files are not read until that replay
passes. After access, the existing condition, timing, treatment, request, trace,
and output checks must establish analysis readiness before an opening and its
input-binding receipt are written. The analysis audit repeats collection replay
from the opened ledger's bound suite path, preventing direct callers from
bypassing the command.

This is an evidence-ordering control, not a claim that the software can prevent
an authorized filesystem user from opening a private file manually. Filesystem
separation, reviewer access control, consent, and independent qualification
remain operational responsibilities. The compiler grants no model, API, GPU,
experiment, recruitment, or compensation authority.

### ADR-099: Approved method archives use the atomic streaming acquisition path

Status: accepted and exercised for pinned Agent Laboratory and DeepScientist
source archives; neither archive has been opened or executed.

The generic acquisition contract already bounded a transaction near 10 GB, but
its implementation admitted only small text records and accumulated each file
in memory. That mismatch made the owner-approved source-archive transaction
either impossible or unsafe to scale.

The default downloader now admits an explicit gzip media type and streams every
chunk directly to a newly created staging file. It enforces declared and
observed per-item ceilings while hashing, rejects redirects and content encoding,
fsyncs completed bytes, and publishes the transaction directory only after all
items and the self-hashed receipt are complete. Test fetchers retain their
bounded byte-returning interface so existing deterministic acquisition tests do
not gain filesystem or network behavior.

The transaction ceiling is decimal 10,000,000,000 bytes to match the owner's
standing policy exactly. Archive media support is download authority only: no
member listing, extraction, parsing, installation, import, execution, provider
call, GPU work, task admission, or scientific claim follows from a receipt.

### ADR-100: Source-archive inspection is a bounded, no-extraction gate

Status: accepted and exercised on the acquired Agent Laboratory and
DeepScientist archives under the project owner's standing local-read policy.

Possession of a hash-receipted tarball does not make it safe to extract or prove
which source tree it contains. Conversely, opening a downloaded archive during
adapter implementation would silently combine content-read, extraction, and
execution authority and make the unchanged-core claim difficult to audit.

SciTaste therefore freezes a source-qualification plan before content access.
The plan binds the approved request and receipt at both file and semantic hash
levels, each exact archive path/hash/byte count/commit, the expected single root,
the license identifier and license-file digest, per-member and expanded-size
ceilings, and a still-absent output root. Its first inspection streams only the
outer file hash and does not instantiate a tar reader.

A separate authority record binds read-only member qualification to the exact
plan hash; it can instantiate the owner's standing local-read instruction
without another interaction. Qualification additionally requires an explicit
local switch and never calls extraction. It admits non-sparse regular files,
directories, and only relative symbolic links that resolve directly to recorded
regular files inside the same archive root. Schema 1.1 may predeclare exact
dangling package-manager links that a later extraction proposal must omit.
Absolute, escaping, chained, missing, type-mismatched, or ancestor-conflicting
links still fail closed, as do special files, duplicate names, unsafe mode bits,
root drift, size/expansion breaches, and license drift.

The real 83,023,421-byte transaction now yields a 128,923,245-byte manifest:
Agent Laboratory contains 39 members, and DeepScientist contains 2,845. Four
DeepScientist Web UI command links point into an absent ignored `node_modules`
tree and are excluded by exact path; the remaining 2,841 members are preserved.
Even this passing result is only ready for a later extraction proposal. It
authorizes no extraction, installation, import, execution, adapter claim,
network/API action, or GPU work.

### ADR-101: Executable-task ZIP metadata has its own post-download read authority

Status: accepted and exercised with synthetic safe and adversarial ZIPs; no
real MLRC ZIP central directory has been opened.

The large-package downloader already kept extraction and ingestion false, but
its archive qualifier accepted the same approval object used for transfer. That
allowed an operator to open central directories after a download-only decision,
contradicting the project-wide rule that acquisition ends at the receipt.

SciTaste now requires a second self-hashed approval. It binds the exact request,
download approval, acquisition receipt, both file and semantic hashes, selected
tasks, all asset and aggregate byte counts, and the unpack ceiling. The approval
cannot predate acquisition and grants only ZIP central-directory and outer-byte
reads. Qualification replays the full chain and additionally requires an
explicit local switch before any ZIP object is instantiated.

The resulting schema-1.1 report records that archive metadata was read and that
no extraction occurred. A safe result still grants no extraction, ingestion,
task-layout validation, baseline execution, API/model use, GPU work, or
experiment authority. This makes the 39-asset MLRC acquisition visible as exact
but unqualified rather than either falsely missing or prematurely executable.

### ADR-102: Native condition readiness requires behavioral route attestation

Status: accepted and exercised on the deterministic repository fixture; no real
task, checkpoint, model, API, GPU, network, or formal experiment was used.

A six-row condition matrix and Git-bound source hashes prove that intended
component switches exist, but they do not prove that the complete workflow sends
actions through the corresponding controller and executor paths. A misspelled
condition, an ignored Knowledge switch, a retriever relation inversion, or a
critic that never contributes score evidence could otherwise survive a static
preflight and invalidate an expensive matched run.

SciTaste therefore has a separate local behavioral attestation. It first proves
that the production workflow, condition matrix, fixture workflow, controller,
critics, native executor, and state persistence objects are byte-identical at
the pinned source and inspected HEAD. After an explicit local-fixture switch, it
runs all six conditions through the same Discovery, Evidence, Communication,
and Figure workflow and checks observed Knowledge results, Taste retrieval,
decision counts, final blockers, component telemetry, and invariant integrity
gates. Closed two-case routing additionally distinguishes matched from
source-disjoint Taste, while a fixed readiness conflict shows critic score
evidence is absent from control and active in the critics arm.

The resulting report is implementation evidence, not empirical evidence. It
does not use acquired content, certify a real matched/placebo corpus, exercise
the Qwen checkpoint, qualify a benchmark, or estimate any Scientific Taste
effect. Those gates remain independently blocking in the campaign.

### ADR-103: Hosted-model changes create a new end-to-end Taste-path stratum

Status: accepted and bound for planning; no current DeepSeek or Zhipu call was
made and no primary model was selected.

A provider catalog can change more quickly than a research campaign. Updating
only the resource inventory is insufficient: a formally current model could
still be unreachable from the reference-mining, reference-quality, grounded
abstraction, and decision-deliberation nodes, while old callable aliases remain
embedded in profile sets. That split would either fail at launch or encourage an
operator to relabel historical model evidence.

SciTaste therefore versions the whole hosted-model path. The current resource
definition, compute catalog, project binding, temporal identity protocol,
review-followup activation, backend ceiling, and four title-critical Taste-node
profiles are content addressed as one new generation. Earlier DeepSeek V4.1
files remain readable historical strata but are absent from the current project
binding and identity allowlist. The current DeepSeek V4 Flash candidate remains
rolling, so an authenticated sentinel-bracketed conformance window is still
required before selection and a distinct window is required for formal work.

This continuity is launch correctness, not model quality or Scientific Taste
effectiveness. The profile sets select no provider, the tracked backend remains
disabled, and neither catalog facts nor a future conformance pass can substitute
for real source qualification, independent human review, or held-out outcomes.

### ADR-104: Local reads use standing authority; semantic transitions stay gated

Status: accepted and exercised on the AAAR pilot.

Repeated conversational approval for every already-local file made scientific
resource inspection a scheduling bottleneck without changing what the read was
allowed to do. The project owner therefore established one project-scoped
standing local-read policy. Readers still bind exact receipt or artifact hashes,
enforce byte/item bounds, reject links and path escape, treat source content as
inert data, and keep derivatives under the owning project. No per-artifact owner
response is required.

Read authority is intentionally narrower than semantic or external authority.
It does not permit downloads, uploads, link resolution, archive extraction,
source execution, API/model calls, GPU work, human recruitment, source
admission, or formal experiment launch. Those operations retain their existing
controller gates.

The AAAR projector demonstrates the separation. It replays the exact 16-item
receipt and passing audit, maps each source to an opaque identity, retains only
the abstract problem context, annotated experiment alternatives/reasons, and
observed experiment record, and removes explicit author, title, record, venue,
locator, acknowledgment, and bibliography signals. One source passage can carry
multiple declared semantic roles so later quality judgments can cite exact
action, evidence, outcome, or limitation excerpts without duplicating the full
paper section. The resulting inputs are ready for bounded quality proposals but
grant no admission or effectiveness claim.

### ADR-105: Structured local model nodes are a separate authority plane

Status: accepted and exercised through tokenizer-only AAAR calibration planning;
no local model generation has occurred.

Keeping licensed source content local cannot mean bypassing the model-node
runtime or disguising a local generation as a provider response. SciTaste adds a
`local-transformers` runtime mode that shares the exact structured prompt and
deterministic proposal validator with hosted backends, but has an independent
authority bit. Local execution requires profile permission, backend capability,
and caller `--allow-local`; neither zero API cost nor `--allow-live` grants it.
The backend is network-free, reports zero API cost, binds checkpoint identity,
and preserves every malformed JSON attempt for audit before emitting an invalid
empty object that the node rejects normally.

The AAAR instrument-calibration planner closes the resource join without
running it. It replays all sixteen projection identities, chooses the largest
content record and a distinct maximum-redaction record, emits exact project-
revision-bound runtime configs, and can load only the local tokenizer for true
input counts. The current plan binds Qwen3-VL-2B snapshot `47f9c0e0...`, two
inputs of 24,670 and 6,759 tokens, 8,192 maximum output tokens, one repair, one
RTX 3090, and one GPU hour. Source upload, network, API calls, model loading, GPU
generation, human review, source admission, and effectiveness claims remain
false. A successful two-record calibration can justify inspecting or expanding
the measurement instrument; it cannot support H0 or the paper title.

The Python 3.12 environment was subsequently closed under the owner's bounded
download policy: its resolved PyTorch 2.5.1/CUDA 12.4 transaction comprised 19
new wheels and 3,005,789,578 bytes, below the decimal 10-GB ceiling. Import and
device visibility are verified, but dependency readiness does not satisfy the
independent `--allow-local` execution gate.

### ADR-106: The evidence program is project content before it is interface layout

Status: accepted and exercised on the SciTaste self-development project; no
experiment, model generation, API call, GPU work, or resource mutation was
performed.

An ICLR plan spread across configs, runs, evaluation proposals, resource
records, and prose is technically traceable but not cognitively usable. The
Generation as Content project home therefore discovers only an explicitly
registered `iclr-evidence-program-v1` run and its run-owned, bounded dossier
report. The snapshot adapter hashes both the declaring run directory and exact
report; a missing, moved, malformed, oversized, or changed report fails the
whole projection rather than falling back to documentation.

The receiver collapses the 16-stage campaign DAG into seven stable navigation
phases while retaining the raw stage graph in the report. It separately shows
the Scientific Taste mechanism, native causal comparison, and external
end-to-end validity tracks because their estimands and resource confounds cannot
be pooled. Designed cells, future resources, and project blockers are presented
as planning facts; `scientific_effectiveness_established` remains false.

Fixed phase names are a receiver cache, not the generated content. The optional
model planner still chooses and composes only trusted project surfaces. Phase
exploration now reaches the proposal boundary described in ADR-107; it still
does not edit the campaign or grant execution.

### ADR-107: Generated planning content is a cached proposal, not scientific state

Status: accepted through generated proposal, iterative edit, explicit user
decision, versioned planning publication, and project-resource configuration.
Canonical campaign rewriting and experiment execution remain separate controller
boundaries.

Generation as Content needs model-authored content, not only a model-selected
layout. `ProgramRevisionService` therefore binds user feedback to the exact
project revision, snapshot hash, and ICLR dossier hash, then exposes closed
catalogs of incomplete stages, evidence tracks, project resource IDs, and
resource roles to a structured planner. Summary, rationale, and required-
evidence prose may be generated flexibly because the receiver always renders it
as inert text. The model cannot name an unregistered target, mark work complete,
remove a blocker, apply a change, authorize an external action, or execute.

Successful proposals are cached under the owning project for reuse; unavailable
responses are not cached and receive no deterministic pseudo-proposal. A user
may bind new feedback to an exact prior proposal, so the model edits the prior
planning content instead of starting an unrelated answer. Accept/reject is a
separate immutable user decision. Acceptance alone does not mutate project state.
A second explicit action publishes the accepted proposal as a predecessor-linked
project planning directive for subsequent generation without rewriting its source
dossier or authorizing execution.

The evaluation layer, rather than the UI package, owns the deterministic
effective-program compiler. It combines the exact dossier report with a neutral
control translated from the published directive. A reprioritization can permute
only the currently dependency-eligible stages; clarification, risk, and required
evidence remain typed controller guidance. The resulting program has its own hash,
records the base and effective orders, and is the source of the project home's
current stage. This makes a published user intervention consumable by SciTaste
without turning generated prose into evidence or execution authority.

The project resource portfolio is projected from the shared, content-addressed
registry without copying infrastructure or serializing credential values. For a
resource directive, one further explicit user action may compile current catalog
resources into a successor project binding by attaching each new entry to exactly
one compatible existing role and changing role-local priority. The predecessor,
exact proposal, user confirmation, registry identity, and successor hash remain
project-owned evidence; historical or disabled resources cannot be newly
attached, and the shared catalog, credentials, observations, provider state, and
execution authority do not change. This keeps Generation as Content parallel to
SciTaste as a display plane and interactive with it only through typed,
reviewable controller inputs.

### ADR-108: Verification effort is proportional to expected avoidable loss

Status: accepted and connected to the native Full Workflow Tool Intelligence
hotspot.

Blanket preflight wastes latency and compute on reversible, low-impact work.
Skipping every check is unsafe for irreversible, external, paid, secret-bearing,
or untrusted actions. The verification router therefore compares the expected
avoidable failure loss with the cost and detection probability of a targeted
check and a full preflight. It chooses the cheapest justified route from direct,
targeted check, full preflight, and owner approval while returning no execution
authority.

Irreversibility, paid compute, secret access, and external mutation remain hard
owner boundaries. Untrusted code requires full preflight plus owner approval.
Only an explicitly quantified semantic gray zone admits model advice, which must
bind the exact action fingerprint and cannot weaken a hard gate. The native Full
Workflow records this route before constructing any model/tool request; a direct
route avoids that invocation entirely. An owner-gated route is deferred before
constructing a model/tool request. The same router records that accepting or
rejecting a content-bound local planning proposal, publishing its planning
version, and applying a role-local resource-membership or priority revision take
the direct path: their minimal identity, hash, staleness, compatibility, and
lifecycle guards cost less than a generic preflight and the writes are reversible
project-local metadata. Compiling the effective experiment program is also
direct: it is a pure local derivation over already verified, self-hashed inputs.

Among optional checks, the router prefers the smallest sufficient intervention.
If a targeted check already clears the minimum expected-net-gain threshold, a
full preflight must clear that same threshold on *incremental* value over the
targeted check. A model advisory cannot introduce a declared negative-value
check or choose the lower-value check depth when both are positive; it may still
select the direct path if the semantic concern does not apply. This prevents
semantic uncertainty from becoming a generic reason to add ritual preflight.

### ADR-109: Effective gates use cost-sensitive action routing

Status: accepted and projected on the project home.

The evaluation-layer `program_action` compiler maps the effective gate's declared
external actions and owner boundary into the common Tool Intelligence effect
vocabulary. Hard authority boundaries remain hard; otherwise the router compares
expected avoidable loss with targeted- and full-check costs. The v1 numbers are
declared policy priors, not measured failure rates, and are exposed for later
calibration. The self-hashed result may recommend direct blocker resolution, one
targeted check, a full preflight, or an owner decision, but it carries no executor
or authority.

### ADR-110: Fixed entry labels may cache model authorship without replacing flexible generation

Status: accepted as an opt-in project capability and exercised once through the
current live GLM-5.3-Flash composition path; no usability or scientific-effect
claim follows from that product validation.

Generation as Content has two parallel interaction modes. A fixed project label
is a stable navigation affordance, but its evidence composition may be authored
in advance by the same bounded model planner. Free questions and feedback edits
remain fresh model interactions with bounded conversation context. The receiver
labels cached entries and otherwise preserves the on-demand path; a cache miss
never becomes deterministic content masquerading as model output.

The mutable cache index belongs below the project and points only to immutable
generated-workspace archives. Its policy binds provider, model, selected
server-issued intent IDs, TTL, and cumulative call, token, and cost limits.
Successful generations retain response telemetry. A failed or rejected call
debits the full per-response envelope because provider-side consumption may have
occurred before validation failed. Project snapshot or intent changes make the
entry stale without deleting its provenance.

Proactive warming touches the network, a secret, and paid compute, so the common
Tool Intelligence router keeps an explicit owner boundary and the CLI requires a
second execution flag. No full generic preflight is added. Reading the cache,
opening an exact archived generation, and falling through to ordinary on-demand
interaction are cheap local operations and do not acquire a new check.

An exact fresh cached generation may also be promoted into the first immutable
turn of a project-owned research conversation. Promotion revalidates project,
catalog, intent, generation, document, and expiry identities and invokes no
provider. Subsequent feedback takes the normal fresh model-edit path with that
turn as bounded context. The receiver's operating-loop map presents this content
plane beside—not inside—the SciTaste controller and routes explicit user changes
across the existing publication boundary.

### ADR-111: Project resource lifecycle is visible before model-planned attachment

Status: accepted for project resource membership and priority configuration;
shared-registry administration and scheduling remain separate.

A project cannot make an informed resource intervention when the interface shows
only resources already attached to it. Conversely, exposing every historical
provider alias or disabled backend as selectable would let a flexible model revive
stale infrastructure. Referenced compute catalogs therefore declare each entry
as `current`, `historical`, or `disabled`. All three remain visible for
provenance; only `current` resources enter the model planner's closed selection
catalog.

The project portfolio derives compatible roles from its existing bindings. A
model-authored resource revision may select an unbound current resource only when
the same draft selects exactly one compatible role. Acceptance and planning
publication still precede a distinct apply action. That compiler revalidates the
current project snapshot, binding, registry, catalog lifecycle, proposal, and
user decision; archives the predecessor; and emits a self-hashed project run. It
copies catalog identity into project membership but does not read access material,
probe or reserve hardware, call a provider, start a workload, or grant experiment
authority.

The operation is a reversible local metadata change. Under ADR-108, Tool
Intelligence routes it directly because a generic preflight has negative expected
value. Its identity, hash, staleness, compatibility, and lifecycle validations
are intrinsic transaction guards, not a separate check phase. Catalog editing,
credential-value administration, observations, connectivity qualification,
scheduling, and scientific resource selection remain independently governed
operations.

An actual provider use may advance availability only through a separately typed
resource observation and successor project binding. The 2026-09-14
GLM-5.3-Flash Generation as Content interaction records requested and returned
model identity, successful authenticated use, bounded telemetry, conversation
identity, and provider-response hashes without retaining a credential or raw
response. It verifies that project's interactive model availability; it does not
select a formal experiment resource or establish scientific quality.

### ADR-112: Costly experiment launch binds scientific intent and typed readiness evidence

Status: accepted for prelaunch schema 1.6 and external adapter preflight schema
1.1; no new experiment is authorized.

A file path and SHA-256 establish byte identity but not semantic type. Earlier
prelaunch manifests could point `adapter_preflight_ref` at a static translation
contract, and the generic artifact critic could verify those bytes without
proving that a checkout had been inspected or that an adapter was ready. The same
operational manifest also lacked an exact link to the ICLR evidence program,
allowing scientific scope and execution scope to drift independently.

Schema 1.6 binds the evidence-program file hash, semantic proposal hash, program
identity, and resource corpus. Its gate checks that every benchmark resource and
external method remains within the program's selected scope. Adapter evidence is
declared and parsed as a static contract, external preflight report, native
preflight manifest, or native preflight report. Static contracts and manifests
are proposal-only. A verified external system requires a ready preflight report
for the same resource and corpus; a verified first-party system requires a ready
native report for the same source commit.

External adapter preflight schema 1.1 separately binds the preceding static
contract by file and proposal hash. Before a checkout can be called ready, the
compiler replays code-use eligibility, contract requirement status, resource
identity, and upstream commit. A rights-blocked, incomplete, unrelated, renamed,
or drifted contract therefore cannot manufacture downstream readiness.

These checks are intrinsic identity validation at an API/GPU/human-resource
transaction whose failure cost is material. Under ADR-108 they do not justify a
repository-wide preflight or additional checks for cheap reversible actions. Old
manifests retain their historical hashes; they are not silently upgraded, and a
fresh 1.6 proposal should be created only after the bound evidence exists.

### ADR-113: External methods receive exact task bytes through an outside adapter

Status: accepted and exercised for Agent Laboratory preparation; live execution
and comparison evidence remain unavailable.

An accepted external method should not be copied into SciTaste's control path or
patched until it behaves like SciTaste. The first Agent Laboratory adapter is
therefore an outside compiler. It accepts one fixed resource corpus, translation
contract, clean Git checkout, and held-out research brief. Only tracked regular
upstream files enter a new run-owned workspace. The original brief is retained as
an immutable file and decoded into the native `research-topic` field; reloading
the emitted YAML must reproduce the original UTF-8 bytes exactly. Standard notes
state visibility and asset boundaries but contain no task-specific scientific
hint. Provider credentials never enter the configuration.

The materialized source tree is hash-equivalent to the clean checkout while the
generated configuration remains separately identified. This permits native code
to write its ordinary research directories and checkpoint files without changing
the upstream source of record. The whole workspace is retained on failure.

Preparation is intentionally weaker than execution readiness. A dependency
environment, networked filesystem sandbox, exact provider identity, closed
provider telemetry, and a scientifically qualified task population remain
required. In particular, the current MLR-Bench brief supports an ecological
research-package comparison but has no objective executable signal. This avoids
conflating an operational adapter milestone with a valid ICLR effectiveness
result.

### ADR-114: Models author semantic surfaces while receivers own integrity identity

Status: accepted and exercised through one live project conversation and one
feedback revision; usability and scientific-effect claims remain unevaluated.

Generation as Content must be flexible enough to answer an unforeseen project
question, but model flexibility does not require the model to reproduce trusted
hashes. The structured composer therefore selects only server-issued component
IDs, placements, and cited authored content. The receiver injects the exact
project, snapshot, intent, and catalog identities after schema admission, then
replays the existing candidate and evidence boundaries. This narrows the model's
task while preserving the same integrity trust boundary.

Deterministic intent recognition remains the zero-cost fast path. Any unresolved
free-form question, including one that ambiguously mentions several known
concepts, may be passed to the optional bounded classifier. It can select only a
current server-issued intent; it cannot create actions or authority. If the
classifier is absent or rejected, the deterministic clarification or no-match
reason remains visible. This prevents keyword ambiguity from making the flexible
model path unreachable.

The reading surface leads with a few recommendation, uncertainty, and finding
cards and keeps the longer synthesis collapsed. This is a presentation decision,
not evidence summarization by CSS: all displayed claims still come from the
admitted model brief and retain their evidence references. The first live
GLM-5.3-Flash exercise generated a project workspace and then edited it from
explicit user feedback. It establishes only that the interaction path operates;
it does not establish research quality or user benefit.

The two displayed planes also share one effective planning identity. When an
evidence program is registered, its compiled current stage and decision override
the manifest's historical focus extension in both the browser projection and the
model-visible digest. The manifest value remains a fallback for projects without
a compiled program. This prevents generated content from treating stale project
notes as a gate that SciTaste Core no longer consumes.

The same receiver-owned identity rule now applies to program amendments. The
model returns only change kind, current server-issued IDs, narrative guidance,
evidence requirements, optional resource choices, and eligible Tool Intelligence
advice. It no longer copies the dossier hash or safety booleans. The receiver
injects those values and validates a declared contract for each change kind. In
particular, within-stage guidance cannot masquerade as a partial gate reorder:
`reprioritize_next_gates` must retain the entire current set, while
`clarify_stage_decision` must provide no stage order. Rejections expose only a
content-free failure category and retain bounded usage accounting.

### ADR-115: Natural Taste populations are project evidence before they are benchmarks

Status: accepted and exercised with the official ARIES review-edit population;
multi-domain and human-quality admission remain open.

High-quality reference acquisition begins with natural scientific decisions, not
with model-generated pseudo-labels. The first compiler therefore binds seven
official ARIES objects to one download receipt, retains only manual review rows,
and reconstructs their observed revision evidence from source/target S2ORC
documents without extracting the archive. Direct document, reviewer, and author
identities are replaced by receipt-salted opaque IDs; email-like strings are
redacted. Source groups remain on the upstream held-out split with zero overlap.

Observed revisions and upstream alignment annotations are context, not preferred
scientific actions. Agreement and disagreement remain separate facts, and a
missing aligned edit remains visible rather than becoming a negative quality
label. The resulting 196 candidates across 42 groups clear only the declared
population floor. One machine-learning review domain cannot clear a three-domain
coverage gate, and independent scientific-quality review, decision-family
stratification, and privacy review remain explicit blockers. Project publication
therefore sets Taste-abstraction review ready while benchmark admission stays
false.

Generation as Content receives a compact whitelist of project progress facts,
including this population and its boundary, rather than a lexicographically
truncated projection. A fixed curation label may be proactively cached, while
free-form generation and predecessor-bound editing remain the primary interface.
The generated plane may rearrange the review graph in response to feedback; only
an explicitly accepted and published planning directive can influence SciTaste
Core, and it still carries no execution authority.

Tool Intelligence routes the local compiler directly. Receipt/file hashes, JSON
duplicate-key rejection, tar path/link/expanded-byte limits, split disjointness,
and atomic writes are intrinsic guards on the created evidence object, not a
separate preflight. Network acquisition, secret use, paid compute, benchmark
admission, and human labels retain their own authority boundaries.

### ADR-116: Flexible generated control normalizes provider variance without weakening evidence admission

Status: accepted and exercised on the multidomain self-development source gate;
human usability and scientific effectiveness remain unevaluated.

The second natural source path uses the official F1000Research API to freeze
exact first/later version groups with their reviews and observed author replies
from two publisher-subject strata. It broadens candidate evidence, but subject
membership, recommendations, replies, revisions, and publication remain
non-gold. Structured identities are removed locally, while independent domain,
quality, decision-family, privacy, and Taste-abstraction review remain required.
The resulting 77 episodes from 39 groups therefore enter project planning but
not the benchmark or admitted Taste memory.

A live Generation as Content pass exposed ordinary structured-provider variance:
the model repeated the trusted candidate's display component in an otherwise
valid entry and supplied visual focus references broader than that entry. The
receiver now removes only an exactly matching redundant component echo,
intersects visual focus with the selected candidate's evidence, and binds edit
lineage to the latest trusted model-authored predecessor. Unknown or mismatched
fields still fail closed, and authored brief/canvas claims still require exact
admitted evidence citations. This keeps semantic layout flexible without asking
the model to reproduce receiver-owned integrity facts.

The feedback request also legitimately contained the bounded project digest,
schema, and predecessor page. A 64,000-byte transport ceiling rejected it before
the configured 32,000-token input budget was reached. The ceiling is now 128,000
bytes, aligned with that token envelope; the independent 8,192-output-token,
response-byte, latency, and cost limits remain. Oversize rejection is a reactive
admission guard with its own reason code, not a preliminary call or generic
preflight.

Tool Intelligence likewise sends the reversible local F1000 compiler through
`direct_path`. XML/node/byte bounds, content hashes, privacy transformation, and
atomic publication run inline because they define the evidence object itself.
Paid provider generation retains its declared per-call bounds, and GPU or formal
experiment launch still stops at owner approval. The successful feedback turn
edited an exact predecessor into a five-node project decision flow; it is a
product dogfood observation, not proof that the model's plan is scientifically
correct.

### ADR-117: Approved evaluation plans execute through one project-owned campaign ledger

Status: accepted for exact-cell execution; formal SciTaste evidence remains
uncollected.

The evaluation subsystem previously ended its automated path at a no-run
`EvaluationCellPlan`, while the older matched-study runner used a different
protocol type. Consequently an approved current proposal still needed an
untracked operator loop to translate cells into commands, collect results, and
decide what could be resumed. SciTaste now executes the registered evaluation
type directly. The campaign identity binds the project evaluation bundle,
proposal, cell plan, launcher configuration, and selected cells before any
adapter starts.

The runner has no design or approval authority. It reopens the exact registered
artifacts and will not create a run unless the proposal is execution-authorized,
owner-approved, preparation-ready, and covered by a compatible shell-free
launcher. Each adapter sees one content-bound cell request; only explicitly
declared environment variables cross the process boundary. The runner owns
elapsed time and GPU allocation, requires complete API counters, enforces
per-call and cumulative cell ceilings, hashes every retained artifact, and turns
budget excess into a failed measured cell rather than a successful result.

Every attempt publishes a checkpoint before it enters the aggregate result set.
Resume revalidates that checkpoint and skips successful cells; a failed cell is
retried only under an explicit retry instruction, with its preceding request,
logs, result, and evidence moved into an immutable attempt archive. The resulting
raw `EvaluationResultSet` intentionally contains neither invented comparisons nor
reviews. Its next authority boundary is the already preregistered objective
analysis or condition-blinded human-review workflow. Thus automation removes
manual experiment bookkeeping without weakening the scientific separation
between execution, inference, review, and claim admission.

### ADR-118: Formal task cells receive a content-bound model-visible workspace

Status: accepted for source workspace materialization; autonomous benchmark
iteration and held-out execution remain pending.

The campaign ledger previously knew which task a cell named but not which bytes
the research agent could see or edit. Reusing an external benchmark agent would
also import its file and process authority into SciTaste. A formal task runtime
specification now binds the exact upstream repository commit, clean checkout,
task and visible roots, visible-tree digest, research brief, read-only and
environment manifests, editable globs, controller-owned dataset directories,
writable output directories, separate
development and held-out commands, hidden-test materialization paths, objective
metric, baseline scores, and acquired archive/license evidence.

Inspection is non-mutating and reports source drift, unsafe tree entries, empty
edit surfaces, hidden-test leakage, bounded-tree violations, evidence mismatch,
and the independent readiness state of source, archives, licenses, ingestion,
environment, and scorer. Source-only materialization requires a separate explicit
flag, copies only the model-visible tree into a new cell-owned directory, marks
every non-editable file read-only, creates only declared output directories, and
publishes a portable self-hashed receipt. The receipt separately binds the
protected source surface so later dataset/output writes and admitted source edits
cannot mask changes to evaluation code. It does not extract datasets, install
the benchmark's pinned external Python environment, call a model, or execute a
development or held-out command.

SciTaste therefore owns the future research loop and its authority boundary;
MLRC-Bench supplies frozen task bytes and objective scoring semantics only. The
benchmark's Python 3.10/3.11 environment versions are task-local external
runtimes and do not widen SciTaste's Python 3.12 support target. Held-out bytes
must remain absent while ideas and patches are selected, and may be introduced
only by a later scorer-owned transition after the candidate is frozen.

### ADR-119: Research models propose bounded source transitions or stop

Status: accepted for proposal and mutation; development execution remains
pending.

A real autonomous-research loop needs model judgment inside the cell, but giving
the model a shell, patch command, or unrestricted repository would merge
scientific choice with execution authority. The `benchmark-research-patch` node
therefore receives only an exact caller-selected snapshot of editable UTF-8
files, objective metric and development scores, remaining experiment count,
hard constraints, and separate experiment-feedback, utility-policy, Knowledge,
Taste, and critic channels. That separation lets
the registered native conditions vary the intended mechanism without changing
the executor.

The node may either propose complete replacement text for files already present
in its snapshot or stop because another development experiment is not justified.
It cannot name commands, dependencies, held-out material, resource policy, or
execution. A controller-owned proposal binds the model ledger identities,
context, policy, task, predecessor surface, and iteration. Deterministic
admission then rejects stale predecessors, paths outside the exact editable
surface, no-op or oversized replacements, forbidden file types, and invalid
Python/JSON/YAML syntax.

Applying an accepted proposal is a separately authorized, rollback-capable
multi-file transaction. All replacements are staged before the first source
transition; any failure restores preceding bytes. The resulting portable,
self-hashed receipt binds before/after editable surfaces and explicitly states
that no model or benchmark was executed by the mutation step. Development
execution, score parsing, best-candidate selection, and held-out scoring remain
separate later authorities.

### ADR-120: Development feedback uses an objective-only isolated entrypoint

Status: runtime accepted; first real MLRC development execution pending resource
activation.

Calling the benchmark's original `main.py` on its test phase would also invoke
its code summarizer and LLM judge, which is not the preregistered objective
endpoint and could leak provider variance into the result. SciTaste therefore
ships a hash-bound, dependency-free MLRC entrypoint that imports the frozen task
implementation and calls only training, inference, and the benchmark's objective
scorer. It emits exactly one typed development-result marker and explicitly
records that no secondary LLM judge ran. The Meta-learning route also replaces
the upstream shell-based output cleanup with bounded filesystem operations and
shell-free subprocess arguments.

The development runner requires an execution-authorized request bound to the
campaign, owner approval, task spec, workspace receipt, current editable-source
hash, task-local runtime profile, and campaign resource-verification receipt. It
mounts the task workspace read-only in Bubblewrap, overlays only declared output
directories as writable, mounts prepared development data read-only at declared
dataset paths, exposes no API credentials, unshares the network, and meters wall
and GPU time. A successful result requires one valid objective marker plus
unchanged protected and editable source surfaces; artifacts and logs are bounded
and content-hashed.

Full content verification of multi-gigabyte datasets and runtime trees happens
once before a campaign and produces a reusable receipt. Individual read-only
cells bind that receipt and still check device availability and source integrity,
but do not repeat full dataset hashing before and after every experiment. This is
the Tool Intelligence cost rule applied to verification: repeat a check only
when its expected failure cost exceeds the repeated verification cost or the
underlying authority boundary has changed.

### ADR-121: Development search retains the best candidate under compiled conditions

Status: accepted and integrated; real resource activation remains pending.

The source proposal, mutation, and development runner previously existed as
separate authorities, so a human still had to decide which result became the next
model context and restore a worse candidate. The benchmark research controller now
executes one development-only sequence: measure the untouched baseline, ask the
durable `benchmark-research-patch` node to propose or stop, admit and atomically
apply an exact replacement, execute the objective-only development command, and
retain the candidate only when its directed improvement exceeds the registered
threshold. Failed or non-improving candidates are restored to their exact
predecessor bytes before another decision. Output directories are moved into the
iteration evidence tree and recreated empty, so later trials cannot consume stale
artifacts.

The model-node runtime supplies request/response hashes, token and cost telemetry,
cumulative budgets, interrupted-call recovery, and a proposal-only authority
boundary. The controller independently checks the returned execution receipt and
the real source surfaces. A self-hashed cell binding is derived from the selected
authorized campaign and fixes project, evaluation, campaign, plan, cell, system,
task, resource, seed, and author-approved evaluation-bundle identities before the
loop starts. It writes a complete iteration record before proceeding, counts
unverifiable executor attempts separately, and never invokes or materializes
held-out evaluation. The final result identifies the best development surface and
the campaign adapter now owns the later freeze and one-way scorer transition.

Condition assignment is no longer a collection of caller-authored prompt strings.
One content-bound guidance set registers utility policy, raw Knowledge, matched
Taste, source-disjoint mismatched Taste, and critics together with their derivation
evidence and the exact six-arm condition matrix. A deterministic compiler projects
only the components permitted by Base, Knowledge, Taste, Critics, Full, or the
mismatched placebo. Missing channels are explicitly disabled and the model is told
not to reconstruct them. This closes the software isolation needed for a causal
prepilot, but does not claim that current guidance assets are reviewed, paired, or
ready, and it authorizes no API, GPU, dataset, or held-out use.

### ADR-122: Hidden-test scoring begins only after an immutable candidate freeze

Status: accepted and integrated; no real cell has been authorized or executed.

An evaluation cell is not successful merely because its development loop found a
better candidate. The first-party native benchmark adapter now binds the exact
campaign manifest, plan, cell, system, task, model profile, condition matrix,
five-channel guidance set, and separate development and held-out execution
profiles. Development resources must omit every declared hidden path. After the
loop stops, a self-hashed candidate record binds the winning source surface, its
development receipt, and only the winning output artifacts explicitly required
by the scorer. The held-out resource profile is materialized after this record
exists and must contain every declared hidden path.

Held-out execution has a separate request whose authority is test-only: source
mutation and model invocation are both false. It restores any frozen scorer input
such as the Perception checkpoint, runs the fixed objective entrypoint once in the
same no-network Bubblewrap boundary, rejects source drift, and archives its logs
and outputs. The Meta-learning scorer changes validation cardinality only in a
temporary scorer-local method copy; it no longer edits and restores the frozen
workspace. No adapter code path invokes the research model after candidate
freeze. A raw task measurement records the original held-out score, baseline,
metric direction, and directed progress; the legacy count-oriented `StudyOutcome`
is retained only for campaign compatibility and is not the scientific endpoint.

Large task/runtime/model resources are fully hashed when first materialized for a
campaign. Later read-only cells reopen the small profile record and bind the
campaign verification receipt instead of rehashing multi-gigabyte trees at every
iteration. This optimization does not bypass the initial content check, task
source checks, cell identity, or source postconditions.

Generation as Content remains outside this executor. Its stable read seam is the
campaign/loop/freeze/measurement evidence chain, and its write seam is the
existing typed project-program revision submitted before launch. It may explain
or propose a plan change, but it cannot enter the hidden-test process, mutate a
candidate, or grant model/data/GPU/API authority.

### ADR-123: Acquired archives become two isolated data views in a separate transaction

Status: accepted; first real Perception mapping is owner-review-ready and has not
been executed.

An acquisition receipt proves downloaded bytes, and an archive qualification
proves that ZIP metadata is safe. Neither proves that archive members were mapped
to the paths expected by a task, nor prevents hidden labels from entering the
model-visible development data. SciTaste now represents archive ingestion as a
third, independently approved transaction. Its request binds the acquisition and
qualification semantic hashes, the task's ingestion-license evidence, the exact
runtime spec, every asset hash and size, each member count and expanded-byte
total, and the final target of every archive.

The transaction publishes `development/data` and `heldout/data` together or not
at all. Development targets must be disjoint from every hidden path. Held-out
targets must equal the runtime spec's complete hidden-path set rather than merely
containing a caller-selected subset. During extraction, every source ZIP is
rehashed, only regular non-encrypted members with the declared flat layout are
streamed, per-asset and aggregate byte ceilings remain active, and neither source
archive is changed. The published views are read-only and carry the same
path/size/file-hash digest used by `NativeExecutionProfile`, so later profiles do
not need an informal conversion step.

The approval grants only local extraction and task-data ingestion. It explicitly
withholds environment installation, model calls, GPU work, benchmark execution,
and scientific claims. The receipt repeats those negative facts. Perception is
the first real proposal: six train/validation archives form the development view
and three test archives form the scorer-only view. Meta-learning remains blocked
at its separate AWA license boundary and cannot inherit Perception's authority.

### ADR-124: Formal native conditions identify representation before components

Status: accepted; executable contract implemented, real treatment content not
yet curated or launched.

The original six-condition native matrix was built to prove component routing
and diagnose sufficiency. It cannot identify the paper's abstraction claim:
`native-knowledge` supplies raw Knowledge, while `native-taste` simultaneously
adds both matched Taste and the Utility policy. A difference between those arms
would mix reference representation with policy changes. More seeds would not
repair that confound.

SciTaste keeps the six-arm schema 1.0 matrix for compatibility and introduces an
independent schema 1.1 confirmatory matrix with exactly five conditions: Native
Base, same-source Raw RAG, matched abstracted Taste, source-disjoint mismatched
Taste, and Full SciTaste. The three reference-mechanism conditions keep Utility
and Critics off. Raw RAG versus matched Taste changes only representation;
matched versus mismatched Taste changes only source-domain relation. Full versus
Base estimates the complete Scientific Taste bundle.

Formal guidance must carry the existing `MechanismContextBundle`, not merely
three plausible strings. It requires identical ordered source identities for
Raw RAG and matched Taste, complete source disjointness for mismatched Taste, and
parity in tokenizer identity, retrieval query, rendering template, source count,
observed tokens, token ceiling, truncation, provenance/curation tier, and outcome
availability. Old guidance cannot be attached to the formal matrix. Knowledge-
only, Taste-plus-Utility, and Critics-only cells remain optional diagnostics and
do not inflate the confirmatory allocation.

### ADR-125: Native Taste claims bind three directional contrasts, not one star topology

Status: accepted and implemented; first real five-arm feasibility block remains
resource-gated.

The generic claim contract originally required every contrast to share the Full
SciTaste candidate. That representation was appropriate for external-system
comparisons and the earlier bundle-oriented diagnostic, but it could not encode
the causal graph in ADR-124. In particular, `full-scitaste` versus
`raw-source-rag` changes several policies at once and cannot estimate whether
abstraction improves on the same source content.

The `native_taste_mechanisms` estimand therefore admits exactly one closed
five-system lane and three confirmatory directional contrasts:
`full-scitaste` versus `native-base`, `matched-abstracted-taste` versus
`raw-source-rag`, and `matched-abstracted-taste` versus `mismatched-taste`.
Their registered roles are respectively complete-bundle, reference-
representation, and source-domain-relation evidence. Every system must occur in
the contrast graph, every non-Full system remains a first-party ablation under
one matched backbone, and all three comparisons must pass the same multiplicity
family before the native Taste title claim is eligible.

Legacy native and external estimands retain their common-candidate rule. The
cell planner, objective analysis, failure-inclusive input hashes, and result
admission already operate on each contrast's own candidate/comparator pair, so
the new estimand removes the upstream schema confound without introducing a
second analysis path. A one-task five-cell run remains feasibility evidence
only; it can resume the exact cells and measure runtime/failure behavior, but it
cannot satisfy the preregistered multi-task claim.

The first executable proposal using this contract is the unapproved
`native-taste-mechanism-prepilot-v12` design. It fixes five first-party systems,
two candidate tasks, the local Qwen3-VL-2B checkpoint, and an executable
objective-score contract. Authoring these bindings did not materialize task
data, prepare a runtime, load the model, occupy a GPU, or execute an outcome.

### ADR-126: Pilot activation is a complete task block and objective closure is automatic

Status: accepted and implemented; the first real activation remains unapproved.

A multi-task pilot can contain one task that is executable before another task's
license or assets are ready. Requiring whole-proposal readiness prevented useful
feasibility evidence, while the old `--cell-id` selection could expose a single
condition before its controls and permit adaptive continuation. SciTaste now
uses a distinct feasibility activation: it recompiles every plan cell for one or
more selected tasks, fixes their ordered tasks, lanes, systems and cells, sums
their GPU/API/token/storage ceilings, and requires owner approval over that exact
hash. A normal claim-bearing campaign must still select the complete plan.

The activation is accepted only for a pilot with an objective endpoint, a clean
registered source identity, schema-1.6 typed native preflight reports, and a
content-bound objective-outcome contract. Every selected cell must independently
be ready. The resulting campaign manifest records the activation hash and
`claim_authority=false`; completion routes to feasibility review even when all
five cells succeed and can never enter confirmatory analysis. Failed feasibility
cells remain retained observations and do not trigger an automatic retry.

For native objective campaigns, the adapter's scorer-owned
`OBJECTIVE_MEASUREMENT.json` is no longer a manual handoff. The campaign runner
verifies its result-record hash, cell/task/condition identity, metric, direction,
baseline and project-owned bytes, then compiles the generic measurement set.
When the entire claim-authorized task population is complete, it executes the
already bound task-clustered estimator, freezes the analysis and completed result
set, and routes only registration. Resume recomputes and verifies these derived
objects instead of overwriting them. Generation as Content consumes this ledger
through its existing read seam and may submit only a pre-launch typed program
revision; it has no experiment or claim authority.

### ADR-127: Idea revision invalidates downstream Taste supervision and experiment freeze

Status: accepted; revision binding and cross-channel candidate contract
implemented, with reviewed policy estimation continued in ADR-128.

The self-development case showed that an experiment can be mechanically ready
while the scientific thesis is still being revised. Treating the Idea as prose
would let an old ablation matrix continue running after the learned object,
hypotheses, or claim boundary changed. SciTaste therefore reads the project's
current Idea revision as a content-bound scientific contract. Its record,
narrative, and declared evidence inputs are rehashed before a downstream binding
is issued. Candidate revisions may guide method development, but they cannot
freeze a title-level experiment or grant paper claim authority. Unrelated project
updates do not invalidate the binding; selecting different Idea bytes does.

Scientific Taste has one supervision object across three channels. An external
source miner proposes a grounded precedent; Tool Intelligence's process miner
proposes an interpretation of a real internal decision and delayed outcome; and
Generation as Content records a typed, user- or project-scoped correction. Every
`TasteEpisodeCandidate` closes the alternative set, chosen action, state,
evidence, outcome horizon, separated hypothesis/design/execution/adaptation/
claim/review/communication signals, causal-credit hypothesis, confounders,
transfer/failure conditions, and reversal probe. Human interventions may remain
in an explicit awaiting-outcome state.

All three producers have the same negative authority: their output is not
canonical evidence, is not retrieval-eligible, cannot update the policy, and
cannot execute an action. Taste Core verifies the bytes and current Idea binding,
then may send an outcome-bearing candidate to independent review. Later work must
demonstrate that the ADR-128 reviewed outcome-attribution and estimated policy
path changes held-out decisions on natural trajectories. The existing five-arm
native design is retained as a representation and specificity mechanism slice,
but it cannot alone establish lifecycle-policy learning or trajectory credit.

### ADR-128: Outcome-reviewed episodes estimate preference and abstain outside support

Status: accepted and implemented on authored fixtures; real longitudinal evidence
and held-out effectiveness remain open.

An executed action is not a reward label. Success may be accidental, a failed
probe may still be the correct decision, and an authored expected-value field is
part of the original judgment rather than independent evidence for that judgment.
SciTaste therefore makes outcome attribution a reviewed scientific object. A
schema-1.1 episode records action types and tags while retaining the full
alternative set, exact delayed outcomes, confounders, credit hypotheses, and
Idea revision. Schema 1.2 additionally freezes the source project or external
relationship, source group, and dataset partition before review. Self-project
evidence is development-only, and a formal-held-out partition is structurally
excluded from policy training. Generation as Content remains the intervention
producer when a process miner later joins an outcome; the two identities cannot
be collapsed. Schema-1.0/1.1 episodes remain replayable under their original
hashes, but an attribution without the new sampling identity cannot enter the
new training path.

Two distinct, conflict-cleared primary reviewers must independently accept the
same preferred action and at least one shared credit assignment. A split verdict
or preference requires one distinct adjudicator; two rejections close the
episode. Neither the episode producer nor the attribution producer may review
the record. Admission freezes the candidate, decisive review identities,
supported credit, and conservative minimum confidence into a self-hashed episode.
Admission grants training eligibility only: it does not silently mutate a
running controller or authorize an experiment.

The replayable first estimator is `factorized-beta-pairwise-v1`; the current
estimator is `signed-factorized-beta-pairwise-v2`. The legacy field
`preferred_action_id` identifies the action receiving reviewed causal credit.
Beneficial credit compares it as the winner against every alternative; harmful
credit compares it as the loser. Mixed-sign admissions fail closed. Total
confidence weight is divided across alternatives, and all decisions from one
source trajectory share at most one source-group unit of weight, so neither a
large authored candidate set nor a long trajectory can masquerade as independent
sample size. Independent Beta posteriors estimate action-type,
stage-action, domain-action, venue-action, tag, and stage-tag features. The
explicit update modes—outcome-updated, no-update, unambiguous success-only,
unambiguous failure-only, and deterministically shuffled credit—are experimental
conditions rather than hidden flags. Mixed or unresolved
outcomes cannot leak into the success/failure controls. Source/training episode
identities, priors, posterior counts, and policy bytes close under content
hashes. Because these factor features originate from the same episode,
assessment uses a fully
correlated uncertainty upper bound rather than treating feature count as sample
size.

Policy schema 1.1 records the composite source-group keys and their effective
training weight. Schema-1.0 policies remain hash-replayable, but do not acquire
the newer independence claim retroactively.

Execution-only credit is excluded from the scientific policy by default; an
explicitly separate configuration may study operational policy without mixing
it into the title-level estimand. At decision time only feasible actions are
scored. The caller must supply the currently verified Idea binding; a missing or
changed Idea forces abstention.
Cross-domain transfer is off by default, stage support can be required, and
insufficient support, low pairwise probability, or a credible margin crossing
zero likewise forces abstention with zero score adjustment. When the policy
applies, adjustments are centered and bounded before entering the existing
controller; hard budget feasibility remains unchanged. The decision log binds
the policy, policy and observed Idea revisions, candidate set, assessment,
reasons, and per-action adjustments. Current scope matching is intentionally
exact and structured. Semantic boundary transfer, natural episode reconstruction,
independent real review, calibration, and held-out H1--H4 effects are not implied
by the fixture-level implementation.

### ADR-129: Trajectory reconstruction preserves decisions without inventing rewards

Status: accepted and implemented; delayed scientific-outcome collection remains
open.

A continual policy cannot learn honestly by scanning old successful runs. That
would select on observed outcomes, blur trajectory dependence, and turn executor
completion into scientific reward. SciTaste therefore freezes a self-hashed
trajectory sampling plan before attribution review. The plan binds the current
Idea revision, owning and source projects, source run, natural source group,
dataset partition, assignment timing, decision-log locator, and a bounded state
snapshot search root. The project CLI checks that a prospective source run does
not yet exist; retrospective sources must already exist and are development-only.

Reconstruction is read-only. It hashes each exact JSONL line, parses the complete
candidate set and selected action, and resolves the referenced pre-decision state
from content-addressed snapshot directories anywhere below the declared root.
Duplicate state copies are accepted only when their bytes agree; unsafe paths,
symbolic links, malformed identities, stale Idea bindings, and unbounded trees
fail closed. Missing states and one-action decisions remain visible as gaps.

The resulting inventory records executor-result identity, status, and exact
outcome bytes only as operational provenance. It sets both
`scientific_outcome_labels_created` and `policy_training_authorized` to false.
Only a prospectively frozen, state-verified, multi-alternative, executed decision
becomes a foundation awaiting separately evidenced delayed scientific outcome
and reviewed causal credit. A real retrospective self-development replay exposed
one valid comparative decision and one missing intermediate state; both remained
audit-only. This is implementation evidence for the reconstruction boundary, not
evidence that Scientific Taste improves research.

The capture path is now also first class: after a pre-source plan is frozen and
that exact source run is registered, `taste capture-prospective-decision` writes
the content-addressed state and append-only decision line. Its receipt binds the
current project revision, current Idea, executor outcome, and exact stored bytes.
It cannot label delayed scientific success or make the record training-eligible;
those authorities remain in the independent outcome-attribution and admission
stages.

That original command remains replayable as schema v1, but it cannot establish
temporal separation because its decision line already contains the executor
outcome. Schema v2 therefore uses `taste lock-prospective-decision-v2` before
execution. The lock rejects either post-execution field, requires at least two
non-duplicate candidates, and hashes the full menu, exact selection, rationale,
decision time, state snapshot, append-only line, and a separate write-once record.
Only `taste attach-prospective-outcome-v2` may later bind an executor result,
strictly later observation time, and run-owned outcome evidence. It emits a
self-hashed attachment and completed projection while replaying the unchanged
predecision bytes. Neither artifact grants policy authority.

Once a downstream observation exists, the process miner seals a proposal that
names its outcomes, causal-credit hypothesis, confounders, applicability and
failure boundaries, and run-owned evidence locators. The compiler replays the
plan, capture, inventory, exact decision line, and state binding before hashing
the evidence and producing a quarantined `TasteEpisodeCandidate`. The proposal
is not a review: the existing cross-model attribution panel must still accept or
reject its causal interpretation before admission can authorize a policy update.
That panel may combine a live provider with a separately pinned local checkpoint;
both paths use the same semantic packet and durable ledger, and neither is
represented as human review.

### ADR-130: Venue deadlines are project state, not remembered dates

Status: accepted and implemented.

A research controller cannot trade off engineering polish, evidence collection,
writing, and external submission reliably if the venue clock lives only in a
human's memory or a transient UI. SciTaste therefore assigns one immutable,
self-hashed `ProjectVenueSchedule` to the revisioned project manifest. Every
milestone has an explicit timezone, required outcomes, source, hard/soft status,
and external-action boundary. Hard deadlines must reference an authoritative
venue source. Community deadline aggregators remain useful calendar indexes but
cannot override the venue record.

`ProjectDeadlineStatus` is a time-relative, self-hashed projection rather than a
mutation. It records the observation time, next unfinished milestone, exact
remaining seconds/hours/days, urgency, required outcomes, and a deterministic
`defer_noncritical_work` signal. The first policy marks seven days or fewer as
critical, fourteen or fewer as urgent, and thirty or fewer as active. Expired
milestones remain visible; a clock crossing zero cannot silently advance the
project.

Registration and submission happen outside SciTaste. The runtime advances a
milestone only after an explicit owner attestation binds a regular non-symlink
project file and its SHA-256 digest into a new optimistic project revision. This
does not prove acceptance or paper quality, but it prevents the scheduler and
generated interface from confusing a planned external action with a completed
one. The ICLR 2027 profile records the official abstract and paper deadlines and
retains CCFDDL only as a secondary index.

### ADR-131: Lifecycle Taste is an every-round intervention, not a condition label

Status: accepted and implemented; real H4 artifacts and execution remain open.

H4 estimates the intention-to-treat effect of a learned lifecycle policy on
held-out objective progress. Both arms therefore receive the same task, Full
SciTaste static guidance, patch model, prompt, seed schedule, tool/repair policy,
execution profiles, scorer, and budget. The only treatment is lifecycle-policy
weight: one in the treatment arm and zero in the control arm. The retained
legacy condition ID `native-base-without-learned-taste` means lifecycle-policy
off only; the schema-1.2 matrix prevents it from being mistaken for a Base
system because both arms still contain the same Knowledge, Taste precedents,
utility policy, and critics.

The intervention occurs on every development round. A deterministic fixed menu
offers high-level PROBE, PILOT, EXPERIMENT, ANALYZE, REFINE, PIVOT, and STOP
actions. Intrinsic `TasteController` selects one under the frozen policy with
the generic stage critic disabled, because that critic contains stage-specific
priors against otherwise valid H4 actions. Only a sanitized action ID, type, and
instruction reach the common patch model. Policy scores, rationale, request IDs,
and request fingerprints remain audit-only. STOP ends the loop without a model call;
every other selection requires exactly one proposal, so the patch model cannot
become a second stopping policy or widen the search budget.

### ADR-133: Deadline pressure compiles the work order, not just a countdown

Status: accepted and implemented.

`ProjectDeadlineStatus.defer_noncritical_work` previously reached the project UI
without deterministically changing Core scheduling. SciTaste now separates an
editable `DeadlineWorkPlanDraft` from a snapshot-bound `DeadlineWorkPlan`, then
compiles both with the exact time-relative deadline status into a
`DeadlineRoutedWorkProgram`. Work items declare dependencies, effort, evidence
gain, next-milestone outcomes, and claim, submission, or release criticality.
Under critical pressure the compiler admits only ready critical-path work to the
immediate queue and explicitly defers noncritical polish and non-release checks.

This is scheduling evidence, not execution authority. It cannot contact a
provider, reserve a GPU, mutate an external service, or attest submission. The
deadline route sits upstream of Tool Intelligence: Tool Intelligence chooses the
smallest justified check for an admitted action, while the deadline compiler
prevents low-value actions from reaching that stage.

Before baseline execution, model contact, or editable mutation, the adapter
loads one protocol-level H4 profile, a canonical outcome-blind five-state probe
contract, and a passed deterministic manipulation report. The contract freezes
the controller seed; report margins and dispositions are recomputed from the
observations, and the adapter replays the complete probe before accepting exact
report equality. It then exclusively
writes an arm request, which breaks the profile/campaign hash cycle by binding
the actual campaign/cell only after the campaign exists. The request also binds
the accepted Idea, task bytes, canonical
held-out identity, source partitions, workspace surfaces, dev/held-out resource
records, model profile, prompt, node policy, decoding configuration, and budget.
The repository must be clean at the frozen commit and tracked-tree hash. Static
guidance sources, policy sources, and held-out tasks must be canonical and
pairwise disjoint. Formal multi-task execution uses one guidance/mechanism-context
binding per task. The complete campaign's worst-case calls, tokens, and cost are
reserved before the first model call so arm order cannot exhaust a later arm.

Every baseline and decision record carries its arm request, predecessor receipt,
post-iteration state, source surface, and a self-hash. The final objective binds
that loop chain. Development, proposal, held-out, adapter, timeout, or process
failure remains an observed cell under a preregistered task-specific worst bound
rather than disappearing from analysis. Every failure has a typed terminal
outcome receipt whose stage, error, predecessor, failure artifact, and resource
use are replayed by the collector. The same validation is invoked by the public
analysis and result-registration route; it closes the arm request, loop, frozen
candidate, held-out request and receipt, raw score, terminal, and measured or
conservative usage instead of trusting a caller-supplied measurement set. A pair
artifact then joins the exact on/off
arm requests and measurements for the same task, seed, and repetition, reports
the on-minus-off effect, and is persisted inside the objective measurement set.
A project evaluation may register only one claim-authoritative H4 primary
attempt; additional campaigns must be explicitly non-claim sensitivity runs.
That primary-attempt lock is preceded by a no-execution preparation replay.
The formal launch config binds `PREPARATION.json`, which in turn binds the exact
on/off launchers, adapter configs, selected H4 cell population, accepted Idea,
repository identity, state-probe artifacts, lifecycle policy, and a policy
reproduction report. Policy reproduction re-runs every AI-reviewed episode
admission against the original evidence and panel contract, then refits the
schema-1.5 outcome-updated policy and requires exact equality. This prevents a
caller from making a hand-built posterior look eligible merely by setting its
derived flags. The campaign validates this chain before registering or resuming
a project run. A stable Idea scientific-contract hash excludes incidental
project revision/snapshot counters but retains the exact Idea revision record
and artifact hashes, so bookkeeping updates neither invalidate the experiment
nor weaken scientific-change detection.
The formal launcher is an absolute isolated Python process whose bootstrap pins
`<repository>/src` ahead of installed packages. Its inherited environment is
limited to the proposal's API-key variable, and its GPU count must equal the
proposal resource. Registering a formal primary campaign reserves the unique
run even before treatment contact, so an abandoned pre-treatment run may resume
but cannot coexist with a second primary run. After an arm request exists,
resume first reconstructs that entire request from the frozen adapter, condition,
task, pristine workspace, development and held-out resource receipts, model
profile, policy, and campaign. A missing or invalid checkpoint is not repaired
around an old result: the partial bytes are retained and the verified exposure
is closed as a preregistered worst-bound ITT failure. Exposure also sets the
project run's consumed marker, and result registration requires that marker plus
the exact schema-1.2 campaign, launch config, and preparation provenance.
Any claim containing an H4 system requires executable comparison schema 1.2 and
must reproduce the registered analysis. Conservative API/GPU terminal ceilings
are derived exactly from the planned cell and arm iteration limit, including
failures before a loop exists; measured usage must agree with the loop and stay
inside the same authority.
These controls create formal-evidence infrastructure; they do not create a
favorable effect, validate the learned policy, or authorize a real experiment.
All independent reviews used during implementation are explicitly AI reviews,
not human or expert judgments.

### ADR-132: Scientific Taste is family-conditioned, not one pooled preference

Status: accepted and implemented through project-owned refresh; a sufficiently
supported scientific episode population and formal effects remain open.

A single lifecycle preference table can combine incompatible judgments. Choosing
a worthwhile question, selecting a diagnostic experiment, allocating a final
model call, calibrating a claim, transferring a precedent, and communicating an
argument are all scientific decisions, but evidence that teaches one does not
automatically teach the others. SciTaste therefore defines seven decision
families: scientific value, epistemic discrimination, empirical diagnosticity,
adaptive allocation, inferential discipline, transfer and correction, and
scientific communication.

An admitted episode enters exactly one family through a self-hashed assignment.
The assignment requires two isolated AI primary reviews over the fixed ontology;
agreement forbids an unnecessary adjudicator, while disagreement requires exactly
one distinct AI adjudicator. Reviewer, invocation, model, rationale, and raw
response hashes remain bound. These are non-human reviews even when the workflow
treats them as a completed engineering gate.

Fitting partitions the complete admitted population by those assignments and
invokes the existing outcome-updated, source-group-aware estimator independently
for each observed family. Empty families are explicit. Inference requires a
declared family and cannot fall back to another head; within a head, Idea, domain,
stage, support, pairwise probability, and credible-margin gates still control
application or exact abstention. The decision trace binds both the chosen head and
its parent family-policy artifact. For H4, the reproduction spec additionally
binds every assignment and proves that the legacy-compatible policy consumed by
the runner is exactly the family policy's adaptive-allocation head.

Grounded source curation now permits a separate dual-AI-reviewed tier with exact
model and raw-response provenance. It can support retrieval and AI-evaluated
experiments, but it never sets `human_verified` or permits a human-validity claim.
The original human tier remains available. This preserves truthful evidence while
allowing the self-development workflow to proceed without waiting for human labor.

The project refresh path makes the continual loop operational without silently
scanning every file under `outputs/`. A self-hashed corpus manifest explicitly
binds project-owned admitted bytes to runtime-bound family assignments under the
current Idea. Formal-heldout data, non-project files, symlink traversal, stale
Idea records, incomplete assignment coverage, and later byte drift fail closed.
The separate refresh transaction atomically publishes canonical corpus and config
copies, the family-conditioned policy, a readiness report spanning all seven
families, and a receipt. Readiness distinguishes family observation, outcome-
eligible training, minimum support, and behaviorally actionable adaptive heads.
Structural H4 eligibility is necessary but cannot bypass the configured minimum
feature support.
Even a ready head receives no application authority from this compiler, and the
report always requires a separate formal effect evaluation. AI reviews satisfy
the configured operational gate but retain `not_human_review=true` and cannot
support a human-validity claim.

### ADR-133: Calibration data and validation reserve are separate acquisitions

Status: accepted and implemented through a new source-disjoint v7 calibration
sample; Git freeze, live execution, and later AI review remain open.

Repeated segmentation calibration consumed nearly all source groups in the
original ARIES and F1000 campaigns. Reusing those groups for validation would
measure adaptation to inspected sources rather than independent construction
reliability. SciTaste therefore treats a validation reserve as new source bytes,
not as another random seed over the old campaign.

The F1000 reserve uses a schema-1.1 acquisition plan whose exclusion list
contains the canonical identity of every work in the first receipt. It queries
the same official subject strata, downloads exact version-one/latest XML pairs,
and assigns a population identity derived from the new acquisition rather than
reusing the historical campaign ID. Historical F1000 XML may declare CC-BY 3.0
IGO; this is admitted as an attribution license while reviewer sub-articles
still require supported CC-BY URIs.

The ARIES reserve binds the separately acquired official public review/reply
object to the original receipt-bound split, paper-edit, and S2ORC bytes. A fixed
hash rank selects one review and one public author response from each of twenty
dev groups. Raw forum, review, response, and document IDs remain in a private
map; model-visible candidates expose only canonical group identities and
de-identified text. Because train/dev reply-to-edit association is heuristic,
the report forbids human-gold, scientific-correctness, or preferred-action
claims.

Both reserve populations render through the existing outcome-blind source-review
interface. V7 selects ten groups from each population and retains ten ARIES plus
thirty F1000 groups for a later independent validation cohort. The previous v6
live run stopped at request four because its frozen contract rejected a context
range overlapping its own trigger. V7 changes only that contract: exact source
unit ranges are retained and explicitly marked, with no fuzzy reconstruction,
response repair, or retry. AI quality/privacy review remains operational
nonhuman evidence and cannot itself admit the benchmark.

### ADR-134: Unknown null provider fields require dual opt-in and disclosure

Status: accepted for future protocols; v7 remains frozen and consumed.

The v7 provider returned 179 otherwise reviewable decisions, but its first
workload response also contained two unknown fields whose values were exactly
`null`. The frozen runner rejected those keys at request two. This is adapter
strictness evidence, not evidence about the model's scientific judgment or the
effect of Scientific Taste, and the source sample cannot be rerun.

A later protocol may ignore an unknown provider-output field only when both the
protocol and its exact rubric enable the behavior, the value is strictly null,
and every removed JSON-pointer path is written to the call receipt. The raw
response remains immutable and hash-bound. Missing required fields, unknown
non-null fields, malformed structures, and all semantic constraints still fail
closed. The flag defaults to false and is omitted from serialized historical
protocols, preserving their artifact hashes. No new reserve run is scheduled
before the deadline-critical Track-A H1/H2 pilot.

### ADR-135: Track-A preference review has an explicit AI-only evidence lane

Status: accepted and implemented through bounded execution, final lock, and
AI-only descriptive analysis; no live call or paper-level effect is claimed.

The H1/H2 public blind package is reusable without converting a model judgment
into human evidence. `ai-preference-pack-prepare` accepts either its public
`study.json` or the preparation output directory plus an explicit AI protocol.
The protocol binds two primary assignment identities to different providers and
provider/model/revision hashes, plus a third distinct adjudicator. It also binds
the public benchmark suite whose file and semantic hashes must match the study's
treatment commitment, so each request includes the exact decision context, task,
and stage. Compilation reads only that suite, the public manifest, and reviewer-
visible output bytes. The API has no blind-key or generation-ledger parameter,
rejects paths containing private study components, and grants no model-call or
experiment authority.
Each model identity is the SHA-256 of canonical JSON over exactly `provider`,
`model`, and `model_revision`, preventing a label-only identity substitution.

Each primary request contains only that model's X/Y assignments and no output
from the other primary. `ai-preference-primary-lock` requires two exact raw JSON
files and two execution receipts binding request bytes, provider/model identity,
provider request ID, timestamps, status, and raw-response bytes. Deterministic
normalization maps inverse X/Y presentations to selected output hashes and
self-hashes every row before the primary set locks. Agreement ends the block;
preference or assessability disagreement alone creates a third-model pack. That
pack contains only disputed public outputs and excludes both primary decisions
and rationales.

This lane consistently serializes `reviewer_kind=ai`,
`not_human_review=true`, and `human_validity_claim_allowed=false`; human identity,
qualification, and consent flags are false. It can replace an unavailable human
operational gate for the self-development study, but it cannot support a human
preference or external-expert validity claim. The downstream execution and
analysis adapter consumes this locked AI schema without renaming it as a human
review set. Its final lock explicitly sets
`operational_review_gate_satisfied=true`, so orchestration can continue without
waiting for a person while preserving that epistemic distinction.

Execution is a separate, double-opt-in action. A secret-free backend file names
an environment variable, HTTPS endpoint, exact provider/model/revision, zero
retries, timeout, output ceiling, and captured USD rates. A phase budget reserves
exactly two primary calls or one adjudicator call and bounds each request plus
the aggregate tokens and cost before contact. The runner resolves keys only from
the environment, calls each identity once, persists the exact HTTP request and
raw response body, extracts a strict JSON response, and binds request/config,
HTTP status, provider request ID, timestamps, token usage, derived cost, and all
file hashes in its receipt. A failed request writes a terminal failure record;
the occupied output directory cannot silently resume or recall a successful
identity.

`ai-preference-adjudicator-execute` either performs the one identically bounded
online call or emits a content-bound local execution request that grants no
execution authority. `ai-preference-finalize` accepts adjudicator evidence if
and only if primary disputes exist, verifies exact dispute coverage, and locks
one AI result per H1/H2 case block. `ai-preference-analyze` first replays this
public chain, then and only then reads the committed private condition map. Its
input and descriptive result use endpoint kind `ai-only-paired-preference`, set
`human_or_expert_endpoint=false`, and preserve the source-group paired rows.

### ADR-136: Track-A execution preserves partial coverage without replacement

Status: accepted and implemented; real model execution remains separately
authorized and has not occurred through this adapter.

The Track-A source design targets 24 cases and 72 three-arm decisions, but the
materialized suite may be a smaller coverage-aware subset. Execution therefore
records three numbers rather than silently treating the subset as the planned
population: `planned` remains 24/72, `eligible` is the frozen suite coverage,
and `executed` is the successfully completed eligible coverage. Every eligible
case must retain all three arms. Missing source cases are never resampled, and
one failed call makes the output directory terminal without producing an
admissible partial recording.

Preparation performs no external action. It requires an exact pre-execution
token manifest, including tokenizer/revision, prompt-template revision, token
IDs, and hashes for every eligible model-visible request. It then persists the
exact OpenAI-compatible request bytes only after checking one model identity,
one sampling profile, hidden controller conditions, and hard per-call and
aggregate byte, input/output/total-token, cost, latency, and call limits. Live
execution requires both a secret-free config opt-in and an explicit CLI flag;
the API secret is resolved only from its named environment variable. Calls run
sequentially once, with zero retry. Exact request bytes, provider response body,
strict decision JSON, provider request identity, timestamps, measured usage,
derived price, receipt, and semantic/file hashes remain replayable.

Only a successful complete eligible-subset run may cross into preference
review. The bridge creates condition-hidden X/Y artifacts and reuses the
existing schema-1.2 study, blind-key, generation-ledger, and AI request-pack
contracts as a compatibility envelope. Human-named fields in that legacy
envelope do not change the endpoint: the bridge and all downstream panel
artifacts state `reviewer_kind=ai`, `not_human_review=true`, and
`human_validity_claim_allowed=false`. Two provider-distinct primary AI judges
review identical blinded blocks; a third distinct AI sees disputed blocks only.
The bridge itself performs no call and grants no additional execution authority.

### ADR-137: Track-A token evidence pins local rendering, not provider internals

Status: accepted and implemented for the natural AI pilot.

`track-a-token-manifest-materialize` validates the configured official tokenizer
snapshot path, every file size and SHA-256, the Hugging Face repository and
revision, installed Transformers version, suite/backend model identity, and the
pinned chat template before it emits anything. It directly constructs
`PreTrainedTokenizerFast` from `tokenizer.json`; it never uses `AutoTokenizer`
or remote model code. Every eligible provider message list is rendered with
`add_generation_prompt=true`, `tools=null`, `reasoning_effort=max`,
`clear_thinking=false`, and `add_special_tokens=false`. The resulting trace
stores all token IDs plus hashes of the message list, complete provider payload,
rendered prompt, template, tokenizer config, and compound request identity.

The v2 manifest remains a no-call, atomic, non-overwriting artifact, while the
loader retains semantic-hash compatibility with existing v1 manifests. The
official local snapshot proves exact token IDs for that pinned local template;
it does not prove that the provider's rolling alias uses the same serving build.
Consequently v2 records `provider_serving_build_attested=false`, forbids a formal
provider-token-equivalence claim, and is restricted to the natural pilot. A
successful API usage receipt remains authoritative for observed provider token
counts.

### ADR-138: Prospective trajectories, not reconstructed foils, define decision episodes

Status: accepted and implemented for self-development diagnostics; formal external
cohort construction remains open.

Track-A source construction consumes the two-phase prospective Taste chain:
sampling plan, exact outcome-free decision/state lock, later outcome attachment,
completed projection, delayed outcome proposal, compiled episode, and completed
cross-model AI admission. The compiler proves that all alternatives and the
selected action came from the
recorded predecision `ResearchDecision`; postdecision prose, scores, replies, or
revisions cannot add an alternative. Missing outcomes remain pending, incomplete
joins or byte drift are quarantined, and attribution must retain confidence,
confounders, unresolved outcomes, or explicit missing-evidence questions.

Legacy schema-v1 capture and reconstruction artifacts remain loadable for audit
and historical replay, but receive the explicit pending finding
`legacy-temporal-unverified`. They cannot enter the label-hidden source pool,
even when later attribution and AI admission were completed. Prospective
eligibility begins only with a complete, byte-consistent v2 temporal chain.

The materialized source pool separates target-visible context from a scoring-only
label vault. Held-out targets contain no selected action, outcome, or attribution;
precedents may expose the reviewed lesson. One source group has one evidence tier,
split, and role. `self-dogfood` is development diagnostics only and cannot support
external-generalization claims; `formal-external` requires independently owned
prospective projects and compatible precedent/held-out splits. All operational
review can be completed by independent AI models, but every artifact records
`reviewer_kind=ai`, `not_human_review=true`, and no human-validity permission.

The H4 benchmark loop has a separate ingress hook for its pre-patch
`RESEARCH_STATE.json` and `RESEARCH_ACTION_DECISION.json`, with optional iteration
and loop-result receipts. Those files can establish a real fixed action menu and
selection, but development scores are retained only as post-run bindings. The H4
source remains pending until a dedicated delayed scientific-outcome attribution
contract and independent AI panel are joined.

### ADR-139: Held-out objective labels live outside candidate inference

Status: accepted and implemented for MLRC Perception adapter qualification.

Freezing model-authored source before test execution is necessary but not
sufficient when the candidate process can still read test annotations. The
Perception v2 runtime therefore projects two scorer roles from the already
receipt-bound held-out view. Candidate inference mounts feature arrays plus a
deterministic metadata-only manifest whose action lists are empty. It emits an
exact prediction hash and no objective. A separate scorer process imports no
candidate module, opens the original label bytes only after prediction freeze,
and requires both prediction and ground-truth SHA-256 values.

The scorer reproduces the fixed upstream label IDs, microseconds-to-seconds
conversion, tIoU thresholds, and interpolated mAP. Readiness requires a
content-bound parity receipt against the fixed upstream metric, in addition to
source, data, environment-import, and projection integrity. This adapter gate
does not imply a reproduced GPU baseline, formal execution authority, or a
scientific result.

### ADR-140: A complete research program selects resources by role and closes on typed evidence

Status: accepted and implemented at the orchestration boundary; B0 execution and
formal evidence remain open.

SciTaste Native is the method under study and owns the complete research
lifecycle. External benchmarks provide task environments and scorer-owned
endpoints; accepted external systems provide unchanged-core comparison rows.
Neither AutoResearchClaw nor any other framework is a mandatory runtime parent of
SciTaste. A blocked external row remains visibly blocked and is never replaced by
a prompt-level imitation.

The ICLR 2027 program is a project-owned, hash-chained state machine spanning task
acquisition, admission and split freeze, role-scoped model selection, idea and
experiment decisions, development execution, candidate freeze, hidden scoring,
evidence admission, paper construction, two independent AI reviews, conditional
third-AI adjudication, review-driven revision, final review, and immutable package
closure. Ordinary planning records are content-bound, while title-critical gates
must replay their native typed validators. Consequently an arbitrary non-empty
JSON file cannot claim model freeze, hidden score, admitted scientific evidence,
or operational review finality.

Model choice is not a single global switch. Research-agent, code-agent, judge,
embedding, and task-training resources are qualified independently on a
task-excluded conformance suite; task-training choices are additionally scoped to
the benchmark or task family. Existing checkpoints, hosted APIs, and later
downloads are all candidates until exact identity, license, load/execution, case,
and result receipts are bound. Small local checkpoints therefore remain useful
for cost and failure baselines without becoming the default scientific engine.

MLR-Bench and EXP-Bench assets are projected into separate model-visible and
scorer-only packages. The MLR acquisition currently supports a brief-only
development pilot and cannot claim formal benchmark coverage. EXP-Bench preserves
461 tasks grouped by 51 source papers; expected outcomes remain scorer-only. The
controller reports the exact next interface and authority flags, but performs no
implicit download, API call, GPU job, hidden scoring, or external-system launch.
Those operations belong to explicit executors whose receipts are then admitted by
the controller.

### ADR-141: Scientific capability selects experiment resources

Status: accepted and implemented at the v4 program boundary; B0 execution and
formal evidence remain open.

Historical feasibility work bound Qwen3-VL-2B because it was locally available,
but checkpoint availability is not a scientific design criterion. The v4 main
program therefore treats every registered local checkpoint, remote checkpoint,
hosted endpoint, and task-fit download as a candidate. It assigns the research
agent, code agent, judge, embedding model, and task-training model independently
only after role-specific, source-disjoint conformance. Existing bytes break ties
on cost and reproducibility after capability equivalence; they do not select a
study, endpoint, or headline model. Qwen3-VL-2B remains useful solely as a cheap
lower bound or compatibility slice.

Completeness is also a semantic constraint rather than a directory convention.
A v4 program cannot initialize unless it requires all capabilities from goal and
reference intake through grounded Taste, idea and experiment choice, objective
execution and hidden scoring, evidence admission, paper assembly, independent
dual-AI review, disagreement adjudication, review-driven revision, final review,
and immutable package freeze. Review can return work to experiment planning,
execution, evidence analysis, or paper assembly; a draft without this return path
is not a complete autonomous-research trajectory.

The v4 plan keeps four scientific jobs distinct: SciTasteBench identifies Taste
mechanisms, MLRC/MLE-style hidden objectives authorize the improvement claim,
MLR-Bench measures idea-to-reviewed-paper ecology against unchanged external
methods, and EXP-Bench diagnoses the experiment chain. The local RTX 3090 is a
development lane and the remote eight-RTX-3090 host is a formal lane, but workload
requirements and frozen budgets choose the lane. The owner's standing permission
allows an individually identified model resource up to 10 GiB to be downloaded;
every download and model use still enters the exact run manifest and cannot be
triggered merely by loading this program file.

### ADR-142: Training is a research-workload property, not a SciTaste product fork

Status: accepted and implemented at the shared workload-contract boundary; one
T0 runtime and one T1 runtime are available, while formal paired results remain
open.

SciTaste has one system identity. `training-free-research` means that the
scientific workload changes code, analysis, prompts, retrieval, or algorithms
without updating a task model. `training-based-research` means that the
scientific workload trains or fine-tunes a benchmark-owned task model and must
retain its initialization, training recipe, checkpoint, learning evidence, and
resource use. Neither term says whether SciTaste is a different product or uses
a different research-agent backbone.

`ResearchWorkloadContract` makes that distinction executable. A T0 contract
rejects task-model weight updates, training recipes, and produced checkpoints;
a T1 contract requires all of them. Both contracts keep the SciTaste research
backbone frozen and allow the same outcome-updated Taste state. Neural training
of a Taste scorer remains an optional mechanism study rather than a prerequisite
for either workload.

The independent adaptation axis names the implemented primary mechanism **A0**
(`nonparametric-outcome-updated-taste`) and the optional learned extension
**A1** (`learned-taste-component`). T0/T1 answer what experiment SciTaste runs;
A0/A1 answer how SciTaste updates Taste. A training-based T1 workload may still
use A0, and enabling A1 does not relabel the workload or create another product.
The formal primary comparison holds A0 fixed across T0 and T1; an A0/A1 contrast
is a selected-task mechanism ablation only after A1 has real implementation and
evidence.

The NewtonBench interactive runtime is the current T0 route. Its measurement
RNG is isolated per event and bound to an environment seed; new protocols and
receipts carry an opaque hidden-environment commitment. Locked Taste actions are
execution constraints: an incompatible model proposal terminates as
`agent_noncompliance` before tools or the scorer run. The MLRC Perception route
is the current T1 route and explicitly declares `training-based-research` while
retaining its fixed initialization, 50-epoch recipe, candidate checkpoint, and
one-way hidden scorer. T0 and T1 outcomes are reported separately rather than
pooled into one headline score.

### ADR-143: Lifecycle Taste credit is signed and failure evidence is diagnostic

Status: accepted and implemented for development-policy refreshes; formal effect
evidence remains open.

An admitted outcome attribution identifies the action receiving causal credit,
not an unconditional positive preference. The lifecycle estimator therefore
maps beneficial credit to pairwise wins for that action and harmful credit to
pairwise losses against the same alternatives. Admissions that mix beneficial
and harmful scientific credit fail closed. The explicit estimator identity
`signed-factorized-beta-pairwise-v2` keeps old v1 policy artifacts replayable
without silently changing their meaning.

This distinction matters whenever the same semantic action succeeds in one
source group and fails in another. Action type, stage/action, domain/action,
venue/action, tags, and decision-state/action remain the transferable features;
run-local action IDs remain provenance only. Source-group weighting and review
confidence still cap effective support, so contradictory evidence changes the
posterior rather than manufacturing readiness. Frozen minimum-support and
uncertainty gates are never lowered merely to activate a policy.

Long trajectory review uses a compact outcome projection whose file hash and
terminal receipt SHA-256 bind it to the complete immutable run. This reduces
context pressure without replacing the full source evidence. Model-node
attempts that fail now archive their exception class and a bounded,
credential-redacted, hash-bound diagnostic. Legacy v1.0 archives remain valid;
the diagnostic improves reproduction but never changes cost accounting,
execution authority, or a failed outcome into evidence of success.

### ADR-144: Model-role conformance is a one-shot execution dependency

Status: accepted and implemented for the current E2 development handoff.

Model-role conformance is an engineering selection gate, not an effectiveness
experiment. A campaign freezes task-excluded case bytes, candidates, role
profiles, budgets, and receipt rules before any request. Failed or inconsistent
answers are retained and cannot be selectively rerun. A successor campaign may
change the declared candidate/role assignment, but it receives a new campaign
identity and never overwrites predecessor evidence.

Local checkpoint visibility is the only planning blocker that may be rechecked
in place: removable or network storage can be absent at plan time. Resumption
must resolve the same frozen path and then content-hash the checkpoint before
execution. It cannot alter the candidate, path, case, budget, or completed API
receipts. This avoids repeating paid calls merely because a mount was restored.

An E2 manifest that marks model-role selection verified must content-bind the
actual `SELECTION.json`. Inspection requires a complete selection, no missing
roles, the same selected research/code model as the declared E2 agent, and an
identity-independent judge. The selection has no paper-effectiveness authority;
it only determines which exact roles may enter the subsequently approved paired
development and formal runs.

### ADR-145: Pre-execution command identities are closed across result admission

Status: accepted and implemented for E2 v4; execution remains owner-gated.

An executable handoff must use its manifest identity in both the campaign launch
and the result-admission command. A mismatch discovered before launch is recorded
as a failed no-execution program, not edited out of its immutable transition
history. A successor program may replay the same verified content-hashed inputs,
but receives new program and manifest identities.

The closed handoff must also state its matched per-block API ceiling. E2 v4
freezes Qwen3.8-Max at eight calls, 16,000 input and 8,192 output tokens per call,
193,536 total tokens, USD 1, and zero retries. These bounds plus static readiness
do not authorize provider, GPU, benchmark, or hidden-score execution; the exact
manifest hash and execution authority remain separate owner decisions.

### ADR-146: E2 requires a behaviorally active Taste treatment

Status: accepted and implemented at the no-run boundary in E2 v5; policy
activation and all external execution remain pending.

A lifecycle-policy weight of one does not establish a treatment. The E2 ON arm
may execute only when its manifest content-binds a family-conditioned policy,
the corresponding project readiness report, the `adaptive-allocation` head,
and source groups disjoint from the evaluation task. The inspector recomputes
policy/readiness/Idea coherence and refuses an untrained, insufficient-support,
domain-ineligible, or non-H4-eligible head. Historical schema-1.0 manifests stay
loadable, but cannot receive execution readiness without this intervention.

Static policy eligibility is also insufficient. A frozen, outcome-blind H4
state-probe contract must target the evaluation domain and bind the exact
adaptive head. Its report must show both a nonzero ON/OFF action change and
different supported preferences across feedback states. This proves only that
the manipulation exists; the later paired hidden endpoint remains the sole
authority for an effectiveness claim.

Policy v6 closes its identity but has zero adaptive-allocation training episodes,
zero training source groups, and zero feature support, so E2 v5 correctly blocks.
The activation-v1 development cohort freezes nine unused NewtonBench modules,
one outcome-independent candidate-selection rule per task, cross-model local AI
review, a support threshold of three, and cross-domain transfer followed by the
MLRC-domain state probe. It is policy-training data, not another B0 or paper
effect experiment, and cannot lower the support threshold to manufacture an
active treatment.

### ADR-147: policy activation is a prospective cohort, not a turn harvest

Status: accepted and implemented at the no-run and episode-projection boundary;
external execution remains owner-gated.

The adaptive-allocation head cannot be activated by collecting every decision
from a trajectory and later retaining whichever decisions receive favorable
credit. Each frozen NewtonBench source group contributes at most one candidate:
the earliest actually executed non-STOP controller decision after at least one
observation was already retained. The selector cannot read terminal score or
credit direction, never substitutes STOP when no decision qualifies, and keeps
failed or zero-score trajectories in the campaign record. When a successor
belief update exists, the selected candidate is projected to action-local
scientific credit before independent attribution and outcome-blind family
review; otherwise it remains quarantined rather than being replaced.

`adaptive-policy-activation-inspect` turns the versioned activation manifest
into a hash-bound project plan and initial state. It verifies the exact v6
predecessor, nine task bytes and canonical groups, clean NewtonBench commit,
program and limits, model configs, and resource arithmetic. The initial state is
restart-safe but explicitly lacks API, benchmark, GPU, policy-refresh, formal
claim, or E2 execution authority. Approval and execution remain separate state
transitions so a no-run readiness result cannot launch work.

`adaptive-policy-activation-approve` emits a separate hash-bound owner record;
it does not mutate state or contact a backend. The subsequent
`adaptive-policy-activation-authorize` transition accepts only that exact
approval, plan, initial state, frozen task population, and resource ceiling,
then emits sequence 1 in `ready` status. This transition still performs no
external work and never grants formal-effect authority. Consequently an
approval can neither authorize a drifted cohort nor be mistaken for a result.

The executable successor plan additionally freezes the current Idea revision
and its scientific-contract hash, while deliberately allowing ordinary project
revision increments caused by run registration. Each trajectory requires a
one-use task permit bound to the preceding state, exact ordinal, run, source
group, per-task API ceiling, zero retries, zero task GPU, and no downloads. A
terminal receipt plus its at-most-one-candidate batch advances the hash chain,
accounts calls, tokens, and new disk bytes, and exposes only the next frozen
task. A provider failure with unavailable telemetry is charged the complete
per-task token envelope rather than assumed free. Provider failures remain
terminal campaign members; a prospective lock
created before a failed provider response is retained as audit evidence but is
not projected as a completed decision. Existing run evidence makes the live
wrapper fail rather than selectively rerun the task.

Trajectory completion is not policy admission. Only after all nine frozen
members terminate may `adaptive-policy-activation-issue-review` bind the next
one-candidate batch to a one-use local-review permit. The permit freezes the
candidate file bytes, both reviewer identities, four-generation maximum, zero
retries, remaining GPU-hour and disk ceilings, and absence of API or formal
claim authority. The review runner executes two identical-packet attribution
reviews, deterministic admission, and—only for an admitted episode—two
outcome-blind family reviews. Attribution rejection, cross-model disagreement,
family disagreement, or runtime failure is terminal evidence for that source
group; it cannot trigger adjudication, replacement, or an extra generation in
this activation cohort. A task becomes `admitted` only when all four actual
runtime-bound generations and the deterministic admission/assignment artifacts
form one verified chain. Thus the declared 36 generations are physical
generation attempts, not 36 nominal calls with a hidden retry multiplier.

`finalize_adaptive_policy_activation.py` then performs the resource-free part
of the scientific gate exactly once. It seals the old plus newly eligible
episode population, fits policy v7 with the unchanged support threshold and
explicit cross-domain flag, and reports adaptive-family readiness. A ready head
is evaluated on the manifest-bound five-state MLRC-domain ON/OFF manipulation;
an insufficient head skips the probe, and an inactive or feedback-insensitive
head fails it. The final state distinguishes policy support, probe disposition,
and permission to proceed to E2 development. None of these deterministic
transitions authorizes the E2 benchmark, hidden scorer, formal claim, API, or
GPU execution.

### ADR-148: activation execution is append-only and hands off through an acyclic E2 successor

Status: accepted and implemented; the exact activation and all external E2
execution remain owner-gated.

The activation cohort is now operated as one durable campaign rather than a
manual sequence of task, review, and finalization commands. Every issued permit
and campaign state is written once under the project-owned activation journal.
The next action is a pure projection of the sealed state. Completed trajectory
receipts and batches are consumed without another provider call, a sealed state
left between write and canonical rename is recovered, and a review or
finalization result written before its successor state is deterministically
rebound. A cohort in which no trajectory yields a candidate advances to
`review-complete` with zero review generations and zero admissions; it cannot be
made to look productive by generating substitute candidates.

The operator requires the exact approval artifact plus separate `--allow-live`
and `--allow-local` flags. It retains zero retries and zero replacements. If a
process stops inside a local generation before a terminal review result exists,
the partial evidence is ambiguous and the campaign fails closed for audit
instead of rerunning the model. This is the deliberate boundary between durable
resumption and selective repetition.

An E2 manifest that embeds the probe proving its own treatment would otherwise
create a content-hash cycle: the probe must bind the manifest, while the
manifest must bind the probe. The successor therefore names a new E2 identity
and carries an `activation_basis` binding to the immutable predecessor E2-v5
bytes. Its newly derived state-probe contract targets the successor identity but
hashes that predecessor basis. The successor then binds policy v7, readiness,
the contract, and the report. Inspection verifies this chain and behavioral
activation. Compilation performs no API, model, GPU, benchmark, or hidden-score
work, and keeps development execution behind a new owner hash approval.

### ADR-149: research workload training is not SciTaste-controller training

Status: accepted and implemented in the activation-v2 boundary.

SciTaste remains one meta-research system. `T0 training-free` means that a
research workload does not update the weights of the task model being studied;
`T1 training-based` means that the experiment may train or fine-tune that task
model. Neither label selects the language model that plans the research, and T1
does not require a 7B--9B model to replace SciTaste's controller. Strong hosted
models may operate the research, review, and synthesis nodes in either workload,
while open models may be experimental subjects, baselines, or robustness bounds.

Controller adaptation is a separate axis. `A0` uses the frozen intrinsic or
rule-based Taste controller; `A1` fits a bounded decision policy from admitted
episodes. A1 learns a decision head over evidence and resource state, not a new
general-purpose autoresearch LLM. Specialized 7B/8B research agents reported by
related work are comparison systems, not a dependency or default SciTaste
backbone.

Activation v2 consequently freezes fresh NewtonBench task identities and assigns
each source group to EXPERIMENT, REFINE, or the first prospectively approved STOP
before execution. It projects the same immutable decisions as allocation-local
episodes, retains missing strata without replacement, and uses two
identity-distinct strong hosted reviewers. Review API calls, tokens, and cost are
separate from trajectory usage and local GPU accounting. The retrospective v2/v3
curations remain protocol-development evidence and cannot activate the policy.

### ADR-150: scientific situations and objective forks have separate authority

Status: accepted and implemented for consumed development; no new confirmation is authorized.

The earlier counterfactual selector treated stage and evidence status as hard applicability and
the diagnostic rationale as lexical similarity. Objective replays showed that these fields hide
different epistemic bottlenecks and can collapse transfer to a global action prior. The successor
contract represents the decision-time situation with six typed axes: hypothesis structure,
evidence relation, bottleneck, identifiability, budget pressure, and terminal readiness. A model
may populate this representation only from the prefix and must cite exact visible spans. It cannot
see target branch outcomes or recommend the target action during abstraction.

Utility authority remains outside that model. Shared-prefix action forks expose scorer-owned
outcomes. Per-state normalization is retained only as a consumed-development diagnostic: it is not
a formal common utility scale and cannot establish practical separation. The deterministic selector
uses one common-action-support population for every candidate action, collapses correlated prefixes
within a task cluster, and abstains for missing common support, insufficient similarity, effective
support, action margin, or excessive uncertainty. An optional model synthesis
node sees the same typed states and source utility vectors, but its output is admitted only after
deterministic citation, task-diversity, boundary, confidence, and margin checks. Unknown citations
cause abstention; they are never silently repaired.

Natural research records serve a complementary role. They supply ecological context and
construct coverage, but do not acquire counterfactual utility authority from a plausible generated
label. SciTasteBench therefore requires both a full-context invariant-fact review and a
boundary-only negative control, or independent expert adjudication, before a reconstructed pair
can enter a formal population. Development replays may change this mechanism, but their effects
cannot be promoted to confirmation.

### ADR-151: objective transfer compiles into the canonical Taste control packet

Status: implemented as the claim-bearing interface; formal source data are not yet collected.

Scientific-situation transfer is not a second controller. Its output can affect execution only
after `compile_scientific_situation_control_packet` binds every admitted source fork to an existing
grounded Taste case, at least two exact current-state facts, and a one-to-one mapping over the
frozen target action menu. The compiler rejects post-selection action remapping, same-task
precedents, menu drift, missing contributing evidence, and fewer than two grounded source task
clusters. Any finding produces the ordinary zero-adjustment abstaining `TasteControlPacket`.
Consequently local mechanism studies and external research trajectories consume the same typed
treatment object and the controller's existing bounded adjustment path remains authoritative.

Formal objective sources use `FormalObjectiveForkSituationCase`, not the legacy one-rollout
development schema. Every action has at least three independently identified continuations on one
registered utility scale; failed branches retain the preregistered intention-to-treat utility;
action semantics, practical equivalence, and the scorer result are bound. Transfer estimates
combine between-task variation with within-case replicate uncertainty, and formal mode refuses
mixed utility or action contracts. Legacy min--max cases remain readable for development, but
cannot satisfy the formal-source gate.
