# Matched-budget system study

Phase 9 provides the registered study harness and the current
AutoResearchClaw-substrate matrix. The ICLR 2027 headline design, external-system
comparison, native causal ablation, statistical contract, and author-approval
gates are specified separately in
[`ICLR_2027_EVALUATION_PLAN.md`](ICLR_2027_EVALUATION_PLAN.md). The study harness
plans and audits runs; it does not manufacture executor outputs or expert
judgments.

The registered v1 conditions below share the AutoResearchClaw Stage 8--18
lifecycle. They test augmentation on one common execution substrate; they are
not four independent autonomous-research frameworks. Consequently this matrix
cannot by itself establish that SciTaste Native outperforms AutoResearchClaw or
other external systems. That claim requires the separate external comparison in
the ICLR evaluation contract.

## Registered matrix

The v1 protocol contains four independent task categories:

1. diagnosis-friendly failure-boundary research;
2. a clear mechanism hypothesis;
3. a new benchmark formulation;
4. an ambiguous empirical direction.

The four enabled core conditions are AutoResearchClaw, Knowledge RAG, Taste
Library, and Full SciTaste. Three fixed seeds produce 48 cells. Sibyl and AI
Scientist-v2 are registered but disabled until pinned, license-reviewed adapters
with complete budget telemetry are available.

Here, `disabled` means optional external-baseline integration is pending. It does
not mean a mock implementation is substituted, and it does not block local
experiments on the four core conditions. Sibyl currently requires a separate
Claude Code/agent-team/MCP environment and broad execution permissions. AI
Scientist-v2 executes LLM-written code and explicitly requires a controlled
sandbox. Each must pass repository/version pinning, license review, isolated
execution, artifact mapping, and all six telemetry dimensions before it can be
enabled. Until then, both remain visible in the protocol as unavailable rather
than contributing fabricated results.

Integration assessments must use the official
[Sibyl repository](https://github.com/Sibyl-Research-Team/AutoResearch-SibylSystem)
and [AI Scientist-v2 repository](https://github.com/SakanaAI/AI-Scientist-v2),
not similarly named forks.

Every enabled cell inherits the same:

- Qwen base-model declaration and frozen revision;
- frozen search snapshot and search policy;
- task asset and codebase commit;
- GPU-hour, experiment, wall-time, API-cost, query, and token ceilings.

Cell and blinded artifact identifiers are deterministic hashes of the complete
protocol. Evaluators see only the blinded identifier.

## Eligibility gate

A result cannot enter headline comparisons unless all planned cells:

- succeed and provide content-hashed artifacts;
- report every resource dimension;
- stay inside every fixed budget;
- keep experiment counts consistent between telemetry and outcome records;
- receive a rubric-matched, condition-blinded external panel review;
- use real rather than synthetic execution evidence.

The evaluator returns one of three states:

- `incomplete`: missing cells, readiness blockers, failures, budget violations,
  incomplete telemetry, or invalid/missing expert review;
- `acceptance_only`: structurally complete but containing synthetic fixtures;
- `eligible`: complete real execution with valid external review.

Only `eligible` sets `headline_eligible=true`.

## Metrics

Per-condition system metrics include research yield per GPU-hour, idea yield,
invalid-idea rate, pilots, discarded ideas, unproductive-experiment rate,
compute before useful signal, pivots, evidence sufficiency, reviewer-concern
closure, unsupported-claim rate, correct-pivot rate, six expert quality scores,
and final expert preference. The report also computes aggregate deltas against
AutoResearchClaw. Statistical intervals and hypothesis tests will be added only
with real repeated observations.

## Commands

Generate or inspect the deterministic plan:

```bash
.venv/bin/scitaste study plan \
  --config configs/experiments/matched_budget_study_v1.yaml \
  --output outputs/matched-study-phase9-plan
```

Audit externally produced execution records and blinded panel reviews:

```bash
.venv/bin/scitaste study evaluate \
  --config configs/experiments/matched_budget_study_v1.yaml \
  --results path/to/study-results.json \
  --output outputs/matched-study-evaluation
```

Planning and evaluation are local operations. They never invoke an LLM or launch
an experiment implicitly.

Inspect all project-owned result sources against one exact protocol without
launching a cell or writing a file:

```bash
.venv/bin/scitaste study status \
  --config configs/experiments/matched_budget_study_v1.yaml \
  --outputs-root outputs
```

The status command separates exact-protocol, foreign-protocol, and invalid
sources. Exact-protocol records count only when their self-hashed run manifest,
cell checkpoint, request, aggregate/owned execution records, and evidence bytes
all revalidate. Identical duplicates are deduplicated; conflicting records or
reviews are excluded. The proposed next execution batch is one incomplete
task/seed/repetition block, preserving the matched four-condition design. An
optional `--output` writes a self-hashed report to the caller-selected path; a
project run directory should be used rather than a new loose top-level output.

Run selected execution-ready cells through explicit command adapters:

```bash
.venv/bin/scitaste study run \
  --config configs/experiments/matched_budget_local_pilot_v1.yaml \
  --launch-config path/to/reviewed-launchers.yaml \
  --task diagnosis-friendly-v1 \
  --output outputs/local-study-pilot
```

`study run` creates an isolated directory per cell, writes a complete request,
starts the adapter without a shell, bounds the process by wall/GPU allocation,
captures logs, validates its standard result, re-hashes declared artifacts, and
atomically checkpoints aggregate results after every cell. The output root has a
self-hashed run manifest binding the protocol, deterministic plan, and exact
launcher configuration. Every completed attempt has a self-hashed cell
checkpoint binding its request, command, execution record, and evidence files.
Successful cells are resumed only after those identities and every artifact hash
revalidate. A changed launcher, tampered record/artifact, orphaned aggregate
entry, or legacy output without an integrity manifest fails closed.

Failed attempts are moved beneath the owning cell's `failed_attempts/` directory
before a retry, retaining logs, raw launcher result, record, and checkpoint.
Runner-owned time remains cumulative. One non-blocking process lock protects the
complete output directory, so concurrent runners cannot overwrite each other's
checkpoints or aggregate results. A timed-out process group, missing executable,
non-zero exit, missing telemetry, path-escaping artifact, or invalid result
becomes a failed record; none is replaced with synthetic success.

`ProjectMatchedStudyRunner` is the project-owned application boundary for this
runner. It requires an existing `ProjectRuntime` project, registers and selects
one run whose `stage_path` is `study`, stores the integrity-checked study below
that run, and finalizes the run as `partial`, `complete`, or `failed` under the
same optimistic project revision held before the long execution. A concurrent
project mutation therefore conflicts instead of being silently adopted.
Mutation-free dry-run and strict resume identity checks are available through
both the Python API and the project-owned command:

```bash
.venv/bin/scitaste study project-run \
  --config configs/experiments/matched_budget_local_pilot_v1.yaml \
  --launch-config path/to/reviewed-launchers.yaml \
  --project-id my-study --run-id local-pilot-v1 \
  --provider local --model Qwen3-VL-4B-Instruct \
  --condition autoresearchclaw --max-cells 1 --dry-run
```

The project must already exist. Remove `--dry-run` only after reviewing the
launcher and resource implications. A later invocation must add `--resume` to
reuse the same registered partial or failed run; a new invocation never silently
adopts an existing run directory.

Protocols declare either `formal` or `pilot` scope. A pilot remains
`acceptance_only` even if every execution and external review is otherwise
complete, preventing engineering trials from becoming headline evidence.

## Local RTX 3090 execution path

`configs/experiments/study_launchers_qwen3vl4b_local_v2.yaml` is the current
launcher set for all four core conditions. It invokes
`scitaste.benchmark.local_study_adapter`, which verifies the content hash of
`configs/backends/local_transformers_qwen3vl4b_study_v2.yaml` and the names,
sizes, and bytes of every checkpoint file, loads that checkpoint once per cell,
and serves only the narrow non-streaming Chat Completions subset on loopback.
The historical v1 launcher remains pinned to its original 20,000-token pilot.
The ephemeral bearer is held in process
memory and the child receives only its environment-variable name and loopback
URL. Requests have byte, context, output, schema, model-identity, and serialized
inference bounds. No network model or fake completion is used.

A real project-owned run is retained under
`outputs/projects/phase9-local-qwen3vl4b-pilot`. For the diagnosis/base/seed-7
cell, Qwen3-VL-4B made seven calls and completed Stage 8 and Stage 9. Stage 10
failed before its next request because admitting that request would exceed the
20,000-token protocol ceiling. The child result reports 18,579 total tokens
(10,131 prompt and 8,448 completion), 267.754 seconds of model latency, zero API
cost, zero searches, zero experiments, and 0.074909 runner-allocated GPU-hours.
There is intentionally no experiment, manuscript, score, or success record.

This run accepts the local transport and early-stage adapter integration only.
It demonstrates that the v1 token allocation is not completion-ready and does
not justify running the remaining 15 cells unchanged. It also exposed a now
fixed parent-runner defect: a non-zero launcher exit previously replaced a valid
failed child result with unknown counters. Future executions preserve exact
schema-valid failure telemetry while forcing any non-zero child success claim
back to failure; the original record stays immutable and its exact counters
remain in `launcher_result.json` and `llm_telemetry.jsonl`.

The completion-calibrated local preacceptance retains the same checkpoint and
transport but raises the cell budget to 200,000 tokens and three wall/GPU hours.
Its diagnosis task declares a repository-relative executable asset by SHA-256,
module, and entrypoint. SciTaste copies the exact kernel plus a canonical wrapper
into Stage 7, injects those bytes at code extraction and sandbox execution, and
requires one source-verified call from a Python main guard. The selected run is
rejected if the contract, kernel, wrapper, sandbox trace, registered seed matrix,
dispersion, or sole machine-evidence record disagrees.

The current kernel executes all 1,944 registered packets. Its observed method
means are 0.855453, 0.975309, and 0.938786; their cross-method balanced-accuracy
aggregate is 0.923182. Across seeds 7, 19, and 31 it finds 16 reproducible
majority-vote failure cells, no confidence-weighted failure cell, and 3
position-aware failure cells under the registered below-0.75/on-at-least-two-seeds
criterion. Factor effects and boundary cells are first-class evidence rather
than optional text hidden in stdout.

Local v6--v8 are retained failures, not retries rewritten in place. They reached
real experiment execution and progressively exposed that generic analysis could
discard diagnostics, deterministic outline evidence could use labels its own
auditor did not recognize, and small-model debate roles could negate an executed
grid or repeat prohibited audit shorthand. The adapter now passes the
publication-safe diagnostic projection to every analysis role and synthesis,
omits the raw machine record from prose prompts, and rejects contradictory or
incomplete diagnostic reporting before spending later-stage tokens. A fresh
versioned cell is required to establish complete Stage 8--18 feasibility.

Local v9 pins that evidence-bound implementation and passed its offline and
focused checks, but its real attempt produced zero model tokens and zero
experiments after the RTX 3090 reported NVIDIA Xid 79 (GPU fallen off the bus).
The immutable failed attempt records 0.023591 allocated GPU-hours before exit.
It does not test the repaired Stage 14 path and must not be interpreted as a
software regression or feasibility result. After host-level GPU recovery, v9
can resume through the registered runner, which will archive the failed attempt
instead of overwriting it.

## Current execution state

The formal protocol pins Bailian `qwen3.8-max-2026-09-02` and a
content-addressed local snapshot. Fixed synthetic generators provide controlled
internal comparisons; transfer to natural scientific corpora remains an explicit
limitation.

As of 2026-09-09, the current formal protocol fingerprint is
`ce09bf7d3ad22db09d40fc4368b03e3b903b3087b571cc1ecfecbb081690587c`
and its plan fingerprint is
`c510998914b7be5a2874698478b73131c7483b44d4128b1a75a84947581d22d5`.
The integrity-aware status scan finds 0/48 exact-protocol execution records and
0/48 external reviews. The earlier successful Base cell uses predecessor
protocol `20ee06e9...` and remains valid engineering evidence, but is not
reusable in this matrix because later adapter fixes changed the registered
implementation identity. Thus the operational count for the current protocol
is 48 missing cells, not 47.

The four first-party launchers run unmodified AutoResearchClaw from hypothesis
generation through peer review. The adapter isolates Knowledge and Taste
augmentation, records the Full SciTaste controller decision, captures exact wire
tokens, estimates API cost from the frozen posted-price schedule, and rejects
generated experiment code containing network access. Upstream novelty,
benchmark, and code search are disabled so `search_queries=0` is enforced.

The peer-review endpoint is intentional: a real preacceptance cell consumed
190,688 of its 200,000-token allowance before AutoResearchClaw attempted a
second paper-revision pass. Ending at peer review keeps every condition inside
the preregistered budget and leaves concern closure to the independent blinded
panel instead of allowing unequal revision retries.

Remaining exit-gate work is operational:

- restore or replace the protocol-pinned Qwen provider access, then pass one
  clean four-condition matched batch before scaling to all 48 registered cells;
- inspect every generated code/result/paper manifest and budget audit;
- collect independent condition-blinded reviews and adjudicate conflicts;
- optionally enable Sibyl/AI Scientist-v2 after their separate gates pass.

Until external reviews arrive, completed executions remain `incomplete` for
headline eligibility. This does not weaken their execution evidence or modify
AutoResearchClaw internals.
