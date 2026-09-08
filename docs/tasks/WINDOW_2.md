# Window 2 Dispatch: Tool Intelligence — Durable Project Loop

Assignment token: `W2-tool-intelligence-20260908-r3`

Status: `registered live study complete; independent review pending`

This assignment is authorized by the project owner on 2026-09-08 to continue
Tool Intelligence through a complete project-level development loop and report
measured improvements. It supersedes the integrated v2 dispatch. V2 is present
on `main` as `00b006b`; do not continue from the old feature head.

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/tool-intelligence-v3`
- branch: `feat/tool-intelligence-v3`
- base: `859e86540b8ccdb8ea778eae8a552bb7239c4240`

Do not merge, push, or rebase. The primary worktree has unrelated active work;
do not clean, reset, or overwrite it.

## Objective

Turn the v2 process-local, caller-bound execution slice into a durable,
project-owned Tool Intelligence loop:

```text
deterministic semantic-hotspot detector
  -> bounded model proposal
  -> deterministic admission
  -> durable single-action lease/claim
  -> project-bound read-only handler
  -> durable observation/postcondition
  -> deterministic accept/reject/escalate/re-plan
```

The model remains proposal-only. ProjectRuntime revision, ResearchState,
evidence status, budget, filesystem containment, tool registry, action lease,
observation admission, and all state transitions remain deterministic.

## Owned paths

- `src/scitaste/model_nodes/**`
- `tests/model_nodes/**`
- `configs/model_nodes/**` for disabled, non-secret examples
- `docs/TOOL_INTELLIGENCE.md`
- this dispatch document

The main window owns `full_workflow.py`, CLI routing, central roadmap,
architecture, changelog, README, board, generated outputs, and GitHub sync. The
child branch may provide a complete workflow bridge under `model_nodes/**` and
focused tests, but any final call site in a main-owned file is delivered as an
explicit integration step rather than edited concurrently.

## Work packages

### WP1 — Durable lease and observation runtime

1. Publish leases, claims, handler results, observations, and a hash-chained
   ledger below exactly one registered project run.
2. Use atomic exclusive claims and a project/run lock so two processes cannot
   execute the same lease concurrently.
3. Revalidate ProjectRuntime and ResearchState immediately before and after the
   handler call.
4. Recover a completed durable handler result without invoking the handler
   again. For a claim with no durable result, fail closed as ambiguous unless
   the registered first-party handler is explicitly deterministic,
   side-effect-free, and replay-safe.
5. Detect path/symlink escape, content tampering, changed handler identity,
   chain corruption, stale revision, duplicate lease, and interrupted
   publication.

### WP2 — Project-owned handler bindings

1. Define content-addressed project bindings for Knowledge JSONL, Evidence
   records, and registered-run metrics.
2. Resolve only normalized project-relative locators under the selected run;
   reject any symlink component, non-regular file, unregistered run, hash drift,
   duplicate record, unknown identifier, or oversized source.
3. Construct the existing three v2 handlers from verified bindings rather than
   caller-supplied arbitrary in-memory dictionaries.
4. Keep all handlers read-only, network-free, process-free, and unable to admit
   canonical evidence.

### WP3 — Deterministic hotspot workflow bridge

1. Provide a project-facing bridge that detects a named ambiguity from typed
   state, invokes or reuses a durable Tool Plan, leases one dependency-free
   action, executes/resumes it, and returns a typed decision record.
2. Support accept-as-advice, reject, escalate-to-human, and bounded re-plan. No
   observation becomes evidence or changes state automatically.
3. Limit the horizon, model/tool invocations, tokens, latency, output bytes, and
   cumulative cost. Preserve all known costs even when the observation is
   rejected.
4. Provide a narrow integration contract for the main-owned full workflow.

### WP4 — Reproducible improvement benchmark

Measure v2 versus v3 on the same fixtures and report, at minimum:

- restart duplicate-execution rate;
- crash-recovery success and ambiguous-call handling;
- stale/concurrent-result acceptance rate;
- project-locator escape/tamper rejection rate;
- manual-controller-step proxy per resolved hotspot;
- successful hotspot resolution rate;
- model/tool invocation count, token/cost evidence, and runtime overhead.

Do not convert engineering proxies into scientific-effectiveness claims. A
matched live-model study and independent domain review remain separate gates.

### WP5 — Verification and handoff

Run focused durability/adversarial/benchmark tests, all model-node tests,
`make check`, and `git diff --check`. Update `docs/TOOL_INTELLIGENCE.md`, commit
one or a small number of cohesive changes, and report exact metric deltas,
remaining limitations, and the main-window integration order.

## Exit gate

This child Epic is complete only when WP1–WP5 are implemented and verified on
the feature branch. The broader research goal remains active after integration
until a registered matched live-model evaluation and independent outcome review
support any claimed efficiency or scientific-quality improvement.

## Progress update — 2026-09-08

- WP1 implemented: project-run leases, atomic claims, handler-start/result
  markers, observations, attempt archival, hash-chained ledger, non-blocking
  cross-process lock, crash recovery, ambiguity fail-closed handling, telemetry,
  and structural verification.
- WP2 implemented: hash-pinned run-relative Knowledge, Evidence, and registered
  metrics JSONL bindings with strict no-symlink/no-escape/no-drift loading and
  built-in handler construction.
- WP3 implemented below `model_nodes/**`: typed semantic-hotspot detector,
  durable one-attempt bridge, exact decision reuse, deterministic step
  selection, accept/reject/escalate/re-plan outcomes, and per-attempt budgets.
- WP4 implemented: paired metric schemas, committed six-scenario protocol, and
  a measured integration benchmark. The current engineering result is 100% to
  0% restart duplicates, 0% to 100% exact crash recovery, 72.7% fewer external
  controller steps per resolved hotspot, and 37.5% fewer handler calls, at
  approximately 130 ms mean scenario overhead on the local one-pass fixture.
- WP5 implemented: 62 focused Tool Intelligence tests pass; `make check` passes
  formatting, lint, and all 886 repository tests. The final diff, owned-path,
  secret-pattern, JSON, and submodule-pin audits pass. The cohesive feature
  implementation is committed as `0012d669ccc7526553190e43372eba7ceaf00217`;
  all 198 model-node tests pass on that commit.

## Primary-window handoff

Window 2 has no remaining implementation item inside its owned paths. The
primary window must now review and integrate `0012d66`, wire the documented
bridge contract into the main-owned workflow, expose the durable decision and
telemetry locators, and run repository regression tests from the integrated
tree. Only after that integration should the project register the matched live
model evaluation and independent outcome review required by the broader exit
gate.

## WP6 — Preregistered grounded-resolution study

The project owner authorized further scientific-effectiveness validation on
2026-09-08. Window 2 may extend only its existing owned paths and may create a
dedicated, ignored local evaluation project; the main workflow call site and
the primary self-development project remain main-window owned.

1. Freeze a paired task matrix before the formal provider responses: twelve
   project-evidence acquisition tasks, three seeds, explicit and semantic
   routing strata, and an unchanged v2-style keyword-router baseline.
2. Use the same project-owned read-only Knowledge, Evidence, and registered-run
   data in both conditions. The treatment must run the complete durable v3
   bridge with the pinned `zhipu-direct/glm-5.3-flash` model and no retries.
3. Make exact grounded resolution the primary endpoint. Aggregate three seeds
   by majority within each task, then report task-level paired discordances, an
   exact two-sided McNemar p-value, response-level Wilson intervals,
   unsafe-scope rate, admission/resolution rates, calls, tokens, price-bound
   cost, and latency. Seeds are replicates, not independent sample-size units.
4. Produce a condition- and gold-blinded review packet plus a separately hashed
   key. No result becomes a broad scientific-effectiveness claim until an
   independent domain review is returned and the main-window integration gate
   also passes.

### WP6 progress — 2026-09-08

- The strict 36-response/12-independent-task protocol, frozen baseline, typed
  scorer, task-clustered exact paired test,
  Wilson intervals, blind packet/key, and fail-closed claim boundary are
  implemented under `model_nodes/**`; the committed config remains inert.
- GLM-5.3-Flash availability was authenticated without persisting the key.
  User-provided promotional pricing (CNY 0.4 input / CNY 1.4 output per million
  tokens) is converted with the 2026-09-08 CFETS central parity of USD/CNY
  6.7804 and bound to a date-limited configuration.
- A one-call diagnostic selected the correct run-comparison action but exposed
  that the request omitted the profile fingerprint that the output contract
  required the model to echo. The diagnostic is not counted as a study trial.
  The request contract now transmits that exact deterministic binding and has a
  regression test.
- The dedicated project-owned runner now materializes hash-pinned inputs, runs
  or exactly resumes all 72 condition records, verifies the model/tool ledgers,
  publishes a blinded packet plus private key and hash-bound run manifest, and
  rejects nested symlinks or artifact drift. A deterministic injected-backend
  test completes all 36 treatment calls and proves that a second run performs
  zero provider calls.
- The formal GLM-5.3-Flash run is registered against source commit `4606211`:
  35/36 response-level grounded resolutions versus 18/36 for the fixed router,
  12/12 versus 6/12 at the independent task-majority level, six improvements,
  zero regressions, six ties, and exact two-sided McNemar p=0.03125. Scope
  violations were 0/36. One over-broad three-metric proposal was rejected and
  never executed. The 97,002 tokens cost USD 0.00727049 under the frozen
  full-input ledger; applying 128 reported cache-hit tokens gives CNY 0.04926032
  at the registered rates. Mean provider latency was 5.522 seconds.
- All formal artifacts and runtime ledgers verify with zero pending attempts.
  A second execution without the API key recovered all 72 condition records and
  made no provider call. Independent blinded outcome review and primary-window
  integration remain open; the report correctly keeps the scientific claim
  false.
- Provider cache-hit telemetry and pricing are now explicit for subsequent
  runs, including fail-closed validation of malformed or impossible cached-token
  counts. A strict blind-review return contract now requires complete ID
  coverage and reviewer independence/key-separation attestations, then computes
  response rates and task-majority paired outcomes without enabling a scientific
  claim. All 213 model-node tests and all 901 repository tests pass after this
  final follow-up; the frozen formal ledger and its source commit remain
  unchanged.
