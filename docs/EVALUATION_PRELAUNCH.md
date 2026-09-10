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
| `formal-v4-prepilot` | API matched-backbone feasibility | DeepSeek API `deepseek-flash`, documented version `DeepSeek-V4.1-Flash` | 5 system × task × seed cells | current proposal; blocked on task subset, adapters, analysis/integrity contracts, reviewers, and approval |
| `formal-v3-prepilot` | historical API proposal | retired DeepSeek V4 API identity, temporarily compatibility-routed by the provider | 5 system × task × seed cells | immutable history; do not launch or edit into V4.1 evidence |
| `formal-v2-prepilot` | API matched-backbone feasibility | requested Zhipu `glm-5.3-flash` | 5 system × task × seed cells | additionally blocked on official/authenticated model identity and pricing |
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

The public Zhipu model overview and chat-completions schema checked for this
proposal do not list `glm-5.3-flash`; they currently list other GLM-5 and Flash
families. That requested model stays blocked until an official page or an
authenticated, no-generation model inventory establishes its identity and a
dated price record is captured.

The local Qwen tree and license metadata have been inspected without loading the
model. The remote machine has not been contacted, so GPU count, free storage,
runtime compatibility, and remote checkpoint presence remain pending. The 2B
model is a robustness condition, not a replacement for a frontier API backbone.

## Machine gate

Inspect any proposal without provider or GPU access:

```bash
.venv/bin/scitaste evaluation prelaunch \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v2.yaml \
  --source-root /path/to/exact-clean-executable-checkout
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

The critic review is explicitly advisory: its schema fixes
`authorizes_execution=false`. `ready_for_author_review` becomes true only when
all five critic domains and the resource gate have no blockers. Even then, only
the separate proposal-hash approval can authorize a launch service.

Add `--require-ready` in CI or a launch wrapper to return nonzero until the exact
proposal is both ready and approved. The command itself has no execution path.
A launch service must independently require `execution_authorized=true` and the
same proposal hash.

The `max_output_tokens_per_call` values in these proposals are per-experiment
ceilings, not a global SciTaste limit. API proposals currently reserve 32,768
output tokens per call and five million total tokens for the first block; these
budgets can change only by creating new proposal bytes and obtaining a new
hash-bound approval.

## Remaining work before the first approved block

1. Freeze a source-disjoint MLR-Bench pilot subset with asset, license, source
   group, and executable-signal hashes.
2. Implement and validate the direct-agent control and the real external-system
   adapters; unavailable systems remain unavailable rather than receiving a
   pseudo-implementation.
3. Freeze matched tools, starting information, repair policy, telemetry,
   failure handling, and statistical analysis.
4. Secure the blinded expert rubric, reviewers, conflict checks, and
   adjudication path.
5. For Zhipu, resolve model identity and pricing. For DeepSeek, perform an
   authenticated identity preflight immediately before launch because the API
   name is a rolling alias.
6. For the GPU lane, inspect the remote inventory and storage without running a
   workload, define the checkpoint transfer/archive plan, and verify the copied
   tree hash.
7. Present the regenerated exact manifests and their proposal hashes to the
   project owner. Run one matched block only after explicit approval; require a
   second approval for scale-out.
