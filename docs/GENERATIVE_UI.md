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
component candidates. An explicit deterministic controller can approve a
bounded handoff, but the interface includes no task executor and the provider
never authors renderer content or authority.

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

The fixed receiver provides a project switcher, the eight project-scoped view
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

Project selection, conversation history, fixed views, and advanced evidence
selectors live in a receiver-owned drawer. It is open by default on a desktop,
closed by default as an overlay on a narrow screen, and can always be toggled
from the header without persistence or a model call. Questions are not placed
in that navigation tree: the quick prompts, bounded-context selector, free
question, and submit control form one horizontal composer beneath the main
workspace. The workspace and composer share a viewport-height content column,
so evidence scrolls inside the workspace while the current interaction remains
available below it.

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

Each follow-up explicitly chooses either the current question alone or at most
the eight latest immutable turns. The receiver submits only their IDs; the
server reloads them from the same project and conversation, verifies their
registered order, and exposes only the retained prior questions to the optional
model intent classifier. The selected IDs and a hash of the exact context are
bound into the generated document and immutable turn. Prior generated prose,
components, actions, and explanations are never replayed as authority. The
deterministic resolver still evaluates the current question first, so this is a
bounded conversational intent aid rather than an unconstrained chat agent.

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

A manual receiver check against that revision at a 1720-pixel desktop viewport
confirmed that the summary rendered without browser errors, reduced the initial
document height from roughly 6606 to 2045 pixels, kept 19 evidence disclosures
available, and let an `Explore next` choice reach the retained generated-view
route. These dimensions are a visual-regression observation, not a product
metric or progress claim.

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
gate, a registered acquisition decision, or a registered evaluation landscape
only when their required project records exist. They contain no command or
execution authority.

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
the set of goal-relevant panels. Featured goal components span the workspace;
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
empty hint rail occupies the project page. Likewise, the visual project
navigation is a toggleable drawer and the question composer is a bottom content
surface; these visual placements do not change the archived logical region
names. The other receiver assets are
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
  model can still choose only a currently offered quick intent and cannot answer
  an arbitrary research question. Conversation context currently informs this
  bounded intent selection only; it is not a general memory, summarizer, or
  model-authored answer history.
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

An adapter may translate a validated `SurfaceSpec` into A2UI messages after the
project-runtime binding is available. It must preserve component registry checks,
evidence IDs, snapshot revision/hash, and `proposal_only` authority. A2UI events
must return to the deterministic approval/controller boundary; only its bounded
handoff may reach a separately validated downstream service. Events and
controller results must not be mapped directly to shell commands or tools.
