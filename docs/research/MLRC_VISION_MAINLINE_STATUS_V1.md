# MLRC vision mainline: development outcomes and next independent task

Updated 2026-09-24. This is a project-side experiment record, not text for the
CVPR main paper. The evidence below is **consumed development**: it cannot fill
the manuscript's formal system or mechanism table, and its task cannot be
presented as a fresh held-out confirmation of a policy revised after seeing it.

## What actually ran

The self-development project's `evaluations/mlrc-perception-research-arms-development-v1/REPORT.json`
records a real, scorer-owned MLRC-Bench temporal-action-localisation development
comparison on one task. Official upstream baseline: 0.233919; same-runtime
SciTaste Native Base: 0.241669; equal-source Raw context: 0.235708; and the
earlier taste-guided abstraction: 0.243956. The last arm predates the shared
state-conditioned TasteControlPacket, so it is **not Full SciTaste**. The Raw arm
had one failed execution and six preparation attempts before its successful
score; those costs cannot be silently removed from interpretation.

`evaluations/mlrc-perception-adaptive-policy-pair-development-v1/PAIR_RESULT.json`
then executed a separate Native policy pair: OFF scored 0.260075, selected a
PROBE and edited the loss; ON scored 0.249452, selected an EXPERIMENT and edited
the configuration. ON minus OFF was **-0.010622**. This is an adverse one-task
development result, not a formal estimate of Scientific Taste or a general
policy rejection. It is evidence that merely activating the learned head can
change the executed research action without improving the outcome. Both reports
explicitly mark `formal_evidence_eligible=false` and `heldout_opened=false`.

The latest inspected policy refresh is v19: its `policy_application_ready=true`
means it has an eligible adaptive head, not that it has passed an effect test or
successor selection. Do not use this readiness bit as a benefit claim; do not
retune and re-test the same Perception development task as independent evidence.

## Next task, without weakening data rights

The pinned official MLRC-Bench `meta-learning` task is cross-domain few-shot
image classification. Its `scripts/prepare.py` uses Meta-Album sets 0 and 1
for development, and adds set 2 for test. All 20 development archives are
already acquired; the missing AwA2 per-image license records concern AWA in
set 2. A **development-only** materialization and baseline run can therefore
be constructed without ingesting AWA or changing the official development
split. This does **not** authorize the official held-out test, omit AWA from
that test, or establish a second formal task outcome. Keep the existing AWA
ingestion gate intact. The [AwA2 source](https://cvml.ista.ac.at/AwA2/) says
individual image licenses are in the original image archive; Meta-Album's
[AWA page](https://meta-album.github.io/datasets/AWA.html) gives only a broad
Creative Commons label, not the missing per-image mapping.

The development-only, receipt-bound projection is now materialized at
`outputs/projects/scitaste-self-development/evaluations/materializations/mlrc-meta-learning-development-v1`.
Its `MANIFEST.json` records 20 datasets (ten per set), 1,824,250,419 expanded
bytes, all exact acquired archive hashes, and `heldout_opened=false`. The local
Python 3.12 environment uses torch 2.5.1+cu124 and torchvision 0.20.1+cu124.
The unchanged official `my_method` completed all 1,000 development tasks on
one RTX 3090, scoring **0.207025 normalized balanced accuracy**; its reported
method runtime, excluding scoring, was 361.24 seconds. The exact native score
file and model source hashes are retained in
`evaluations/mlrc-meta-learning-upstream-baseline-development-v1/BASELINE_RESULT.json`.
The MLRC repository's historical development baseline is 0.182165, but this
single reproduction differs numerically and is not a method improvement or
same-environment matched comparison. Next connect the same native executor and
named real agent in this development environment.
Hold the set-2 test bytes outside the agent workspace. The main system study
still needs a **prospectively frozen, independent task population**, matched
resource accounting, valid external-system runs, and visual error analysis.
Temporal action localisation uses precomputed video features; it alone cannot
support a broad image-grounded scientific-judgment claim.

The first Meta-Learning visual-fork qualification now has two exact,
same-prefix method branches prepared: original Euclidean ProtoNet geometry
and L2-normalized prototype/query geometry. See
`docs/research/MLRC_META_VISUAL_FORK_DEVELOPMENT_V1.md`. The original 3090
queue was cancelled with zero arms because all cards were occupied. The user
supplied `4090-2`; an isolated Python 3.12 environment and the unchanged data
are now staged under `/data/zfx/scitaste/mlrc-meta-dev-20260925`. Its `pair-v1`
queue completed the first arm on GPU 3 (official normalized balanced accuracy
0.184874, 1,000 predictions, 512.08 seconds) and the second arm (0.106298,
1,000 predictions, 510.99 seconds). The queue is complete.
Real image-conditioned
direct/planning decisions were obtained before execution and choose different
branches. The historical local 0.207025 score is not a matched remote control,
and the matched pair favors Euclidean geometry by 0.078575. See the qualification contract
for the current PID, resource ceilings, and result-to-decision scorer.

The runtime now also supports `package-candidate`: a complete agent-generated
method tree can be frozen against the same official development runtime,
dataset identity and dependency lock, without choosing one of the two fixed
forks. The package binds claimed system revision, trajectory and budget-contract
hashes. These claims are not independently verified agent identities, and no
named external agent has run through this path yet. Generated code must be
admitted to an isolated execution workspace before live execution; a content
hash is not a security sandbox. The new candidate runtime now enforces
Bubblewrap isolation (no network, explicit read-only inputs, one selected GPU
and one writable output root). A real short CUDA probe on 4090 verified the
boundary without retraining; whole-agent orchestration remains unexecuted.
This interface does not change completed frozen fork bundles or authorize a
new experiment by itself. Aggregate RAM/disk quotas and formal hidden-label
isolation are outside this development boundary.

The remote bridge is now a handler of the existing `SciTasteNativeExecutor`,
not merely a standalone launcher. `scripts/run_mlrc_native_action.py` accepts
the serialized binding, research state and selected action; model output cannot
change remote paths or candidate identity through action parameters. Launch is
explicit, budget checked and at-most-once; reconnection observes the same job.
The actual Euclidean result was consumed through Native ANALYZE and its record
is under `evaluations/mlrc-meta-native-remote-feedback-v1/`. It is explicitly
a historical result analysis, not a new Native experiment. A complete Native
controller trajectory and a named external-agent trajectory remain next work.

The repository's `erasing_invisible_watermarks` task is another visual
candidate, but its own README says the bundled warm-up metrics are not the
competition's final evaluation. Its scorer must be independently qualified
before a score can appear in the same official-benchmark block. Do not repair
that scorer after observing outcomes and still call the changed endpoint the
unchanged official MLRC task.
