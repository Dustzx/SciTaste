# AutoResearchClaw integration

SciTaste treats AutoResearchClaw as an immutable execution substrate. The pinned
`v0.5.0` submodule is not patched; all compatibility and control behavior lives
in `src/scitaste/executor/`.

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

## Project-owned action lifecycle

The raw command above remains useful for adapter diagnostics. New live work
should use `substrate project`, which imports an existing upstream run as an
immutable project input and creates a separate working copy. Its self-hashed
manifest binds the project/run/action/seed, both configuration hashes, the exact
source tree, and the pinned upstream commit. Completion is registered only after
the action evidence and final working tree have been hashed. Failed work is kept
under a numbered attempt archive and may be resumed only with the same identity.

The committed GLM-5.3-Flash template is inert (`live_enabled: false`). Copy it to
a private run configuration, explicitly change that field to `true`, and supply
the key through `ZAI_API_KEY`. Planning does not create a project or call a
provider:

```bash
.venv/bin/scitaste substrate project plan \
  --config path/to/project-substrate-live.yaml \
  --run-id 2026-09-05__glm-5.3-flash__selected-search__seed-07 \
  --source-run outputs/<source-autoresearchclaw-run> \
  --outputs-root outputs --seed 7

.venv/bin/scitaste substrate project execute \
  --config path/to/project-substrate-live.yaml \
  --run-id 2026-09-05__glm-5.3-flash__selected-search__seed-07 \
  --source-run outputs/<source-autoresearchclaw-run> \
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

The historical accepted vertical slice covers initialization, problem
decomposition, and a SciTaste-selected search-strategy stage. The project-owned
lifecycle has also passed one live GLM-5.3-Flash Stage 3 preacceptance with exact
status revalidation. It reached the 4,096-token per-request ceiling and emitted
no API-cost log, so it is accepted for integration engineering only. Neither
result validates literature collection, experiment execution, paper generation,
or effectiveness. Source entries emitted while web search is disabled are
planning artifacts, not independently verified knowledge and are not
automatically ingested into the Knowledge Library. See
`docs/experiments/zhipu_glm53_project_substrate_search_2026-09-05.md`.
