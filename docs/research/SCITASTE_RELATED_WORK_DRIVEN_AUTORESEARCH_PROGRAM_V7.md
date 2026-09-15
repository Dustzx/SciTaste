# SciTaste related-work-driven AutoResearch program v7

Status: **current project authority; B0 role panel incomplete; no formal E1--E4
result yet**.

The machine-readable authority is
[`iclr2027_scitaste_capability_driven_autoresearch_program_v7.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_capability_driven_autoresearch_program_v7.yaml).
The self-development project binds an immutable copy of that program and the
v2 resource inventory under run
`scitaste-iclr2027-capability-driven-autoresearch-program-v7`. Planning does not
itself authorize a benchmark, GPU, download, or provider call.

## Selection order

Model availability no longer defines the experiment. The enforced order is:

1. freeze the current SciTaste Idea and its claimed causal mechanism;
2. inspect recent neighboring AutoResearch work and the selected benchmark's
   native experimental conventions;
3. derive the model classes and role separation needed for a comparable test;
4. construct a candidate universe that may include models absent from every
   current machine;
5. run task-excluded capability, identity, license, reliability, and cost gates;
6. only then prefer an already available API or checkpoint when scientifically
   equivalent.

The executable candidate authority is now
[`scitaste_iclr27_related_work_candidates_v1.yaml`](../../configs/evaluation/model_selection/scitaste_iclr27_related_work_candidates_v1.yaml).
It starts with the two direct 2026 Scientific Taste neighbors before using the
broader AutoResearch literature to assign research, coding, figure, review, and
task-model roles. Its ten candidates span eight model families, including
models for which access is not configured. This is intentional: access state is
recorded but cannot select or exclude a scientifically required model.

The closest released baselines have narrow roles. `SciJudge-4B-2605` is an
external impact-preference baseline and `SciThinker-4B` is an external ideation
baseline. Neither is evidence of a complete lifecycle policy, and SciJudge's
citation-impact objective cannot make it a full-paper peer reviewer. Conversely,
the MLRC `LocPointTransformer` is owned by the benchmark task recipe and cannot
act as a scientific agent.

The program records MLR-Bench, AI Scientist-v2, SciNav, DeepScientist,
AutoResearchClaw, SAGE/MHFA, and SGHA as current design anchors. Their combined
implication is not one preferred model name: it is stagewise plus end-to-end
evaluation, actual execution, matched-model method contrasts, cross-model
generalization, independent generation/judgment roles, progressive experiment
search, grounded recovery, and one local open-weight robustness stratum.

Qwen3-VL-2B and Qwen3-VL-4B are retained only as optional efficiency or
capability floors. The primary candidate set can add current frontier APIs,
8B--14B open models, specialist VLMs, scientific embedding models, and
task-specific trainable models. The owner's standing download authority permits
each newly justified resource up to 10 GiB; larger items require a new notice.

## Three different meanings of “model”

| Plane | Function | Selection rule |
|---|---|---|
| Scientific agent | literature, Idea, experiment design, code, evidence, writing | recent-work comparability plus role-specific task-excluded conformance |
| Review panel | two independent reviews and conditional adjudication | identity-distinct, generator-disjoint calibration; never self-judge |
| Benchmark task model | the model actually trained or evaluated inside an experiment | benchmark/task recipe, not the scientific-agent checkpoint |

For example, the current E2 Perception task trains the benchmark-owned
`LocPointTransformer` from deterministic random initialization. Qwen3-VL is not
that task model. A hosted research agent may design and edit the method while
the 8×RTX 3090 lane trains and evaluates the task model. E3 and E4 select their
task models separately for each frozen benchmark task.

## Complete automated-research trajectory

Every formal E3 trajectory must produce actual, content-hashed artifacts for:

```text
task and literature acquisition
  -> source-quality admission and grounded Taste abstraction
  -> ideas, hypotheses, selection or abstention
  -> experiment preregistration, model/resource/budget freeze
  -> implementation, bounded development repair, actual execution
  -> candidate freeze, isolated hidden scoring
  -> evidence and contradiction admission
  -> claim-linked paper and figures
  -> two independent AI reviews
  -> distinct-AI adjudication on disagreement
  -> review-routed re-experiment, reanalysis, or rewrite
  -> final dual review and immutable package
```

A paper-only run, simulated metrics, an unlogged manual rescue, or a run without
review-driven revision cannot be marked complete. Formal review may return work
to experiment planning, execution, evidence analysis, or paper assembly. Hidden
scores cannot update the same formal policy split.

## Main evidence program

| Track | Question | Data/benchmark | Model and compute shape |
|---|---|---|---|
| E1 | Which Scientific Taste mechanisms improve decisions? | source-disjoint SciTasteBench natural decisions | parameter-training-free; one frozen strong agent per contrast, two independent judges; no GPU required unless the local robustness stratum is run |
| E2 | Does SciTaste improve objective research progress? | MLRC-Bench primary, another scorer-owned route only after qualification | same scientific agent for Native and Native Base; benchmark task model on 8×3090; hidden scorer owns the endpoint |
| E3 | Can SciTaste complete Idea to reviewed and revised paper better than admitted AutoResearch methods? | MLR-Bench | matched-model primary and native-best secondary reported separately; actual task-dependent API/GPU work and complete paper-review loop |
| E4 | Where does the executable research chain fail? | EXP-Bench | smallest Native/Base diagnostic pair covering hypothesis through conclusion |

B0 exercises roles and the complete interface graph only on excluded development
content. B1 runs the smallest complete formal trajectories needed to cover the
four questions. B2 expands only contrasts whose B1 variance, failure rate, and
clustered power require it; no decorative model × system × task × seed grid is
permitted.

## Current evidence and next execution

The latest B0 role campaign executed 14 real task-excluded requests. Research
and code with GLM-5.3-Flash each passed 4/4 cases; the local Qwen3-VL-8B task
executor passed 2/2; local MiniLM retrieval passed 2/2. Qwen3.8-Max produced one
correct and one incorrect blind judgment, so it failed the frozen reliability
threshold and is not selected as the paper's reviewer panel. This failure is
retained rather than hidden or repaired by lowering the gate.

The immediate critical path is therefore:

1. refresh independent judge candidates from the related-work-derived universe
   and qualify two generator-disjoint reviewers plus one adjudicator;
2. execute one development-only full trajectory through paper, review, return,
   revision, and final disposition;
3. freeze and disclose the exact E2 Native/Base manifest: MLRC bytes,
   `LocPointTransformer` recipe, scientific-agent identity, two GPUs per arm,
   16 aggregate GPU-hours, API ceiling, scorer firewall, and zero formal rescue;
4. after explicit launch approval, run the paired E2 objective experiment;
5. run the smallest complete E1/E3/E4 block and scale only effects that need
   power.

The current no-run E2 handoff is
[`mlrc_perception_native_pair_e2_v2.yaml`](../../configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v2.yaml),
SHA-256 `98741378de7a809a8e2d19d67f5e3edc5d57f335f7243ddda54c4331f2fc90e4`.
Its eleven static scientific and execution boundaries pass, including exact
bindings to accepted Idea revision `outcome-calibrated-scientific-taste-policy-v2`
and the related-work candidate catalog. The E2 pool now includes unconfigured
GPT and Gemini candidates alongside current GLM, DeepSeek, Qwen API, and open
9B candidates, so local inventory cannot silently define the experiment.
It is deliberately not
launchable while the independent judge panel, development-only full-loop receipt,
actual GPU baseline, final role/budget freeze, and owner approval remain open.

The remote fixed-revision `Qwen/Qwen3.5-9B` candidate is now statically complete:
16 files, four indexed shards, 15,664,539,861 bytes, aggregate checkpoint digest
`eb33159890e4493dd7fa36b611020576535ecbcf776bcfd3f540f92914f63884`.
Only the previously missing 3,345,623,595 bytes were downloaded. No model load,
generation, GPU job, or benchmark run occurred. This changes feasibility, not
selection; the checkpoint still needs source-disjoint role conformance and
cannot replace the frontier matched-model stratum.
