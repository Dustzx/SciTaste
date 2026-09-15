# MLRC Perception split runtime

Status: **development/scorer adapter-ready; no experiment or GPU launch authorized**.

`mlrc-perception-temporal-action-loc-v2` closes the task-specific bridge from
the already materialized MLRC Perception bytes to an executable Python 3.12
development path and a label-isolated held-out path. It preserves upstream
commit `0d26417034811d2d4587646c4520cc305ea09dd6` and the original development
and held-out view hashes. It does not modify the historical v1 task spec or its
materialization receipt.

The held-out path has two processes:

1. The candidate inference sandbox receives the two test feature directories
   and a deterministic metadata-only JSON. Every `action_localisation` list is
   empty. The original 35,440 labels, timestamps, and action metadata are not
   mounted, and inference emits a hash-bound prediction artifact rather than a
   score.
2. The independent scorer receives only the frozen prediction bytes and the
   scorer-owned original test JSON. Both SHA-256 values are required. It imports
   no workspace or candidate module, rejects malformed/non-finite/out-of-taxonomy
   predictions, and emits one replayable objective receipt.

The scorer implements the fixed upstream interpolated temporal-detection mAP at
tIoU 0.1, 0.2, 0.3, 0.4, and 0.5. A 126-prediction fixture (one TP and one FP per
each of 63 labels) was evaluated with both the new scorer and the fixed upstream
`ANETdetection` over the same test JSON. Every threshold and the average matched
within absolute tolerance `1e-15`; average mAP was
`0.05726421058733953`. A separate empty-prediction negative-control scored zero.
These are scorer qualification checks, not benchmark or method results.

The local environment is a 69-MiB content-hashed Python 3.12 overlay on the
repository environment. It imports the real task modules and executes the
compiled `nms_1d_cpu` operator on CPU. This establishes adapter/import
compatibility, not numerical equivalence to the upstream Python 3.11 Conda
environment and not baseline reproduction. The exact overlay, parity receipt,
and runtime projection live in ignored project outputs.

Inspect or reconstruct the runtime without a model call:

```bash
.venv/bin/python -m scitaste.evaluation.mlrc_perception_runtime inspect \
  --manifest configs/evaluation/task_runtime/mlrc_perception_temporal_action_loc_v2.yaml \
  --workspace-root .

.venv/bin/python -m scitaste.evaluation.mlrc_perception_runtime prepare \
  --manifest configs/evaluation/task_runtime/mlrc_perception_temporal_action_loc_v2.yaml \
  --workspace-root . --allow-projection
```

Before a scientific run, a new campaign must bind this v2 manifest and runtime
receipt, freeze the candidate/checkpoint before inference, reproduce the real
development baseline and one held-out candidate under the selected GPU
environment, and receive explicit cell-level launch authority. Meta-Learning
remains separately blocked by AWA per-image license coverage.
