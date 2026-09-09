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
policy. Current implementation covers deterministic ranking, stage-aware Taste
retrieval, intrinsic/augmented modes, budget feasibility, and decision replay.
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

### 3. Tool Intelligence — execution intelligence

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
| Scientific Taste control | Implemented and offline-tested | Formal independent matched-system effectiveness evidence |
| Generation as Content workspace | Trusted-shell, evidence-bound surfaces, typed intents, structural/latency evaluator, and responsive browser probe implemented | Counterbalanced human study, bounded disclosure, and richer safe presentation repertoire |
| Tool Intelligence | Plans, schema-pinned repair, replay/live gating, content-addressed handlers, and a durable project-owned single-step loop implemented; one registered live study is a narrow preliminary signal | Independent blinded review, automatic main-workflow triggers, durable observation-to-evidence admission, broader tasks, and external replication |
| Native Knowledge retrieval | Implemented for project-owned local libraries | Licensed open-web/search connectors and snapshot governance |
| Native experiment execution | Static code admission, isolated replicate measurement, content-bound read-only datasets, explicit NVIDIA device profiles, and one content-bound local Qwen3-VL-2B CUDA environment implemented | Portable environment construction, cross-host/cold-cache reproduction, quality evaluation, and broader workloads |
| Evidence-to-writing binding | Measured projection, hierarchical Writing Taste retrieval/audit, bounded semantic review, audit draft, and clean publication view implemented | Open-ended high-quality scientific prose, citation generation, and independent writing-quality evidence |
| Independent superiority claim | Not claimed | Phase 9 formal cells and valid external review panel |

## Naming note

The project term is **Generation as Content**. “Generative UI” names the current
implementation family; “Content as Generation” may be understood conversationally,
but is not the canonical concept name in SciTaste.
