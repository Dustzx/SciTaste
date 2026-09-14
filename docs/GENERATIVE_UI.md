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
structured model may classify a long-tail question and, in one call, arrange
server-owned component candidates plus author a concise cited brief. The brief
is inert text, each point names selected candidate and evidence IDs, and it may
also carry a compact evidence-cited visual canvas whose nodes and relations are
model-authored inside a closed receiver schema. Follow-up feedback must name the
exact predecessor turn it edits. An explicit deterministic controller can
approve a bounded handoff, but the model never authors renderer code or
authority.

## Evidence-native project workspace

`WorkspaceSurfaceFactory` is the server-owned composer for nine closed views:
project list, project progress, project overview, run/stage explorer,
paper/evidence, run comparison, blockers, pending proposals, and a registered
research-evaluation landscape. A browser may select only the
view and canonical project-owned run or paper identities defined by the
corresponding discriminated query model. It cannot submit components, fields,
layout, evidence, filters, prose, or renderer code.

Every project view is rebuilt from a fresh `ProjectRuntime` snapshot. The query
identity, project revision, snapshot hash, surface contents, and every displayed
evidence hash feed the returned fingerprints. Unknown or stale deep links fail
closed. Empty projects, absent papers, unavailable stages, and missing
comparable metrics use explicit typed availability states; the composer does not
invent research progress or substitute model-authored explanations.

The fixed receiver provides a project toolbar, the eight project-scoped view
controls, run and paper selection, comparison controls, freshness/provenance,
and browser back/forward deep links. The fixed views and evidence selectors are
grouped under one receiver-owned `Evidence tools` disclosure; they remain
available without competing with project content or conversation history.
Conditional GET uses the workspace
fingerprint as an ETag. The responsive shell and all navigation remain receiver
code shipped in the package; only validated component data changes. Every
workspace render and project-selector change clears the prior run and paper
catalogs before admitting identities from the newly validated view, so browser
history cannot retain another project's selection controls. A project change
also clears the prior quick-intent catalog, free-question value, generated
layout, proposal result, artifact preview, response cache, and current document
before any newly selected project is rendered.

The receiver-owned left drawer has one responsibility: project-scoped
conversation history. It contains new-topic, title-search, rename, topic, and
immutable turn-page controls, but no fixed-view or evidence-selection controls.
The drawer is closed by default. On a fine-pointer desktop, moving onto the
left-edge affordance previews it without shifting content or adding a backdrop;
moving into the drawer preserves the preview, while leaving closes it after a
short intent delay. Clicking pins it, Escape closes it, keyboard focus opens it,
and touch layouts use the same explicit button with a modal backdrop. No state
is persisted and no model is called by these shell interactions.

Questions are not placed in that navigation tree. Evidence-derived prompt chips
sit above a single-row-first text entry that grows only to a bounded height;
Enter submits, Shift+Enter inserts a newline, and the verified-context selector
remains visible but secondary. This bottom composer and the main workspace share
a viewport-height content column, so evidence scrolls inside the workspace while
the current interaction remains available below it. The compact composition is
a receiver layout choice, not evidence or a learned preference claim.

The navigation hierarchy is deliberately four-level: the portfolio index lists
all registered projects; each project opens to its stable `project-progress`
home; a first question creates a project-owned research conversation; and every
question or follow-up is an immutable turn page with its own deep link. Follow-up
questions stay in the active conversation, while `New conversation` returns to the project home
and makes the next question start a separate context. The active conversation expands
its ordered page list, so earlier questions are navigable without relying on
browser history. A generated page displays a `project / conversation / page`
breadcrumb and human-readable page ordinal; storage identities remain available
only in its provenance details. This is a project workspace model, not one
disconnected chat window per sentence.

Topic management is metadata-only. A user may rename a topic through an
optimistic `metadata_revision` check and filter the current project's topic
titles with a literal, case-insensitive browser search. Renaming preserves every
immutable turn byte and deep link; title filtering does not search prompt or
generated-document contents and does not call a model. Project-local shared and
exclusive file locks coordinate readers, appends, creation, and renames across
local server processes. A stale rename returns a conflict and reloads current
metadata instead of overwriting it.

An unrenamed quick-intent conversation keeps its stable intent ID in storage,
but the receiver projects the current server-issued `label_code` in the active
locale for both its topic title and quick-turn label. A user-authored rename
replaces that projection. Thus internal identifiers such as
`review-project-progress` remain available for audit and search without becoming
the default human-facing history label.

Each follow-up explicitly chooses either the current question alone or at most
the eight latest immutable turns. The receiver submits only their IDs; the
server reloads them from the same project and conversation and verifies their
registered order. Prior questions may guide intent selection, while only the
latest validated model-authored brief is exposed to composition as an explicit
edit predecessor. Components, actions, controller decisions, and arbitrary
renderer payloads are never replayed as model authority. The selected IDs and a
hash of the exact context are bound into the generated document and immutable
turn.

The browser shell contains no credential field. Loopback use establishes an
ephemeral HttpOnly session automatically; a remote deployment must enforce
identity and project access outside the content surface, through an explicit
bearer API client or a deployment-owned authentication gateway.

Generated page identities bind an explicit receiver-envelope version and the
exact materialized surface fingerprint. A compatible repeated question reuses
identical archived bytes; a component or receiver schema change creates a new
immutable generation identity instead of overwriting or colliding with an older
page at the same project revision.

### Progress-first self-hosting view

`project-progress` is the default view after selecting a project. Its
`ProjectProgressBoard` is a receiver-owned component built from the current
`PROJECT.json`, registered run records, current stage binding, and registered
paper and evaluation manifests. It reports observed record counts, the selected
current run, declared focus and next gate, latest registered activity in
manifest order, completed AutoResearchClaw stages where those semantics apply,
paper state, blocked/failed run attention, exact no-run API/GPU proposal
resources, canonical no-network data-acquisition decisions, and
evidence-supported next-step candidates.

A registered `review-driven-research-iteration-plan` run adds one compact
review-iteration map to this home. The receiver independently rehashes the exact
review round, every report and cumulative routing bundle, the terminal routed
state, and the plan before admitting it. It aggregates the potentially large DAG
into horizontal research/method/evidence/writing/review lanes, keeps each lane's
nodes collapsed with bounded internal scrolling, exposes cross-lane dependency
counts, and distinguishes immediately available no-run work, dependency-blocked
work, owner-approval gates, and independent reviewer verification. The plan
remains inspectable as its exact run artifact and explicitly carries
`authorizes_execution=false`.

The browser renders this baseline as a layered decision brief rather than a
serialized field inspector. Its always-visible layer contains one categorical
status statement followed by four canonical research-room launchers: project
direction, experiments and evaluation, paper and review, and risks and
decisions. Each launcher is bound to a currently available server-issued
candidate and creates a conversation page only after the user selects it; the
home does not fabricate four placeholder conversations. Current
focus/run/next gate, a collapsed lifecycle conclusion, and a compact
evidence-vault summary follow those launchers. The
nine exact record counts, run distribution, acquisition requests, full
evaluation cards, result cards, blockers, milestones, and recent activity remain
in that default-collapsed vault. Generated progress responses select only the
progress brief and a project evidence graph instead of repeating generic
summary, run-health, and blocker cards. Raw evidence IDs, full run IDs, locators,
and secondary status fields remain available through native disclosures. This
changes only receiver-owned presentation: all visible values are deterministic
functions of validated component data, and no browser prose is fed back as
research evidence.

The project graph contains at most 24 nodes and 64 edges; the current progress
composer uses at most 12 nodes spanning the project manifest, five recent runs,
two papers, four evaluation proposals, three results, and one stage-history
record where those records exist. Each node kind and ID is revalidated against
the immutable snapshot. The receiver draws only local SVG primitives. Selecting
a node reveals its evidence identity; an explicit exploration button creates a
bounded progress question and another immutable page in the same conversation.
It does not treat graph layout, labels, or selection as new research evidence.

An acquisition run appears as a decision card only when it registers the exact
`runs/<run-id>/acquisition/REPORT.json` locator under the canonical
`acquisition` stage. The server rejects symlinked, missing, oversized,
out-of-project, or schema-inconsistent reports and binds the accepted bytes to
the run evidence hash. The compact card exposes the exact request and report
hashes, pinned item count, aggregate byte ceiling, allowlisted hosts, readiness,
and authorization state. It also retains the stronger negative facts that no
network access, download, dataset creation, ingestion authority, or execution
authority occurred. Its button and quick prompt generate an immutable review
page in the active project conversation; neither is an approval or download
control. If immutable history contains several reports for the same request ID,
the latest manifest entry supplies the current card while every earlier run
remains visible in project activity.

A completed download appears through a registered
`runs/<run-id>/acquisition_receipt/RESULT.json` bundle. The server validates the
bundle totals and no-authority boundary, reopens every referenced canonical
receipt, verifies its file and semantic hashes, and requires an exact matching
project acquisition gate. The resulting card shows observed bytes and source
hosts as `acquired · content unopened`; it exposes content inspection as the
next gate and does not relabel the source as ingested or experiment-ready.
Once that receipt is present, the older gate is removed from the pending list,
so completed downloads cannot continue to appear as awaiting owner approval.

Downloaded structured benchmark metadata advances through a separate canonical
`runs/<run-id>/metadata_audit_planning/BUNDLE.json` artifact. The receiver
replays every bound YAML/CSV plan against its exact acquisition receipt, checks
the plan, receipt, and bundle file hashes, and recomputes the current auditor
implementation identity. It then renders the exact item count, accepted
formats, aggregate read ceiling, and either the explicit content-read decision
or an implementation-drift repair action as the next scientific-data gate.
This card is intentionally visible before the collapsed evidence vault: it
distinguishes bytes already acquired from content still unopened. Navigation to
the frozen evidence is not approval, and the bundle cannot inspect content,
project fields, ingest data, follow links, call a model, or start an experiment.

After an independently approved projection, a registered
`runs/<run-id>/benchmark_metadata_projection/POPULATION.json` supersedes the
corresponding audit-plan card. The receiver replays its plan, approval, scope,
request, receipt, and audit hashes without reopening raw metadata. The compact
population card shows only the complete record count, format, screen-field
count, retained source-field-gap count, and next scientific decision; projected
field values remain in the inspectable artifact rather than expanding the
project home. It explicitly states that no task was selected and that formal
outcomes, installed models, and compute inventory were not consulted. The next
action can review a frozen screening proposal but cannot silently convert the
population into an experiment-ready subset.

A completed screen appears only at the canonical
`runs/<run-id>/benchmark_metadata_screening/REPORT.json` locator. The receiver
replays the population, scope, projection plan and approval, rulebook, complete
decision package, control hashes, chronology, and current screening
implementation without reopening raw benchmark metadata or assessment evidence.
For each scope it supersedes the projection card and renders compact eligible,
excluded, and unresolved counts, whether the full record-by-rule population was
screened, and the next gate. An unresolved screen points back to evidence
resolution; a complete screen points to a powered allocation proposal. Neither
state is shown as task selection or experiment readiness, and the inspect action
opens the immutable evidence page rather than mutating the project.

A powered allocation plan is recognized only at
`runs/<run-id>/benchmark_metadata_allocation_planning/PLAN.json`. The receiver
replays its complete screening chain and objective-H3 clustered-power evidence,
then shows eligible records, distinct source groups, powered units, strata, and
blockers without displaying a selected identity. An implementation-current,
scientifically ready plan exposes exact approval as the next interaction; a
blocked or drifted plan exposes repair instead. The card cannot itself allocate
tasks, and its navigation button only opens immutable run evidence.

After exact approval, a canonical
`runs/<run-id>/benchmark_metadata_allocation/REPORT.json` supersedes the plan,
screening, and population cards for that scope. The receiver replays the plan,
approval, screen, population, rulebook, decisions, power request, pilot evidence,
and deterministic allocation. Its compact card shows powered/selected counts,
covered strata, retained unsampled eligibility, and the formal task-set hash;
individual identities remain in the evidence page. The next interaction is
asset qualification and prelaunch review, not execution. This strongest-state
projection keeps the project home short while preserving the earlier records in
run history and the evidence graph.

A post-download qualification appears only through the separately registered
`runs/<run-id>/acquisition_qualification/REPORT.json` artifact. The receiver
rechecks the report's embedded semantic hash, exact task and byte arithmetic,
scientific-use partition, path containment, and size before rendering it. Its
card distinguishes brief/package-prepilot eligibility from formal empirical
and objective-progress eligibility and displays the exact blocker codes. It
also preserves the negative authority facts: qualification cannot ingest data,
execute a task, call a provider, or use a GPU. This prevents an already
downloaded prompt collection from looking like an executable benchmark merely
because its acquisition step completed.

When a qualification binds the exact request SHA-256 of an older acquisition
gate, the stronger terminal evidence replaces that gate card in the active
decision list. The immutable request run remains available in history and as
provenance, but it no longer appears as “awaiting approval” beside proof that the
same request was already acquired and qualified. Pending requests with different
hashes remain separate decision cards.

An executable-benchmark qualification is likewise projected only from the
canonical `runs/<run-id>/benchmark_qualification/REPORT.json` locator of a
registered run. The receiver revalidates the report's self-hash and exact
selected/excluded task partition before displaying it. The compact decision
card renders the accepted-to-selected-to-first-preflight funnel, the declared
GPU-hour ceiling, exact first acquisition-review candidates, tasks excluded by
the single-device memory boundary, and separate metadata, acquisition, local
preflight, and experiment gates. Its review action opens an immutable evidence
page; it cannot acquire an asset, connect to a provider, inspect a GPU, or
launch an experiment. The card is absent for projects without this registered
evidence rather than showing a synthetic empty state.

Every evaluation card is derived from a project-owned `EVALUATION.json` whose
five bound artifacts are rehashed before rendering. Any record, manifest,
resource corpus, gate, critic, or cell-plan drift fails the project surface
closed. Selecting a proposal is navigation only: the card explicitly retains
`no_execution_performed=true`, and the interface has no provider-call, download,
GPU-launch, or approval-escalation path.

The card does not present hundreds of expanded diagnostics as hundreds of user
decisions. A deterministic seven-segment rail groups them into task scope,
comparator adapters, statistical design, temporal integrity, independent
review, runtime resources, and owner approval. It shows the next unresolved
decision, affected-identity count, exact diagnostic count, and content hash;
collapsed evidence still retains every original code. This is presentation
taste over verified state, not a model summary.

Registered experiment results form a separate section from proposal readiness.
Each result card is reconstructed from a project-owned immutable result bundle
and exposes planned/succeeded/failed/missing/invalid cell counts, valid external
review count, scientific-evidence completeness, headline eligibility, and
whether all required primary contrasts support the claim. The project lifecycle
disclosure separately states whether the current paper binds that exact result
and whether a subsequent independent review closes the top-venue evidence loop.
Consequently, a completed robustness result, an old paper, or a self-review
cannot be presented as a formal paper-level effectiveness result.

The canonical progress summary and a generated workspace have distinct roles.
`project-progress` is the stable, reproducible landing view. The bottom quick
prompts and free-question composer, together with the progress view's four core
research-room launchers, all cross the same typed intent endpoint to request a goal-specific generated
arrangement. Thus the user gets a useful synthesis before asking anything and a
visibly recomposed component workspace after expressing an intent. The latter
is generation-as-content; it remains a selection and arrangement of
server-authored evidence components, not generated HTML or a model-written
answer.

Progress is categorical rather than numeric. The contract distinguishes
`observed_completed`, `current_work`, `blocked`, `failed`, `candidate`,
`unavailable`, and `unknown`; it deliberately has no percent, ratio, schedule,
or estimated-completion field. A selected `current_run` is described as a
selection and never upgraded to currently executing. A completed run also does
not make the project complete. Status mapping uses a small exact allowlist so a
novel or compound status remains `unknown` unless its meaning is explicitly
registered.

A manual receiver check against an earlier revision at a 1720-pixel desktop viewport
confirmed that the summary rendered without browser errors, reduced the initial
document height from roughly 6606 to 2045 pixels, kept 19 evidence disclosures
available, and let an `Explore next` choice reach the retained generated-view
route. These dimensions are a visual-regression observation, not a product
metric or progress claim.

A later receiver check against project revision 301 verified the registered
MLRC-Bench qualification at 1440-, 768-, 390-, and 320-pixel widths. The
qualification appeared directly below the progress brief, the page retained a
bounded viewport-height workspace, and no document-level horizontal overflow,
browser runtime error, or sub-24-pixel enabled target was observed. These are
interaction and layout checks only; they do not validate benchmark fitness or
scientific effectiveness.

Project revision 303 adds the next decision artifact without expanding the page
into an archive ledger. The compact dataset-package card shows the 39-archive
and 3.503-GiB transfer, 16-GiB unpack and 32-GiB free-space bounds, the two task
license dispositions, and the exact blocker/authority split. Its review action
opens a generated evidence workspace through the existing intent contract; it
cannot approve a download or execute the task. Exact per-object URLs, ETags,
timestamps, and license sources remain in the content-bound report rather than
becoming a long default-page table.

A Chromium DevTools emulation at 1440, 768, 390, and 320 CSS pixels observed
equal document and viewport widths, equal workspace client/scroll widths, one
bounded package card, and no browser exception. After the quick-intent catalog
finished loading, the card's review action created a first immutable page in a
project conversation at revision 303 and disclosed deterministic planning with
no execution authority. The check is receiver engineering evidence, not a
human-usability result.

Project revision 308 replaces that package card's coarse license disposition
with the content-bound MLRC first-preflight policy result. The selected run now
shows that all 39 archive identities are acquisition-license-ready for an exact
owner decision while preserving two AWA per-image-license checks as unresolved
ingestion qualifications. The same card continues to report an empty approval-
blocker set separately from the five post-approval qualifications and retains
`authorizes_download=false` and `authorizes_ingestion=false`. This registration
is self-dogfooding evidence for the interface and control plane only; it is not
a dataset acquisition, experiment, or scientific-effectiveness result.

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
latest two registered runs, paper-evidence review, review of a declared next
gate, a registered acquisition decision or qualification, a registered
dataset-package review, an executable-benchmark qualification, or a registered
evaluation landscape or reviewer-driven iteration only when their required
project records exist. They
contain no command or execution authority.

### Research synthesis as generated visual content

The `research-landscape` view prevents a prose experiment plan from becoming a
premature protocol. It reads only a strict, project-owned
versioned `autoresearch-evaluation-landscape-v1` through `v6` artifact declared
by a registered run; the latest `v6` schema carries separated contribution
types, publication evidence, and experiment tracks. The artifact is bounded, schema-closed, contained
beneath that run, and covered by the run-directory hash in the current snapshot.
An absent projection becomes an explicit unavailable state; an escaping,
oversized, duplicate-key, malformed, or stale artifact fails closed.

The receiver applies a versioned research-synthesis Taste instead of displaying
the source audit chronologically. It keeps six estimands separate; foregrounds
primary comparisons and resource-bearing precedents; maps work against eight
lifecycle stages; distinguishes executed, mixed, artifact-only, and simulated
signals; and places benchmarks, systems, and judges on a reference-to-adaptation-
to-formal readiness ladder. Contextual benchmarks and unresolved design choices
use progressive disclosure. No completion percentage, universal score, or
inferred superiority appears.

The same projection now exposes two non-interchangeable experiment tracks. The
system-comparator track contains accepted methods and only the system portion of
hybrid papers; the evaluation-infrastructure track contains benchmarks, tasks,
datasets, rubrics, judges, and only the corresponding portion of hybrid papers.
They meet at a matched-protocol gate rather than in one paper leaderboard. The
schema fixes prevalence inference to `not-estimable`, because the method side is
a census candidate while evaluation resources are a targeted design sample.
Candidate readiness is rendered separately for systems and for benchmarks or
judges, so an adapted benchmark cannot visually imply an adapted baseline
system. Publication status and execution readiness are orthogonal: archival
acceptance cannot waive an adapter gate, and a runnable preprint cannot enter
the headline system lane. The v5 schema requires at least two accepted external
headline candidates while keeping preprint-only systems in sensitivity analysis.

The current v6 synthesis contains 16 method, 6 hybrid, and 23
benchmark/evaluation entries. Its primary page does not present these as a
single ranked list: it renders the three contribution lanes separately, then
derives a system-comparator track and an evaluation-infrastructure track from
their declared artifacts. The counts are corpus diagnostics only. Because the
fourth screen still found material accepted methods and evaluation resources,
the map keeps the literature freeze on `hold` and points to a focused
citation/resource screen.

This Taste is a presentation and abstraction policy, not a factual rewriter. It
chooses relationships, visual hierarchy, compression, and disclosure while
preserving the registered synthesis bytes and evidence identities. The current
self-development artifact therefore leads with `hold`: the literature map is
sufficient to identify the next no-run work, but exact held-out tasks, matched
adapters, statistical power, expert calibration, and a resource manifest remain
blocked. The map can justify continuing experiment *planning*; it cannot
authorize downloads, provider calls, GPU work, human recruitment, or formal
cells.

On 2026-09-11 the earlier v3 two-track projection was exercised through the real local
receiver against the registered `scitaste-self-development` landscape. The
generated Chinese workspace showed eight screened system-track sources, twelve
screened evaluation-track sources, seven registered system candidates, three
registered evaluation candidates, and zero formal-ready candidates in either
track. Those overlapping source counts are historical v3 classification outputs, not paper
prevalence or experiment results. Headless Chromium at 1440, 768, 390, and 320
CSS pixels found no document-level horizontal overflow, undersized enabled
target, locale-switch request, or runtime error after the tablet track layout
was repaired. This is an engineering presentation check, not usability or
scientific-effectiveness evidence.

The existing `scitaste-self-development` project is a read-only self-hosting
acceptance case. Its repository-local manifest had reached revision 203 with 40
registered run records and a selected project-owned manuscript bundle before
this mainline closure. The exact categorical composition is derived afresh from
that manifest rather than frozen in the UI documentation. The UI must not infer
newer progress from Git or docs; main registers later milestones through the
normal `ProjectRuntime` workflow before they can appear in this view.

### Unified intent and surface-plan contracts

The self-development project can additionally register one run-owned
`iclr-evidence-program-v1` projection report. The projection identifier is a
stable receiver contract rather than the scientific-program revision: it now
accepts either the exact historical stage vocabulary or the exact lifecycle-v2
vocabulary and rejects any mixture or unknown stage. The current lifecycle
dossier is
[`iclr2027_self_development_lifecycle_v2.yaml`](../configs/evaluation/campaigns/iclr2027_self_development_lifecycle_v2.yaml).
The default project home puts its compact seven-phase evidence route before the large run synopsis: research basis,
Scientific Taste instrument, task/method readiness, independent review design,
bounded prepilots, formal evidence, and the paper/reviewer loop. The current
gate, parallel next gates, exact blocker counts, owner-decision status, external
action classes, and three non-pooled claim tracks are projected from the
validated dossier rather than inferred from Git or documentation. Raw scope and
hashes use progressive disclosure, and fixed labels remain multilingual
receiver content.

Selecting a phase or “discuss or revise plan” returns a bounded question to the
conversation composer. This is presently a model-assisted exploration path, not
a plan mutation: the generated surface remains declarative and read-only. The
planned revision slice will add a typed amendment proposal and explicit
controller handoff; until that exists, the UI must not claim that conversation
feedback changed project state.

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

The initial deterministic resolver recognizes progress, blocker, run comparison,
research-landscape, paper-evidence, and next-step goals in Chinese or English. A free comparison
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
legal `SurfaceSpec`. An external planner receives `SurfaceCandidateDescriptor`
plus a bounded digest of the already visible candidate data. The digest strips
paths, locators, credential fields, hashes, actions, and controller proposals;
caps depth, list length, string length, candidate count, and total bytes; and
declares that omitted content is unknown. This gives the model enough project
evidence to write useful content without exposing the execution plane.

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
by returning a closed `SurfacePlan` together with a cited `ModelAuthoredBrief`.
There is deliberately no execute, mutate, transition, callback, fetch, or tool
method. Deterministic intent recognition in
`WorkspaceIntentResolver` remains the first, zero-cost path. When it cannot
select exactly one intent—including ambiguous questions that mention several
known concepts—the optional classifier may choose only from the current
server-issued intent catalog. If classification is unavailable or rejected, the
receiver preserves the deterministic resolver's clarification reason rather
than guessing.

`DeterministicWorkspacePlanner` orders trusted candidates by a versioned,
intent-aware stable rule and works without a provider. A progress request leads
with the progress summary; blocker, comparison, and paper requests lead with
their matching diagnostic component, retain progress only as compact context,
and omit unrelated context such as current-run approval from a blocker
diagnosis. Candidate ID remains the deterministic tie-breaker.
`StructuredWorkspacePlanner` adapts the
existing provider-neutral `StructuredModelBackend`; it does not import a vendor
SDK or read credentials itself. Classification receives the bounded question
and a list of closed quick-intent IDs/goals/registered target IDs. Composition
receives snapshot and intent hashes, candidate descriptors, the current prompt,
the bounded visible-data digest, and at most one prior cited brief. It receives
no action proposal, artifact path/locator, credential field, content hash, or
controller state.

The model response is untrusted. Backend/model identity, request bytes,
response bytes, token telemetry, latency, tool-call absence, exact response
binding, closed Pydantic schema, snapshot hashes, intent hash, catalog hash, and
final plan materialization are all checked in code. The model returns only
bounded candidate placements and cited authored content. The optional visual
canvas is likewise data rather than renderer code: it chooses one closed layout,
two to ten typed nodes, closed node states and closed relation labels. Every node
must cite the offered component/evidence candidates that ground it, and every
edge must remain inside that admitted node set. If a model cites a trusted
candidate but omits its component placement, the receiver may complete that
placement from the exact offered catalog; it cannot admit a new identity. The
receiver injects
project, snapshot, intent, and catalog identities after admission instead of
asking the model to reproduce integrity metadata. Prompt instructions are
defense in depth, not the trust boundary. A failed or malicious composition is
replaced by the deterministic layout through `FallbackWorkspacePlanner`; a
failed long-tail classification remains explicitly unavailable because guessing
an intent would change meaning.

Accepted provenance records planner implementation and configuration hashes,
snapshot, intent, candidate catalog, structured request, provider response hash,
result plan hash, and authored-content hash. It never records credentials.
Model-assisted results set `deterministic_reproducible=false`; deterministic
fallbacks identify the attempted provider planner and bind the independently
reproducible fallback plan. The existing OpenAI-compatible backend supplies the
transport timeout and server-side environment-variable credential lookup; the
UI adapter additionally rejects provider configurations whose retry-adjusted
timeout exceeds its policy bound.

The CLI injects `BoundedPlannerHTTPTransport` into the compatible backend. It
streams decoded response bytes under the planner limit before building a
response string, checks any declared length, requires UTF-8, rejects duplicate
JSON keys and non-finite values, and requires an object root. The planner then
repeats a canonical post-read size check before schema admission.

```text
question ──> deterministic resolver ──resolved──┐
   │                                            │
   └─long-tail─> optional ID-only classifier ───┤
                                                v
project snapshot ─> trusted candidate factory ─> planner
                                                │ closed plan + cited brief/canvas
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

Successful model generation first renders a concise authored brief with finding,
uncertainty, and recommendation cards, evidence chips, follow-up/edit prompts,
and, when grounded evidence supports it, a compact flow, network, or decision
canvas. The model authors the canvas content and relations; the receiver owns the
renderer and citation checks. Clicking a canvas node, evidence chip, or suggested
question prepares editable feedback in the same project conversation. The next
brief must bind the exact prior authored turn, so requests such as “move this
blocker to secondary and foreground the causal decision” edit a concrete prior
generation rather than restart from a generic prompt. The model also changes
component order, grouping, emphasis, and the set of goal-relevant panels.
Featured goal components span the workspace;
a progress board used only for context collapses its timeline, activity, and
next-step regions while preserving its categorical synopsis and exact record
counts. The receiver shows the admitted intent goal, planner mode, snapshot
revision, read-only authority, and a short server-owned explanation for each
component; lower-level provenance remains available through disclosure.
Layout classes affect only the fixed CSS grid; the response still contains no
markup or renderer code. A failed request leaves the current workspace visible
and reports clarification candidates, missing evidence, provider
unavailability, stale state, or rejected planning in the intent panel.

Generated surfaces are retained in memory by exact project and surface ID so
browser back/forward and proposal-only actions resolve against the precise
validated surface instead of invoking the model again. Every retrieval and
action rehashes current project evidence. A server restart deliberately drops
this cache; an old generated deep link then fails stale rather than attempting
to recreate a non-deterministic result. Opening a generated surface starts the
same project-owned audit epoch used by fixed views. Generated actions and
artifact inspections still stop at their existing proposal/read-only
boundaries. The process retains at most 128 generated surfaces using
least-recently-used eviction; an evicted link likewise fails stale.

### Receiver-owned multilingual presentation

The fixed shell and all receiver-authored vocabulary are available in English
and Simplified Chinese. The packaged `en.json` and `zh-CN.json` catalogs have an
exact key contract covering navigation, accessibility labels, placeholders,
progress synthesis, fixed and generated component names, standard proposal
labels, field names, status categories, freshness, empty states, and closed
server error codes. A small side-effect-free `locale.js` module validates both
catalogs before enabling the receiver, applies deterministic English fallback,
and treats interpolation values only as text. The renderer continues to use
`createTextNode` and `textContent`; translations cannot become markup, URLs,
callbacks, or executable values.

Language is presentation state, not research state. The selector rewrites only
the fragment suffix, for example
`#/projects/my-project/project-progress?lang=zh-CN`. The server never receives a
fragment, and its prohibition on HTTP query strings remains unchanged. A
refresh or copied deep link can therefore restore the locale and route without
putting the bearer credential, project evidence, or question in local/session
storage. An unsupported or hostile `lang` value becomes English. The skip link
focuses the workspace without replacing the evidence route or losing this
locale binding.

Switching locale re-renders the already validated document in place. It does
not call an API or planner and preserves the selected project, fixed or retained
generated route, quick-intent catalog, proposal receipt, and verified artifact
preview. Browser back/forward restores the locale recorded with each history
entry before revalidating that entry's normal project route. Project switching
still performs the stronger isolation reset described above.

Project titles, current research directions, blocker reasons, milestone
decisions, paper titles, excerpts, model/provider identities, artifact source,
and other authoritative values remain byte-for-byte presentation of their
recorded language. Only receiver-owned labels surrounding those values change.
Stage records already carry authoritative `label_en` and `label_zh` fields, so
the receiver selects the matching recorded label rather than translating one.
No translated string participates in a snapshot hash, surface fingerprint,
planner input, evidence record, proposal, audit record, permission, or
controller decision.

### Self-hosting verification

On 2026-09-06 the offline receiver was exercised against a temporary copy of the
then-current revision 21 `scitaste-self-development` project, leaving the
repository's `outputs/` untouched. That historical fixture reported nine runs
and no paper. Later project registrations supersede those counts; the observation
is retained only as the first self-hosting UI check, not as current project
status.

Selecting progress review produced an admitted deterministic generation with
five native components grouped as primary, attention, and context. The response
and renderer both reported `execution_authority: none`. This verifies current
project-management usefulness and the offline generation path; it is not an
effectiveness result, a live-provider result, or evidence that unregistered
repository work is complete.

On 2026-09-07 the multilingual receiver was exercised against a temporary copy
of the then-current outputs, leaving repository `outputs/` untouched. The
`scitaste-self-development` progress view opened revision 147 in Simplified
Chinese with 28 registered runs, 19 observed-complete records, seven requiring
attention, one candidate, no paper, and 21 evidence disclosures. These are only
the facts recorded by that copied project snapshot. A blocker-diagnosis quick
intent produced a deterministic retained workspace whose blocker, progress,
project-context, placement, planner, and read-only authority labels all changed
language while project-authored English evidence remained unchanged.

Scripted Chromium checks at 1440-pixel desktop and 390-pixel mobile widths
found no runtime exceptions. An in-place Chinese/English switch issued zero
network requests, preserved the project and generated-surface IDs, and retained
both a proposal receipt and a verified Markdown preview in a separate
paper-bearing project check. Back/forward restored a Chinese fixed progress
entry and an English retained generation with their original routes. Refresh
restored the fragment locale while the loopback server re-established its
HttpOnly session; the receiver contained no credential input. The screenshots
were temporary visual-inspection artifacts and were not added to the repository.

The prior generation-planner branch verification passed 223 Generative UI and
focused CLI tests with 86.03% branch-aware coverage of
`scitaste.generative_ui`, followed by all 626 then-current repository tests.
Those counts are retained as historical verification, not the multilingual
branch's final result.

Final multilingual verification passed 232 Generative UI and focused CLI tests
with 86.12% branch-aware coverage of `scitaste.generative_ui` (above the 85%
gate), followed by all 823 current repository tests through
`PYTHONPATH=src make check`. Ruff formatting/lint, `node --check` for both
receiver modules, and `git diff --check` passed. An isolated wheel contained 152
entries, including `index.html`, `app.css`, `app.js`, `locale.js`, `en.json`,
and `zh-CN.json`; it contained no `outputs/`, tests, `third_party/`, key, or
environment files.

### Evaluation boundary and pre-experiment

The repeatable evaluation harness and paper-ready study design are documented in
[Generation as Content Evaluation](GENERATION_AS_CONTENT_EVALUATION.md). The
automated structural report measures fixed-source-view consolidation, focused
component rank, component count, evidence grounding, and local service latency.
Every output explicitly says that it is not a human-usability or
scientific-effectiveness result.

On 2026-09-08 the harness read `scitaste-self-development` revision 180 without
writing project outputs. Across its four applicable quick intents, one generated
workspace represented a mean 3.25 distinct fixed source views, a 65.83-percent
structural reduction; the goal-focused component ranked first in all four cases
and all 30 components remained grounded. Mean component count was 7.5, with both
progress and paper review reaching the 12-component cap. Twenty local samples
put deterministic generated-progress composition at 1,657.035 ms median and
1,720.975 ms p95, compared with 132.748 ms and 152.052 ms for the fixed progress
surface. The result is therefore a navigation-structure gain paired with a
latency and information-load cost, not an unqualified usability gain.

A dependency-free headless-Chromium probe now checks a real temporary project
copy at 1440, 768, 390, and 320 CSS-pixel widths. It exposed and drove two
receiver repairs: generated cards become single-column at the tablet breakpoint,
and a completed response focuses and scrolls to the beginning of the workspace.
At 768 pixels the same 12-component document fell from 134,812 to 28,134 pixels
in the baseline/repaired comparison. The final run had no document horizontal
overflow, undersized enabled target, locale-switch request, or runtime error.
These remain engineering observations until the counterbalanced human study
measures evidence-grounded task completion, time, SUS, task ease, and authority
comprehension.

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
a model-driven layout generator, approval workflow, or action executor. The
local application described below adds planning and a deterministic proposal
controller around freshly rebuilt factory surfaces. Authorization stops at a
typed handoff and never executes the proposed operation.

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
- `POST /api/v1/projects/<project-id>/decisions` accepts exactly one explicit
  `ProposalControllerRequest` and returns its deterministic decision;
- `GET /api/v2/workspace/projects` returns the authenticated project-list view;
- `GET /api/v2/workspace/projects/<project-id>/<view>` returns one current
  workspace, with typed `/runs/...` or `/papers/...` suffixes only where the
  closed query permits them;
- `POST` to the same workspace path plus `/events` records a proposal-only
  interaction;
- `POST` to that workspace path plus `/decisions` controls a previously audited
  proposal against the same current surface;
- `POST` to a workspace path containing a visible artifact plus `/inspections` accepts exactly
  `ArtifactInspectionEvent` and returns a bounded `ArtifactInspectionDocument`.
- `GET /api/v3/generative/projects/<project-id>/intents` returns the current
  evidence-derived `QuickIntentCatalog` and fingerprint;
- `GET /api/v3/generative/projects/<project-id>/warm-cache` returns the
  project-local model-cache state and only current, unexpired generation IDs;
- `POST /api/v3/generative/projects/<project-id>/workspace` accepts one
  `WorkspaceGenerationRequest` and returns a question-free
  `GeneratedWorkspaceDocument`;
- `GET /api/v3/generative/projects/<project-id>/generations/<surface-id>`
  revalidates and returns an exact project-archived generation;
- `POST` to that generated path plus `/events`, `/decisions`, or `/inspections`
  resolves only against the retained server-owned surface.
- `GET /api/v4/projects/<project-id>/workspaces` lists project-owned research
  conversations without mixing them with runs or papers;
- `POST /api/v4/projects/<project-id>/workspaces` creates one conversation and its
  first immutable turn from a `WorkspaceGenerationRequest`;
- `GET /api/v4/projects/<project-id>/workspaces/<workspace-id>` returns the
  ordered turn index, while `/turns/<turn-id>` returns one exact page;
- `PATCH /api/v4/projects/<project-id>/workspaces/<workspace-id>` renames only
  topic metadata using exact prior-title and metadata-revision preconditions;
- `POST /api/v4/projects/<project-id>/workspaces/<workspace-id>/turns` appends
  a follow-up turn without rewriting earlier turns. Its optional
  `context_turn_ids` is limited to eight IDs and must be an ordered selection
  from that exact conversation; standalone and new-conversation generation
  reject non-empty context.

There is no general filesystem, artifact download, callback, tool, model, or
executor endpoint. The controller endpoint accepts only a request/proposal
identity and explicit approval or rejection; it cannot accept commands, tool
arguments, or state patches. Query strings are rejected, so credentials cannot
be passed in a query. Explicit API bearer headers are compared in constant time.
On loopback only, `GET /session` validates the `Host` header and installs a
memory-only credential as an HttpOnly, `SameSite=Strict`, `/api/` cookie; cookie-
authenticated mutations additionally require an exact same-origin `Origin`.
The fixed shell remains public and the main interface contains no credential
field. The browser uses neither local nor session storage. Non-loopback serving
does not expose this bootstrap and continues to require explicit bearer access
or a deployment-owned authentication gateway.

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

Serve the loopback application without a manually managed browser credential:

```bash
.venv/bin/scitaste ui serve --outputs-root outputs
```

The default bind is `127.0.0.1:8765` and creates a fresh ephemeral credential at
startup. `--token-env NAME` or `--token-file PATH` supplies an explicit shared
credential for API clients. There is intentionally no plaintext token argument.
A non-loopback `--host` fails unless exposure is acknowledged and an explicit
credential exists. `--dry-run` reports only the credential source, never its
value, and does not open a socket or create the outputs root.

The offline deterministic planner is the default. Enabling the optional
OpenAI-compatible structured planner requires two independent operator inputs:

```bash
export SCITASTE_UI_TOKEN='replace-with-a-long-local-secret'
export ZAI_API_KEY='read-by-the-provider-backend-only'
.venv/bin/scitaste ui serve \
  --outputs-root outputs \
  --planner-config configs/generative_ui/zhipu_glm53_flash.priced_20260908.yaml \
  --enable-live-planner
```

The committed GLM-5.3-Flash UI config carries date-pinned pricing evidence, not a
claim that the rate remains current indefinitely. Refresh it before a formal or
materially larger campaign. A normal live configuration must use confirmed
pricing as required by `StructuredOpenAICompatibleConfig`.
`--planner-config` without `--enable-live-planner`, or the flag without a
configuration, fails validation. The YAML may name only the API-key environment
variable; embedded credentials are rejected. Dry-run output includes only the
provider, model, mode, and configuration hash, never the endpoint credential or
question. No live provider call is part of the automated test suite.
The Generation as Content profile allows up to 32,000 input tokens by default
and the current GLM configuration allows up to 8,192 output tokens for a flexible
structured planning response. These are UI-specific per-call safety/budget
envelopes, not repository-wide development limits; paper drafting and other
model-node profiles retain their independently configured ceilings. The larger
input envelope is necessary because the current project evidence digest is about
20,800 tokens before generation.

### Model-authored fixed-entry cache

Generation as Content now separates two equally visible paths. Fixed project
labels may open a pre-generated model-authored evidence layout, while a free
question or follow-up remains a fresh, context-aware model interaction. A cache
hit is labeled in the composer and promotes the exact archived generation into
the first immutable turn of a real editable conversation without invoking the
provider again. Missing, expired, stale-snapshot, or unconfigured entries keep
the normal flexible path.

The cache is project-owned at
`outputs/projects/<project-id>/.generative-ui/warm-cache/index.json`. Its policy
binds the project, provider, model, selected server-issued quick-intent IDs,
expiry, per-call ceilings, cumulative call/token/cost budgets, and a time-bounded
owner authorization. Every successful entry retains model telemetry and points
to an immutable generated-workspace archive. A provider failure is charged its
full declared per-call envelope so retrying cannot silently escape the approved
budget. Snapshot or intent-fingerprint changes invalidate presentation reuse;
they do not delete the archived record.

The paid warm pass is the narrow case where Tool Intelligence keeps an owner
boundary because it uses a secret, network access, and paid compute. It does not
add a generic preflight. Cache reads and exact generation replay are cheap local
operations and take the direct path. The committed example policy is deliberately
inactive. After copying it outside Git and adding a real owner identity and
timezone-aware authorization window, an operator may run the bounded pass alone:

```bash
.venv/bin/scitaste ui warm-cache \
  --outputs-root outputs \
  --project-id scitaste-self-development \
  --planner-config configs/generative_ui/zhipu_glm53_flash.priced_20260908.yaml \
  --policy /path/to/authorized-warm-cache.yaml \
  --enable-live-planner \
  --execute-authorized-warm-cache
```

Alternatively, `ui serve` accepts the same policy through
`--warm-cache-policy` plus `--enable-model-warm-cache`; it fills only missing
current entries before listening and consumes no call when all entries are
fresh. Neither mode grants experiment, resource-mutation, or arbitrary tool
authority.

The fixed labels are latency optimizations, not the product's semantic boundary.
They are proactively generated from the same current project evidence, expire
with that evidence, and become editable conversation turns after opening. Free
questions, node-selected follow-ups, and predecessor-bound revisions remain the
primary path for questions and interventions that do not fit a fixed label.

The receiver can explicitly approve or reject the returned proposal. Approval
rebuilds the current surface, reproduces its audited receipt, checks the current
snapshot and human-confirmation requirement, and emits only a closed handoff:
artifact inspection or run comparison is `read_only`; transition or approval is
`approved_handoff`. The decision always records
`state_mutation_authorized=false`. The receiver does not consume that handoff or
execute the proposal.

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
set `requires_approval`; the deterministic controller decides whether the
proposal receives a bounded handoff. Each approval subject is also restricted to
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

The logical `inspector` name remains in the v1 shell contract so archived
documents preserve their fingerprints. The packaged browser no longer renders
a permanent right-hand inspector: proposal decisions and artifact previews are
materialized as an inline workspace panel only after an explicit action, and no
empty hint rail occupies the project page. Likewise, the visual conversation
history is a hover-previewable, explicitly pinnable drawer; project and
evidence navigation lives in the project toolbar; and the question composer is
a compact bottom content surface. These visual placements do not change the
archived logical region names. The other receiver assets are
build-time package data rather than generated project output and reference no
remote script, stylesheet, font, or renderer.

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
`deterministic_controller`. It does not itself invoke that controller or modify
research state. Accepted event IDs cannot be replayed.

`ProposalControllerRequest` then names only the issued proposal event, a unique
request ID, approve/reject, and explicit human confirmation. The controller
revalidates the exact current `SnapshotBinding`, server-owned surface/action, and
receipt. Rejection grants nothing. Approval maps the four proposal kinds to one
closed read-only or approved-handoff boundary; the resulting
`ProposalControllerDecision` is non-executable and cannot mutate state. A
proposal and controller request may each be decided only once.

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
`surface_revised`, `proposal_issued`, `proposal_controlled`, or
`artifact_inspected` records. Each
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
receipt and controller decision against the owning project directory, and then
shows only issued receipts without a valid controller result. A corrupt,
changing, oversized, symlinked, renamed
cross-project, or otherwise foreign history is rejected instead of partially
displayed. The browser can submit approval/rejection from this evidence view,
but the result remains a non-mutating handoff rather than execution.

Each audit epoch is capped at 8 MiB and fails closed when the limit is reached.
The log records proposals, controller decisions, and read-only inspections, not
executions. Persisted receipts retain `proposal_only` authority and
`execution_authority: none`; controller records separately retain only their
closed handoff authority. No log API invokes a tool, model, executor, or state
mutation. The hash chain detects
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
- forged quick-intent or surface-candidate IDs and stale catalog fingerprints;
- duplicate component, action, metric, or evidence IDs;
- duplicate plan entries and cross-candidate focus evidence;
- action evidence that is outside the component to which the action is bound;
- proposal targets with the wrong evidence kind;
- status or paper fields without suitable content-addressed evidence;
- executable authority or undeclared fields;
- oversized/control-bearing questions, oversized provider responses, provider
  tool calls, backend/model mismatches, and resource telemetry overruns;
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

## Known limitations

- Project conversations and turns are local, single-user records. Free questions are
  retained as inert project-owned text so the conversation remains intelligible;
  users should not paste credentials into a research question. The records stay
  below ignored `outputs/projects/<project-id>/.generative-ui/workspaces/`.
- Generated documents and exact server-owned surfaces survive restart below the
  project archive. A later project revision keeps a current-schema historical
  page readable, but generated actions still fail closed against stale evidence.
  A recognized pre-lifecycle renderer page remains byte-preserved and visible in
  its topic index as `archive_incompatible`; the current receiver refuses to
  render it instead of weakening validation or breaking the entire project
  topic catalog. General schema migration remains future work.
- The first deterministic free-question resolver is a bounded Chinese/English
  keyword classifier. Unknown phrasing needs the optional model selector; the
  general workspace model can select only a currently offered quick intent and
  may synthesize only the bounded visible evidence digest. Its cited brief can be
  edited from the latest selected predecessor, but this is not unrestricted
  memory and it cannot change project state. The evidence-program revision
  endpoint is deliberately different: it writes typed planning content against
  server-issued stage, track, resource-ID, and role catalogs. Its project-local
  cache is a proposal cache, not canonical state.
- Automatic session bootstrap is loopback-only. This remains a single-user
  engineering receiver, not a multi-user identity or remote authorization
  system.
- UI audit chains detect mutation relative to the inspected chain but are not
  signatures and are not yet anchored into the project event log.
- Automated tests use fake structured backends. The GLM-5.3-Flash configuration
  and double gate are validated offline in this Epic; no new live response or
  cost claim is recorded here. An unpriced engineering probe can validate the
  provider transport, but its output is rejected from workspace admission because
  accepted model-assisted plans require measured cost telemetry under the finite
  per-response policy ceiling.
- A self-development project snapshot can lag repository work between normal
  `ProjectRuntime` updates. The UI must continue to display only its recorded
  revision rather than infer progress from Git or documentation.

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
| `WorkspaceIntent` | snapshot-bound semantic goal and evidence entities |
| `SurfaceCandidateDescriptor` | data-free receiver catalog projection |
| `SurfacePlan` | ID-only ordered/grouped declarative layout |
| `GeneratedWorkspaceDocument` | validated generated surface plus provenance |
| `ArtifactInspectionEvent` | identity-only request for a visible evidence preview |
| `ProposalControllerRequest` | explicit identity-bound approve/reject request |
| `ProposalControllerDecision` | audited non-executable handoff result |
| `SurfaceAuditRecord` | receiver-side append-only interaction history |

## Project program revision and resources

The project home now has two coordinated but distinct planes. The SciTaste
controller owns research state, evidence, budgets, execution, and immutable
campaign dossiers. Generation as Content owns how those records are presented
and how a user starts a bounded interaction. A generated page cannot become the
controller merely because it is visually primary.

Fixed high-value tabs always retain deterministic project projections and ETag
caching. An explicitly authorized project warm-cache policy may additionally
pre-generate selected fixed labels with a pinned provider/model, cumulative cost
and token ceilings, expiry, and snapshot invalidation. It fills only missing
entries before the local server listens; opening a project by itself never causes
an undeclared provider call. On-demand generations are also cached after success,
while free questions and follow-up edits remain fresh model interactions. The ICLR
program view collapses 16 exact dossier gates into seven readable phases and keeps
the three scientific tracks separate. Flexible feedback uses
`ProgramRevisionService`. The request binds the exact project revision,
snapshot SHA-256, and dossier SHA-256; a structured model can choose only the
registered change kind, incomplete stage, track, resource ID, and resource role.
Its summary, rationale, and requested evidence are model-authored text rendered
through `textContent`. The result is always `applied=false` with
`execution_authority=none`. Successful model proposals are cached under
`outputs/projects/<project-id>/.generative-ui/program-revisions/`; provider
failure is returned explicitly and is not cached or replaced with invented prose.
Failures are reduced to content-free categories (disabled backend, provider HTTP
or transport failure, invalid provider response, missing cost telemetry, or
schema rejection) rather than exposing raw provider content.

A cache hit is not a dead-end replay page. The receiver may promote the exact
fresh generation into the first immutable turn of a new project conversation.
The server revalidates the project, catalog, quick-intent, generation, document
hash, and expiry, then performs zero provider calls. Follow-up feedback uses that
turn as bounded context and asks the model to edit its cited brief. Cache hits in
an already active conversation are deliberately ignored because a fixed first-
turn page is not a valid substitute for a context-aware edit.

The latest proposal is restored after a reload. New feedback may name that exact
proposal and record hash, causing the model to edit the prior draft rather than
generate an unrelated answer. Accept and reject are explicit user actions stored
as immutable decisions. Acceptance does not silently mutate project state: a
second explicit publish action compiles the accepted proposal into a self-hashed
project run below `runs/<run-id>/planning_directive/PUBLICATION.json`. Each
publication binds its source dossier, proposal, decision, and predecessor while
declaring that the dossier and resource binding are unchanged and execution is
not authorized. The current publication is projected beside—not inside—the
scientific evidence plan, and becomes the automatic edit baseline for the next
model-authored revision. Reject closes a proposal. Stale proposals remain visible
but cannot be decided, refined, or published.

Publication is also the bridge into the SciTaste control plane. The independent
`evaluation.program_control` compiler combines the immutable dossier report with
the exact user-published directive and emits a self-hashed effective program.
Reprioritization can change only the order of the already eligible next stages;
decision clarification, risk notes, and evidence requests remain typed guidance;
resource revisions remain preferences until their separate apply action. The
project home renders the effective current stage and identifies the base order,
effective order, control effect, and compiler hash. This derived read-only action
is routed directly by Tool Intelligence because an additional preflight has
negative expected value. It grants no API, GPU, download, or execution authority.
The next model revision receives this same effective current stage and order plus
the full active directive, so iterative feedback never silently falls back to the
dossier's pre-intervention display state.

The same precedence applies to the compact progress header and model-visible
digest. Once a verified effective evidence program exists, its current stage,
state, decision, and supporting references replace the manifest's historical
`current_focus` extension. The manifest remains a fallback for projects without
a compiled program, and the browser labels which source is in use. A stale
self-iteration note therefore cannot override the plan consumed by SciTaste Core.

Every currently eligible next gate is independently compiled into a Tool
Intelligence action route without changing its user-published order. The project
home shows the route portfolio beside the primary current decision, so parallel
work can distinguish direct progress, a positive-value targeted check, a
justified full preflight, and a non-negotiable owner boundary before any check is
run. Each route is also an interaction entry point: selecting it seeds editable
feedback and binds the subsequent model request to the exact stage and route
hash. The model receives the complete parallel route portfolio, must retain the
selected route's check/authority boundary, and cannot silently redirect the
revision to another stage. Route drift is rejected before a proposal is stored.
The current gate evidence drawer exposes declared effects, expected loss,
check net gains, reason codes, and route hash. These v1 economics are policy
priors rather than empirical measurements. A semantic gray zone may admit
bounded model advice, but model output cannot weaken paid-compute, secret,
external-mutation, untrusted-code, irreversibility, or dossier-declared owner
boundaries.

The default project reading path now begins with a compact operating-loop map.
Generation as Content and SciTaste Core are parallel visual planes separated by
an explicit user-publication boundary: the former shows model synthesis,
feedback editing, and proposal status; the latter shows the current evidence
gate, Tool Intelligence route, next action, and project resource readiness. Its
controls route back into model-authored plan or resource revisions. Full ledgers,
metadata screens, and historical evaluations remain accessible in the collapsed
evidence vault so the generated workspace stays scannable rather than becoming a
long report.

The generated plane may express that loop as a model-authored, evidence-cited
canvas instead of a vertically serialized report. Its nodes can represent
milestones, decisions, resources, risks, or evidence and its edges can express
dependencies, support, blocking, use, and revision. Selecting a node begins a
predecessor-bound edit; publishing an admitted planning or resource revision is
the explicit interaction boundary into SciTaste Core. Thus the generated plane
is neither a passive dashboard nor the executor itself.

A predecessor-bound edit now supplies the model with both the bounded cited
brief and the prior safe `SurfacePlan`, not merely the previous prose. The model
can therefore retain, remove, reorder, regroup, re-emphasize, or refocus existing
components while rewriting the cited content in response to feedback. The
server derives an exact `SurfaceEditDelta` from the admitted predecessor and
successor plans; the model cannot self-report or conceal the change. The browser
renders that delta as a compact revision ribbon before the edited canvas. Fixed
entry labels may still be generated ahead of time under the project-owned warm
cache budget, but opening a cache hit promotes it into an ordinary conversation,
so the next free-form feedback uses the same flexible edit path. Cache warming
is an optional cost-bearing action rather than a prerequisite for project use.

Compute remains physically shared above projects in `outputs/resources`, but
`load_project_resource_portfolio()` gives each project a first-class, secret-free
view of its exact binding and the compatible remainder of the shared catalog. The
view reports roles, resource identities, selection lifecycle, declared and
observed status, whether required access material is present, and registry
hashes. It does not serialize a credential value, probe a remote host, or run a
workload. `current` resources may be proposed for attachment, while `historical`
and `disabled` entries remain visible but cannot enter new project work.
“Generate configuration proposal” and each catalog-row intervention route through
the program revision contract. When an accepted resource proposal is published,
its selected resource IDs become a visible project planning preference and guide
the next model revision. The shared registry remains unchanged until the user
invokes a separate “apply as project configuration” action. That action accepts
only the latest published resource directive and the exact current project
snapshot, binding record, catalog lifecycle, and registry hashes. It may attach a
current catalog entry to exactly one compatible existing role and reorder
role-local priorities; it archives the predecessor binding and writes a
self-hashed project run receipt containing the complete lineage. It cannot create
or edit a catalog definition, change an observation or credential binding, probe
a host, contact an API, launch a workload, or authorize an experiment. The
project resource card distinguishes a published planning preference from an
applied project binding and exposes the configuration run and predecessor
identity.

An attached API binding whose `required_for` list contains
`generation-as-content-planner` is also the project's authoritative planner
route. The portfolio exposes its resource, provider, model, and one of
`ready`/`unavailable`/`unmanaged`. Once managed, a live planner call is admitted
only when the binding, catalog definition, access presence, provider, and model
all match. A mismatch cannot be hidden by a process-global planner configuration:
a resolved fixed entry falls back to offline composition, while an unresolved
free question reports provider unavailability. Legacy projects without such a
binding remain compatible. In this version the server still has to be launched
with the matching backend configuration; applying a project resource revision
does not hot-load arbitrary providers or credentials.

The project data-package card can also join a no-download request with a later
project-owned archive-qualification run. Pending source hashes and future-safety
copy are replaced only when the exact proposal, task order, and asset count match.
The current self-development surface therefore shows the observed 39-archive,
178,325-member MLRC structural qualification while retaining license, layout,
baseline, held-out, ingestion, compute, and experiment gates.

Planning publication and project-local resource membership/priority changes are
cheap, versioned, reversible local writes; effective-program compilation is a
pure local derivation. Tool Intelligence routes all three directly after only
their intrinsic identity/hash/staleness/lifecycle guards instead of imposing a
generic preflight. The routes and reasons are projected in the interface. Paid
compute, provider contact, credential changes, untrusted code, and experiment
launch remain separate hard-gated actions.

Content-addressed inspection follows the same rule. Opening a current local text,
image, JSON, TeX, or PDF evidence object takes `direct_path`; its existing
no-follow open, media/size bounds, and post-read hash are intrinsic guards, not a
standalone preflight or approval ceremony. The inspection receipt records that
no standalone preflight ran. This prevents a cheap reversible read from being
blocked while keeping external or expensive effects gated.

The current Reference Quality calibration is the first complete intervention
bridge across the two planes. The project home renders a compact action packet
beside the generated program: two exact source inputs, the bound local
Qwen3-VL-2B checkpoint, one project-bound RTX 3090, token and time ceilings, the
scientific role of the output, and the claim boundary. The packet binds the
current project snapshot, effective program, Tool Intelligence route, immutable
action plan, invocation configurations, and project resource-binding record.
Authorize or reject records an immutable owner decision over that exact packet;
the browser never launches the workload. Execution additionally requires an
explicit local CLI switch and the packet, decision, and project-revision
identities. This keeps Generation as Content visually parallel to the SciTaste
controller while making an intentional user intervention consumable by the
controller.

This path deliberately has no standalone preflight. Tool Intelligence selected
an owner boundary because local GPU work is a declared external-resource action.
At execution time, the existing model-node runtime performs only the guards whose
value is intrinsic to the call: packet and revision identity, checkpoint binding,
node schema, and budget. The status and authorization paths do not load the
checkpoint, reserve a GPU, contact a provider, or create a run directory.

Resources follow a two-level ownership model. The physical API/GPU/checkpoint
catalog remains shared so the same machine or provider is not duplicated in every
project. Each project owns its resource binding, role, priority, access-presence
view, planning proposal, applied configuration receipt, and action-packet use.
The platform can therefore inspect resources and model-author a project-local
membership or priority revision through the normal conversation. Endpoint
definitions, observations, credential names, and credential values remain
administrator-level shared-registry concerns in this version; a project surface
never receives credential values.

One live self-project pass at snapshot revision 475 exercised this distinction.
GLM-5.3-Flash authored a ten-component project-progress canvas, then edited the
same conversation from `turn-0001` to `turn-0002` after the user selected the
next-gate question. The admitted successor retained six components, removed four,
changed the authored brief, and exposed both content and layout changes. The edit
used 12,110 input and 2,104 output tokens, reported USD 0.0011488407763553773,
and took 13,447 ms. This is a receiver-and-accounting dogfood observation, not
evidence of usability or scientific benefit.

The self-project now also projects its first real natural Scientific Taste
candidate population. The fixed `review-taste-candidate-population` label can be
pre-generated by the ordinary bounded warm cache, but it is not a static page:
opening it creates a normal project conversation, and free questions or later
feedback invoke the same model-authored content and canvas editor. At revision
478, GLM-5.3-Flash selected that server-issued intent from a free-form request and
generated an evidence-cited decision graph over 196 candidates, 42 source groups,
one of three target domains, 149/47 alignment agreement/disagreement, and the
four registered blockers. A predecessor-bound second turn changed quality
labeling and privacy review into parallel branches, joined them at
decision-family stratification, and moved domain expansion before benchmark
admission. Both turns retained `execution_authority=none` and
`ready_for_benchmark_admission=false`.

This pass also corrected the model projection boundary. The progress board no
longer supplies whichever sixteen fields happen to sort first. It emits a small
purpose-built view of current focus, evidence-program state, lifecycle, exact
counts, natural Taste populations, available decisions, and project resource
bindings. Scalar leaves and short scalar lists survive the depth bound, while
hashes, locators, credentials, actions, and deeply nested containers remain out
of the provider input. This gives the model enough verified state to compose a
specific plan without turning the full project ledger into prompt text.

The subsequent Core-intervention dogfood exposed a separate contract problem.
The model initially interpreted within-stage curation guidance as a request to
reorder all current gates, then omitted members of the exact four-stage order.
The receiver rejected it and the negative cache prevented an identical paid
retry. Program revision composition now gives the model explicit contracts for
decision clarification, gate reordering, resource revision, and risk notes, and
asks it only for semantic planning fields. The receiver, rather than the model,
injects the dossier hash and immutable preserve/no-remove/no-apply/no-external/
no-execution values. Content-free failure codes distinguish unexpected or
missing fields, invalid stage order, identifiers, resources, route focus, and
verification advice.

After that correction, a live call produced proposal
`program-revision-2d78b1001879330710b8` as `clarify_stage_decision` for the
current Scientific Taste source gate. It retains every blocker, records the two
new-domain requirement, makes independent quality labeling and privacy review
parallel prerequisites to decision-family stratification, and requests no
resource or execution authority. It remains pending and unapplied: only the user
may accept and publish it into the Core planning overlay.

The same project interaction produced a still-pending planning proposal for
`attest-native-condition-implementations`. The model attached a semantic
gray-zone `direct_path` advisory to the exact verification-input fingerprint in
the same paid response. Deterministic policy revalidated the advice and retained
the existing blocker; it did not execute, accept, publish, or alter Core state.
Schema-rejected provider responses now retain known token, cost, latency, and
response-hash telemetry and are negative-cached for the exact request. A pure
no-response transport failure remains retryable. This prevents repeated payment
for an identically invalid response without turning transient availability into a
permanent result.

An adapter may translate a validated `SurfaceSpec` into A2UI messages after the
project-runtime binding is available. It must preserve component registry checks,
evidence IDs, snapshot revision/hash, and `proposal_only` authority. A2UI events
must return to the deterministic approval/controller boundary; only its bounded
handoff may reach a separately validated downstream service. Events and
controller results must not be mapped directly to shell commands or tools.

### Multidomain source planning and receiver-normalized editing (2026-09-14)

The self-development project now presents both natural candidate populations
through one fixed `review-taste-candidate-population` entry. That label may be
pre-generated into the project cache, but it opens as an ordinary editable
conversation: free questions and feedback still invoke the bounded model rather
than selecting canned prose. The current F1000 projection adds 77 review
episodes from 39 Ecology/Public Health publisher-subject groups and keeps all
independent domain, quality, privacy, decision-family, and abstraction blockers
visible.

The first real GLM-5.3-Flash response correctly selected this intent but exposed
two integration defects rather than a model-capability failure. The provider
echoed one trusted display-only `component` field, and the 64,000-byte request
ceiling could not hold the already permitted project digest, output schema, and
predecessor page. The receiver now removes only an exact redundant echo, bounds
visual focus to the selected candidate's evidence, owns predecessor lineage,
and classifies an oversize request separately. The request byte ceiling is
128,000, consistent with the existing 32,000-input-token budget; output remains
independently bounded at 8,192 tokens in the deployed GLM profile.

The successful feedback edit is project-owned workspace
`workspace-7784add91c0c42ba`, `turn-0004`, editing `turn-0001`. It generated a
horizontal five-node flow covering parallel domain/privacy review, blind quality
review, decision-family stratification, Taste abstraction, and the visible
API/GPU compute plane. The receiver reports one added, two removed, and four
retained candidates, plus both content and layout change. The call used 24,895
input and 2,390 output tokens, reported USD 0.0019621261, and took 18,280 ms.

This verifies genuine model authorship, exact-predecessor feedback editing, and
the parallel/interactive Core boundary on the real project. It does not measure
human comprehension, scientific-plan correctness, or research effectiveness.
The generated page can propose and visualize project-resource choices, while
the shared registry, project binding, credential material, resource observation,
reservation, and experiment authority remain separate typed transitions.

### Flexible campaign control and risk-routed intervention (2026-09-14)

Revision 482 projects the first self-contained F1000 natural-source review
campaign into the ordinary project home and the existing
`review-taste-candidate-population` entry. The fixed entry is eligible for the
bounded warm cache, but is not a canned page: a free question created
`workspace-9d8e7a38a4c3913e`, and two successor feedback turns edited the exact
predecessor. The final canvas contains six compact nodes and four grounded
edges. It separates 154 required scientific assessments and 77 required privacy
assessments from the observed completion state of zero sessions and zero
submissions.

The three GLM-5.3-Flash turns used 39,317 input and 7,640 output tokens, reported
USD 0.003896938233732523, and took 62,424 ms in total. The first generation
mistook source identities for action routes. The first edit recovered the two
actions but narrated required workload as if it were complete and inferred
unsupported resource edges. The second edit corrected both errors. The planner
contract now states generally that required, planned, and maximum values are not
observed completion, and that co-visible entities do not establish dependency,
blocking, use, or resource relations. These turns are engineering dogfood, not
a usability or scientific-effect result.

The campaign also extends Tool Intelligence to an actual next scientific block.
Local review-package preparation is reversible and cheap: its avoidable expected
loss is 0.2 units, while both optional checks have negative net value, so it
takes `direct_path` with no standalone preflight. Contacting human reviewers is
irreversible, mutates an external relationship, and crosses a declared owner
boundary, so it takes `owner_approval`. That route requires explicit ethics,
compensation, consent, conflict-screening, and reviewer-identity decisions; it
does not insert a generic preflight before asking the owner.

The project resource portfolio remains present as a sibling component even when
the model elects not to draw resource nodes in a particular canvas. A user can
ask the model for a project-local attachment or priority revision and explicitly
apply an admitted revision. Shared definitions and secret values remain an
administrator/backend concern; model content never receives credentials and
cannot itself probe, spend, reserve, or execute. This is the intended visual and
operational relationship: Generation as Content and SciTaste Core are parallel
surfaces, joined only by reviewable user interventions.

### Owner-gated review sessions and evidence-changing feedback (2026-09-14)

The natural Taste campaign is now actionable from the same project page. Its
collapsed control asks the project owner for pseudonymous reviewer aliases, the
ethics determination reference, a reviewer-hour ceiling, and explicit
compensation, consent, retention/withdrawal, and conflict-screening
confirmations. Submission is bound to the current project revision, snapshot,
campaign bytes, and a final browser confirmation. The server hashes the aliases,
materializes two outcome-blind scientific sessions and one separate privacy
session, and records an immutable activation/control receipt before advancing
the project run. It stores no name, email address, or contact channel and sends
no message.

This is a user-to-Core intervention, not a model tool call. The generated canvas
can explain, reorganize, or propose the review plan; it cannot supply ethics or
human-recruitment authority. After a valid decision, the ordinary progress
projection changes from zero to three prepared sessions and tells the next model
turn to reason about external distribution and blind collection. API, GPU,
experiment, and model-call authority remain false. Thus feedback can change the
project evidence that later generations see, while the flexible content plane
and the authoritative Core plane remain visually parallel.

Project resources use the same separation. The sibling resource card exposes
the project-owned API/GPU/checkpoint membership, access state, priority, and
planner binding. A model may author a resource revision and the user may apply
it; the shared registry and secret material remain backend-owned, and applying a
configuration does not probe, reserve, spend, or execute a resource.

### Tool-routed post-acquisition blocker (2026-09-14)

The self-project also demonstrates why Tool Intelligence is not a generic
preflight framework. The current evidence program named
`qualify-held-out-task-bytes` as a `targeted_check`. SciTaste therefore read only
the exact acquired AWA Mini ZIP metadata needed by its frozen license policy. It
rehashes the receipt-bound archive, joins the prior archive-safety and policy
hashes, and reads `labels.csv` plus `info.json` directly from the ZIP without
extracting it. A full package inspection, model judgment, network lookup, GPU
job, and experiment would add no value to this decision and were not run.

The registered result has 2,000 unique image members and 2,000 exactly matching
label records, but the only non-image files are `labels.csv` and `info.json`;
there are zero license files, license columns, or license metadata keys. The
project data card now shows this as an observed blocker instead of the older
generic “license remains open” prose. Its user-facing decision is to obtain an
exact image-to-license manifest under separate authority or explicitly revise
the protocol to exclude AWA. Generation as Content receives these bounded facts
and can flexibly compare or edit those options, but cannot infer coverage from a
dataset-level label or launch the blocked task.

A live self-use conversation at project revision 484 verified the feedback
loop. GLM-5.3-Flash first generated a compact project decision page that surfaced
the new AWA result but selected an older Taste population. The user-style second
turn asked it to promote the F1000 campaign; it correctly refused to repeat the
prompt's 77/39/154/77 values because the old bounded projection had silently
dropped fields after the first sixteen sorted keys. The model was behaving
correctly; the evidence adapter was incomplete. The progress digest now retains
the complete purpose-built safe-field projection while still filtering hashes,
locators, credentials, deep containers, and arbitrary non-progress data.

The third turn then evidence-grounded all four counts, the zero-of-three session
state, `owner_approval`, and `record_owner_decision`; removed the irrelevant
failed-run panel; retained the AWA two-way choice and project resource entry; and
changed both the authored content and component layout relative to turn two.
Workspace `workspace-b70478939bba9a48`, turns `turn-0001` through `turn-0003`,
used 41,165 input and 7,322 output tokens, reported USD
0.0039402985074626865, and took 59,116 ms total. This is an engineering
observation of evidence recovery and feedback editing, not a usability or
scientific-effect result.

### Blind-review returns as a generated-to-Core feedback loop (2026-09-14)

The project page now completes the return half of the natural Taste review
campaign. After owner authorization has prepared the two scientific sessions
and one privacy session, a user can import each exact JSON emitted by the
offline reviewer interface. The receiver admits one file at a time, binds it to
its authorized session, and updates observed progress from 0/3 through 2/3.
When the third valid return arrives, the existing independent-review compiler
locks domain, five-dimensional quality, decision-family, privacy, eligibility,
and adjudication outcomes into `review-control/RESULT.json` and advances the
project run. It still cannot admit a benchmark directly.

This is not a new preflight. Tool Intelligence classifies collection as a cheap,
reversible project-local write whose optional advance checks have negative
value, so it selects `direct_path`. Exact session identity, complete item
coverage, role/blinding attestations, hashes, and no-overwrite publication run
inline because they define whether the submitted object is valid at all. The
HTTP receiver retains the ordinary 64 KiB limit for other events and raises only
this single-import route to a bounded 4 MiB ceiling.

The locked counts and route enter the bounded model evidence digest. The fixed
project entry then changes from candidate curation to
`plan-reviewed-taste-abstraction`, while free questions and predecessor-bound
feedback remain available. A model can therefore generate and visually
recompose the post-review plan from observed human evidence; it cannot invent
reviews, resolve adjudication, admit a corpus, or authorize downstream compute.
The resource portfolio remains a sibling project surface: project membership
and priority revisions are model-proposable and user-applicable, while shared
definitions, credentials, probes, reservations, spend, and execution remain
Core-owned transitions.

### Generated planning after independent source admission (2026-09-14)

The source-review card now carries the downstream grounded-abstraction resource
state before and after review. Before a result exists it shows a clearly labelled
campaign-ceiling forecast; after a valid 3/3 lock it atomically exposes the exact
eligible-input plan, current proposal profiles, capacity gap, same-source Raw RAG
constraint, and the direct/owner-gated routes for compilation, model generation,
and human verification. A result requiring adjudication does not compile inputs.

This is deliberately split across the two product planes. The fixed progress
component is a project-owned cached evidence seed. Clicking “generate and edit”
starts or continues a model-authored conversation that can condense, reorder,
compare, and feedback-edit the plan and its visual canvas. Only explicit user
actions may cross back into Core to record a review result, publish an admitted
planning revision, change project resource membership or priority, or authorize
a later execution. Credentials and execution authority are never model-visible.
Thus the page remains useful without a model call, but fixed labels do not become
the product's primary interaction language.

Tool Intelligence does not schedule a standalone preflight for the compiler.
Campaign/result identity, source binding, relation hiding, source-projection
parity, bounded files, and atomic publication are inline validity conditions of
the object being written. Local compilation is cheap and reversible, so further
advance inspection has negative value. Paid provider calls and human review are
materially different actions and remain at explicit owner boundaries.

The canonical ICLR evidence program was refreshed with the same evidence rather
than leaving this only as a lower-page campaign card. Its current Taste-instrument
decision now exposes two explicitly non-pooling branches: the F1000 2+1 blind
source review followed by exact-capacity grounded abstraction, and the separate
two-record local AAAR quality calibration. Consequently the top operating loop,
the fixed project summary, free model questions, and model-authored planning
amendments all start from one current project plan. The model may propose or edit
their ordering and project-resource priorities; only an accepted and explicitly
published amendment changes the Core planning overlay, and it still authorizes
neither branch.

A live GLM-5.3-Flash planning turn then exercised that path at project revision
491. From the refreshed dossier and an explicit user-style request, it produced a
`clarify_stage_decision` draft that prioritizes the F1000 owner/human decision,
keeps AAAR separate, identifies 77 as a ceiling rather than exact demand, and
retains zero execution authority. The proposal remains unaccepted and
unpublished so the UI can expose the real feedback/accept/reject/publish sequence.
It used 5,710 input and 366 output tokens, reported USD 0.0004124240457790101,
and took 5,783 ms. A read immediately after persistence reported `stale=false`.
This is an engineering interaction observation, not evidence
that the planning advice is scientifically superior.
