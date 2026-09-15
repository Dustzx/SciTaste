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
task-model roles. Its sixteen candidates span fourteen model families, including
models for which access is not configured. This is intentional: access state is
recorded but cannot select or exclude a scientifically required model.

The closest released baselines have narrow roles. `SciJudge-4B-2605` and
`SciJudge-30B-2605` are external impact-preference baselines;
`SciThinker-4B` and `SciThinker-30B` are external ideation baselines. Each is
paired with its exact Qwen3 architecture/scale base. The 4B pairs provide the
minimum reproduction, while the 30B MoE pairs test whether the Taste-training
effect survives the stronger scale reported by the direct neighbor. This
choice precedes local-resource inspection: the 30B checkpoints remain in the
candidate universe even though they are not currently acquired. None is
evidence of a complete lifecycle policy, and SciJudge's citation-impact
objective cannot make it a full-paper peer reviewer. Conversely, the MLRC
`LocPointTransformer` is owned by the benchmark task recipe and cannot act as a
scientific agent.

The no-run direct-neighbor study extension is
[`iclr2027_scitaste_direct_neighbor_extension_v1.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_direct_neighbor_extension_v1.yaml),
SHA-256 `fdf51ec564d3bb0a6ea9160b4299cb2e04dbc5ff787b792b16711a7b00a31ba0`.
It reports 4B native-task reproduction, conditional 30B scale-by-training
robustness, lifecycle transfer, SciTaste mechanisms, and downstream objective
progress as separate estimands. Aggregating those heterogeneous tasks into one
score is forbidden.

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

## SciTaste policy versus research workload training

“Training-free” applies first to the current SciTaste method: the frozen
research-agent weights are not updated. SciTaste instead updates grounded Taste
memory, delayed outcome credit, routing statistics, and abstention state. It
does **not** imply that every scientific experiment run by SciTaste is
training-free.

The workload contract is independently two-stratum and is frozen in
[`iclr2027_scitaste_workload_paradigms_v1.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_workload_paradigms_v1.yaml),
SHA-256 `60fe5de9e3554e685c18d15d66d53d1648e96ab8b4969bfb29ff304a9913f13b`:

- **T0 training-free research** executes a complete project by changing
  analysis, code, prompts, retrieval, or algorithms while keeping task-model
  weights fixed. It still requires a hidden objective endpoint, evidence,
  paper, review, revision, and final disposition.
- **T1 training-based research** trains or fine-tunes a benchmark-owned task
  model and retains learning curves, failures, and resource telemetry. The
  current first route is MLRC Perception with its `LocPointTransformer`.

Both T0 and T1 compare `scitaste-native` with `native-base` under the same
research-agent model and budget. Their primary results are reported separately.
The direct Scientific Judge/Thinker training comparison is a third, external
mechanism-reproduction question; it is not one of these SciTaste workload
strata. A learned-weight SciTaste policy may be studied later, but it is not
required by the current title or primary causal claim.

## Main evidence program

| Track | Question | Data/benchmark | Model and compute shape |
|---|---|---|---|
| E1 | Which Scientific Taste mechanisms improve decisions? | source-disjoint SciTasteBench D-layer natural decisions | training-free SciTaste policy; one frozen strong agent per contrast, two independent judges; no GPU required unless the local robustness stratum is run |
| E2 | Does SciTaste improve objective training-based research progress? | MLRC-Bench primary, another scorer-owned route only after qualification | same scientific agent for Native and Native Base; benchmark task model on 8×3090; hidden scorer owns the endpoint |
| E3 | Can SciTaste complete Idea to reviewed and revised paper better than admitted AutoResearch methods? | MLR-Bench plus a qualified T0 task | matched-model primary and native-best secondary reported separately; at least one complete training-free and one training-based research workload, with actual task-dependent API/GPU work and paper-review loop |
| E4 | Where does the executable research chain fail? | EXP-Bench | smallest Native/Base diagnostic pair spanning T0/T1 where qualified and covering hypothesis through conclusion |

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
SHA-256 `35d40ace350bf8ab5e7c7e85491209b08e7dcfcf2ae4767b91e0106bd0d92357`.
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

The two released 4B direct-neighbor checkpoints are now fixed-revision,
full-tree hashed, and attached to the self-development project resource set.
One task-excluded B0 run per checkpoint loaded successfully on separate RTX
3090s under Python 3.12: Scientific Judge returned its required answer schema in
15.49 seconds at 8,223,046,144 peak allocated bytes, and Scientific Thinker
returned its required title/abstract schema in 25.87 seconds at 8,251,090,944
bytes. Both receipts record zero formal dataset rows. These observations prove
only load/generation compatibility; they do not establish impact accuracy,
ideation quality, lifecycle transfer, or AutoResearch improvement. The exact
4B Qwen bases are being acquired next so any N1/N2 difference can be attributed
to the neighbor's Taste training rather than an unmatched backbone.
