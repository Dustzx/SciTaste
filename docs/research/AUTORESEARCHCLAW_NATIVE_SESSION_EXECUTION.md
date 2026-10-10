# Native AutoResearchClaw execution with session model transport

## Comparison boundary

AutoResearchClaw is the executed open-source framework. A child agent is only a
model responder, never an imitation of that framework. The native Python source
selects stages, builds prompts, decides research transitions, invokes experiments,
and writes/reviews/revises artifacts. Replacing any of these operations with a
handwritten successful artifact would invalidate this comparison.

Pinned source: `third_party/autoresearchclaw` at
`12d3fd809fa9658e91a0328c3280a0e462c78386`. The launcher requires a clean checkout;
the submodule is not edited. This route does not import `arc_bootstrap`, the old
stage-8 study adapter, or SciTaste controller/audit overrides.

| Responsibility | Actual owner |
| --- | --- |
| Stage order, loops, prompts, tools and research decisions | Native `researchclaw.pipeline.runner.execute_pipeline` and stage implementations |
| Chat completion request | Native `researchclaw.llm.client.LLMClient` |
| Model response content | Fresh inherited-model session child, given only that request |
| Exact request/reply binding | First-party authenticated loopback transport |
| Generated experiment execution | Native subprocess sandbox, inside an outer isolated run |
| Research paper, peer review and revision | Native stages 16–19; not a common SciTaste writer |
| Formal independent benchmark scoring | Not supplied by this development launch |

## Transport contract

`backends.framework_session_http.FrameworkSessionHTTPServer` implements only the
local `/v1/chat/completions` route. The original request body, messages, options and
raw-body hash are retained. Identical requests receive distinct persistent request
IDs. Replies bind both ID and hash and record `subagent-session` plus actual author
reference. A child has no authority to inspect experimental files, browse, execute
code or insert unrequested evidence; generated code is returned as model content
and only the framework may execute it.

The dispatcher creates a fresh child per request rather than carrying a hidden
cross-stage conversation. Model configuration is inherited, not independently
verified provider identity. Missing token/cost measurements remain null. HTTP usage
is omitted: upstream defaults of zero are retained as upstream artifacts but must
not be interpreted as measured zero usage. This is a session-backed execution
cohort, not an API-model performance claim.

Native sampling settings and token ceilings are preserved as request metadata,
but this session interface cannot certify provider-equivalent sampling or tokenizer
limits. Wall time includes responder dispatch/wait time, so it is not comparable
to a direct supplier-API latency measurement. This route establishes ownership of
the research workflow; formal model/resource comparisons need their own matched
execution cohort and observed accounting.

## Native configuration and isolation

October 2 molecular recovery adds a declared runtime transport intervention:
`--metadata-timeout-seconds 60` bounds requests connect/read operations only when
the metadata caller otherwise supplied no timeout. Explicit request deadlines and
native retry/search/stage behavior remain unchanged; this is not a total search
deadline. The original blocked run, its operator interruption and consumed allocation
are retained. A separate campaign/launch binds that original receipt and resumes
its completed native prefix with remaining resources, not another full budget.
Byte-identical model HTTP inputs may reuse their accepted source reply through
`scripts.reuse_identical_framework_reply`; source/target byte fingerprints and reuse
receipts are required. Reused transport requests still consume slots, but are not
new model generation or measured token/cost evidence. This environment intervention
and developmental recovery must remain visible in any reported framework result.

`scripts.run_autoresearchclaw_session` starts at `TOPIC_INIT` and requests all 23
native stages without preauthoring a stage-7 brief or overriding stage functions.
The native auto-approval option is disclosed; it is not human review. Failures and
native rollback attempts are retained. Native stage completion does not certify
scientific correctness, experiment independence, or formal benchmark readiness.

The first development configuration uses real subprocess experiments, not simulated
results. Advanced optional code/benchmark/figure/repair agents, OpenCode, external
CLI providers, MetaClaw, persistent memory and Overleaf are disabled through native
configuration. This is a bounded configuration, not an unrestricted best-native
claim. Native public scholarly search/citation requests remain enabled; optional
paid web-search routes are disabled.

An outer Bubblewrap process binds only selected runtime/code read-only and a new
run directory read-write. Actual GPU devices, user credentials, unrelated projects,
prior results and session reply files are not mounted. The process receives a fresh
environment containing only runtime settings and an ephemeral local transport key.
`PIP_NO_INDEX=1` prevents upstream dependency installation through package indexes;
the supplied task limits imports to installed CPU packages. No local GPU or remote
experiment resources are used in this task. Public literature network access is
permitted; this is not a network-disabled sandbox.

## First task and current evidence

The task asks for an evidence-grounded classification robustness study on the real
Wine dataset bundled with scikit-learn. The framework chooses hypothesis and design;
the brief supplies data, objective, primary metric and CPU constraints. It is one
development task, not newly admitted SciTasteBench data, and not a claim of novelty
or superiority. Native research artifacts and later independent benchmark scoring
must not be conflated.

Self-project locations:

- `evaluations/arc-native-session-task-20260930/TOPIC.md`: public brief.
- `evaluations/arc-native-session-execution-20260930-v1/`: startup failed because
  local Bubblewrap 0.4 lacks `--clearenv`; no model requests. The launcher instead
  supplies an explicitly clean subprocess environment.
- `evaluations/arc-native-session-execution-20260930-v2/`: startup lacked an OS user
  database for native `Path.home()`; no model requests. Read-only passwd/group
  mounts repair lookup without exposing home contents or rewriting HOME.
- `evaluations/arc-native-session-execution-20260930-v3/`: first native stage reached
  the session endpoint and stages 1–3 completed with four model replies. Stopped
  during native stage-4 literature search after observing its required `arxiv`
  dependency absent and both alternative services rate-limited. This is operator
  environment intervention, not an autonomous scientific decision.
- `evaluations/arc-native-session-execution-20260930-v4/`: native stage-4 continuation
  using exact hash-bound previous artifacts and the remaining 76 requests/4803 wall
  seconds. The original run began at stage 1; continuation does not claim a new
  independent task or overwrite the failed/stopped attempts. `SESSION_CLOSED.json`
  and native artifacts determine eventual completion, not this initial note.

The required arXiv dependency and its narrower requests version are isolated under
`evaluations/runtime-environments/autoresearchclaw-session-deps-v1/`, mounted as
read-only `/runtime-deps`. Exact versions are recorded in
`requirements/python312-arc-session-overlay.lock`. Temporary main-environment
installs were removed and its original requests 2.34.2 restored; other workloads do
not inherit the native framework's requests constraint. Read-only system TeX runtime
directories are mounted for later native export without exposing unrelated projects.

Run artifacts: `EXECUTION_CONTRACT.json`, `native.log`, `exchange/*.request.json`,
`*.reply.json`, `*.receipt.json`, native `work/upstream_run/stage-*`, optional
`work/NATIVE_RESULTS.json`, and terminal `SESSION_CLOSED.json`. Never label the
pipeline complete merely because a model responder returned a final answer.

## Terminal outcome and wall-time diagnosis — 2026-09-30

The launcher set 5400 seconds/80 requests for the original development workflow,
not a scientific time requirement or user-specified budget. v3 used 596.213601 s;
v4 inherited 4803 s/76 remaining requests and ended at 4803.006985 s with exit -15.
Combined charged wall time was 5399.220586 s. There were 31 consumed model responses
across both packages. This is a deliberate launcher wall-limit stop, not GPU shortage,
API credit exhaustion or an experiment subprocess timeout.

Native execution reached stage 15 and twice chose REFINE, rolling back to stage 13.
The current completed prefix is 12 after versioned rollback, not 15 or 23. No final
paper/review/revision chain was completed. ProjectRuntime records stopped-incomplete.

Three real experiment subprocesses completed without timeout/failure: stage 12 took
5.2366 s, and the two completed refinements took 2.3012 s and 2.2146 s. Total actual
subprocess runtime was 9.7525 s. About 3776 s elapsed between answered session request
and receipt files, plus 172 s waiting for the last unfinished response. These are
response-turnaround observations, not measured model compute/token time. Native
literature/novelty network work used roughly 1428 s, including repeated 429s/503s.

The native decisions combined genuine gaps with evidence-transfer problems. H2's
scaled-tree control was not implemented; a depth-2 capacity control is not equivalent.
Raw results did retain the scheduled seeds, but downstream truncated summaries did
not consistently expose them. Identical raw/no-standardization kNN conditions were
aliases, not distinct scientific ablations. The scalar 0.7820 → 0.9360 changes endpoint
and aggregation semantics and must not be reported as comparable improvement.

Authoritative files under v4 `work/upstream_run/`: `stage-12/runs/run-1.json`,
`stage-13_v1/refinement_log.json`, `stage-13_v2/refinement_log.json`,
`stage-13_v2/refine_sandbox_v1/_project_1/results.json`, `stage-15_v2/decision.md`,
and `decision_history.json`. The top-level `SESSION_CLOSED.json` binds termination.

Future continuation needs a disclosed new development budget and rollback-aware
state reconciliation. Native checkpoint records stage 15 as completed, while actual
control flow is at the second stage-13 rollback; blindly resuming at stage 16 skips
pending work. The launcher's prefix heuristic happens to choose 13 here but does not
validate all rollback state. Preserve failed runs and native rollback count, never
force PROCEED or silently reset the original budget. Do not modify pinned upstream
behavior to make a baseline finish or quietly repair its scientific results.
