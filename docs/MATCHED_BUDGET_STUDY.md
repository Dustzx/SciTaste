# Matched-budget system study

Phase 9 evaluates complete research systems under one preregistered resource and
task contract. The study harness plans and audits runs; it does not manufacture
executor outputs or expert judgments.

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
atomically checkpoints aggregate results after every cell. Successful cells are
resumed by default. A timed-out process group, missing executable, non-zero exit,
missing telemetry, path-escaping artifact, or invalid result becomes a failed
record; none is replaced with synthetic success.

Protocols declare either `formal` or `pilot` scope. A pilot remains
`acceptance_only` even if every execution and external review is otherwise
complete, preventing engineering trials from becoming headline evidence.

## Current readiness blockers

The committed v1 draft deliberately contains explicit pending markers for the
provider-resolved Qwen revision and frozen search snapshot. The planner surfaces
both markers as blockers. Real execution additionally requires:

- end-to-end condition launchers through later AutoResearchClaw stages;
- externally measured API/token cost, because the accepted Stage 1–3 substrate
  run did not emit an API cost log;
- pinned Sibyl/AI Scientist-v2 adapters if they prove practical;
- independent experts, conflict adjudication, and reviewer identity hashes.

A local Qwen3-VL-4B decision-backend smoke run is complete on one RTX 3090. It
validates model loading and the preference protocol only; it is not a complete
system cell and therefore does not clear the executor, search-snapshot, or expert
review requirements above.

These are operational/research prerequisites, not reasons to weaken the audit
contract or modify AutoResearchClaw internals.
