# Tool Intelligence

Tool Intelligence is SciTaste's bounded execution-intelligence layer. It makes
semantic judgment available at selected rigid-tool boundaries without making a
model the controller or executor. The v1 vertical slice added typed tool-plan
and structured-repair advice on top of the durable model-node runtime described
in `BOUNDED_MODEL_NODES.md`. The v2 slice adds a deterministic, single-step,
read-only execution boundary for fresh accepted tool-plan advice.

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
registered deterministic read-only handler
        |
        v
typed observation + post-call revision check
        |
        v
no automatic evidence admission or state transition; controller decides next
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
fingerprint. Changing the records between lease issue and execution therefore
requires a different handler identity and fails closed.

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

- No workflow automatically detects a semantic hotspot, requests a Tool Plan,
  or accepts a Tool Observation. The v2 API is an explicit controller-facing
  substrate.
- Lease consumption is atomic only inside one executor process. Durable
  cross-process claim/receipt storage and crash recovery remain a later
  integration gate, so leases must not be serialized and resumed as if they
  were globally single-use.
- Knowledge, evidence, and metric registries are caller-bound in memory. A main
  integration must build them from verified project-owned locators without
  weakening path/symlink containment.
- Handler observations are not persisted by this slice and cannot become
  canonical evidence without a separate deterministic admission record.
- No live provider profile or live call is included.
- Repair supports four pinned output schemas and performs structural validation;
  target-specific semantic gates require a new target invocation.
- The catalog cannot write files, run experiments, launch code, access the open
  web, or mutate ResearchState.
- Implementation and replay tests do not establish intervention reduction,
  scientific benefit, or the ADR-022 acceptance claim.
