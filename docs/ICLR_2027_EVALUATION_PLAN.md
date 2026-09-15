# SciTaste ICLR 2027 evaluation contract

Status: **proposal for author approval; no API, GPU, remote-environment, human-study,
or formal-cell execution is authorized by this document**.

The current main execution authority is the capability-driven
[`AutoResearch program v4`](research/SCITASTE_CAPABILITY_DRIVEN_AUTORESEARCH_PROGRAM_V4.md).
It requires the complete task/idea/experiment/evidence/paper/review/revision
loop and selects research, coding, judging, retrieval, and task-training models
independently by task-excluded capability gates. Qwen3-VL-2B is only a cheap
lower-bound candidate; the local and remote inventories are candidate floors,
and task-fit downloads may extend them. The former v3 plan and the Qwen v11
prepilot remain immutable history and do not authorize a new run.

The resource-independent title strategy is
[`ICLR_2027_EXPERIMENT_STRATEGY_V1.md`](ICLR_2027_EXPERIMENT_STRATEGY_V1.md).
The underlying scientific intervention design remains the lifecycle-policy
[`evidence program v2`](../configs/evaluation/programs/iclr2027_scitaste_lifecycle_evidence_program_v2.yaml),
with a concise rationale in
[`SCITASTE_LIFECYCLE_EVIDENCE_PROGRAM_V2.md`](research/SCITASTE_LIFECYCLE_EVIDENCE_PROGRAM_V2.md).
It preserves same-source abstraction and contextual-selection controls while
adding outcome-updated versus no-update and shuffled-credit interventions. v4
wraps that design in the executable whole-research lifecycle. This
closes the design gap between static Taste retrieval and the paper's learned
lifecycle policy. The earlier evidence-program v1, Qwen v11, and DeepSeek V4.1
proposals remain immutable feasibility/history artifacts rather than the final
formal design.

The owner selected the disclosed AI-only operational route on 2026-09-15.
[`AI_REVIEW_SUBSTITUTION_PROTOCOL_V1.md`](research/AI_REVIEW_SUBSTITUTION_PROTOCOL_V1.md)
therefore replaces reviewer staffing with two independent agent roles plus a
disagreement-only agent adjudicator. This does not relabel AI evidence as human
or expert evidence: H1--H3 decision endpoints become AI-panel/natural-outcome
proxies, while H4 retains its scorer-owned objective endpoint. Human-study
requirements below describe the stronger unexecuted validation route, not a
blocker that an agent may claim to have satisfied.

The broad source pool is now governed by the no-action contract in
[`SCIENTIFIC_REFERENCE_MINING.md`](SCIENTIFIC_REFERENCE_MINING.md). It starts
from the registered decision and evidence gaps, covers six contrastive query
families, and freezes only after decision/evidence/domain/source-group coverage
plus consecutive-batch saturation. This procedure runs once upstream of both H0
arms. It cannot read content or qualify a source, so it neither bakes the
content-grounded treatment into discovery nor treats metadata relevance as
Scientific Taste.

The connector path has now closed on real self-development evidence: an
accepted 12-query GLM-5.3-Flash plan drove four bounded OpenAlex/Crossref passes
and froze 48 request/response records. A record-aware, domain-grounded selector
then replayed those same 350,848 metadata bytes with zero new model or network
calls and produced a 12-source cohort covering every registered family and
domain. The current v7 receipt binds all control, derived, request, and response
files; earlier selector failures and the integrity-only v6 supersession remain
in project history. This advances construction readiness only. The selected
source bodies, prestige-blind quality judgments, independent reviews, and
H1--H4 effects are still absent, so the experiment contract remains unauthorized.

Target venue: [ICLR 2027](https://iclr.cc/Conferences/2027/CallForPapers).
The genuine abstract is due September 18, 2026 at 23:59 AoE and the full paper
is due September 25, 2026 at 23:59 AoE. The submission must use at most nine
main-text pages, remain double blind, and include the mandatory AI-use
statement. This schedule makes evidence quality, not feature count, the
critical path.

## Paper contract

The paper asks one central question:

> Under matched information and resource budgets, does an explicit scientific
> taste policy help autonomous research systems choose more valuable and more
> evidence-grounded research actions than execution-centric control?

The intended central claim is:

> SciTaste improves the scientific value and evidence validity of autonomous
> research trajectories by representing scientific judgment as explicit,
> precedent-informed, critic-checked decisions over persistent research state.

This claim is not yet established. Engineering tests, successful fixtures,
paper generation, provenance preservation, and one controlled run establish
implementation readiness only. The title-level effect is a held-out,
within-SciTaste intervention over Taste—not an external framework ranking. The
paper must not claim external-system superiority unless a separate eligible
external estimand is complete.

The preferred result-dependent title is **“SciTaste: Improving Autonomous
Research through Scientific Taste.”** If the headline comparison is not
positive and complete, use the bounded title **“SciTaste: Grounded Scientific
Taste for Autonomous Research.”** The word *Learning* is not justified unless the
submitted method actually estimates or updates a learned taste policy; retrieval
from a precedent library alone is not sufficient.

## Recursive self-iteration contract

The default development mode is recursive, not merely retrospective
dogfooding:

1. SciTaste is the independent product and research method.
2. `scitaste-self-development` is a SciTaste-owned research project that uses
   the full lifecycle to improve the product and build this paper.
3. The self-development project creates separate held-out formal projects in
   which SciTaste Native and external systems attempt independent research tasks
   from idea through executable evidence and paper.
4. Formal failures and effects return to the self-development project as
   evidence gaps and versioned proposals; accepted fixes create a new system and
   protocol version rather than rewriting completed cells.

The self-development trajectory can establish ecological usefulness,
traceability, and defect discovery. It cannot establish comparative
effectiveness because the subject system, development process, and selected
evidence are coupled. Only source-disjoint held-out child projects contribute
to the title-level native Taste estimate; external-system outcomes occupy a
separate estimand.

The software return path from a future formal result is now explicit. A result
must first pass project-owned admission and selection. Only a complete positive
formal result may then create typed comparative-effectiveness and matched-
external-baseline evidence in the routed review ResearchState; multi-task
validity additionally requires at least two matched held-out tasks. The derived
state transition can emit exact paper-revision closure proofs, but it cannot
revise the manuscript or certify review closure. Original-reviewer verification
and two conflict-cleared independent experts remain mandatory only for a
human/expert validity claim. Under the active AI-only route, agents may close
an internal revision audit while the result stays explicitly non-human. No
current self-development result satisfies the stronger validity path.

The accepted-literature basis and the resulting evaluation-stack decision are
recorded in
[`research/AUTORESEARCH_ACCEPTED_EVALUATION_AUDIT_V1.md`](research/AUTORESEARCH_ACCEPTED_EVALUATION_AUDIT_V1.md).
The independent fourth screen and its non-saturation decision are recorded in
[`research/AUTORESEARCH_METHOD_CENSUS_FOURTH_SCREEN_V6.md`](research/AUTORESEARCH_METHOD_CENSUS_FOURTH_SCREEN_V6.md).
It recovered three additional accepted methods and eight accepted evaluation
works. The resulting bounded corpus contains 16 methods, 6 hybrids, and 23
benchmark/evaluation works; these counts describe search coverage rather than
field prevalence. A focused citation/resource screen is still required before
the declared stopping rule can be assessed, so this remains a candidate
comparison inventory rather than a frozen census.

## Four distinct evaluation tracks

| Track | Question | Required comparison | Role in the paper |
|---|---|---|---|
| A. Decision benchmark | Do content-qualified references and Taste improve local scientific decisions? | prestige-only references, quality-qualified references, raw RAG, matched/mismatched Taste, direct LM, experts | source-quality, abstraction, selection, and scalable mechanism evidence |
| B. External end-to-end systems | How does independent SciTaste Native compare with real accepted systems? | direct agent where applicable, accepted qualified systems, and SciTaste Native; preprint systems only in sensitivity analysis | ecological external validity under best-native models; external superiority only under a separately admissible matched design |
| C. SciTaste native causal intervention | Does reviewed delayed credit teach a lifecycle policy, and does that policy change executable research outcomes? | outcome-updated, no-update, shuffled-credit, diagnostic success/failure-only updates; then learned-policy on/off in the same Native executor | title-supporting lifecycle-learning and objective-progress evidence on held-out tasks |
| D. Product-supporting studies | Do Tool Intelligence and Generation as Content improve grounded use? | paired task-resolution and counterbalanced human/browser studies | secondary system evidence; never pooled into scientific effectiveness |

Benchmark papers and method papers are never rows in the same role. Track B
compares executable **systems**. Accepted resources such as InnovatorBench,
InnoGym, ScienceBoard, AutoExperiment, NewtonBench, MoSciBench, MedAgentGym,
MLGym, and MLR-Bench may provide tasks, environments, or judges only after
resource admission. A baseline shipped by one of those benchmarks is not a
method comparator unless its method contribution and unchanged implementation
pass a separate system audit.

The tracks answer different questions and must not share one aggregate score.
In particular, the current registered 48-cell study uses the same
AutoResearchClaw lifecycle for its four enabled conditions. It is an
AutoResearchClaw-substrate augmentation/ablation study, not an independent
comparison between AutoResearchClaw and SciTaste Native. Its results may support
Track C or serve as a bridge study, but cannot be the Track B headline.

### Current dual-estimand prepilot freeze

Two no-run proposals now materialize this distinction:

- `qwen3vl2b-native-taste-causal-prepilot-v11` uses schema 1.4 and expands to 12 trajectories:
  six native conditions × two MLRC objective-task candidates × one seed. It
  binds the same Qwen3-VL-2B checkpoint, GPU lane, implementation commit, and
  condition matrix to every condition; requires two confirmatory no-Taste and
  mismatched-Taste contrasts plus three mandatory component-only diagnostics;
  retains valid failed trajectories as outcomes; and forbids title or
  formal-effect claims from the prepilot.
- `external-best-native-prepilot-v7` expands to six historical no-run trajectories: SciTaste
  Native, Agent Laboratory, and TinyScientist × the same two task candidates ×
  one seed. It pins DeepSeek V4.1 Flash, o3-mini, and GPT-4o respectively and
  declares model effects confounded. Its DeepSeek identity is now superseded,
  so it is not launchable. Even a complete positive result would be
  descriptive external evidence, never a causal Taste or headline result.

Both proposals are unapproved. Native structural implementations plus the
Git-object-qualified bounded candidate-generation and fixed-candidate selection
path now exist. The production-retrieval corpus qualifier also exists, but no
formal matched/placebo corpus bytes have been acquired or qualified. Task bytes,
external adapters, remote checkpoint identity, credentials, and independent
review remain explicit blockers. Their one-seed matrices are
feasibility prepilots; formal task and seed counts require a new pilot-informed
power analysis. No data download, provider call, SSH session, GPU work, or
reviewer recruitment was performed to create them.

The missing corpus-construction path is now implemented separately from the
formal evidence. `taste-corpus-curation` binds each source and its independent
quality evidence, preserves human- or model-assisted abstraction provenance,
requires two condition-blinded human verifications with conditional third-party
adjudication, and materializes a pair only if the production retriever passes all
parity and contamination checks. This is protocol and product readiness, not a
claim that the v11 task-specific sources or reviews have been collected.

## Track A: decision-level scientific taste

SciTasteBench v2 must use held-out, source-disjoint cases derived from real
research decisions rather than only authored synthetic prompts. It must cover
at least the following decision families:

1. problem selection and significance;
2. hypothesis refinement and falsification;
3. diagnostic experiment selection;
4. evidence interpretation and confound detection;
5. pivot, continue, or stop decisions;
6. claim calibration and reviewer-concern closure.

The design floor is 120 independently scored cases spanning at least three
scientific/ML domains, with the final sample size set by a pilot-based power
analysis before the formal split is opened. Cases derived from the same source
paper, repository, or trajectory remain in one split to prevent leakage.
Every formal case receives at least two independent expert labels; disagreement
is retained and adjudicated rather than replaced by model consensus.

Primary mechanism metric: expert-aligned action selection under the fixed action
set. Secondary metrics: calibration, selective accuracy/abstention, wrong-level
decision rate, evidence localization, and budget-weighted decision utility.
Random or label-frequency policies and shuffled/mismatched Taste retrieval form
negative controls so that gains cannot be attributed merely to extra context.

The executable curation contract is now implemented. It keeps preferred actions
out of natural case records, admits only conflict-cleared human labels, preserves
primary disagreement with explicit tie adjudication, binds source/rubric/Taste
corpus hashes, and fails before compilation unless the formal population floor
passes. Declared and reversed action orders are separate repeated-measure arms.
No natural case population or expert annotation has yet been collected, so this
is protocol readiness rather than Track A evidence. See
[`research/protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md`](research/protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md).
The metadata-only acquisition screen and exact API/GPU decision brief are
[`research/data/scitastebench_v2_source_candidates_v1.yaml`](research/data/scitastebench_v2_source_candidates_v1.yaml)
and
[`research/SCITASTE_EXPERIMENT_DECISION_BRIEF_V1.md`](research/SCITASTE_EXPERIMENT_DECISION_BRIEF_V1.md).
Neither artifact authorizes a download, label, provider call, or GPU job.

## Track B: independent end-to-end comparison

### Required systems

1. **Direct/ReAct-style LM agent**: a minimal execution-capable baseline with no
   research-specific taste memory.
2. **MLR-Agent**: the official agent scaffold associated with the accepted
   MLR-Bench lifecycle, if its version, license, and environment pass.
3. **AI-Researcher**: the accepted NeurIPS 2025 end-to-end system, if explicit
   code-licensing, unchanged-core, sandbox, task, model, artifact, failure, and
   telemetry gates pass. Its current absence of an identified root license is a
   blocker, not permission to imitate the system.
4. **Agent Laboratory**: the accepted Findings of EMNLP 2025 system, if its
   MIT-licensed pinned implementation passes the same matched-task and telemetry
   gates.
5. **TinyScientist**: the accepted EMNLP 2025 system-demonstration framework,
   if its exact code/license identity and an unchanged-core matched-task adapter
   pass. Its accepted status makes it a candidate, not an automatically usable
   baseline.
6. **SciTaste Native**: the first-party controller, state, native executor, and
   publication path, with no AutoResearchClaw runtime dependency.

At least two **accepted archival** independent external research systems, in
addition to the direct agent, must pass the adapter and fairness gates before
the manuscript claims broad external-system superiority. Publication status and
execution readiness are independent: acceptance cannot waive adapter gates, and
a runnable preprint cannot satisfy this archival-evidence minimum.

The exact-commit translation audit found that the historical DeepSeek v6
proposal cannot satisfy this rule: MLR-Agent and Agent Laboratory do not
natively expose the same callable model across all research/coding roles, and
their selected-task mappings are not losslessly admitted. The provider identity
is now also historical, and updating it would not repair comparator
inequivalence. The systems
remain valid candidates, while v6 is non-launchable feasibility evidence rather
than a formal matched block. A common-backbone or explicitly confounded
best-native comparison must be frozen in a new proposal; wrapper code cannot
retroactively make the design matched.

**AI Scientist-v2** and **AutoResearchClaw** remain real pinned sensitivity
systems if their respective license, sandbox, task, model, artifact, failure,
and telemetry gates pass. They do not occupy headline external-system slots
because neither has an accepted archival publication in the current audited
corpus. Sibyl remains unavailable rather than receiving a mock implementation.

### Accepted-benchmark task stack and repetitions

The earlier 12-task natural-transfer floor was a planning heuristic rather than
an accepted-benchmark design. It is replaced by this evidence stack:

1. **MLR-Bench stagewise population**: evaluate idea and proposal decisions with
   the benchmark's research-quality rubric on all feasible official tasks or a
   powered, source-stratified, frozen subset no smaller than 120 cases. This is
   rubric evidence, not fixed objective progress.
2. **MLR-Bench end-to-end population**: begin with the benchmark's official
   ten workshop-derived research briefs for matched idea-to-paper runs. The
   primary signal is blinded expert preference over complete research packages;
   MLR-Judge is secondary. The exact system/task/seed count follows adapter
   feasibility and pilot power analysis. Four systems on ten tasks with three
   seeds would yield 120 trajectories, but this is a planning reference rather
   than authorization.
3. **EXP-Bench experiment-integrity population**: use a preregistered,
   source-stratified subset to measure hypothesis, design, implementation,
   execution, conclusion, and conjunctive full success. Its size follows a
   no-formal-data pilot and resource calculation.
4. **MLRC-Bench objective-progress population**: qualify its seven accepted
   competition tasks and use objective metrics to test proposal and
   implementation progress against human leaderboard anchors. Exact code,
   task-data licenses, assets, and source-disjoint splits must pass before use.
5. **AAAR-1.0 decision/review population**: use a frozen subset of experiment-
   design and paper-weakness tasks as secondary mechanism and reviewer-capacity
   evidence, not as an end-to-end replacement.
6. **Bounded frontier-progress cases**: optionally test two or three external
   open-ended objectives against human or strong public baselines. Treat these
   as a high-cost case series, not a population estimate.

MLR-Bench package preference and MLRC-Bench objective progress are distinct
estimands with separate schemas, protocols, analyses, and result tables. A
rubric score or model-judge score cannot be relabelled as a task's objective
value, and the two task populations are never pooled into one headline number.
The first executable-source audit is now frozen in
[`research/EXECUTABLE_BENCHMARK_QUALIFICATION_AUDIT_V1.md`](research/EXECUTABLE_BENCHMARK_QUALIFICATION_AUDIT_V1.md).
It admits MLRC-Bench for metadata review, selects its four published 16 GB tasks
against the registered 8×3090 host, and excludes the three published 48 GB
tasks. Only Temporal Action Localisation and Cross-Domain Meta Learning may
proceed to an exact acquisition-request review; no task is locally preflighted
or experiment-ready. The four-task matched Base/Full/mismatched-Taste slice is
mechanism/transfer evidence and cannot independently support a population-level
or headline superiority claim.
The current no-run package protocol is
[`research/protocols/AUTORESEARCH_PACKAGE_PREFERENCE_PREPILOT_GOVERNANCE_V4.md`](research/protocols/AUTORESEARCH_PACKAGE_PREFERENCE_PREPILOT_GOVERNANCE_V4.md).
The earlier DeepSeek v3, Zhipu v2, and Qwen robustness v2 manifests remain
immutable design history because they bound MLR-Bench briefs to an objective-
progress endpoint; none is eligible for launch or formal evidence.

The existing four synthetic generators remain controlled stress tests. They do
not satisfy external validity and must be reported separately. Every formal
task list is frozen as a content-addressed manifest before the first run. A task
is excluded before launch if systems cannot receive an equivalent starting
package or if evaluation depends on unavailable private data.

### Fairness tracks

The primary **matched-backbone track** uses the same controller model revision,
starting evidence/search snapshot, task assets, token and dollar ceilings, wall
time, experiment count, and accelerator allocation wherever each system permits
those controls. Current conformance candidates are DeepSeek
`deepseek-v4-flash` / `DeepSeek-V4-Flash` and Zhipu `glm-5.3-flash` /
`GLM-5.3-Flash`. One primary backbone is frozen before study outcomes; the other
is a separate non-pooled provider-robustness slice. Exact dated pricing and
authenticated served identity must be captured in new immutable proposal bytes.

A separate **official-configuration sensitivity track** may run each framework
with its authors' recommended model and settings. It is labelled as a sensitivity
analysis and is never pooled with matched-backbone estimates.

The local checkpoint
`/media/good/dxhismyson/weights/Qwen3-VL-2B-Instruct` is a small-model robustness
and availability condition, not a substitute for the frontier matched-backbone
comparison. The eight RTX 3090 GPUs may execute registered task workloads after
approval; provider inference and experimental GPU use remain separately
accounted resources.

### External package endpoint

The Track B endpoint is condition-blinded expert preference for the scientific
value and evidence validity of the complete research package under a matched
output budget. Reviewers receive anonymized trajectories, executable evidence,
and papers with system-identifying metadata removed. Paper fluency alone is not
the target. MLR-Judge or another model judge is secondary until calibrated
against independent experts on the actual SciTaste comparison population. A
best-native version of this endpoint is ecological and model-confounded; it is
not the title-level causal endpoint.

Secondary endpoints include:

- evidence sufficiency and unsupported-claim rate;
- valid, diagnostic, failed, timed-out, repaired, and discarded experiments;
- correct pivot/stop decisions and resources before first useful signal;
- reproducibility and reviewer-concern closure;
- wall time, provider tokens/cost, search calls, human intervention, and
  allocated versus active hardware use;
- scientific value per dollar, wall hour, and active accelerator hour, each
  reported separately rather than collapsed into one efficiency score.

## Track C: causal ablation

The first-party condition family is:

1. Native Base: the same candidate-action and executor envelope without the
   explicit utility policy, Knowledge retrieval, Taste retrieval, or Taste
   critics;
2. Native Knowledge: Base plus Knowledge retrieval only;
3. Native Taste: the utility policy plus matched Taste retrieval only;
4. Native Critics: Base plus stage-specific Taste critics only;
5. Full SciTaste: utility, Knowledge, matched Taste, and Taste critics;
6. Mismatched-Taste placebo: Full SciTaste with the Taste corpus relation changed
   from matched to source-disjoint/wrong-domain, and no other component changed.

Every condition retains the same candidate set, native executor, tools, repair
rules, task bytes, model revision, seed, and budget. Evidence-integrity,
writing-integrity, visual, resource, and sandbox gates are invariants rather than
ablatable treatment components; turning one off would change validity, not Taste.
This separates the complete decision-policy bundle from executor capability and
gives one single-factor negative control for matched Taste context.

The confirmatory interpretations are deliberately narrower than the six labels.
Full versus Base estimates the effect of the complete explicit Scientific Taste
bundle. Full versus the mismatched placebo isolates the effect of matched rather
than irrelevant Taste context, conditional on the rest of Full. The three
component-only conditions are mechanism/sufficiency diagnostics: Full-minus-one
of them changes multiple components and cannot identify an individual marginal
component effect. Any claim that Knowledge, retrieval, or critics independently
caused a gain requires a separately preregistered leave-one-out or factorial
study. The existing AutoResearchClaw/Knowledge RAG/Taste Library/Full SciTaste
matrix may be retained as a substrate transfer study, but it cannot replace this
native comparison.

For Full--mismatched to remain a single-factor contrast, matched and placebo
corpora must be paired before launch on stage/decision role, number of eligible
cases, retrieved-case count, context-token budget, provenance/curation tier, and
outcome-information availability. They differ only in source-group/domain
relation to the target. A missing or zero-result retrieval, unequal context
budget, or systematically lower-quality placebo blocks the formal cell rather
than becoming a favorable treatment result.

`native_taste_condition_matrix_v1.yaml` and the Full Workflow condition runtime
now enforce this exact structural contract offline. That acceptance path uses a
deterministic controller and a seed library, so it proves treatment isolation and
gate invariance only. It does not establish Qwen-backed executability, corpus
quality, or an outcome effect; the formal launcher must bind a model-backed Base
policy and frozen task-specific matched/placebo corpora at a later fixed commit.

Prelaunch schema 1.4 makes the reporting boundary executable. All five pairwise
analyses remain required for result completeness. Only Full--Base and
Full--mismatched-Taste carry `confirmatory`; the three component-only contrasts
carry `mechanism_diagnostic`. Thus a null or adverse component diagnostic stays
visible without incorrectly vetoing the bundle/context headline, while a null
or adverse result for either confirmatory control blocks that headline. This
contract does not weaken the evidence requirement: a missing diagnostic analysis
still makes the result incomplete.

At least one budget-scaling slice and one second-model slice are required to test
whether the result is a fixed-budget or single-model artifact. The local 2B
checkpoint is suitable for the small-model slice if its preflight passes without
changing the formal primary model.

## Statistical contract

- The title-confirmatory H3 experimental unit is an independent held-out task
  (and unique source group), not a seed, tool call, generated paragraph,
  experiment row, or reviewer rating. Seed/repetition trajectories are paired
  blocks averaged within task before inference.
- Systems are paired by task, seed, starting evidence, and budget block, while
  task-level estimates receive equal weight.
- The title-confirmatory native comparison uses the preregistered objective
  task score and independent evidence-validity review. External package
  preference uses a separate task- and reviewer-aware paired model. Each reports
  effect sizes, 95% intervals, raw outcomes, and paired sensitivity analyses.
- H3 uses the frozen objective-analysis contract: task-specific normalized
  progress, preregistered task floors for failures, a task-clustered bootstrap,
  a paired task sign-flip test, and Holm adjustment over confirmatory contrasts
  only. Continuous secondary outcomes use hierarchical or task-blocked models;
  binary failures remain outcomes and are not silently dropped.
- One headline hypothesis is tested. Secondary confirmatory families use a
  prespecified multiplicity correction; all other analyses are explicitly
  exploratory.
- The pilot selects feasibility bounds and estimates variance only. Pilot cases
  and trajectories do not enter formal estimates.
- Missing, failed, over-budget, manually repaired, and human-rescued runs remain
  visible. The protocol specifies their estimand treatment before unblinding.
- Reviewer agreement, adjudication rate, and reviewer expertise are reported.

## P0 integrity and resource gates

No formal run may start until all of these gates pass:

1. the runner verifies the actual SciTaste Git tree/commit, protocol bytes,
   launcher bytes, external-system pins, task assets, model revision, and data
   manifest rather than trusting declared metadata;
2. a formal study cannot aggregate records from different launcher hashes;
3. the result schema records provider calls/retries/token classes/price date,
   allocated and sampled-active GPU time, peak memory/utilization, CPU/RAM,
   storage, failures/repairs/discards, and human minutes;
4. `formal-v1` remains frozen to Bailian `qwen3.8-max-2026-09-02`; Zhipu
   `glm-5.3-flash` uses a separate family. Existing DeepSeek proposals remain
   immutable historical snapshots. The current `deepseek-v4-flash` /
   `DeepSeek-V4-Flash` identity needs a new proposal and a bounded
   sentinel-bracketed temporal window. Any new provider plan needs new
   IDs, blind IDs, hashes, and price records rather than mutating prior studies;
5. all external systems pass license, sandbox, data-equivalence, artifact, and
   telemetry review without a pseudo-implementation;
6. expert reviewers and the blinded adjudication process are secured before
   scale-out;
7. retention and archive locations are declared before using the remote 3090
   host, whose storage headroom is limited.
8. the self-development memory, current SciTaste manuscript, benchmark answers,
   hidden source papers, and previous formal outputs cannot enter a held-out
   external task;
9. formal tasks are separate project records, and an L0 product change after a
   block begins creates a new protocol rather than silently replacing its cells.
10. every formal manifest uses machine-checked endpoint semantics: package-
    preference tasks require independent blinded human review, while objective-
    progress tasks must expose a fixed objective score. A model judge cannot be
    the primary judge of the package-preference headline endpoint.

The current local v9 failure is an engineering recovery item. It must not be
resumed from an unverified source tree and must not be counted as formal-v2 or
ICLR evidence.

## Scale-out and stop rules

1. Freeze the proposal, task manifest, evaluation code, statistical analysis,
   models, and budgets.
2. Present the exact prelaunch manifest to the user and wait for explicit
   approval.
3. Run one complete matched block: every system on the same task and seed.
4. Stop if any adapter breaks equivalence, telemetry is incomplete, reviewers
   cannot be blinded, the task has no discriminating signal, or costs exceed the
   registered ceiling.
5. After a clean block, run a multi-task pilot that is disjoint from the formal
   set and perform the registered power calculation.
6. Obtain a second explicit scale-out approval before launching the formal
   matrix.

Before either approval, the user must receive one manifest naming:

- every exact provider/checkpoint and revision;
- every dataset/task asset, license, split, hash, and expected storage size;
- every external repository commit and environment image/lock hash;
- the complete cell count and GPU/API/human-review ceilings;
- launch order, commands, output directories, retention policy, and stop rules;
- the claims each block may and may not support.

The typed no-run manifest, provider-separated proposals, and current blockers
are implemented in [`EVALUATION_PRELAUNCH.md`](EVALUATION_PRELAUNCH.md) and
`configs/evaluation/prelaunch/`. These proposals do not authorize execution;
their hashes must change when a pending task, adapter, model, reviewer, or remote
resource becomes concrete.

## ICLR 2027 go/no-go criteria

An ICLR submission is scientifically defensible only if, by manuscript freeze:

- Track A has held-out natural cases, expert labels, negative controls, and
  uncertainty estimates;
- Track B has SciTaste Native plus at least two accepted archival, real, pinned
  external systems for any broad external-validity claim; best-native outcomes
  remain explicitly model-confounded, and preprint sensitivity systems do not
  satisfy this count;
- Track C has source-disjoint executable tasks and enforces the declared
  Knowledge/Taste/critic conditions under one fixed backbone and executor;
  Full--Base owns the bundle effect, Full--mismatched owns the matched-context
  effect, and any marginal component claim has its own valid design; this,
  rather than Track B, owns the title-level causal gate;
- the primary endpoint, task unit, power analysis, failure policy, and statistics
  were frozen before formal results were inspected;
- the main paper contains the principal quantitative tables/plots and failure
  analysis rather than delegating decisive evidence to an appendix;
- code, data manifests, raw outcome records, analysis, resource accounting, AI
  use, ethics, and limitations are reproducible and anonymous.

Passing repository tests or formatting checks is necessary software evidence but
does not satisfy these criteria. No plan can guarantee acceptance; these gates
are the minimum needed to make the submission answer the ICLR review questions
about motivation, correctness, rigor, reproducibility, novelty, significance,
and value to the community.

## Deadline-critical schedule

| Date (2026, Asia/Shanghai working date) | Required outcome |
|---|---|
| Sep 10--11 | freeze central claim, baseline candidates, P0 fixes, natural-task candidates, and author list |
| Sep 12 | complete adapter/data/license feasibility and produce the no-run prelaunch manifest |
| Sep 13 | author approval of exact models, data, budgets, and pilot matrix |
| Sep 14--15 | only after approval, run matched pilot blocks and make a formal go/no-go decision |
| Sep 16--18 | freeze a genuine title/abstract and author list; submit abstract by Sep 18 AoE |
| Sep 16--20 | only after scale-out approval, execute complete task blocks |
| Sep 20--22 | blinded review, adjudication, frozen statistical analysis, and resource audit |
| Sep 22--24 | rebuild the nine-page paper around actual results; independent claim/citation/anonymity audit |
| Sep 25 | final artifact/hash/reproducibility checks and submission by 23:59 AoE |

If the external-baseline, natural-task, expert-review, or integrity gates miss
the go/no-go point, submitting a broad superiority claim would not meet this
contract. The appropriate response is to narrow the claim substantially or defer
the submission rather than convert engineering evidence into scientific results.
