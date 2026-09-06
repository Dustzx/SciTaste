# Evidence-Grounded Generative Research Interface

SciTaste's generative interface uses a fixed, trusted application shell and a
dynamically selected research workspace. The generated object is data, not code:
it can choose from registered native components and bind those components to a
specific project snapshot, but it cannot define HTML/JavaScript renderers,
command-bearing fields, callbacks, tool calls, or state mutations. Text is always
untrusted display text and is never evaluated.

This module is a contract and interaction-boundary layer plus a trusted
ProjectRuntime adapter. It includes a framework-neutral renderer document and a
runnable, local receiver-owned browser/API application. An optional bounded
structured model may classify a long-tail question or arrange server-owned
component candidates. It does not include controller approval or a task
executor, and the provider never authors renderer content.

## Evidence-native project workspace

`WorkspaceSurfaceFactory` is the server-owned composer for eight closed views:
project list, project progress, project overview, run/stage explorer,
paper/evidence, run comparison, blockers, and pending proposals. A browser may select only the
view and canonical project-owned run or paper identities defined by the
corresponding discriminated query model. It cannot submit components, fields,
layout, evidence, filters, prose, or renderer code.

Every project view is rebuilt from a fresh `ProjectRuntime` snapshot. The query
identity, project revision, snapshot hash, surface contents, and every displayed
evidence hash feed the returned fingerprints. Unknown or stale deep links fail
closed. Empty projects, absent papers, unavailable stages, and missing
comparable metrics use explicit typed availability states; the composer does not
invent research progress or substitute model-authored explanations.

The fixed receiver provides a project switcher, the seven project-scoped view
controls, run and paper selection, comparison controls, freshness/provenance,
and browser back/forward deep links. Conditional GET uses the workspace
fingerprint as an ETag. The responsive shell and all navigation remain receiver
code shipped in the package; only validated component data changes. Every
workspace render and project-selector change clears the prior run and paper
catalogs before admitting identities from the newly validated view, so browser
history cannot retain another project's selection controls. A project change
also clears the prior quick-intent catalog, free-question value, generated
layout, proposal result, artifact preview, response cache, and current document
before any newly selected project is rendered.

### Progress-first self-hosting view

`project-progress` is the default view after selecting a project. Its
`ProjectProgressBoard` is a receiver-owned component built from the current
`PROJECT.json`, registered run records, current stage binding, and registered
paper manifests. It reports observed record counts, the selected current run,
declared focus and next gate, latest registered activity in manifest order,
completed AutoResearchClaw stages where those semantics apply, paper state,
blocked/failed run attention, and evidence-supported next-step candidates.

Progress is categorical rather than numeric. The contract distinguishes
`observed_completed`, `current_work`, `blocked`, `failed`, `candidate`,
`unavailable`, and `unknown`; it deliberately has no percent, ratio, schedule,
or estimated-completion field. A selected `current_run` is described as a
selection and never upgraded to currently executing. A completed run also does
not make the project complete. Status mapping uses a small exact allowlist so a
novel or compound status remains `unknown` unless its meaning is explicitly
registered.

Every visible progress row carries supporting evidence references. Run and
paper status rows cite both `PROJECT.json` and their content-addressed run or
paper record because selection and status come from the project manifest.
Optional `current_focus`, run `blockers`, and `iterations` extensions are parsed
through strict local schemas. Invalid extensions degrade to an explicit
unavailable/fallback state rather than becoming display data. A milestone
locator covered by a bound evidence directory is marked `content_addressed`;
otherwise it remains only `manifest_declared` and is never exposed as an
inspection target.

Next-step entries are capabilities for later intent planning, not controller
decisions. They can offer progress review, blocker diagnosis, comparison of the
latest two registered runs, paper-evidence review, or review of a declared next
gate only when their required project records exist. They contain no command or
execution authority.

The existing `scitaste-self-development` project is a read-only self-hosting
acceptance case. At revision 21 it truthfully yields nine registered runs, four
observed completions, two blocked records, one failed record, one candidate,
one unknown reference, four manifest-declared milestones, no registered paper,
and a blocked overall project status. That project record predates some later
repository work, so the UI must not infer newer progress from Git or docs. Main
must register later milestones through the normal `ProjectRuntime` workflow if
they should appear in this view.

### Unified intent and surface-plan contracts

Quick clicks and free questions enter one snapshot-bound intent boundary. A
`QuickIntentRequest` names only a server-issued quick-intent ID; a
`FreeQuestionRequest` carries bounded opaque text for resolution but that text
is deliberately absent from every `WorkspaceIntent`, `IntentResolution`,
surface, renderer, and audit document. Request fingerprints retain request
identity without turning the question into display content.

`WorkspaceIntentResolver` derives its quick catalog from the current
`ProjectProgressBoard.next_step_candidates`. An empty project therefore offers
only progress review; blocker diagnosis, run comparison, paper review, and
next-gate review appear only when the current manifest and evidence binding make
them possible. Equivalent quick and recognized free-form requests resolve to
the same canonical `WorkspaceIntent` fingerprint.

The initial deterministic resolver recognizes progress, blocker, comparison,
paper-evidence, and next-step goals in Chinese or English. A free comparison
must name exactly two registered Run IDs or returns a bounded Run candidate set.
A paper request with multiple registered papers likewise requests
clarification. Unknown long-tail language returns
`provider_unavailable/long-tail-question-requires-planner` until the optional
planner boundary is configured; it never guesses an entity or fabricates an
answer.

Resolved intents contain one project-manifest binding plus only the Run or paper
evidence roles required by the closed goal. The raw question and input modality
are excluded, so the intent is a scientific target rather than a transcript.
All references are revalidated against the exact `SnapshotBinding`.

`SurfaceCandidateFactory` then assembles complete server-owned component and
action candidates from the existing closed workspace views. It scopes component
and action IDs to prevent collisions and validates the whole catalog as one
legal `SurfaceSpec`. An external planner receives only
`SurfaceCandidateDescriptor`: candidate ID, registered component enum, source
view, evidence IDs, reason code, and allowed group/emphasis enums. Component
data, titles, action proposals, paths, and evidence content are withheld.

A `SurfacePlan` can contain only an ordered candidate ID, closed group,
closed emphasis, and optional focus evidence IDs for each entry. It is bound to
the project, snapshot, canonical intent, and complete candidate-catalog
fingerprints. It has no prose, component schema, component data, action, URL,
path, callback, command, or authority field. Materialization copies the selected
trusted `ComponentSpec` and `ActionBinding` objects unchanged; an unknown
candidate, cross-candidate evidence reference, disallowed group, duplicate ID,
or stale fingerprint rejects the complete plan.

### Planner boundary and offline fallback

`WorkspacePlanner` exposes only two advisory operations: classify a long-tail
question by selecting one server-issued quick-intent ID, and compose a surface
by returning a closed `SurfacePlan`. There is deliberately no execute, mutate,
transition, callback, fetch, or tool method. Deterministic intent recognition in
`WorkspaceIntentResolver` remains the first path; the optional classifier is
only useful after that path returns `long-tail-question-requires-planner`.

`DeterministicWorkspacePlanner` orders trusted candidates by a versioned stable
rule and works without a provider. `StructuredWorkspacePlanner` adapts the
existing provider-neutral `StructuredModelBackend`; it does not import a vendor
SDK or read credentials itself. Classification receives the bounded question
and a list of closed quick-intent IDs/goals/registered target IDs. Composition
receives only snapshot and intent hashes plus data-free candidate descriptors.
Neither operation receives evidence content, component data, action proposals,
artifact paths, titles, URLs, or controller state.

The model response is untrusted. Backend/model identity, request bytes,
response bytes, token telemetry, latency, tool-call absence, exact response
binding, closed Pydantic schema, snapshot hashes, intent hash, catalog hash, and
final plan materialization are all checked in code. Prompt instructions are
defense in depth, not the trust boundary. A failed or malicious composition is
replaced by the deterministic layout through `FallbackWorkspacePlanner`; a
failed long-tail classification remains explicitly unavailable because guessing
an intent would change meaning.

Accepted provenance records planner implementation and configuration hashes,
snapshot, intent, candidate catalog, structured request, provider response hash,
and result plan hash. It never records the free question or credentials.
Model-assisted results set `deterministic_reproducible=false`; deterministic
fallbacks identify the attempted provider planner and bind the independently
reproducible fallback plan. The existing OpenAI-compatible backend supplies the
transport timeout and server-side environment-variable credential lookup; the
UI adapter additionally rejects provider configurations whose retry-adjusted
timeout exceeds its policy bound.

```text
question ──> deterministic resolver ──resolved──┐
   │                                            │
   └─long-tail─> optional ID-only classifier ───┤
                                                v
project snapshot ─> trusted candidate factory ─> planner
                                                │ IDs/enums only
                                                v
                                 validate + materialize SurfacePlan
                                                │
                                                v
                                  fixed native component receiver
```

Provider construction remains disabled unless the server receives both a
non-secret planner configuration and explicit live-planner authorization. With
no provider, the same visible interaction uses the deterministic planner.

### Visible generation-as-content flow

The fixed navigation now asks “What do you want to understand?” and provides
both evidence-derived quick-intent buttons and an editable bounded question
field. The buttons are not a universal prompt menu: each comes from the current
`ProjectProgressBoard.next_step_candidates`. Both controls submit a
`WorkspaceGenerationRequest` to the same service and bind the exact quick
catalog, project revision, snapshot hash, and request fingerprint.

Successful generation visibly changes component order, grouping, emphasis, and
the set of goal-relevant panels. The receiver shows the admitted intent goal,
planner mode, snapshot revision, execution authority, and a short server-owned
explanation for each component. Layout classes affect only the fixed CSS grid;
the response still contains no markup or renderer code. A failed request leaves
the current workspace visible and reports clarification candidates, missing
evidence, provider unavailability, stale state, or rejected planning in the
intent panel.

Generated surfaces are retained in memory by exact project and surface ID so
browser back/forward and proposal-only actions resolve against the precise
validated surface instead of invoking the model again. Every retrieval and
action rehashes current project evidence. A server restart deliberately drops
this cache; an old generated deep link then fails stale rather than attempting
to recreate a non-deterministic result. Opening a generated surface starts the
same project-owned audit epoch used by fixed views. Generated actions and
artifact inspections still stop at their existing proposal/read-only
boundaries.

## Trusted project surface factory

`ProjectSurfaceFactory` is the first-party entry point for a real project
overview. Its constructor accepts a `ProjectRuntime`, and its build methods
accept only a canonical project ID. It does not accept a caller-authored
`ProjectSnapshot`, `SnapshotBinding`, evidence list, component, or action. The
factory delegates evidence discovery and hashing to `ProjectSnapshotAdapter`,
projects the resulting surface through the fixed shell, and checks the runtime
snapshot and evidence binding again before returning.

The overview always contains `ProjectSummaryCard`, grounded by `PROJECT.json`.
It adds components only when their exact authoritative inputs exist:

- `RunHealth` for the selected registered run;
- `StageTimeline` when the project explicitly uses
  `autoresearchclaw-stages`, has completed stages, and has a current stage
  record;
- `PaperPreview` for a valid selected paper manifest;
- `ArtifactViewer` for the first declared supported paper artifact, selected
  deterministically in PDF, Markdown, TeX, then plain-text order.

Missing optional state omits its component. Missing or corrupt evidence for
state that the project claims is selected fails closed. Values are copied from
the relevant manifest without status rewriting or guessed summaries. In
particular, `PaperPreview.excerpt` is null because the paper manifest does not
define an authoritative excerpt. Run and stage components cite both their
record and `PROJECT.json`, because their visible status and completed-stage
facts come from the project manifest.

Evidence IDs are the adapter's deterministic locator-derived IDs. For an
unchanged project and artifacts, canonical surface JSON and its fingerprint are
stable. A project revision, manifest value, or referenced artifact-content
change changes the snapshot binding and therefore the surface fingerprint,
even if a directly edited artifact did not increment the project revision.

Generated actions are limited to typed `proposal_only` requests for run or
paper approval and artifact inspection. The factory never activates them. An
optional explicit `write_project_overview` call creates a new destination with
`surface.json`, `renderer.json`, and a `SurfaceAuditLog.start` record in
`surface-audit.jsonl`. Publication is transactional: the helper writes all three
files into a unique temporary directory beside the destination, reloads the
surface and renderer through their schemas, verifies and replays the audit log,
and only then atomically renames the complete directory into place. Failure at
any pre-publication step removes the temporary directory and leaves no final
destination. An existing file, directory, or symbolic link is never reused or
overwritten. On Linux the publication step uses `renameat2` with
`RENAME_NOREPLACE`; if that atomic no-replace operation is unavailable, the
helper fails closed instead of falling back to an overwrite-capable rename.
Building a surface alone writes nothing.

The same trusted path is available without application code:

```bash
.venv/bin/scitaste project surface build \
  --project-id my-project \
  --outputs-root outputs \
  --destination outputs/projects/my-project/surfaces/overview-v1
```

Add `--dry-run` to validate and fingerprint the authoritative in-memory surface
without creating the destination. The command reports the selected trusted
components and proposal IDs; it does not activate those proposals.

The factory itself still stops at the declarative boundary: it does not provide
a model-driven layout generator, deterministic controller, approval workflow,
or action executor. The local application described below revalidates every
interaction through `SurfaceSession`, but its successful receipt still stops
before the later controller boundary.

## Local receiver application

`GenerativeUIApplication` owns one `ProjectRuntime`,
`ProjectSurfaceFactory`, and the project-local audit boundary. It discovers only
canonical, non-symlink project directories that open as valid runtime
snapshots. Surface requests rebuild current authoritative state and return a
`RendererDocument`; the browser never receives the server-owned `SurfaceSpec`
action payloads.

The versioned same-origin JSON API is deliberately closed:

- `GET /api/v1/projects` returns canonical project IDs and revisions;
- `GET /api/v1/projects/<project-id>/surface` returns the current fixed-shell
  renderer document;
- `POST /api/v1/projects/<project-id>/events` accepts exactly `SurfaceEvent`
  and returns exactly `ProposalReceipt` with HTTP 202.
- `GET /api/v2/workspace/projects` returns the authenticated project-list view;
- `GET /api/v2/workspace/projects/<project-id>/<view>` returns one current
  workspace, with typed `/runs/...` or `/papers/...` suffixes only where the
  closed query permits them;
- `POST` to the same workspace path plus `/events` records a proposal-only
  interaction;
- `POST` to a workspace path containing a visible artifact plus `/inspections` accepts exactly
  `ArtifactInspectionEvent` and returns a bounded `ArtifactInspectionDocument`.
- `GET /api/v3/generative/projects/<project-id>/intents` returns the current
  evidence-derived `QuickIntentCatalog` and fingerprint;
- `POST /api/v3/generative/projects/<project-id>/workspace` accepts one
  `WorkspaceGenerationRequest` and returns a question-free
  `GeneratedWorkspaceDocument`;
- `GET /api/v3/generative/projects/<project-id>/generations/<surface-id>`
  revalidates and returns an exact in-memory admitted generation;
- `POST` to that generated path plus `/events` or `/inspections` resolves only
  against the retained server-owned surface.

There is no general filesystem, artifact download, callback, controller, tool,
or model endpoint. Query strings are rejected, so credentials cannot be passed
in a query. API requests require an exact bearer authorization header, compared
in constant time. The fixed HTML, CSS, and JavaScript shell is public because it
contains no project state or credential; all project data remains behind the
authenticated API. The browser retains the credential only in its password
input and does not use local or session storage.

The packaged JavaScript contains a closed receiver function for every
`TrustedComponent`. It creates elements and text nodes with `createTextNode` or
`textContent`; it never assigns generated text to HTML, script, URL, or event
handler slots. The Content Security Policy permits same-origin script, style,
image, and API connections plus receiver-created in-memory image Blob URLs; it
forbids objects, base changes, framing, and form actions. There are no remote
assets. `ArtifactViewer` is not a file link and never receives an arbitrary URL.

At event submission the application rebuilds the current surface from
`ProjectRuntime` before resolving the identity-only event. A changed project
revision, evidence hash, artifact, surface fingerprint, cross-project ID,
unknown action, or stale tab is rejected before an audit append. Accepted
events are recomputed from the server-owned surface, then appended under
`outputs/projects/<project-id>/.generative-ui/audits/`. Audit epochs are keyed by
snapshot and surface fingerprints, allowing direct artifact changes at an
unchanged project revision to invalidate the old surface without conflating two
bindings. Each epoch remains hash-chained and replayable; replay on process
restart restores duplicate-event protection. File locking serializes concurrent
accepted events.

Serve the application with a credential sourced from an environment variable:

```bash
export SCITASTE_UI_TOKEN='replace-with-a-long-local-secret'
.venv/bin/scitaste ui serve --outputs-root outputs
```

The default bind is `127.0.0.1:8765`. `--token-env NAME` selects another
environment variable; `--token-file PATH` reads a regular non-symlink file.
There is intentionally no plaintext token argument. A non-loopback `--host`
fails validation unless `--i-understand-non-loopback-exposure` is also present.
`--dry-run` validates the complete configuration and credential source without
opening a listening socket or creating the outputs root.

The offline deterministic planner is the default. Enabling the optional
OpenAI-compatible structured planner requires two independent operator inputs:

```bash
export SCITASTE_UI_TOKEN='replace-with-a-long-local-secret'
export ZAI_API_KEY='read-by-the-provider-backend-only'
.venv/bin/scitaste ui serve \
  --outputs-root outputs \
  --planner-config configs/model_nodes/zhipu_glm53_flash.unpriced_probe.yaml \
  --enable-live-planner
```

The committed GLM-5.3-Flash probe config is an explicitly unpriced engineering
condition, not a production price claim. A normal live configuration must use
confirmed pricing as required by `StructuredOpenAICompatibleConfig`.
`--planner-config` without `--enable-live-planner`, or the flag without a
configuration, fails validation. The YAML may name only the API-key environment
variable; embedded credentials are rejected. Dry-run output includes only the
provider, model, mode, and configuration hash, never the endpoint credential or
question. No live provider call is part of the automated test suite.

This receiver does not approve or execute the returned proposal. The only next
boundary named by a valid receipt is `deterministic_controller`, which is not
called by the HTTP service or browser.

## Safe artifact inspection

Artifact inspection is a separate read-only operation, not approval of the
`inspect_artifact` proposal. The browser sends only event, project, surface,
snapshot, and visible artifact-reference identities. The server rebuilds the
workspace and requires exactly one `ArtifactViewer` in that current view to
name the reference. Callers cannot supply a locator, MIME type, preview kind,
URL, command, or renderer.

The inspector accepts only project-relative evidence already hashed in the
surface. It opens the project and every nested directory through no-follow file
descriptors, opens only a regular final file, checks descriptor/path identity
after the read, enforces a fixed media/extension pair, applies byte limits, and
recomputes SHA-256. Missing, changed, swapped, symlinked, oversized, or
MIME-confused files invalidate the operation.

The preview catalog is closed:

| Media | Maximum | Receiver behavior |
|---|---:|---|
| UTF-8 plain text, Markdown source, TeX source, JSON | 512 KiB | inert `<pre>` text; JSON keys must be unique |
| PNG, JPEG, WebP | 5 MiB | verified bytes copied into a receiver-created Blob URL |
| PDF | 20 MiB | verified byte length, hash, media type, and PDF version only |

Markdown is not converted to HTML, HTML/script-like source is not interpreted,
and PDFs are not embedded into an active object. There is no download, path, or
general filesystem endpoint. Successful inspection records metadata and the
artifact hash in the project audit chain; preview bytes themselves are not
persisted by the UI service.

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
| `AvailabilityNotice` | `AvailabilityNoticeData` |
| `RunStageExplorer` | `RunStageExplorerData` |
| `EvidenceInventory` | `EvidenceInventoryData` |
| `RunComparisonPanel` | `RunComparisonPanelData` |
| `RunBlockerPanel` | `RunBlockerPanelData` |
| `PendingProposalList` | `PendingProposalListData` |
| `ProjectProgressBoard` | `ProjectProgressBoardData` |

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

The packaged local receiver implements those four regions directly. Its assets
are build-time package data rather than generated project output and reference
no remote script, stylesheet, font, or renderer.

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

## Auditable interaction history

`SurfaceAuditLog` stores accepted UI history as self-hashed, predecessor-linked
JSONL. A log starts with one complete `surface_opened` record and can append only
`surface_revised`, `proposal_issued`, or `artifact_inspected` records. Each
append first validates and semantically replays the entire history; a proposal
receipt must be reproducible from the server-owned action, and an inspection
receipt must match a visible artifact binding, before it can be recorded.

Writes replace the complete log atomically and are serialized with thread and
local-process locks. Audit storage walks every parent component with no-follow
directory descriptors, opens the lock relative to the retained directory,
writes and replaces a temporary file through that same descriptor, and verifies
the directory and lock identities before release. Replacing an audit parent or
lock with a symbolic link therefore fails closed and cannot redirect a write
outside the original directory. New logs use atomic no-replace publication;
updates use atomic exchange, verify that the displaced inode is exactly the
record that was read, and roll the exchange back if a target, lock, directory,
or temporary-file identity changed. A partially written final record, a changed
payload, a missing or reordered record, a stale revision, a duplicate event, or
a forged receipt therefore fails verification. Replaying a valid log
reconstructs both the current surface and the accepted-event set. These audit
publication guarantees require Linux `renameat2`; an unavailable syscall fails
closed rather than falling back to an overwrite-capable rename.

The pending-proposals workspace reads only fully verified project-local chains,
content-addresses each contributing audit file as `audit_record` evidence, and
checks every opened/revised surface and every proposal/inspection event and
receipt against the owning project directory, and then shows the recorded
pending receipts. A corrupt, changing, oversized, symlinked, renamed
cross-project, or otherwise foreign history is rejected instead of partially
displayed. Pending still means advice awaiting the later deterministic
controller; this view has no approval or mutation operation.

Each audit epoch is capped at 8 MiB and fails closed when the limit is reached.
The log records proposals and read-only inspections, not executions. Persisted
receipts retain `proposal_only` authority and `execution_authority: none`; no log
API invokes a controller, tool, model, or state mutation. The hash chain detects
corruption or editing relative to the copy being inspected, but is not a digital
signature and does not establish authorship. A future ProjectRuntime event-log
integration should anchor the latest record hash in a separately trusted project
record if protection against full-history replacement is required.

## Trusted components

The registry contains `ProjectSummaryCard`, `StageTimeline`,
`BlockerList`, `RunHealth`, `BudgetMeter`, `DecisionComparison`, `EvidenceGraph`,
`ClaimMatrix`, `ReviewerQueue`, `ArtifactViewer`, `PaperPreview`,
`AvailabilityNotice`, `RunStageExplorer`, `EvidenceInventory`,
`RunComparisonPanel`, `RunBlockerPanel`, `PendingProposalList`, and
`ProjectProgressBoard`. A renderer
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
- executable authority or undeclared fields;
- stale/cross-project events, repeated event IDs, and unknown action IDs;
- surface revisions based on stale fingerprints or inconsistent snapshot hashes;
- changed, truncated, reordered, or semantically inconsistent audit histories;
- non-visible, changed, oversized, symlinked, swapped, MIME-confused, or
  cross-project artifact inspections.

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
11 original contract component data schemas is instantiated. Workspace tests
exercise the six additional navigation components against real
`ProjectRuntime` fixtures. None of these deterministic fixtures is research
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
| `WorkspaceQuery` | closed client-selectable view identity |
| `ArtifactInspectionEvent` | identity-only request for a visible evidence preview |
| `SurfaceAuditRecord` | receiver-side append-only interaction history |

An adapter may translate a validated `SurfaceSpec` into A2UI messages after the
project-runtime binding is available. It must preserve component registry checks,
evidence IDs, snapshot revision/hash, and `proposal_only` authority. A2UI events
must return to a deterministic approval/controller boundary; they must not be
mapped directly to shell commands or tools.
