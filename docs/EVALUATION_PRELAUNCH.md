# Evaluation prelaunch contracts

Status: **resource proposals only**. No API generation, remote login, model
transfer, dataset download, GPU execution, reviewer recruitment, or formal cell
is authorized by these files.

SciTaste keeps three experimental objects separate:

| Object | Examples | What it determines |
|---|---|---|
| research method/system | SciTaste Native, MLR-Agent, AI Scientist-v2, AutoResearchClaw, direct agent | who is compared |
| benchmark/task source | MLR-Bench, EXP-Bench | where and on what evidence the systems are evaluated |
| review/judge protocol | blinded experts, adjudication, calibrated model judge | how the outputs are judged |

A Benchmark repository cannot satisfy a method-comparator gate, and a method
repository cannot satisfy a task-source gate. The prelaunch validator enforces
that distinction through the audited external-resource corpus rather than the
display label in a YAML file.

## Resource lanes

Each provider alternative has a separate protocol and proposal hash. There is
no silent fallback between Zhipu and DeepSeek.

| Proposal | Scientific role | Exact model/resource currently named | Planned first block | Current state |
|---|---|---|---:|---|
| `formal-v4-prepilot` | API matched-backbone feasibility | DeepSeek API `deepseek-flash`, documented version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 1 seed = 50 cells | current scope proposal; blocked on task qualification, adapters, replication, analysis/integrity contracts, reviewers, and approval |
| `formal-v3-prepilot` | historical API proposal | retired DeepSeek V4 API identity, temporarily compatibility-routed by the provider | 5 system × task × seed cells | immutable history; do not launch or edit into V4.1 evidence |
| `formal-v2-prepilot` | API matched-backbone feasibility | Zhipu `glm-5.3-flash`, documented version `GLM-5.3-Flash` | 5 system × task × seed cells | official identity verified; blocked on dated exact pricing, authenticated served revision, tasks, adapters, reviewers, and approval |
| `robustness-v1-prepilot` | local small-model robustness | Qwen3-VL-2B-Instruct, tree SHA-256 `8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1`, 4,266,653,057 bytes; 8 × RTX 3090 requested | 6 ablation × task × seed cells | blocked on ablation adapters, task subset, remote inventory/checkpoint, reviewers, and approval |

DeepSeek released V4.1 Flash on 2026-09-10. Its official callable identifier is
now `deepseek-flash`; legacy V4 identifiers are temporarily routed to the new
model. SciTaste therefore created `formal-v4-prepilot` rather than rewriting the
V4 proposal. The new proposal records the documented V4.1 identity and the
published peak prices as conservative cost bounds. Because `deepseek-flash` is
a rolling alias, an authenticated identity observation is still mandatory
immediately before an approved call. See the official [release
notice](https://deepseek.com/news/deepseek-v4-1-flash/) and [dated model and
pricing table](https://api-docs.deepseek.com/quick_start/pricing/).

The official Zhipu model page now names callable ID `glm-5.3-flash`, version
`GLM-5.3-Flash`, 1M context, and 128K maximum output. The proposal therefore
marks public identity verified. The public price page still does not expose a
stable exact token table to the no-JavaScript inspector, and the model page gives
only relative-cost language. Pricing stays blocked rather than borrowing values
from another GLM family. An authenticated preflight must also record the served
revision immediately before an approved call because the callable name is a
rolling alias.

The local Qwen tree and license metadata have been inspected without loading the
model. The remote machine has not been contacted, so GPU count, free storage,
runtime compatibility, and remote checkpoint presence remain pending. The 2B
model is a robustness condition, not a replacement for a frontier API backbone.

The V4.1 proposal now names the exact ten-task MLR-Bench Appendix A population
used by the accepted benchmark for experimentation, writing, and end-to-end
evaluation. It contains seven Trustworthy AI, two LLM/VLM, and one ML Theory
task. This preserves direct comparability but is not a broad field sample. The
metadata-only selection is tracked in
`research/data/mlr_bench_official_ten_candidate_v1.yaml`; its task bytes are not
present, its upstream licenses and executable signals remain pending, and it
authorizes neither download nor execution. One seed yields a scope/preflight
block, not a variance estimate; the statistics critic therefore continues to
block author review until a multi-seed pilot is frozen.

## Machine gate

Inspect any proposal without provider or GPU access:

```bash
.venv/bin/scitaste evaluation prelaunch \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v2.yaml \
  --source-root /path/to/exact-clean-executable-checkout \
  --evidence-root /path/to/proposal-and-protocol-checkout
```

The result contains:

- file and semantic hashes;
- the observed executable Git commit and tree cleanliness;
- exact planned cell count;
- method-system and benchmark-resource blockers;
- API identity/pricing or GPU inventory/checkpoint blockers;
- human-review blockers;
- evidence-bound findings from benchmark-fit, baseline-applicability,
  statistics, integrity, and resource critics;
- separate readiness and exact-hash author-approval verdicts;
- `no_execution_performed=true`.

## Project-owned proposal bundles

The global `configs/evaluation/prelaunch/` files are reusable proposal sources,
not a project history. A project registers an exact no-run copy before treating
it as its current experiment plan:

```bash
.venv/bin/scitaste project evaluation register-prelaunch \
  --project-id scitaste-self-development \
  --evaluation-id deepseek-v41-prepilot \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v2.yaml \
  --source-root . --evidence-root . \
  --expected-revision <current-project-revision> --select \
  --outputs-root outputs
```

This atomically creates
`outputs/projects/<project-id>/evaluations/<evaluation-id>/` with exact copies of
the prelaunch manifest and resource corpus plus `GATE_REPORT.json`,
`CRITIC_REPORT.json`, `CELL_PLAN.json`, and a self-hashed `EVALUATION.json`.
`PROJECT.json` retains the record hash, readiness, resources, blocker count, and
cell count. Opening or selecting the proposal rehashes every file. Registration
does not acquire data, contact a provider, inspect the remote GPU host, or launch
a cell; even an approved proposal remains data-only until a separate launch
service revalidates its exact authority.

Inspect the selected proposal at decision scale without hiding its exact
diagnostics:

```bash
.venv/bin/scitaste project evaluation status \
  --project-id scitaste-self-development \
  --outputs-root outputs
```

The output deterministically groups repeated task/cell/resource diagnostics into
seven ordered decisions: task scope, comparator adapters, statistical design,
temporal integrity, independent review, runtime resources, and exact-hash owner
approval. `diagnostic_blocker_count` remains the number of exact unique codes;
`decision_blocker_count` is the number of unresolved decision domains. Unknown
diagnostic codes fail closed into the integrity domain.

## Result admission after approved execution

Execution output does not become paper evidence merely because a launcher
finished. A runner writes a self-hashed `EvaluationResultSet` beneath the owning
project. It records exact cell/plan/resource identities, API or GPU telemetry,
real-versus-synthetic evidence class, hashed output artifacts, condition-blinded
review attestations, and primary analysis contrasts. Register it without
performing another model, provider, or GPU call:

```bash
.venv/bin/scitaste project evaluation register-result \
  --project-id scitaste-self-development \
  --evaluation-id <approved-evaluation-id> \
  --result-id <immutable-result-id> \
  --result-set outputs/projects/scitaste-self-development/runs/<run>/RESULT_SET.json \
  --expected-revision <revision> --select --outputs-root outputs --dry-run

.venv/bin/scitaste project evaluation result-status \
  --project-id scitaste-self-development --outputs-root outputs
```

The dry run fully verifies existing bytes but creates no execution. Result
selection also selects the proposal it belongs to; selecting another proposal
clears an incompatible result selection. For a formal headline result, every
matched-backbone cell must be a budget-compliant real success, every required
blind review must be external and attested, and the preregistered primary
contrast against at least two independent method comparators must verify. A
pilot, synthetic run, internal review, missing cell, drifted artifact, or GPU
small-model robustness lane cannot establish the headline claim.

The critic review is explicitly advisory: its schema fixes
`authorizes_execution=false`. `ready_for_author_review` becomes true only when
all five critic domains and the resource gate have no blockers. Even then, only
the separate proposal-hash approval can authorize a launch service.

Add `--require-ready` in CI or a launch wrapper to return nonzero until the exact
proposal is both ready and approved. The command itself has no execution path.
A launch service must independently require `execution_authorized=true` and the
same proposal hash.

Expand the proposal into its exact per-system, per-task, per-seed identities
without preparing or executing a launcher:

```bash
.venv/bin/scitaste evaluation cell-plan \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml \
  --output /tmp/deepseek-v41-cell-plan.json
```

The compiler generates opaque cell and review-blind IDs, preserves declared
matrix order, binds every cell to the proposal, task-asset, adapter-preflight,
and API/checkpoint resource hashes, and reports cell-local plus protocol-wide
blockers. Its output fixes `authorizes_execution=false` and records that no
provider call, GPU work, or task download occurred. For the current V4.1
proposal it produces all 50 intended cells, with zero ready for launch
preparation; this makes the gap between a YAML cell count and an executable
cross-framework experiment explicit.

The `max_output_tokens_per_call` values in these proposals are per-experiment
ceilings, not a global SciTaste limit. The V4.1 scope proposal reserves 32,768
output tokens per call, 1,500 requests, and fifteen million total tokens across
all 50 cells. These are ceilings rather than targets and still require a
pilot-informed adequacy check. Any change creates new proposal bytes and needs a
new hash-bound approval.

### Prompt-only control boundary

SciTaste now has a real `direct-agent` control adapter rather than a name-only
placeholder. It accepts one exact visible task package and makes exactly one
structured provider call under a cell-local token, cost, latency, and request
budget. Retrieval, Taste, memory, tools, code execution, experiment execution,
repair, and independent review are structurally absent. The returned paper is
therefore labelled a proposal: its claim statuses are fixed to
`unsupported-until-executed`, and its receipt fixes empirical evidence,
independent review, and complete idea-to-paper eligibility to false.

An admitted call retains the exact invocation, task projection, model request,
raw provider response, structured research package, proposal paper, self-review,
and their SHA-256 values. Backend retries are prohibited so a one-call cell
cannot silently consume a larger budget. The live entry point remains closed
unless the invocation contains an exact proposal/plan/cell approval and the
operator also supplies `--allow-live`:

```bash
.venv/bin/scitaste evaluation direct-agent-run \
  --invocation /path/to/approved-invocation.json \
  --task-root /path/to/frozen-task-root \
  --backend-config /path/to/ignored-live-backend.yaml \
  --output /path/to/empty-cell-output \
  --allow-live
```

This is a low control condition, not the principal comparator and not a
substitute for the native no-Taste ablation. A top-level scientific-taste claim
still requires matched executable trajectories and the separate blinded review
protocol.

## Remaining work before the first approved block

1. Freeze a source-disjoint MLR-Bench pilot subset with asset, license, source
   group, and executable-signal hashes.
2. Prepare and approve exact direct-agent invocations, and implement the real
   external-system adapters; unavailable systems remain unavailable rather than
   receiving a pseudo-implementation.
3. Freeze matched tools, starting information, repair policy, telemetry,
   failure handling, and statistical analysis.
4. Secure the blinded expert rubric, reviewers, conflict checks, and
   adjudication path.
5. For Zhipu, resolve exact dated pricing and record the authenticated served
   revision. For DeepSeek, perform an
   authenticated identity preflight immediately before launch because the API
   name is a rolling alias.
6. For the GPU lane, inspect the remote inventory and storage without running a
   workload, define the checkpoint transfer/archive plan, and verify the copied
   tree hash.
7. Present the regenerated exact manifests and their proposal hashes to the
   project owner. Run one matched block only after explicit approval; require a
   second approval for scale-out.
