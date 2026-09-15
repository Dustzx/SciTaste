# Model-role conformance and selection

SciTaste selects models by role from task-excluded evidence, not by checkpoint
availability or a single global default. The five required roles are
`research_agent`, `code_agent`, `judge`, `embedding`, and `task_training`.
Research and code models may coincide, but a judge sharing the selected
generator identity makes the compiled manifest ineligible for headline claims.
Agent roles use an `agent-global` scope. Embeddings are selected per retrieval
corpus and task-training/backbone models per benchmark or task family, so a SAM,
Qwen, or InternVL result can never become a meaningless project-global task
model.

The B0 candidate suite is
`configs/evaluation/model_roles/scitaste_b0_model_role_conformance_v1.yaml`.
It includes the currently registered hosted models and local 4B/8B candidates,
an embedding model, and multiple task-runtime candidates. It is a no-run example:
it neither selects a model nor authorizes API, GPU, download, or training work.
Its conformance IDs are planning labels whose task bytes have not yet been
frozen, so status reports `executable_for_conformance=false` and refuses any
receipt until a byte-bound successor suite is created.
Qwen3-VL-2B has no default or privileged role in this suite.

## Evidence flow

1. `plan` verifies the current model inventory and role-contract hashes, expands
   each candidate's profile and budget, and freezes seven criteria: schema and
   tool adherence, success, context fit, latency/cost, reproducibility, and task
   fit.
2. A separate authorized runner executes only the frozen conformance tasks. It
   must write one `ModelRoleConformanceRunResult` with an exact hosted temporal
   identity or immutable local checkpoint identity and the frozen profile and
   budget hashes. Every result must bind exactly three content-addressed files:
   an actual executor receipt, a byte-bound case manifest, and case-level results.
   A validator registry parses native model-node or benchmark receipts, or the
   strict self-hashed conformance-runner schema; booleans and inventory entries
   alone are not accepted as execution evidence.
3. `compile-selection` verifies every receipt and evidence byte, rejects task or
   source-group crossover into formal/heldout partitions, aggregates only actual
   receipts, and deterministically selects the highest-scoring qualifying
   candidate for each role.
4. The resulting `ModelRoleSelectionManifest` is the project-controller input.
   Each role binding carries the resource ID, exact identity, complete profile,
   complete budget, aggregate score, and evidence hash. The manifest grants no
   execution authority; the controller must still use its normal execution gate.

## Commands

```bash
scitaste model-role plan \
  --suite configs/evaluation/model_roles/scitaste_b0_model_role_conformance_v1.yaml \
  --output outputs/projects/<project>/model-roles/B0_PLAN.json

scitaste model-role compile-selection \
  --plan outputs/projects/<project>/model-roles/B0_PLAN.json \
  --receipt outputs/projects/<project>/model-roles/receipts/<run>.json \
  --evidence-root outputs/projects/<project>/model-roles \
  --output outputs/projects/<project>/model-roles/SELECTION.json

scitaste model-role status \
  --plan outputs/projects/<project>/model-roles/B0_PLAN.json \
  --receipt outputs/projects/<project>/model-roles/receipts/<run>.json \
  --evidence-root outputs/projects/<project>/model-roles
```

An empty receipt set is valid for planning/status and reports all role/scope
bindings missing;
it never promotes inventory presence into a selection. Formal runs bind the
selection manifest's `selection_sha256` and exact per-role fields rather than a
mutable model alias or a program-document content hash.
