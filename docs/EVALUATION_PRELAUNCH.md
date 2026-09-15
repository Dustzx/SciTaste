# Evaluation prelaunch contracts

Status: **resource proposals only**. A read-only remote inventory has been
recorded, but no model transfer, dataset download, GPU execution, reviewer
recruitment, or formal cell is authorized by these files.

For every new run, the controlling experiment is now the capability-driven
[`AutoResearch program v4`](research/SCITASTE_CAPABILITY_DRIVEN_AUTORESEARCH_PROGRAM_V4.md).
The model-specific proposals catalogued below are historical or bounded
substudies. In particular, Qwen3-VL-2B is not the primary-model default; v4
selects each role from all qualified resources or task-fit downloads.

SciTaste keeps three experimental objects separate:

| Object | Examples | What it determines |
|---|---|---|
| research method/system | SciTaste Native, Agent Laboratory, AI-Researcher, DeepScientist, other admitted accepted methods, and the direct agent | who is compared |
| benchmark/task source | SciTasteBench decision cases, InnovatorBench/InnoGym objective tasks, MLR-Bench lifecycle tasks, and EXP-Bench diagnostics | where and on what evidence the systems are evaluated |
| review/judge protocol | blinded experts, adjudication, calibrated model judge | how the outputs are judged |

The cross-track approval view is the
[`EXPERIMENT_DECISION_DOSSIER.md`](EXPERIMENT_DECISION_DOSSIER.md). Its current
machine-readable campaign binds the API and GPU plans, their dependency order,
resource ceilings, paper title, and review closure path while granting no
download or execution authority. The older individual proposal files remain
immutable evidence and are not silently promoted when the campaign changes.

Prelaunch schema `1.2` makes the external-system resource choice explicit. An
API lane must declare either:

- `matched_backbone`, with one common provider/model resource, an unconfounded
  model-effect declaration, and a matched-backbone claim boundary; or
- `best_native`, with one content-bound API resource per system, an explicit
  `model_effects_confounded=true` declaration, and a claim boundary that
  prohibits interpreting the result as a causal scaffold effect.

Schema `1.3` then binds the scientific interpretation itself: one exact
estimand kind, lane, candidate, closed contrast set, direction, minimum effect,
minimum task population, and `include-as-outcome` failure policy. The resulting
cell plan carries the claim hash and actual system-specific model resource into
every cell. Best-native cells receive the separate `best_native_system`
scientific role and are excluded from causal and headline-completeness
calculations. Different estimands may be reported side by side, but the result
verifier cannot pool or relabel them.

Schema `1.4` separates a declared contrast's analysis obligation from its
inferential role. Every contrast must still produce a valid, content-bound
analysis. Only `confirmatory` contrasts can determine the preregistered headline
conclusion; `mechanism_diagnostic` contrasts remain mandatory to report but may
be positive, null, or negative without being silently converted into a failed
headline hypothesis. For native Taste causality, Full--Base and
Full--mismatched-Taste are confirmatory. Knowledge-only, Taste-only, and
critics-only arms are component diagnostics, not marginal ablations. Legacy
schema-1.3 proposal, claim, and analysis hashes remain unchanged.

Exact source acquisition is governed separately by
[`DATA_ACQUISITION_APPROVAL.md`](DATA_ACQUISITION_APPROVAL.md). An acquisition
request can become ready for owner review without granting download authority;
it never authorizes ingestion or experiment execution.

A Benchmark repository cannot satisfy a method-comparator gate, and a method
repository cannot satisfy a task-source gate. The prelaunch validator enforces
that distinction through the audited external-resource corpus rather than the
display label in a YAML file.

The scientific authority now precedes these resource manifests. Inspect
[`iclr2027_scitaste_evidence_program_v1.yaml`](../configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml)
before interpreting any lane:

```bash
.venv/bin/scitaste evaluation evidence-program \
  --manifest configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v9.yaml \
  --require-scientifically-coherent
```

This inspection currently passes scientific coherence and fails acquisition,
experiment, and launch readiness. Consequently every model-bound lane below is
historical feasibility evidence until a new prelaunch manifest is derived from
the approved task, adapter, conformance, power, and human-review decisions. A
newly discovered Qwen checkpoint cannot promote an old lane.

The exact bridge from scientific design to owner decisions is now separately
content-bound:

```bash
.venv/bin/scitaste evaluation evidence-review \
  --manifest configs/evaluation/programs/iclr2027_evidence_review_package_v1.yaml \
  --workspace-root . \
  --require-owner-review-ready
```

The command verifies complete coverage of the four selected source proposals
and three accepted-method adapter proposals. Its current 21-file, 8-MiB metadata
request is review-ready but unapproved. It requests only 20 InnovatorBench task
configs and one EXP-Bench CSV; the 69.7-GB archive, runtime assets, repositories,
models, API calls, GPUs, and reviewers remain outside the scope. AI-Researcher
is reference-eligible but code-use-blocked because no applicable repository
license is identified.

## Resource lanes

Each provider alternative has a separate protocol and proposal hash. There is
no silent fallback between Zhipu and DeepSeek.

| Proposal | Scientific role | Exact model/resource named in its immutable bytes | Declared matrix | Current state |
|---|---|---|---:|---|
| `native-taste-causal-prepilot-v11` | within-SciTaste causal feasibility | one content-bound Qwen3-VL-2B tree (`47f9c0e0...`) and one remote 8×RTX 3090 lane shared by all six conditions | 6 native conditions × 2 MLRC task candidates × 1 seed = 12 trajectories | current schema-v1.4 no-run proposal; six structural implementations bind commit `eca58df...`, while v3 preflight qualifies bounded candidate generation, fixed-candidate selection, and the source/quality-bound human curation runtime; Full--Base and Full--mismatched are the two confirmation obligations, while three component-only analyses are mandatory diagnostics; actual paired corpora, assets, remote checkpoint, reviewers, and approval remain blocked |
| `external-best-native-prepilot-v7` | model-confounded ecological system feasibility | SciTaste/DeepSeek V4.1 Flash, Agent Laboratory/o3-mini, TinyScientist/GPT-4o-2024-08-06 | 3 real systems × 2 MLRC task candidates × 1 seed = 6 trajectories | immutable, superseded schema-v1.3 no-run proposal; model mapping is statically bound, but the retired V4.1 identity and the missing task/sandbox/telemetry/artifact/failure adapters, task assets, credentials, reviewers, and approval make it non-launchable; it can never establish the causal Taste/title claim |
| `formal-v6-package-prepilot` | historical API idea-to-paper package-preference feasibility | historical DeepSeek API `deepseek-flash`, served version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 execution units | immutable no-run proposal under an older resource/protocol generation; the current V4 identity requires a new proposal, and the 100 units remain only a historical ceiling |
| `formal-v5-package-prepilot` | superseded provider-identity snapshot | historical `deepseek-v4-flash` / `DeepSeek-V4-Flash-0731` assumption | 5 systems × 10 official tasks × 2 seeds = 100 execution units | immutable no-run history; the legacy alias is now routed to V4.1, so this record must not be relabeled or launched |
| `formal-v4-package-prepilot` | historical package-preference proposal | `deepseek-flash` / `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 execution units | immutable history with a superseded identity and older source/resource/governance contract; do not launch |
| `formal-v4-accepted-method-prepilot` | historical API scope with an invalid endpoint/task binding | DeepSeek API `deepseek-flash`, documented version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 cells | immutable history; v3 incorrectly treated the MLR-Bench open-ended package rubric as objective task progress and must not be approved or launched |
| `formal-v4-prepilot` | historical API scope proposal | DeepSeek API `deepseek-flash`, documented version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 1 seed = 50 cells | immutable history; included preprint comparators and lacked replication plus analysis/integrity contracts |
| `formal-v3-prepilot` | historical API proposal | earlier DeepSeek V4 API identity | 5 system × task × seed cells | immutable history; do not edit it into current evidence |
| `formal-v2-accepted-method-prepilot` | historical Zhipu scope with the same invalid endpoint/task binding | Zhipu `glm-5.3-flash`, documented version `GLM-5.3-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 cells | immutable history; rebuild as a separate schema-v1.1 package-preference proposal after exact pricing is resolved rather than editing or silently falling back from DeepSeek |
| `formal-v2-prepilot` | historical Zhipu scope proposal | Zhipu `glm-5.3-flash` | 5 system × task × seed cells | immutable history; do not edit into the accepted-method proposal |
| `robustness-v2-multitask-prepilot` | historical local small-model scope with an invalid endpoint/task binding | Qwen3-VL-2B-Instruct, tree SHA-256 `8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1`, 4,266,653,057 bytes; 8 × RTX 3090 requested | 6 ablations × 2 tasks × 2 seeds = 24 cells | immutable no-run history; rebuild against qualified objective-score tasks or an explicit package-review endpoint before any GPU approval |
| `robustness-v1-prepilot` | historical local scope proposal | the same local Qwen checkpoint candidate | 6 ablation × task × seed cells | immutable one-task/one-seed history |

The 2026-09-10 DeepSeek V4.1 release exposes canonical callable ID
`deepseek-flash` and family `DeepSeek-V4.1-Flash`. Resource catalog v13 records
the conservative peak tariff—USD 0.006/M cache-hit input, USD 0.30/M cache-miss
input, and USD 1.20/M output. The prior V4 snapshot and every proposal that
binds it remain historical no-run evidence, not current launch candidates. A new
proposal and an authenticated returned-model observation are required. See the
official [model and pricing table](https://api-docs.deepseek.com/quick_start/pricing/).

The official Zhipu model page now names callable ID `glm-5.3-flash`, version
`GLM-5.3-Flash`, 1M context, and 128K maximum output. The proposal therefore
marks public identity verified. The public price page still does not expose a
stable exact token table to the no-JavaScript inspector, and the model page gives
only relative-cost language. Pricing stays blocked rather than borrowing values
from another GLM family. An authenticated preflight must also record the served
revision immediately before an approved call because the callable name is a
rolling alias. A future Zhipu package-preference proposal must bind the same
schema-v1.1 endpoint semantics in its own immutable bytes; it cannot reuse the
historical objective-progress proposal or act as a silent DeepSeek fallback.

A fresh read-only SSH observation on 2026-09-12 verified eight idle RTX 3090
devices with 24,576 MiB each, driver 570.211.01, Python 3.12.3, Docker,
Bubblewrap, and 311,710,777,344 bytes free on `/media/sdb`. Bounded discovery
found eight remote model paths; Qwen3.5-4B was full-tree hashed and matches a
local replica, while Qwen3.5-9B is incomplete and blocked. These assets are
inventory only. The ICLR model policy is selected from the scientific design,
not from what happens to be installed, and the old 2B proposal remains a
feasibility prepilot rather than a frontier-backbone substitute.

The historical DeepSeek package proposals name the exact ten-task MLR-Bench
Appendix A candidate population used by the accepted benchmark for
experimentation, writing, and end-to-end evaluation. It contains seven
Trustworthy AI, two LLM/VLM, and one ML Theory task. These are open-ended
workshop-derived research briefs assessed with research-quality rubrics; they do
**not** expose a fixed objective score for each task. The metadata-only
selection is tracked in
`research/data/mlr_bench_official_ten_candidate_v2.yaml`, which machine-labels
every task as `research_package_review`. Its starting brief bytes are not
present, downstream/runtime asset licenses and executable signals remain
pending, and it authorizes neither download nor execution. The content-bound
package protocol at
`research/protocols/AUTORESEARCH_PACKAGE_PREFERENCE_PREPILOT_GOVERNANCE_V4.md`
freezes independent blinded expert preference as primary and a model judge as
secondary. Objective progress remains a separate lane for a benchmark such as
qualified MLRC-Bench; the two estimates are never pooled.

## Replication and matrix discipline

An execution `cell` is an internal scheduling and accounting term for one
system--task--seed--condition combination. The paper reports systems, tasks,
independent trajectories, repetitions, and analysis units; a large cell count
is not evidence of rigor by itself.

- Deterministic checks receive no repeated scientific runs; unit and replay
  tests establish their engineering behavior.
- One task/seed across every admitted system is an adapter block only. It can
  expose inequivalence and telemetry failures but cannot estimate an effect.
- A pilot uses the smallest source-diverse task set and paired seeds needed to
  estimate between-task, within-task, and reviewer variance. More distinct
  tasks are preferred over additional seeds once within-task variance is small.
- Formal task and seed counts follow the preregistered pilot power analysis.
  The historical 100-unit matrices are ceilings and design snapshots, not
  quotas that must be consumed.
- Exactly one provider/model family supplies the primary matched-backbone
  estimate. A second provider runs only the powered robustness slice needed to
  test model dependence; SciTaste does not duplicate the full Cartesian matrix
  merely because another API is available.
- Scale-out stops after each complete matched block if task signal, adapter
  equivalence, telemetry, reviewer reliability, or conditional variance makes
  further repetitions uninformative.

## Machine gate

Inspect any proposal without provider or GPU access:

```bash
.venv/bin/scitaste evaluation prelaunch \
  --manifest configs/evaluation/prelaunch/qwen3vl2b_native_taste_causal_prepilot_v11.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v8.yaml \
  --source-root /path/to/exact-clean-executable-checkout \
  --evidence-root /path/to/proposal-and-protocol-checkout
```

The result contains:

- file and semantic hashes;
- the observed executable Git commit and tree cleanliness;
- exact planned cell count;
- method-system and benchmark-resource blockers;
- API identity/pricing or GPU inventory/checkpoint blockers;
- human-review blockers;
- evidence-bound findings from benchmark-fit, baseline-applicability,
  statistics, integrity, and resource critics;
- separate readiness and exact-hash author-approval verdicts;
- `no_execution_performed=true`.

Qualify the exact objective-progress task slice against the current API/GPU
catalog without acquiring data or launching a task:

```bash
.venv/bin/scitaste evaluation executable-candidate \
  --manifest configs/evaluation/candidates/mlrc_3090_objective_progress_v1.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v7.yaml \
  --compute-catalog configs/resources/compute_catalog_v6.yaml \
  --require-metadata-review-ready
```

The current v1 candidate accepts all seven official MLRC-Bench task identities,
selects four 16 GB tasks for a mechanism/transfer study, excludes three 48 GB
tasks from the 24 GB-per-device host, and nominates only Temporal Action
Localisation and Cross-Domain Meta Learning for the first acquisition-request
review. Its declared 4 tasks × 3 conditions × 3 seeds totals 36 internal run
units and at most 180 GPU-hours under the 192 GPU-hour ceiling. The command
deliberately fails `--require-experiment-ready`: exact acquisition allowlists,
task bytes, upstream-license closure, environments, baselines, and held-out
reproduction are not yet complete, and the four-task slice cannot support a
benchmark-wide generalization claim.

The first two candidates now have an exact large-asset inventory and a separate
review-only request:

```bash
.venv/bin/scitaste evaluation dataset-package-request \
  --manifest configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml \
  --workspace-root . --require-metadata-review-ready
```

It binds 39 archives with 3,761,168,137 observed compressed bytes, a 16 GiB
unpacked ceiling, and a 32 GiB minimum-free-storage requirement. The package is
now approved under the standing download policy, atomically acquired, and
independently rehashed with zero mismatches. The bound license policy preserves
CC-BY-4.0 for Perception materials and Meta-Album's CC-BY-NC-4.0 overlay plus
source-specific obligations. AWA correctly remains a per-image license case:
acquisition is reviewable, while ingestion requires license-record presence and
coverage checks. Opening ZIP central directories now requires a separate exact
archive-read approval and explicit local switch; the real archives remain
unopened and unqualified. See
[`MLRC_FIRST_PREFLIGHT_ACQUISITION_AUDIT_V1.md`](research/MLRC_FIRST_PREFLIGHT_ACQUISITION_AUDIT_V1.md).

## Project-owned proposal bundles

The global `configs/evaluation/prelaunch/` files are reusable proposal sources,
not a project history. A project registers an exact no-run copy before treating
it as its current experiment plan:

```bash
.venv/bin/scitaste project evaluation register-prelaunch \
  --project-id scitaste-self-development \
  --evaluation-id deepseek-v41-package-prepilot-v6 \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v6.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v6.yaml \
  --source-root . --evidence-root . \
  --expected-revision <current-project-revision> --select \
  --outputs-root outputs
```

This atomically creates
`outputs/projects/<project-id>/evaluations/<evaluation-id>/` with exact copies of
the prelaunch manifest and resource corpus plus `GATE_REPORT.json`,
`CRITIC_REPORT.json`, `CELL_PLAN.json`, and a self-hashed `EVALUATION.json`.
`PROJECT.json` retains the record hash, readiness, resources, blocker count, and
cell count. Opening or selecting the proposal rehashes every file. Registration
does not acquire data, contact a provider, inspect the remote GPU host, or launch
a cell; even an approved proposal remains data-only until a separate launch
service revalidates its exact authority.

Inspect the selected proposal at decision scale without hiding its exact
diagnostics:

```bash
.venv/bin/scitaste project evaluation status \
  --project-id scitaste-self-development \
  --outputs-root outputs
```

The output deterministically groups repeated task/cell/resource diagnostics into
seven ordered decisions: task scope, comparator adapters, statistical design,
temporal integrity, independent review, runtime resources, and exact-hash owner
approval. `diagnostic_blocker_count` remains the number of exact unique codes;
`decision_blocker_count` is the number of unresolved decision domains. Unknown
diagnostic codes fail closed into the integrity domain.

## Result admission after approved execution

Execution output does not become paper evidence merely because a launcher
finished. A runner writes a self-hashed `EvaluationResultSet` beneath the owning
project. It records exact cell/plan/resource identities, API or GPU telemetry,
real-versus-synthetic evidence class, hashed output artifacts, condition-blinded
review attestations, and primary analysis contrasts. Register it without
performing another model, provider, or GPU call:

```bash
.venv/bin/scitaste project evaluation register-result \
  --project-id scitaste-self-development \
  --evaluation-id <approved-evaluation-id> \
  --result-id <immutable-result-id> \
  --result-set outputs/projects/scitaste-self-development/runs/<run>/RESULT_SET.json \
  --expected-revision <revision> --select --outputs-root outputs --dry-run

.venv/bin/scitaste project evaluation result-status \
  --project-id scitaste-self-development --outputs-root outputs
```

The dry run fully verifies existing bytes but creates no execution. Result
selection also selects the proposal it belongs to; selecting another proposal
clears an incompatible result selection. For a formal claim result, every
planned cell must have a budget-compliant real outcome and every required blind
review must be external and attested. A preregistered execution failure remains
in the intention-to-run population at its frozen task floor; it is not silently
excluded. A missing/invalid record, drifted artifact, unplanned contrast, or
changed analysis rule blocks the claim. Under schema 1.4, the native Taste title
gate requires valid analyses for the complete no-Taste, placebo, and component
contrast family, but its positive conclusion depends only on the two explicitly
confirmatory controls. The assessment reports confirmatory and diagnostic
required/valid counts separately. External matched superiority requires at
least two qualified method comparators. Best-native evidence stays descriptive
even when complete and positive.

Each schema-1.1 primary comparison also carries `analysis_input_sha256`, derived
from every exact candidate/comparator cell record, record hash, and
success/failure status under the claim's failure policy. A declared unit count
therefore cannot hide a dropped failed trajectory.

Result registration still does not alter an existing manuscript. A subsequent
`project paper build|build-draft|build-revision --evaluation-result-id <id>`
must materialize a new paper with a self-hashed
`SCIENTIFIC_EVIDENCE_BINDING.json`. It binds every other paper artifact plus the
exact result bundle, result set, and deterministic assessment. The review packet
then hashes that sidecar with the rest of the paper. This ordering prevents a
pre-result draft or pre-result review from inheriting scientific completeness.

The critic review is explicitly advisory: its schema fixes
`authorizes_execution=false`. `ready_for_author_review` becomes true only when
all five critic domains and the resource gate have no blockers. Even then, only
the separate proposal-hash approval can authorize a launch service.

Add `--require-ready` in CI or a launch wrapper to return nonzero until the exact
proposal is both ready and approved. The command itself has no execution path.
A launch service must independently require `execution_authorized=true` and the
same proposal hash.

Expand the proposal into its exact per-system, per-task, per-seed identities
without preparing or executing a launcher:

```bash
.venv/bin/scitaste evaluation cell-plan \
  --manifest configs/evaluation/prelaunch/qwen3vl2b_native_taste_causal_prepilot_v11.yaml \
  --output /tmp/native-taste-causal-cell-plan.json
```

The compiler generates opaque cell and review-blind IDs, preserves declared
matrix order, binds every cell to the proposal, task-asset, adapter-preflight,
and API/checkpoint resource hashes, and reports cell-local plus protocol-wide
blockers. Its output fixes `authorizes_execution=false` and records that no
provider call, GPU work, or task download occurred. The current native v11 and
external v7 proposals produce 12 matched native GPU trajectories and six
per-system best-native API trajectories respectively; all are blocked. This
makes the gap between a YAML matrix count and an executable experiment explicit
without using matrix size as a proxy for rigor.

The model-backed native path has an additional implementation-level preflight:

```bash
.venv/bin/scitaste evaluation native-condition-preflight \
  --manifest configs/evaluation/preflight/qwen3vl2b_native_condition_path_v6.yaml \
  --source-root .
```

Unlike ordinary local-file inspection, this command reads the evidence bytes
directly from the pinned Git commit and compares every implementation evidence
locator with the current worktree. A dirty or newer implementation therefore
cannot silently stand in for the claimed bytes. The current report verifies
the closed six-condition runtime, hard-feasible fixed-candidate selection,
provider/model/checkpoint identity checks, and durable decision telemetry at
the pinned `83a2e77...` implementation. The earlier v4/v5 proofs remain immutable
history artifacts and now fail closed against the changed implementation. V6 deliberately remains not
experiment-ready: bounded model candidate generation is statically verified, but
the exact checkpoint has not executed this path under an approved preflight and
no task-specific matched/placebo corpus pair exists. Corpus admission requires
equality in stage/decision role, eligible and retrieved case counts,
context-token budget, provenance tier, curation tier, and outcome-information
availability; only source/domain relation may differ, and zero retrieval
invalidates the cell. `--require-experiment-ready` returns nonzero while any of
these gates remains open. The report always fixes execution authority to false.

Static identity is complemented by an executable, local-only implementation
attestation:

```bash
.venv/bin/scitaste evaluation native-condition-attest \
  --manifest configs/evaluation/preflight/qwen3vl2b_native_condition_path_v6.yaml \
  --fixture-workflow configs/workflows/full_offline_native_conditions_v1.yaml \
  --source-root . \
  --workspace-root . \
  --output outputs/projects/scitaste-self-development/evaluations/\
native-condition-implementation-attestation-v1/REPORT.json \
  --allow-local-fixture-execution \
  --require-qualified
```

The switch permits only the repository's deterministic fixture. The command
runs all six conditions through Discovery, Evidence, Communication, and Figure,
checks the observed executor and controller routes against the closed matrix,
and removes its temporary project after producing the report. It cannot load a
checkpoint, use the network, call an API, inspect acquired source/task content,
or execute a real benchmark. A passing report establishes first-party condition
wiring; it does not clear matched/placebo corpus parity or support an effect
claim.

### Program-bound and typed execution evidence

Prelaunch schema `1.6` closes the last identity boundary before an expensive
pilot or formal block. A new proposal binds the exact ICLR evidence-program file,
its semantic hash, and the resource corpus. Inspection rejects task resources or
external comparators that are outside the program's selected scope, so an older
operational manifest cannot silently execute after the scientific plan changes.

Adapter evidence now declares whether its bytes are a static contract, an
external preflight report, a native preflight manifest, or a native preflight
report. The declaration is parsed, not trusted from the filename. Static
contracts and native manifests remain proposal-only and block readiness. A
verified external method requires a schema-1.1 adapter preflight report that
names the same external resource and resource corpus and reports
`ready_for_matched_adapter=true`. A verified first-party system analogously
requires a ready native report bound to the exact source commit.

External adapter preflight schema `1.1` also binds and replays the preceding
static contract by file hash and proposal hash. It checks code-use viability,
external-resource identity, upstream commit, and every implementation requirement
before inspecting a checkout. This prevents an unrelated or rights-blocked
adapter implementation from manufacturing a clean downstream report.

These validations are part of the launch transaction's identity, comparable to
checking that a payment addresses the intended recipient. They are required
because a wrong experiment can consume API/GPU/human resources and invalidate an
entire comparison. They do not change Tool Intelligence's direct path for cheap,
reversible project metadata work and do not add repeated environment-wide
prechecks.

Static exact-commit translation review has now resolved one ambiguity inside
that open adapter gate. MLR-Agent and Agent Laboratory are real method
candidates, but their pinned releases cannot provide an unchanged-core, fully
matched v6 trajectory under its task and coding-role contract. Their
content-addressed adapter contracts remain blocked before upstream checkout or
runtime implementation. This makes the declared v6 matched-backbone matrix
non-launchable even though its provider identity is current. Preserving the
blocked contracts avoids silently weakening “matched backbone”; choosing a
common natively supported backbone or a separately disclosed best-native-system
design requires a new proposal.

The `max_output_tokens_per_call` values in these proposals are per-experiment
ceilings, not a global SciTaste limit. V6 reserves 32,768 output
tokens per call, 1,500 requests, and fifteen million total tokens across its 100
candidate execution units. These are ceilings rather than targets and still
require a pilot-informed adequacy check. Any change creates new proposal bytes
and needs a new hash-bound approval.

### Prompt-only control boundary

SciTaste now has a real `direct-agent` control adapter rather than a name-only
placeholder. It accepts one exact visible task package and makes exactly one
structured provider call under a cell-local token, cost, latency, and request
budget. Retrieval, Taste, memory, tools, code execution, experiment execution,
repair, and independent review are structurally absent. The returned paper is
therefore labelled a proposal: its claim statuses are fixed to
`unsupported-until-executed`, and its receipt fixes empirical evidence,
independent review, and complete idea-to-paper eligibility to false.

An admitted call retains the exact invocation, task projection, model request,
raw provider response, structured research package, proposal paper, self-review,
and their SHA-256 values. Backend retries are prohibited so a one-call cell
cannot silently consume a larger budget. The live entry point remains closed
unless the invocation contains an exact proposal/plan/cell approval and the
operator also supplies `--allow-live`:

```bash
.venv/bin/scitaste evaluation direct-agent-run \
  --invocation /path/to/approved-invocation.json \
  --task-root /path/to/frozen-task-root \
  --backend-config /path/to/ignored-live-backend.yaml \
  --output /path/to/empty-cell-output \
  --allow-live
```

This is a low control condition, not the principal comparator and not a
substitute for the native no-Taste ablation. A top-level scientific-taste claim
still requires matched executable trajectories and the separate blinded review
protocol.

## Remaining work before the first approved block

1. Review and approve the exact MLRC post-download archive-read boundary, then
   run no-extraction ZIP qualification and close AWA's per-image license-record
   checks before ingestion. Separately select a deliberately non-formal
   MLR-Bench brief-only prepilot from the ten
   exact acquired inputs; freeze output package hashes, reviewer blinding, and
   runtime policy. Do not promote these broad prompts to empirical tasks. After
   an approved MLRC acquisition and package qualification, reproduce each
   baseline and held-out path before a formal objective-progress proposal. The
   Perception v2 adapter now makes that future execution label-safe: development
   uses only train/validation bytes, test inference receives features plus a
   metadata-only manifest, and the independent fixed-upstream-parity scorer
   opens original labels only after prediction bytes freeze. The scorer and
   Python 3.12 import/NMS path are ready; GPU baseline reproduction and launch
   authority remain open.
2. The dual-estimand architecture is materialized as native v11 and external v7
   immutable proposals. The six native structural policies are real and
   hash-bound; bounded candidate generation and fixed-candidate selection are
   Git-object-qualified at `8378736...`. A production-retrieval corpus-pair
   qualifier is implemented, but formal source bytes still require approval,
   acquisition, human abstraction, and qualification. Then close
   task, sandbox, telemetry, artifact,
   and failure-resume requirements for only those external adapters whose exact
   static contracts pass. Unavailable systems remain unavailable rather than
   receiving a pseudo-implementation.
3. Instantiate the package-preference protocol with common tools, repair
   budget, telemetry, blinded artifacts, and the later pilot-informed formal
   power analysis. Starting anchors and failure floors belong only to the
   separate objective-progress protocol.
4. Secure the blinded expert rubric, reviewers, conflict checks, and
   adjudication path.
5. For Zhipu, resolve exact dated pricing and record the authenticated served
   revision. For DeepSeek, perform an
   authenticated identity preflight immediately before launch because the API
   name is a rolling alias.
6. The GPU lane has now been independently re-probed: eight idle 24 GB devices,
   311,710,777,344 free storage bytes, and current isolation tools are verified.
   Next calculate only the scientifically selected task/model package before any
   transfer. Per-device capacity still cannot emulate the three 48 GB tasks.
7. Present the regenerated exact manifests and their proposal hashes to the
   project owner. Run one matched block only after explicit approval; require a
   second approval for scale-out.
