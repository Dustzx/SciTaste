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
→ hashed artifact manifest + checkpoint + runtime
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
a matched-budget experiment.

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
  --output outputs/scitaste-substrate-action
```

Generated upstream artifacts and exact execution logs stay under ignored
`outputs/`. Aggregate hashes and acceptance facts may be committed.

## Current limit

The accepted vertical slice covers initialization, problem decomposition, and a
SciTaste-selected search-strategy stage. It does not yet validate literature
collection, experiment execution, or paper generation. Source entries emitted
while web search is disabled are planning artifacts, not independently verified
knowledge and are not automatically ingested into the Knowledge Library.
