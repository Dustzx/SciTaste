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

SciTaste should combine these forms, while keeping their estimands separate.
The primary full-lifecycle scaffold should be MLR-Bench; EXP-Bench should test
the experiment-design-to-conclusion middle of the pipeline; a small bounded
frontier-progress study is a stretch track rather than a substitute for either.

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

## What accepted work actually evaluates

| Work | Accepted venue | Evaluation unit and scale | Compared against | Principal evidence | Boundary |
|---|---|---|---|---|---|
| [MLR-Bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html) | NeurIPS 2025 D&B | 201 open-ended ML tasks; idea, proposal, experiment, writing, and end-to-end stages | six frontier LMs, coding agents, its MLR-Agent, and an AI Scientist-v2 comparison | stage rubrics, final-paper review, expert validation, and invalid/fabricated-result auditing | broad early-stage coverage but only a smaller task subset is practical for executable end-to-end evaluation |
| [AI-Researcher](https://proceedings.neurips.cc/paper_files/paper/2025/hash/0d904d300a105809a2114d727851e759-Abstract-Conference.html) | NeurIPS 2025 | Scientist-Bench over target AI papers, with guided and open-ended innovation settings | human target papers and model/backbone variants | implementation completion/correctness and blinded paper-level novelty, rigor, and validation judgments | broad direct comparison with other autonomous-research frameworks is not its main design |
| CycleResearcher | ICLR 2025 | generated research papers and review/research corpora | human papers, AI Scientist, training and search ablations | reviewer-score prediction, simulated acceptance, expert paper judgments | training papers can contain fabricated experimental results; it is not evidence of executable end-to-end research |
| [DeepScientist](https://proceedings.iclr.cc/paper_files/paper/2026/hash/4f64494ecc3442f1c9261baa036378bc-Abstract-Conference.html) | ICLR 2026 | about 5,000 ideas and 1,100 experimental validations on three frontier AI tasks | human 2025 state of the art, system variants, and publicly available AI-scientist papers | real external scores, progressive discovery traces, generated-paper review, scaling, and failure analysis | strongest frontier-progress precedent but uses more than 20,000 GPU hours and only three target tasks |
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
   content-addressed projects for held-out MLR-Bench, EXP-Bench, and optional
   frontier tasks. SciTaste Native and pinned baselines each traverse their real
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

### E2: accepted-benchmark full lifecycle

Use MLR-Bench as the primary external scaffold:

- run idea/proposal assessment over all feasible official tasks or a frozen,
  powered, source-stratified subset no smaller than 120 cases;
- use the official executable end-to-end subset as the starting task population
  rather than inventing 12 arbitrary tasks;
- compare SciTaste Native, MLR-Agent, AI Scientist-v2, and a direct
  execution-capable agent when their official licenses and adapters pass;
- include AutoResearchClaw as another real system only if it can consume the
  same task package and expose comparable evidence without altering its core;
- use matched models and resource ceilings as the primary analysis and each
  framework's official configuration only as a separate sensitivity analysis;
- make blinded expert judgment of the complete evidence-bearing package primary,
  with MLR-Judge as a calibrated secondary measure.

The final system/task/seed count must follow an adapter feasibility study and a
pilot-based power analysis. As a planning reference, four systems on ten tasks
with three seeds yield 120 independent task-system-seed trajectories; this is a
reference count, not launch authorization.

### E3: executable experiment-chain integrity

Run a preregistered, source-stratified EXP-Bench subset large enough to estimate
design, implementation, execution, conclusion, and conjunctive success. The
subset size must be selected from a no-formal-data pilot and resource model. A
small convenient subset can be an adapter smoke test but not a paper result.

### E4: bounded frontier-progress cases

Use two or three open-ended tasks with external continuous objectives and human
or strong public baselines to test whether better decisions translate into
actual scientific progress. This is explicitly a low-n, high-cost case series,
not the main population estimate. The 8xRTX 3090 host may support it only after
the exact model, data, storage, runtime, and stop manifest receives approval.

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

1. create a new immutable accepted-evaluation corpus revision with licenses,
   hashes, task assets, and official repository commits;
2. implement an experiment-design state that represents E1--E5, their
   estimands, baselines, statistics, resources, and evidence dependencies;
3. add benchmark-fit, baseline-applicability, statistics, integrity, and
   resource critics whose outputs are proposals rather than auto-accepted plans;
4. perform read-only adapter and dataset feasibility audits for MLR-Bench,
   EXP-Bench, AI Scientist-v2, MLR-Agent, and AutoResearchClaw;
5. have SciTaste generate the concrete prelaunch proposal inside
   `scitaste-self-development`, then require human approval before any download,
   model call, human recruitment, API spend, or GPU run.
