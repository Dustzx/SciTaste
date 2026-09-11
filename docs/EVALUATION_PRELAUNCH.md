# Evaluation prelaunch contracts

Status: **resource proposals only**. A read-only remote inventory has been
recorded, but no model transfer, dataset download, GPU execution, reviewer
recruitment, or formal cell is authorized by these files.

SciTaste keeps three experimental objects separate:

| Object | Examples | What it determines |
|---|---|---|
| research method/system | SciTaste Native, accepted MLR-Agent, Agent Laboratory, AI-Researcher, TinyScientist, and the direct agent; preprints only in sensitivity analysis | who is compared |
| benchmark/task source | MLR-Bench, MLRC-Bench, EXP-Bench, HeurekaBench, AAAR-1.0 | where and on what evidence the systems are evaluated |
| review/judge protocol | blinded experts, adjudication, calibrated model judge | how the outputs are judged |

The cross-track approval view is the
[`EXPERIMENT_DECISION_DOSSIER.md`](EXPERIMENT_DECISION_DOSSIER.md). Its current
machine-readable campaign binds the API and GPU plans, their dependency order,
resource ceilings, paper title, and review closure path while granting no
download or execution authority. The older individual proposal files remain
immutable evidence and are not silently promoted when the campaign changes.

A Benchmark repository cannot satisfy a method-comparator gate, and a method
repository cannot satisfy a task-source gate. The prelaunch validator enforces
that distinction through the audited external-resource corpus rather than the
display label in a YAML file.

## Resource lanes

Each provider alternative has a separate protocol and proposal hash. There is
no silent fallback between Zhipu and DeepSeek.

| Proposal | Scientific role | Exact model/resource currently named | Planned first block | Current state |
|---|---|---|---:|---|
| `formal-v6-package-prepilot` | API idea-to-paper package-preference feasibility | DeepSeek API `deepseek-flash`, served version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 cells | current schema-v1.1 no-run proposal; independent expert preference is primary and a model judge is secondary; task bytes, adapters, reviewers, clean executable checkout, authenticated served identity, and approval remain blocked |
| `formal-v5-package-prepilot` | superseded provider-identity snapshot | historical `deepseek-v4-flash` / `DeepSeek-V4-Flash-0731` assumption | 5 systems × 10 official tasks × 2 seeds = 100 cells | immutable no-run history; superseded by the provider's 2026-09-11 V4.1 catalog and must not be approved or launched |
| `formal-v4-package-prepilot` | historical package-preference proposal | `deepseek-flash` / `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 cells | immutable history with the current identity but an older source, resource snapshot, and governance contract; use v6 for new review or approval |
| `formal-v4-accepted-method-prepilot` | historical API scope with an invalid endpoint/task binding | DeepSeek API `deepseek-flash`, documented version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 cells | immutable history; v3 incorrectly treated the MLR-Bench open-ended package rubric as objective task progress and must not be approved or launched |
| `formal-v4-prepilot` | historical API scope proposal | DeepSeek API `deepseek-flash`, documented version `DeepSeek-V4.1-Flash` | 5 systems × 10 official tasks × 1 seed = 50 cells | immutable history; included preprint comparators and lacked replication plus analysis/integrity contracts |
| `formal-v3-prepilot` | historical API proposal | earlier DeepSeek V4 API identity | 5 system × task × seed cells | immutable history; do not edit it into current evidence |
| `formal-v2-accepted-method-prepilot` | historical Zhipu scope with the same invalid endpoint/task binding | Zhipu `glm-5.3-flash`, documented version `GLM-5.3-Flash` | 5 systems × 10 official tasks × 2 seeds = 100 cells | immutable history; rebuild as a separate schema-v1.1 package-preference proposal after exact pricing is resolved rather than editing or silently falling back from DeepSeek |
| `formal-v2-prepilot` | historical Zhipu scope proposal | Zhipu `glm-5.3-flash` | 5 system × task × seed cells | immutable history; do not edit into the accepted-method proposal |
| `robustness-v2-multitask-prepilot` | historical local small-model scope with an invalid endpoint/task binding | Qwen3-VL-2B-Instruct, tree SHA-256 `8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1`, 4,266,653,057 bytes; 8 × RTX 3090 requested | 6 ablations × 2 tasks × 2 seeds = 24 cells | immutable no-run history; rebuild against qualified objective-score tasks or an explicit package-review endpoint before any GPU approval |
| `robustness-v1-prepilot` | historical local scope proposal | the same local Qwen checkpoint candidate | 6 ablation × task × seed cells | immutable one-task/one-seed history |

DeepSeek's 2026-09-11 official catalog exposes callable ID `deepseek-flash` and
served version `DeepSeek-V4.1-Flash`. Peak pricing is $0.006/M cached input
tokens, $0.30/M uncached input tokens, and $1.20/M output tokens. The older
`deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` names are accepted only
as compatibility aliases routed to V4.1. SciTaste therefore retains v5 as
non-launchable history and creates `formal-v6-package-prepilot` with the
canonical identity and conservative peak prices. Because the callable ID is a
rolling alias, an authenticated returned-model observation is still mandatory
immediately before an approved call. See the official
[dated model and pricing table](https://api-docs.deepseek.com/quick_start/pricing/).

The official Zhipu model page now names callable ID `glm-5.3-flash`, version
`GLM-5.3-Flash`, 1M context, and 128K maximum output. The proposal therefore
marks public identity verified. The public price page still does not expose a
stable exact token table to the no-JavaScript inspector, and the model page gives
only relative-cost language. Pricing stays blocked rather than borrowing values
from another GLM family. An authenticated preflight must also record the served
revision immediately before an approved call because the callable name is a
rolling alias. A future Zhipu package-preference proposal must bind the same
schema-v1.1 endpoint semantics in its own immutable bytes; it cannot reuse the
historical objective-progress proposal or act as a silent DeepSeek fallback.

The local Qwen tree and license metadata have been inspected without starting a
new workload. A read-only SSH observation on 2026-09-11 verified eight idle RTX
3090 devices with 24,576 MiB each, driver 570.211.01, Python 3.12.3, Docker,
Bubblewrap, and 59,034,427,392 bytes free on the 88%-used root filesystem. The
intended remote checkpoint destination is absent. The exact observation is
recorded in
`research/data/gpu_host_3090_2_inventory_v1.yaml` with no address or credential;
verified GPU inventory declarations now require this kind of content-bound
evidence, and a verified remote checkpoint separately requires an attestation.
The 2B model is a robustness condition, not a replacement for a frontier API
backbone. Its replacement proposal must use the SciTasteBench mechanism track,
a genuinely objective benchmark, or the package-preference protocol rather than
reusing the invalid MLR-Bench objective-progress binding.

The current DeepSeek proposal names the exact ten-task MLR-Bench Appendix A
candidate population used by the accepted benchmark for experimentation,
writing, and end-to-end evaluation. It contains seven Trustworthy AI, two
LLM/VLM, and one ML Theory task. These are open-ended workshop-derived research
briefs assessed with research-quality rubrics; they do **not** expose a fixed
objective score for each task. The metadata-only selection is tracked in
`research/data/mlr_bench_official_ten_candidate_v2.yaml`, which machine-labels
every task as `research_package_review`. Its starting brief bytes are not
present, downstream/runtime asset licenses and executable signals remain
pending, and it authorizes neither download nor execution. The content-bound
package protocol at
`research/protocols/AUTORESEARCH_PACKAGE_PREFERENCE_PREPILOT_GOVERNANCE_V4.md`
freezes independent blinded expert preference as primary and a model judge as
secondary. Objective progress remains a separate lane for a benchmark such as
qualified MLRC-Bench; the two estimates are never pooled.

## Machine gate

Inspect any proposal without provider or GPU access:

```bash
.venv/bin/scitaste evaluation prelaunch \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v6.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v6.yaml \
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
  --evaluation-id deepseek-v41-package-prepilot-v6 \
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v6.yaml \
  --resource-corpus docs/research/data/autoresearch_evaluation_resources_v6.yaml \
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

Result registration still does not alter an existing manuscript. A subsequent
`project paper build|build-draft|build-revision --evaluation-result-id <id>`
must materialize a new paper with a self-hashed
`SCIENTIFIC_EVIDENCE_BINDING.json`. It binds every other paper artifact plus the
exact result bundle, result set, and deterministic assessment. The review packet
then hashes that sidecar with the rest of the paper. This ordering prevents a
pre-result draft or pre-result review from inheriting scientific completeness.

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
  --manifest configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v6.yaml \
  --output /tmp/deepseek-v41-cell-plan.json
```

The compiler generates opaque cell and review-blind IDs, preserves declared
matrix order, binds every cell to the proposal, task-asset, adapter-preflight,
and API/checkpoint resource hashes, and reports cell-local plus protocol-wide
blockers. Its output fixes `authorizes_execution=false` and records that no
provider call, GPU work, or task download occurred. The current v6 proposal
produces 100 intended two-seed cells; none is launch-ready while task and
accepted-system adapter gates remain open. This makes the gap between a YAML
cell count and an executable cross-framework experiment explicit.

Static exact-commit translation review has now resolved one ambiguity inside
that open adapter gate. MLR-Agent and Agent Laboratory are real method
candidates, but their pinned releases cannot provide an unchanged-core, fully
matched `deepseek-flash` / `DeepSeek-V4.1-Flash` trajectory under the current
task and coding-role contract. Their content-addressed adapter contracts remain
blocked before upstream checkout or runtime implementation. Consequently v6
must not be approved as written. Preserving v6 as immutable evidence avoids
silently weakening “matched backbone”; choosing a common natively supported
backbone or a separately disclosed best-native-system design requires a new
proposal.

The `max_output_tokens_per_call` values in these proposals are per-experiment
ceilings, not a global SciTaste limit. The current V4.1 proposal reserves 32,768
output tokens per call, 1,500 requests, and fifteen million total tokens across
all 100 candidate cells. These are ceilings rather than targets and still require a
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

1. Freeze a source-disjoint MLR-Bench package-review pilot subset with starting
   brief bytes, licenses, source groups, runtime acquisition rules, and output
   package hashes. Separately qualify MLRC-Bench or another fixed-scorer source
   before proposing any objective-progress lane.
2. Choose a common backbone actually supported across at least two accepted
   external methods, or preregister a separately labelled best-native-system
   design with model effects acknowledged; create a new immutable proposal for
   that decision. Then prepare exact direct-agent invocations and implement only
   adapters whose static contracts pass. Unavailable systems remain unavailable
   rather than receiving a pseudo-implementation.
3. Instantiate the package-preference protocol with common tools, repair
   budget, telemetry, blinded artifacts, and the later pilot-informed formal
   power analysis. Starting anchors and failure floors belong only to the
   separate objective-progress protocol.
4. Secure the blinded expert rubric, reviewers, conflict checks, and
   adjudication path.
5. For Zhipu, resolve exact dated pricing and record the authenticated served
   revision. For DeepSeek, perform an
   authenticated identity preflight immediately before launch because the API
   name is a rolling alias.
6. For the GPU lane, review the recorded remote inventory, define the checkpoint
   transfer/archive plan within the remaining 59 GB, then transfer and verify the
   copied tree hash only after approval. No task data currently fits inside that
   authorization.
7. Present the regenerated exact manifests and their proposal hashes to the
   project owner. Run one matched block only after explicit approval; require a
   second approval for scale-out.
