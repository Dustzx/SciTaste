# Accepted AutoResearch evaluation audit v1

Date: 2026-09-10

Status: literature and protocol-design evidence only. This document authorizes
no model call, dataset download, external-system installation, human study, API
spend, GPU allocation, or formal experiment.

## Decision

SciTaste must be evaluated as an independent AutoResearch system on research
problems outside its own development history. The `scitaste-self-development`
project remains a valuable longitudinal deployment case, but it cannot be the
headline effectiveness test: using SciTaste to improve SciTaste and then citing
that improvement as proof of SciTaste would create a self-confirming loop.

The accepted literature does not expose one universally adopted end-to-end
leaderboard. It instead combines three evidence forms:

1. **matched task execution**, where several agents receive the same problem and
   are scored under comparable resources;
2. **human or paper targets**, where an agent's code, findings, or paper is
   assessed against expert attempts or accepted work;
3. **frontier progress**, where the system must execute experiments and improve
   a real external objective rather than merely write a plausible paper.

SciTaste should combine these forms while keeping their estimands separate. The
title-critical system test is objective research progress on held-out tasks,
with [InnovatorBench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/3d13d910b48ac2e672a32cfdf98be1bf-Abstract-Conference.html)
as the primary acquisition candidate and
[InnoGym](https://proceedings.iclr.cc/paper_files/paper/2026/hash/743514dfa1ef705f378424bd1effb57b-Abstract-Conference.html)
as a contingent source pending an exact public implementation. MLR-Bench tests
the complete idea-to-paper package as supporting ecological evidence, while
EXP-Bench diagnoses the experiment-design-to-conclusion chain. Neither benchmark
is itself a competing autonomous-research method.

## Scope and correction to the existing resource ledger

This audit covers representative peer-reviewed AutoResearch systems and
benchmarks accepted at ICLR, ICML, or NeurIPS through the date above. It is not
a claim that every scientific-agent paper is included.

The earlier project-owned resource ledger remains useful for provenance and
availability screening, but its 36-work and 64-source snapshots are not a
complete accepted-evaluation landscape. In particular, they did not adequately
surface:

- [MLR-Bench (NeurIPS 2025 Datasets and Benchmarks)](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html),
  the closest accepted benchmark to an idea-to-paper comparison; and
- [EXP-Bench (ICLR 2026)](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c411f5b2d9c55f1685e72db224ad8b0e-Abstract-Conference.html),
  a large executable benchmark of the hypothesis-to-conclusion experimental
  chain.

This is a corpus-coverage defect, not evidence that the former snapshot was
fabricated. The snapshot must remain immutable; a future project-owned corpus
revision should add these works, inclusion rules, acquisition hashes, license
status, and adapter feasibility rather than silently editing the old ledger.

The current additive revision is the tracked, metadata-only
[`autoresearch_evaluation_resources_v9.yaml`](data/autoresearch_evaluation_resources_v9.yaml).
It preserves every earlier snapshot by content hash and adds exact metadata for
DeepScientist and InnovatorBench. Deterministic code derives four different
permissions from evidence gates; scientific relevance never implies operational
admission:

| Resource | Reference | Code audit | Benchmark task source | External comparison system |
|---|---:|---:|---:|---:|
| MLR-Bench | yes | yes | blocked | not applicable |
| EXP-Bench | yes | yes | blocked | not applicable |
| MLR-Agent | yes | yes | not applicable | blocked |
| AI Scientist-v2 | yes | yes | not applicable | blocked |
| AutoResearchClaw `v0.5.0` | yes | yes | not applicable | blocked |
| InnovatorBench | yes | yes | blocked | not applicable |
| DeepScientist | yes | yes | not applicable | blocked |

MLR-Bench and EXP-Bench still need a frozen source-disjoint executable subset,
asset inventory, and per-task upstream-license audit. MLR-Agent still needs a
thin unchanged-core adapter and complete mappings. AI Scientist-v2 additionally
has a custom license with restricted-use and manuscript-disclosure obligations
that require explicit acceptance; it must execute only in a dedicated sandbox.
AutoResearchClaw already has a pinned unchanged-core integration and native
artifact mapping, but its MLR/EXP task semantics, matched model mode, sandbox on
those assets, and telemetry remain unqualified. Therefore no formal external
run is authorized.

The v9 additions remain equally explicit. InnovatorBench lacks a dataset-level
license, frozen task selection, acquired assets, upstream-license audit, and
runtime qualification. DeepScientist lacks proof that its current product is
equivalent to the ICLR system, plus common task/model mapping, sandbox,
telemetry, artifact, and resume acceptance. Its reported 20,000-plus GPU-hour
campaign is a literature observation, not a compute prescription for SciTaste.

## What accepted work actually evaluates

| Work | Accepted venue | Evaluation unit and scale | Compared against | Principal evidence | Boundary |
|---|---|---|---|---|---|
| [MLR-Bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html) | NeurIPS 2025 D&B | 201 open-ended ML tasks; idea, proposal, experiment, writing, and end-to-end stages | six frontier LMs, coding agents, its MLR-Agent, and an AI Scientist-v2 comparison | stage rubrics, final-paper review, expert validation, and invalid/fabricated-result auditing | broad early-stage coverage but only a smaller task subset is practical for executable end-to-end evaluation |
| [AI-Researcher](https://proceedings.neurips.cc/paper_files/paper/2025/hash/0d904d300a105809a2114d727851e759-Abstract-Conference.html) | NeurIPS 2025 | Scientist-Bench over target AI papers, with guided and open-ended innovation settings | human target papers and model/backbone variants | implementation completion/correctness and blinded paper-level novelty, rigor, and validation judgments | broad direct comparison with other autonomous-research frameworks is not its main design |
| [Agent Laboratory](https://aclanthology.org/2025.findings-emnlp.320/) | Findings of EMNLP 2025 | staged literature, experimentation, report-writing, and human-feedback workflow | system variants and human-feedback settings | phase outputs, empirical results, report quality, and efficiency | an accepted method candidate, but matched-task semantics and current model mapping require a new adapter |
| CycleResearcher | ICLR 2025 | generated research papers and review/research corpora | human papers, AI Scientist, training and search ablations | reviewer-score prediction, simulated acceptance, expert paper judgments | training papers can contain fabricated experimental results; it is not evidence of executable end-to-end research |
| [DeepScientist](https://proceedings.iclr.cc/paper_files/paper/2026/hash/4f64494ecc3442f1c9261baa036378bc-Abstract-Conference.html) | ICLR 2026 | about 5,000 ideas and 1,100 experimental validations on three frontier AI tasks | human 2025 state of the art, system variants, and publicly available AI-scientist papers | real external scores, progressive discovery traces, generated-paper review, scaling, and failure analysis | strongest frontier-progress precedent but uses more than 20,000 GPU hours and only three target tasks |
| [InnovatorBench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/3d13d910b48ac2e672a32cfdf98be1bf-Abstract-Conference.html) | ICLR 2026 | 20 long-horizon LLM research tasks derived from 14 papers across six categories | ReAct-style agents with several frontier models | executable objective score, best/final score, multi-host action traces, checkpoints, and failures | objective-progress benchmark rather than an external method; tasks take roughly 2--36 hours and require additional data/checkpoints |
| [InnoGym](https://proceedings.iclr.cc/paper_files/paper/2026/hash/743514dfa1ef705f378424bd1effb57b-Abstract-Conference.html) | ICLR 2026 | 18 curated improvable tasks, with ten used in the main evaluation | multiple agents/models under visible and hidden evaluation | valid performance gain plus separately judged novelty | highly aligned objective/novelty task source, but an exact public code and asset pin is not yet established |
| [EXP-Bench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c411f5b2d9c55f1685e72db224ad8b0e-Abstract-Conference.html) | ICLR 2026 | 461 tasks from 51 top-tier papers | OpenHands/IterativeAgent and multiple model backbones | hypothesis, design, implementation, execution, conclusion, and conjunctive full success | starts from a question and incomplete code; does not test original idea selection or final-paper quality |
| [PaperBench](https://proceedings.mlr.press/v267/starace25a.html) | ICML 2025 | replication of 20 ICML 2024 Spotlight/Oral papers with 8,316 rubric items | multiple frontier agents and top ML PhD baselines | author-developed replication rubrics, executed artifacts, and a separately tested judge | tests faithful replication, not creation and selection of a new idea |
| [RE-Bench](https://proceedings.mlr.press/v267/wijk25a.html) | ICML 2025 | seven open-ended ML R&D environments; 71 eight-hour attempts from 61 experts | several agents/models and human experts at 2-, 8-, and 32-hour budgets | external task score, best-of-k scaling, and score-versus-time curves | evaluates research engineering progress, not manuscript generation |
| [MLE-bench](https://proceedings.iclr.cc/paper_files/paper/2025/hash/7e3767db483c942b883eb4f8cfb74e31-Abstract-Conference.html) | ICLR 2025 | 75 Kaggle competitions | multiple model/scaffold configurations and public human leaderboards | medal rate, resource scaling, and contamination analysis | strong ML-engineering signal but no idea or paper stage |
| MLAgentBench | ICML 2024 | 13 executable ML research tasks | several model and agent variants | task success, action traces, and failure categories | small engineering benchmark without paper output |
| AstaBench | ICLR 2026 Oral | more than 2,400 problems across the scientific process | 57 agents from 22 agent classes | stage-specific task metrics and holistic component coverage | broad component map, not one persistent idea-to-paper trajectory |
| DiscoveryWorld | NeurIPS 2024 D&B | 120 simulated discovery challenges | multiple LM agents and prompting/scaffold variants | task completion, relevant actions, and explanatory knowledge | closed simulated world rather than real ML research and publication |

Two distinctions are essential. First, a benchmark paper and an autonomous
research system paper answer different questions. Second, a fluent final paper
is not proof that the underlying experiment ran. MLR-Bench reports fabricated
or invalid experimental outcomes in a large fraction of coding-agent cases;
EXP-Bench reports only 0.5% complete executable success even though individual
sub-stage scores are much higher. SciTaste must therefore admit a paper only
after its claims resolve to executable, provenance-bearing evidence.

### Method and benchmark admission are separate

The formal program now gives every external item exactly one operational role:

- **method candidates** are executable systems such as Agent Laboratory,
  AI-Researcher, and DeepScientist; at least two real accepted systems must pass
  unchanged-core adapter admission before the ecological comparison can run;
- **task sources** are benchmarks such as InnovatorBench, MLR-Bench, and
  EXP-Bench; they provide environments and endpoints but never count toward the
  accepted-method minimum;
- **hybrid papers** may contribute both a benchmark and a named baseline only
  when the resource corpus registers and gates those identities separately; and
- **historical paper artifacts** can support a common review analysis but cannot
  be presented as a matched system execution.

The distinction is executable in
[`iclr2027_scitaste_evidence_program_v1.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml):
putting `innovator-bench` in the system-candidate set makes the scientific
coherence gate fail even though it is an accepted ICLR paper.

## Evaluation patterns supported by accepted papers

### 1. Broad stage evaluation, narrow expensive end-to-end evaluation

MLR-Bench uses a large collection for idea/proposal evaluation but a much
smaller executable subset for experimentation, writing, and full trajectories.
This is stronger than inventing a small set of synthetic generators, and more
feasible than pretending every one of hundreds of tasks can receive repeated
GPU-heavy runs.

### 2. Matched execution where compatibility is real

RE-Bench and MLE-bench provide the same environment and external scoring signal
to multiple systems. MLR-Bench also includes a direct AI Scientist-v2
comparison. This is the preferred evidence whenever systems can receive an
equivalent task package and budget.

### 3. Common artifact judging where execution cannot be matched

CycleResearcher and DeepScientist compare generated papers with human or public
AI-scientist papers through common review criteria. Such comparisons are useful
but secondary: historical artifacts differ in task, budget, model, publication
selection, and access to human intervention. They must not be presented as a
causal matched-system effect.

### 4. Human calibration rather than an unvalidated LM score

MLR-Bench, AI-Researcher, CycleResearcher, DeepScientist, PaperBench, and
RE-Bench all use human targets, expert assessment, author-created rubrics, or a
judge-validation study. A single proprietary model's review score is therefore
insufficient for SciTaste's headline result.

### 5. Executability and failure are outcomes

The accepted benchmarks preserve broken runs, invalid results, task failures,
and budget effects. SciTaste may not manually repair a formal trajectory and
then compare it with an unrescued baseline; repairs, retries, and human minutes
must be measured and governed by a matched policy.

### 6. Scientific progress and publication quality are separate axes

DeepScientist supports real frontier progress on a few tasks; MLR-Bench supports
stagewise and final-paper assessment; EXP-Bench supports experimental integrity.
No one number safely compresses all three. SciTaste should report:

- external scientific/task progress;
- evidence validity and experiment-chain success;
- final research-package/paper quality; and
- resource and human-intervention cost.

## SciTaste's recursive evaluation structure

The self-iteration design contains four nested levels:

1. **L0 — SciTaste product.** The reusable open-source controller, project
   state, Taste/Knowledge policies, critics, executor, evidence ledger, and
   publication path.
2. **L1 — `scitaste-self-development`.** A normal SciTaste project whose research
   question is whether explicit scientific taste improves autonomous research.
   It plans changes to L0, records failures, runs admissible studies, and builds
   the ICLR manuscript.
3. **L2 — external formal research projects.** L1 launches independent,
   content-addressed projects for held-out decision cases, InnovatorBench-style
   objective tasks, MLR-Bench full-lifecycle tasks, and EXP-Bench diagnostics.
   SciTaste Native and pinned baselines each traverse their real
   lifecycle and produce trajectories, evidence, code, results, and—where the
   task requires it—papers.
4. **L3 — evidence-guided return.** Failures and measured effects from L2 become
   evidence gaps or design proposals in L1. Accepted changes update L0, create a
   new versioned protocol, and rebuild the paper only from admitted evidence.

This recursion is intentional product dogfooding, but it needs strict temporal
and data boundaries. L1 proves ecological usefulness, traceability, and defect
discovery. Only held-out L2 tasks estimate comparative effectiveness.

## Revised ICLR 2027 evaluation stack

### E1: scientific-decision mechanism

Use a source-disjoint, expert-labeled benchmark of problem choice, hypothesis
refinement, diagnostic experiment choice, evidence interpretation, stop/pivot,
and claim calibration. This isolates the Taste contribution without requiring a
full paper for every case.

### E2: native objective-progress causal study

Use a source-disjoint, license-cleared subset of InnovatorBench as the first task
acquisition candidate, with InnoGym contingent on an exact public
implementation. Compare Full SciTaste with Native Base under one frozen capable
model, identical starting information, tools, repair policy, time/compute
budget, and failure accounting. The independent unit is a held-out task;
repeated stochastic runs are nested measurements rather than artificial sample
inflation. The formal task and repetition counts follow a non-formal pilot and
power analysis, not an arbitrary `N systems × M tasks × K seeds` matrix.

### E3: accepted-benchmark full lifecycle and external methods

Use MLR-Bench as the primary complete research-package scaffold. Compare
SciTaste Native, a direct tool agent, and at least two accepted methods only
after unchanged-core adapters preserve the same task meaning. Agent Laboratory,
AI-Researcher, and DeepScientist form the current high-relevance candidate pool;
license or adapter blockers remain genuine exclusions rather than reasons to
insert a pseudo-implementation. Matched-model and best-native configurations are
different estimands and must be reported separately. Blinded expert assessment
of the evidence-bearing package is primary; a validated model judge is
secondary.

### E4: executable experiment-chain integrity

Run a preregistered, source-stratified EXP-Bench subset large enough to estimate
design, implementation, execution, conclusion, and conjunctive success. The
subset size must be selected from a no-formal-data pilot and resource model. A
small convenient subset can be an adapter smoke test but not a paper result.
EXP-Bench remains diagnostic and cannot replace E2 or E3.

### E5: longitudinal self-development case

Report `scitaste-self-development` as a process case with versioned proposals,
defects found, decisions rejected, experiment plans revised, evidence admitted,
paper changes, human intervention, and costs. It demonstrates that the product
can manage a real evolving project. It is never included in E1--E4 headline
averages and never counted as an independent task.

## Fair comparison and anti-self-confirmation rules

1. Freeze held-out task manifests before any formal output is inspected.
2. Group tasks derived from the same source paper/repository in one split.
3. Pin external systems without changing their core methods. Adapter-only
   changes must be disclosed and tested for semantic equivalence.
4. Give systems equal starting information, tool permissions, resource budgets,
   repair policy, and evaluator access in the matched track.
5. Do not let SciTaste's self-development memory, paper draft, benchmark answer,
   hidden source paper, or previous formal outputs enter a held-out task.
6. Once an L2 formal block starts, an L0 improvement creates a new system and
   protocol version; it cannot replace earlier cells in place.
7. Keep framework-compatible matched runs separate from historical public-paper
   comparisons.
8. Count failed, invalid, fabricated, timed-out, over-budget, and human-rescued
   runs in the formal outcome.
9. Build the manuscript from admitted result artifacts; do not allow the writing
   stage to invent or reinterpret missing evidence.
10. Have experts blind-review the complete package, validate any model judge,
    and report agreement and adjudication.

## Model-capability versus framework-capability attribution

The recursive design also enables diagnosis, provided the system records the
right counterfactuals:

- If the same complete planning state and schema succeed with a stronger model
  but fail with the planned model, classify a **model-limit candidate**.
- If a model proposes a sound plan but SciTaste cannot represent, gate, execute,
  or admit it, classify a **framework limit**.
- If Native Base succeeds while Full SciTaste fails under the same model and
  task, classify a **framework-induced regression**.
- If all models lack required literature, task assets, tools, or evaluation
  context, classify a **context/tooling gap**, not a model failure.
- If execution fails because of memory, environment, storage, provider, or data
  availability, classify a **resource/environment failure**.
- If neither matched-model nor framework ablations identify the cause, record
  **unresolved** rather than assigning blame to model quality.

Consequently, failure to produce an ICLR-grade experimental plan is not by
default evidence that GLM-5.3-Flash, Qwen3-VL-2B, or any other model is too weak.
The present SciTaste planner must first demonstrate that it can represent
external benchmarks, baseline applicability, estimands, power, failure policy,
resource constraints, and temporal leakage. Missing representation or gates are
framework deficiencies even if a human can repair the prose afterward.

## Next no-run work

1. completed: create a tracked accepted-evaluation corpus revision with official
   repository/data pins, license hashes, capabilities, requirements, and
   use-specific feasibility evidence;
2. completed: implement a content-bound experiment-design state for E1--E5 and
   require admitted benchmark/system resources before design completion;
3. completed: add benchmark-fit, baseline-applicability, statistics, integrity,
   and resource critics whose outputs are content-bound proposals and whose
   schema cannot authorize execution;
4. completed: encode H1--H3, task-source roles, accepted method candidates,
   model-selection independence, pilot-based power, human review, and recursive
   self-development boundaries in a machine-checkable ICLR evidence program;
5. next: prepare separately reviewable acquisition proposals for the
   decision-case corpus and exact benchmark task subsets, plus unchanged-core
   adapter proposals; do not download, install, recruit, or execute yet;
6. after those proposals are accepted, present the exact model/data/runtime/cost
   conformance pilot for owner approval, then use its failure/variance evidence
   to freeze a new formal prelaunch manifest.
