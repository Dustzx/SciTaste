# Decision-grounded Scientific Taste selection

Status: implemented at the proposal, deterministic-admission, and controller
boundary. No real provider call, source-content read, human judgment, or effect
measurement is reported here.

## Scientific gap

Grounding a Taste case is necessary but does not explain how an autonomous
system chooses the right case. The prior production retriever ranked eligible
cases by lexical overlap plus stage, action, domain, venue, and writing metadata.
That mechanism is useful as broad retrieval, but it can select a topical passage
whose transfer conditions do not hold, retrieve several mutually reinforcing
cases from one source, or hide a precedent that challenges the favored action.
It therefore cannot by itself distinguish Scientific Taste from curated RAG.

SciTaste now separates transport from judgment:

1. **Broad retrieval** cheaply constructs a bounded candidate pool. Its score is
   recorded but has no final-selection authority.
2. **Taste deliberation** evaluates every candidate against a closed projection
   of the current scientific decision.
3. **Deterministic admission** rejects identity drift, unsupported applicability,
   triggered failure conditions, duplicate-source selections, unknown actions,
   and avoidable one-sidedness.
4. **Action selection** receives only the admitted set and retains a ledger-bound
   trace in the final `ResearchDecision`.

This makes retrieval an efficiency device and the transfer judgment the method.

## Closed-world deliberation contract

`TasteDeliberationInput` binds one state snapshot, at least two fixed current
actions, a bounded list of current-state facts, and 2--20 broadly retrieved
cases. Only cases with a grounded-abstraction hash, at least two applicability
conditions, at least two failure conditions, and a counterfactual probe are
eligible. Each case is content-hashed and carries hashed source identities.
Source outcomes, experimental relation labels, and held-out task content are
withheld from the selector.

The proposal-only `taste-deliberation` node must assess every case exactly once.
An applicable assessment must cite at least two of the case's exact
applicability conditions, bind each judgment to current decision-fact IDs,
trigger no failure condition, and align to at least one current action. Unknown
facts, conditions, cases, or actions are rejected after the model returns.

Final selection is also constrained as a set. Two selected precedents cannot
share a source identity. If the eligible pool bears on multiple current actions,
the selection must retain that action tension. If a source-disjoint challenge or
boundary precedent is available in a multi-case set, a support-only proposal is
rejected. There is no lexical fallback after failed deliberation.

Provider profiles for GLM-5.3-Flash and DeepSeek-V4.1-Flash permit structured
32,768-token responses without tools. They are candidates, not a selected model
or launch authorization.

## Runtime boundary

`TasteController.prepare_taste_deliberation` freezes the exact broad pool and
node input. A verified accepted live ledger entry compiles into
`VerifiedTasteDeliberation`. Reusing it after state, action, candidate, source,
score, or case-content drift fails closed. The final decision records provider,
model, invocation, ledger hash, input hash, proposal hash, broad case IDs, and
selected case IDs. Candidate concretization must happen first; the controller
refuses a deliberation trace combined with an unresolved candidate-generation
backend.

This boundary does not claim that a model's semantic assessment is correct. It
makes the assessment falsifiable and prevents it from silently broadening the
evidence or execution boundary.

## ICLR evidence obligation

The original H2 matched-versus-mismatched contrast establishes whether relevant
Taste can causally help when relevance is controlled. It does not establish
that SciTaste can find relevant Taste without an oracle. The evidence program
therefore adds H2b:

- same outcome-hidden, source-group-disjoint hard-negative pool;
- same source bytes, model, prompt, context ceiling, tools, and action set;
- decision-grounded deliberative selection versus the recorded lexical/metadata
  retriever;
- primary endpoint: paired condition-blinded expert preference over the produced
  scientific action and claim calibration;
- diagnostic endpoints: applicable-case recall, duplicate-source rate, failure-
  boundary violation rate, action-tension coverage, latency, tokens, and cost.

The pool is the experimental unit's frozen input, not a source of extra tokens:
only the selected contexts enter the downstream decision prompt under equal
rendering and token ceilings. Pool labels remain hidden until selection and
downstream outputs are locked. Pilot data determine burden and variance but
cannot enter the formal confirmatory estimate.

## Remaining evidence

The software boundary is complete, but the scientific claim is open. It still
requires admitted real source cases, independently labeled applicability on
held-out decisions, a task-excluded provider conformance pilot, frozen
hard-negative pools, blinded downstream decisions, expert outcomes, and powered
source-group analysis. Until those exist, SciTaste has a testable method rather
than evidence that the method improves research.
