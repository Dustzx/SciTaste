# SciTasteBench: complete research and evidence-responsive judgment

Status: design and implementation specification, 2026-09-30. This supersedes the
paper's previous decision-only benchmark positioning, not frozen experiments or
their results. A protocol is not a released dataset or demonstrated novelty.

## Scientific question and contribution boundary

Can a research system turn a problem into a reproducible scientific result, and
revise its explanation appropriately when new evidence challenges it? Does
Scientific Taste improve this ability relative to real autonomous research systems?

The primary unit is **one complete research task**, not a model response, decision
menu, experiment seed, paper section, or repeated evaluation episode. Agents receive
a research question, accessible materials and a budget. They develop a hypothesis,
choose and execute experiments, interpret evidence, submit a paper with executable
artifacts, receive a bounded evidence-based review, and submit a revision. A valid
negative finding can be scientifically successful; fabricating a positive result
cannot. A task with a supplied question measures research development, not autonomous
topic selection. Within-brief hypothesis novelty is a separate judged outcome.

Full-cycle execution is already addressed by MLR-Bench and FIRE-Bench; paper revision
is already addressed by ReviseBench. The proposed contribution is the **linked
measurement of complete research outcomes and evidence-responsive judgment**:
research trajectories, independently checkable claims, and controlled feedback
share one source-task identity. A secondary shared-prefix experiment diagnoses
decisions without constraining primary agents to SciTaste's action menu. This is a
candidate contribution whose construct validity must be demonstrated, not a claim
that adding review or combining datasets is itself novel.

## Relationship to existing benchmarks

| Reference | Existing capability | Consequence for this design |
| --- | --- | --- |
| [ScienceAgentBench, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html) | Scientific task completion with executable outputs | Execution alone is insufficient differentiation; imported tasks retain original attribution. |
| [PaperBench, ICML 2025](https://proceedings.mlr.press/v267/starace25a.html) | Paper replication with detailed rubrics | Artifact reproducibility needs explicit requirements, not a language-model quality score alone. |
| [MLRC-Bench, NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/82c96f3c90741ef2c9b248e65d9b5db0-Abstract-Datasets_and_Benchmarks_Track.html) | Objective research-task performance | Keep task-native metrics and budget accounting; innovation ratings do not replace actual execution. |
| [MLR-Bench, NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html) | Open-ended research and resulting artifacts | Complete research and paper generation are not new by themselves. |
| [FIRE-Bench](https://arxiv.org/abs/2602.02905) | Full-cycle empirical rediscovery from high-level questions | Hiding a source paper's answer does not alone establish a new evaluation construct. |
| [ReviseBench](https://www.microsoft.com/en-us/research/publication/can-ai-revise-research-papers-with-human-review-feedback-an-empirical-study-and-benchmark/) | Research revision using review feedback | Evaluate evidence discrimination rather than counting whether revision occurred. |

## Task population and data construction

Domain and resource mode are separate axes. Scientific discovery, ML methodology,
and vision research are candidate domains; training-free and training-based are
ways an agent conducts an experiment, **not requirements to train the SciTaste
controller**. CPU-only is a valid budget. GPU tasks use remote resources. Coverage
claims follow admitted data, not the desired taxonomy.

Each task must contain:

1. A public problem brief, accessible data/code and provenance, resource ceiling,
   permitted tools, submission requirements and a public scoring rubric. The brief
   must allow substantively different hypotheses; copying a source method is not
   required for success.
2. A scorer-private endpoint: held-out data or executable claim checks, frozen
   metric direction and units, reproducibility checks, and a verified reference
   artifact showing the task is solvable within its declared budget. The scientific
   endpoint is identical before and after review and is never available to the agent.
3. A public-visible review instrument, prepared from permitted evidence rather
   than hidden test labels. It can supply additional diagnostic evidence with a
   recorded acquisition cost; it cannot disclose the hidden endpoint. Review and
   verification budgets are separate from the initial research allocation.
4. Source-family and split metadata covering shared paper, dataset, repository,
   task generator and derivative hypotheses. Memory sources and test tasks cannot
   share a disallowed lineage. Publication dates or different seeds do not establish
   independence. All previously consumed tasks are development-only.
5. Permission and redistribution status for every asset, an immutable content
   reference, documented scientific ambiguities, and source-bound independent
   adjudication. AI reviewers are labeled as AI; agreement is not human gold.

At intake, source-derived tasks and benchmark-authored tasks are distinguished.
The former validate adapters and external transfer but do not count as newly
collected SciTasteBench contributions. Novel benchmark content must consist of
substantive question/evidence/claim/feedback annotations with traceable origin.
There is no magic minimum task count. Release requires coverage of each claimed
domain and paradigm, task-family diversity, and precision adequate for the claimed
effect; any narrow slice is reported as such. Do not expand by duplicating stages.

## Review design: responding to evidence, not obeying a reviewer

The main research run uses one standardized evidence-grounded review per submission.
A review can recommend collecting evidence, revising an interpretation, or retaining
a supported claim. Systems are allowed to reject a review suggestion with evidence.
Successful revision must not require an improved task score when the correct action
is to retract an unsupported explanation.

A separate diagnostic sample includes supporting evidence, contradictory evidence,
and a non-diagnostic control. Content and presentation are balanced and source-bound;
reviewers do not know the system identity. Do not require three complete reruns of
every task. Allocate this diagnostic subset in advance and report its distinct
denominator. Pair before/after artifacts within the same trajectory. Include a
budget-matched continuation-without-review control on that subset before interpreting
change as a review benefit rather than an effect of extra compute or a second attempt.

Agent-authored claim lists do not define their own grading denominator. A frozen
task-level claim rubric evaluates required conclusions (including uncertainty),
unsupported claims, and unsupported rejection/acceptance of review evidence. Additional
novel claims are assessed separately with disclosed uncertainty. A short empty paper
cannot achieve perfect groundedness by making no claims.

## Primary systems, adaptations and ablations

Primary comparisons use actual version-pinned external research frameworks and
SciTaste Native, not prompts named after those systems. The local inventory records
which implementations have really run. At least one comparator must support a
genuine full research lifecycle; a coding/search agent with a shared report adapter
is an explicitly separate adapted-system block. A contract file is not evidence
that an adapter works. Unavailable systems remain unavailable, not synthetic rows.

The matched block shares the same backbone, visible task material, tools and stage
budgets; capability restrictions introduced by adaptation are disclosed. A best-native
block can use a framework's preferred setup but cannot be pooled with matched results.
Writing/review supplied by a common adapter measures the augmented system, not the
upstream framework's native writing capability. Frameworks are not forced to emit
Taste episodes, choose from a fixed action menu, or use SciTaste's internal memory.

No Taste, raw-source retrieval, generic memory, mismatched Taste, and applicability/
abstention removals are **within-framework ablations**, in their own table. Independent
decision policies on shared-prefix forks are mechanism studies, not whole-framework
baselines. Existing external benchmarks provide secondary transfer evidence.

Current execution uses session/subagent model roles. The default child configuration
inherits the parent; a provider-verified model identifier, tokens and financial cost
must remain unknown unless actually observed. Isolation is fresh role-scoped context,
not a claim of separate hardware or statistically independent models. Do not pool
this cohort with GLM/DeepSeek API runs. No Qwen API calls. Session time is not free
compute merely because no supplier API receipt is produced.

## Outcomes, missing data and scientific interpretation

| Outcome | Definition and denominator | Not a substitute for |
| --- | --- | --- |
| Task-native result | Frozen objective endpoint, per task/domain in its original units | Novelty, paper quality or scientific correctness |
| Reproducible completion | Valid runnable artifact and frozen task requirements; all assigned tasks | Positive results or good scientific judgment |
| Evidence-supported conclusions | Task-required claims assessed against executable checks and a calibrated, blinded rubric | A generic paper-writing grade |
| Review response | Claim-level correction/retention and paired pre/post outcome at the same hidden endpoint | Blind compliance, or guaranteed score improvement |
| Research cost | Observed runtime, compute allocation, calls/tokens where available | Unknown cost reported as zero |

Keep failures, deferred runs and missing metrics distinct. Report completion over all
assigned tasks and native scores with explicit availability denominators; do not rank
systems on different survivor subsets or impute zero for missing scores. If an official
task defines a failure utility, show it separately with that rule disclosed. Never
average incompatible domain metrics into a made-up overall score. Per-task paired
effects, task-family macro summaries of common binary/rubric outcomes, and counts are
primary readable reporting. Uncertainty is analysis, not a standalone performance metric.

Review validity requires blinded calibration against executable claim checks,
counterexamples to unsupported claims, style-only perturbations and documented
disagreements. Independent AI assessment is permitted now; until calibrated its
scores are exploratory and cannot establish scientific correctness or benchmark quality.

## Implementation boundary and next delivery

`scitaste.benchmark.full_task` implements admission contracts and evidence separation;
the old fixed-choice runner remains a diagnostic subsystem. Contract acceptance is
not automatic execution permission, artifact reproduction or scientific approval.
The first inventory is `outputs/projects/scitaste-self-development/evaluations/
scitastebench-full-task-intake-20260930-v2/`. Its observed counts override aspirations.

Next deliverable is a source-bound development task pack through two real full-task
system adapters, including actual experiments and pre/post-review artifacts. In
parallel, qualify fresh task families and benchmark-authored annotations for the
formal population. Freeze the population, comparators, grader and budgets before
observing formal outcomes. Do not restart the old expensive meta-learning run simply
to fill the new primary table, or label old exposed tasks as held-out SciTasteBench.

### Actual comparator qualification order

The source audit found AutoResearchClaw's 23-stage implementation. The historical
seeded-study adapter starts at stage 8; it is not the current native whole-task
execution. Actual graph development runs from the original stage sequence and
retains a separate mapping recovery, delivered paper and missing confirmation.
Disclose skipped topic-discovery work when the benchmark supplies a question.
MLR-Agent is now the second executed external system, not a completed formal
baseline. Following the initial intake, its actual code was acquired
at `f728d571a992d71c8b526eeb4d9ab6bb5c8cc824` through a code-only sparse checkout;
the source receipt is `evaluations/acquisitions/mlr-agent-native-source-v1.RECEIPT.json`
in the self-project. Its native experiment stage invokes an actual coding CLI, which
must remain an executed dependency, not be replaced by a role-playing subagent.
October 1 development now runs that pinned native sequence with a real Codex CLI
and a request-bound chat/Responses session transport. Idea, literature and proposal
are delivered, and the CLI has executed experiments and pre-freeze internal critique.
Frozen confirmation completed all eleven declared procedures/controls and the native
pipeline returned a paper. The coding CLI authored it; upstream writing detected
the existing manuscript and reused it, without a separate writer model pass. The
original missing-dependency failure is retained. Independent paper assessment stays
separate from objective scoring and native pipeline completion.
The literature configuration uses a native ordinary text model rather than the
supplier search engine. Model aliases are not verified backbone identities.
This is a post-hoc graph-development assignment, not formal qualification or a new
independent task. MLR-Agent has native paper writing but no post-paper review/revision
stage. Primary initial-paper outcomes can compare its actual native workflow;
adding a feedback loop must be labeled an augmented system in the revision study,
not silently attributed to upstream MLR-Agent.
Agent Laboratory has a prepared checkout but an
explicitly false live-readiness receipt. AI-Researcher remains conditional on source,
license and task integration. The real MLAgentBench ResearchAgent is already executed
but belongs to the separately labeled adapted-controller/shared-writer comparison.

### Contract command

For a materialized full-task manifest (not the heterogeneous intake inventory):

```bash
.venv/bin/python -m scripts.scitastebench_full_task audit \
  --suite /path/to/SUITE.json --artifact-root /path/to/task-assets
.venv/bin/python -m scripts.scitastebench_full_task export-public \
  --suite /path/to/SUITE.json --artifact-root /path/to/task-assets \
  --output /path/to/new-public-manifest.json
```

Audit returns status 2 for blocked admission. Public export is exclusive-create and
does not copy assets or launch experiments. Scientific task qualification must
precede a successful export; the current intake is not such a qualified release.

## Current scientific-design appendix — 2026-10-08

Canonical deliverable: `task-freeze`, specifically research questions with
distinguishable explanations and evidence-bounded conclusions. The current
machine-readable design is
[`scientific_design_v1.json`](../../configs/benchmark/scientific_design_v1.json).
The read-only interface is `scitaste.benchmark.scientific_design`.

This is a **prospective development successor**, written after the six original
cohorts' outcomes were visible. It neither edits their briefs/scorers nor upgrades
them to a newly frozen formal population. Six domains, successful code execution,
or a schema-complete contract do not demonstrate benchmark novelty or quality.
The six source families remain `development_exposed`; different within-family
examples or new controls do not create independent research tasks.

### What was inspected, and what it changes

The six `SCITASTEBENCH_*_V1.md` source designs, actual campaign `TASK.md`,
`CAMPAIGN.json` and researcher-visible `PROTOCOL.json` were inspected. Their
frozen primary endpoints remain unchanged. They already require hypotheses and
honest interpretation; their weakness is not simply an absent schema field.
They do not supply a concrete sufficient discrimination matrix, and ordinary
reference executability does not establish strong domain competitiveness.

Accepted-work comparison used Methods/Evaluation, not abstract-level matching:

- [MLR-Bench, NeurIPS 2025 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html):
  Sections 2–4 and Appendix A of the
  [author full text](https://arxiv.org/html/2505.19955v3) distinguish open-ended
  task-to-paper evaluation, stage-specific outputs and reviewer validation.
  Actual experimentation uses a selected subset rather than treating every
  ideation prompt as an executed complete research task. Our fixed, executable
  endpoints are useful but narrower; paper ratings need independent validity
  evidence, not adoption of its rubric name.
- [AI-Researcher, NeurIPS 2025 main track](https://proceedings.neurips.cc/paper_files/paper/2025/hash/0d904d300a105809a2114d727851e759-Abstract-Conference.html):
  local `papers/related_work/pdfs/autoresearch/systems/tang2025airesearcher/paper.pdf`,
  Sections 2.1–2.3 and 3–4 separate guided implementation, autonomous exploration,
  implementation correctness and comparative contribution assessment. Supplying
  our research questions measures within-brief hypothesis development, not topic
  discovery. Neither coherent writing nor a native stage-complete run substitutes
  for a scientifically informative implementation.
- [PaperBench, ICML 2025](https://proceedings.mlr.press/v267/starace25a.html):
  local `papers/related_work/pdfs/autoresearch/benchmarks/starace2025paperbench/paper.pdf`,
  Sections 2–5 separate source-code development, actual execution and reproduced
  results, with an independent judge evaluation. Our evidence-supported-claim
  measurement needs the same separation. These are comparison constructs, not
  numerical quality thresholds or a requirement to copy its task count.

Local paper paths above are relative to the self-development project's root.
The six original task families are source-derived authored adaptations; their
task data sources are not autonomous-research framework competitors.

### Scientific gaps and minimum discriminating actions

| Family | Mechanism currently not identified | Next prospective public-data contrast | Strong subject reference still required | Data/scope boundary |
| --- | --- | --- | --- | --- |
| Molecular gap | Angular information versus estimator capacity and chemical composition | Same estimator/capacity/fit exposure, angular removal plus matched-dimension null information | Train-only learned structural predictor, e.g. PaiNN; Methods/adaptation and result remain pending | Computed equilibrium QM9 gaps; public larger-molecule validation is already visible, not an unseen domain |
| Planar geometry | Confidence order versus spatial support, scoring and executed work | Fixed-point-set rank shuffle, plus coverage-matched filtering; actual work and selector use retained | Same-correspondence MAGSAC++ at a frozen actual-work objective | Planar SIFT correspondence inference, not matcher training, nonplanar geometry or universal confidence calibration |
| Physical rollout | Conservation versus stability, smoothing and coarse-grid closure | Same fitted rule/integrator, conservation-by-stability contrast; resolved modes assessed separately from mean drift | Converged known-equation spectral reference; neural operator needed only for a learned-model competitiveness claim | One simulated equation/viscosity; later public horizon is visible; coarse averages are not exact generator states |
| Forecasting | Pooling versus target-unit loss, series weighting and local capacity | Loss/exposure-controlled shared versus local coefficients; capacity attribution remains unresolved without an effective-complexity negative control | Seasonal ETS/Theta reference; global N-BEATS only for broad learned-model competitiveness | Capped-history monthly new-series identities, not unseen temporal laws or certified structural breaks |
| Population variation | Recalibration versus ranking/capacity and marginal prevalence | Fixed predictor outputs, household-crossfitted monotone mapping, no-mapping and intercept-only controls | Strong categorical boosted predictor at shared exposure/search budget | Eligible state/year populations and nominal income; year/geography are descriptive, not a causal intervention |
| Perturbation composition | Condition-specific residuals versus mean/amplitude/saturation correction | Fit-only additive/amplitude reference followed by correctly assigned versus permuted residual correspondence | Strong simple additive/mean/ridge reference; GEARS only for contemporary learned-model competitiveness | Known constituent singles and one K562 assay; split-half cells are not independent biological replicates |

These controls are **experimental-subject comparisons**, not extra AutoResearch
framework rows. The system comparison remains genuine pinned frameworks. The
minimum Taste attribution study is separately matched OFF/raw-source/full Taste;
generation-versus-selection diagnosis belongs only to a subset where the
intervention is observed to operate. This appendix does not require five arms
for every task or repeated runs solely to increase counts.

The hypotheses in the JSON are assessment anchors, not a restricted menu of
allowed researcher ideas. Researchers may introduce better hypotheses; their
scientific claims still require discriminating evidence and a declared scope.
Positive and well-supported negative conclusions are both admissible. A lower
task error alone does not establish an explanation, novel insight or Taste benefit.

Important unresolved boundaries remain explicit in the contract: matching
forecast lags/regularization does not match the total or effective capacity of
global versus local coefficients; rank-preserving population recalibration plus
Brier gain does not itself prove calibrated probabilities or a transfer mechanism;
rank shuffling in geometry tests the supplied ordering, not the causal generation
of real-world confidence. These are scientific identifiability limitations, not
schema omissions that the audit can declare repaired.

### Executable audit and its deliberately limited meaning

```python
from pathlib import Path
from scitaste.benchmark.scientific_design import (
    audit_scientific_design,
    load_scientific_design,
)

suite = load_scientific_design(Path("configs/benchmark/scientific_design_v1.json"))
for task in suite.tasks:
    print(audit_scientific_design(task).model_dump(mode="json"))
```

The interface rejects dangling hypothesis/control references and contradictory
matching declarations. Its coverage check asks whether every hypothesis pair
has at least one *declared directional difference* under a contrast. A difference
in prose or a successful schema parse is not empirical identifiability. Explicit
remaining confounders and falsifying counterexamples must still be examined
scientifically; those limitations are not silently resolved by the code.

All seven required contrasts and six required domain references are currently
unimplemented in this successor and have no successor-bound result. References
retain `required=true` and `result_status=not_run`; optional modern learned
references cannot be used to claim an unperformed comparison. Methods marked
`methods_read_required` must be read before their implementation protocol is
frozen. This audit can report omissions without blocking unrelated authorized
research or requesting human review for a checklist.

For subsequent work, `DesignEvidence` binds a stated observation to the canonical
design digest, subject identifier and a real local artifact digest. Without a
local root, missing bytes or mismatched designs, the observation remains
unverified. Receipt binding still does not prove correct implementation, full
sample coverage, independent reproduction or valid judge measurement. The audit
never sets `scientific_validity_certified`, `formal_evidence_eligible` or
`legacy_results_upgraded` to true, even when every structural/evidence item is
present. `ready_for_supported_mechanism_assessment` means evidence is present for
scientific assessment, not that the mechanism has been established.

Next evidence-producing action is one public-data discrimination contrast with
its meaningful subject reference, followed by a new explicitly development
assignment if needed. Do not rerun old private scores, select new primary methods
from old confirmation or count these six exposed families as fresh formal transfer.
GPU-dependent reference qualification requires a new shared-resource setting;
it is not permission to change only SciTaste's resources or launch GPU work now.
