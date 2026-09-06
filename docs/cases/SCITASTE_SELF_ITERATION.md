# SciTaste self-iteration case

SciTaste's own development is a useful dogfooding case because each milestone
contains a problem, competing actions, evidence, costs, a selected intervention,
and an observable outcome. It is used for workflow usability and auditability,
not as evidence that SciTaste improves research quality.

The canonical project-level record is
`outputs/projects/scitaste-self-development/`. It owns the self-development
iteration index and points to immutable raw evidence without copying or renaming
historical runs.

## Phase 7.5 case

The case asks how to deepen AutoResearchClaw integration before Phase 8. It
compares three normalized ideas:

1. keep upstream immutable and strengthen the external contract adapter;
2. fork AutoResearchClaw and insert SciTaste control logic into its runner;
3. defer real integration and benchmark only mock/replay execution.

One real-substrate probe recorded that qwen3.8-max completed AutoResearchClaw
Stages 1–3, Stage 3 produced three validated artifacts, and the submodule remained
clean. The controller selected the external adapter with score `3.744`, versus
`1.280` for deferral and `-0.545` for a fork. The trajectory contains one probe
and ends at `PILOT`.

Run the case locally with:

```bash
scitaste discover \
  --config configs/cases/scitaste_phase75_self_iteration.yaml \
  --output outputs/scitaste-self-iteration-phase75 \
  --seed 7
```

The scenario and its expected selection are regression-tested. Generated state,
decision logs, and summaries remain ignored because they contain runtime paths
and timestamps.

## Phase 9 four-condition case

The Zhipu GLM-5.2 preacceptance is a second dogfooding episode. Four real system
conditions completed one frozen task, while failed gates exposed a resume-order
bug, a negation-sensitive evidence audit, a wrong derived grid count, an empty
factor slice, and an expensive per-example refit. The resulting fixes are
regression-tested and the failed/slow Full attempts are retained alongside the
raw runs. A fresh Full selected experiment reduced execution from 734.58 seconds
to 0.63 seconds after the prompt began enforcing feature reuse.

This episode supports claims about traceability and defect discovery only. It is
not evidence that Full SciTaste outperforms the other conditions: the cells were
continued after fixes, so runner duration is not a matched comparison. Promotion
of any lesson from this episode into the Taste Library still requires a separate
outcome review and human verification.

## Tool-intelligence model-node case

The next self-development decision asks how to make the deterministic SciTaste
core responsive to open-ended context. Three alternatives are registered:

1. keep every decision deterministic and manually encode new semantic cases;
2. add bounded model nodes for interpretation, candidate proposal, and ambiguous
   action ranking while deterministic gates retain authority;
3. allow an unrestricted model agent to call tools, modify code, update evidence,
   and stop runs.

The provisional selection is the bounded-node option. Its first pilot covers a
review semantic parser, an interpretation-threat critic, and an ambiguity-triggered
action ranker. New online Zhipu calls are pinned to `GLM-5.3-Flash`; local 2B/4B
models remain a separate condition.

The nodes and their project-owned orchestration are now implemented. On
2026-09-05 a seven-case engineering run invoked the real GLM-5.3-Flash endpoint,
retained its exact request/response without credentials, and completed the
registered offline recording/replay cases. The live JSON was schema-valid but
the proposal was rejected by token, latency, unavailable-cost, and action
allowlist gates. An earlier truncated response was retained as a failed attempt
before the corrected content-addressed run. This establishes endpoint,
provenance, recovery, and enforcement behavior only; missing external manual
measurements, verified pricing, an unsupported-action safety failure, and
independent review keep the pilot blocked and ADR-022 proposed.

The project record freezes the alternatives, current cost baseline, hard safety
boundaries, and falsifiable acceptance gates. It remains
`retrieval_eligible=false`, and the registered Phase 9 protocol is not modified
mid-study. The detailed run ledger is
`docs/experiments/zhipu_glm53_model_node_probe_2026-09-05.md`.

The same design has now entered the actual `run full` evidence path. A
content-addressed GLM-5.3-Flash condition and a separate caller switch must both
authorize the call. The workflow publishes its immutable inputs before provider
access; if a paid response was recorded before interruption, resume parses and
accounts that exact response without calling the provider again. If completion
is ambiguous, it records unknown cost and refuses a repeat. This is a concrete
dogfooding result for the earlier “tool intelligence” idea, but remains
engineering/recovery evidence rather than evidence of better scientific taste.
The corresponding real Full Workflow run is indexed in
`docs/experiments/zhipu_glm53_full_workflow_advisory_2026-09-05.md`.

## Project-owned substrate-action case

The self-development project also owns the first live test of the new
AutoResearchClaw action lifecycle. A Zhipu GLM-5.3-Flash call reran only the
selected search-strategy stage from an imported immutable source snapshot. The
three expected artifacts, fresh checkpoint, exact terminal summary, working-tree
hash, action state, and ProjectRuntime metadata passed independent revalidation.

The run is intentionally classified as online engineering evidence. Its single
request used 4,509 tokens and hit the 4,096 completion ceiling; upstream emitted
no API-cost log, and web search was disabled. The generated search terms are
broad fragments rather than an accepted literature strategy. These negatives
are retained rather than converted into a taste-quality success. The detailed
ledger is
`docs/experiments/zhipu_glm53_project_substrate_search_2026-09-05.md`.

A follow-up closes the remaining source-ownership gap. The same project created
Stages 1–2 through a registered bootstrap run, issued an immutable source
receipt, and then bound a new selected Stage 3 run to that receipt. Both runs
passed independent rehash. The bootstrap used 3,484 tokens and the Stage 3
increment used 4,571; cost was again unavailable and the selected response again
reached its completion ceiling. This is a stronger lifecycle result, but it
retains the same engineering-only classification. The receipt and manifest
ledger is
`docs/experiments/zhipu_glm53_project_owned_stage13_2026-09-05.md`.

## Native execution ownership case

The later product-positioning decision compares three different relationships
with AutoResearchClaw:

1. keep AutoResearchClaw as SciTaste's mandatory default runtime;
2. copy or fork the complete upstream implementation into SciTaste;
3. make a first-party SciTaste executor the default while retaining the pinned,
   unmodified upstream only as an optional baseline and compatibility adapter.

The third alternative is selected in ADR-028. It gives SciTaste one public
product boundary and permits independent system comparison without hiding an
upstream framework inside the claimed system. Wholesale copying is rejected
because it would preserve fixed-pipeline coupling while making license,
provenance, maintenance, and causal attribution harder.

The first implementation result is deliberately narrow: the Phase 4--7 Full
Workflow now shares one `SciTasteNativeExecutor`, explicit `--backend mock`
remains available, non-successful execution cannot advance state, and the wheel
build/import succeeds without packaging AutoResearchClaw. These results establish
architectural ownership only. Native open-ended retrieval, code generation,
sandbox execution, metric extraction, analysis, and generative writing remain
registered work, and no superiority claim follows from this self-development
case.

The next implementation increment closes the first part of that registered
work. Native `SEARCH` now executes against a project-owned, content-bound
Knowledge Library and stores the exact ranked result. Every selected native
action receives a chained record binding its pre-state, action, inputs, outputs,
and result; resume verifies those records against the stage decision log. This is
evidence that the architectural choice can support a real capability without
AutoResearchClaw, but it is still not open-web retrieval or outcome superiority.

The following increment closes the registered offline experiment boundary. The
default Full Workflow now copies one exact CPU source into its owning run,
executes it through a shell-free Bubblewrap launcher without network, host-project,
GPU, or writable-filesystem access, and retains bounded stdout/stderr and resource
telemetry. Its strict machine record contains three replicate rows; SciTaste
independently recomputes their metrics and Evidence replaces the old configured
result fixture with that measured result before interpretation. Host-file,
network, write, timeout, malformed-record, missing-isolation, and output-ceiling
tests are retained. This demonstrates project-owned execution mechanics only:
the experiment is a small committed synthetic CPU case, so the self-development
case remains excluded from effectiveness evidence and from Taste promotion.
The next increment closes that visible evidence-to-writing gap. Communication now
accepts a self-hashed projection only after the canonical state, interpretation,
decision-bound native record, and parsed replicate artifact agree. Its Results
contract reports the actual mean, replicate values, population dispersion, and
synthetic-offline limitation; the old configured `0.11` result cannot enter this
path. The stage retains a trace-rich audit draft, while the project paper is built
from a reader-facing projection that removes internal claim, evidence, and
obligation identifiers without adding scientific content. This strengthens
integration provenance but remains excluded from effectiveness evidence.

The local acceptance run is registered under the existing project boundary at
`outputs/projects/scitaste-offline-full/runs/2026-09-06__native__evidence-writing__seed-07/`;
its paper is the sibling project artifact
`papers/2026-09-06__native__evidence-writing__reviewed-draft/`. It completed 18
first-party action records, projected three measured replicates with a mean
correct-pivot delta of `0.100000` and population SD `0.000000`, and produced
Markdown, TeX, and a compiled PDF. These ignored local outputs are inspectable
engineering evidence; the committed tests reproduce and verify their contracts.

## Project-owned composable Discovery case

The public Phase 4 commands exposed a new dogfooding problem: each command had a
valid immutable state and receipt, but a caller still chose unrelated output
directories and manually threaded state paths. Three alternatives were recorded:

1. wrap the commands in a revision-reserved ProjectRuntime transaction while
   retaining explicit nonlinear advancement;
2. remove independent advancement and force Discovery through the monolithic
   Phase 4--7 Full Workflow;
3. leave outputs caller-managed and infer ownership later through the catalog.

The first option is the registered high-value choice. Its deterministic probe
runs the weak trajectory as six project-owned steps, verifies state and decision
lineage, rejects stale/invalid admission without mutation, and interrupts both
after step persistence and before head publication. In both post-execution
cases, explicit resume commits the existing result without another executor
call. The scenario is
`configs/cases/scitaste_project_owned_discovery_iteration.yaml`.

This is evidence that the project lifecycle can own an interactively composed
Discovery run. The scenario, executor, and observations are deterministic; it
does not show that model-generated hypotheses are good, that open-ended research
is autonomous, or that SciTaste outperforms another system.

The first self-project attempt is retained as a failed admission: its scenario
declared zero GPU budget while the registered diagnostic probe costs `0.1`
GPU-hours, so TasteController refused to bypass the budget. After correcting the
declared budget, the successor run
`2026-09-07__scitaste-native__project-owned-discovery-v2__seed-07` completed four
commands and eight decisions at `PILOT`; independent verification bound the
final state and `DISCOVERY.json` head. This is exactly the kind of project
configuration defect that self-iteration should preserve rather than conceal.

## Anti-self-confirmation rules

- Self-iteration cases are excluded from headline Phase 8 effectiveness scores.
- Their primary claims are usability, traceability, and defect discovery—not
  scientific superiority.
- Negative evidence is retained, including long prompt latency, an upstream
  topic-specificity warning, run-ID discontinuity, and unavailable API cost.
- Candidate alternatives and scoring inputs are versioned before results are
  interpreted.
- Independent benchmark tasks and matched external baselines remain mandatory.

Future milestones can add cases to this series, but a successful implementation
must never be converted automatically into a retrieval-eligible Taste Case. That
promotion requires a separate outcome review and human verification.
