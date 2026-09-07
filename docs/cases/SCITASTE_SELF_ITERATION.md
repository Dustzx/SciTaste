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

The optional project-owned AutoResearchClaw handoff has also been hardened using
the same self-development criterion: a successful selected-action result is now
a durable no-repeat boundary. A controlled interruption after result publication
resumes by revalidating the pinned command, predecessor, terminal stage evidence,
incremental cost, complete work tree, pre-call invocation, decision, state, and
verification without a second executor call. The same lock and failure-validation
boundary now covers the Stage 1–2 bootstrap. A hard-crashed `running` run can
recover only from a verified success; changed, missing, or contradictory evidence
remains blocked rather than spending again. This is a recovery/integrity result
for the compatibility adapter, not a reason to make it SciTaste's default path.

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

## Bounded semantic Discovery case

The next self-iteration addresses the remaining fixed-content boundary. A
project-owned command could already recover its deterministic execution, but
`hypothesize` still copied intuition and hypothesis prose from the scenario.
The chosen alternative adds a typed, proposal-only semantic node after project
reservation. Direct state/tool authority and a larger template library remain
explicit comparators rather than being conflated with the chosen mechanism.

The registered scenario is
`configs/cases/scitaste_bounded_semantic_discovery_iteration.yaml`; its offline
structured condition is
`configs/model_nodes/discovery_hypothesis_self_iteration_v1.json`. Acceptance
requires content different from the fallback seed, the same three controller
actions, rejection of unknown source/probe identifiers, known resource usage,
one hash-bound ledger entry, and no second backend call after downstream failure.
The complete self-run is integration evidence only: scripted semantic content
cannot establish scientific-quality improvement or open-ended autonomy.

The real self-run exposed one additional validator defect after its probe step:
the first implementation expected inherited semantic provenance to disappear in
successor states. The step had already completed atomically, so the corrected
validator recovered and committed it without another execution. The run keeps
that recovery count and command identity as negative evidence instead of hiding
the failed intermediate project revision.

The completed run is
`2026-09-07__scitaste-native__bounded-semantic-discovery-v1__seed-07`. It reached
`PILOT` through four commands and eight controller decisions, retained one
292-token/zero-cost scripted semantic ledger entry, selected
`idea-01-bounded-semantic-node`, and ended at state
`state-e2606a0f9700da5cc33d2ae95221887b98808e505ab072e9b25e49034164312e`.
The verified Discovery head is
`93373a4754e42c2f3c037bf487a4b184e46f5ea59470b977869059ca0ab434e2`;
the proposal digest is
`5618ee996482335595636503ca5c946e0ebb43ed257bd88be4db0550aa3b6e04`.

## Evidence-bound semantic reformulation case

The initial semantic node did not yet make the nonlinear loop adaptive after a
probe changed the evidence. The next self-case therefore preserves a stable
contradiction, asks a separate typed node for revised hypothesis content, and
keeps `REFORMULATE_HYPOTHESIS` under deterministic controller authority. Its
scenario is `configs/cases/scitaste_semantic_reformulation_iteration.yaml`; the
second offline condition is
`configs/model_nodes/discovery_reformulation_self_iteration_v1.json`.

The first attempted run, ending in `semantic-reformulation-v1__seed-07`, exposed
a configuration-binding defect: the CLI constructed every scripted backend with
the initial hypothesis invocation ID. The project retained the failed run and
archived attempt. The fix hashes the complete non-secret backend fixture and
constructs it for the actual command-derived invocation ID; the failed run was
not rewritten or silently resumed under a different identity.

The replacement run
`2026-09-07__scitaste-native__semantic-reformulation-v2__seed-07` completed six
commands and ten controller decisions at `PILOT`. Its ordered ledger contains an
initial proposal and one state-bound reformulation (630 total scripted tokens,
zero cost); the latter cites `obs-probe-01-working-hypothesis-01`, while the only
selected reformulation action remains controller-generated. The selected idea is
`idea-01-semantic-history`, the final state is
`state-37df39047a85335e3bbdddf690b32f2aef2baab49abfb8d91372f08b3c02ae99`,
and the verified Discovery head is
`e09c1a20e8801b516f8f770319e617523fd0eeee8d211dde5620d15b85f0e22f`.
The reformulation proposal digest is
`2b134a32dd427db187f591320514707b84821bfd40f61cebee00c4c3da677929`.
This remains implementation/recovery evidence, not a model-quality result.

## Evidence-bound semantic ideation case

The next self-iteration removes the remaining fixed problem/idea prose from the
adaptive Discovery path without giving the model portfolio or execution
authority. `discovery-ideation` receives the active hypothesis, exact registered
observations, research identity, and resource ceilings. It returns one problem
and three divergent idea seeds; deterministic validation rejects invented
evidence, a different active hypothesis, duplicate mechanisms, malformed value
scores, and per-idea estimates beyond the project budget.

The completed run is
`2026-09-07__scitaste-native__semantic-ideation-v1__seed-07`. It reached `PILOT`
through six commands and ten controller decisions. Its ordered three-entry
semantic ledger contains 1,110 scripted tokens, zero cost, no rejected or
unknown-cost entry, and chain head
`95fd9f9f56a4e54335f41fa9fc66ccb13801eaae42e301ab4871318beb135037`.
The final controller-selected idea is `idea-01-semantic-continuity`; the other
two model-proposed candidates remain explicit backups rather than silently
discarded output.

The final state is
`state-f9e348873e3a0fb62b276151f79a49fa208409dda01126a0202557fa55e3214f`,
the verified Discovery head is
`daf55d5925c5360169e0c3ec933a589f58309aa6489683b00bafcf4f94154707`,
and the ideation proposal digest is
`2eee560118d638f962bac6b90caaa9922e236ea23394ddbf651c2f536bbc3ba8`.
Independent tests also cover unknown observation/hypothesis rejection,
per-idea budget rejection, mutation-free preview, and no-second-call recovery.
This is implementation and lineage evidence only; the scripted content does not
establish live-model creativity or scientific effectiveness.

## Project-owned native Knowledge Discovery case

The next self-iteration replaces caller-only initial landscape evidence with a
real native retrieval while preserving the authority boundary established by
the semantic cases. Its strict corpus is
`configs/cases/scitaste_discovery_knowledge_v1.yaml`; the initial scripted
proposal is
`configs/model_nodes/discovery_hypothesis_native_retrieval_self_iteration_v1.json`.
Admission computes a deterministic plan, the project then copies the corpus and
plan, and the normal controller-selected `SEARCH` must reproduce the same three
document identities and scores before semantic content can enter state.

The completed run is
`2026-09-07__scitaste-native__native-knowledge-discovery-v1__seed-07`. It reached
`PILOT` through six commands, ten controller decisions, and ten content-bound
native execution records. The three-entry semantic ledger used 1,162 scripted
tokens at zero cost; its hypothesis cited
`knowledge-native-retrieval-gap` and
`knowledge-controller-authority-boundary`, both present in the exact retrieval
artifact. The selected idea remained `idea-01-semantic-continuity`.

The Knowledge binding is
`65f3e2ebd9173a21dccc275de914d81a8916dc082834ad74ceacb5b798357744`,
the independently reproducible plan is
`8636766408b33ce0051101465b57748211160b404d0f087b30c8aec349bc3e23`,
and its state reference is
`3b8ebe52434f72389dc050ff27888335d8b170b3bcbd6c160a8c8c0aff04f0d9`.
The final state is
`state-30ebbccf8a191a035673b85277c2bcb7ad9730c8c73e47fc59d6c7b20e398615`,
the verified Discovery head is
`5b0b961693dcaaa22a207bd8245192a63443793c3bbf5498633458c9cced078e`,
and the native chain head is
`7b448bb5e35ebc488f5fb0985401cc8ff35fbbbc0108406d78b0f0eec425adff`.
This is evidence-acquisition, integration, and recovery evidence; it does not
show that lexical retrieval or scripted semantics improve research quality.

## External-call phase-protocol case

The earlier durable-result boundary still could not distinguish a crash before
the provider boundary from a crash after the call began. The selected
intervention adds three write-once receipts to each project-owned
AutoResearchClaw bootstrap or selected action: `prepared`, `call_started`, and
`result_published`. They bind the request, exact non-secret call specification,
external-attempt number, pre/post work trees, result file, result identity, and
terminal status. `resume_attempt` remains a separate bookkeeping counter.

The completed self-run is
`2026-09-07__scitaste-native__external-call-phase-protocol-v1__seed-07`, bound
to commit `b33b17dcd3faa5cdcea389c970963ca9d1d62127`. Its controlled interruptions
cover prepared continuation with no prior call, started/no-result refusal,
result-before-final-marker recovery, verified failure rollover, hard-crashed
running records, schema 1.1 success/failure compatibility, and schema 1.0
read-only behavior. The full suite completed 781 tests at 83% coverage; the
executor/project slice completed 98 tests. An independent review found no
high-risk duplicate-call path and its compatibility/durability findings were
closed before the commit. No external call was made for this iteration.

The project record is now revision 139 and its evidence is
`outputs/projects/scitaste-self-development/runs/2026-09-07__scitaste-native__external-call-phase-protocol-v1__seed-07/mainline/evidence.json`.
This remains compatibility-adapter integrity evidence. A started call without a
durable result is deliberately blocked until a provider can supply a trustworthy
idempotency or query key; the case makes no scientific-effectiveness claim.

## Native code proposal/admission case

The next mainline intervention closes the trust gap between semantic source
content and the existing CPU sandbox. The selected design separates a strict
proposal-only source contract, a non-expandable deterministic AST/import gate,
atomic project-owned evidence, and Bubblewrap execution. Rejected source keeps
its policy, proposal, verdict, root receipt, and proposed bytes, but never gains
an admitted path. Accepted source must be byte-identical to the proposal, and
runner definition `1.1` requires the emitted metric set to match the proposal
exactly.

The implementation is commit
`53920ee4e77acfb4e3594476d670073143ad2329`. Its final full-suite coverage run
completed 804 tests at 83% total coverage; the new native-code module reached
84%, and the focused executor/Full Workflow slice completed 46 tests. A separate
final Full Workflow acceptance created 18 native records, executed only
`native_execution/context/code/admitted/experiment.py`, measured three
replicates with `correct_pivot_delta` approximately 0.1, and produced Markdown,
TeX, PDF, SVG, and draw.io artifacts. No provider or other external call was
made.

The self-development project is now revision 143. Its run is
`2026-09-07__scitaste-native__native-code-admission-v1__seed-07`; detailed
hashes, alternatives, negative-path checks, and limitations are retained in
`outputs/projects/scitaste-self-development/runs/2026-09-07__scitaste-native__native-code-admission-v1__seed-07/mainline/evidence.json`.
This accepts the proposal/admission/execution binding, not provider-backed code
generation, broad dataset/GPU execution, or scientific effectiveness.

## Provider-backed native code generation case

The follow-on intervention connects that admission boundary to the durable
model-node runtime without granting the model execution authority. A trusted
pre-call record fixes the experiment, metrics, limits, policy, provider profile,
and budget. The model can return only source, rationale, and assumptions. An
accepted result is projected into a proposal; the independent AST gate and
Bubblewrap remain mandatory. Resume consumes committed ledger or recording
evidence and refuses to repeat a call that may have started without a complete
response. Full Workflow also revalidates the generation evidence before paper
publication.

The implementation is commit
`c9d2f758c2984e4c63e28fee7562e2500f2f5fcf`. The final full-suite run completed
817 tests at 83% total coverage; the new generation module reached 77%, and its
focused executor/Full Workflow slice completed 13 tests. The canonical offline
acceptance is project `scitaste-native-codegen-acceptance`. Its one verified
generation entry used 900 input and 1,250 output tokens, the generated, proposed,
and admitted source bytes were identical, and Bubblewrap measured three
replicates with `correct_pivot_delta` approximately 0.1. Its reviewed-draft
Markdown, TeX, PDF, SVG, and draw.io bundle is under
`outputs/projects/scitaste-native-codegen-acceptance/papers/provider-code-generation-reviewed-draft/`.

A separately authorized real GLM-5.3-Flash probe returned HTTP 200 with 1,260
input and 935 output tokens in 15.8 seconds. It was rejected before source
materialization because an exact public price could not be bound; independent
inspection also found invalid Python. No live source was admitted, executed, or
used to create a paper. This negative result and an earlier ambiguous started
call are retained rather than assigned zero cost or silently retried.

The self-development project is now revision 147. Its current run is
`2026-09-07__scitaste-native__provider-code-generation-v1__seed-07`; full hashes,
alternatives, external-call scope, and limitations are retained in
`outputs/projects/scitaste-self-development/runs/2026-09-07__scitaste-native__provider-code-generation-v1__seed-07/mainline/evidence.json`.
This accepts provider transport and the complete generation/admission/isolation
pipeline, not priced live acceptance, automatic repair, broad dataset/GPU
execution, model-quality gain, or scientific effectiveness.

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
