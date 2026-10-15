# First real visual-fork qualification: MLRC Meta-Learning development

Updated 2026-09-25. This is an execution contract and preparation record, not
a completed SciTasteBench case or a CVPR effectiveness result.

The shared prefix is the unchanged MLRC-Bench Meta-Learning development task:
20 qualified Meta-Album image datasets, official 1,000-task development
scorer, and the upstream randomly initialized ResNet-18 ProtoNet method with
seed 98. The prior local baseline scored 0.207025 normalized balanced
accuracy, but **must not** be used as the matched score of a future remote
branch. Both arms need fresh remote runs in the same environment.

The scientific decision is whether cross-domain variation in feature norm
justifies changing the prototype metric. The two frozen actions are:

| Action | Executable change | Scientific interpretation |
|---|---|---|
| `euclidean-prototypes` | Exact upstream method bytes | Preserve unnormalized squared Euclidean geometry. |
| `unit-normalized-prototypes` | Normalize query and class prototypes before the same squared Euclidean distance | Test angular rather than feature-magnitude geometry under domain shift. |

Only `helpers_protonet.py` differs between the branches. Their model, task
configuration, training-task count, validation-task count, random seed, data,
and official scoring code are otherwise shared. The exact source and branch
file hashes are frozen in the ignored project artifact
`evaluations/scitastebench-mlrc-meta-visual-fork-development-v1/MANIFEST.json`.
The preparer refuses source-model drift or any additional branch file change.
The metric and execution ceiling must be identical for both arms; score all
1,000 official development tasks and retain failures as failures.

Next execution uses the registered remote 8×RTX 3090 host, **one available
card per arm, sequentially**, with a proposed 20-minute wall ceiling per arm
and a no-retry, preserve-partial-output rule. Transfer only the qualified
development data and frozen method/runtime bytes. Recheck disk, GPU ownership,
Python/CUDA dependency compatibility, and the exact official scorer before
launch; do not open Meta-Album set 2/AWA or alter the official test split.
The 2026-09-25 remote observation found all eight cards active, so no GPU
branch was started and the local GPU is not a fallback.

An exclusive, content-hashed execution bundle now exists at the ignored
`evaluations/scitastebench-mlrc-meta-visual-fork-remote-bundle-v4/`. Its v1
predecessor did not bind every transferred image byte, while v2 retained a
relative-output-path error in the runner. V4 additionally preserves valid
negative chance-normalized official scores; all method/scorer/data bytes are
unchanged from v3. The bundle copies
only the official runtime/scorer, two frozen method branches, standalone
runner, and `requirements/mlrc-meta-remote-py312.lock`; the 2.0 GB image data
remains a separate transfer. A deterministic digest binds all 112,321 files
and 1,824,250,806 payload bytes including the split declaration; the remote
runner verifies the same digest before spending GPU time. It refuses an occupied GPU, requires a
dedicated Python 3.12 environment with CUDA PyTorch, preserves partial logs,
and accepts a branch only after all 1,000 official predictions and
`overall_score` are present. The system Python 3.12 on the remote host lacks
PyTorch, and the later 2026-09-25 observation found all eight GPUs at 100%
utilization with 36.4 GB storage free at that historical snapshot.

The dedicated remote environment is now installed at
`/local/scitaste-runs/mlrc-meta-dev-20260925/venv`: Python 3.12.3,
torch 2.5.1+cu124 and torchvision 0.20.1+cu124. Both the frozen bundle and
112,321 data files were transferred and verified; the local environment receipt
is `outputs/resources/REMOTE_MLRC_META_ENVIRONMENT_20260925.json`. No local
GPU was used. An earlier waiting-only queue was cancelled before any experiment
to correct the score reader. The former remote queue `pair-v2`, PID 3509686,
started at 2026-09-25 12:07:57 UTC. It allows 3,600 total waiting seconds,
then at most 1,200 seconds per arm on the same card, with no retry. It refuses
cards with a compute process even when their instantaneous utilization is low.
It was cancelled while still waiting, with zero arms, following the user's
replacement-host instruction. The unchanged pair subsequently completed on `4090-2`
GPU 3, queue PID 641918, below
`/data/zfx/scitaste/mlrc-meta-dev-20260925/pair-v1`. Both arms use the same
RTX 4090 and isolated Python 3.12.12 environment. The project evaluation record
`scitastebench-mlrc-meta-4090-resource-amendment-v1.json` preserves this change;
do not pool cross-host timings. The Euclidean branch has now completed all
1,000 predictions and official scoring: normalized balanced accuracy
**0.1848735779036495**, total ingestion/scoring time **512.0777 seconds**.
The normalized branch also completed all 1,000 predictions and scoring:
**0.1062983802557951**, **510.9856 seconds**. The normalized-minus-Euclidean
difference is **-0.0785751976478544**. Direct selected the better action;
planning has utility-scaled regret 0.0392876 versus direct's zero. Both choices
preceded execution, but this is only one development source task and no Taste
arm. The official result join is `DECISION_RESULT.json` under
`evaluations/scitastebench-mlrc-meta-remote-4090-pair-v1/`. The queue is complete
and its PID has exited; no retries were used.
The historical local score 0.207025 is not a matched control and is not pooled.

After observing this baseline, the existing research-patch model node was
extended to the Meta-Learning method surface and called once with Qwen3.8-Max.
It proposed cosine logits in `helpers_protonet.py`, consuming 10,747 input and
790 output tokens under a USD 0.157404 conservative cost ceiling. The complete
input/response and preparation receipt are retained at
`evaluations/mlrc-meta-native-candidate-development-v1/`. This is a real
model-generated patch component, not a complete SciTaste Native agent run.
Its forecast of improvement is unmeasured.

The proposed cosine logits substantially overlap the now-completed
normalized-distance hypothesis. For nonzero unit embeddings the latter is
`2*cosine - 2`, so the same embedding has the same argmax but a different
cross-entropy scale and training trajectory. The proposal is therefore held
out of the current campaign: the nearby normalization result is adverse and
does not justify an automatic temperature sweep. No candidate GPU attempt has started,
and the existing score cannot be attributed to this unexecuted candidate.
`EXECUTION_DECISION.json` retains the original deferral; the subsequent
`OUTCOME_REVIEW.json` records the post-outcome decision without rewriting it.

The completed fork is exported with `export_mlrc_meta_development_dataset.py`
to `evaluations/scitastebench-mlrc-meta-development-dataset-v1/`. The common
participant/scorer interface reproduced both original method scores, with
four exact image inputs and one independent source task. The upstream code
license does not license dataset images; this remains an internal consumed
development package, not an authorized public release.

The pre-experiment image decision package is
`evaluations/scitastebench-mlrc-meta-pre-experiment-decision-v1/`.
Four deterministic input images illustrate the source domains; no feature-norm
measurement or candidate outcome is claimed. Direct Qwen3.7-Max selected
Euclidean prototypes; two-stage planning selected normalized prototypes.
The three actual calls used 4,958 tokens and USD 0.061392 under the conservative
configured liability ceiling, not a measured dollar invoice. The queue binds
both decision receipts before either experiment starts. These initial calls
retain selected actions, model identities, usage and response hashes but not
raw response bodies or intermediate estimated scores; the runner now records
those for subsequent runs. Do not claim exact replay of these initial calls.

After copying the completed remote pair into the corresponding project
evaluation directory, `scripts/score_mlrc_meta_decision.py` joins the frozen
decisions to exact official score files and emits one-task decision regret.
It preserves raw normalized accuracy and maps utility as `(score + 1) / 2`
to support negative official values. The v3-to-v4 launcher correction is
accepted only when all method, scorer, data and dependency bindings match.
`collect_mlrc_meta_remote_pair.py` performs this copy and join, verifies live
queue identity, and updates the project run status. It also preserves explicit
cancellations rather than interpreting a stale waiting state as a live job.

This is a **CVPR-facing evidence slice**, chosen because an unchanged external
visual-research task supplies executable outcomes and tests the project in the
conference's field. It does not redefine SciTaste as a vision-only system.
The paper's domain-general method claim additionally needs complete-system
evidence on at least one independent non-vision task family (and should narrow
the claim if such transfer fails). This single fork neither establishes that
transfer nor substitutes for whole-agent comparisons.

Even after both arms run, this is one visual **development qualification
fork**, not 1,000 independent research tasks or a validated cross-domain
SciTasteBench release. Its policy-visible request and independent choices now
exist, but its images are input examples rather than measured error slices.
A richer benchmark
requires additional source-task groups, feasible action semantics, matched
budgets, release rights, and prospective untouched populations.
