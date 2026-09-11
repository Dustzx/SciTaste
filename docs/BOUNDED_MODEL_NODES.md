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
  candidate-action identifiers plus the cumulative project API cost immediately
  before the call. It is not a mutable `ResearchState` reference.
- `NodePolicy` is opt-in and pins allowed nodes, backend, model, action types,
  tool names, request bytes, tokens, API cost, latency, and ambiguity margin.
- `NodeResult` preserves the request and response plus a typed proposal or
  deterministic rejection reasons. A rejected result never exposes a trusted
  `proposal`; a structurally parsed value may be retained only as
  `untrusted_proposal`. Its literal authority fields cannot be set to executable
  values.

The Pydantic models freeze their outer fields but do not claim that nested JSON
containers are deeply immutable. Each invocation therefore revalidates deep
copies of its input, context, policy, audited request, backend-facing request,
and response. The backend never receives the audited request object, and a
mutation of its private request copy is a deterministic rejection.

Policy failures known before a call raise `NodePolicyViolationError` and do not
contact the backend. A clear deterministic action margin raises
`NodeNotApplicableError`, so `AmbiguousActionNode` cannot add cost to an
unambiguous decision. Failures observable only after a response—schema,
identity drift, budget, tool, reference, or action violations—produce a rejected
result that still retains response telemetry and hashes for audit.

`NodeContext.cumulative_api_cost_usd` is required and all policy limits are
finite. Before invoking a node, the caller must supply the project ledger's
current API cost. The node rejects a response when prior cumulative cost plus
the response's measured cost exceeds `NodePolicy.max_api_cost_usd`. Because a
model call may incur cost even when its response is rejected, the caller remains
responsible for recording every measured response cost—accepted or rejected—in
the deterministic project resource ledger before making another call. Missing
cost telemetry is never admissible.

## Initial nodes

| Node | Typed input | Proposal only | Deterministic checks |
|---|---|---|---|
| `ReviewSemanticNode` | free-text review and permitted evidence types | concerns and candidate action types | known claim/section IDs, evidence types, action allowlist |
| `VenuePaperReviewNode` | exact packet-bound anonymous paper text and the four venue questions | ICLR-style review content and typed concerns | packet/text hashes, known claims/sections, evidence types, action allowlist; no reviewer identity or numeric score |
| `InterpretationThreatNode` | existing result and interpretation context | validity threats, alternatives, follow-up action type | known evidence IDs, action allowlist; output has no claim-status field |
| `AmbiguousActionNode` | feasible actions and deterministic scores | ranking over supplied IDs | low-margin trigger, exact full-action match with the complete context candidate set, exact candidate coverage, candidate action allowlist |
| `EvidencePaperDraftNode` | closed claims, evidence, citations, venue duties, limitations, and numeric vocabulary | complete sectioned manuscript proposal plus a reference sidecar | exact input fingerprint and section order, known references, claim--evidence bindings, headline coverage, limitation retention, word budget, and numeric-token allowlist |

`EvidencePaperDraftNode` is the long-form content path, not another placeholder
renderer. Internal claim, evidence, citation, and limitation identifiers stay in
the typed proposal sidecar; `render_evidence_paper_markdown` emits only clean
paper prose using the venue builder's explicit Title/Abstract contract. Citation
IDs are converted to registered BibTeX keys by the deterministic renderer rather
than copied from model-authored citation markup. An empirical paragraph requires registered evidence, an unsupported
claim cannot be presented as a result, and every number in the generated title
and body must occur in the input's explicit numeric vocabulary. These checks do
not establish that the evidence itself is correct, so the draft remains a
proposal until the ordinary paper, venue, and review gates accept its artifacts.

The content-addressed DeepSeek profile
`runtime_profiles.deepseek_v4_paper_draft_v2.yaml` gives this node a 32,768-token
output envelope for a full manuscript. That is a per-call generation ceiling,
not a fixed limit on normal development. Live use still requires the normal
priced backend configuration, environment credential, exact runtime invocation,
and explicit `--allow-live`; committed files contain no secret. Offline scripted
execution and replay remain available for deterministic acceptance tests.

An accepted long-form proposal is not exported by trusting terminal output.
`scitaste project paper build-draft` reads it back through the verified durable
ledger, re-applies current admission, checks bibliography closure, and records a
self-hashed draft trace before invoking the ordinary venue-native Markdown,
TeX, PDF, assessment, and project-registration path.

Whole-paper review uses its own content-addressed profile set,
`runtime_profiles.deepseek_venue_review_v1.yaml`, and a separately copied local
backend configuration. The committed backend example remains disabled. The
project review CLI first verifies and freezes the exact paper, packet, claims,
sections, and caller-permitted evidence vocabulary into a normal runtime config;
it never calls the provider while constructing that config. See
`docs/PAPER_REVIEW_LOOP.md` for the complete command sequence and authority
boundary.

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
preflight identity failure; there is no fallback. A provider response with the
wrong request ID or fingerprint is durably recorded before evaluation and exact
replay reproduces the rejected `NodeResult`. Recordings may contain raw provider
text and belong under ignored project outputs, never in Git.

## Workload profiles and normal project runtime

Normal project invocations select one strict `ModelNodeProfile`. A profile makes
three different limits visible and fingerprinted instead of collapsing them into
one misleading token number:

| Layer | Meaning | Authority |
|---|---|---|
| `generation` | provider request bytes, requested output, context capacity, JSON and seed capabilities | limits what the adapter may request; it does not admit a proposal |
| `admission` | per-response input/output/total tokens, latency, measured cost and tool proposals | deterministic code accepts or rejects one proposal |
| `cumulative_project` | invocation, non-cached token and measured USD totals across restarts | the durable ledger blocks later calls or acceptance |

`runtime_profiles.example.yaml` content-addresses the committed short structured
and deeper semantic profiles. Both are offline scripted examples. They do not
claim provider pricing, enable live access, or authorize unrestricted code or
manuscript generation. In particular, the old 2,048-token engineering probe is
still local to its pilot adapter configuration; the normal short profile exposes
a 1,024-token provider envelope and an independent 512-token admission limit.
Additive extension nodes such as Discovery, Writing Taste, and evidence-grounded
paper drafting are registered by the runtime entry point and retain their own
strict input/output schemas; they cannot replace a built-in node.

`ModelNodeRuntime` runs beneath an already registered normal `ProjectRuntime`
run. Before a backend can be contacted, its immutable intent binds the project
revision, state revision and projection, node input, trigger, profile, policy,
provider/model, seed, request ID, and predecessor ledger hash. The project
manifest and `ResearchState` are not mutated. `ModelNodeFacade` is the narrow
workflow boundary: it accepts `ImmutableStateProjection` and returns a typed
`NodeResult` plus a durable receipt. Every result remains
`advisory_only=true` and `executable=false`.

The ledger persists accepted, rejected, not-applicable, failed, and planned
outcomes. Known usage from every non-cached response advances totals even when
schema or deterministic gates reject the proposal. Unknown paid cost is explicit
and blocks later priced work. Exact replay is cached and therefore preserves its
telemetry without incrementing cumulative token or USD effects. A changed state,
request, profile, policy, prompt, seed, provider, or model misses; replay never
falls through to a live or scripted backend.

Runtime evidence is project-owned:

```text
outputs/projects/<project-id>/runs/<run-id>/model_nodes/
  .runtime.lock
  ledger/00000000__<invocation-id>.json
  recordings/<invocation-id>.jsonl
  pending/<attempt-id>/
  attempts/<attempt-id>/failure.json
  attempts/<attempt-id>/recording.jsonl  # when a failed attempt returned a response
```

Ledger entries are an indexed, contiguous SHA-256 predecessor chain. Each entry
also binds its typed result and recording hashes. `status`/`verify` revalidates
the complete chain, typed schemas, standard recordings, archived-attempt hashes,
and cumulative totals after process restart. Writers use a non-blocking run lock
and exclusive fsynced publication. Runtime roots, nested attempt/pending entries,
recordings, ledger files, and the lock reject symbolic links and non-regular
evidence; security-sensitive reads use no-follow file opens so a nested path
cannot redirect verification or cleanup outside the owning run. Resume accepts
only the identical invocation intent and archives incomplete attempts. When a
live response was durably recorded before interruption, the runtime reconstructs
the exact request and consumes that response without provider access, retaining
its original non-cached token/cost effect exactly once. A complete ledger entry
is also returned idempotently if publication stopped before the caller wrote its
own result record. A possibly started live call with no complete response remains
unknown-cost and is never repeated. Completed pending state is first atomically
renamed to a disposable `.published--*` directory, so a crash during marker
deletion cannot make the ledger incomplete or cause the model call to repeat.

The project revision is checked once while registering the intent, again
immediately before the backend may run, and again after it returns. A revision
change before the call prevents backend access. A change during the call cannot
undo an already incurred provider charge, so the exact response recording and
known token/cost/latency telemetry are published, but the proposal is
deterministically rejected as stale.

The runtime CLI uses a strict JSON invocation configuration. It can contain an
offline scripted reply or an OpenAI-compatible configuration that names only an
API-key environment variable; embedded credential fields are rejected. The
selected profile remains a separate content-addressed profile-set binding:

```bash
scitaste model-node runtime plan \
  --project-id <project> --run-id <registered-run> \
  --invocation-id <new-id> --expected-revision <revision> \
  --config <invocation.json> \
  --profile-set configs/model_nodes/runtime_profiles.example.yaml \
  --profile-id short-structured-semantic --outputs-root outputs

scitaste model-node runtime execute [--resume] [--dry-run] \
  --project-id <project> --run-id <registered-run> \
  --invocation-id <new-id> --expected-revision <revision> \
  --config <invocation.json> --profile-set <profile-set.yaml> \
  --profile-id <profile-id> --outputs-root outputs

scitaste model-node runtime replay \
  --source-invocation <recorded-id> \
  --project-id <project> --run-id <registered-run> \
  --invocation-id <new-replay-id> --expected-revision <revision> \
  --config <the-identical-invocation.json> --profile-set <profile-set.yaml> \
  --profile-id <profile-id> --outputs-root outputs

scitaste model-node runtime status \
  --project-id <project> --run-id <registered-run> --outputs-root outputs

scitaste model-node runtime verify \
  --project-id <project> --run-id <registered-run> --outputs-root outputs
```

Plan, status, verify, replay, scripted execution, and `execute --dry-run` are
network-free. A live call requires all three independent permissions: the
profile permits live execution, the compatible backend configuration is itself
live-enabled with the required pricing declaration, and the caller passes
`--allow-live`. Omitting any switch persists a planned outcome with blockers and
does not access the credential environment variable or transport.

Machine JSON separates `generation_envelope`, `admission_budget`, and
`cumulative_project_budget`; reports per-invocation and cumulative token/cost/
latency telemetry, cache/replay state, blockers, hashes, and relative evidence
locators. It reports only proposal availability and authority flags—not proposal
content, raw provider responses, authorization headers, or secret values.

## Full Workflow integration

`run full` can bind `interpretation-threat` after deterministic evidence
interpretation. Scripted mode uses the offline profile set. The committed
GLM-5.3-Flash engineering condition uses
`runtime_profiles.live.example.yaml` and additionally requires
`--allow-live-model-nodes`; neither switch substitutes for the other.

Before the model runtime is entered,
`stages/evidence/model_advisory_input.json` binds the predecessor/evidence state,
decision log, evidence summary, original project revision, invocation ID,
profile, policy and advisory configuration. `model_advisory.json` then binds the
runtime receipt and ledger head, and `STAGE.json` hashes both. This extra
checkpoint lets a failed Full Workflow recover an already recorded provider
response without rerunning the Evidence workflow or contacting the provider.
Recovery after project-revision advancement keeps usage accounting but rejects
the pre-ledger proposal as stale. The live example is unpriced, so even an
ordinary successful response is rejected for missing cost telemetry and remains
engineering-only evidence.

## Live-model promotion boundary

`StructuredOpenAICompatibleBackend` provides a provider-SDK-free Chat
Completions adapter for a later live pilot. It sends the node's exact system
instruction separately from a canonical user payload containing the complete
bounded input, output JSON Schema, request fingerprint, state and policy
identities, prompt version, and seed. The configured model and seed are also
top-level request fields. The adapter requests `json_object` output; strict
schema validation remains in the deterministic node boundary.

Acceptance-eligible live use has three independent fail-closed switches:

1. `live_enabled` must be true;
2. finite non-negative USD input/output token rates with a timezone-aware
   capture timestamp and source must be present and explicitly confirmed;
3. the configured API-key environment variable must contain a value.

The key value is read only immediately before a call and is never stored in the
configuration, prompt, response, or logs. Provider usage must contain explicit
input/output token counts; supported aliases are `prompt_tokens` /
`completion_tokens` and `input_tokens` / `output_tokens`. Missing or conflicting
usage fails instead of becoming zero. The calculated USD cost and its full
pricing provenance are retained in `StructuredModelResponse` and record/replay.

An explicitly separate `unpriced_engineering_probe` mode exists only to test a
real endpoint when the provider exposes token usage but no rate that can be
verified for the account's billing route. It requires live mode, forbids price
configuration and retries, retains token/latency/raw-response evidence, sets
cost to unknown, and therefore deterministically rejects the proposal. Such a
call can establish adapter and schema behavior, but can never pass the cost gate
or support an effectiveness claim.

The exact decoded provider response body and its SHA-256 are retained together.
The requested model remains in the fingerprinted request and the provider's
returned model identity remains verbatim in the response, so the two cannot be
silently collapsed. A returned alias or fallback is rejected unless a new
runtime policy itself pins that returned identifier. The adapter never executes
provider tool calls: supported function-call structures become
`ToolCallProposal` values for later deterministic review, while unknown tool
types and malformed arguments fail closed. Transport retries are bounded to the
configured count and apply only to transport failures, HTTP 429, and HTTP 5xx;
HTTP 4xx and malformed semantic responses are not retried.

The whole-paper venue reviewer additionally specializes its output schema per
invocation. Only the packet's registered claim and section IDs, the explicitly
permitted evidence types, and the policy's allowed action types appear in that
schema. Category/action mismatch is checked again after parsing. This is a
generation aid plus deterministic admission boundary; it is not semantic repair
of a rejected review.

The committed
`configs/model_nodes/zhipu_glm53_flash.example.yaml` pins the general prepaid
OpenAI-compatible endpoint, `glm-5.3-flash`, and `ZAI_API_KEY`, but is intentionally
disabled and contains no guessed price. Before any live call, replace the null
pricing placeholder with rates verified for the account and billing route, add
their provenance, set `pricing_confirmed: true`, and only then set
`live_enabled: true`. Coding Plan credentials or endpoints are a separate
condition and must not be substituted silently. The example also keeps retries
at zero because a timeout or 5xx may be ambiguous about whether inference and
billing already occurred; enable retries only with a provider-specific accounting
rule for those attempts.

The committed `zhipu_glm53_flash.unpriced_probe.yaml` is the narrower executable
engineering configuration. GLM-5.3-Flash requires thinking to remain enabled;
the compatible payload therefore pins `thinking.type=enabled` and
`reasoning_effort=low`. The 2026-09-05 self-development run described below is a
real adapter probe, not a model-quality assessment or autonomy claim. A later
study may compare Zhipu `glm-5.3-flash`, local 2B/4B text models, and Qwen3-VL-4B
for a separate visual node. Each provider/model is a distinct registered
condition.

The probe's `max_output_tokens: 2048` is only the provider-request generation
ceiling for that one content-addressed backend configuration. It is not a global
SciTaste limit, a model context limit, or permission for the node result to pass.
The pilot's independent `NodePolicy.max_output_tokens: 100` remains the stricter
admission budget and is why a longer but valid provider response is retained and
rejected. Normal semantic nodes must select an explicit workload profile;
long-form code or manuscript generation belongs to a separately budgeted
executor/writing path and must not silently reuse this engineering-probe file.

ADR-022 must stay proposed until the local self-development record verifies at
least the registered gates: schema success rate 0.98, zero deterministic-gate
bypasses, complete record/replay coverage, at least 30% manual-intervention
reduction, no unsupported-claim increase, no unbounded tool calls, no more than
$0.15 additional API cost per project, and independent outcome review. Passing
the offline tests below establishes only the implementation substrate.

## Versioned self-development pilot

`bounded_self_development_pilot_v1.yaml` is the committed protocol fixture for
the implementation pilot. Its protocol, cases, input envelopes, `NodeContext`,
`NodePolicy`, budgets, expected applicability, allowed outcomes, seeds, and
backend/model identities are all explicit and closed to unknown fields. The
fixture is permanently marked `self_dogfooding_only: true`,
`retrieval_eligible: false`, and `effectiveness_claim: false`; a passing report
does not change those declarations. Its live condition is pinned to
`zhipu-direct / glm-5.3-flash`.

The runner distinguishes four conditions by concrete backend type:

| Condition | Behavior | Backend boundary |
|---|---|---|
| `deterministic_only` | pre-registers a required manual baseline and handleability judgment and never invokes a model backend | no backend binding is permitted |
| `scripted_node` | executes deterministic offline fixtures | only `ScriptedStructuredBackend`, optionally inside `RecordingStructuredBackend` |
| `replay_node` | reproduces an exact recorded request | only `ReplayStructuredBackend`; a replay miss never falls back |
| `live_structured_node` | remains a planned result when no backend is injected | executes only an explicitly injected `StructuredOpenAICompatibleBackend` whose own `live_enabled` gate is true |

Consequently scripted or replay evidence cannot be labelled as live evidence.
The committed fixture includes all three nodes, an applicable ambiguous-action
case, a clear-margin not-applicable case, and a recording/replay pair with an
identical request contract. The runner remains separate from the controller,
executor, retrieval corpus, and full workflow. The project-owned orchestration
layer described below is the only CLI/runtime integration for this pilot.

The committed protocol contains only `ManualInterventionRequirement` values: it
declares which case needs the baseline, which needs the observed count, and that
the deterministic baseline must assess whether the case is handleable without a
model. It contains no measured count, source, or evidence hash. Actual
`ManualInterventionMeasurement` values enter only as an external mapping keyed
by `case_id` when `BoundedPilotRunner.run` is called. Every supplied measurement
must repeat the matching case and role, name its real source, and pin its
measurement artifact with `evidence_sha256`; a baseline also records
`handleable_without_model`.

`BoundedPilotRunner` produces a result for every declared case plus separate
total-case and actual planned-outcome counts, followed by invoked,
not-applicable, accepted, rejected, schema-valid, gate-bypass,
unsupported-reference/action, token, measured-cost, latency, manual-intervention,
and bounded-tool-call counts. Only `accepted` increments `successful_count`;
expected rejections, deterministic baselines, planned live cases, and expected
not-applicable cases remain distinct audit outcomes. Each invocation retains the
request, response-content, result, and case-evidence fingerprints. A
deterministic-only result instead retains a fingerprint of its complete baseline
record, including whether external measurement evidence was present.

Exact replay coverage is credited only when the same report contains both a
successful non-cached recording and a successful cached replay with identical
request and response-content fingerprints. Merely configuring a replay case is
not evidence. Additional API cost is aggregated per project from non-cached
responses; missing cost telemetry blocks that acceptance metric.

The acceptance evaluator returns `pass`, `fail`, or `blocker` separately for:

- schema validity at or above 0.98;
- zero gate bypasses;
- zero cases left at the planned-only outcome;
- 1.0 exact recording/replay coverage;
- at least 0.30 measured manual-intervention reduction;
- no increase over the declared unsupported claim/reference/action baseline;
- zero tool-call proposals beyond the per-case bound;
- no more than USD 0.15 additional API cost per project;
- protocol-outcome conformance; and
- independent outcome review.

Missing denominators, required external manual measurements, telemetry, replay
pairs, or review evidence are blockers, never inferred passes. Missing manual
measurements do not abort the run and are listed by case ID in the report. A live
case without its explicitly injected backend remains `planned` and makes the
report blocked. Loading the committed protocol without live evidence, external
manual measurements, or independent review therefore produces an honest blocked
report. A report is eligible only when every metric passes. Eligibility still
means only that the registered pilot gates passed; it is not an effectiveness or
autonomy claim.

`save_pilot_report` verifies the report's canonical SHA-256, writes a fully
fsynced temporary file in the destination directory, and publishes it
atomically. It refuses to overwrite an existing path unless the caller makes
that choice explicit. Loading a report strictly revalidates its complete schema
and canonical hash, so content tampering is rejected.

## Project-owned orchestration and CLI

The production-facing orchestration layer registers each pilot as one unique
`ProjectRuntime` run. It accepts a strict, versioned orchestration configuration
whose relative input paths are confined to the configuration directory. Every
referenced protocol, scripted-reply bundle, live-backend configuration, manual
measurement bundle, and independent-review bundle carries an expected raw-file
SHA-256. The protocol also carries its canonical model SHA-256. Duplicate YAML
keys, unknown fields, absolute/traversing paths, symlink escape, content drift,
protocol drift, and backend/model identity drift fail before a run is created.

`configs/model_nodes/pilot_orchestration.example.yaml` is deliberately a
planning-only template. It contains the pinned `zhipu-direct / glm-5.3-flash`
binding but no scripted replies, manual measurements, review evidence,
credentials, prices, or effectiveness evidence. A plan made from that template
therefore reports its missing bindings and evidence rather than inventing them.
Scripted reply bundles must identify themselves as `fixture_only: true` and
`effectiveness_claim: false`; they can execute only scripted/recording
conditions. Manual measurements and review remain separate external evidence
types and are never derived from those fixtures.

The command namespace is:

```bash
scitaste model-node pilot plan \
  --project-id scitaste-self-development \
  --run-id <safe-unique-run-id> \
  --expected-revision <project-revision> \
  --config <orchestration.yaml> \
  --outputs-root outputs

scitaste model-node pilot execute \
  --project-id scitaste-self-development \
  --run-id <safe-unique-run-id> \
  --expected-revision <project-revision> \
  --config <orchestration.yaml> \
  --outputs-root outputs

scitaste model-node pilot execute --resume \
  --project-id scitaste-self-development \
  --run-id <existing-run-id> \
  --expected-revision <current-project-revision> \
  --config <the-identical-orchestration.yaml> \
  --outputs-root outputs

scitaste model-node pilot status \
  --project-id scitaste-self-development \
  --run-id <existing-run-id> \
  --outputs-root outputs
```

`execute --dry-run` is an alias for `plan`, including when paired with `--resume`.
A resume dry-run validates the existing registration, immutable execution
identity, owned evidence, and reusable checkpoint prefix without changing the
project revision or run files. Planning, status, tests, and default execution
never contact a provider. A live case runs only when the orchestration config
has `live_enabled: true`, the caller adds `--allow-live`, and the content-addressed
compatible backend config is also live-enabled. That backend must either have
confirmed pricing or explicitly declare the non-promotable unpriced engineering
mode. The credential environment variable is
not read while loading, planning, verifying, or executing earlier cases; the
compatible backend reads it only when the live case actually starts. Omitting
any live authorization leaves that case `planned` and the report blocked.

The canonical run evidence is contained below:

```text
outputs/projects/<project-id>/runs/<run-id>/model_node_pilot/
  manifest.json
  protocol.json
  orchestration.json
  external/                    # present only for supplied external evidence
  cases/0000__<case-id>.json   # immutable case-boundary checkpoints
  recordings/<pair-id>.jsonl  # exact recording used by replay
  recordings/live/<case-id>.json # exact request/body before semantic parsing
  attempts/<attempt-id>/       # archived incomplete and failed attempts
  report.json
  verification.json
```

Each checkpoint binds the protocol and config hashes, complete case hash,
effective binding and identity, optional external-measurement hash, exact
recording hash, typed result evidence, and predecessor checkpoint hash. Resume
reuses only a contiguous prefix that passes every binding and chain check.
Incomplete markers and orphan recordings are moved into a failed-attempt
directory before retry. A changed protocol/config/backend/measurement, corrupt
checkpoint/report/recording, stale project revision, non-contiguous prefix, or
existing final destination fails closed.

A newly registered pilot becomes the project's explicit `current_run`. A valid
resume increments `resume_attempt`, restores the run to `running`, and reselects
it when necessary, but only after the existing prefix has validated. `status`
cross-checks the immutable evidence chain against the registered protocol,
configuration, manifest, report, verification, artifact, acceptance, and final
run-status metadata; valid files cannot mask a drifted `PROJECT.json` entry.
If both final files were fully published and validate but the process stopped
before registering their hashes, an explicit resume performs metadata-only
finalization and does not rerun cases. A lone report or verification file is a
half-published state and remains a manual, fail-closed boundary.

Publication uses exclusive, fsynced atomic writes and a non-blocking per-run
writer lock. Two writers therefore cannot silently replace case or final
evidence. CLI summaries are JSON and include project/run identity, project
revision, protocol/config/report/verification hashes, case completion/planned/
blocker counts, exact acceptance state, and measured token/cost/latency totals.
They never include API-key values or raw provider responses.

The runtime has an additive `ModelNodeRegistration` extension boundary for
domain consumers. Extensions must register a node class and its exact input and
output models under the class's own name; they cannot replace built-ins. A
runtime reopening a ledger must supply the same extension registry, otherwise
typed verification fails closed. Project-owned Discovery uses this boundary for
`discovery-hypothesis`, `discovery-reformulation`, and `discovery-ideation`,
while retaining the shared cumulative ledger, recording, revision gate, and
interruption recovery semantics. Reformulation is scoped to a predecessor
hypothesis and registered contradictions. Ideation is scoped to the active
hypothesis and registered reproducible observations, returns only one problem
plus three to eight divergent idea seeds, and cannot rank, select, execute, or
allocate actual resources. Its larger offline profile permits 4,096 output
tokens per response; all three nodes still share one 50,000-token cumulative
project ceiling.

Application bindings hash the complete non-secret backend configuration, not
only provider/model labels. Invocation-aware construction lets a single strict
runtime config serve the command-derived ledger ID without weakening request or
resume identity; embedded credential values remain forbidden.

The live transport persists the exact request payload and decoded response body
under the owning project before higher-level schema parsing. It deliberately
omits authorization headers. The file hash is bound into the case checkpoint
and final verification record; if parsing later fails, the exchange moves with
the incomplete marker into the immutable failed-attempt directory. This keeps a
paid-but-malformed response auditable and prevents resume from silently treating
it as completed evidence.

## 2026-09-05 real engineering probe

`2026-09-05__zhipu-glm-5.3-flash__model-node-probe-02` completed all seven
registered cases inside `scitaste-self-development`. The real live case returned
the pinned model identity and schema-valid JSON with 1,001 input and 587 output
tokens; the complete pilot used 1,622 tokens and 16,033 ms. The live proposal
was correctly rejected for token, latency, missing-cost, unsupported-action, and
related policy violations. The report therefore has `effectiveness_claim=false`,
`acceptance_status=blocker`, and three unresolved blockers: external manual-
intervention measurements, complete price/cost telemetry, and independent
outcome review. It also records one actual safety-metric failure caused by the
unallowlisted `ADD_ANALYSIS` proposal.

An earlier 512-output-token attempt ended with provider `finish_reason=length`.
That exact exchange was archived, and a new content-addressed run—not an in-place
rewrite—raised the transport ceiling to 2,048 tokens. See
`docs/experiments/zhipu_glm53_model_node_probe_2026-09-05.md` for the evidence
hashes and interpretation boundary.

## Verification

```bash
.venv/bin/python -m pytest tests/model_nodes
make check
git diff --check
```

Pilot tests label their manual measurements as synthetic fixtures and exercise
the live condition with the real compatible-backend class plus a fake transport;
neither is evidence for the committed self-development pilot. The tests cover
accepted proposals, strict schema rejection, invented references
and actions, disabled nodes, clear-margin bypass, provider/model drift, token,
finite cumulative cost and latency limits, missing cost telemetry, unallowlisted
tools, raw hash validation, boundary mutation detection, exact recording/replay
of accepted and rejected responses, replay misses, missing-key and disabled-live
preflight, request identity, provider model drift, token aliases, explicit price
calculation, malformed live responses, bounded HTTP retry behavior, and live
adapter record/replay through fake transports. Tests never access the network.
