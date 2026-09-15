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

The project-level successor is
`configs/evaluation/model_roles/scitaste_b0_bytebound_campaign_v1.yaml`. It
binds seven development-only case files byte-for-byte, declares their source
groups disjoint from every E1--E4 formal or held-out source group, and expands
the selected 4B/8B/API/embedding candidates into 46 per-case, per-repetition
requests. Preparation writes `CAMPAIGN_PLAN.json`, `MODEL_ROLE_PLAN.json`,
`CASES.json`, and one exact JSON request per dispatch beneath the owning project
run. The plan accounts for 20 API requests, 26 local requests, at most 6 local
GPU-hours, and 1.5 GiB of per-request evidence allowance. It performs no model
load, provider call, download, or benchmark execution.

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

scitaste model-role prepare-campaign \
  --spec configs/evaluation/model_roles/scitaste_b0_bytebound_campaign_v1.yaml \
  --project-id <project> \
  --run-id <registered-run> \
  --outputs-root outputs \
  --repository-root .

scitaste model-role campaign-status \
  --plan outputs/projects/<project>/runs/<registered-run>/model_role_conformance/\
scitaste-b0-bytebound-conformance-v1/CAMPAIGN_PLAN.json

scitaste model-role campaign-request \
  --plan <CAMPAIGN_PLAN.json> \
  --request-id <request-id>
```

Generative requests include a binding template and `next_command` for the
existing durable `model-node runtime execute` CLI. The caller must still render
the runtime config/profile-set files and pass the indicated `--allow-live` or
`--allow-local` flag. The embedding request is deliberately `blocked` until its
real local dispatcher emits `scitaste-conformance-execution-v1`; no synthetic
or test receipt is substituted. `campaign-status` discovers only
`receipts/<request-id>/RUN_RESULT.json`, validates those bytes through the
normal compiler, and reports `request-prepared`, `launch-ready`, `blocked`, or
`complete`.

Campaign status distinguishes `request-prepared` from `launch-ready`. A request
with `<RUNTIME_CONFIG_JSON>` / `<PROFILE_SET_YAML>` placeholders remains only
`request-prepared`; a local request additionally requires a resolved immutable
checkpoint hash and revision. Only a request with materialized, hash-bound
runtime/profile files and (for local models) exact checkpoint identity may be
reported as `launch-ready`. Consequently the initial dry plan's next action is
to materialize executor bindings, never to dispatch a model directly.

An empty receipt set is valid for planning/status and reports all role/scope
bindings missing;
it never promotes inventory presence into a selection. Formal runs bind the
selection manifest's `selection_sha256` and exact per-role fields rather than a
mutable model alias or a program-document content hash.
