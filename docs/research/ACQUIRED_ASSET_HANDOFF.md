# Acquired resources to Native tasks

## Model-selected handoff

If resource work was pending or interrupted after a plan was accepted, use
`scitaste resource materialize-planned-resources --project PROJECT --planning-run RUN`.
Add `--allow-network-download` only when missing resources should be fetched under
the declared allowance. This does not call the planner or execute research again.
`ACQUISITION_OUTCOMES.jsonl` retains changing resource outcomes;
`ACQUISITION_RESULT.json` exists only after resource preparation succeeds.

An acquisition option is a project JSON object with `request`, `workspace_root`,
`resource_template`, `role`, and `use_constraints`. Paths are relative to the project;
workspace_root must contain the project. The source request fixes URLs/revisions,
item IDs, license declarations and byte ceilings. Models see only declared choices.

Pass repeatable `--acquisition-option` to
`python -m scitaste.project.research_planning`. `--acquire-selection` materializes an
accepted selection; `--allow-network-download` separately permits missing resources
to be downloaded. Without it, existing receipts are reused and missing resources
remain awaiting enablement. Selection never starts a research experiment.

Native `project.research_cycle` supports `--next-acquisition-option`,
`--acquire-next-resources`, and the separate network switch for post-paper planning.
The original cycle's inputs remain pinned. Use a new cycle identity to change them.

`model-acquisition-handoff-v1` in the self-development project exercised actual model
selection and receipt reuse in one call; new network acquisition was not exercised.

## Acquire or reuse, then prepare

`scitaste resource acquire-workspace-resources` accepts the same project/request,
selected items, constraints, role and optional template, plus `--workspace-root`
and `--output`. Receipt location is derived from the bound acquisition request.
Completed receipts are reused without network. A missing receipt requires
`--allow-network-download`; `--maximum-download-bytes` defaults to 10,000,000,000
and cannot exceed that ceiling. The entire declared request is downloaded, not just
the selected handoff items; the declared aggregate must fit the allowance.

Reinvoke the same job with identical inputs to resume after a terminal failure.
Do not launch another process while its lock is held. The job retains up to three
attempts and never loops through network retries automatically. Completed jobs
verify the recorded files before reuse. Existing downloader transactions are atomic;
this wrapper does not add byte-range resume or package extraction.

Actual reuse-only example is registered as
`evaluations/acquisition-workspace-cycle-v1` in the self-development project.

## Prepare already acquired items directly

`scitaste resource prepare-acquired-assets` bridges existing acquisition receipts
into the Native planner's resource bundle. It does not run a benchmark.

Required arguments are `--project`, `--request`, `--receipt`, `--output`, repeatable
`--item` IDs, and `--use-constraints`. Optional `--resource-template` reuses an
existing project bundle's harness/backend/runtime envelope; `--role` defaults to
`reference` (also `data` or `starter-code`). Existing output is never overwritten.

The result contains `ASSETS.json`, optional `WORKSPACE_RESOURCES.json`, and registered
`RESULT.json` provenance. Pass the resource bundle to the `--workspace-resources`
option of `python -m scitaste.project.research_planning`.
The planner may select declared assets and compile a task through its existing
`--compile-selection` path. Execution still requires the ordinary task authorization.

Origin revision, license scope and actual-byte hashes come from the original request
and receipt. No directory scan becomes an implicit asset selection. Download-only
authority is not converted into ingestion/execution authority; use constraints
remain explicit, and package extraction/hidden splits are not handled by this step.

Actual local case: the self-development project's
`evaluations/acquired-metadata-workspace-handoff-v1` binds one retained public
InnovatorBench task-configuration file for discovery reference only. It does not
establish benchmark-data availability, formal selection or executable readiness.
