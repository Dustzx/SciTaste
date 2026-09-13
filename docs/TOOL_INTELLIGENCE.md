# Tool Intelligence

Tool Intelligence is SciTaste's bounded execution-intelligence layer. It makes
semantic judgment available at selected rigid-tool boundaries without making a
model the controller or executor. The v1 vertical slice added typed tool-plan
and structured-repair advice on top of the durable model-node runtime described
in `BOUNDED_MODEL_NODES.md`. The v2 slice added a deterministic, single-step,
read-only execution boundary for fresh accepted tool-plan advice. V3 adds the
project-owned durable lease, content-addressed source bindings, crash recovery,
and deterministic hotspot workflow bridge needed across process restarts.

It is implementation infrastructure, not evidence that additional model calls
improve scientific outcomes. ADR-022 remains proposed until its registered
effectiveness and safety gates are independently satisfied.

## Authority flow

```text
immutable project/state projection
  + deterministic trigger
  + content-addressed model profile and policy
  + content-addressed controlled tool profile or target schema
        |
        v
bounded structured model call
        |
        v
untrusted provider body and provider-native tool-call telemetry
        |
        v
strict Pydantic output parsing
        |
        v
deterministic scope, argument, dependency, budget and identity checks
        |
        v
accepted or rejected advice + project-owned hash-chained receipt
        |
        v
named semantic-hotspot trigger + fresh ProjectRuntime/ResearchState check
        |
        v
single-use, short-lived, profile/request/step/handler-bound action lease
        |
        v
atomic project-run claim + registered deterministic read-only handler
        |
        v
durable result + typed observation + post-call revision check
        |
        v
hash-chained receipt + deterministic accept/reject/escalate/re-plan
        |
        v
no automatic evidence admission or state transition
```

An accepted model-node result always has `advisory_only=true` and
`executable=false`. The same fields are repeated on Tool Plan steps. Model-node
acceptance does not authorize filesystem access, a process, a network request,
a state transition, API spending, or a tool invocation. Only deterministic v2
admission can issue an `ActionLease`, and that lease authorizes exactly one
registered read-only handler call. It explicitly does not authorize canonical
evidence admission or a state transition.

Provider-native function calls are not Tool Plan steps. They remain untrusted
response telemetry and both new nodes reject them even when a name appears in a
policy allowlist. The committed Tool Plan model profile additionally fixes
`max_tool_call_proposals` to zero.

## Initial controlled catalog

The v1 catalog contains exactly three project-owned, read-only capability
contracts:

| Capability | Typed arguments | Deterministic scope and ceilings |
|---|---|---|
| `knowledge.query` | query, library IDs, `top_k` | permitted library IDs, library count, query length, retrieval count |
| `evidence.inspect` | evidence IDs, provenance flag | permitted evidence IDs, immutable context IDs, item count |
| `registered-run.compare` | run IDs, metric names | permitted registered runs and metrics, run count, metric count |

The v1 types remain capability descriptions and proposal schemas. V2 supplies
three deterministic in-process handlers:

- `KnowledgeQueryHandler` performs the existing deterministic lexical ranking
  over caller-verified, handler-bound `KnowledgeDocument` records. It returns
  document identities, scores, and hashes; it does not silently open web search.
- `EvidenceInspectionHandler` returns bounded, content-addressed evidence and
  optional provenance from a caller-verified registry. Inspection never changes
  evidence status.
- `RegisteredRunComparisonHandler` returns finite metrics from a bound metric
  registry. Lease admission additionally verifies that requested run IDs still
  exist in the current ProjectRuntime manifest. It does not launch experiments.

The complete bound handler data/configuration contributes to the handler
fingerprint. V3 constructs these handlers from hash-pinned, run-relative
project files. Changing the records between binding, lease issue, and execution
therefore requires a different handler identity and fails closed.

The catalog is intentionally closed. Adding a tool requires a new typed
permission model, typed arguments, a discriminated Tool Plan step, deterministic
scope checks, adversarial tests, and a schema-version compatibility decision.
A string added only to an allowlist is not a registered capability.

## Controlled tool profile

`ControlledToolProfile` is separate from `ModelNodeProfile`:

- `ModelNodeProfile` binds provider generation capability, one-response
  admission budgets, cumulative project budgets, provider/model identity, and
  whether a live model call is allowed.
- `ControlledToolProfile` binds which data-only tool steps may be proposed,
  project-data identifier scopes, per-tool argument ceilings, total plan steps,
  dependency edges, and a fixed no-side-effect authority boundary.

The controlled profile has a canonical SHA-256 fingerprint. The complete
profile is part of `ToolPlanInput`, the output must echo its ID and fingerprint,
and the surrounding structured request and runtime intent hash the complete
input. The node requires the controlled profile's tool names to equal the
deterministic node policy allowlist. Normal runtime profile validation already
requires that policy allowlist to equal the selected model profile admission
allowlist. Drift at either boundary fails closed.

The v1 authority record fixes these values and Pydantic rejects attempts to
change them:

```json
{
  "read_only": true,
  "network_access": false,
  "filesystem_write": false,
  "process_launch": false,
  "state_mutation": false,
  "direct_execution": false
}
```

`ToolScopeProjection` binds the project and state snapshot plus the exact
library, evidence, run, and metric identifiers visible to one call. Evidence
permissions must also be contained in the immutable `NodeContext`. This keeps a
model from enlarging an identifier scope through its output. The project-scoped
runtime additionally resolves every supplied run ID against the current
ProjectRuntime manifest before planning or backend access.

## Tool Plan node

`ToolPlanNode` (`tool-plan-v1`) receives an objective, scope projection, and
controlled profile. It can propose an ordered list of typed steps. Deterministic
admission requires:

- the project and state-snapshot identities match `NodeContext`;
- the model profile, node policy, and controlled profile tool names agree;
- permissions stay inside the supplied scope;
- the echoed controlled-profile ID and fingerprint match;
- every step uses a registered discriminated schema;
- all argument identifiers and dynamic per-tool limits pass;
- step IDs are unique;
- dependencies name earlier steps only; this rejects unknown references,
  forward references, self-dependencies, and cycles;
- total steps and dependency edges remain within the profile.

The node does not schedule or execute the resulting list. The v2 executor
revalidates a serialized `NodeResult`, reconstructs its request input and
context, binds the accepted proposal back to the provider output, and then
admits only one dependency-free step. A dependent step requires a new planning
turn after the preceding observation; the executor never consumes a complete
model-authored DAG in one call.

## Semantic hotspots and controlled execution

`SemanticHotspotTrigger` records why deterministic code needs semantic help,
the exact project and state snapshots, the controlled profile, visible evidence,
and the maximum set of candidate tools. It asserts that the deterministic fast
path was exhausted; it does not assert that a model answer is correct.

`ControlledToolExecutor.issue_lease()` verifies all of the following before
granting one tool invocation:

- the source is a structurally valid, accepted `tool-plan` result;
- no provider-native function call exists;
- the response fingerprint matches the source request and its parsed proposal
  equals the response payload;
- the request context, Tool Plan input, semantic hotspot, controlled profile,
  objective, project, state and evidence scopes agree;
- the selected step is unique, dependency-free, inside the hotspot tool ceiling,
  and within the handler result limit;
- the registered handler's code/configuration identity is content-addressed;
- ProjectRuntime revision and snapshot hash plus the ResearchState snapshot are
  still current; and
- registered-run comparisons name runs in the current project manifest.

An `ActionLease` lasts at most five minutes and binds the source model request,
raw-response hash, model usage/cost, model latency, controlled profile, exact
step, handler identity, project snapshot, state snapshot, and output-byte
ceiling. It can be consumed once by one executor instance.

Immediately before the handler call, execution rechecks ProjectRuntime and
ResearchState. It checks both again immediately after the call. A concurrent
change rejects the observation even if the handler returned successfully. A
bounded returned value is retained only as `untrusted_output_payload`; its hash,
byte count, handler latency, and the source model token/cost/latency evidence
remain available. Oversized output is hashed but not retained. Handler errors
record only a sanitized exception type, not the exception message.

`ToolObservation` is always `advisory_only=true`, `executable=false`,
`canonical_evidence=false`, and `state_transition_authorized=false`. A
successful observation is therefore input to a later deterministic decision,
not proof of a claim and not permission to modify ResearchState.

## Durable project execution

`DurableToolExecutionRuntime` owns one `tool_intelligence/` directory below a
registered run:

```text
tool_intelligence/
  leases/         immutable serialized ActionLease records
  pending/        atomic claims and crash-recovery markers
  attempts/       completed attempt evidence
  observations/   immutable typed observations
  ledger/         contiguous, hash-chained completion entries
  decisions/      typed hotspot decision envelopes
```

One non-blocking `flock` covers claim recovery and the handler call. A second
process therefore receives a conflict instead of running the same lease. Every
JSON publication uses a synced temporary file plus an exclusive hard link; a
completed pending directory is moved atomically to `attempts/` only after its
observation and ledger entry exist.

Recovery distinguishes four cases:

- a completed ledger entry returns the exact historical observation;
- a durable handler result or observation is finalized without another call;
- a claim that cannot have reached the handler can be retried; and
- a handler-start marker without a result is retried only for the three pinned
  first-party deterministic handlers. Any other handler is durably marked
  ambiguous and fails closed for human reconciliation.

The verifier checks nested symlinks, unexpected paths, non-regular files,
self-hashes, lease/claim/handler identity, observation identity, contiguous
ledger indexes, predecessor hashes, duplicate leases, pending recovery state,
and typed workflow decision records. It also totals handler invocations and
the source model's tokens, cost and latency. A rejected observation retains
known source-model cost and returned-output hashes; concurrent ProjectRuntime
or ResearchState changes can never leave an accepted proposal.

## Project-owned handler bindings

`ProjectToolBindingSet` binds a selected project/run revision to three strict
JSONL source forms:

- one or more `KnowledgeDocument` files, each assigned a permitted library ID;
- `ProjectEvidenceRecord` rows containing canonical `EvidenceItem` payloads;
- `RegisteredRunMetricsRecord` rows containing finite named metrics.

Every `ContentAddressedRunFile` locator is normalized relative to the selected
run. Loading uses no-follow file descriptors and rejects an unsafe path
component, final symlink, non-regular file, byte-ceiling overflow, concurrent
file mutation, hash drift, duplicate record, unknown scoped identifier,
unregistered run, missing metric, or project-revision drift. The loader returns
only the three existing built-in handlers; it cannot load arbitrary Python,
open the network, launch a process, write a file, or admit evidence.

## Deterministic hotspot workflow bridge

`SemanticHotspotDetector` converts a typed deterministic fast-path failure into
a content-addressed `SemanticHotspotTrigger`. The signal's named reason codes,
candidate tools, evidence IDs, current ProjectRuntime snapshot, and immutable
state projection are all checked before a model is involved.

`ProjectToolIntelligenceBridge.resolve()` then performs one bounded attempt:

1. return an exact durable decision if this request already completed;
2. invoke or resume the existing project-scoped Tool Plan model runtime;
3. reject model telemetry outside the hotspot token, cost, or latency envelope;
4. deterministically select the lexically first eligible dependency-free step;
5. find an already persisted matching lease or issue exactly one new lease;
6. execute or recover it through `DurableToolExecutionRuntime`; and
7. persist accept-as-advice, reject, escalate-to-human, or re-plan-required.

The attempt index and `max_replans` bound the re-plan horizon. Existing
`ModelNodeProfile` cumulative budgets continue to bound project-wide model
invocations, tokens, and cost. The bridge adds per-attempt model/tool count,
latency, output-byte, token, and cost ceilings. Its output repeats
`advisory_only=true`, `canonical_evidence=false`, and
`state_transition_authorized=false`.

The narrow integration contract for the main-owned workflow is:

```text
typed ImmutableStateProjection + deterministic unresolved signal
  -> SemanticHotspotDetector.detect(...)
  -> ToolHotspotWorkflowRequest
  -> ProjectToolIntelligenceBridge.resolve(...)
  -> ToolHotspotWorkflowDecisionRecord
```

The caller may display or use accepted advice in a later deterministic
decision. It must construct a new typed state/request for a requested re-plan
and remains responsible for every canonical evidence or ResearchState change.

## Paired engineering benchmark

The committed protocol is
`configs/model_nodes/tool_intelligence_benchmark_v1.json`. The integration test
runs v2 and v3 on matched normal, restart, result-publication crash, unknown
handler interruption, concurrent-state change, and locator-symlink scenarios.
Run it with:

```bash
SCITASTE_PRINT_TOOL_BENCHMARK=1 PYTHONPATH=src \
  .venv/bin/python -m pytest \
  tests/model_nodes/test_tool_benchmark_integration.py -q -s
```

One local one-pass measurement on 2026-09-08 produced:

| Engineering metric | v2 | v3 | Change |
|---|---:|---:|---:|
| restart duplicate-execution rate | 1.00 | 0.00 | -1.00 |
| crash recovery without duplicate call | 0.00 | 1.00 | +1.00 |
| ambiguous custom call fails closed | 0.00 | 1.00 | +1.00 |
| stale/concurrent result acceptance | 0.00 | 0.00 | unchanged |
| locator attack rejection | 0.00 | 1.00 | +1.00 |
| controller steps per resolved hotspot | 3.67 | 1.00 | -72.7% |
| successful hotspot resolution | 0.50 | 0.50 | unchanged |
| model invocations | 6 | 5 | -16.7% |
| tool handler invocations | 8 | 5 | -37.5% |
| scripted source tokens | 240 | 200 | -16.7% |
| scripted known cost | $0.012 | $0.010 | -16.7% |
| mean scenario runtime | 3.48 ms | 133.70 ms | +130.21 ms |

The call/token/cost reduction comes from rejecting an unsafe project locator
before model or tool execution and from removing restart duplicates. The v3
runtime overhead is dominated by synced immutable publications and repeated
hash/containment verification on tiny fixtures. Timing is environment-dependent
and must be remeasured on the deployment filesystem. These are engineering
proxies, not evidence that Tool Intelligence improves scientific outcomes.

## Preregistered grounded-resolution study

The frozen WP6 protocol is
`configs/model_nodes/tool_intelligence_effectiveness_study_v1.json`. It contains
12 independent project-evidence acquisition tasks, split evenly between
explicit and semantic routing, with three model seeds per task. This produces
36 response-level paired replicates. The primary paired analysis does not treat
the seeds as independent observations: it takes a majority over the three
seeds within each task, then applies an exact two-sided McNemar test to the 12
task outcomes. Response-level accuracy receives a Wilson 95% interval.

The two conditions share the exact same content-addressed Knowledge, Evidence,
and registered-run inputs:

- `v2-fixed-router` is a frozen, no-model keyword router followed by the trusted
  read-only handler;
- `v3-live-project-loop` runs the complete durable Tool Plan bridge with the
  pinned `zhipu-direct/glm-5.3-flash` identity, one proposed action, no retries,
  and the same read-only handler.

The primary endpoint is exact grounded resolution: the selected typed action
must match the preregistered tool and identifiers, remain inside scope, execute
successfully, and return the expected project-owned record IDs. Secondary
measurements are model admission, workflow resolution, scope violations,
model/tool calls, input/output tokens, price-bound cost, and model/tool latency.
The committed provider config is inert. Its date-limited pricing record uses
the user-confirmed promotional CNY 0.4 input and CNY 1.4 output rates per
million tokens plus CNY 0.115 per million cache-hit input tokens, converted to
USD at the recorded 2026-09-08 central parity.

`ProjectToolEffectivenessRunner` creates or exactly resumes a dedicated local
project and writes immutable trials, runtime ledgers, a report, a
condition-and-gold-blinded review packet, a separately located private key, and
a hash-bound `RUN.json`. It rejects source/config drift, an incomplete task
matrix, unsafe nested paths, content replacement, provider/model substitution,
retries, unpriced calls, or a response-count mismatch. A complete rerun loads
all 72 condition records and makes zero provider or handler calls.

The formal command requires an explicit live switch and runtime-only secrets:

```bash
PYTHONPATH=src ZAI_API_KEY=... SCITASTE_BLINDING_SALT=... \
  .venv/bin/python -m scitaste.model_nodes.tool_effectiveness_runner \
  --outputs-root outputs \
  --fixture configs/model_nodes/tool_intelligence_effectiveness_study_v1.json \
  --profile configs/model_nodes/profile_zhipu_glm53_tool_effectiveness_v1.yaml \
  --backend-config \
    configs/model_nodes/zhipu_glm53_flash.priced_20260908.example.yaml \
  --run-id <registered-run-id> --source-commit <full-sha> --allow-live
```

Neither credential nor blinding salt is serialized. A preliminary statistical
signal remains only bounded internal evidence. The report schema fixes
`independent_domain_review_complete=false` and
`scientific_effectiveness_claim=false`; those values cannot change until a
reviewer receives the blind packet, returns independently scored outcomes, and
the main-owned workflow integration gate passes.

### Registered GLM-5.3-Flash result — 2026-09-08

The formal run
`2026-09-08__zhipu-glm-5.3-flash__tool-effectiveness-v1` is bound to source
commit `4606211ae9536aa5d5e6a01d86103a1f1ae3ffb2`. It made exactly 36 provider
calls with zero retries. A second invocation was deliberately run without the
API-key environment variable and recovered all 72 condition records, proving
that it made zero additional provider calls.

| Endpoint | v2 fixed router | v3 live project loop | Difference |
|---|---:|---:|---:|
| response-level grounded resolution | 18/36 (50.00%) | 35/36 (97.22%) | +47.22 percentage points |
| Wilson 95% interval | 34.47%–65.53% | 85.83%–99.51% | — |
| task-majority grounded resolution | 6/12 (50.00%) | 12/12 (100.00%) | +50.00 percentage points |
| explicit-routing responses | 18/18 | 18/18 | unchanged |
| semantic-routing responses | 0/18 | 17/18 | +94.44 percentage points |
| unsafe scope | 0/36 | 0/36 | unchanged |
| model calls | 0 | 36 | +36 |
| tool calls | 36 | 35 | -1 rejected plan was not executed |

At the independent task level there were six improvements, zero regressions,
and six ties; the preregistered exact two-sided McNemar p-value is 0.03125. The
treatment used 86,506 input and 10,496 output tokens (97,002 total), with mean
provider latency 5.522 seconds and mean durable-tool latency 2.179 ms. The
frozen ledger's full-input calculation is USD 0.00727049, or CNY 0.0492968 at
the registered exchange rate.

The provider response telemetry reported 128 cache-hit input tokens across the
36 calls. Applying the screenshot's CNY 0.115 cache-hit rate gives a
cache-adjusted billing estimate of CNY 0.04926032 (USD 0.00726511), CNY
0.00003648 below the conservative frozen ledger. Cache-tier parsing and
price-bound telemetry are implemented for subsequent runs; the original
ledger is retained unchanged as evidence from its pinned source commit.

One response selected the correct `registered-run.compare` tool and runs but
requested three metrics where the controlled profile allowed one. Deterministic
admission rejected it with no tool execution. This accounts for the single
response-level failure while the task-majority endpoint still passed. All four
declared artifact hashes, 36 response recordings, both runtime ledgers, and the
zero-pending state verified; the project tree contains no supplied credential.

This result is a preliminary internal signal for a deliberately narrow routing
benchmark, not a general scientific-effectiveness claim. The baseline has a
designed semantic-routing blind spot, the task set was authored within the
project, sample size is 12 independent tasks, and external validity remains
unestablished. The blinded packet still requires an outcome review by someone
who did not author the fixture and who does not receive the private key.

That final review handoff is now typed rather than free-form. The reviewer must
return one `ToolEffectivenessBlindReviewRating` per blind ID, judging grounded
relevance, scope appropriateness, rationale, and confidence, while attesting
that they did not author the fixture and did not receive the private key before
completion. `evaluate_tool_effectiveness_blind_review()` rejects missing,
duplicate, or foreign IDs before unblinding, then reports response-level rates
and task-majority paired discordances. Even a completed independent review
report fixes `scientific_effectiveness_claim=false`; only the main project may
combine it with workflow integration and broader validity evidence.

## Structured Repair node

`StructuredRepairNode` (`structured-repair-v1`) operates only on a previously
captured JSON value. Its input includes:

- the invalid payload and its canonical SHA-256;
- sanitized validation locations and error types, never raw failing values;
- one supported target node name;
- the exact SHA-256 of that target's current validation schema.

Input and repaired payloads are each limited to 32,768 canonical JSON bytes.
The supported targets are `review-semantic`, `interpretation-threat`,
`ambiguous-action`, and `tool-plan`. Before a backend call, deterministic code
recomputes the supported target schema hash. After the response, it checks the
echoed target identity and strictly validates the proposed payload against that
schema.

An accepted repair result means only “this replacement has the pinned target's
shape.” It does not mean that the replacement passed the target node's evidence,
action, ambiguity, capability, context, provider, budget, or revision checks.
The original rejected result and its resource evidence remain unchanged. To be
considered by the workflow, the repaired value must enter a new invocation of
the original node and pass every original deterministic gate.

Repair is deliberately not automatic retry. This avoids hiding failures,
double-spending without a new ledger entry, or transforming a schema helper
into an unbounded model loop.

## Runtime and CLI

Both nodes use the existing `ModelNodeRuntime`, facade, strict JSON config,
project ledger, interruption recovery, and exact replay. The committed model
profile set is:

```text
configs/model_nodes/tool_intelligence_profiles.example.yaml
  controlled-tool-plan
  structured-response-repair
```

The set and both referenced profiles are content-addressed, use the scripted
backend, set `live_execution_permitted=false`, and contain no credentials or
provider pricing. Planning, scripted execution, status, verify, and exact replay
use the existing commands:

```bash
scitaste model-node runtime plan ...
scitaste model-node runtime execute ...
scitaste model-node runtime status ...
scitaste model-node runtime verify ...
scitaste model-node runtime replay --source-invocation <recorded-id> ...
```

Runtime identity binds the complete node input, model profile and policy,
project/state revision, provider/model, seed, trigger, expected request
fingerprint, and predecessor ledger hash. Consequently, a changed controlled
tool profile or target schema misses exact replay rather than falling back to a
model call. Known usage from rejected results continues to advance the project
ledger under the existing rules.

CLI summaries expose only availability, trust state, resource telemetry,
hashes, and evidence locators. Raw responses, repaired content, tool arguments,
and secrets are not printed.

## Cost-sensitive verification routing

`verification_policy.py` prevents “preflight everything” from becoming another
rigid workflow. Each candidate action declares reversibility, effect classes,
evidence freshness, semantic uncertainty, estimated failure probability and
impact, plus the cost and detection probability of a targeted check and a full
preflight. The deterministic router calculates expected avoidable loss and uses
the least costly route whose expected net gain clears the policy threshold:

- `direct_path` for cheap, reversible work where checking costs more than the
  expected loss it could prevent;
- `targeted_check` when one bounded check has positive value and a full preflight
  adds less value;
- `full_preflight` for high-impact stale/absent evidence or untrusted code;
- `owner_approval` for irreversible actions and external authority boundaries.

Paid compute, secret access, external mutation, and irreversibility cannot be
optimized away. Untrusted code requires both a full preflight route and owner
approval. In a declared semantic gray zone, a typed model advisory may select a
different non-authoritative route. It must bind the exact action fingerprint and
cannot replace an owner boundary or grant execution.

The native Full Workflow hook now records this decision before constructing a
model/tool request. A `direct_path` skips the Tool Intelligence invocation; an
owner-gated route is durably deferred before either model or tool is called; and
admitted targeted/full routes preserve the existing project-owned model and tool
ledgers. A broad or semantically uncertain evidence-inspection task may still
select one targeted read-only check. Opening an already visible,
content-addressed local artifact is different: Tool Intelligence classifies it
as cheap, reversible, read-only, and current, then takes `direct_path`. The
descriptor, media/size, and content-hash guards run inline because they define a
valid read; no separate preflight or owner approval is performed. Generation as
Content also routes its explicit local planning-decision and
planning-publication writes: because these content-addressed/versioned writes are
reversible and cheap, they take the direct path after only the necessary
identity, stale-state, and hash guards. The published project artifact records the
route and reason. This integration does not generalize the read-only tool catalog
into code, network, GPU, credential, or mutable infrastructure authority.

The current project experiment gate now consumes the same decision instead of
adding a ritual preflight. Tool Intelligence routes the bounded local Reference
Quality calibration to `owner_approval`; Generation as Content materializes the
exact model/data/GPU/token/time envelope and records the owner's decision without
executing it. A separate executor accepts only the still-current, unexpired
authorization and an independent local-execution switch. Packet identity,
project revision, checkpoint binding, schema, and budget are checked inline at
use. No model load, GPU reservation, provider request, or placeholder run is
performed merely to determine whether the action is allowed.

This is the intended checking rule for future blocks: first classify the action,
then pay only for evidence whose expected avoided loss exceeds its cost. A cheap
reversible local write normally proceeds after invariant checks; an uncertain
read gets one targeted observation only when valuable; an exact current local
artifact read proceeds directly with its intrinsic content guard; a full
preflight is reserved
for stale high-impact evidence or untrusted code; and external authority is
requested from the owner. Optional model advice may help estimate semantic gray
zones, but it cannot downgrade a hard gate or invent execution authority.

Generation as Content consumes this optional advice without adding a separate
review call. When the exact selected project route is advisory-eligible, the
bounded program-revision schema lets the same model response include a
`VerificationAdvisory` over the server-issued input fingerprint. The controller
recomputes the deterministic baseline and applies the ordinary advisory admission
policy; the model cannot change declared effects, probabilities, costs, route
catalogs, blockers, or hard authority boundaries. A published advisory affects
only its exact current stage and route. This makes semantic judgment available
where it can add value while preserving zero extra model calls for verification.

Cost accounting also covers rejected structured responses. If a provider
returned bytes but schema admission failed, SciTaste stores the response hash and
known token/cost/latency telemetry and negative-caches that exact request. It does
not pay repeatedly for the same invalid answer. Failures that returned no
provider response remain retryable, because caching an availability fault would
not represent a reusable judgment.

The optional-check chooser is intentionally lexicographic about effort. Once a
targeted check clears the configured minimum net gain, a full preflight replaces
it only when the deeper check's *incremental* net gain also clears that margin.
A tiny positive marginal gain is not enough. Likewise, model advice in a semantic
gray zone may skip or select a positive-value check, but it cannot add a check
whose declared net value is non-positive. If both check depths are positive, the
model may select only the one with the higher declared net value; it cannot turn
semantic uncertainty into a broader but economically worse preflight. The
project route portfolio renders both net-gain bars and the model-advisory
eligibility flag, making the choice inspectable before any check is run.

## Threat model and extension rules

The current gates address these failures:

- invented tool names or malformed argument types;
- identifier scope expansion;
- argument, step, dependency, token, latency, or cost budget overflow;
- dependency reordering and cycles;
- controlled-profile, target-schema, state, project, provider, or model drift;
- provider-native tool calls masquerading as admitted steps;
- a repair proposal masquerading as target-node acceptance;
- tampering between the provider output, accepted proposal, action lease, and
  registered handler;
- expired, reused, stale, dependent, or over-broad action leases;
- pre-call and concurrent post-call project/state changes;
- invalid, oversized, or failing deterministic handler output;
- replay misses with silent live fallback;
- process restart, incomplete publication, and ledger tampering through the
  shared runtime.

The deterministic caller that constructs a scope, permission profile, and bound
handler registry remains part of the trusted computing base. It must derive
library, evidence, and metric records from verified project-owned sources. A
caller-provided identifier is not proof that a record exists; the content-bound
handler closes that gap for one execution, while run identifiers are also
resolved against the project manifest.

The handler interface is a trust boundary, not a Python sandbox. First-party v2
handlers are deterministic and use only already-bound in-memory data. A new
handler requires code review and adversarial tests; merely declaring
`read_only=true` cannot make untrusted handler code safe. Mutable, networked,
generated-code, GPU, and filesystem-reading tools require distinct profiles,
sandboxing, durable receipts, and threat reviews. None may inherit v2 read-only
status by name similarity.

## Current limitations

- Full Workflow now owns an explicit deterministic post-evidence hotspot policy
  and call site. It can trigger one bounded Tool Intelligence request from
  actual project state and evidence, but it does not let a model invent the
  trigger, tool catalog, permissions, or canonical evidence.
- One attempt executes at most one dependency-free read-only action. A
  `replan-required` result requires a new typed state projection and a new
  bounded model invocation; the model never executes its proposed DAG.
- A custom handler interrupted after its start marker requires human
  reconciliation. Declaring custom code "read only" does not make it replay
  safe.
- The GLM-5.3-Flash study profile and inert priced backend configuration are
  included. The registered live result exists only in a dedicated project-owned
  ignored output and is not part of the source tree.
- Repair supports four pinned output schemas and performs structural validation;
  target-specific semantic gates require a new target invocation.
- The catalog cannot write files, run experiments, launch code, access the open
  web, or mutate ResearchState.
- The paired engineering benchmark establishes deterministic safety/recovery
  behavior and controller-step proxies only. The preregistered study adds a
  narrow grounded evidence-acquisition endpoint, but independent domain review,
  broader main-workflow tasks and external replication remain
  required for scientific-efficiency, scientific-quality, or ADR-022 acceptance
  claims.
