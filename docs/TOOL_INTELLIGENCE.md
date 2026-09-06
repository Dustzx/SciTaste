# Tool Intelligence

Tool Intelligence is SciTaste's bounded execution-intelligence layer. It makes
semantic judgment available at selected rigid-tool boundaries without making a
model the controller or executor. This first production vertical slice adds
typed tool-plan advice and structured-repair advice on top of the durable model
node runtime described in `BOUNDED_MODEL_NODES.md`.

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
no execution; a separate deterministic controller must decide the next action
```

An accepted Tool Intelligence result always has `advisory_only=true` and
`executable=false`. The same fields are repeated on Tool Plan steps. Acceptance
does not authorize filesystem access, a process, a network request, a state
transition, API spending, or any real tool invocation.

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

These are capability descriptions and typed proposal schemas. This increment
does not add an executor for them. In particular, `knowledge.query` describes a
future invocation over project-owned Knowledge storage; it does not silently
open web search. `registered-run.compare` names already registered runs and
does not launch experiments.

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

The node does not schedule or execute the resulting list. A future controlled
executor must consume only a fresh, revision-checked deterministic admission
record, not model output or a `NodeResult` directly.

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
- replay misses with silent live fallback;
- process restart, incomplete publication, and ledger tampering through the
  shared runtime.

The deterministic caller that constructs a scope or permission profile remains
part of the trusted computing base. It must derive library and evidence
identifiers from verified Knowledge and evidence records. A caller-provided
profile is not proof that those identifiers exist outside the bounded node
context; run identifiers are the exception because the runtime resolves them
against the project manifest.

Before adding real execution, a later Epic must define handler identities,
input/output evidence receipts, per-handler sandbox and resource profiles,
revision checks immediately before and after each tool call, interruption and
unknown-cost semantics, idempotency, output-schema validation, and a separate
deterministic accept/reject transition. Mutable, networked, generated-code, and
GPU tools require distinct profiles and threat reviews; none may inherit v1
read-only status by name similarity.

## Current limitations

- No tool is executed by this subsystem.
- No workflow automatically requests either node.
- No live provider profile or live call is included.
- Repair supports four pinned output schemas and performs structural validation;
  target-specific semantic gates require a new target invocation.
- The initial catalog cannot write files, run experiments, launch code, access
  the open web, or mutate ResearchState.
- Implementation and replay tests do not establish intervention reduction,
  scientific benefit, or the ADR-022 acceptance claim.
