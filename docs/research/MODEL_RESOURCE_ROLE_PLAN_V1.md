# Model resource inventory and role plan

The tracked inventory is
`configs/resources/assets/model_role_inventory_v1.yaml`. It records what is
available, not what the paper must use. The local root currently exposes 16
model/component entries, including a tokenizer-only GLM asset, plus three
non-model project directories. Qwen3-VL-2B is an ordinary low-cost baseline
candidate with no preferred or headline status.

The model choice for each role must be frozen by a task-excluded conformance
window. Selection tasks cannot overlap any formal benchmark task used in the
reported development, validation, or test estimates. The gate checks role-level
quality, tool/schema adherence, runtime reliability, latency and cost under a
fixed budget. It also completes license, provenance, exact-identity, and bounded
load or endpoint checks. Inventory presence alone cannot pass the gate.

The full automated-research workflow uses separate roles: a research agent for
literature, hypothesis, experiment design, evidence synthesis, and writing; a
code agent for implementation and repair; an embedding model for retrieval; a
task-training model or component for GPU-backed benchmark execution; and an
independent calibrated judge only where deterministic scoring is unavailable.
These roles may use different models. A judge cannot produce the answer it
scores in the headline comparison.

Current APIs and local checkpoints form a candidate pool, not a closed menu.
New research, coding, judging, embedding, or task-specific models may be
downloaded when the scientific design or conformance result requires them.
Existing files become a cost or reproducibility preference only after scientific
equivalence is established.

`/media/sdb/wwh/models` is not visible from the local host at this observation.
It is therefore registered only as a pending synchronization source with the
older tracked inventory retained as provenance. No remote connection, transfer,
download, model load, GPU job, API call, or new weight hash was performed.
