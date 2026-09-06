# AutoResearchClaw integration

SciTaste treats AutoResearchClaw as an immutable optional baseline and
compatibility substrate. The pinned `v0.5.0` submodule is not patched; all
compatibility and control behavior lives in `src/scitaste/executor/`. The
default `scitaste run full` path uses `scitaste-native` and neither imports nor
invokes this submodule.

## Boundary

```text
ResearchState + candidate actions
→ TasteController decision
→ AutoResearchClaw adapter
→ prerequisite check
→ one bounded upstream stage
→ stage-contract artifact validation
→ fresh checkpoint + exact terminal-stage validation
→ hashed artifact manifest + incremental cost record
→ ResearchState transition only on success
```

The adapter maps supported SciTaste actions to upstream stages. SciTaste-only
actions remain control-only rather than being forced into an inaccurate stage.
Before a live call, every required upstream artifact must already exist in the
shared run directory. A zero process exit code is insufficient: the expected
stage artifacts and pipeline completion status must also pass validation.

## Sessions and resource records

AutoResearchClaw assigns a new internal run ID when an explicit run directory is
reused with `--from-stage`. SciTaste therefore derives a stable session ID from
the resolved run directory and records both previous and current upstream IDs.
This preserves continuity without modifying upstream behavior.

Wall-clock time is always measured. API cost is imported only when upstream
writes `cost_log.jsonl`; otherwise `cost_accounting.api_cost_measured` is false.
An absent upstream cost log must not be interpreted as a zero-cost model call in
a matched-budget experiment. For staged calls, SciTaste records the increase from
the imported cumulative total, not the historical total of the source run.

## Compatibility controls

The original AutoResearchClaw invocation remains available when
`--max-output-tokens` is omitted. For bounded compatibility tests, SciTaste can
launch the same unmodified CLI through a process-local bootstrap that caps LLM
output tokens. A versioned prompt override keeps the smoke contract short and
does not replace the production prompts implicitly.

```bash
export DASHSCOPE_API_KEY='...'

scitaste baseline run \
  --topic "Auditable adapter integration for taste-guided autonomous research" \
  --to-stage PROBLEM_DECOMPOSE \
  --max-output-tokens 512 \
  --config configs/executors/autoresearchclaw.bailian.example.yaml \
  --output outputs/autoresearchclaw-smoke

scitaste substrate execute \
  --action SEARCH \
  --run-dir outputs/autoresearchclaw-smoke \
  --config configs/executors/autoresearchclaw.bailian.example.yaml \
  --max-output-tokens 512 \
  --max-total-tokens 100000 \
  --allow-live \
  --output outputs/scitaste-substrate-action
```

`max_output_tokens` is a configurable per-request ceiling. It is not a global
development limit. `max_total_tokens` bounds all LLM responses in that one
upstream process and the process-local telemetry file retains per-call usage.

## Project-owned source and action lifecycle

The raw command above remains useful for adapter diagnostics. New live work
should use `substrate project`. A first-party bootstrap creates the Stage 1–2
prerequisite tree directly beneath the owning project, after which the selected
Stage 3 action consumes that verified project run. Importing an external upstream
run remains available for migration and diagnostics.

The bootstrap publishes its self-hashed request manifest before contacting the
provider, retains the exact executor result, validates the Stage 1 and exact
Stage 2 contract, and copies successful work to an immutable reusable `source/`
snapshot. The selected-action manifest then binds the source receipt as well as
the project/run/action/seed, both configuration hashes, exact source tree, and
pinned upstream commit. Completion is registered only after the action evidence
and final working tree have been hashed. Failed work is kept under numbered
attempt archives. A successful paid bootstrap result persisted before an
interruption is recovered without issuing the provider call again.

The committed GLM-5.3-Flash template is inert (`live_enabled: false`). Copy it to
a private run configuration, explicitly change that field to `true`, and supply
the key through `ZAI_API_KEY`. Planning does not create a project or call a
provider. Build and verify the owned prerequisite first:

```bash
.venv/bin/scitaste substrate project bootstrap plan \
  --config path/to/project-substrate-live.yaml \
  --run-id 2026-09-05__glm-5.3-flash__bootstrap-stage02__seed-07 \
  --outputs-root outputs --seed 7

.venv/bin/scitaste substrate project bootstrap execute \
  --config path/to/project-substrate-live.yaml \
  --run-id 2026-09-05__glm-5.3-flash__bootstrap-stage02__seed-07 \
  --outputs-root outputs --seed 7 --allow-live

.venv/bin/scitaste substrate project bootstrap status \
  --project-id scitaste-self-development \
  --run-id 2026-09-05__glm-5.3-flash__bootstrap-stage02__seed-07 \
  --outputs-root outputs
```

Then run the selected action from the verified receipt:

```bash
.venv/bin/scitaste substrate project plan \
  --config path/to/project-substrate-live.yaml \
  --run-id 2026-09-05__glm-5.3-flash__selected-search__seed-07 \
  --source-project-run 2026-09-05__glm-5.3-flash__bootstrap-stage02__seed-07 \
  --outputs-root outputs --seed 7

.venv/bin/scitaste substrate project execute \
  --config path/to/project-substrate-live.yaml \
  --run-id 2026-09-05__glm-5.3-flash__selected-search__seed-07 \
  --source-project-run 2026-09-05__glm-5.3-flash__bootstrap-stage02__seed-07 \
  --outputs-root outputs --seed 7 --allow-live

.venv/bin/scitaste substrate project status \
  --project-id scitaste-self-development \
  --run-id 2026-09-05__glm-5.3-flash__selected-search__seed-07 \
  --outputs-root outputs
```

Both the versioned configuration and the CLI flag must authorize a live call.
The example executor is
`configs/executors/autoresearchclaw.zhipu-glm53-flash.example.yaml`; secrets are
environment inputs and are not copied into committed configuration.

Generated upstream artifacts and exact execution logs stay under ignored
`outputs/`. Aggregate hashes and acceptance facts may be committed.

## Current limit

The first-party project lifecycle has completed and independently revalidated a
live GLM-5.3-Flash Stage 1–2 bootstrap and receipt-bound Stage 3 handoff. Stage 3
reached the 4,096-token per-request ceiling and neither run emitted an API-cost
log, so the result remains integration engineering evidence only. It does not
validate literature collection, experiment execution, paper generation, or
effectiveness. Source entries emitted while web search is disabled are planning
artifacts, not independently verified knowledge and are not automatically
ingested into the Knowledge Library. See
`docs/experiments/zhipu_glm53_project_owned_stage13_2026-09-05.md`.
