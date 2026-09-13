# ICLR 2027 core experiment strategy

Status: scientific design freeze candidate. This document selects questions and
estimands, not compute. It authorizes no dataset download, API call, GPU job,
model transfer, human recruitment, or experiment.

The executable contract is
[`iclr2027_scitaste_evidence_program_v1.yaml`](../configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml),
inspected against the additive
[`autoresearch_evaluation_resources_v9.yaml`](research/data/autoresearch_evaluation_resources_v9.yaml)
snapshot. The current deterministic report is scientifically coherent but not
acquisition-ready, experiment-ready, or execution-authorized. In particular,
the program fixes claims and roles before choosing a model: changes in local or
remote inventory update feasibility evidence, not H0--H3.

The separate
[`iclr2027_evidence_review_package_v1.yaml`](../configs/evaluation/programs/iclr2027_evidence_review_package_v1.yaml)
binds the exact next source and method proposals. It is ready for owner review,
not for experiment execution: all four selected task-source roles and all three
accepted-method candidates are covered, while every external-action flag remains
false.

## What the paper must establish

The paper is a method paper about explicit Scientific Taste, not a benchmark
paper and not a report on how much infrastructure SciTaste contains. Its central
claim has six separable parts:

1. the system can identify decision-bearing high-quality references from their
   content rather than equating venue or citation prestige with quality;
2. those references can be transformed into transferable decision experience
   rather than copied as retrieved text;
3. the system can select applicable experience from hard negatives using the
   current scientific decision, rather than an oracle relation label;
4. the resulting experience changes scientific decisions for the right reason,
   rather than because the model received more tokens or generally good prose;
5. those decisions improve held-out executable research outcomes under matched
   model, task, tool, and budget conditions;
6. the complete SciTaste system remains competitive with real autonomous-
   research systems under their usable configurations.

The first five are title-critical. The sixth establishes ecological relevance
but cannot identify a causal Taste effect when systems use different models.

## Confirmatory hypotheses

### H0: decision-bearing quality beyond prestige

Construct one common broad source pool before arm assignment. The pool is
driven by registered decision/evidence gaps and complementary direct,
alternative, negative/null, failure, replication, and transfer queries; it is
frozen by source-group-aware coverage and saturation rather than a scalar
quality rank. Given that same frozen broad source pool, select the same number
of references either by the five content-grounded quality dimensions or by a
precommitted prestige signal. The primary prestige comparator is frozen
citation count divided by years of exposure, ranked only within the exact
decision-pattern × evidence-role × domain strata induced by the quality arm.
Venue is retained as descriptive metadata and may support a separately declared
sensitivity analysis; it is not silently combined with citations into an
arbitrary score.
Keep the abstraction model, abstraction prompt, downstream model, tools, source
count, per-source token ceiling, and total context budget fixed.

Primary contrast: `quality-grounded-reference-admission` versus
`prestige-only-reference-selection`.

The five dimensions are evidential rigor, decision traceability, visible
alternatives, visible failure boundaries, and transfer potential. Each strong
rating requires exact source support; author, venue, citations, experimental
relation, and downstream task identity are hidden from the quality assessor.
This tests source selection rather than assuming that an accepted paper is a
usable scientific precedent.

The executable selector freezes the complete broad pool and its exact file and
semantic hashes before either arm is selected. The quality implementation has
no prestige fields in its input type; the prestige implementation has no
content-quality field. The quality arm first covers registered decision
patterns, evidence roles, and domains, with a precommitted hash tie-break. The
prestige arm then satisfies the quality arm's exact pattern/role/domain stratum
counts using age-normalized citations and the same source-group uniqueness
constraint. A missing observed prestige signal in any required stratum blocks
the plan. Both
arms may naturally overlap: forcing disjoint arms would change the estimand by
discarding sources that both policies genuinely choose. The overlap is reported
and can be used in a predeclared per-protocol sensitivity analysis, while the
intention-to-select contrast preserves it.

Planning, exact owner approval, deterministic selection, and replay are four
separate artifacts. They authorize neither source-body access nor treatment
materialization, model/API calls, human review, GPU work, or experiment launch.
The CLI chain is `reference-selection-plan` → `reference-selection-approve` →
`reference-selection-freeze` → `reference-selection-inspect`.

The representation identity is now concrete rather than a caller-chosen opaque
label. `source-projection-protocol` hashes the ordered field/role projection,
outcome policy, forbidden pointers and exact leakage sentinels, serialization,
external-locator rule, and byte ceilings before H0 selection. After the selector
is frozen, `source-projection-plan --reference-selection-report ...` must recover
that same hash and the exact quality/prestige source IDs. Its schema-1.1 plan and
receipt project the arm union once, preserve natural overlap in separate ledgers,
and allow a quality-rejected prestige source only when the frozen candidate and
admission report both prove exact audit, rights, and isolation eligibility. This
projection approval still opens no tokenizer, model, API, reviewer, GPU, or
experiment gate.

### H1: abstraction beyond retrieval

Given the same source papers, source-quality tier, retrieval query, and context
budget, a compact source-faithful grounded contrastive Taste abstraction improves expert-aligned
scientific action selection over raw excerpt RAG.

Primary contrast: `abstracted-matched-taste` versus `raw-source-rag`.

This contrast prevents the contribution from collapsing into “retrieve good
papers and put them in context.” Retrieval is transport; the treatment is the
source-faithful transformation into a decision context, alternatives, principle,
justification, and outcome boundary.

### H2a: contextual relevance rather than generic inspiration

With provenance tier, curation tier, case count, token budget, stage, role, and
outcome-information availability matched, task-relevant Taste experience
improves decisions over source-disjoint mismatched Taste.

Primary contrast: `abstracted-matched-taste` versus
`abstracted-mismatched-taste`.

### H2b: autonomous decision-grounded selection rather than oracle matching

Given the same frozen outcome-hidden hard-negative precedent pool, source bytes,
model, prompt, action set, context ceiling, tools, and budget, applicability- and
tension-constrained Taste deliberation improves held-out decisions over the
recorded lexical/metadata Taste retriever.

Primary contrast: `deliberative-taste-selection` versus
`lexical-taste-retrieval`.

Every deliberative assessment must cite current decision facts against exact
case transfer conditions. Selected cases must trigger no failure boundary,
remain source-disjoint, and preserve available action tension. Relation labels
and source outcomes remain hidden until selection and downstream decisions lock.
This contrast closes the oracle gap left by H2a: H2a asks whether relevance is
causal, while H2b asks whether SciTaste can discover relevance autonomously.

### H3: end-to-end research progress

Under one frozen frontier backbone and identical executable resources, Full
SciTaste improves task-normalized held-out objective progress over Native Base.

Primary contrast: `full-scitaste` versus `native-base`. Every valid failed run
remains an intention-to-run outcome at the preregistered task floor.

No title claim is admitted unless H0, H1, H2a, H2b, and H3 have complete evidence.
H0, H1, H2a, and H2b are primarily powered at the decision level; H3 is powered over
independent tasks rather than inflated by many seeds on a few tasks.

## Minimal evidence stack

### 1. Decision-level Taste study

Use source-disjoint decisions from real research trajectories across at least
three ML/scientific domains. Candidate families cover problem significance,
hypothesis falsification, diagnostic experiment choice, confound detection,
pivot/stop decisions, and claim calibration.

The formal sample size is selected by a blinded pilot and simulation-based power
analysis. The current 120-case figure is a design floor candidate, not a reason
to manufacture cases. Source groups, not prompts, are the split unit. Each case
receives two conflict-cleared expert labels with retained disagreement and
conditional adjudication.

Conditions:

1. no-reference direct model;
2. prestige-only selected Taste;
3. quality-grounded selected Taste;
4. raw-source RAG;
5. abstracted matched Taste;
6. abstracted mismatched Taste;
7. Full SciTaste with critics and persistent state.

All reference-bearing conditions use matched context budgets. Automated judges
are diagnostics; expert action preference and calibration are primary.

#### Executable H1/H2 boundary

SciTasteBench v3 names three new conditions rather than reinterpreting historical
ones: `raw_source_rag`, `matched_abstracted_taste`, and `mismatched_taste`.
`knowledge_rag`, `taste_library`, and `taste_placebo` remain legacy diagnostic
arms and cannot be cited as the confirmatory H1/H2 comparisons.

Every v3 decision binds a three-arm mechanism context. The raw and abstracted
matched arms must have exactly the same source groups, locators, content hashes,
and source count. The mismatched arm must be disjoint on all three source
identities. All arms bind the same retrieval-query and rendering-template
hashes, one tokenizer identity and artifact hash, an observed token count, one
token ceiling and truncation policy, provenance and curation tiers, and the same
outcome-information policy. Each rendered treatment also binds its construction
receipt. Held-out decision sources are forbidden from every reference arm. The
model sees the neutral label `Reference context`; treatment names remain
evaluation metadata.

Those fields are necessary but not sufficient. Before suite compilation, a
schema-1.0 reference-treatment manifest must bind the complete case population
and derive each arm's construction receipt from the exact context, ordered source
identities, support artifacts, protocol hashes, and token sequence. The compiler
replays source-projection identities, matched/mismatched Taste corpus provenance,
formal-ready curation and pair qualification, and arm-specific token traces, then
requires the manifest contexts to equal the curation package exactly. An opaque
placeholder file or supplied 64-hex receipt is not admissible evidence.

Treatment correctness must also survive generation and human review. A formal
schema-1.2 reviewer manifest publicly commits the exact formal v3 suite, typed
treatment manifest, and a private self-hashed generation ledger. Each case's
three arms share seed, candidate order, provider, and model; every arm binds its
reconstructed benchmark request fingerprint, construction receipt, execution
trace, and output bytes. The ledger remains condition-private until both reviews
for every H1/H2 comparison are locked. Only then may schema-1.1 blind opening
replay the ledger and prove that X/Y were the committed outputs. Legacy formal
schema 1.1 remains inspectable but is not admissible to the H1/H2 title gate.

The transition is executable rather than operator-authored. A dedicated offline
compiler accepts the exact timestamped recording from `benchmark run --record`,
rejects missing, duplicated, foreign, or mixed-model requests, and atomically
emits opaque reviewer outputs, the public schema-1.2 study, and private blind-key,
trace, and generation-ledger files. X/Y order is randomized and counterbalanced
across the two preassigned reviewers. The compiler performs no model call or
human contact; it only packages already completed, separately authorized runs.

Reviewer delivery and collection are executable as a separate blind boundary.
For each preassigned pseudonym, `human-review-session-prepare` rechecks the exact
suite, study, rubric, interface, assignment block, and output bytes before
building one self-contained offline workspace. It includes the shared case
context but omits conditions, provider/model identity, traces, paths, aggregate
state, and the other reviewer. After complete explicit-lock exports from both
reviewers, `human-review-lock` verifies the non-overlapping assignment partition
and content-addresses both sessions and submissions in the immutable review set.
A formal treatment-bound study rejects an older unbound review set before key
opening. These commands implement presentation and evidence capture; they do not
satisfy reviewer qualification, consent, conflict, compensation, independence,
or recruitment approval.

Opening is now a third executable boundary rather than a JSON object assembled
by an operator. Before either private file is read, `human-blind-open` reruns the
public readiness audit and uses the original collection compiler to reproduce
the complete review set from its two bound sessions and two raw submissions at
the frozen lock time. Exact equality is required. It then opens the committed
key and generation ledger and emits an analysis input only after the entire
treatment-to-output chain passes. The analyzer independently repeats collection
replay from the ledger-bound suite. This prevents a valid set of collection-file
hashes from being attached to substituted review rows while preserving the rule
that condition identity cannot enter reviewer-visible state.

Two oracle-controlled directional contrasts are preregistered: H1 compares
matched abstraction against same-source raw RAG with representation as the only
permitted difference; H2a compares matched against mismatched abstractions with
source-domain relation as the only permitted difference. The benchmark runner
reports these contrasts by ID rather than deriving them from Base deltas.

H0 is a source-selection contrast over the same broad source pool. It shares
held-out decisions and compatible downstream outputs with H1--H2b, but changes
only the source-selection rule at equal source count. H1 then holds the
quality-admitted source set fixed, preventing source quality and representation
effects from being conflated. Decision-gap mining is applied once upstream of
both H0 arms and cannot use source bodies, arm labels, or downstream outcomes;
therefore it is a common-pool construction policy rather than an extra
treatment. The deterministic H0 freeze additionally matches the quality arm's
decision-pattern × evidence-role × domain strata, uses identical downstream
protocol hashes and token ceilings, preserves natural cross-arm overlap, and
fails if the bound mining or source-admission bytes change.

H2b is a separate paired selector contrast, not another reinterpretation of the
three-arm context. Both selector conditions receive the same frozen broad pool.
The deliberative arm uses the fact-grounded applicability node and deterministic
set admission; the lexical arm uses the pre-existing broad score. Only the
selected, token-matched context enters the common downstream decision prompt.
The frozen pool includes source-disjoint hard negatives and independently
assigned applicability labels that remain unavailable to both selectors.

The v3 mechanism package requires only Base plus these three reference arms.
Full SciTaste may be added as a supporting condition, but v2 Knowledge-only,
Critics-only, and legacy-placebo cells are not mandatory. This prevents an old
software matrix from inflating the powered experiment without answering H1/H2a.

Runner accuracy measures agreement with a previously collected expert action
label. It is a useful diagnostic, but it is not the frozen confirmatory endpoint.
For H0/H1/H2a/H2b, the primary endpoint remains condition-blinded independent expert
preference over the produced decision and claim calibration. Consequently a v3
runner report leaves the confirmatory result incomplete until a separately
content-bound blind-review artifact is attached. The local alignment command is:

```bash
scitaste evaluation benchmark-alignment \
  --program configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml \
  --suite <scitastebench-v3.yaml> \
  --require-design-aligned
```

This check performs no download, model call, GPU work, human review, or
experiment, and it grants no execution authority.

### 2. Native end-to-end causal study

Use independent executable tasks with objective progress signals. The
confirmatory block contains only `native-base`, `abstracted-matched-taste`,
`abstracted-mismatched-taste`, `raw-source-rag`, and `full-scitaste`. Knowledge-
only and critics-only arms may run as mechanism diagnostics on a frozen subset;
they do not need the full confirmatory allocation.

Pair conditions within task, starting snapshot, backbone revision, tool set,
repair policy, wall time, token/cost budget, accelerator allocation, and seed.
Prefer more independent tasks over repeated stochastic runs. A pilot may use two
or three tasks and one repeat solely to estimate failure rate, variance, runtime,
and reviewer burden. Before formal execution, freeze the task count and any
replication from a power simulation without inspecting formal outcomes.

Primary endpoint: task-normalized objective progress. Secondary endpoints:
valid completion, unsupported-claim rate, evidence sufficiency, resource use,
and condition-blinded expert preference over the complete research package.

The first task-source acquisition candidate is InnovatorBench because its
long-horizon tasks expose executable objective scores. InnoGym is a contingent
alternative once an exact public implementation and task assets can be pinned.
This source order is based on endpoint fit, not on whether its models or data
already exist on either available machine.

### 3. External-system ecological comparison

Compare SciTaste Native, a direct tool-using agent, and at least two accepted
archival autonomous-research systems whose unchanged cores, licenses, task
adapters, failure policy, artifacts, and telemetry are qualified. Run each
system with its authors' usable configuration unless a genuinely common
backbone exists across all roles.

This track reports package preference, objective progress where defined,
completion/failure modes, evidence validity, and resource use. Best-native model
effects are explicit confounds. It supports “competitive with real systems,” not
“Taste caused the cross-system difference.” AutoResearchClaw and AI
Scientist-v2 may appear as sensitivity systems but do not replace the accepted-
method minimum.

MLR-Bench is the primary full-lifecycle task scaffold for this layer, while
Agent Laboratory, AI-Researcher, and DeepScientist are method candidates. A
benchmark cannot satisfy the two-method requirement, and a method that fails
license, unchanged-core, task-mapping, sandbox, telemetry, artifact, or resume
admission cannot be replaced by a mock implementation.

## Model policy, independent of current hardware

The main causal study uses exactly one frontier model identity across all native
conditions. Model selection occurs before any task outcome is observed and uses
only protocol conformance:

- exact callable and returned revision can be recorded;
- required structured output and tool calls work without hidden fallback;
- the context/output envelope covers the fixed workflow;
- retry and schema-failure rates are acceptable on non-study fixtures;
- cost and rate limits permit the powered design.

The current candidates are [DeepSeek V4.1 Flash](https://api-docs.deepseek.com/quick_start/pricing/)
and [GLM-5.3-Flash](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash).
Official documentation describes both as 1M-context, tool-capable frontier
agent models; GLM-5.3-Flash is additionally native multimodal. This makes either plausible
for a conformance pilot, but not scientifically interchangeable. One becomes the
frozen primary backbone; the other is a preregistered provider-robustness slice
on a locked subset and is never pooled with the primary estimate.

Existing local or remote checkpoints are not selection criteria. Small open
models can support reproducibility, intervention-isolation diagnostics, and
cost/scale analysis. They become title-level backbones only if the scientific
design explicitly targets small-model research autonomy and they pass the same
predeclared capability threshold. The current Qwen3-VL-2B v11 proposal therefore
remains a feasibility prepilot, not the ICLR headline experiment. Discovered
Qwen3.5-4B replicas carry no experimental role.

## What must happen before experimental spend

The following are necessary because their absence changes the meaning of the
result:

1. freeze task/source groups and licenses;
2. construct and independently review real matched, mismatched, and raw-RAG
   corpora from the same source population;
3. bind executable condition implementations and intervention-isolation checks;
4. qualify objective scorers, failure handling, blinding, and expert rubrics;
5. run a separately approved non-outcome model-conformance probe;
6. run a separately approved feasibility pilot and freeze formal power;
7. obtain exact owner approval for the resulting model, data, task count, cost,
   GPU/API allocation, and human-review burden.

The source-to-Taste compiler, element-level grounding and transfer-boundary gate,
corpus parity checks, immutable failure evidence,
and condition binding already cover items 2--4 at the software-contract level.
They still lack real source/review bytes and empirical execution.

The following are not prerequisites for the first scientific pilot: additional
generic unit-test coverage beyond the current stable level, more UI polish,
full hashing of every discovered model, a general multi-project scheduler, or a
camera-ready paper layout. Work on those areas must not delay the evidence path.

## Exact next external decisions

The owner-approved bounded acquisition is complete: all 20 pinned InnovatorBench
task-configuration YAML files and the pinned EXP-Bench metadata CSV have exact
receipts below the 8 MiB combined ceiling. Download did not authorize content
inspection. The next external decision is therefore whether SciTaste may read
those 21 acquired files under the already generated, no-extraction audit plans
to recover task fields and source-paper groups for subset design.

The post-audit implementation is now fixed before that decision. A passing
structural report can bind observed fields from the corresponding frozen scope
or preserve an explicitly declared source-field gap; it cannot invent missing
evidence. Materialization must retain the complete 20-task or 461-row population
and record that formal outcomes, installed models, and compute inventory were
not consulted. It still cannot select a subset. This prevents the future task
manifest from being reconstructed as an unexplained hand-written list after
resource or performance information is visible.

The next scientific screen is also frozen before source content is opened.
InnovatorBench's rulebook separates five eligibility questions—objective-signal
reproduction, runtime-asset feasibility under approved terms, source overlap,
rights, and sandbox safety—from one post-eligibility capacity rule. EXP-Bench's
six eligibility questions additionally require source-paper grouping and an
experiment-chain success signal, with no capacity exclusion. The compiler must
evaluate every projected record against every eligibility rule and retain
excluded and unresolved records. Current model, GPU, API, host, and expected
outcome information cannot enter these decisions. Only after a complete screen
with no unresolved records may clustered power and a precommitted seed propose
an allocation over eligible records; unsampled eligible records remain in the
ledger. The rulebooks are executable controls, but no real screen exists because
the owner has not authorized the preceding content audit or projection.

The powered allocation implementation now closes the next design gap without
pretending that a study has started. It requires a complete eligibility ledger
and an independently replayed objective-H3 clustered-power report, counts held-out
source groups rather than repeated trajectories as independent units, guarantees
coverage of every non-empty declared stratum, and precommits its seed before any
task identity is selected. Exact owner approval then freezes one immutable task
set while retaining every unsampled eligible and excluded record. This supports
an ICLR-grade selection audit, but it is not empirical evidence: the real
InnovatorBench/EXP-Bench allocation cannot exist until the owner authorizes the
preceding content audit and projection and a diagnostic pilot supplies the
source-group-level power inputs.

The frozen set is now an executable identity boundary rather than an artifact
that a later hand-written manifest may summarize. Formal objective-progress
prelaunch uses schema 1.5 and must bind the allocation report's exact file hash,
semantic task-set hash, selected task order, source groups, formal study ID, and
identical per-lane task populations. The critic independently replays the full
screen--power--plan--approval--allocation chain and rejects implementation or
population drift. Cell-plan schema 1.3 propagates both hashes into result
admission. Thus a formal H3 result cannot enter the paper from a convenient
subset that differs from the outcome-blind powered allocation.

That decision still does not include the 69.7-GB InnovatorBench archive, task
workspaces, runtime assets, repository checkout, API calls, checkpoint loading,
GPUs, or human recruitment. The ten MLR-Bench starting briefs already have an
immutable local acquisition inventory and are not requested again.
SciTasteBench remains a construction-and-review track rather than a public-file
download.

The method source bytes have advanced one bounded step beyond proposal. Under
the standing sub-10-GB policy, the exact Agent Laboratory and DeepScientist
commit archives were streamed into one atomic transaction: 83,023,421 bytes
total, with receipt SHA-256
`7a119c3bec53de52c8cd928472f64090098c89e5c3f3bfe2ad408e14d09b7009`.
They remain unextracted and unread, so unchanged-core equivalence and task,
sandbox, telemetry, artifact, model, and failure/resume mappings are still
unresolved. AI-Researcher remains a valid accepted-paper reference and
ecological comparator candidate, but its missing repository code license blocks
code acquisition/adaptation. It cannot be replaced with a mock.

The exact archive-to-tree qualification plan is now executable without opening
the member streams. It replays the acquisition chain and all outer archive byte
identities, then stops at an independent owner read decision. If approved, a
second command may hash bounded tar members without extraction while rejecting
unsafe paths/types, expansion, root, and license drift. The real archives have
not crossed that read gate, so no unchanged-core evidence has been promoted and
no method experiment is yet runnable.

Inspect the combined decision without network, API, model, GPU, or repository
access:

```bash
.venv/bin/scitaste evaluation evidence-review \
  --manifest configs/evaluation/programs/iclr2027_evidence_review_package_v1.yaml \
  --workspace-root . \
  --require-owner-review-ready
```

The current report covers 21 metadata files with an 8 MiB aggregate ceiling,
reports 14 later experiment blockers, and grants no external-action authority.

## Resource-independent launch sequence

1. finalize the source/task acquisition proposal and human-review package;
2. choose the primary API backbone using non-study conformance fixtures;
3. execute the smallest diagnostic pilot needed for power and failure estimates;
4. freeze the confirmatory decision and end-to-end allocations;
5. execute the native causal block, then the external ecological block;
6. produce the paper and run model-assisted plus two independent human reviews;
7. revise only against admitted evidence and preserve failed/null results.

Every external step is a new approval boundary. Available API keys, free GPUs,
or pre-existing checkpoints make an approved design executable; they do not
make the design scientifically valid.
