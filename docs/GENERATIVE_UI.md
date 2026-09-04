# Evidence-Grounded Generative Research Interface

SciTaste's generative interface uses a fixed, trusted application shell and a
dynamically selected research workspace. The generated object is data, not code:
it can choose from registered native components and bind those components to a
specific project snapshot, but it cannot define HTML/JavaScript renderers,
command-bearing fields, callbacks, tool calls, or state mutations. Text is always
untrusted display text and is never evaluated.

This module is a contract and interaction-boundary layer plus a trusted
ProjectRuntime adapter. It includes a framework-neutral renderer document, but
not a web server, actual renderer, model call, authenticated API, or task
executor.

## Contract hierarchy

`SnapshotBinding` identifies the exact `project_id`, snapshot revision, snapshot
hash, and content-addressed `EvidenceRef` records used by a surface. An evidence
locator is project-relative and cannot traverse outside the project.

The snapshot hash has one normative representation: SHA-256 over compact,
key-sorted UTF-8 JSON containing `schema_version: 1.0`, the canonical project ID,
the snapshot revision, and the full evidence records sorted by `evidence_id`.
`SnapshotBinding.from_trusted_evidence` is the low-level adapter entry point and
validation recomputes the same hash. `ProjectSnapshotAdapter.build_binding` is
the first-party trusted entry point: it opens the authoritative project through
`ProjectRuntime`, resolves every locator beneath that project root, recomputes
each evidence hash, and confirms that the runtime revision did not change during
binding.

`SurfaceSpec` binds that snapshot to one or more `ComponentSpec` objects. Each
component is selected from the closed `TrustedComponent` registry and cites the
evidence IDs supporting its visible data. The registry also declares the evidence
kinds required by each component. For example, `PaperPreview` requires paper
evidence, `RunHealth` requires a run record, and `ClaimMatrix` requires both claim
and evidence records.

Every registered component has a closed data model. Unknown or missing fields are
invalid, and visible rows carry typed evidence-reference fields that must resolve
within the component. `DecisionComparison` uses a discriminated `view` field for
transition and run-comparison data. Artifact paths must exactly match the locator
of their content-addressed artifact evidence.

| Component | Closed data model |
|---|---|
| `ProjectSummaryCard` | `ProjectSummaryData` |
| `StageTimeline` | `StageTimelineData` |
| `BlockerList` | `BlockerListData` |
| `RunHealth` | `RunHealthData` |
| `BudgetMeter` | `BudgetMeterData` |
| `DecisionComparison` | `DecisionComparisonData` |
| `EvidenceGraph` | `EvidenceGraphData` |
| `ClaimMatrix` | `ClaimMatrixData` |
| `ReviewerQueue` | `ReviewerQueueData` |
| `ArtifactViewer` | `ArtifactViewerData` |
| `PaperPreview` | `PaperPreviewData` |

Adapters and receivers can obtain the exact JSON Schema for any registry member
with `component_data_json_schema`; every object in those schemas forbids extra
properties.

`ActionBinding` attaches an `ActionProposal` to a visible component. The only
initial proposal kinds are:

- `inspect_artifact`;
- `compare_runs`;
- `propose_transition`;
- `request_approval`.

Every proposal serializes `authority: proposal_only`. It has no command, URL,
tool name, callback, or executor field. Transition and approval proposals must
set `requires_approval`; a later deterministic controller decides whether a
proposal is feasible and accepted. Each approval subject is also restricted to
its corresponding evidence kind: decision, artifact/paper, paper, run record, or
blocker evidence.

`SurfaceRevision` replaces a prior surface as an auditable, fingerprint-linked
document. It does not patch `ResearchState` and cannot execute its declared
proposal.

## Fixed-shell projection

`project_surface` converts a validated surface into `RendererDocument`. The
document pins `scitaste-research-shell` with fixed `header`, `project_nav`,
`workspace`, and `inspector` regions. Generated components can populate only the
`workspace` region and must still name a trusted native renderer.

The projected action metadata contains an action ID, presentation hint, proposal
kind, and approval flag. It deliberately omits the server-owned proposal payload
and rationale, so a browser cannot rewrite a transition target or its evidence
references. `RendererDocument.execution_authority` is always `none`.

## Interaction handshake

A renderer emits a `SurfaceEvent` containing only identity fields: event/action,
project, surface revision/fingerprint, and snapshot revision/hash. Arbitrary
client payloads are schema-forbidden. `SurfaceSession` compares every binding to
the current server-owned surface before resolving the registered action.

Successful activation returns a `ProposalReceipt` with status
`proposal_pending`, execution authority `none`, and next boundary
`deterministic_controller`. It neither invokes that controller nor modifies
research state. Accepted event IDs cannot be replayed.

`SurfaceSession.replace` applies a complete `SurfaceRevision` only when the
previous revision and fingerprint still match. It rejects project changes,
snapshot regression, and any difference in the complete `SnapshotBinding` for an
unchanged snapshot revision. The session revalidates deep serialized copies at
construction and replacement, returns copies rather than its internal surface,
and does not share receipt proposals with internal state. This prevents nested
list/dictionary mutation from bypassing validation or a stale browser tab from
proposing against a new research state.

## Trusted components

The initial registry contains `ProjectSummaryCard`, `StageTimeline`,
`BlockerList`, `RunHealth`, `BudgetMeter`, `DecisionComparison`, `EvidenceGraph`,
`ClaimMatrix`, `ReviewerQueue`, `ArtifactViewer`, and `PaperPreview`. A renderer
must map these identifiers to code shipped with and trusted by the application.
An unknown component is invalid rather than a request to generate new UI code.

## Validation and threat boundary

The primary content-safety boundary is the per-component closed field schema:
generated data cannot introduce a URL, callback, command, handler, source, or
other unregistered slot. Defense-in-depth text checks reject common active
content, but intentionally do not claim to recognize every programming language
or command written as prose. Trusted renderers must always render text as text and
must never evaluate it.

Together, the Pydantic contracts and closed schemas reject:

- raw HTML markers and common active JavaScript forms;
- common shell syntax/commands and every command-bearing field;
- registered or protocol-relative remote URI forms;
- absolute paths, backslashes, encoded traversal, repeated separators, and dot
  segments;
- unknown components and unknown evidence IDs;
- duplicate component, action, metric, or evidence IDs;
- action evidence that is outside the component to which the action is bound;
- proposal targets with the wrong evidence kind;
- status or paper fields without suitable content-addressed evidence;
- executable authority or undeclared fields.
- stale/cross-project events, repeated event IDs, and unknown action IDs;
- surface revisions based on stale fingerprints or inconsistent snapshot hashes.

A valid binding proves that its evidence manifest matches its snapshot hash; a
binding created by `ProjectSnapshotAdapter` also proves that every referenced
file or directory existed beneath the project root when it was hashed. Directory
hashes cover the sorted relative tree and file-content hashes; nested symlinks
are rejected. Renderers must never accept a binding authored by an untrusted
client as proof of existence, and artifact access must verify the stored hash
again if files can change after surface creation.

Project-runtime identity is canonical lowercase kebab-case. Existing
`ResearchState` records historically allowed arbitrary strings; an adapter must
reject or explicitly migrate a non-canonical ID before snapshot construction. It
must not silently lowercase, trim, or replace characters because that could merge
two project identities.

## Deterministic fixtures

`scitaste.generative_ui.fixtures` provides five data-only surfaces for project
overview, paper status, blocked-run diagnosis, next-step proposal, and run
comparison. They use clearly named fixture evidence and are intended only for
contract, renderer, and integration tests. Across those surfaces every one of the
11 registered component data schemas is instantiated. They are not research
evidence.

All surface fields have stable canonical JSON and a SHA-256 content fingerprint.
Object key order does not change the fingerprint; any visible value or binding
change does.

## Future A2UI projection

The contracts intentionally resemble the safe subset of A2UI without depending
on an A2UI package in this phase:

| SciTaste contract | Future A2UI role |
|---|---|
| `SurfaceSpec` | declarative surface/update root |
| `TrustedComponent` | receiver-owned component catalog entry |
| `ComponentSpec.data` | data-model values bound to a native component |
| `ActionBinding` | user event declaration |
| `ActionProposal` | typed event payload sent back for validation |
| `SurfaceRevision` | versioned surface replacement/update |
| `RendererDocument` | receiver-owned shell plus declarative workspace update |
| `SurfaceEvent` | identity-only user event returned to the agent boundary |

An adapter may translate a validated `SurfaceSpec` into A2UI messages after the
project-runtime binding is available. It must preserve component registry checks,
evidence IDs, snapshot revision/hash, and `proposal_only` authority. A2UI events
must return to a deterministic approval/controller boundary; they must not be
mapped directly to shell commands or tools.
