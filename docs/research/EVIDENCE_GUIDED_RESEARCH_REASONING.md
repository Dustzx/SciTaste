# Evidence-guided scientific reasoning

## Objective and scope

Scientific Taste should help notice consequential gaps, generate competing explanations,
choose discriminating experiments and evolve questions from actual evidence. It is
not just a retrieval-based action ranking step. Optimize useful, credible scientific
progress under a budget, not a purported known shortest path to a positive score.
Negative findings, calibrated uncertainty and justified stopping remain valid outcomes.

The implemented reasoning frame records a question, explanatory gap, importance,
2–6 mechanisms and their falsification/transfer boundaries, and 1–4 candidate probes.
Each probe includes differing observable predictions, controls/confounders, separate
cost/feasibility reasoning, decision relevance, and diagnostic/inconclusive branches.
Lookahead is bounded to 1–3 steps. These bounds limit active context, not the entire
research trajectory or a universal scientific taxonomy.

## Runtime integration

- `project.research_planning` requests the frame through the existing
  `project-research-design-v9` node during scientific planning. Explicit
  completeness-first work does not acquire an extra mechanism-study gate.
  Session output admission is a 32 KB conservative byte bound, distinct from the
  API path's 8192-token ceiling; neither is a claim of measured session tokens.
- `executor.workspace_task` and `executor.project_task` carry it with the bound study.
- `executor.native_workspace` seeds the current state from the immutable design;
  planning source aliases are namespaced and bound to the design hash. A predecessor
  or resumed state retains its evolved frame instead of being reset to the plan.
- `ResearchToolProposalBatch.scientific_reasoning` updates the frame in the existing
  model call; routine reads, edits and reporting may omit it. No additional model
  node, per-tool review or full-suite validation is required.
- `scientific_probe_id` binds a proposed/selected tool action to a declared probe.
  The controller sees the current frame; the Taste deliberation sees bounded,
  explicitly provisional scientific context. Neither is forced to select the
  model's preferred probe. Only the selected tool executes.
- Frames and the selected probe persist in the existing decision snapshots and
  `TRAJECTORY.jsonl`; canonical-state handoff exposes them to subsequent planning.
  No new sprawling collection of per-question Markdown documents is created.

### Source experience before proposal, applicability after proposal

New Native assignments can explicitly freeze `reviewed-conditional-v1` as their
proposal-context treatment. A frozen, retrieval-eligible and grounded library supplies
bounded conditional lessons, applicability/failure boundaries and reversal probes to
the existing proposal call. The projection excludes source outcomes and evidence-state
labels; it neither certifies transfer nor recommends an executable action. A proposed
lesson remains a hypothesis until current observations establish its assumptions.
The normal post-proposal applicability/abstention gate still applies.

Use both the provisioner and Native CLI's `--taste-proposal-context` and
`--taste-decision-context` flags. The campaign freezes these versions before launch;
late switches and changed continuation policies fail closed. Defaults remain
`disabled` / `legacy-full` for existing assignments. Pre-proposal exposure and
post-proposal selection are distinct treatments and need matched equal-source controls;
the new entry point alone is not evidence that Taste improves scientific outcomes.
Gate abstention preserves the current proposal, not a counterfactual trajectory with
no prior source exposure. Its rate cannot by itself measure hypothesis-generation effects.

October 7 development: `taste.inquiry_transfer` defines an opt-in
`reviewed-inquiry-v1` protocol separating inquiry transfer from recipe eligibility.
Every exact source applicability/failure premise receives an explicit observed,
contradicted or unknown judgment. Non-unknown judgments need exact current-evidence
quotes; failed tools cannot establish a premise. A source-bound inquiry must name
the active question and an existing discriminating probe, addressing a blocking
premise when one remains. Unknown premises can motivate inquiry, but cannot
establish eligibility to copy a source method. Neither eligibility nor a valid
packet authorizes execution or substitutes for the action-applicability gate.
The projection preserves whole source conditions and visibly omits complete cases
when needed to meet the shared byte ceiling. This protocol is implemented and
locally checked and wired into the Native proposal admission and campaign builder.
The opt-in mode retrieves using the evolving question and explanatory gap instead
of the initial topic alone. It shares the existing proposal call, retains source-bound
inquiry packets and rejects unsupported quotes before action selection. Generic tool
loops require an explicit inquiry validator; they cannot silently accept these packets.
Its first prospectively frozen live assignment is the October 7 source-bound
review-directed retained-prediction followup. The earlier three-system MLR-Bench
campaign retains its original `reviewed-conditional-v1` policy and terminal outcomes.
Live use and validated packets are not themselves an effectiveness gain.
The first live followup is terminal: paired/tie-policy computation, evidence-bound
hypothesis updates, report, independent review, revision and PDF completed within
the original 3600-second/36-reply ceiling (1643.23 seconds, 26 replies). Six actual
consultations abstained, no inquiry packet was proposed and two maintenance gaps
remain pending. The independent reviewer substantially accepts the numerical
response but still rejects contribution/significance. This is evidence-responsive
execution, not efficacy of inquiry transfer or scientific venue readiness.

In the new opt-in mode, Tool Intelligence also consumes existing verified transfer
judgments to maintain one bounded, deduplicated source-gap queue. It distinguishes an
empty qualified retrieval pool, inapplicable precedents and unresolved premises;
transport/schema failure is not a coverage diagnosis. The next existing proposal
call sees the current gap and compares a permitted source-search/re-abstraction action
against scientific probes and remaining cost. A pending handoff is not a running
search or an admitted experience. Source qualification, grounded abstraction,
independent review and a successor freeze remain necessary; no automatic library
mutation or forced adoption occurs. `project.source_maintenance` supervises a
previously prepared source through qualification, abstraction and independent review
to a separately frozen successor; suppliers must answer the actual model requests.
Current queue visibility is run-local, and fully unattended discovery and successor
activation are not implemented. A retained-source replay produces the exact four-case
library without new inference; it is not a fresh scientific experiment.

`bounded-research-source-v1` projects long implementation bodies with exact full-action
hashes and explicitly partial excerpts. Task instructions stay lossless, including late
restrictions. Long other facts carry complete preimage hashes and omission notices;
missing assumptions require abstention. Original executable actions remain unchanged
in the controller binding and trajectory. This is scientific-intent context, not a
verification of omitted code. New launches retain contract-bound source bytes before
the first action; historical terminal captures are separately labeled, not full replay.

Workspace history now keeps the latest explicit source read (bounded when very large),
instead of hiding it because a previous write existed while all write bodies were also
hidden. Only an earlier visible byte-identical write can deduplicate a read. Execution
measurements and errors remain intact. One no-model replay of the already closed
microscopy decision reduced node-input text from 104,372 to 40,243 UTF-8 bytes,
preserving action identities and late task constraints. This is projection sizing,
not actual model admission, measured token savings, a new experiment or Taste efficacy.
Receipt: `evaluations/research-context-projection-20261002-v1/RESULT.json`.

## Evidence and revision semantics

Completed paper feedback now exposes scientific work items, including computation
on retained evidence when an `ADD_ANALYSIS` concern carries no new-training flag.
`project.review_research` prepares a separate source-bound Native continuation with
explicit own-run public assets, a distinct allocation and no replacement of the
original comparison. Paragraph edits cannot close uncomputed scientific concerns;
new measurement and independent followup review remain separate evidence.

Runtime anchors bind exact observation/error quotes to committed result IDs and
result hashes. Unknown quotes and reused source identities are rejected. Failed or
pending execution cannot by itself strengthen, weaken or retire a scientific
hypothesis; its implication is unresolved. This restriction survives history
compaction and canonical-state handoff.

The frame may change the question after an unexpected positive, null result or
boundary observation—not only after a contradiction. A changed mechanism gets a
new hypothesis ID; dropping an old one requires an explicit evidence-bound retirement.
An active frame is capped at 24 KB and 12 source anchors. Explicit archival names
omitted old source IDs and explains the revision; complete prior frames remain in
the trajectory. Archival is not evidence deletion or permission to suppress negatives.

All dispositions remain **model-proposed reasoning**. A quoted observation proves
provenance, not its causal interpretation, reliable replication or semantic truth.
These updates do not mutate formal claim support, invent posterior probabilities,
admit Taste lessons, authorize new resources or certify scientific quality. Existing
claim assessment and external evaluation remain distinct. Legacy fixed information-
gain/heuristic confidence components are not rebranded as calibrated inference.

## Validation and remaining scientific work

Focused tests cover source binding, failure attribution across handoff, identity and
evidence preservation, design seeding, and controller-visible reasoning followed by
actual selected file-tool execution. These are engineering checks, not a Taste result.

The separate `evaluations/evidence-reasoning-integration-20260930/` package exercises
the real design node with a session response on retained AutoResearchClaw Wine raw
results and its native decision. It does not rerun experiments, change the external
trajectory or establish a comparative advantage. Its `RESULT.json` determines
admission; request generation alone is not completion.

Observed integration result: 19 focused tests passed (2.53 s, no full suite/coverage).
The first real session response was rejected because its 26989-byte output exceeded
the development invocation's conservative 24000-byte limit. It remains immutable.
One compact retry in `evaluations/evidence-reasoning-integration-20260930-compact/`
was accepted by the real design node, with source quotes and competing predictions
retained. It proposes distinguishing effective metric-space noise dose from residual
directional neighborhood geometry, with conditional branches and no execution
selection. This is a grounded development replan, not evidence that the proposed
mechanism is correct, the next experiment succeeded or SciTaste beats the baseline.

Actual Native molecular and microscopy development tasks now retain this reasoning,
experiments, reports and independent assessments alongside pinned external trajectories;
the microscopy Native paper/review/revision recoveries completed inside their original
ceilings. Their scientific novelty and matched Taste efficacy remain insufficient.
Next delivery must add decision-relevant source coverage and untouched task assignments,
not another repetition of the completed pipeline. Compare task outcomes, supported
conclusions and resource cost under matched conditions before attributing benefit to Taste. Process
analysis asks whether a consequential alternative was distinguished and whether the
observed result changed the subsequent decision appropriately—not whether the model
wrote a persuasive rationale or changed its mind frequently.
