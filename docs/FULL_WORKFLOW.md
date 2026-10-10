# Project-owned full workflow

## Native operational progress

`scitaste project progress --project-id <id> --outputs-root outputs` reads the last
recorded Native cycle boundaries. New cycles publish preparation, stage-start and
return, known model waits and final delivery under `progress/native-cycles/`.
Immutable events retain source/contract hashes and predecessor identities; a current
pointer advances atomically. No command lines or provider prompts are copied.
Corrupt records are reported as issues, and changed sources are marked non-current.
A recorded start is not a process heartbeat, an authorization or scientific success.

Fresh next-planning requests receive a frozen `PLANNING_PROGRESS.json` alongside
their existing results and review feedback. Session resumes reuse that exact file,
not a moving progress pointer. Older pending requests without it are not retrofitted.
This first path covers Native workspace cycles, not all legacy executors, the UI's
historical scientific dossier or arbitrary mid-tool crash recovery.

## Retained-source delivery and figure recovery

A Native task can inspect existing records and write a report without running code.
Delivery retains its successful Read observations as source evidence, not a new
experiment. If preparation failed after reserving a report destination, explicitly
preserve that failed directory before preparing the same empty destination again.
This exception does not permit research-execution replay or overwrite a provider call.

For a malformed optional figure, keep the original sealed contract. Supply
`--figure-contract-repair <project-owned JSON>` to the Native `project research-cycle`
or `scitaste.writing.native_lifecycle` delivery entry. The JSON contains `source`
(`assistant-session` or `subagent-session`), `author_reference`, `reason`,
`execution_sha256`, `original_contract_sha256`, and `replacement_fields`.
The corrected FigureContract must validate and retain its original claim targets.
In particular, `forbidden_emphasis` contains entity IDs, not prose restrictions.
The derivative receipt binds the repair, and does not alter original execution.
This is recorded assisted recovery, not uninterrupted autonomy or visual inspection.

## Optional explanatory figures in Native delivery

When a diagram materially helps explain an existing canonical claim, the Native model
may write `workspace/report/figure_contract.json` using the FigureContract schema
included in its prompt. Normal statistical plots keep their existing image pathway.
Terminal execution seals the contract and scientific-state hashes. Report lifecycle
then invokes the existing semantic layout, SVG/draw.io exporters, deterministic
VisualTasteCritic and ObjectPatcher in a separate `<paper-prefix>-figure` directory.

With the optional `figures` dependency installed (`pip install -e '.[figures]'`,
system Cairo required), a PDF figure asset is generated from the internally exported
SVG. The paper importer verifies execution and artifact bindings and adds the
conceptual figure to the new manuscript; original report/experiment files are not
changed. Existing papers cannot silently gain a different figure: use a new version.
Unknown claims, changed artifacts and unresolved contract findings reject delivery.
The receipt preserves claim statuses and explicitly withholds scientific approval.
This is deterministic contract review, not human visual inspection or a guarantee
of conference-quality aesthetics. No model call, training or new measurements occur.

## Canonical predecessor state

Native `project research-cycle` accepts `--research-state <project-owned-state.json>`.
With `--objective`, the state also enters the planner's evidence packet. Execution
binds its exact bytes/state identity and retains hypotheses, observations, claims,
evidence, review obligations and decision history. Existing runtime handles are not
carried into a new process. Scientific context is supplied to subsequent proposals.

The declared run envelope must fit the predecessor's remaining budget. Prior usage
is retained; API accounting adds this run's charge to prior usage rather than resetting
it. An oversized or unbounded allocation against a bounded predecessor is rejected.
The handoff enters Evidence under the explicitly selected execution plan; it does not
mark any hypothesis supported. Known-wait recovery separates predecessor decisions
from this run's committed tool trajectory. Direct `--continue-from` already inherits
its parent state and cannot also accept `--research-state`.

Native proposal batches can additionally include bounded `interpretations`, each
referencing a committed `source_result_id`, an exact `source_quote`, and an explicit
InterpretationContext (including uncertainty). Optional new claims must start
unsupported without evidence links. Ordinary tool success needs no interpretation.
Existing InterpretationCritic/EvidenceLoop updates a copied canonical graph; measured
replication provenance is required for support/contradiction, otherwise the relation
stays uncertain. Model-authored assessment is not independent scientific validation.
Identical replay is a no-op; conflicting replay or unknown sources reject.
Terminal state is source-bound and supplied to subsequent planning without another
model call or another experiment. Evidence routes guide proposals, never launch tools.

If an already consumed session interpretation fails at this boundary, retain the
execution and diagnose the rejection. After a justified code repair,
`python -m scitaste.evidence.native_interpretation --project ... --execution ...
--session-reply ... --output <separate-project-directory>` materializes only the
derived state. It checks the retained consumed response and terminal state, binds
trajectory/response/source hashes, and never replays a tool or changes execution
status. A derived state is not proof that the original run completed uninterrupted.

`project prepare-workspace-task --max-experiments 0` can explicitly allocate a
read/analysis-only task. Nonnegative caps are optional for compatibility; when remote
jobs are configured, an explicit cap must match their declared allocation.

## Initial objective resource acquisition

`project research-cycle --objective ...` accepts repeatable
`--planning-acquisition-option <project-owned-option.json>`. These options enter the
same source-bound planning contract as prepared tasks and workspace resources.
Use `--acquire-planning-resources` to materialize an accepted acquisition selection;
network activity additionally requires `--allow-network-download`. The existing
10 GB bound, license/source checks and retained download receipts still apply.

Acquisition stops at resource preparation, even with `--allow-execution`. Intake
`STATUS.json` distinguishes waiting for enablement, waiting for a download, and
`workspace-resources-prepared`. The latter exposes `workspace_resources` and its
hash: pass this file as `--planning-workspace-resources` to a new objective cycle.
This fresh planning decision, not acquisition itself, selects the experiment.
An accepted acquisition can be enabled/resumed without another model call; retained
source changes fail closed. Initial acquisition flags require `--objective`.

## Session-assisted model nodes

Supply `--session-exchange <project-owned-directory>` instead of `--allow-api` to
the Native project research cycle. Execution still needs `--allow-execution`.
Planning, Native proposal/selection, Taste deliberation, review and revision export
input-bound `*.request.json` files. A session supplies the corresponding `*.reply.json`
with `request_fingerprint`, `source` (`assistant-session` or `subagent-session`),
`author_reference` and contract-valid `output_payload`. This is assisted execution,
not a hosted provider call; actual session usage/cost remain unknown.

A missing reply retains pending state. Repeat the original command after supplying
the reply; do not change inputs or delete stage receipts. Native waits bind code,
workspace, plan and treatment to a checkpoint and reuse committed actions. Changed
inputs, terminal runs and ambiguous uncommitted tools reject replay. Recovery is not
permission to overwrite a rejected response or automatically repeat an experiment.
The bounded `session-native-resume-drill-v1` exercised four such waits with one actual
file read and a stop. It is recovery evidence, not a scientific study.

## Bounded unattended execution continuation

Native `project research-cycle --max-execution-continuations N` permits 0–3 child
continuations (default 0). Both API and execution flags are still required before
launching a child. Eligible boundaries are recorded JSONDecodeError interruptions
and remote `execution-unresolved` states. Normal outcomes, low scores, unknown errors,
exhausted turns/time/API caps and unresolved provider requests do not authorize retries.
Children inherit the same plan, treatment, provider ledger, time and remote-job slots;
no extra turns/budget are granted. Existing continuation ownership prevents branching
the same remaining budget. Stage markers prevent duplicate launch after restart.

`CONTINUATIONS.json` binds parent/child terminal receipts and the effective execution
passed to paper delivery. A still-pending remote experiment stops before writing;
unknown process exits or partially started children require observation/recovery,
not another launch. This is a bounded opt-in path, not unrestricted self-repair.
One no-call policy check passed; a full live unattended continuation has not yet run.

## Native action response format

Native action proposal calls explicitly request `response_format: {type: json_object}`
through the shared provider bridge. Other bridge callers retain their previous default
unless they opt into `json_mode=True`. Mode selection is recorded in run contracts and
provider request ledgers; unsupported providers are not silently retried with another
mode. JSON-object output still needs normal proposal and tool-argument validation.
The existing one formatting retry is unchanged, and no executable content is locally
rewritten to repair JSON. A single real replay of the capacity case's malformed final
response produced an accepted proposal batch, with no action execution.

## Generic remote workspace jobs

`Fetch Remote` is a separate Native collection action: supply the retained 20-character
job ID and workspace-relative artifact names, or an empty list to inspect inventory.
It invokes no launch entry and consumes no new experiment count; per-file errors and
job identities are visible to subsequent model planning. This prevents artifact-path
correction from requiring a new training action. Actual use through model ranking is
not yet demonstrated; the first subsequent model attempt failed JSON parsing.

For terminal reporting after operator artifact recovery, `scitaste.writing.native_report`
accepts `--remote-artifact-recovery RECOVERY.json`. It checks the recovery file hashes
and original job binding against the execution lineage, copies evidence into the new
report workspace, and selects original remote source/measurements rather than any
local repair. Full learning histories remain bound on disk; report prompts retain
per-run measurements. Existing execution evidence is not rewritten. This route
delivered `remote-capacity-paper-v1-revised/main.pdf` with actual review/revision;
review remains open and the case remains operator-repaired development evidence.

Pending-boundary recovery is now connected to Native `--continue-from`: for a recorded
`execution-unresolved` checkpoint whose final action is `Run Remote`, recovery copies
workspace/job ledgers into `remote-recovery/`, invokes the tool in observation-only mode,
and never creates a new request. A matching terminal remote identity with complete
nonnegative costs updates the child's original action/checkpoint before normal
continuation. `RECONCILIATION.json` retains both pending and terminal observations;
the parent's records stay unchanged and observation time counts against remaining
workspace duration. Still-pending results stop without relaunch. Historical Taste
capture is explicitly not marked reconciled. One focused observer fixture passed;
real interrupted remote recovery remains unverified.

Completed-job continuation is now supported: Native `--continue-from` copies the
remote job ledger alongside workspace/provider records, verifies every completed
job's manifest and checkpoint cost, and retains original remote identities. Cached
results consume neither another job slot nor additional cost. Missing/pending job
receipts or costs not yet committed to the checkpoint still reject continuation.
The latter needs observation/reconciliation rather than a fresh launch. This replaces
the earlier blanket rejection of all remote-bound continuations; arbitrary hard-crash
and pending-job recovery are not yet complete. One focused ledger-inheritance fixture
passed without SSH/API/GPU work.

Live evidence: `evaluations/native-remote-retained-analysis-v1/RESULT.json` records
successful assistant-selected Native tool execution on 4090-2. It summarized existing
allocation results (4 conditions, 400 pairs), returning summary JSON/CSV and logs.
No new experimental samples, API calls or GPU use. This demonstrates actual SSH
execution and artifact transport, not online model ranking or full autonomous study
execution. Generic `experiments` usage here counts execution reservations; scientific
trial counts must come from study provenance, not this transport counter.

Native integration: `project prepare-workspace-task --remote-resource RESOURCE.json`
binds a project-local configuration containing `host`, `port`, absolute `python`,
`gpu_indices`, `max_jobs`, and per-job `wall_seconds`. The resource-to-design bundle
also accepts optional `remote_resource` (project-relative). Its selected task retains
that configuration and hash. The reservation sum must fit the study time ceiling.
The Native runner exposes `Run Remote` only for these plans, with files/argv/artifacts
arguments, while host/devices/attempt limits remain outside model control. Local GPU
visibility stays disabled. SSH credentials must be configured in the launcher environment.

The tool waits on the same detached job, copies declared artifacts under the local
workspace's `remote-results/<job>/`, and returns experiment/wall/GPU costs through
the normal selected-action handler. Missing artifacts are recorded separately from
execution status. Identical input/code requests reuse results without a second charge;
new attempts require remaining slots and no unresolved job. Generic remote continuation
is currently explicitly rejected until its retained-job reconciliation is implemented.
One mocked transport check passed tool selection/handler/cost/artifact/cached-result
integration. This is not evidence of real SSH or GPU execution.

`python -m scitaste.executor.remote_workspace {submit,observe,collect}` provides
an explicit SSH job substrate independent of the unlearning/perception adapters.
Common flags: `--project`, `--output`, `--run-id`, `--host`, `--port`, `--python`.
Submit additionally requires `--allow-execution --request request.json`; request
fields are `files` (workspace target to project-relative source), `argv`,
`wall_seconds` (1–10800) and explicit `gpu_indices` (`[]` disables GPUs).
Remote jobs occupy only their new `/data/zfx/scitaste/native-workspaces/<run-id>`
directory. Credentials stay in the caller's SSH environment/config, not manifests.

Submission stages hashed inputs and a standalone stdlib worker, then returns while
the worker runs independently of SSH. Repeating submission observes the binding;
it never stages/launches again. `observe` retains uncertainty on connection failures.
`collect --artifact workspace/report/report.md` retrieves explicit job-relative files
only after a bound terminal receipt, validates hashes and preserves previous copies
(20 MB per file ceiling). Nonzero exit and timeout are execution outcomes, not scientific
scores. An incomplete upload/launch remains unresolved and is not automatically retried.

This is trusted-code execution with cwd separation, **not an OS sandbox**. Explicit
device selection does not reserve idle GPUs or authorize unrelated filesystem access.
The substrate is not yet wired into Native model-selected workspace tools or verified
over real SSH; one local CPU worker check demonstrated detached execution and no
duplicate launch. Generic remote orchestration remains incomplete until those links
and job-level GPU accounting are connected.

## Observe reserved remote experiments before leaving the loop

For an iterative Native unlearning run that already returned `execution-unresolved`,
the existing `--continue-from` route can now observe the last pending attempt before
restoring the controller. It uses the parent's frozen remote binding, validates the
candidate and execution ceiling against its reservation, and writes collection data
under the new run's `recovery-observation/`. Only a terminal result with complete
costs can update the child's checkpoint and experiment ledger. The parent's pending
trajectory is never rewritten; `CONTINUATION.json` records both observations and
the cost reconciliation. A single continuation owns the remaining budget. This is
recovery from a recorded unresolved terminal boundary, not arbitrary hard-crash
repair. A historical pending Taste capture is not automatically relabeled as a new
prospective capture or admitted lesson.

The Native unlearning runner now defaults to a 300-second observation-only window
when its selected experiment returns `PLANNED`. `--pending-observation-seconds`
sets 0–7200 seconds; zero retains the immediate unresolved return. Observations
use the existing reservation and backend `observe()` entry every 45 seconds, with
append-only `tools/PENDING_OBSERVATIONS.jsonl`. No model call, new proposal or launch
occurs during this wait. Transient observation failures retain pending status;
window exhaustion does not become experiment failure. A terminal result goes back
to the original selected action so cost, Taste capture and subsequent turns follow
the normal single-outcome path. Iterative attempts preserve their terminal receipt.
This closes in-process reconnect waiting for the existing remote backend, not
generic remote provisioning or crash recovery of the complete controller process.
The wait policy has a focused simulated-clock check; no GPU run was repeated.

## Provision a new study from project resources

The package planner accepts repeatable `--workspace-resources /absolute/resource.json`
alongside `--compile-selection`. Unlike `--prepared-task`, this input does not need
an existing task. A project-local resource file contains:

```json
{
  "assets": "docs/records/AVAILABLE_ASSETS.json",
  "harness": "evaluations/acquisitions/researchharness-runtime-v1",
  "backend": "/absolute/backend.yaml",
  "max_rounds": 24,
  "wall_seconds": 900
}
```

`assets` is the existing explicit file catalog (`files`: workspace target to
locator/role/use_constraints). Paths except an absolute backend are project-relative.
The model chooses a study, comparison arm and subset of declared file targets in
`workspace_selection`. Compilation writes `provisioned-workspace/SELECTED_ASSETS.json`,
`PROVISION.json` and `<planning-run>-task/PLAN.json`; the latter is directly accepted by
`project research-cycle --executor native-workspace`. Resource and source hashes
must match those supplied to the model. No download, experiment, GPU use or positive
result is implied by provisioning. API and execution enablement remain separate.

Native research cycles also accept repeatable `--next-workspace-resources` with
`--next-planning-objective`, passing actual paper feedback to this planner and
compiling its selection without automatically starting another experiment. This
removes manual task/asset-subset assembly; initial resource registration and broader
autonomous acquisition remain unfinished. One fixture exercised selection, real
workspace compilation/materialization and changed-resource rejection. New online
model selection subsequently succeeded in `resource-selected-native-design-v1`:
one call, USD 0.121164 liability, zero unresolved reservations. Its compiled plan
loaded successfully but was not executed. That historical output retains the initial
`task/PLAN.json` layout; future plans use the run-qualified identity to avoid registry
collisions across planning runs.

## Artifact-only figure supplements

`plot_kind: replicate-summary` additionally accepts long-form observed records with
`group_fields`, `series_field`, `replicate_field`, `value_field` and display-label to
series-ID mapping. It plots every observed value and its arithmetic mean; paired
replicate identities must match, and duplicate/undeclared rows are rejected. No new
samples or interval estimates are generated. This produced the remote-capacity case's
second required figure in a separate, not-newly-reviewed paper version.

Experience disposition can close a capture interrupted before outcome publication
without admitting it: a verified continuation binds the original pre-execution lock,
decision/state and matching terminal result. `excluded_recovered_captures` records
the explicit exclusion, while the original missing attachment remains missing.
Choose a new disposition output for this supplementary closure; do not rewrite the
prior pending receipt or interpret exclusion as learned scientific credit.

`python -m scitaste.writing.figure_supplement` accepts `--project`, `--delivery`,
`--data`, `--spec`, `--output`, `--source-paper` and `--paper-directory`. The data
must match a registered terminal delivery hash. The JSON specification declares
group fields, labeled numeric series, figure name and caption/section text.
This creates an empirical-distribution plot and a separately registered paper/PDF
version; it does not rerun experiments, alter the original manuscript or inherit
review approval. It is intended for missing artifact completion from existing data.

## Explicit interruption recovery

The Native package runner accepts `--continue-from PARENT`. A turn-exhausted task
may explicitly request `--extra-turns N` (1–16, cumulative maximum 120), recorded in
the child lineage without resetting API cost or cumulative runtime. This is an
operator budget amendment, not a new independent trial or unchanged protocol.
`--resolve-closed-background` checks recorded local terminal PIDs are absent and
binds those observations; live or unknown sessions remain blocked. The current
foreground tool interface no longer advertises incomplete terminal-session controls.
Failures and recovery must be disclosed when reporting automation completeness.

## Feedback-informed planning without checkout

Native `project research-cycle --next-planning-objective ...` now uses the package
planner and no longer requires `--workspace`. It passes the bound task backend and
optional credentials, actual review/revision feedback and experience disposition.
`python -m scitaste.project.research_planning` also accepts explicit `--backend`,
`--credentials`, and optional `--code-root` to inventory legacy adapters. Without
that code root, only installed package capabilities are advertised. Planning does
not execute the selected study. The compatibility planning script retains the old
checkout inventory; optional legacy campaign compilation still needs its scripts.

This section supersedes older statements below that every next-planning invocation
requires a checkout. Unlearning and legacy draft/campaign paths remain separate gaps.

## Native cycle outside the checkout

For `--executor native-workspace`, `--workspace` is now optional unless requesting
next planning. Supply absolute project/plan/output paths. For new writing calls,
provide `--paper-backend`, `--review-profile`, `--venue-taste-profile` and, if needed,
`--credentials`; these select configuration files, never inline secrets. Existing
completed cycles can resume without API/execution flags, with the original venue
profile supplied explicitly. This route was exercised from `/tmp` on real artifacts.

Native report services are `scitaste.writing.native_report`, `report_import`,
`native_lifecycle`, `paper_cycle`, `lifecycle_revision` and
`scitaste.review.lifecycle_review` / `recover_lifecycle`. Old script module names
remain compatible. Unlearning, next planning and optional legacy measured-draft
building have not yet completed their checkout-dependency migration. A new full
model-backed run after migration and a clean wheel installation remain unverified.

The older implementation notes below retain the history of that migration; this
section supersedes their statements that Native paper handling always needs scripts.

## Package-owned execution entry

`python -m scitaste.executor.native_workspace --project PROJECT --plan PLAN
--output RUN --allow-api --allow-execution` invokes the package-owned runtime.
Use absolute paths when invoking outside the repository. `--credentials FILE`
overrides the default `OUTPUTS_ROOT/resources/access/credentials.env`; files must
remain private and non-symlinked. If the file is absent, the configured environment
variable may supply the credential. Do not put credentials in plans or command text.

The old `scripts.run_native_benchmark_task` and `scripts.collect_research_experience`
entries remain compatible. Optional `--report-paper-prefix` still invokes the
checkout-dependent writing lifecycle; external tool-provider code remains explicitly
declared in the task. Do not infer full standalone packaging from this execution entry.

## Project-defined study tasks

`scitaste project prepare-workspace-task` accepts `--project`, `--design`,
`--study-id`, `--comparison-id`, `--comparison-arm`, `--assets`, `--harness`,
`--backend`, `--output`, and optional `--max-rounds` / `--wall-seconds`.
The resulting plan is consumed by `project research-cycle --executor native-workspace`.
No benchmark checkout or task metadata schema is required for this plan kind.

The assets JSON is a `files` mapping from canonical workspace paths under `data/`,
`references/` or `code/` to objects with `locator` (project-relative source file),
`role` (`data`, `reference`, `starter-code`) and `use_constraints`. Sources, design,
tool-provider code and backend configuration are hash-bound. Asset choice is explicit;
model study prose cannot silently expand resource authority. Preparation is not
execution authorization. Only CPU/API is enabled on this generic path currently.

The exercised project-owned setup reuses existing development data. It is not an
official benchmark task, an independent new dataset, or proof of a newly executed
full study. Generic resource discovery and autonomous asset selection remain separate.

## Unified project command

When library/profile are configured, initial and next planning now perform a bounded
Taste consultation as well as execution. `planning-taste/` retains the frozen library,
closed candidate packet, result and validated advice. No applicable precedent is an
explicit abstention, not a forced preference. Only the validated advice enters design.

Completeness-first planning normally selects implementation work. If a real run is
necessary to close a supplied gap, the model can bind `next_work_item.validation` to
one declared Native study with explicit completion observations and existing-result
reuse. This does not authorize execution, start a campaign or claim scientific gains.
Compiled task locations come from `prepared-task/SELECTION.json`, not an assumed
global task name. Preparation can complete from an accepted selection without a new
model call; changed source bytes reject reuse.

Native cycles can also start before a prepared task exists:

```bash
scitaste project research-cycle --executor native-workspace \
  --project /path/to/outputs/projects/PROJECT \
  --output /path/to/PROJECT/evaluations/CYCLE \
  --objective 'Answer the registered research question using the declared resources' \
  --planning-workspace-resources /path/to/PROJECT/resources/BUNDLE.json \
  --session-exchange /path/to/PROJECT/evaluations/CYCLE-exchange \
  --allow-execution
```

Alternatively, repeat `--planning-prepared-task PLAN.json` for existing task options;
`--planning-evidence` supplies project-local evidence. API mode uses `--allow-api`
and optional `--planning-backend` instead of the session exchange. `--plan` and
`--objective` are mutually exclusive. Initial planning and intake receipts live in
the sibling `CYCLE-planning` and `CYCLE-intake` directories. The same command resumes
a pending session request, then follows only the exact model-selected compiler
receipt into the existing execution/paper/feedback cycle. No executable selection
means no experiment: workflow-only, rejected and resource-incomplete plans remain
explicit. Current project completeness gaps can legitimately select implementation
work instead of an experiment. This entry does not launch an unlimited sequence of
subsequent studies or discover undeclared resources.

Actual `session-objective-entry-v1` exported a request, resumed an accepted session
plan and correctly retained workflow-only work without starting execution. The
positive selected-plan forwarding branch still requires final integration coverage;
this case is not evidence of a fresh complete autonomous study.

`scripts.plan_project_research --prepared-task PLAN --compile-selection` now accepts
Native workspace plans as well as iterative unlearning. A valid model-selected
component creates `prepared-task/PLAN.json` and `SELECTION.json` under the planning
output. Supply that compiled plan to the project research-cycle command. Study and
selected-arm instructions reach execution/reporting, but data, runtime dependencies,
budgets and actual controller identity remain those of the prepared resource plan.
This does not generate new benchmark tasks or imply the absent comparator exists.

Use the installed entry for Native prepared tasks:

```bash
scitaste project research-cycle --executor native-workspace \
  --workspace /path/to/SciTaste --project /path/to/outputs/projects/PROJECT \
  --plan /path/to/PROJECT/evaluations/TASK/PLAN.json \
  --output /path/to/PROJECT/evaluations/CYCLE --allow-api --allow-execution
```

For existing completed execution/report artifacts, add `--execution-run RUN`,
`--report-delivery DELIVERY` and `--paper-prefix PAPER_ID`; omit both enablement
flags for no-call recovery. Paths resolve relative to the caller before entering
the explicitly trusted workspace. Incomplete execution is observed/recovered,
never silently relaunched. Review/revision remain resumable stages and experience
counts refer only to the bound execution's collection, not recounted ancestors.
The existing default `--executor unlearning` retains its required brief/baselines.
Optional `--next-planning-objective` proposes a subsequent plan using delivered
review feedback; it does not authorize that plan's experiments.

The current backend still depends on checkout scripts/configuration. Native support
here removes the previous unlearning-only orchestration restriction, not that
remaining standalone-packaging gap.

After delivery, Native cycles register `CYCLE-experience-disposition/RESULT.json`
and link it from `CYCLE/EXPERIENCE_DISPOSITION.json`. This covers the verified
continuation lineage, while the historical cycle summary's current-run count stays
unchanged. No-credit observations may finish with explicit abstention; directional
claims remain pending without bound review/admission. Optional next planning receives
this receipt alongside paper feedback. A completed disposition is not proof that
the experience improves future decisions.

## Native terminal execution to report and planning feedback

`scripts.run_native_benchmark_task --report-paper-prefix PAPER_ID` can hand terminal
execution to the report lifecycle. To recover only delivery, use
`scripts.run_native_report_lifecycle --project PROJECT --source-run NATIVE_RUN
--delivery REPORT_RUN --paper-prefix PAPER_ID [--allow-api]`.

The handoff copies source-bound evidence and inherits the existing execution API
ledger/ceiling. It generates a report from retained code and observations, or reuses
an existing report without generation. It launches no experiments; null/negative
results and terminal execution budgets do not require research to restart. Unresolved
requests, incomplete checkpoints and background sessions still require resolution.
Review/revision are separate explicitly enabled writing stages, with their own
accounting. A completed invocation can resume with API disabled. Partial attempts
are retained rather than silently regenerated.

Artifacts include original/revised Markdown, TeX, PDF and figures, plus source-bound
`PAPER_FEEDBACK.json` for planning. `plan_project_research --previous-paper-flow`
accepts this direct cycle as well as measured-draft flows. Review comments are
fallible context, not automatic Taste admission, approval or mandatory experiments.

## Native controller ownership of workspace tools

`--continue-from PARENT` restores an explicitly interrupted Native workspace into
a fresh sibling run. It inherits the provider ledger, elapsed duration, complete
post-action history and data/code/results; only one child can claim the remaining
budget. Unknown provider outcomes or background sessions require observation first.
This is continuation of one task, not another independent experiment. All-action
experience collection omits unsupported allocation context rather than fabricating
remaining experiment counts. A budget-admission stop is distinct from an error.

Prepare with `scripts.prepare_benchmark_task --controller-owner scitaste-native`
to freeze this execution owner separately from the upstream baseline arm. Then use
`scripts.run_native_benchmark_task --project PROJECT --plan PLAN --output NEW_RUN
--allow-api --allow-execution`. The explicit runtime has an USD 8 API liability
ceiling, plan-bound turns/time, GPU visibility disabled and Python 3.12 on tool PATH.
The Native proposer supplies two alternatives; the controller also receives stop.
The existing prospective Taste capture records pre-execution state/selection and
post-tool feedback. Collection uses `--all-actions` to quarantine these real action
episodes without inventing causal credit or validated metrics. An existing run is
never blindly relaunched. Scientific review/admission remains separate from capture.

`HarnessToolEnvironment` supplies only workspace tool execution to the existing
`run_research_tool_loop`. It does not instantiate or run ResearchHarness's autonomous
agent. The SciTaste proposer supplies alternatives; TasteController selects one or
stops; SciTasteNativeExecutor dispatches it and stores decision/state/outcome records.
Read/search, write/edit and shell probe mappings are explicit. Argument schemas bind
required and optional fields. Shell success is not an official experimental score,
and a tool call is not automatically a scientific experiment. A fixture exercised
the bridge; a complete model-backed CPU/API launcher is still required.

## Prepared CPU/API benchmark tasks

For a **new** task run add `--capture-decisions` to persist upstream tool choices
before execution and their subsequent feedback. This selection is frozen in the
run contract; do not enable it retroactively on a completed run. The observer
records exact runtime-source bindings, ordered event hashes and unmatched calls.
Terminal dispositions remain observation-only: no alternative scientific actions,
causal attribution, admission or policy updates are inferred from tool success.
`scripts.replay_benchmark_decisions` can process retained events, but its mode is
always historical-replay and cannot establish prospective capture. Live use of the
new hook remains to be exercised in a necessary future task, not a redundant rerun.

Use `--report-paper-prefix PAPER_ID` on `scripts.run_project_benchmark_task` to
carry the actual generated report into registered paper review/revision, preserving
figures. Optional repeatable `--paper-evidence FILE` supplies code or measured output
to revision; the terminal task result is always included. This mode is exclusive
with `--paper-brief`, which generates a new case study. Completed stages are reused
without API or execution flags. Report import binds original bytes and normalizes
figure paths only; imported claims remain unapproved. Do not equate report reuse
with independently validated metric implementations or scientific conclusions.

Install the optional `researchharness` dependencies into the Python 3.12 environment;
the official ResearchHarness checkout and ResearchClawBench visible task assets
remain separate project-owned acquisitions, not bundled substitutes.

`scripts.prepare_benchmark_task --project PROJECT --benchmark BENCHMARK_ROOT
--harness HARNESS_ROOT --backend BACKEND_YAML --task-id TASK --output PLAN_DIR`
binds the current Idea, visible data/reference hashes, execution-source hashes and
backend settings. It does not read hidden target-study material or launch anything.

`scripts.run_project_benchmark_task --project PROJECT --plan PLAN_DIR/PLAN.json
--output RUN_DIR --allow-api --allow-execution` invokes the existing benchmark arm,
with GPU visibility disabled, bounded rounds/runtime and a persistent child process
record. A terminal receipt can be imported without API/execution flags. Missing
receipts after launch require observation/recovery, not automatic relaunch. Optional
`--paper-brief BRIEF` continues through the existing paper lifecycle. This is the
upstream native-base arm: task orchestration is not proof of full SciTaste control,
automatic task invention, sandbox isolation or online Taste experience learning.

## Review feedback and completeness-first planning

`scripts.plan_project_research --previous-paper-flow PAPER_FLOW` imports verified
registered concerns plus their revision responses as planning context. It handles
the explicit revision recovery branch, verifies paper and evidence bindings, and
does not treat text edits as scientific resolution or automatically admitted Taste.

Add `--workflow-gaps PROJECT_JSON` (a nonempty ID-to-description mapping) to select
completeness-first. The proposal must choose an existing gap as `next_work_item`;
scientific studies remain a deferred agenda with no immediate execution selection.
The product research-cycle entrypoint accepts the same frozen gap file for its
optional next-planning stage. Plans remain advisory: completion evidence must be
checked against the user's real whole-flow requirement, not merely a proposed dry-run.

## Benchmark terminal delivery

`python -m scripts.import_benchmark_delivery --project PROJECT --run RUN_A
--run RUN_B --output DELIVERY` preserves terminal ResearchClawBench receipts and
checks the bound report and, when present, official scoring bytes. The delivery
can then be passed to `scripts.run_measured_paper_lifecycle --project PROJECT
--delivery DELIVERY --brief BRIEF --output PAPER_FLOW --sectioned-draft --allow-api`.
Importing a historical run is not executing a new experiment. Unbound adjacent
score files are not measurements authorized by this adapter.

If a revision reaches terminal `rejected`, the measured lifecycle supports explicit
`--revision-recovery-output NEW_RUN --allow-api`. This preserves the original result
and binds one additional revision request (maximum liability USD 3) in
`REVISION_RECOVERY.json`; resume with that same option. It does not repeat drafting
or imported review, retry live/unknown requests, or erase the rejected call's cost.
Heading blocks are read-only context; only supplied editable paragraph IDs may be
replaced. The historical ResearchClawBench paper flow exercised this recovery and
produced revised Markdown/TeX/PDF, without claiming complete scientific evidence.

For new runs, `scripts.run_researchclawbench_system_arm` accepts `--project PROJECT`
to register terminal delivery automatically, and optional `--paper-brief BRIEF
--allow-paper-api` to continue through the same paper lifecycle. Output and brief
must belong to that project. If paper processing stops, resume the paper command
using the existing delivery, not the experiment launcher. Failed execution and
scoring remain visible independently of whether a paper is produced. This does
not yet supply decision-level experience learning or generic task provisioning.

## Refresh from admitted experience

`scripts.run_registered_attribution_review --kind decision-family --candidate
ADMITTED.json` runs the existing outcome-blind family node through durable model
runtime records. Supply the normal project, backend, evidence root, output and
explicit API flag. The candidate argument here is an admitted episode, not a raw
candidate. Two independent model runs are required by the existing panel.

`scripts.refresh_reviewed_experience_policy --project PROJECT --episode ADMITTED.json
--family-review-run RUN_A --family-review-run RUN_B --output NEW_REFRESH` imports
those reviews, resolves the family and creates a separate registered policy
snapshot. `--adjudicator-run` handles an actual split; `--existing-corpus` may add
the new episode to an earlier frozen population. Neither refresh nor resume makes
provider/GPU calls. A snapshot with insufficient support remains non-activated;
do not lower defaults merely to force a visible policy change.

`scitaste project research-cycle --development-policy-refresh REFRESH/policy`
can explicitly consult a project-owned snapshot during development allocation
decisions. The loader verifies every snapshot file and current Idea binding;
Native freezes the consulted policy and provenance in its run. This mode is
currently separate from library-deliberation mode, is limited to experiment/stop
choices, and does not change the project's default policy. Insufficient support
still yields abstention. A retained real decision was consumed offline and
abstained; live use through this new option remains unexercised.

## Live model-selected development lifecycle

The live coordinator is available as `scitaste project research-cycle`. Supply
`--workspace /absolute/path/to/SciTaste` for trusted executor scripts/configs,
plus the study arguments below. User paths resolve against the invoking directory.
Omit API/execution flags for a no-call continuation of completed stages.

Coordination and artifact registration now live in the installed package. The old
`scripts.run_project_research_cycle` is a compatibility shim. The scenario-based
`FullWorkflow` remains separate, not evidence of arbitrary research coverage:

1. Prepare a supported task with `scripts.prepare_project_research_task`, including
   `--remote-resource configs/resources/execution/mlrc_unlearning_4090_v1.yaml`.
2. Give its `PLAN.json` to `scripts.plan_project_research --prepared-task PLAN.json
   --compile-selection`. The model may select a task component, a supplied
   campaign template, or neither. A selected task produces `prepared-task/PLAN.json`.
3. Pass that generated plan to `scitaste project research-cycle --workspace CHECKOUT` with the
   baseline, editorial brief and explicit API/execution enablement below.
4. Optionally set `--next-planning-objective` to feed the completed cycle's measured
   outcomes and dispositions into a subsequent proposal (separate USD 3 ceiling).

Task resources, source/scorer bounds and original template identity remain fixed;
model selection changes the scientific study binding, not resource authority.
This currently supports iterative unlearning, not arbitrary task provisioning or
an entire external-framework comparison. Executor/writing/planning backends still
use workspace `scripts.*` modules; checkout-independent backend distribution is
unfinished. The new product entrypoint successfully reused the completed cycle
from `/tmp` with API/execution disabled, without another experiment or model call.
`model-selected-research-cycle-v1` completed the supported path through revised PDF,
experience disposition and next planning. Its final artifact-registration collision
required a no-call resume after a targeted ID fix. This is recovered completion,
not an uninterrupted first-pass run or completion of the general project scope.

## Compile a development task matrix

Eligibility uses explicit development split labels plus pilot scope, not merely
`held_out=false`: existing development protocols may correctly keep held_out=true
to indicate separation from Taste-learning sources. Isolation flags are retained.
Planning can receive `--pilot-template` and `--compile-selection` to generate exact
task/system selections and invoke this compiler directly; neither flag launches
the resulting experiment.

`scripts.compile_design_task_plan` consumes `--project`, `--design`, `--study-id`,
`--template`, `--selection` and `--output`. Selection JSON contains `manifest_id`,
`lane_id`, `task_ids` and `comparisons` (the comparison/system mapping). It creates
`PRELAUNCH.json`, `CELL_PLAN.json`, `DESIGN_BINDING.json` and `COMPILATION.json`.
Only pilot templates with explicit development-use task splits are supported;
held-out Taste-learning isolation flags remain intact. The resulting manifest
has no inherited approval. Its requested primary outcome and configured endpoint
are not automatically equivalent; register and bind the experiment through the
existing evaluation workflow before execution.

## Design-bound campaign execution

`scripts.bind_research_design_campaign` takes a project design/study, existing
evaluation cell plan, existing launcher config and JSON comparison mapping
(`comparison_id: {treatment: system_id, comparator: system_id}`). It writes a new
v1.2 launch config, without executing anything. Pass that config to the normal
evaluation campaign runner; its existing resource approvals and checkpoints remain
in force. Before launch, every mapped comparison must cover matching task, lane,
seed and repetition assignments. This converter does not create missing task
populations or implement prose-defined scoring and external systems.

## Model-backed design handoff

For a design that nominates a supported Native adapter,
`scripts.prepare_project_research_task` additionally accepts `--design-path`,
`--study-id`, `--comparison-id` and `--comparison-arm treatment|comparator`.
All four are required together. They preserve the full study definition inside
the prepared plan and check design immutability on execution. This creates a
single study-component configuration, not an entire matched comparison campaign.
An unavailable executor is rejected rather than replaced by an unrelated task.

`scripts.plan_project_research` consumes a verified idea, project-owned evidence
and a source-bound capability inventory. `--required-comparison-role` can require
external-method, mechanism-ablation or validity-control coverage. A structurally
accepted response produces `DESIGN.json` and `EXECUTION_HANDOFF.json`; the latter
lists each study's selected capability, implementation gaps and resource needs.
Both remain proposals. Neither asserts scientific adequacy nor launches work.
The current inventory has eight maintained entries, not exhaustive runtime
discovery or automatic arbitrary-task provisioning.

## Prepared study through final delivery

`scripts.run_project_research_cycle` takes `--project`, `--plan`, `--brief`,
`--output`, `--baseline-run` and `--baseline-source`. With `--allow-api` and
`--allow-execution` it runs the idea-bound iterative unlearning executor followed
by measured paper generation/review/revision and experience disposition. Without
those switches a new cycle is only prepared. Optional development Taste library
and deliberation profile must be supplied together. It does not provision a new
remote dataset or support arbitrary task executors yet.

The native execution log and terminal receipt are preserved separately. A started
execution without terminal delivery must be observed/reconciled; re-running the
coordinator will not launch it again. Never remove its launch marker to force a
retry. Existing paid paper-stage responses are reused under their frozen inputs.

## Idea-bound execution entry

`scripts.prepare_project_research_task` accepts `--project`, `--task-path`,
`--adapter`, `--candidate-source`, `--study-question` and `--output`. It writes
`PLAN.json` from the verified registered idea and source hashes; it makes no API
call and does not execute an experiment. The study question is an explicit
planning input, not a generated scientific plan.

Pass that file to `scripts.run_native_tools_development --project PROJECT
--project-plan PLAN.json --task ADAPTER --output RUN` plus the existing explicit
live flags and, for iterative tasks, `--iterative`. Existing task context, Taste
capture and deliberation options remain available. Candidate paths are now
project-plan inputs; remote assets/scorers still require the chosen adapter's
resource setup. This is not yet arbitrary-task resource provisioning.

## Measured delivery to revised manuscript

When the delivery includes `experience/COLLECTION.json`, the coordinator also
registers a separate experience-disposition receipt. The standalone
`scripts.finalize_measured_research_cycle` command can attach an already-completed
paper flow without repeating its calls. Optional `--reviews` must bind exact
collected candidates. Abstention preserves observations but does not admit them;
positive reviews remain pending the existing admission process. This path does
not claim operational policy learning or whole-project completion.

`python -m scripts.run_measured_paper_lifecycle --project PROJECT --delivery DELIVERY
--brief BRIEF --output RUN --evidence EVIDENCE --sectioned-draft --allow-api`
composes prepared evidence, section-resumable prose, candidate build/registration,
model review and model revision. Every supplied path is project-owned. Omit
`--allow-api` to allow only already-retained work to be reused. Use a new RUN
identity when changing evidence or the drafting format; never overwrite an old
failed campaign. Individual responses and conservative provider liability remain
in sibling stage directories. A started request without a response requires
explicit reconciliation, not a blind retry.

This entrypoint does not execute experiments or prove the Idea-to-paper lifecycle.
Completed manuscript flow, scientific quality and superiority to baselines are
separate claims. Negative findings and negative reviews are valid flow outcomes;
review closure and scientific admission are not fabricated to complete the flow.

## Bounded live development handoff

Initial candidate construction is available through
`scripts.build_lifecycle_paper_candidate`: provide the project, prepared input,
retained provider response, original registered source run, output checkpoint
directory and a new paper directory. It recovers only supported full responses,
builds Markdown/TeX/PDF and registers an unapproved candidate without changing
current aliases. Resume verifies bindings and refuses incomplete builds rather
than overwriting them. No model call occurs in this step.
The cycle command accepts `--draft-input`, `--draft-response` and
`--draft-source-run` together to perform this construction before review/revision.

The real candidate-paper segment now has a resumable orchestration command:

```bash
.venv/bin/python -m scripts.run_candidate_paper_cycle \
  --project outputs/projects/scitaste-self-development \
  --source-paper unlearning-lifecycle-case-preview-v1 \
  --revised-paper unlearning-lifecycle-case-preview-v2 \
  --review-id unlearning-lifecycle-review-v1 \
  --review-output outputs/projects/scitaste-self-development/evaluations/unlearning-lifecycle-paper-review-v1 \
  --revision-output outputs/projects/scitaste-self-development/evaluations/unlearning-lifecycle-paper-revision-v1 \
  --output outputs/projects/scitaste-self-development/evaluations/unlearning-lifecycle-paper-cycle-v1 \
  --evidence outputs/projects/scitaste-self-development/evaluations/native-unlearning-contextual-taste-development-v1-delivery/SELECTION.json \
  --evidence outputs/projects/scitaste-self-development/evaluations/native-unlearning-contextual-taste-development-v1/CONTRACT.json
```

This invocation reuses the already imported review and registered revision with
zero API calls. For fresh identities, `--allow-api` permits the missing review and
revision stages only (separate USD 2 and USD 3 liability ceilings). A cycle lock
and durable stage-start receipts prevent concurrent duplicate work. Failed or
incomplete stage directories require reconciliation, not automatic re-execution.
Source/evidence changes reject resume. The summary binds source, revised text
and PDF; it does not close review, establish quality or claim whole-project
automation. This is the post-draft segment, not a replacement for idea-to-paper
orchestration. The existing manuscript naming conventions are accepted by both
review and revision so a revised candidate can enter a later cycle.

The iterative Native development command accepts `--finish-at-experiment-limit`.
With this explicit policy, reaching the declared experiment count exits before
another proposal, Taste deliberation or ranking API call. It writes
`loop/RESOURCE_STOP.json` and the normal measured-result delivery follows.
This is a resource-policy stop, not a fabricated controller STOP decision or a
claim of scientific success. Pending execution stays unresolved. Default behavior
is unchanged, and continuation cannot silently change this contract-bound policy.
Use it for finite experimental campaigns whose analysis can consume the delivered
measurements separately; leave it off when further interactive analysis within
the same trajectory is required. It does not increase any experiment/API budget.

`scitaste run full` is the first-party composition of SciTaste's Phase 4--7
workflows. Its core path is deterministic and offline; explicitly configured
evidence advice, native-source generation, or Tool Intelligence may additionally
use bounded model nodes. It is not a
reserved CLI or four disconnected demos. Discovery creates the initial `ResearchState`;
Evidence, Communication, reviewer-driven evidence collection, and Figure
generation each load and extend that same state history.

Run the committed acceptance case with:

```bash
sudo apt-get install bubblewrap  # once on Debian/Ubuntu hosts
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project \
  --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-integration-fixture \
  --seed 7 --output outputs
```

If the run stops during one of the four workflow stages, resume the same
registered run and publication identity with:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_v1.yaml \
  --project-id my-full-project \
  --run-id offline-full-seed-07 \
  --paper-directory offline-full-seed-07-integration-fixture \
  --seed 7 --output outputs --resume
```

The committed default is `scitaste-native`. One first-party executor instance is
shared across Discovery, Evidence, Communication, nested reviewer evidence, and
Figure actions. It emits typed action receipts without inventing mock
observations; its Discovery `SEARCH` action now performs real local retrieval
against a content-bound project copy of the configured Knowledge Library. Its
admitted Evidence experiment executes real CPU code through Bubblewrap and
independently derives metrics from the emitted replicate rows; Evidence then uses
those measured values rather than the scenario's result fixture. Communication
admits that result only through a self-hashed projection that revalidates the
canonical state, interpretation, decision-bound native record, and parsed metric
artifact. Its measured writing path replaces the demo claim/evidence references
and turns the review into an explicit limitation acknowledgement rather than
executing the scenario's second prefilled experiment. The remaining deterministic
workflow components perform bounded scenario operations.
`--backend mock` is an explicit compatibility/test mode. The native run validates
one bounded offline experiment, but does not prove broad experiment compatibility,
model-generation quality, or effectiveness.
`--dry-run` validates the configuration and prints the planned executor and
project/run/paper identity plus Bubblewrap availability without writing files.

## Native Scientific Taste conditions

`native_condition_config` turns the first-party workflow into an exact treatment
runtime instead of treating `condition` as a reporting label. The committed
matrix at `configs/evaluation/native_taste_condition_matrix_v1.yaml` admits only
six profiles: Native Base, Native Knowledge, Native Taste, Native Critics, Full
SciTaste, and a mismatched-Taste placebo. It fixes utility-policy, Knowledge,
Taste-corpus relation, and Taste-critic switches for each profile. The same
controller/retriever policy is then passed through Discovery, Evidence,
Communication, and Figure rather than allowing each stage to construct a
different implicit controller.

Run the structural acceptance without contacting a provider or GPU:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_native_conditions_v1.yaml \
  --project-id native-condition-check \
  --run-id full-seed-07 --seed 7 --output outputs --dry-run
```

Dry-run reports the condition ID, role, exact component switches, matrix file
hash, semantic fingerprint, and integrity-gate invariant without creating a
project. A real offline acceptance materializes one content-bound Knowledge/Taste
library and selectively exposes it according to the chosen profile. Unknown
conditions, profile drift, missing required libraries, symlinks, oversize files,
and mid-run matrix changes fail closed.

Taste critics modify action ranking but never become hard evidence or safety
gates. Evidence obligations, writing-integrity criticism, visual criticism,
resource budgets, code admission, and sandbox isolation remain enabled for all
six profiles. Component-only arms measure sufficiency, Full--Base measures the
whole explicit Taste bundle, and Full--mismatched changes only corpus relation.
The committed workflow uses `provider: mock` and a deterministic controller: it
is an integration fixture, not evidence of model-backed effectiveness or a
formal experiment launcher.

### Bounded candidate generation

`native_candidate_generation_enabled: true` extends the pinned native
preference backend to the step immediately before action selection. The stage
workflow still owns a closed set of executable templates. For every feasible
template the model must return exactly one concrete description and rationale;
it cannot invent an action identifier, type, tool, cost, value, precondition, or
protected parameter. Deterministic admission permits only one operational
override: a bounded non-empty `query` for a template that is already a `SEARCH`
action and already declares a query. Retrieval limits and domains remain
controller-owned.

The admitted actions retain template identifiers and order. The durable
decision stores a separate candidate-generation trace before the fixed-candidate
selection trace, including hashes of the context, template set, admitted set,
raw response, backend/model identity, attempts, latency, token usage, rationales,
and admitted override keys. Missing or duplicate templates, identity or
fingerprint drift, malformed output, protected overrides, and raw-response hash
drift fail closed without deterministic fallback. A single feasible action
remains deterministic and spends no generation or selection call.

This is bounded autonomy rather than open execution. The current Qwen3-VL-2B
configuration enables the path for offline integration testing, but enabling it
does not authorize checkpoint loading. `--allow-live-model-nodes` remains
mandatory, and no real model execution is claimed by the fixture tests.

## Open-question intake

The optional `research_brief` config field moves Full Workflow's entry boundary
from an implicit topic string to a strict research contract. The brief fixes one
question and objective, project identity, exact executable Discovery budget,
required evidence types, success criteria, constraints, and prohibited claims.
For example:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_open_question_offline_v1.yaml \
  --run-id open-question-seed-07 --seed 7 --output outputs --dry-run
```

Dry-run builds the same self-hashed `WorkflowLaunchPlan` used by execution and
reports its readiness, input hashes, authority boundary, and known limitations
without creating `outputs/`. Admission fails if brief/config identity differs,
the brief budget is not the executable Discovery budget, or any configured
Evidence/Communication requirement lies outside the brief's authorized evidence
types.

The committed config uses a content-bound `scenario_catalog`. Before mutation,
`deterministic-catalog-selection-v1` filters complete four-stage bundles by exact
domain, executable budget, authorized evidence types, and question/objective
keyword matches, then ranks ties by hit count and stable bundle ID. Dry-run
reports the selected and eligible bundle IDs. Directly configured scenarios
remain supported through `deterministic-registered-inputs-v1` for pinned
experiments.

On formal execution, the plan, exact brief, catalog, and selected scenario bytes
are published under the owning run before stage work begins. All four stages then
load the run-owned copies. Source drift between inspection and copy, copy drift,
plan drift, and resume-time tampering fail closed. A partially published intake
can be completed on explicit resume only when every existing byte still matches
its registered hash. Catalog selection admits only registered actions; it does
not generate arbitrary Discovery, Evidence, Communication, or Figure code. A
`ready` plan is an execution admission result, not an effectiveness or
publication claim.

An opt-in offline acceptance config also exercises a bounded semantic node in
the real evidence-stage path:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_model_advisory_v1.yaml \
  --project-id my-advisory-project \
  --run-id offline-advisory-seed-07 \
  --seed 7 --output outputs
```

After deterministic evidence interpretation, the hook projects an immutable
slice of the actual `ResearchState` and invokes `interpretation-threat` through
the normal project-owned model-node runtime. The committed backend is scripted,
costs zero, has no network or tool path, and exists to validate integration—not
model quality. Its accepted output remains a proposal: it cannot update claims,
select an action, execute a tool, or mutate state. The record proves this by
binding identical input/output state hashes.

Tool Intelligence is a separate optional post-interpretation hook:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_tool_intelligence_v1.yaml \
  --run-id offline-tool-intelligence-seed-07 \
  --seed 7 --output outputs
```

A deterministic claim-status policy first decides whether a registered hotspot
exists. If it does, the run publishes an immutable state/evidence request,
invokes the normal typed model ledger, admits at most one dependency-free tool
step, issues a single-use lease, and executes the registered read-only handler.
The committed case inspects one exact project-owned evidence record. The
observation and final decision remain `advisory_only`; they are neither canonical
evidence nor authority to advance `ResearchState`. Resume verifies and reuses the
model and tool ledgers without repeating a completed call.

The live engineering condition is separately configured and double-gated:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_zhipu_model_advisory_probe_v1.yaml \
  --run-id glm53-advisory-probe-seed-07 \
  --seed 7 --output outputs --allow-live-model-nodes
```

Both the content-bound advisory/profile/backend configuration and the caller
must enable live execution. Omitting `--allow-live-model-nodes` fails before a
project is created. The committed GLM-5.3-Flash condition has no verified price,
so it is an engineering probe: usage and the raw response are retained, cost is
unknown, and the proposal is deterministically rejected. It cannot support an
effectiveness claim.

Native experiment source has a separate optional generation hook:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_code_generation_v1.yaml \
  --project-id my-code-generation-project \
  --run-id generated-code-seed-07 \
  --seed 7 --output outputs
```

The scripted condition traverses the real model-node ledger, source extraction,
static admission, Bubblewrap experiment, measured-evidence projection, and paper
publication path without network access. The model controls only source,
rationale, and assumptions; the project controls experiment identity, metrics,
imports, limits, backend, and budget. The live engineering configuration uses
`full_zhipu_glm53_flash_code_generation_probe_v1.yaml`, requires
`--allow-live-model-nodes`, and is deliberately non-promotable until an auditable
price for that exact model is available. See `docs/NATIVE_CODE_GENERATION.md`.

An additional offline acceptance config exercises a real project-owned dataset
mount:

```bash
.venv/bin/scitaste run full \
  --config configs/workflows/full_offline_dataset_v1.yaml \
  --run-id dataset-seed-07 --seed 7 --output outputs
```

The workflow verifies the registered dataset hash, copies the exact bytes into
`native_execution/context/resources/`, and mounts only that copy read-only at
the derived `/datasets/<dataset-id>` path. `--dry-run` validates the source data
and optional GPU identity without materializing a project. GPU access remains
disabled unless a separate profile explicitly admits device indices and a
GPU-hour ceiling. See `docs/NATIVE_EXECUTION.md`.

## Project layout

One execution owns this tree:

```text
outputs/projects/<project-id>/
├── PROJECT.json
├── runs/<run-id>/
│   ├── full_run_summary.json
│   ├── intake/{BRIEF.yaml,PLAN.json,SCENARIO_CATALOG.yaml}
│   ├── intake/scenarios/{discovery,evidence,communication,figure}.yaml
│   ├── finalization/PLAN.json          # write-once stage/paper input binding
│   ├── failed_attempts/stages/<stage>/attempt-NNN/  # when resumed
│   ├── failed_attempts/finalization/{paper,summary}/attempt-NNN/
│   ├── model_nodes/{ledger,recordings,pending,attempts}/ # when opted in
│   ├── native_execution/{context,artifacts,records}/ # native action evidence
│   │   ├── context/code_generation/ # generated-source evidence when opted in
│   │   ├── context/code/            # deterministic admission and admitted source
│   │   └── context/resources/       # profile plus copied datasets when opted in
│   └── stages/
│       ├── discovery/
│       ├── evidence/model_advisory_input.json # pre-call, when opted in
│       ├── evidence/model_advisory.json  # result bridge, when opted in
│       ├── communication/{evidence_projection.json,paper.md,paper.publication.md}
│       └── figure/
├── stages/current -> ../runs/<run-id>/stages
├── papers/<paper-directory>/
│   ├── MANIFEST.json
│   ├── main.md
│   ├── main.tex
│   ├── main.pdf              # when XeLaTeX is available
│   ├── build.json
│   ├── ASSESSMENT.json
│   └── figures/{figure.svg,figure.drawio}
├── papers/current -> <paper-directory>
└── surfaces/<run-id>-snapshot-binding.json
```

Each stage contains a self-hashed `STAGE.json`. It states the stage purpose and
records run-relative locators plus SHA-256 hashes for the input state, output
state, decision log, and required stage artifacts. Paths recorded by the
full-run summary are run-relative rather than machine-specific absolute paths.

The default paper is a registered `integration-fixture` with
`publication_ready: false`; it proves that evidence projection, reader-facing
sanitization, Markdown-to-TeX conversion, PDF compilation, figures, manifests,
and project registration compose correctly. It is not a reviewed research
manuscript and must not be presented as one.

`communication/paper.md` is the audit view and retains machine-readable
claim/evidence trace markers. `paper.publication.md` is the deterministic
reader-facing view: it removes internal trace and obligation identifiers but
cannot add prose, measurements, or claims. The registered `main.md`, `main.tex`,
and optional PDF are built from that reader-facing view. Markdown-to-TeX
packaging is deterministic and performs no extra model call. If
`latexmk` with XeLaTeX is installed, compilation must succeed and `main.pdf` is
registered; otherwise `build.json` records `unavailable` and the Markdown/TeX
bundle remains complete.

Every bundle includes `ASSESSMENT.json`, a self-hashed deterministic role and
completeness record. A configuration may request `research-working-draft`, but
publication then fails closed unless the manuscript has at least 2,500 counted
words, all required Abstract/Introduction/Method/Evaluation/Results/Limitations/
Conclusion sections, and no known placeholder marker. This is a minimum
classification gate, not a scientific-quality or peer-review judgment. The
substantive SciTaste framework manuscript is maintained separately at
`manuscripts/scitaste/main.md` and registered under the `scitaste-self-development`
project when its source and compiled bundle pass acceptance.

## Revision and failure behavior

The workflow creates the project when it does not exist, otherwise it requires
the existing research identity to match. Every run ID must be new. Repeated
iterations in one project should use a new `--run-id` and
`--paper-directory`; historical runs and paper versions are never overwritten.

Project mutations use the same optimistic revisions and file locks as manual
project commands. A successful run is selected, marked complete, linked to its
final state and stage records, and owns the selected paper. If a later phase
fails, completed stage artifacts remain in place and the registered run is
marked `failed` with the exception type and bounded message for diagnosis.

`--resume` accepts only a previously registered failed run with the same
provider, model, condition, seed, evidence scope, stage path, and content-hashed
workflow configuration (including the optional research brief, scenario catalog,
all four scenario files, and optional advisory, Tool Intelligence, or
source-generation profile bindings). It reuses only
the contiguous completed prefix whose record, state continuity, project
identity, lifecycle position, and every declared file hash still validate. A
missing completion record means that stage is incomplete: its existing directory
is atomically moved to `failed_attempts/stages/<stage>/attempt-NNN/`, and that
stage plus every downstream stage is rerun. A malformed completion record or a
hash mismatch is treated as possible tampering and fails closed; it is not
silently archived or regenerated.

When model advice or Tool Intelligence is enabled, evidence-stage reuse
additionally revalidates the self-hashed pre-call input record and advisory
result, immutable predecessor and evidence states, decision log, evidence
summary, complete model-node ledger totals/head, exact response recording,
and—where applicable—the controlled tool binding, lease, observation, and
decision ledger. A verified prefix therefore does not call the backend or tool
again. Multiple Full Workflow model-node hooks share one typed ledger;
historical receipts bind the exact prefix visible when they were issued, while
final verification covers the complete chain.

The input record is published before provider access and cannot be overwritten.
If a live response was durably recorded but the process stopped before ledger
publication, `--resume --allow-live-model-nodes` reconstructs the exact original
request, consumes that recorded response without provider access, and records
its original token/cost telemetry once. Because the project revision advanced
while failure/recovery metadata was written, the recovered proposal is
conservatively rejected as stale. If the ledger was already published, resume
returns that exact entry without another call. If a live call may have started
but no complete response exists, its cost remains unknown and resume refuses to
repeat it. An invalid input checkpoint fails closed instead of being archived.

Finalization has a separate write-once, self-hashed plan binding all four stage
records, the final state, publication manuscript, editable figures, workflow
configuration, and intended paper identity. If all four stages already validate,
`--resume` continues finalization without executing a stage again. An incomplete,
unregistered paper directory is moved intact beneath
`failed_attempts/finalization/paper/` before deterministic rebuilding. A
registered paper is reused only when every declared file hash, assessment,
source, figure, and manifest field still matches the plan; drift fails closed.
Likewise, a summary left before an interrupted completion-metadata update is
archived before a fresh revision-bound summary is published.

If the command stops after the run becomes complete but before its generated UI
snapshot binding is published, the same `--resume` command verifies the complete
run, plan, summary, paper, and project identity and writes only the missing
binding. It performs no model, retrieval, experiment, writing, or figure action.
An existing binding with different content is treated as tampering rather than
overwritten.

Native execution resume first validates its contiguous predecessor chain, every
bound Knowledge or experiment-source input, every generation/ledger/admission
binding, every action artifact, and the record hash/action/result identity
embedded in each reusable stage decision. Tampering with the local Knowledge
copy, generated or registered source, retrieval output, raw process output, or
derived metrics therefore blocks reuse before a stage can advance. See
`docs/NATIVE_EXECUTION.md` for the record contract.

The Communication stage independently repeats the relevant binding checks before
writing: exactly one successful registered experiment must resolve to one
interpretation review, one supporting evidence item, one supported claim, and one
hashed metrics artifact whose replicate rows reproduce the reported mean and
population dispersion. `evidence_projection.json` and both paper views are part
of the stage artifact manifest, so deleting or changing any of them blocks resume.

After completion, `ProjectSnapshotAdapter` hashes the authoritative manifest,
run tree, current stage, paper manifest, and every declared paper artifact into
`surfaces/<run-id>-snapshot-binding.json`. That record can ground a trusted
Generative UI surface but has no execution authority.

## Configuration boundary

`configs/workflows/full_offline_v1.yaml` chooses the four typed scenario files,
a versioned native Knowledge seed, and one typed native code proposal, and owns
the canonical project/publication identity. The proposal is inspected without
mutation during `--dry-run`; an actual run durably publishes its policy,
proposal, verdict, proposed source, and accepted source before constructing the
Bubblewrap runner. Scenario files contribute
phase-specific claims, evidence, narrative contracts, review feedback, and
figure contracts; their standalone demo project IDs are replaced and revalidated
against the full-workflow project. This permits reusable phase fixtures without
splitting the resulting project state.

`configs/workflows/full_offline_model_advisory_v1.yaml` adds the content-bound
`full_model_advisory_scripted_v1.yaml`. The live probe instead uses
`full_model_advisory_zhipu_glm53_unpriced_v1.yaml` and its content-addressed live
profile set. Loading rejects embedded credentials, unrestricted code generation,
tools, non-zero scripted cost, inconsistent live gates, and policy/profile/
backend identity drift. `--dry-run` reports the backend mode, both authorization
gates, and whether a real execution would contact a provider without creating a
project or accessing the network.

`configs/workflows/full_offline_tool_intelligence_v1.yaml` adds the
content-bound `full_tool_intelligence_scripted_v1.yaml`. Its controlled profile
names exact tools and evidence IDs; loading and dry-run reject permission,
backend, profile, trigger, budget, or authority drift. A profile valid for one
evidence identity is not silently generalized to another workflow result.

`configs/workflows/full_offline_code_generation_v1.yaml` replaces the registered
source proposal with a content-bound generation configuration and 8,192-token
provider envelope. Dry-run reports the generation/provider/admission/isolation
plan without creating a project. Execution checkpoints its complete trusted
brief before any backend access; only a cost-admitted ledger result is projected
into a model-attributed proposal, and that proposal still requires the same
deterministic admission and isolated runner. The GLM-5.3-Flash variant reads only
the `ZAI_API_KEY` environment variable and never stores credentials in YAML.

AutoResearchClaw is not modified or invoked by this acceptance case. It remains
an optional baseline/compatibility adapter. The native path now owns local
retrieval plus one admitted isolated CPU experiment and its metric extraction.
The same experiment can now originate from a first-party bounded provider-backed
proposer while remaining behind independent admission and isolation. Explicit
dataset and NVIDIA device profiles now provide a default-deny resource boundary.
Open-web retrieval, iterative code repair, portable package/model environment
construction, cross-host CUDA reproduction, and long-form generation remain
capability-parity work. One content-bound local Qwen3-VL-2B text/vision workload
has passed on the registered RTX 3090, but it is execution-boundary evidence and
not a model-quality result; subsequent work must preserve the same
ProjectRuntime ownership, state-continuity, evidence-binding, and
failure-retention contracts.

## Project lifecycle control

`scitaste project lifecycle advance` is the execution control plane above the
native full workflow and venue review runtime. One call runs or resumes the
configured Discovery--Evidence--Paper lineage, registers the paper as current,
prepares an exact venue-review packet, and returns the first boundary that needs
new semantic or external input. A second call may supply a structured
`--review-proposal`; accepted no-concern development reviews close directly,
while concern-bearing reviews are projected into an immutable project-owned
`paper_revision_context` run. That handoff partitions prose-only, formally
proof-backed, and still-blocked concerns and exposes the exact Stage 19 model
input fingerprint. Repeating the command verifies and reuses the registered
full run, paper adoption, review, and revision context instead of duplicating
them.

Lifecycle status also composes the standalone project registries used by longer
research programs. A current Idea Revision satisfies the Idea gate only after
its record, narrative, and every declared evidence input revalidate. A selected
evaluation result satisfies the Evidence gate only after the result bundle and
assessment replay as complete and headline-eligible. This lets an incrementally
developed project enter the same control plane without rerunning discovery or
experiments merely to satisfy one workflow shape; paper lineage, exact evidence
binding, review closure, and independent review remain separate gates.

Official external benchmarks with hidden model-judged rubrics use a distinct
`official_benchmark_score` endpoint. They are neither relabelled as deterministic
GPU objectives nor treated as human package preference. Admission requires the
exact benchmark task allocation, official judge protocol, disclosed judge model,
fail-closed rubric parsing, and a matched `complete_system_bundle_effect`
contrast. This contrast may support the complete-system title claim, but it does
not substitute for SciTasteBench's representation and transfer-mechanism tests.

For Stage 19 papers, lineage follows the registered
`paper_revision_source_paper_directory` chain back to the native source run.
Missing links, malformed pointers, or cycles block the gate; a revision never
loses valid provenance merely because its immediate source run is a model-node
invocation.

```bash
scitaste project lifecycle advance \
  --project-id scitaste-lifecycle-control-example \
  --full-config configs/workflows/lifecycle_control_offline_v1.yaml \
  --run-id lifecycle-control-e2e-001 \
  --review-id lifecycle-control-review-001
```

An already registered concern-bearing review can enter the same path without
rerunning Discovery or Evidence:

```bash
scitaste project lifecycle revise \
  --project-id PROJECT \
  --paper-directory PAPER \
  --review-id REVIEW \
  --source-commit COMMIT \
  --evaluation-evidence-run-id ADMITTED_EVIDENCE_RUN
```

New full-workflow papers use canonical machine labels such as
`source-markdown`, `bibliography`, and `paper-argument-contract`. A workflow can
bind `paper_bibliography` and `paper_argument_contract` in its YAML; both source
files are content-bound by the workflow and finalization plans. The argument
contract must identify the exact project/paper and exact manuscript SHA-256, so
a superficially compatible contract cannot be attached after generation.

The offline example validates orchestration only and cannot establish scientific
effectiveness. The controller never converts a mock run, interactive-session
review, or missing independent review into scientific or official authority.
Resource-backed experiments, selected headline-eligible results, exact paper
evidence binding, and independent pre-submission review remain separate verified
gates in `project lifecycle status`.
