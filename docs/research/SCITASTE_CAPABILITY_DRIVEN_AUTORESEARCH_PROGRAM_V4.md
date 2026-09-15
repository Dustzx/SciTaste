# SciTaste capability-driven AutoResearch program v4

Status: **historical program; superseded by related-work-driven v7**.

Current authority is
[`SCITASTE_RELATED_WORK_DRIVEN_AUTORESEARCH_PROGRAM_V7.md`](SCITASTE_RELATED_WORK_DRIVEN_AUTORESEARCH_PROGRAM_V7.md).
V4 is retained to reproduce the transition away from checkpoint-driven planning.

The machine-readable authority is
[`iclr2027_scitaste_capability_driven_autoresearch_program_v4.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_capability_driven_autoresearch_program_v4.yaml).
It supersedes v3 for every new run while preserving v3 and the earlier
Qwen3-VL-2B prepilot as history. It does not launch an API, GPU, download, or
external system by itself.

## What changed

The experiment is now selected by the scientific task and required capability,
not by the checkpoint that happens to be easiest to load. Qwen3-VL-2B is one
local resource and may serve only as a cheap lower bound or software-compatibility
slice. It is not the primary research agent, code agent, judge, task-training
backbone, or headline model by default.

Every role is selected independently on source-disjoint conformance tasks:

| Role | Minimum capability | Current candidates, not selections |
|---|---|---|
| Research agent | scientific reasoning, long context, tool use, grounded citation, structured output | DeepSeek V4 Flash, GLM-5.3-Flash, Qwen3-VL-8B, Qwen3.5-4B, and qualifying downloads |
| Code agent | repository editing, executable code, tools, bounded repair | DeepSeek V4 Flash, GLM-5.3-Flash, Qwen3-VL-8B, Qwen3.5-4B, and qualifying downloads |
| Judge | generator-independent rubric following and calibration | a different qualified API/local identity from the generator |
| Embedding | scientific retrieval quality and stable batch execution | MiniLM as a baseline and a task-fit scientific embedding model if needed |
| Task model | benchmark fit, reproducible load, license clearance, 24 GB or distributed feasibility | Qwen3-VL-4B/8B, InternVL3.5-4B, LLaVA-OneVision-4B, Qwen3.5-4B, task-specific models, and qualifying downloads |

The inventory is therefore a floor, not a ceiling. A missing capability triggers
candidate expansion. The owner has authorized individual downloads up to 10 GiB;
the exact resource is still named and entered into the run manifest before use.
Larger resources require a new notice. Existing local assets receive a cost and
reproducibility preference only after they meet the same scientific gate.

## One paper, four evidence jobs

The main paper remains one method paper. SciTasteBench is its mechanism
instrument, while external benchmarks supply ecological tasks and objective
endpoints:

| Study | What it isolates | Required endpoint |
|---|---|---|
| E1 / SciTasteBench | source quality, Taste abstraction, contextual match, autonomous selection, reviewed delayed credit | blinded, independent dual-AI decision quality and calibration; nonhuman mechanism evidence |
| E2 / MLRC-Bench (or qualified MLE-Bench route) | whether Scientific Taste improves actual research progress | paired hidden objective score for SciTaste Native versus the same native executor with Taste removed |
| E3 / MLR-Bench | idea-to-reviewed-paper ability versus admitted AutoResearch methods | evidence-valid complete package, paper review, revision, and final disposition |
| E4 / EXP-Bench | where experiment generation succeeds or fails | stagewise and conjunctive hypothesis-to-conclusion success |

E2 is title-critical. E1 cannot by itself support “improving autonomous
research,” because an AI preference endpoint is not an objective research
outcome. E3 verifies whole-lifecycle usefulness and external method comparison;
E4 diagnoses the experiment subsystem. Benchmark scores and method effects are
reported separately.

## What “complete automated research” means

A SciTaste trajectory is not complete when it merely produces a draft. It must
cross the following evidence-bearing loop:

```text
goal/task intake
  → literature and high-quality reference admission
  → grounded Taste abstraction
  → candidate ideas/hypotheses
  → Taste-guided selection or abstention
  → preregistered experiment and resource allocation
  → implementation, bounded repair, and execution
  → candidate freeze and isolated hidden score
  → evidence/contradiction admission
  → claim-linked paper
  → two independent AI reviews
  → third-AI adjudication on disagreement
  → review-driven revision
  → final review and immutable package
```

Final review may send the trajectory back to experiment planning, execution,
evidence analysis, or paper assembly. The returned work must generate a new
content-addressed artifact chain. Formal hidden scores cannot update the policy
inside the same split, and the formal route has no unlogged human rescue.

## Training-free and GPU routes

Scientific Taste itself is parameter-training-free: the frozen research model
does not receive gradient updates. It can update only source-grounded episodic
memory, action-specific delayed credit, routing statistics, and abstention state
using reviewed outcomes from disjoint source groups.

GPU work measures the downstream research that the agent designs and executes.
It can train/evaluate task models, run benchmark workloads, or serve a qualified
local agent, with each cost separated. The local RTX 3090 is the development
lane; the remote 8×RTX 3090 host is the formal/scale-out lane. Neither lane nor a
checkpoint chooses the research question.

## Minimal execution sequence before the deadline

1. **B0:** complete the role-conformance bindings and exercise every lifecycle
   interface, including hidden-score isolation and review returning work to an
   earlier phase. B0 is engineering evidence only.
2. **B1:** run the smallest complete, source-disjoint formal block containing
   the E1 causal contrasts, one E2 hidden-score pair, one complete E3 route, E4
   diagnostics, and actual review-driven revision.
3. **B2:** expand only effects that require statistical power or robustness,
   using B1 variance, failure rate, and cost. Do not create a decorative
   model × system × task × seed grid.

The ICLR 2027 abstract deadline is September 18, 2026 AoE and the paper deadline
is September 25, 2026 AoE. Until E2 supplies admitted paired hidden-objective
evidence, the working title remains a target rather than an authorized result
claim. Optional UI and broad regression work do not precede B1.

## Immediate executable boundary

The next step is not another model-specific preflight. It is:

1. finish the content-addressed B0 role bindings;
2. select roles from task-excluded receipts;
3. bind the first MLRC objective task, exact data bytes, executor model(s),
   environment, GPU/API ceiling, hidden scorer, and SciTaste Native/Base pair;
4. disclose that exact manifest before consuming GPU/API resources;
5. execute and retain success, failure, cost, review, and revision artifacts.

The historical `native-taste-causal-prepilot` in
`iclr2027_self_development_v1.yaml` remains reproducibility history only. New
execution must use v4 and cannot inherit its Qwen3-VL-2B selection.
