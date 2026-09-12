# SciTaste experiment decision brief v1

Status: **historical feasibility brief; superseded for launch planning**. The
Qwen3-VL-2B choice, 120-case floor, and 100-trajectory API matrix below predate
the resource-independent H0/H1/H2a/H2b/H3/E1/D1 evidence program and must not
authorize or size a current experiment. Current scientific authority belongs to
`configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml`; current
resource joining belongs to
`configs/evaluation/activation/iclr2027_review_followup_v3.yaml`. Those records
leave the primary model, formal sample size, repetitions, and compute allocation
unset until task metadata, a task-excluded conformance pilot, and power analysis
are complete. No experiment execution is authorized.

This retained brief separates the earlier API and GPU feasibility blocks. It does
not treat a model review of the manuscript as an experiment, and it does not pool
provider inference with local accelerator use.

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
| Current status | the first 16-record, 3 MiB AAAR rights pilot is exact and approval-ready; no source bytes, natural cases, abstractions, or human labels have been acquired |

The curation/compiler contract is
[`protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md`](protocols/SCITASTEBENCH_V2_CURATION_GOVERNANCE_V1.md).
The metadata-only source screen is
[`data/scitastebench_v2_source_candidates_v1.yaml`](data/scitastebench_v2_source_candidates_v1.yaml).
The first core-source transaction is
`configs/evaluation/acquisition/aaar_experiment_design_rights_pilot_v1.yaml`.
It selects sixteen source-body-unseen experiment-design JSON records from five
arXiv primary categories after a paper-level CC-BY-4.0 screen. Its 3 MiB
download-only scope advances treatment construction, not formal case sampling or
effectiveness estimation; ingestion and every model, human, API, and GPU action
remain separately gated.

## API block — Track B end-to-end external systems

| Binding | Current no-run proposal; immutable registered instance |
|---|---|
| Question | Under matched starting briefs, tools, model, repair rules, and budgets, are complete SciTaste Native packages preferred by blinded experts? |
| Provider/model | DeepSeek `deepseek-flash` / `DeepSeek-V4.1-Flash`, confirmed by the live official catalog on 2026-09-12; legacy `deepseek-v4-flash` is routed to V4.1; Zhipu `glm-5.3-flash` requires a separate proposal and is not a silent fallback |
| Data | the ten candidate ICLR-2025 MLR-Bench workshop briefs; exact task assets remain unacquired and unadmitted |
| Systems | SciTaste Native, Direct Agent, MLR-Agent, Agent Laboratory, TinyScientist candidate |
| Matrix | historical upper design: 5 systems × 10 tasks × 2 seeds = 100 trajectories; formal size must follow pilot power analysis |
| API ceiling | v6 ceiling: 1,500 requests, 15M total tokens, USD 100 at the confirmed conservative peak prices |
| Human ceiling | 30 reviewer-hours; at least two conflict-checked blinded reviewers per comparison |
| Primary metric | task-averaged blinded expert package preference for scientific value and evidence validity |
| Secondary metrics | unsupported claims, valid/failed experiments, pivot/stop quality, reproducibility, wall time, tokens, cost, interventions |
| Current status | non-launchable: accepted external adapters, per-task assets/licenses, held-out audit, clean executable binding, human reviewers, and owner approval are not ready |

The registered immutable proposal is
`outputs/projects/scitaste-self-development/evaluations/deepseek-v41-package-prepilot-v6/`.
Its proposal SHA-256 is
`0820a4589b859d1f2feb2e8f14bf37cc8c0477b6c1413e32cbbe8122b6411e8e`.
It pins executable commit `2e2316099700951c922a79cbc04bd95dea4cf892` and
authorizes no execution. Its provider identity is current, but its recorded
executable commit and other bindings remain immutable. Any later executable
change requires a new proposal; this one must not be edited in place or approved
by alias.

## Launch order

1. Decide the exact AAAR sixteen-file rights-pilot request; approval permits only
   one receipt-bearing 3 MiB download and does not start ingestion, a model, a
   human task, or a GPU.
2. Audit the acquired schema/content and publish a separate source-projection,
   real-abstraction, and human-fidelity pilot before any benchmark case is
   admitted.
3. Curate and human-label a source-disjoint natural pilot, then freeze its power
   analysis before opening the formal Track A split.
4. Run the selected local/API mechanism block only after model conformance and
   checkpoint/identity attestation.
5. In parallel, finish at least two accepted external-system adapters and the
   ten-task asset/license audit.
6. Run exactly one API end-to-end pilot block after a new clean-commit proposal
   and exact hash approval.
7. Admit only verified results, bind them into the paper, run internal model
   critique, then obtain independent expert review and reviewer-verified closure.

Failure at any gate is retained as evidence; it is not replaced by a mock
system, synthetic label, silent provider fallback, or manually completed cell.
