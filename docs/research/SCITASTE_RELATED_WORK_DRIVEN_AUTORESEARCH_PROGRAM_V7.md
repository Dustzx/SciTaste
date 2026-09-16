# SciTaste related-work-driven AutoResearch program v7 to v8 handoff

Status: **v8 is the current project authority; one-shot B0 role selection complete;
controller at development execution; no formal E1--E4 result yet**.

The machine-readable authority is
[`iclr2027_scitaste_capability_driven_autoresearch_program_v8.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_capability_driven_autoresearch_program_v8.yaml).
The self-development project binds an immutable copy of that program and the
v2 resource inventory under run
`scitaste-iclr2027-capability-driven-autoresearch-program-v8`. Planning does not
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
SHA-256 `d12795a6f1b8ef8d7fd4129900b3541f7a372c39818cb191188f3e20d15c2879`.
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

SciTaste is one system, not separate training and training-free products. In
this program, **training-free** and **training-based** describe the scientific
workload that SciTaste actually executes. The current SciTaste implementation
keeps the research-agent backbone frozen while updating grounded Taste memory,
delayed outcome credit, routing statistics, and abstention state. An optional
neural learned-Taste component is a secondary mechanism study, not another
product and not required for the headline claim.

The workload contract is independently two-stratum and is frozen in
[`iclr2027_scitaste_workload_paradigms_v1.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_workload_paradigms_v1.yaml),
SHA-256 `8db7b68b339a10b7a82b9c1e1a30512baf7f850f23cadb14fed4855cee79f935`:

- **T0 training-free research** executes a complete project by changing
  analysis, code, prompts, retrieval, or algorithms while keeping task-model
  weights fixed. It still requires a hidden objective endpoint, evidence,
  paper, review, revision, and final disposition.
- **T1 training-based research** trains or fine-tunes a benchmark-owned task
  model and retains learning curves, failures, and resource telemetry. The
  current first route is MLRC Perception with its `LocPointTransformer`.

Both T0 and T1 compare `scitaste-native` with `native-base` under the same
research-agent model and budget. Their primary results are reported separately.
This workload axis is orthogonal to SciTaste's adaptation axis: **A0** is the
headline nonparametric, outcome-updated Taste policy, while **A1** is an optional
learned Taste component evaluated only on selected tasks if justified. T1 does
not imply A1, and T0 does not define a separate A0 product. The primary paper
therefore tests one SciTaste system in T0 and T1 under A0; it does not require a
decorative T0/T1 × A0/A1 full grid.

The direct Scientific Judge/Thinker training comparison is a third, external
mechanism-reproduction question; it is not one of these SciTaste workload
strata. A learned-weight SciTaste policy may be studied later, but it is not
required by the current title or primary causal claim.

## Main evidence program

| Track | Question | Data/benchmark | Model and compute shape |
|---|---|---|---|
| E1 | Which Scientific Taste mechanisms improve decisions? | source-disjoint SciTasteBench D-layer natural decisions | frozen-backbone, outcome-updated SciTaste policy; one frozen strong agent per contrast, two independent judges; no GPU required unless the local robustness stratum is run |
| E2 | Does SciTaste improve objective training-based research progress? | MLRC-Bench primary, another scorer-owned route only after qualification | same scientific agent for Native and Native Base; benchmark task model on 8×3090; hidden scorer owns the endpoint |
| E3 | Can SciTaste complete Idea to reviewed and revised paper better than admitted AutoResearch methods? | MLR-Bench plus a qualified T0 task | matched-model primary and native-best secondary reported separately; at least one complete training-free and one training-based research workload, with actual task-dependent API/GPU work and paper-review loop |
| E4 | Where does the executable research chain fail? | EXP-Bench | smallest Native/Base diagnostic pair spanning T0/T1 where qualified and covering hypothesis through conclusion |

B0 exercises roles and the complete interface graph only on excluded development
content. B1 runs the smallest complete formal trajectories needed to cover the
four questions. B2 expands only contrasts whose B1 variance, failure rate, and
clustered power require it; no decorative model × system × task × seed grid is
permitted.

## Current evidence and next execution

The independent-judge successor B0 executed 14 real task-excluded requests
without selective reruns. Qwen3.8-Max passed 4/4 research and 4/4 code cases;
GLM-5.3-Flash passed 2/2 blind judge repetitions and is identity-distinct from
the generator; local MiniLM retrieval and Qwen3-VL-8B task execution each passed
2/2. The API portion used 12,738 input and 6,950 output tokens for USD 0.060684.
The incomplete predecessor, where Qwen3.8-Max failed judge reproducibility, is
retained and explicitly superseded rather than repaired by lowering a gate.
This selects execution roles only; it does not by itself qualify the two-model
paper-review panel or supply an effectiveness result.

Two source-disjoint T0 development trajectories now exercise signed lifecycle
learning. NewtonBench Gravity v7 accepted an evidence-backed STOP before scorer
access and received `symbolic_accuracy=1.0`. Fourier v8 used 21 experiments over
five turns and produced a numerically close law, but the frozen exact-symbolic
endpoint returned `symbolic_accuracy=0.0`; its terminal STOP therefore carries
harmful credit. For each trajectory, Qwen3-VL-4B and Qwen3-VL-8B received the
same compact, hash-bound packet and independently admitted the causal-credit
claim; separate outcome-blind panels assigned `scientific-value`. These are A0
development learning units, not Native/Base treatment effects or formal rows.
Corpus v4 seals four source groups and policy v6 trains on three eligible
episodes with `signed-factorized-beta-pairwise-v2`. The shared STOP feature now
has 0.5 win and 0.5 loss rather than two false wins. Its support 1.0 remains
below the frozen threshold 3, so the policy correctly abstains.

The v7 controller replayed acquisition, quarantine, split/firewall, and actual
role-selection evidence, then prospectively selected the accepted Idea from
three alternatives and froze H0--H4 plus E2 v3. Before launch, inspection found
that its campaign command named E2 v3 while result admission named E2 v2. V7 is
therefore retained as a zero-execution failed plan. V8 replayed the same
content-hashed evidence against E2 v4 and again reached
`development-execution` without launching a benchmark cell.

The immediate critical path is therefore:

1. approve and execute the exact two-arm E2 development block disclosed by v4;
2. carry that trajectory through paper, review, return,
   revision, and final disposition;
3. before its paper-review phase, qualify a second generator-disjoint reviewer
   and a distinct adjudicator without reopening the execution-role selection;
4. after the development trajectory validates the loop, request separate B1
   authority for the 16-GPU-hour paired hidden-objective experiment;
5. run the smallest complete E1/E3/E4 block and scale only effects that need
   power.

The current no-run E2 handoff is
[`mlrc_perception_native_pair_e2_v4.yaml`](../../configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v4.yaml),
SHA-256 `03dccd1adcf803c804f28b8b67abc97f3a9c6335f10a037780649d6341514c9e`.
Its eleven static scientific and execution boundaries pass, including exact
bindings to accepted Idea revision `outcome-calibrated-scientific-taste-policy-v2`
and the related-work candidate catalog. V4 additionally binds the actual B0
selection file and verifies Qwen3.8-Max for both agent roles plus independent
GLM-5.3-Flash judging. It closes campaign-to-admission identity and freezes, per
block, eight Qwen3.8-Max calls, 16,000 input and 8,192 output tokens per call,
193,536 total tokens, USD 1, and zero retries. The broader pool still includes unconfigured GPT and
Gemini candidates alongside current GLM, DeepSeek, Qwen API, and open 9B
candidates, so local inventory cannot silently define the experiment. It is
deliberately not launchable while exact owner approval, the development-only
two-arm/full-loop receipt, and actual GPU baseline remain open.

The remote fixed-revision `Qwen/Qwen3.5-9B` candidate is now statically complete:
16 files, four indexed shards, 15,664,539,861 bytes, aggregate checkpoint digest
`eb33159890e4493dd7fa36b611020576535ecbcf776bcfd3f540f92914f63884`.
Only the previously missing 3,345,623,595 bytes were downloaded. No model load,
generation, GPU job, or benchmark run occurred. This changes feasibility, not
selection; the checkpoint still needs source-disjoint role conformance and
cannot replace the frontier matched-model stratum.

The two released 4B direct-neighbor checkpoints and their exact Qwen3 bases are
now fixed-revision, full-tree hashed, and attached to the self-development
project resource set. All four completed task-excluded load/final-channel B0 on
remote RTX 3090s under Python 3.12 and read zero formal dataset rows. The Qwen3
Thinking base retained its 1024-token truncation and completed only with the
role-specific 2048-token envelope. These observations prove only
load/generation compatibility; they do not establish impact accuracy, ideation
quality, lifecycle transfer, or AutoResearch improvement.
