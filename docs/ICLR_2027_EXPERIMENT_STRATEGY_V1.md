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
remote inventory update feasibility evidence, not H1--H3.

## What the paper must establish

The paper is a method paper about explicit Scientific Taste, not a benchmark
paper and not a report on how much infrastructure SciTaste contains. Its central
claim has four separable parts:

1. high-quality references can be transformed into transferable decision
   experience rather than copied as retrieved text;
2. the resulting experience changes scientific decisions for the right reason,
   rather than because the model received more tokens or generally good prose;
3. those decisions improve held-out executable research outcomes under matched
   model, task, tool, and budget conditions;
4. the complete SciTaste system remains competitive with real autonomous-
   research systems under their usable configurations.

The first three are title-critical. The fourth establishes ecological relevance
but cannot identify a causal Taste effect when systems use different models.

## Confirmatory hypotheses

### H1: abstraction beyond retrieval

Given the same source papers, source-quality tier, retrieval query, and context
budget, a compact source-faithful Taste abstraction improves expert-aligned
scientific action selection over raw excerpt RAG.

Primary contrast: `abstracted-matched-taste` versus `raw-source-rag`.

This contrast prevents the contribution from collapsing into “retrieve good
papers and put them in context.” Retrieval is transport; the treatment is the
source-faithful transformation into a decision context, alternatives, principle,
justification, and outcome boundary.

### H2: contextual relevance rather than generic inspiration

With provenance tier, curation tier, case count, token budget, stage, role, and
outcome-information availability matched, task-relevant Taste experience
improves decisions over source-disjoint mismatched Taste.

Primary contrast: `abstracted-matched-taste` versus
`abstracted-mismatched-taste`.

### H3: end-to-end research progress

Under one frozen frontier backbone and identical executable resources, Full
SciTaste improves task-normalized held-out objective progress over Native Base.

Primary contrast: `full-scitaste` versus `native-base`. Every valid failed run
remains an intention-to-run outcome at the preregistered task floor.

No title claim is admitted unless all three hypotheses have complete evidence.
H1 and H2 are primarily powered at the decision level; H3 is powered over
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
2. raw-source RAG;
3. abstracted matched Taste;
4. abstracted mismatched Taste;
5. Full SciTaste with critics and persistent state.

All reference-bearing conditions use matched context budgets. Automated judges
are diagnostics; expert action preference and calibration are primary.

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

The current candidates are [DeepSeek V4 Flash](https://api-docs.deepseek.com/quick_start/pricing/)
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

The source-to-Taste compiler, corpus parity checks, immutable failure evidence,
and condition binding already cover items 2--4 at the software-contract level.
They still lack real source/review bytes and empirical execution.

The following are not prerequisites for the first scientific pilot: additional
generic unit-test coverage beyond the current stable level, more UI polish,
full hashing of every discovered model, a general multi-project scheduler, or a
camera-ready paper layout. Work on those areas must not delay the evidence path.

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
