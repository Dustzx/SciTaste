# E2 MLRC Perception Native Pair v1

This protocol defines the first executable boundary for the title-critical E2
study in `scitaste-iclr2027-capability-driven-autoresearch-program-v4`. It does
not authorize a run. The content-addressed source of truth is
`configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v1.yaml`.

## Scientific question and minimal contrast

The first pair asks whether SciTaste's learned lifecycle Scientific Taste
policy improves scorer-owned held-out research progress over the same native
executor with the policy weight set to zero. The external system names map to
the already implemented H4 arms:

| E2 system | Native condition | Policy weight |
| --- | --- | ---: |
| `scitaste-native` | `full-scitaste-learned-policy` | 1.0 |
| `native-base` | `native-base-without-learned-taste` | 0.0 |

Both arms use the same exact agent model, task bytes, task-model architecture,
random initialization and seed, prompt, information, tools, editable surface,
time, token, GPU, CPU/RAM/disk, repair, and stop envelopes. Execution is
counterbalanced and sequential on the same device pair. Failed formal cells are
retained and are not silently retried. This is a causal within-native comparison,
not a comparison against AutoResearchClaw or an external framework.

One task cannot establish cross-task generality. B1 supplies the first
title-relevant hidden-score pair; B2 may expand only after B1 variance, failure,
and cost evidence yields a frozen clustered-power design.

## Actual workload

The acquired MLRC Perception task is temporal action localization over fixed
multimodal feature arrays, not a vision-language generation workload. Its task
model is the benchmark's `LocPointTransformer`: 768-dimensional input, 63
classes, batch size 16, 50 training epochs plus 5 warm-up epochs, and mean
average precision at tIoU 0.1 through 0.5. Training begins from deterministic
random initialization with seed 1234567891; there are no external initial task
weights. The trained cell checkpoint is frozen before held-out inference.

The development view is about 305 MiB and the scorer-side held-out view about
759 MiB. The tracked runtime binds the exact source commit, split hashes,
Python 3.12 package overlay, development entrypoint, inference entrypoint,
objective scorer, and scorer-parity receipt. These sizes are current observed
inputs, not total run-output ceilings.

## Agent model policy

The research/code agent must reason over Python and experiment evidence, edit a
repository, obey structured schemas, use bounded tools, cite evidence over long
contexts, and run reliably twice under a matched contract. It is not the task
model. Model choice is made role by role on task-excluded conformance data;
MLRC development or held-out outcomes cannot select it.

No E2 B0 or B1 agent is selected merely because its checkpoint is already on a
host. DeepSeek V4 Flash, GLM-5.3-Flash, the exact Qwen3.5-4B tree,
Qwen3-VL-8B, and other inventory candidates remain eligible. Qwen3-VL-2B is
only a low-cost lower bound and cannot become the default. A new model is
downloaded only if the task-excluded role gate or resource feasibility leaves a
real gap: one resource up to 10 GiB uses the owner's standing download authority;
a larger resource requires a new owner notice. Every selected checkpoint must
also pass identity, license, load, generation, context, structured-output, and
24-GiB-device feasibility gates.

## Compute and storage envelope

The host supplies eight RTX 3090 devices, but the first matched pair allocates
two devices per active cell and runs at most one cell at a time. One device is
reserved for a local research/code agent and one for task training/inference;
if task-excluded selection chooses a hosted agent, the exact B1 budget must be
refrozen instead of spending the reserved agent GPU by habit.

| Block | Evidence use | Cells | Ceiling per cell | Aggregate ceiling | Disk ceiling |
| --- | --- | ---: | ---: | ---: | ---: |
| B0 | development-only full-loop shape | 2 | 2 GPUs × 1 hour | 4 GPU-hours | 30 GiB |
| B1 | formal paired hidden endpoint | 2 | 2 GPUs × 4 hours | 16 GPU-hours | 100 GiB |

B0 must exercise every interface, including paper review and a revision-return
route, using development-only scoring. It cannot be cited as a real held-out
effect. B1 starts only after B0, model identity, budgets, and the exact manifest
hash are frozen and approved.

## Hidden scoring firewall

The candidate process receives the label-redacted inference projection. It
does not receive the scorer, reference paper, labels, or hidden score. Candidate
code, environment, task checkpoint, and inference parameters freeze before
inference. The isolated scorer receives the original label bytes and only the
prediction artifact whose SHA-256 was frozen by inference. It has no network
and opens one formal score per candidate. The score cannot update the current
formal policy, trigger a favorable retry, select a model, or determine early
stopping.

## Automated project handoff

The inspector verifies that the current project is at revision 602 or later and
that its selected run is the v4 capability-driven controller. The controller
then owns this complete chain:

1. acquire, quarantine, license, and freeze task splits;
2. select role models on task-excluded data;
3. generate and lock the idea and experiment plan;
4. execute development work and freeze the candidate;
5. run isolated inference and scorer-owned hidden measurement;
6. admit results and contradictions into the project evidence graph;
7. build a claim-evidence-linked paper;
8. obtain two identity-distinct AI reviews and adjudicate disagreements;
9. route objections back to experiment design, execution, analysis, or writing;
10. revise, conduct final AI review, and freeze the complete package.

The manifest contains argv arrays for the existing project controller, native
H4 preparation/campaign, MLRC development/inference/scoring, result admission,
paper build, review, and revision interfaces. Angle-bracketed values are
content-addressed outputs created by the preceding phase, not shell variables or
permission to execute.

## Static inspection and remaining launch gates

Compute the current manifest SHA-256 and pass it explicitly:

```bash
E2_MANIFEST_SHA=$(sha256sum configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v1.yaml | cut -d' ' -f1)
.venv/bin/python3.12 -m scitaste.evaluation.e2_prelaunch \
  --manifest configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v1.yaml \
  --manifest-sha256 "$E2_MANIFEST_SHA" \
  --workspace-root .
```

The current static handoff is closed. Actual execution remains blocked on an
exact selected-model load/endpoint preflight, exact B0 role attestation, owner hash
approval, real GPU baseline reproduction, B0 completion, task-excluded B1
selection, exact B1 model/budget freeze, and B1 owner approval. The inspector
performs no download, model load, generation, API call, GPU work, benchmark
execution, or hidden-label read.
