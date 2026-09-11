# SciTaste experiment decision brief v1

Status: **awaiting data/resource admission; no experiment execution is
authorized**. This brief separates the first API and GPU blocks that can produce
paper evidence. It does not treat a model review of the manuscript as an
experiment, and it does not pool provider inference with local accelerator use.

## GPU block — Track A scientific-taste mechanism

| Binding | Frozen proposal |
|---|---|
| Question | Does matched, abstracted scientific Taste improve expert-aligned decisions beyond Base, factual Knowledge, critics, and mismatched Taste? |
| Model | `Qwen/Qwen3-VL-2B-Instruct`, local tree SHA-256 `8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1` |
| Data | SciTasteBench v2: at least 120 natural, source-group-disjoint decisions, at least three domains, all six decision families, at least two human labels per case |
| Conditions | Base, Knowledge, matched Taste, critics, Full SciTaste, mismatched-Taste placebo |
| Counterbalance | declared and reversed candidate order |
| Calls | 1,440 decisions at the 120-case floor; 120 experimental units |
| Hardware | up to 8 × RTX 3090, one resident worker per GPU, no tensor parallelism |
| Ceiling | 16 allocated GPU-hours, 100 GiB output/storage ceiling |
| Primary metric | paired expert-aligned action selection, Full SciTaste versus Base |
| Negative control | matched Taste versus source-disjoint mismatched Taste |
| Current status | blocked: the candidate source list exists, but no source bytes, natural cases, or human labels have been acquired |

The curation/compiler contract is
[`protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md`](protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md).
The metadata-only source screen is
[`data/scitastebench_v2_source_candidates_v1.yaml`](data/scitastebench_v2_source_candidates_v1.yaml).

## API block — Track B end-to-end external systems

| Binding | Frozen proposal |
|---|---|
| Question | Under matched starting briefs, tools, model, repair rules, and budgets, are complete SciTaste Native packages preferred by blinded experts? |
| Provider/model | DeepSeek `deepseek-v4-flash`, documented release `DeepSeek-V4-Flash-0731`; Zhipu `glm-5.3-flash` requires a separate proposal and is not a silent fallback |
| Data | the ten candidate ICLR-2025 MLR-Bench workshop briefs; exact task assets remain unacquired and unadmitted |
| Systems | SciTaste Native, Direct Agent, MLR-Agent, Agent Laboratory, TinyScientist candidate |
| Matrix | 5 systems × 10 tasks × 2 seeds = 100 trajectories |
| API ceiling | 1,500 requests, 15M total tokens, USD 20 for the DeepSeek pilot |
| Human ceiling | 30 reviewer-hours; at least two conflict-checked blinded reviewers per comparison |
| Primary metric | task-averaged blinded expert package preference for scientific value and evidence validity |
| Secondary metrics | unsupported claims, valid/failed experiments, pivot/stop quality, reproducibility, wall time, tokens, cost, interventions |
| Current status | blocked: accepted external adapters, per-task assets/licenses, held-out audit, and human reviewers are not ready |

The registered immutable proposal is
`outputs/projects/scitaste-self-development/evaluations/deepseek-v4-package-prepilot-v5/`.
Its proposal SHA-256 is
`8a9f3002c871f723bf7430a7432ecf428999ad83c19d13546f5030d4a624f6ff`.
That proposal is tied to an older executable commit and must be regenerated from
a clean final implementation before approval; it must not be edited in place.

## Launch order

1. Approve only a bounded metadata/source acquisition slice; do not start a
   model or GPU.
2. Curate and human-label a source-disjoint natural pilot, then freeze its power
   analysis before opening the formal Track A split.
3. Run the local Qwen block after checkpoint attestation on the remote host.
4. In parallel, finish at least two accepted external-system adapters and the
   ten-task asset/license audit.
5. Run exactly one API end-to-end pilot block after a new clean-commit proposal
   and exact hash approval.
6. Admit only verified results, bind them into the paper, run internal model
   critique, then obtain independent expert review and reviewer-verified closure.

Failure at any gate is retained as evidence; it is not replaced by a mock
system, synthetic label, silent provider fallback, or manually completed cell.
