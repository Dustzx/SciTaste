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

- The complete bridge is available below `model_nodes/**`, but the final call
  site in the main-owned full workflow is intentionally left as an explicit
  integration step for the primary window.
- One attempt executes at most one dependency-free read-only action. A
  `replan-required` result requires a new typed state projection and a new
  bounded model invocation; the model never executes its proposed DAG.
- A custom handler interrupted after its start marker requires human
  reconciliation. Declaring custom code "read only" does not make it replay
  safe.
- No live provider profile or live call is included.
- Repair supports four pinned output schemas and performs structural validation;
  target-specific semantic gates require a new target invocation.
- The catalog cannot write files, run experiments, launch code, access the open
  web, or mutate ResearchState.
- The paired benchmark establishes deterministic safety/recovery behavior and
  controller-step proxies only. A registered matched live-model study and an
  independent domain review remain required for scientific-efficiency,
  scientific-quality, or ADR-022 acceptance claims.
