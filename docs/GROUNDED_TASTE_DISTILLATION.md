# Grounded contrastive Scientific Taste distillation

Status: implemented as a formal-method construction gate; no real source has
yet passed this gate and no effectiveness claim follows from it.

## Why a reviewed summary is not yet Scientific Taste

A high-quality paper is evidence that a research process produced something
valuable. It is not automatically evidence that every action in the paper was
the right action, and a fluent summary does not expose why one action should be
preferred to its alternatives. The original Taste abstraction schema represented
a decision, but source fidelity ended in one reviewer checkbox. It could not show
which source-visible observations supported each element, where the inferred
principle should stop transferring, or what counterfactual would change the
decision.

SciTaste therefore treats formal Taste construction as **grounded contrastive
distillation**, not retrieval and not summarization. Retrieval transports a
frozen source representation. Distillation must then produce three separable
objects:

1. a closed scientific decision: context, evidence state, alternatives, choice,
   rationale, and outcome only when outcome information is available;
2. a source trace for every decision-bearing element; and
3. a transfer boundary stating when the principle applies, when it fails, which
   probe would change the action, and which source-specific details were removed.

## Executable contract

The `grounded-taste-abstraction` node consumes the same canonical projection
bytes used by the raw-source RAG control. It is proposal-only and receives no
tools, project claims, experimental relation label, held-out task content, or
memory-admission authority.

Every proposal contains one grounding claim for each of:

- decision context;
- pre-decision evidence state;
- considered alternatives;
- selected action;
- decision principle; and
- outcome, exactly when the source projection exposes an outcome.

Each support names a projection field and copies a verbatim excerpt. Deterministic
admission reparses the exact projection and rejects a missing field or an excerpt
not present in its value. The principle is intentionally stricter: it must be a
`contrastive-synthesis` supported by at least two semantic source roles, including
one `scientific_action` field and one evidence, justification, limitation, or
outcome field. This prevents a model from declaring generic advice to be a
source-derived decision principle merely because the prose sounds plausible.

The transfer boundary requires at least two applicability conditions, two
failure conditions, one counterfactual probe, and one deliberately discarded
source detail. These fields are retained in the resulting `TasteCase` and are
shown to the controller as `applies_when`, `fails_when`, and
`counterfactual_probe`. Retrieval therefore remains only a candidate-selection
mechanism; the controller can reason about whether a retrieved precedent applies
before using its preferred action.

## Human and corpus admission

Formal corpus packages use schema `1.2` and curation tier
`grounded-dual-human-verified`. Every source must bind its exact projection, and
every abstraction must satisfy the grounded contract. The two primary reviewers
still check fidelity, action grounding, generalization, scientific value, and
outcome handling; in schema 1.2 they additionally attest that the element-level
trace and transfer boundary are supported. Candidate authors cannot review their
own output, split reviews require an independent adjudicator, and a rejected
candidate remains visible rather than being silently regenerated.

Materialization stores a grounding hash, covered targets, discarded details,
and the transfer boundary beside the normal source and review provenance. A
formal SciTasteBench v3 suite now rejects any mechanism context whose curation
tier is weaker than `grounded-dual-human-verified`. Legacy schema-1.1 abstractions
remain readable for engineering compatibility but cannot support formal H1/H2.

## Provider profiles and resource boundary

Two proposal-only profiles are available for a later approved construction run:

- `profile_zhipu_glm53_grounded_taste_abstraction_v1.yaml` for
  `zhipu-direct/glm-5.3-flash`;
- `profile_deepseek_v4flash_grounded_taste_abstraction_v1.yaml` for
  `deepseek/deepseek-v4-flash`.

The content-addressed
`runtime_profiles.grounded_taste_abstraction_v2.yaml` set exposes both as
predeclared candidates without selecting or pooling them.

Both permit up to 32,768 output tokens, rather than the earlier 2,048-token
advisory ceiling, because a grounded multi-element record is materially larger
than a short tool recommendation. They grant no tool or execution authority and
unknown cost still blocks acceptance. Selecting one primary model, calling an
API, reading acquired content, or recruiting reviewers remains a separate exact
approval.

## Scientific role

This gate makes the H1 intervention identifiable: raw RAG and grounded Taste see
the same source projection, while only the representation changes. It also
creates intrinsic diagnostics that can accompany—but never replace—the powered
outcome study: deterministic trace validity, human grounding acceptance,
transfer-boundary acceptance, compression, and failure modes by abstraction
element.

Passing the gate proves construction integrity, not that the distilled principle
is useful. H1 still requires blinded expert preference for decisions produced by
grounded Taste versus same-source raw RAG; H2 requires matched versus
source-disjoint mismatched grounded Taste; H3 requires objective progress on
held-out tasks.

## Natural-source campaign handoff

The F1000 source-review path now reaches this contract without a manual format
translation. Only a locked result with zero unresolved adjudications may produce
an abstraction plan. For every admitted episode the compiler creates one exact
`TasteAbstractionInput`: reviewed abstract, blind review comment, revised
abstract, optional author response, and article title are assigned explicit
semantic roles; observed recommendation and held-out task content are omitted.
The resulting source projection is also the only projection allowed for the H1
Raw RAG arm. Relation labels remain hidden.

The plan binds source/result/profile hashes, one model call per admitted source,
two independent primary abstraction reviews per source, and adjudication only on
a split. Local compilation follows Tool Intelligence's `direct_path`; paid model
generation and human recruitment both require owner approval. Before the human
source result exists, the UI reports a worst-case demand based on the campaign
ceiling. After lock, it replaces that forecast with the exact eligible-input
count. The current self-project therefore honestly shows a 77-source ceiling
against 20 calls in one registered profile, a worst-case gap of 57—not a claim
that 77 sources will pass review or that any calls have run.
