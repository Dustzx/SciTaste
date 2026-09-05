# Window 2 Dispatch: Model-Node Pilot Orchestration

Assignment token: `W2-model-pilot-orchestration-20260905-r1`

Status: `in progress`

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/model-nodes`
- branch: `feat/model-node-pilot-orchestration`
- base: the main commit containing this dispatch document
- do not work in `/home/good/zfx/papers/SciTaste`

## Objective

Turn the existing library-only bounded model-node pilot into a production-facing,
fail-closed orchestration path. A user must be able to plan, execute, resume, and
inspect an offline/replay/live-capable pilot through the SciTaste CLI while all
reports and recordings are owned by one `ProjectRuntime` run. This is an
engineering-pilot interface, not an effectiveness claim.

This is one cohesive Epic. Do not reduce it to a thin CLI wrapper around test
fixtures.

## Owned paths

- `src/scitaste/model_nodes/` for orchestration/config/report additions;
- a new focused CLI module beneath `src/scitaste/` and the smallest necessary
  registrations in `src/scitaste/cli.py`;
- `configs/model_nodes/` for versioned non-secret examples;
- `tests/model_nodes/` and focused `tests/integration/` coverage;
- `docs/BOUNDED_MODEL_NODES.md`.

Do not edit common roadmap, architecture, changelog, README, generative-UI code,
full workflow code, AutoResearchClaw, or generated `outputs/`.

## Required behavior

1. Add strict configuration loading for the committed pilot protocol, condition
   bindings, optional external manual-intervention measurements, optional
   independent-review evidence, and the compatible live-backend configuration.
   Unknown fields, unsafe paths, identity drift, and protocol-hash drift fail.
2. Add CLI operations with an internally consistent namespace for at least:
   plan/dry-run, execute-or-resume, and status/verify. Exact names may follow the
   existing CLI style, but must be documented and covered by integration tests.
3. Register a unique run through `ProjectRuntime`; keep the canonical report,
   exact recording, verification record, configuration/protocol hashes, and
   failed-attempt evidence below that run. Never write a cross-project path.
4. Make execution resumable only at auditable case boundaries. Reuse a completed
   case only after its input, protocol, backend identity, response/measurement
   evidence, and predecessor chain validate. Archive incomplete attempts and
   reject tampered completed evidence.
5. Require an explicit live opt-in in both configuration and CLI. Dry-run,
   status, tests, and default execution must not contact a provider. Never read a
   credential until a live case actually starts.
6. Preserve the four real condition types. Scripted/replay results cannot satisfy
   live gates; fixtures cannot satisfy external measurements or independent
   review. A missing live binding must produce a planned/blocker outcome, not a
   crash or substituted result.
7. Publish atomically and refuse overwrite. Concurrent attempts against one run
   must conflict or serialize without losing evidence.
8. Return machine-readable CLI summaries containing project/run identity,
   protocol/report hashes, completed/planned/blocked counts, cost/token/latency
   telemetry when measured, and the precise acceptance state.

## Tests and acceptance

At minimum test:

- dry-run is mutation-free and network-free;
- a complete scripted + record/replay run produces a verifiable report;
- a live condition without explicit opt-in remains planned/blocked;
- external measurement and review inputs are content-addressed and cannot be
  replaced by fixture values;
- interruption resumes a valid prefix and archives an incomplete case;
- changed protocol/config, changed backend identity, corrupt report/recording,
  stale project revision, and an existing destination fail closed;
- two writers cannot silently overwrite the same run;
- no secrets appear in reports, exceptions, CLI JSON, or test snapshots.

Run focused tests, Ruff for owned files, and the complete `make check`. No real
network call is authorized by this assignment.

## Handoff

Return a clean feature branch with cohesive commits and the standard handoff
fields from `docs/tasks/README.md`. Explicitly list any remaining step needed for
a real `zhipu-direct/glm-5.3-flash` execution. Do not merge or push `main`.
