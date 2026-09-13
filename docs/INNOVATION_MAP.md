# SciTaste Innovation Map

SciTaste is one independent research system, not a collection of features around
AutoResearchClaw. Its product-level differentiation is organized around three
forms of intelligence, backed by a set of scientific and systems invariants.

## Three primary innovations

### 1. Scientific Taste — decision intelligence

Scientific Taste evaluates *what should be done next*, rather than merely scoring
the fluency of an idea or paper. It ranks explicit candidate research actions from
the current evidence, uncertainty, scientific value, precedent, and remaining
budget. The selected action, rejected alternatives, rationale, expected value,
cost, and observed outcome become an auditable decision record and can later form
a verified Taste Case.

This turns taste from an implicit model style into an inspectable research-control
policy. Current implementation covers deterministic ranking, opt-in model-backed
fixed-candidate selection, stage-aware Taste retrieval, intrinsic/augmented modes,
budget feasibility, decision replay, and four stage-sensitive critics for
wrong-level action, readiness, diagnosticity, and claim discipline. Model-backed
decisions retain request, context, candidate-set, model, response, and usage
identity rather than reducing the call to prose. A hash-bound six-condition runtime
applies one declared Knowledge/Taste/critic policy consistently from Discovery
through Evidence, Writing, and Figure generation while leaving evidence-integrity,
writing-integrity, visual, budget, and sandbox gates enabled in every condition.
High-quality references enter Taste through a separate source-abstraction path:
candidate discovery begins from the live decision and evidence gaps rather than
a single relevance or prestige ranking. Six contrastive query families seek
alternatives, null results, failure boundaries, replications, and transfer cases;
a source-group-aware coverage compiler freezes the metadata-only audit cohort
only after explicit saturation. These records remain unqualified candidates.
The complete audited population is frozen before outcomes, and rights,
scientific-source quality, and held-out/self-evidence isolation are evaluated as
three separate arguments. Each admitted source needs two independent quality
reviews while every rejection stays visible. Source content and quality evidence
are hash-bound. Before abstraction, a separately approved projector selects only
audited terminal fields and freezes one identical source representation for
same-source raw RAG and Taste abstraction; rejected sources, forbidden outcomes,
held-out identities, condition labels, and external locators cannot enter those
bytes. Abstraction candidates can then be produced by a relation-blind,
proposal-only model node whose exact source, prompt, response, model identity,
usage, and output remain in a verified project-owned ledger. Formal candidates
use grounded contrastive distillation: every decision element binds verbatim
source support, the principle must synthesize action and evidential roles, and
explicit applicability, failure, discarded-detail, and counterfactual boundaries
prevent generic advice from masquerading as transferable Taste. Candidates remain
untrusted, and two independent humans
plus conditional adjudication decide whether the result may become
retrieval-eligible. At decision time, lexical and metadata retrieval now only
construct a broad pool. A separate proposal-only deliberation node must bind at
least two reviewed applicability conditions to current decision facts, trigger
no failure condition, align to a live action, avoid duplicate sources, and retain
available action tension. The controller fails closed on state or pool drift and
records the complete selection identity. Retrieval is therefore an efficiency
mechanism downstream of Taste construction, not the definition of Taste itself.
The continual path applies the same discipline to SciTaste's own
experience: executed decisions first become quarantined reflections, then require
exact outcome evidence, two independent conflict-cleared reviews, and conditional
adjudication before the production retriever can see them. This prevents a
mistaken self-explanation from recursively becoming its own authority.
Formal evidence that it improves scientific outcomes remains a matched-system
evaluation question, not an assumption of the architecture.

### 2. Generation as Content — interaction intelligence

Generation as Content means that a generated, evidence-bound representation is
itself the interactive content. A project need not be forced into one fixed
dashboard: the trusted application shell can render different data-only surfaces,
summaries, comparisons, timelines, and next-action affordances from the same
authenticated project snapshot.

The generator may choose a suitable presentation contract, but it cannot inject
arbitrary executable UI code or invent project state. Every rendered value remains
bound to canonical project evidence, and every mutation returns through a typed,
revision-checked intent. This combines flexible generative interaction with a
stable security and audit boundary.

The current project home separates reusable cached content from open-ended
generation. Seven evidence phases, progress, and the project resource portfolio
are deterministic cached projections of current evidence. A user can then select
a phase or resource concern and ask the configured model to author a new planning
amendment. The prose is flexible, while target stages, tracks, resource IDs, and
resource roles remain server-issued choices. Generation as Content is therefore a
presentation plane parallel to SciTaste's scientific controller, and an
interaction plane only through typed, reviewable proposals and explicit user
decisions; it is not the scientific state itself. Cached proposals survive a
reload, accept/reject is immutable, and later feedback can ask the model to edit
an exact prior draft. A second explicit action publishes an accepted proposal as
a self-hashed, predecessor-linked project planning version; later model edits
automatically inherit that version. Published resource proposals project
attachment and priority preferences without mutating the shared registry. A
further explicit user action may attach only a current catalog resource to
exactly one compatible project role and compile role-local priorities into a
successor binding. Historical and disabled resources remain visible but
unselectable. Its predecessor and planning lineage are retained, while catalog
definitions, credentials, observations, probes, workloads, and experiment
authority remain unchanged. Independently, SciTaste's evaluation layer now
compiles every published directive with the immutable evidence dossier into a
self-hashed effective program. Generation as Content remains the presentation
plane, while the core consumes its typed stage order, decision guidance, risk, or
resource-preference effect without accepting executable model output.

### 3. Tool Intelligence — execution intelligence

Every effective next experiment gate now receives a shared, project-bound
cost-sensitive verification route without changing its published priority.
Declared effects and blocker state determine whether SciTaste proceeds directly,
performs only a positive-value targeted check, escalates to a full preflight, or
stops at an owner boundary. The complete parallel route portfolio is visible
before any check runs. Each route can now start a model-authored planning edit
whose request is bound to that exact stage and route hash; user feedback remains
editable, but the model cannot drift to a different gate or broaden a targeted
check into a ritual full preflight. Semantic model advice is admitted only in the
deterministic policy's gray zone. The first policy uses disclosed priors and
therefore establishes mechanism and auditability, not empirical superiority;
calibration and an intervention-cost study remain required for the paper claim.

Tool Intelligence makes rigid tools adaptive at the points where semantic
judgment is valuable. Bounded model nodes can classify ambiguity, propose a plan,
repair a structured response, or recommend one of the explicitly permitted
actions. Each node has a pinned provider/model contract, input hash, output schema,
token/cost/time ceiling, replay record, and declared authority.

The important boundary is proposal versus authority. A model node does not gain
silent permission to execute code, spend budget, alter canonical state, or contact
an undeclared system. Deterministic validation and the Taste controller retain
those responsibilities. Current implementation supports typed advisory nodes,
record/replay, project-owned receipts, opt-in live providers, content-addressed
first-party bindings, and a durable single-step read-only execution chain across
restarts; observations remain non-authoritative. Broader native code, analysis,
and writing tools are still being implemented.

Tool Intelligence also includes a cost-sensitive verification router. It compares
the expected avoidable loss of a failure with the detection value and cost of a
targeted check or full preflight. This permits cheap reversible work to proceed
without ritual prechecks, while irreversible actions, paid compute, secret access,
external mutations, and untrusted code retain deterministic gates. Model advice
is confined to an explicitly measured semantic gray zone and cannot create
authority.

## Enabling innovations

The three product ideas are made scientifically useful by the following system
designs:

- **Stateful nonlinear research control.** One canonical `ResearchState` supports
  advance, reproduce, narrow, pivot, backtrack, and stop decisions. Phase labels
  describe lifecycle position; they do not force a one-way pipeline.
- **Evidence-to-Idea.** Stable contradiction and negative results are retained as
  observations and can generate a new problem or idea instead of being discarded
  as failed attempts.
- **Evidence semantics.** Raw result, observation, interpretation, evidence
  relation, and scientific claim are separate records. A better metric cannot
  promote itself directly into a claim.
- **Knowledge/Taste dual memory.** Factual sources and decision precedents have
  separate schemas, provenance, retrieval policies, and admission gates. This
  prevents retrieved facts from masquerading as decision-quality evidence.
- **Outcome-gated continual Taste.** Project reflections remain quarantined until
  exact execution outcomes and independently reviewed causal/transfer judgments
  justify reuse. Positive outcomes alone cannot write policy into memory.
- **Evidence-native communication.** Narrative, section, paragraph, review, and
  figure contracts resolve against canonical claims and evidence. Reviewer
  concerns become research obligations; evidence-bearing concerns cannot be
  closed by prose alone. Hierarchical Writing Taste ranks positioning,
  narrative, evidence priority, scope, reader guidance, and style decisions;
  scientific integrity outranks persuasive framing and every semantic review
  remains proposal-only.
- **Project-owned auditability.** Runs, stages, decisions, native execution,
  measurements, papers, figures, and UI surfaces live under one project identity
  with content hashes, resumability checks, and tamper detection.
- **Substrate independence.** SciTaste owns the controller, state, native executor,
  and product boundary. AutoResearchClaw is an optional pinned baseline and
  compatibility adapter, not a required runtime or hidden implementation.
- **Causal evaluation discipline.** Frozen tasks, isolated conditions,
  matched-budget comparisons, negative controls, blinded review, and explicit
  unavailable competitors are used to distinguish integration success from an
  effectiveness or superiority claim.

## Current maturity

| Capability | Current state | Remaining proof or implementation |
|---|---|---|
| Scientific Taste control | Stage-specific critics, a six-condition native isolation runtime, real decision-gap-driven OpenAlex/Crossref mining with frozen replay, source-identity/relevance/family/grounded-domain admission and saturation, prestige-blind five-dimensional reference qualification, a type-separated and stratum-matched H0 quality-versus-prestige selector with exact arm-to-projection identity continuity, replayable H1/H2 source/corpus/token treatment manifests, an exact-recording-to-blind-package compiler with precommitted generation ledgers, reviewer-specific offline blind workspaces, session/submission-bound review locking, pre-key collection replay and post-key generation-chain opening, one opt-in content-bound model path that concretizes every non-trivial controller-owned candidate set, ledger-bound grounded contrastive Taste distillation, decision-grounded source-diverse and tension-preserving Taste selection, schema-1.1 dual-human source admission, a paired corpus compiler, and outcome-gated continual project memory are implemented; the search path has real self-iteration evidence | Content-authorized and quality-screened task-specific sources, provider-produced qualification/abstraction/selector traces, qualified independent humans using the implemented sessions, real frozen H0 source arms and H0/H1/H2 outcomes, real longitudinal admitted project memories, powered held-out evaluation, and formal independent matched-system effectiveness evidence |
| Generation as Content workspace | Trusted shell, evidence-bound generated surfaces, project conversations, concise model-authored/cited briefs and closed evidence-cited visual canvases over a bounded visible-data digest, exact-predecessor feedback editing, compact evidence-program home, secret-free project resource portfolio with current/historical/disabled lifecycle and model-planned catalog attachment, project-bound planner admission, model-authored snapshot- and route-bound planning amendments from every eligible gate, explicit accept/reject decisions, immutable predecessor-linked planning publication, explicit publication-to-project-resource binding compilation, a project-owned budgeted model warm cache for fixed entry labels alongside flexible questions, and one exact owner-decision-to-local-executor experiment bridge are implemented | Dynamic backend activation after project configuration, general action-packet adapters beyond the current Reference Quality calibration, administrator-level registry editing, counterbalanced human study, and a richer safe presentation repertoire guided by observed interaction failures |
| Tool Intelligence | Plans, schema-pinned repair, replay/live gating, content-addressed handlers, a durable project-owned single-step loop, a deterministic Full Workflow hotspot, per-gate cost-sensitive direct/targeted/full/owner routing across all parallel next options, and inline-guarded consumption of one paid-compute owner decision are implemented; project-local planning publication, resource membership/priority changes, and exact current local artifact reads skip generic preflight by explicit expected-value policy; one registered live study is a narrow preliminary signal | Empirically calibrated routing priors, model-advisory evaluation for semantic gray zones, independent blinded review, durable observation-to-evidence admission, broader main-workflow tasks, and external replication |
| Native Knowledge retrieval | Implemented for project-owned local libraries | Licensed open-web/search connectors and snapshot governance |
| Native experiment execution | Static code admission, isolated replicate measurement, content-bound read-only datasets, explicit NVIDIA device profiles, one content-bound local Qwen3-VL-2B CUDA environment, program-bound typed prelaunch evidence, and a real unchanged-core Agent Laboratory source/task materializer with byte-identical native-YAML translation are implemented | Dedicated external-method environments, provider-key-isolating telemetry gateway, external sandbox qualification, cross-host reproduction, quality evaluation, real schema-1.6 pilot manifests after source/adapter admission, and broader workloads |
| Evidence-to-writing binding | Measured projection, hierarchical Writing Taste retrieval/audit, bounded semantic review, audit draft, and clean publication view implemented | Open-ended high-quality scientific prose, citation generation, and independent writing-quality evidence |
| Independent superiority claim | Not claimed | Phase 9 formal cells and valid external review panel |

## Naming note

The project term is **Generation as Content**. “Generative UI” names the current
implementation family; “Content as Generation” may be understood conversationally,
but is not the canonical concept name in SciTaste.
