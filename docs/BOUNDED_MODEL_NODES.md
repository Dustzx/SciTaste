# Bounded model nodes

Bounded model nodes add an optional semantic-advice layer without transferring
SciTaste's control authority to a model. They implement the infrastructure part
of ADR-022; ADR-022 remains **proposed** until the registered self-development
pilot measures schema success, intervention reduction, cost, unsupported claims,
and independent outcome review.

## Authority boundary

```text
bounded state projection + typed node input
  -> deterministic preflight policy
  -> pinned structured backend
  -> raw-response hash + usage telemetry
  -> strict Pydantic output schema
  -> reference/action/tool/budget gates
  -> NodeResult(advisory_only=true, executable=false)
  -> existing deterministic controller and executor boundaries
```

The model cannot update `ResearchState`, close a reviewer concern, promote a
claim, expand a budget, authorize a tool, execute an action, or apply a state
transition. An accepted `NodeResult` means only that the proposal is structurally
valid and policy-admissible for later deterministic consideration.

## Contracts

- `StructuredModelRequest` contains the node, state snapshot, complete bounded
  input, output JSON schema, prompt version, seed, normalized policy fingerprint,
  and pinned backend/model identity. Its SHA-256 fingerprint changes when any of
  those inputs or policy limits change.
- `StructuredModelResponse` contains the parsed payload, backend/model identity,
  exact raw-response SHA-256, input/output tokens, optional measured cost, latency,
  tool-call proposals, and cache state.
- `NodeContext` is a deliberate projection of claim, evidence, section, and
  candidate-action identifiers. It is not a mutable `ResearchState` reference.
- `NodePolicy` is opt-in and pins allowed nodes, backend, model, action types,
  tool names, request bytes, tokens, API cost, latency, and ambiguity margin.
- `NodeResult` preserves the request and response plus a typed proposal or
  deterministic rejection reasons. Its literal authority fields cannot be set to
  executable values.

Policy failures known before a call raise `NodePolicyViolationError` and do not
contact the backend. A clear deterministic action margin raises
`NodeNotApplicableError`, so `AmbiguousActionNode` cannot add cost to an
unambiguous decision. Failures observable only after a response—schema,
identity drift, budget, tool, reference, or action violations—produce a rejected
result that still retains response telemetry and hashes for audit.

## Initial nodes

| Node | Typed input | Proposal only | Deterministic checks |
|---|---|---|---|
| `ReviewSemanticNode` | free-text review and permitted evidence types | concerns and candidate action types | known claim/section IDs, evidence types, action allowlist |
| `InterpretationThreatNode` | existing result and interpretation context | validity threats, alternatives, follow-up action type | known evidence IDs, action allowlist; output has no claim-status field |
| `AmbiguousActionNode` | feasible actions and deterministic scores | ranking over supplied IDs | low-margin trigger, exact candidate coverage, candidate action allowlist |

The interpretation taxonomy includes confounders, alternative explanations,
statistical uncertainty, benchmark artifacts, compute mismatch, data leakage,
and implementation artifacts. It keeps result, observation, interpretation, and
claim status separate as required by the Evidence Loop.

## Offline use and replay

`ScriptedStructuredBackend` supplies deterministic fixtures and never contacts a
provider. Wrap any future structured backend in `RecordingStructuredBackend` to
append the full request and response as JSONL before policy evaluation:

```python
recorded = RecordingStructuredBackend(backend, "outputs/model-nodes/responses.jsonl")
result = ReviewSemanticNode().run(
    review_input,
    context=context,
    backend=recorded,
    policy=policy,
    request_id="review-001",
    seed=7,
)
```

`ReplayStructuredBackend` accepts only the exact request fingerprint and one
pinned backend/model identity per recording file. A changed prompt, schema,
state snapshot, seed, policy, provider, or model produces a replay miss or a
preflight identity failure; there is no fallback. Recordings may contain raw
provider text and belong under ignored project outputs, never in Git.

## Live-model promotion boundary

This iteration deliberately has no live structured-generation adapter and makes
no model-quality or autonomy claim. A later pilot may bind the generic protocol
to Zhipu `glm-5.3-flash`, local 2B/4B text models, and Qwen3-VL-4B for a separate
visual node. Each provider/model is a distinct registered condition and must
report real tokens, latency, and cost; missing cost is not treated as zero.

ADR-022 must stay proposed until the local self-development record verifies at
least the registered gates: schema success rate 0.98, zero deterministic-gate
bypasses, complete record/replay coverage, at least 30% manual-intervention
reduction, no unsupported-claim increase, no unbounded tool calls, no more than
$0.15 additional API cost per project, and independent outcome review. Passing
the offline tests below establishes only the implementation substrate.

## Verification

```bash
.venv/bin/python -m pytest tests/model_nodes
make check
git diff --check
```

The tests cover accepted proposals, strict schema rejection, invented references
and actions, disabled nodes, clear-margin bypass, provider/model drift, token,
cost, and latency overruns, missing cost telemetry, unallowlisted tools, raw hash
validation, exact recording/replay, and replay misses.
