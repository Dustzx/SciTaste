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
replicates with `correct_pivot_delta` approximately 0.1. Its 77-word
Markdown/TeX/PDF/SVG/draw.io bundle was originally misclassified as a
`reviewed-draft`; it is a publication-pipeline integration fixture and is
retained at the historical path for audit under
`outputs/projects/scitaste-native-codegen-acceptance/papers/provider-code-generation-reviewed-draft/`.
The defect exposed by this self-use case led to an explicit manuscript-role
contract and a fail-closed research-draft completeness assessment.

A separately authorized real GLM-5.3-Flash probe returned HTTP 200 with 1,260
input and 935 output tokens in 15.8 seconds. It was rejected before source
materialization because an exact public price could not be bound; independent
inspection also found invalid Python. No live source was admitted, executed, or
used to create a paper. This negative result and an earlier ambiguous started
call are retained rather than assigned zero cost or silently retried.

The self-development project is now revision 150. Its current run is
`2026-09-07__scitaste-native__provider-code-generation-v1__seed-07`; full hashes,
alternatives, external-call scope, and limitations are retained in
`outputs/projects/scitaste-self-development/runs/2026-09-07__scitaste-native__provider-code-generation-v1__seed-07/mainline/evidence.json`.
This accepts provider transport and the complete generation/admission/isolation
pipeline, not priced live acceptance, automatic repair, broad dataset/GPU
execution, model-quality gain, or scientific effectiveness.

## Native dataset and GPU resource-profile case

The next intervention addresses the resource-authority gap without making host
paths or accelerators ambient sandbox capabilities. Four alternatives were
retained: trust direct host mounts, expose every detected GPU, defer the whole
problem to a future scheduler, or admit resources through a separate
content-bound profile. SciTaste selected the last option. Dataset files or
bounded directory trees must match a registered hash, are copied into the owning
run, receive only derived `/datasets/<id>` read-only mounts, and become direct
inputs to the native action record. GPU access remains off unless an exact
device request and positive worst-case GPU-hour budget pass before Bubblewrap.

Implementation commit `68b04b5135058a3c53d8bf8f15d36b68169e07f3`
completed 850 tests at 83% total coverage; the focused native/Full Workflow
slice completed 28 tests, Ruff passed, and the wheel contained the new executor
module without outputs, tests, or AutoResearchClaw. The canonical dataset-backed
Full Workflow is project `scitaste-offline-dataset-full`, run `dataset-seed-07`.
It copied the 524-byte registered dataset, produced 18 verified native records,
derived three replicate measurements with `correct_pivot_delta` approximately
0.1, and packaged a correctly labeled integration-fixture PDF.

The self-development run also performed a real local device acceptance. Inside
the no-network, read-only Bubblewrap namespace, `nvidia-smi` observed device 0 as
an NVIDIA GeForce RTX 3090 with 24,576 MiB; CUDA visibility was restricted to
that device and the record measured `0.0000707703` GPU-hours. This supersedes the
old Xid-79 operational blocker for this narrow device check. It is not yet a
CUDA kernel, local-Qwen inference, training, reproducibility, or effectiveness
result. A content-bound Python/package/model environment and a real CUDA workload
were therefore recorded as the next native-execution gate at that revision.

After registering the updated framework manuscript, the self-development project
reached revision 159. Its then-current run and exact execution evidence
are under
`outputs/projects/scitaste-self-development/runs/2026-09-08__scitaste-native__dataset-gpu-profiles-v1__seed-07/`.

## Main SciTaste manuscript correction

The framework paper is now a separate, substantive artifact rather than the
short Full Workflow fixture. Its title is restored from the authoritative
project specification: **SciTaste: Learning Scientific Taste for Autonomous
Research Decision Making**. The tracked Markdown and bibliography live in
`manuscripts/scitaste/`; the project-owned package contains Markdown, TeX, PDF,
bibliography, build evidence, and a self-hashed completeness assessment. The
working draft describes the complete framework and current engineering evidence
while explicitly withholding an effectiveness claim until the registered
matched-budget matrix and blinded expert review are complete.
The original registered bundle at
`outputs/projects/scitaste-self-development/papers/scitaste-framework-working-draft-v1/`
remains immutable. Revision 159 selects
`outputs/projects/scitaste-self-development/papers/scitaste-framework-working-draft-v2/`,
which contains 4,467 assessed words across 18 headings and a compiled 10-page
PDF. Its source is bound to commit
`12a4e31a09b5404daa1ab741a4cd11402881c4df`, reports the then-current 850-test
snapshot, and documents the leased Tool Intelligence executor plus dataset/GPU
resource-profile boundary. The corrected short
fixture is selected by `scitaste-native-codegen-acceptance` at revision 9, while
the earlier misclassified directory remains visible as historical evidence.

## Content-bound Qwen3-VL-2B CUDA case

The next intervention selected the user-requested local 2B checkpoint rather
than treating the older 4B study configuration as the current default. Native
execution profile schema `1.1` binds the complete Python base, package, and model
trees, derives read-only `/runtime/<id>` and `/models/<id>` mounts, selects only
the admitted interpreter/import/library paths, and rehashes every external tree
after the child process. The checkpoint is
`/media/good/dxhismyson/weights/Qwen3-VL-2B-Instruct`; its admitted tree identity
is `8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1`.

Five non-canonical attempts remain visible before the accepted v6 run. They
exposed, in order, a read-only temporary-directory/threading issue, an optional
`torchvision` processor dependency, an invalid multimodal message shape, GPU
cost overcounting, and wall-time truncation before postflight hashing. The
accepted run is
`2026-09-08__scitaste-native__qwen3vl2b-cuda-runtime-v6__seed-07`. It executed
two text contracts and one synthetic-image contract inside the no-network
Bubblewrap boundary; all three passed answer, non-empty response, CUDA, and
modality-path checks. Average generation latency was 0.579 seconds, model load
was 1.352 seconds on a warm local cache, peak allocated GPU memory was 4.271 GB,
child-process allocation was 7.536 seconds (`0.002093` GPU-hours), and complete
end-to-end time was 56.567 seconds. Postflight resource integrity passed and the
single native record chain verifies.

Implementation commit `859e86540b8ccdb8ea778eae8a552bb7239c4240`
completed 854 tests at 83% combined statement and branch coverage; Ruff and the
155-entry wheel check passed, and AutoResearchClaw remained fixed at
`12d3fd809fa9658e91a0328c3280a0e462c78386`. The updated paper bundle
`outputs/projects/scitaste-self-development/papers/scitaste-framework-working-draft-v3/`
contains 4,541 assessed words, Markdown, TeX, a compiled 10-page PDF,
bibliography, build evidence, and a self-hashed assessment under the original
SciTaste title. At project revision 180, v6 is the current run and working draft
v3 is the current paper. This accepts one local execution environment, not model
quality, portable reproduction, scientific effectiveness, or SciTaste
superiority.

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

# Shared compute-resource integration (2026-09-12)

The self-development case exposed a project-management gap: API endpoints, GPU
hosts, and local checkpoints were named inside individual experiment configs but
were not explicitly reusable infrastructure above projects. SciTaste now uses a
hash-indexed `configs/resources/` catalog and a sibling `outputs/resources/`
runtime. The `scitaste-self-development` binding names DeepSeek as primary API,
Zhipu as a separate robustness API, Bailian as blocked historical provenance,
the local 1×3090 for development, the remote 8×3090 for scale-out, and the
current Qwen3-VL-2B tree as a checkpoint resource.

The exercise also found a scientifically relevant mismatch: the current local
checkpoint hashes to `47f9c0e0...`, while the older GPU proposal freezes
`8e95e5f6...`. SciTaste records both identities and blocks silent substitution.
This iteration therefore produced both a reusable resource-management feature
and a concrete self-case demonstrating why infrastructure identity belongs in
the research evidence chain.

A follow-up explicit-integration check caught configuration drift before any
paid or GPU work: the first resource manifest named `ZHIPU_API_KEY`, while all
tested Zhipu backends and the machine-local credential use `ZAI_API_KEY`. The
catalog now uses the executable name. The same check promoted the remote 3090
alias into structured, non-secret SSH connection fields. This is another Taste
case candidate: readable resource topology is useful only when it is consistent
with the actual execution boundary.

## Real task acquisition changed the experiment plan (2026-09-12)

The next self-iteration exercised SciTaste's acquisition path instead of
reasoning only from benchmark metadata. The project owner approved the exact
download-only request, and SciTaste atomically acquired ten pinned MLR-Bench
research briefs. Their receipt covers 31,345 bytes; no content entered the
Knowledge or Taste libraries and no model, GPU, or experiment ran.

Inspection of the real bytes falsified an implicit planning assumption. The
files are broad workshop topic descriptions, not frozen empirical tasks: they
contain no task-specific data, starter code, environment, or objective score.
A new content-bound cohort inspector now allows stagewise and brief-only package
prepilots while blocking formal empirical and objective-progress use. The paper
plan consequently assigns the causal Taste claim to matched SciTaste Native
ablations and reserves best-native external systems for an explicitly
model-confounded ecological comparison. This is process and defect-discovery
evidence, not comparative effectiveness or a promotable Taste Case.

## Executable-benchmark qualification changed the GPU plan (2026-09-12)

The next recursive decision tested another tempting shortcut: treating an
8×RTX 3090 host as equivalent to any benchmark GPU requirement. SciTaste
retained all seven accepted MLRC-Bench tasks, the official code/data identities,
and their paper-reported runtime and memory limits before selecting a subset.
The resulting gate admitted four 16 GB tasks for metadata review and rejected
three 48 GB tasks because the available memory is 24 GB **per device**, not one
shared 192 GB address space.

Inspection also separated capacity from executability. Temporal Action
Localisation and Cross-Domain Meta Learning can next receive exact acquisition
requests; Machine Unlearning and Next Product Recommendation remain blocked by
Kaggle/AIcrowd terms, authentication, or manual evaluation. None has yet passed
asset hashing, environment reproduction, or a baseline run. The planned
Base/Full/mismatched-Taste contrast therefore remains a 180 GPU-hour ceiling
with no execution authority. This self-case records a project improvement and
a corrected experiment decision, not evidence that Scientific Taste works.

The self-hashed report is registered as run
`2026-09-12__scitaste-native__mlrc-executable-qualification-v1__seed-00` and
selected at project revision 301. Generation as Content revalidates the report
and presents the 7→4→2 task funnel, 180/192 GPU-hour bound, 48 GB single-device
gap, and next review action. A Chromium walkthrough at 1440, 768, 390, and
320 CSS pixels observed no document-level horizontal overflow, undersized
enabled target, or browser runtime error; this is interface engineering
evidence, not human-usability or scientific-effectiveness evidence.

## Exact MLRC asset review changed the acquisition boundary (2026-09-12)

The next recursive pass followed the executable candidate into its actual data
preparation code. That inspection found that the two retained tasks require 39
archives and 3,761,168,137 compressed bytes, not a generic “download the
benchmark” action. Temporal Action Localisation needs all nine video, sound,
and annotation archives because the pinned MLRC configuration selects the
multimodal path. Cross-Domain Meta Learning needs 30 OpenML image archives
whose official per-dataset licenses are heterogeneous.

SciTaste now has a strict dataset-package request that binds every provider
object identity, observed length, last-modified value or ETag, destination,
license evidence, task total, 16-GiB unpack ceiling, and 32-GiB free-space
floor. The metadata gate passes, but owner-approval readiness remains false:
the Perception Test and MLRC derivative-license descriptions conflict, and the
Meta-Album AWA license variant is unresolved. Content hashes and archive safety
are explicitly deferred until an approved first transfer. No dataset body,
provider call, GPU, or benchmark execution was used.

The report is registered as run
`2026-09-12__scitaste-native__mlrc-first-preflight-assets-v1__seed-00` and is
selected at project revision 303. Its canonical artifact is
`dataset_package_acquisition/REPORT.json`. This is acquisition-decision and
project-management evidence; it establishes neither legal clearance nor an
experimental result.

## Local API/GPU access binding became explicit (2026-09-12)

The shared catalog already separated stable API/GPU/checkpoint identity from
project artifacts, but “credential name exists in YAML” still did not answer
which resources this machine could resolve. The new access inspector consumes
only catalog-declared names from a mode-`0600`, Git-ignored file under
`outputs/resources/access/` or the process environment. It persists only a
bound/missing/credential-free partition and never prints or hashes a value.

On this machine, Zhipu GLM-5.3-Flash, historical Bailian Qwen3.8-Max, and the
remote 8×3090 SSH profile are locally bound; the local 1×3090 and verified
Qwen3-VL-2B tree need no credential. DeepSeek V4.1 Flash remains explicitly
missing a local credential. Bailian remains provider-blocked and the remote
host remains owner-reported even though their credentials are present. This
distinction prevents “a key exists” from being promoted into availability or
experiment authority. The inspection made no API request, SSH login, GPU
probe, model load, reservation, or experiment.

## Separating implementation readiness from data authority (2026-09-12)

The exact MLRC inventory exposed a second tempting shortcut: because the real
package is license-blocked, its downloader could have remained a prose-only
future task—or a generic downloader could have been treated as sufficient.
Instead, SciTaste used the blocked request to specify the post-approval control
path without changing the scientific or legal decision.

The resulting implementation binds approval to exact request/inventory/gate
hashes, streams rather than buffering multi-gigabyte objects, validates source
identity on the transfer connection, publishes atomically, and separates byte
receipt from no-extraction archive qualification. Synthetic ZIP tests exercise
success and adversarial rollback without contacting a source. The real
Perception Test and Meta-Album blockers remain unchanged, so no owner approval,
dataset byte, API call, SSH session, GPU use, or experiment occurred.

This is a self-iteration example of Scientific Taste as boundary selection: the
useful next action was to remove an implementation risk while preserving the
rights gate, not to force experimental progress or label software completeness
as empirical evidence.

## Turning license ambiguity into staged policy (2026-09-12)

The next recursive pass challenged the earlier assumption that the two license
issues needed a single definitive label before any transfer could be reviewed.
Official source inspection showed two different problems. Perception Test
already gives a conservative answer—CC-BY-4.0 for non-software material—so the
downstream MLRC Apache wording cannot remove upstream attribution. AWA has the
opposite shape: there is deliberately one license per image, so inventing one
Creative Commons variant would be false precision.

SciTaste converted that distinction into a content-bound policy rather than a
prose exception. Thirty-nine assets map one-to-one into nine obligation
profiles, the declared use is fixed to non-commercial academic research, and
raw/derived data redistribution remains prohibited. This closes acquisition
review for both tasks while leaving AWA ingestion blocked until acquired bytes
prove license-record presence and complete per-image coverage. The package
request binds the policy hash, so weakening a restriction changes the proposal
identity and invalidates any approval.

The resulting gate is now `ready_for_owner_approval=true`, but there is no owner
approval and every external authority remains false. No dataset byte, API call,
SSH session, GPU use, model load, or experiment occurred. This iteration is an
example of Scientific Taste as problem decomposition: resolve what evidence can
resolve, preserve irreducible uncertainty at the stage where it can actually be
tested, and avoid both needless blockage and unsupported clearance.

## Turning the paper claim into executable admission policy (2026-09-12)

The next self-iteration challenged another attractive shortcut: using one
external system table to support both “Taste causes improvement” and “SciTaste
performs well in the ecosystem.” The accepted systems cannot all preserve one
current model unchanged, while a best-native comparison deliberately gives them
different models. Treating that ecological contrast as causal would attribute
model effects to the framework.

SciTaste now represents the two questions as different claim contracts. The
native contract fixes Qwen3-VL-2B, the executor envelope, two MLRC task
candidates, six first-party conditions, and five contrasts including no-Taste
and mismatched-Taste controls. It expands to 12 one-seed feasibility
trajectories. The external contract fixes SciTaste/DeepSeek V4.1 Flash, Agent
Laboratory/o3-mini, and TinyScientist/GPT-4o-2024-08-06 independently. It
expands to six trajectories and carries `model_effects_confounded=true` all the
way into result assessment.

The exercise exposed three product defects and fixed them before a run. The
critic incorrectly demanded two external methods from native ablations and a
direct control from best-native comparisons; one-seed feasibility prepilots
were treated like underpowered formal studies; and an intentionally absent
remote checkpoint produced a redundant hash-mismatch finding. The critic is now
estimand- and study-scope-aware, while all genuine resource, task, adapter,
reviewer, and approval blockers remain.

Finally, result admission distinguishes scientific failure from missing
evidence. A real preregistered failed trajectory remains in the
intention-to-run population at its frozen task floor. A missing record, invalid
telemetry, unplanned contrast, decision-rule drift, or missing review blocks
completion. This self-case is evidence that explicit Taste can improve
experimental *problem formulation and boundary management*; it is not evidence
that the resulting scientific hypothesis is true. No download, provider call,
SSH session, GPU work, model load, or reviewer recruitment occurred.

Both no-run bundles are registered beneath the self-development project. The
external best-native bundle is retained as a non-selected ecological proposal;
the native Taste bundle is the selected title-critical proposal at project
revision 311. Registration copied the exact resource corpus, gate report, critic
report, and expanded cell plan. Both records remain `blocked`,
`execution_authorized=false`, and `no_execution_performed=true`.

## Making the Taste treatment real before spending compute (2026-09-12)

The selected native proposal exposed a recursive failure in SciTaste itself:
`native-base`, `native-taste`, and the other condition names described intended
contrasts, but most had no executable first-party mechanism. Running them would
have produced apparently comparative artifacts whose labels were stronger than
their implementation differences.

The next action was therefore implementation rather than experiment launch. A
closed six-profile matrix now controls utility, Knowledge retrieval, matched or
mismatched Taste retrieval, and four stage-specific Taste critics through the
same Discovery, Evidence, Writing, and Figure path. Evidence-integrity, writing,
visual, budget, code-admission, and sandbox gates stay enabled in every profile.
Offline runs of all six conditions verify state continuity and isolation, and
unknown conditions or missing libraries fail before project mutation.

This pass also narrowed the intended evidence claim. Full versus Base estimates
the whole explicit Taste bundle; Full versus mismatched Taste changes one corpus
relation. The component-only arms are sufficiency diagnostics, not marginal
ablations. The fixture still uses a deterministic controller and seed library,
so it cannot validate Qwen-backed behavior or scientific effectiveness. Recording
that limitation before updating the formal proposal is itself a Scientific Taste
decision: prevent treatment-label leakage now, then build and freeze the real
model-backed adapter before asking the owner to spend GPU or API resources.

## Separating required diagnostics from the title hypothesis (2026-09-12)

Binding the six executable conditions exposed a subtler experimental-design
error in the selected v7 proposal. It correctly required five analyses, but its
result gate also required all five confidence intervals to favor Full before the
title could be supported. That silently treated Knowledge-only, Taste-only, and
critics-only arms as three independent marginal-effect hypotheses even though
Full differs from each arm in several components.

SciTaste now distinguishes evidence completeness from confirmatory inference.
The schema-v1.4 v8 proposal still requires all 12 trajectories and all five
paired analyses. Full--Base and Full--mismatched-Taste are the two confirmation
obligations; the three component-only comparisons are mandatory mechanism
diagnostics. A missing diagnostic blocks the result, while a valid null or
adverse diagnostic remains reportable without being misrepresented as failure
of the bundle/context hypothesis. Conversely, either non-supporting confirmation
blocks title eligibility. Result assessments expose the two populations as
separate counts.

The v8 proposal binds every condition to executable commit `7b82eb5...` and the
exact condition-matrix hash, but retains `pending` system availability because
the model-backed candidate/action path and formal matched/placebo corpora have
not been attested. Task assets, remote checkpoint, independent reviewers, and
owner approval are also still open. This self-iteration changed the protocol
before compute spend, preserved all legacy v1.3 fingerprints, and performed no
download, API call, SSH session, model load, GPU work, or experiment.

## Converting autonomy and placebo quality into executable gates (2026-09-12)

The v8/v9 design exposed two remaining mismatches between SciTaste's claim and
its implementation. First, a model could select only scenario-authored actions,
so the system's claimed research autonomy exceeded its option-construction
ability. Second, the mismatched-Taste control was a domain filter over a generic
integration seed, not a task-specific negative control with measured information
parity. Running either design would have spent compute before the treatment was
scientifically identifiable.

SciTaste therefore added a bounded generation step before selection. The shared
Qwen backend may concretize every feasible controller-owned template and refine
only the query of an existing `SEARCH` action. Deterministic admission retains
action identity, type, costs, values, preconditions, tags, limits, domains, and
all other executable parameters. Missing templates, invented actions, protected
overrides, identity drift, response-hash drift, or invalid JSON fail the decision
without fallback. Generation and selection produce separate durable traces.

The placebo problem became a separate corpus-pair qualification tool. It invokes
the production retrieval policy and checks stage/role, eligible and retrieved
case counts, context budget, provenance tier, curation tier, and outcome
information. It also rejects held-out source/content reuse and any matched versus
placebo overlap in case IDs, source groups, content hashes, or provenance
locators. A native preflight can accept corpus parity only from a Git-bound
`qualified=true` report that repeats both corpus hashes.

The selected v10 proposal now binds six real native conditions to the bounded
generation/selection path and compiles to 12 Qwen3-VL-2B trajectories. It remains
blocked because no task-specific corpus pair or remote checkpoint execution has
been qualified, task assets and reviewers are missing, and the owner has not
approved execution. This is SciTaste self-iteration in the intended sense: use
scientific Taste to detect that an attractive experiment is not yet capable of
answering its stated question, repair the framework and protocol, and preserve
the unresolved empirical question instead of manufacturing positive evidence.
No dataset download, API call, SSH session, model load, GPU job, human
recruitment, or experiment occurred.

## Turning high-quality references into reviewable Taste experience (2026-09-12)

The v10 gate made corpus parity testable but left a more important conceptual
gap: a retrieval engine can locate text, yet it cannot establish that a source
represents a good scientific choice or that the source was faithfully abstracted
into a transferable decision principle. Letting a search score or model-written
summary directly enter the Taste Library would collapse the project's central
innovation back into ordinary RAG.

SciTaste now treats source quality, abstraction, and retrieval as separate
stages. Every source binds its exact bytes and independent quality evidence. A
human-authored or trace-bound model-assisted candidate states a closed decision
context, actions, principle, justification, and outcome boundary, but remains
untrusted. Two independent, conflict-cleared humans inspect its exact hash for
source fidelity, action grounding, generalization, scientific value, and outcome
handling. The author cannot self-review; a split needs one distinct adjudicator;
rejection cannot be hidden by silently dropping the source.

Only the compiler assigns retrieval trust. It constructs matched and
source-disjoint placebo corpora, invokes the production retriever, enforces all
seven parity dimensions and contamination checks, and atomically removes a pair
that fails qualification. Native-path preflight v3 proves this runtime exists at
commit `7d01bb7...`; it separately reports that the real task-specific corpus and
checkpoint execution do not exist.

The resulting v11 no-run proposal still contains 12 Qwen3-VL-2B trajectories and
remains unauthorized. This iteration therefore strengthens what Scientific
Taste means and removes a source of favorable-treatment bias without inventing
source records, human labels, or effectiveness evidence. No dataset download,
API call, SSH session, model load, GPU job, reviewer recruitment, or experiment
occurred.

## Separating available assets from an ICLR-grade experiment (2026-09-12)

The first resource registry made API and GPU access explicit, but it still
encoded two assumptions that could distort the paper: a checkpoint path was
implicitly local to the machine running the CLI, and the model already present
on a GPU host looked like the natural experimental choice. A fresh official-
source review also showed that the current DeepSeek callable identity differs
from the earlier V4.1 record.

SciTaste now has a v3 shared catalog. It preserves the historical DeepSeek
identity and adds the current V4 Flash identity rather than rewriting prior
proposals. A host-scoped checkpoint names the GPU resource on which its path was
observed, so local access inspection cannot report a remote path as missing.
Read-only discovery recorded 18 local and eight remote assets. Qwen3.5-4B was
independently full-tree hashed on both hosts and matched exactly; the remote 9B
tree was missing a weight shard, index, and tokenizer files and is blocked.

The asset catalog deliberately has no selection authority. The associated ICLR
strategy instead derives model choice from three title-critical hypotheses:
abstracted Taste versus raw RAG under the same sources and context budget,
matched versus mismatched Taste, and Full versus Native Base under one frozen
frontier backbone. DeepSeek V4 Flash and GLM-5.3-Flash are conformance candidates;
one can become primary before outcomes and the other a non-pooled robustness
slice. Existing Qwen checkpoints remain reproducibility/diagnostic assets unless
a scientific design independently selects them.

This iteration used one bounded read-only SSH inventory and local full-tree
hashing. It performed no API call, dataset download, model load, GPU job, model
transfer, remote mutation, human recruitment, or experiment.

## Compiling reviewer criticism into the exact evidence program (2026-09-12)

The internal ICLR-style review correctly identified four unresolved issues:
missing effectiveness evidence, absent accepted-system comparison, a title whose
“Improving” claim exceeds current results, and single-task generalization. The
first review DAG represented three of these as generic experiment-design nodes,
but those nodes still did not say which causal question, task population, or
endpoint would answer them. Launching from that representation would leave room
for convenient resources to redefine the experiment.

SciTaste now binds the concerns to its resource-independent evidence program.
The effectiveness concern requires H1, H2, and H3; the external-baseline concern
requires the separately reported E1 ecological comparison; generalization reuses
the complete five-study non-process program, including the D1 experiment-chain
diagnostic. The same study is never launched again merely because another
concern depends on it. The longitudinal self-development trace remains process
evidence and is excluded from population inference.

The title is retained as the intended claim, but submission remains blocked
until all title-critical evidence is complete and positive; otherwise an author
must explicitly narrow it. The compiler cannot silently rename the paper. Its
project package preserves exact mapping/program bytes, leaves the primary model,
formal sample size, repetitions, and compute unset, and performs no download,
API call, SSH session, model load, GPU job, human recruitment, or experiment.

## Joining the review design to real launch constraints (2026-09-12)

The five-study response resolved what evidence would answer the review, but it
did not resolve whether the necessary tasks, systems, models, reviewers, and
budgets were actually ready. The older campaign view also still carried an
early Qwen3-VL-2B/Tiny Scientist/MLR feasibility matrix. Letting that historical
matrix remain the operational view would allow an obsolete resource choice to
override the new scientific design.

SciTaste now compiles a separate activation dossier from the exact review
design, evidence-review package, shared compute catalog, and self-project
resource binding. It covers H1/H2/H3/E1/D1 exactly once, reports the 21-file,
8 MiB metadata request as the only owner-decision-ready step, and preserves the
older campaign as historical rather than launchable.

The initial diagnosis was concrete. Neither API candidate then had an admissible
stable identity observation, GLM pricing was unbound, and none
of the three accepted external systems has an experiment-ready adapter, no
formal sample has been powered, and no independent reviewers have been
recruited. Local Qwen checkpoints remain diagnostic assets rather than being
promoted because they are available. This iteration performs no download,
repository checkout, API call, SSH connection, model load, GPU job, reviewer
recruitment, or experiment and establishes no effectiveness evidence.

## Making rolling API models reproducible without pretending they are checkpoints (2026-09-12)

The first activation gate classified every rolling alias as lacking a stable
revision. That diagnosis was safe but operationally impossible: many capable
hosted models expose only a stable callable name, and an ICLR experiment cannot
wait for a checkpoint that the provider may never publish. Conversely, treating
the callable name as a frozen model would hide provider drift.

An official-source recheck showed that DeepSeek discloses the dated
`DeepSeek-V4-Flash-0731` revision behind `deepseek-v4-flash`, while Zhipu
discloses `glm-5.3-flash` but no immutable served revision. SciTaste now models
these as revision-backed and temporal-only identity strata, respectively. A
task-excluded sentinel must open and close each bounded window, recur after a
fixed call count, and retain exact request/response identity and usage. Any
missing or changed identity closes the window; data from different windows,
revisions, or providers cannot be pooled.

The revised project gate reports protocol coverage, candidates whose pricing is
complete enough to request a pilot, and candidates with a real authenticated
attestation as separate counts. DeepSeek's conservative peak tariff was updated
from the current official catalog; GLM pricing remains unresolved. No sentinel,
API call, dataset download, model load, GPU job, reviewer recruitment, or
experiment was performed.

## Preventing self-iteration from teaching itself an error (2026-09-12)

Using SciTaste's own development as a case exposed a contradiction in the core
Taste loop. External reference abstractions already remained untrusted until
source/quality evidence and independent review were complete, but the older
`TasteMemory.reflect` path immediately marked every project reflection as
retrieval eligible. An executed action and a plausible explanation could
therefore become policy before its outcome attribution or transfer scope was
checked. Repeated retrieval could amplify that mistake.

The continual-learning path now begins in quarantine. Reflection requires an
executed decision, preserves its concrete candidate identities, and freezes the
complete decision and actual-outcome hashes, author, outcome horizon, and
proposed principle. A separate admission binds the exact decision and outcome
files and requires two distinct conflict-cleared human reviews over decision
trace, outcome trace, alternatives, principle, and transfer scope. Split reviews
require a third adjudicator; unanimous reviews cannot be overridden. Tampered
bytes, author self-review, review before outcome observation, and a retry that
would overwrite an already admitted memory all fail closed.

This iteration establishes the safety and provenance mechanism only. Test
reviewers are fixtures, no real reflection has yet passed the new human gate,
and no continual-learning effectiveness claim is made. A future longitudinal
study must measure whether outcome-admitted memory improves later held-out
decisions without reducing calibration or diversity. No API call, dataset
download, SSH session, model load, GPU job, human recruitment, or experiment was
performed.

## Making reference-derived Taste an executable but untrusted treatment (2026-09-12)

The previous source-curation compiler could represent a model-assisted
abstraction, but its trace was only a file binding. Arbitrary JSON could satisfy
that label, and the package simultaneously declared that no model execution had
occurred. More subtly, the generic Pydantic configuration stripped terminal
whitespace from the source text, so a source file ending in a newline did not
have the same hash as the text visible to the node. That was sufficient for an
offline fixture but invalid for a same-source causal comparison.

SciTaste now has a dedicated `taste-abstraction` node and an exact-source input
builder. Source bytes, including terminal newlines, are preserved; relation arm
and held-out task content are excluded; runtime context has no unrelated state or
authority. Candidate creation accepts only a canonical live-mode entry whose
complete project ledger and response recording verify. Curation independently
rechecks request, policy, prompt, schema, provider/model, raw response, usage,
source projection, zero-tool boundary, and proposal equality before considering
the still-required human reviews. Scripted and replay data remain test fixtures.

Curation schema 1.1 separately records historical model invocation count and the
fact that current package processing performs no external action, with a
deterministic migration for valid 1.0 records. The repository itself also moved
from an accidental cross-project Python 3.11 environment to one local CPython
3.12.14 development/study environment shared with CI; historical runtime
receipts remain unchanged.

This iteration closes treatment-construction integrity, not the empirical claim.
The task-specific high-quality sources have not been acquired, no real
abstraction API call or human review was performed, and H1/H2 remain unmeasured.
The next resource-bearing step must name those sources, the conformance model,
call ceiling, review plan, and stopping rule before execution.

## Turning the first core Taste source into an exact decision (2026-09-12)

The source-candidate screen named AAAR, ARIES, and OpenReview, but naming a
dataset was not enough to spend resources safely. AAAR's dataset card declares
MIT while its records contain material derived from papers with their own
licenses. Treating the package license as permission for every embedded work
would make the central Scientific Taste treatment difficult to defend.

SciTaste therefore inspected only repository, dataset-tree, HTTP-header, and
arXiv OAI metadata. Of the 100 pinned AAAR experiment-design records, 44 papers
declare CC-BY-4.0 or CC0, eight use other Creative Commons variants, and 48 use
the arXiv nonexclusive-distribution license. Before reading any source body, all
nine eligible non-`cs.CL` records were retained and seven `cs.CL` records were
selected by a published SHA-256 key. The resulting sixteen CC-BY-4.0 records
span five primary-category strata and have a 3 MiB aggregate download ceiling.

The exact request is download-only. It excludes archives, PDFs, figures, images,
model outputs, linked assets, ingestion, API/GPU work, and human labeling. Its
offline inspector reports no readiness blocker; only exact owner approval is
missing. If approved, the bytes remain quarantined until a new content/schema
audit establishes identity, attribution, field boundaries, and source-group
isolation. A later proposal—not this request—must authorize a real model
abstraction and two-person source-fidelity review.

This is the first self-iteration step that moves H1/H2 from a generic resource
candidate toward real high-quality content without allowing available resources
to define the formal experiment. It creates no benchmark case and makes no
effectiveness claim. No source body was downloaded, no API or GPU was used, and
no human was recruited in this iteration.

## Separating downloaded bytes from permission to inspect content (2026-09-12)

The AAAR pipeline correctly said that download approval does not authorize
content access, but the repository had no executable object for that distinction.
A future operator would otherwise have needed to open the downloaded JSON with
an ad-hoc script in order to learn its schema—the exact unrecorded transition the
protocol was intended to prevent.

SciTaste now creates a separate content-audit authorization after acquisition.
It binds the approved request file, receipt file and semantic hash, ordered item
set, owner and time, auditor implementation hash, designated identity fields,
and structural ceilings without reading source bodies. The subsequent local
auditor needs an explicit content-read switch, rehashes every receipt byte,
closes the directory inventory, and
rejects duplicate keys, non-finite values, non-object roots, symlinks, extra
files, or structural limit violations.

Successful inspection produces field-shape, external-locator, and embedded-
paper-identity evidence only. It does not select fields for a prompt, decide
source quality, admit a Taste principle, call a model, or run an experiment.
Three focused synthetic checks exercised success, missing authority, changed
bindings, duplicate keys, and identity failure. No AAAR body, API, GPU, SSH
session, or human reviewer was used.

## Making the human Taste endpoint tamper-evident before recruitment (2026-09-12)

The H1/H2 plan previously stated that two condition-blinded humans would review
each comparison, but it did not make the timing and information boundary
executable. An operator could still have assembled condition-labelled files,
changed the X/Y map after seeing a review, replaced a disagreement, or shown
different output pairs to the two reviewers while claiming one comparison.

SciTaste now separates the public reviewer manifest, locked review set, private
blind key, and post-lock opening. The public assignment contains only exact
output bytes, presentation budgets, case/source-group identities, reviewer
pseudonyms, and a commitment to the private key. Every case must expose both H1
and H2 to two distinct reviewers. On opening, the inspector verifies that the
key predates the first review, opening follows the complete review-set lock, and
each case has one byte-identical matched-Taste output shared across three
distinct matched/raw/mismatched arms. A changed key or partial assignment cannot
produce an analysis-ready report.

Outcome disagreements are not adjudicated. `cannot-assess` and close-time
nonresponse remain missingness records attached to their original assignments,
so an inconvenient reviewer cannot be replaced after outcomes are visible. The
rubric makes scientific decision quality, evidence fit, claim calibration,
tradeoff awareness, and informative value diagnostic guides to one holistic
preference rather than five post-hoc weighted endpoints.

The download-to-abstraction path was frozen at the same time. Even after the
AAAR transaction is approved, content parsing, field projection, GLM-5.3-Flash
use, and human fidelity review each remain distinct gates. ARIES public object
metadata was inventoried without downloading object bodies; its first slice
still requires same-connection ETag, Last-Modified, Content-Length, and S3
version verification. This iteration ran no source-content download, API call,
model, GPU job, human recruitment, or experiment, and makes no H1/H2 effect
claim.

## Separating high-quality source admission from retrieval (2026-09-12)

The acquired-content auditor could establish byte integrity and observed schema,
while the Taste curation package assumed that its sources were already high
quality. That left the central research idea vulnerable to an informal step:
someone could choose convenient records, call them good precedents, and silently
drop failures after seeing later abstractions or outcomes.

SciTaste now compiles a frozen admission population before abstraction. Every
audited item remains in the ledger. An admitted source must independently pass
rights and attribution, scientific-source quality, and isolation from held-out
cases and SciTaste's own effectiveness evidence. The quality argument is bound to
the exact source bytes and evidence and must be accepted by two distinct human
reviewers who are independent of the curator, blind to each other, and blind to
downstream outcomes. Failed items remain explicit rejections; reaching the
predeclared minimum does not erase them.

This makes retrieval a downstream efficiency mechanism: it can search only among
already admitted abstractions and cannot define quality by relevance score. The
new compiler reads only the audit report and evidence files, not source bodies,
and authorizes neither projection nor model, human-recruitment, or experiment
work. Two focused synthetic checks covered mixed admission/rejection and blocked
post-audit cherry-picking; no external resource was used.

## Preventing resource-aware benchmark cherry-picking (2026-09-13)

The ICLR evidence program had frozen InnovatorBench and EXP-Bench scientific
roles before inspecting their task metadata, and the structured auditor could
prove byte and schema integrity. The next existing abstraction was nevertheless
an operator-written task-selection manifest. It could validate pins and stated
licenses, but it could not prove that the list came from the full audited
population or that inconvenient cases were not removed after checking available
models, GPUs, or expected performance.

SciTaste now inserts a complete-population projection before screening. A
no-read plan binds the approved request, receipt, structural audit, original
scope bytes, every required semantic field, its observed YAML path or CSV
column, explicit whole-source missingness declarations, the projector
implementation, and output ceilings. An observed mapping must occur somewhere
in the audited population; source-wide absence is declared rather than
fabricated, and per-record absence is retained as missingness rather than used
to drop a task. A separate exact approval and runtime switch are required before
reopening source bytes.

Materialization rehashes the full acquired inventory and emits one record per
InnovatorBench configuration or EXP-Bench CSV row. It cannot omit a record,
evaluate spreadsheet-like text, follow a URL, select a task, or consult formal
outcomes, model inventory, or compute inventory. The resulting population only
opens a later source-overlap, license, signal, environment, reproducibility, and
safety screen. Four focused synthetic checks exercised YAML and CSV population
preservation, inert formula-like values, missing-field rejection, and
implementation drift. They also preserve an explicitly missing required field
and expose its aggregate count. The real 21 downloaded files remained unopened;
no API, GPU, external network, model, human, or experiment action occurred.

## Turning a population into an auditable scientific screen (2026-09-13)

Complete projection prevented records from disappearing, but it did not yet
constrain how an operator would label the records or separate scientific
ineligibility from an inconvenient resource budget. The older task-selection
validator could confirm an already written short list, not prove that all
eligible records had first received the same treatment.

SciTaste now freezes source-specific rules before any projected values exist.
InnovatorBench uses five scientific eligibility rules and one later capacity
rule; EXP-Bench uses six scientific eligibility rules. The screening package
must contain exactly every projected-record by eligibility-rule pair, using the
rule's exact fields and assessment authority. Source-wide and record-level
missingness therefore becomes an explicit exclusion or unresolved decision,
never an invisible pass. Rights, reproducibility, overlap, and sandbox claims
that require more than projected metadata must bind immutable external evidence.

The compiler partitions and retains the entire population and opens only an
allocation-proposal gate. Formal outcomes, current models, GPUs, APIs, host
inventory, and expected performance cannot define eligibility; a later powered,
seeded allocation may use only eligible records and must retain unsampled cases.
The project interface recognizes this canonical ledger and shows its next gate
without implying that screening selected or executed tasks. Repository
rulebooks and synthetic compiler behavior were verified, but the real acquired
InnovatorBench and EXP-Bench files remain unopened and no actual population or
screening report exists. No network, provider, model, GPU, human, or experiment
resource was used.

## Closing screening-to-formal allocation without running a study (2026-09-13)

The self-iteration exposed another gap after complete-population screening:
the older shortlist validator could verify a list supplied by an operator, but
could not prove that the formal tasks were derived from the complete eligible
population using the pilot-powered independent-unit count. This matters for the
paper's recursive claim because a convenient task subset could make both the
system and its self-evaluation look stronger.

SciTaste now creates an identity-free allocation plan from the exact screening
chain and an independently replayed objective-H3 clustered-power chain. It
precommits the formal study, output, deterministic algorithm, random seed,
source-group field, and balance strata; blocks insufficient or cross-stratum
source groups; and requires every non-empty stratum to be represented. Only a
separate exact owner approval reveals the deterministic task selection. The
result retains selected, unsampled eligible, excluded, and blocked records and
still cannot launch an experiment.

The project interface recognizes both canonical stages and replaces earlier
cards for the same scope with the strongest evidence state, keeping the home
concise while exposing approval or prelaunch qualification as the next
interaction. Four focused allocation checks plus the affected interface tests
verified replay, source-group uniqueness, stratum coverage, missing-evidence
blocking, complete population retention, and no-execution boundaries. No real
project allocation was fabricated: the acquired benchmark metadata is still
unopened, so the self-development project correctly remains at the earlier
content-read approval gate. No provider, model, GPU, human, or experiment
resource was used.

## Binding exact H1/H2 generations to the later blind review (2026-09-13)

The self-iteration audit followed the newly replayable treatment manifest one
step downstream. It found that the human endpoint correctly froze reviewer
assignments, X/Y order, dual-review completeness, and blind-key timing, yet the
key's generation-trace hashes did not prove that the visible outputs came from
those v3 treatments. A valid statistical result could therefore be attached to
the wrong generation batch.

SciTaste now freezes one private treatment-generation ledger before review. It
contains a complete three-condition record for every held-out source group and
binds the exact suite, treatment manifest, request fingerprint, construction
receipt, seed, candidate order, provider/model identity, trace bytes, and output
bytes. Human-study schema 1.2 publishes only the upstream and ledger commitments;
the condition-bearing ledger opens with the blind key after all primary reviews
are locked. Formal analysis then replays the entire identity chain and rejects a
key whose condition is paired with another valid generation record.

The 120-source-group acceptance fixture also exposed repeated whole-study hashing
inside the per-review loop. Caching the immutable study identity reduces the
focused formal-scale check from roughly 43 seconds to roughly 9 seconds on the
development host. This iteration used no downloaded content, model/API/GPU
resource, human recruitment, or experiment and establishes no H1/H2 effect. The
next real gate remains explicit authorization for the already downloaded AAAR
pilot's request/receipt-bound local content audit.

## Removing manual construction from the H1/H2 blind package (2026-09-13)

After binding generated outputs to blind review, the self-iteration followed the
operational path an experimenter would use. No compiler connected
`benchmark run --record` to the public study, opaque reviewer files, private
blind key, and generation ledger. Manually creating those artifacts at formal
scale would reintroduce the same condition/output mismatch that ADR-095 closed.

SciTaste now timestamps newly recorded preference calls and provides an atomic
offline package compiler. It requires the exact seed/order H1/H2 request
population, emits condition-free opaque reviewer artifacts, and counterbalances
X/Y across the two already assigned reviewer pseudonyms. Condition mappings,
exact replay rows, and generation records stay under `private/`; only commitments
enter `public/study.json`. A 120-source-group fixture compiled 360 generation
records and 480 reviewer comparisons, then reloaded the persisted public/private
contracts and completed the source-group analysis path.

This change does not run a provider, recruit a reviewer, or claim that structural
blinding eliminates stylistic clues inside model prose; the interface protocol
and independent reviewers remain necessary. No quarantined content, API, GPU,
model, or human resource was used. The next real gate remains the separately
authorized AAAR content audit.

## Making the blind package usable by an actual reviewer (2026-09-13)

The next self-iteration followed the public blind package from the operator's
perspective into the reviewer experience. The package contained valid opaque X/Y
outputs but no executable surface that combined the committed decision context,
matched presentation, response constraints, assignment partition, and final
lock. A spreadsheet or hand-built form at this boundary would weaken the exact
identity chain just established by the experiment compiler.

SciTaste now compiles one self-contained offline HTML workspace for each of the
two preassigned reviewer pseudonyms. It verifies the exact treatment-bound suite
and output bytes, shows the case and side-by-side decisions in one bounded
viewport, retains drafts only in browser-local storage, and requires complete
responses, rationales, missingness reasons, and independence/blinding
attestations before export. A second compiler consumes the two session JSON
files and two exports, rejects missing, overlapping, foreign, or time-inconsistent
records, and freezes a schema-1.1 review set that binds all four files before the
private key can open. Formal treatment-bound studies reject legacy unbound
review sets.

The 120-source-group acceptance path exercised 240 assignments per reviewer,
360 generated decision artifacts, and 480 locked comparisons through the actual
session and collection code. A headless browser render confirmed that context,
X/Y outputs, progress, and response controls remain simultaneously visible
instead of forming one long vertical document. This is engineering evidence,
not a human-usability result or a scientific effect. No source corpus, model,
API, GPU, recruited reviewer, or experiment was used; qualified independent
review and the separately authorized AAAR content audit remain real gates.

## Replaying locked reviews before opening the H1/H2 key (2026-09-13)

Following the implemented reviewer workflow one boundary further exposed a
validity gap: the formal audit checked that the two session and two submission
files still matched their recorded hashes, but it did not reconstruct the
locked rows from those files. A manually assembled review set could therefore
claim valid collection bindings without being their actual product.

SciTaste now shares one in-memory collection compiler between review locking and
later blind opening. The new opening path completes the public readiness audit,
replays the exact four collection files against the committed suite and study,
and requires full equality with the locked set before reading either private
file. It then opens the committed key and generation ledger, replays the formal
treatment-to-output chain, and writes an analysis input only when every gate
passes. The analyzer performs the collection replay again for direct callers.

The focused formal-scale acceptance path used 120 source groups, 360 generation
records, and 480 locked comparisons. It completed opening and the preregistered
analysis entrance; a review set with one substituted rationale failed before a
deliberately nonexistent private-key path was examined. This is executable
integrity evidence, not a real scientific outcome. No acquired content, model,
API, GPU, recruited reviewer, or experiment was used. The next empirical gate
remains owner authorization to read the already downloaded AAAR pilot content.

## Freezing real external-method source bytes without executing them (2026-09-13)

The current evidence review identified Agent Laboratory and DeepScientist as the
two license-feasible archival method candidates, but both remained attached only
to remote commit metadata. The owner's standing policy now permits automatic
downloads below decimal 10 GB, so SciTaste created one exact transaction with
64-MiB and 512-MiB item ceilings, verified MIT and Apache-2.0 acquisition scope,
and the two already registered commit-addressed GitHub archive URLs.

The generic acquisition path had a 16-MiB per-file, text-only implementation
despite its transaction schema advertising a much larger aggregate ceiling.
SciTaste closed that operational gap by admitting gzip as an explicit media type
and streaming it directly into the atomic staging file while incrementally
enforcing size and SHA-256. Existing small-file fetcher semantics remain
available for deterministic tests; large default downloads no longer require
whole-object memory buffering.

The completed transaction acquired 1,327,928 Agent Laboratory bytes and
81,695,493 DeepScientist bytes, with exact hashes recorded in receipt
`7a119c3bec53de52c8cd928472f64090098c89e5c3f3bfe2ad408e14d09b7009`.
No archive was listed, extracted, parsed, installed, imported, or executed. This
turns remote availability into immutable local acquisition evidence only; a
separate source-read/extraction decision is still required before unchanged-core
adapter implementation can begin.

## Separating source inspection from extraction (2026-09-13)

The acquisition receipt made the two comparison-method archives immutable, but
it did not establish whether their tar members are structurally safe or whether
the archive root and repository license agree with the frozen source census.
SciTaste now compiles those identities into a second plan that can be reviewed
without opening the member stream. The real plan reverified both acquisition
artifacts and all 83,023,421 outer archive bytes and is ready for a separate
owner content-read decision.

The later qualifier has two independent gates: a plan-hash approval and an
explicit local-read switch. It does not extract; it rejects traversal, absolute
or non-normalized paths, links and special files, sparse payloads, duplicates,
unsafe modes, expansion bombs, unexpected roots, and license-file drift, then
content-addresses every accepted member and the complete tree. Synthetic safe
and adversarial archives passed and failed at the intended boundaries while
creating no extracted file. The real Agent Laboratory and DeepScientist member
streams remain unopened, so this milestone advances operational readiness but
does not yet establish unchanged-core adapter equivalence.

## Correcting download authority leakage in task-archive qualification (2026-09-13)

After the 3,761,168,137-byte MLRC task package completed acquisition, the
campaign still described both task candidates as not acquired. More seriously,
the existing archive qualifier could open all 39 ZIP central directories using
only the earlier download approval. That contradicted the project's explicit
rule that transfer authority ends when the receipt is written.

The campaign now binds a tracked acquisition boundary and reports exact task
bytes as available but unqualified. ZIP inspection requires a new self-hashed
approval over the exact request, download approval, receipt files and semantic
hashes, task IDs, asset count, aggregate bytes, and unpack ceiling. The qualifier
also requires an explicit local-read switch and records that content metadata
was read while extraction, ingestion, API, GPU, and execution authority remain
false. Synthetic safe, traversal, and symlink ZIPs exercised the boundary; no
real MLRC ZIP was opened. This removes a real provenance flaw without claiming
that the downloaded tasks are already executable.

## Behaviorally attesting the six native Taste conditions (2026-09-13)

The next campaign stage exposed a different risk: the formal proposal named six
first-party conditions and the static preflight verified their Git objects, but
neither artifact demonstrated that a complete workflow actually respected every
switch. Treating those names as executable evidence would defer intervention
leakage discovery until the GPU prepilot.

SciTaste now runs one bounded implementation attestation before real resources.
Each of the six conditions completed the same 18-decision, four-stage offline
fixture. The report observed Knowledge retrieval only in the declared three
conditions, Taste retrieval only in the declared matched or mismatched arms,
disjoint matched/placebo precedents, critic-specific score evidence, zero final
blocking findings, and invariant integrity gates. Full and its placebo preserved
the registered single-factor difference.

This is a concrete self-iteration example of Scientific Taste as experimental
discipline: it converted a plausible configuration claim into an executable
falsification check before spending scarce resources. The result closes only
first-party implementation qualification. Real source abstraction and
independent corpus review, MLRC archive/task qualification, checkpoint execution,
and empirical effects remain open; the attestation used no acquired content,
model, API, GPU, network, or real experiment.

## Turning Tool Intelligence routes into project interventions (2026-09-14)

The project home could show four independently routed next gates and could ask a
model to revise the overall evidence program, but those two capabilities were
only visually adjacent. A user selecting one route supplied natural-language
context, while the stored model request did not bind the exact gate or route
identity. The model could therefore return a valid amendment aimed at another
eligible gate.

SciTaste now includes every eligible route in the bounded model catalog. Clicking
one seeds editable feedback and binds the request to its stage and route hash.
The model may rewrite the plan and narrative, but it must keep that target and
must respect the route selected by Tool Intelligence: direct work receives no
ritual precheck, a targeted check cannot silently expand, and an owner boundary
cannot become execution authority. Stale route identities and stage-drifting
drafts are rejected before storage. Exact-predecessor edits retain the same
focus.

The first browser pass also exposed a backward-compatibility defect: adding the
optional focus fields changed the canonical hash of older proposal records and
made project-memory restoration return HTTP 400. Canonicalization now omits only
the absent new fields, so old records validate without migration or rewriting.
The repeated real-project browser probe completed with four route controls, no
HTTP failures, no runtime errors, no horizontal page overflow across 320, 390,
768, and 1440 pixel viewports, and a bounded bottom composer. This is engineering
acceptance of the control surface, not a human-usability or scientific-effect
result; it used no provider, API, GPU, download, or experiment.

## Closing cached generation and intervention readability (2026-09-14)

The self-project revealed that the warm-cache implementation reused provider
output but opened it as a standalone generated page. It saved a call, yet the
next feedback could not name that cached page as its conversation predecessor.
The fixed label therefore behaved like a static cache instead of the first step
of a flexible Generation as Content exchange.

SciTaste now promotes an exact fresh cached generation into a new project topic
after checking its project, catalog, intent, generation, document hash, and
expiry. Promotion makes no provider call; later feedback follows the ordinary
model-edit path. The same project home now presents an abstract two-plane loop:
model synthesis and feedback editing remain visibly parallel to SciTaste's
evidence/resource/execution controller, while explicit publication is the only
bridge that alters effective planning. Deep experiment and metadata records move
to the evidence vault rather than lengthening the default path.

This iteration also used the user's objection to repeated preflight as a Tool
Intelligence design signal. The router now keeps a sufficient targeted check
unless full preflight contributes material incremental net gain, and rejects a
gray-zone model advisory that adds a negative-value check. These are engineering
policy changes, not evidence that either the UI or Tool Intelligence improves
scientific outcomes.

One post-change browser probe against the real revision-461 self project found
both parallel planes, the user bridge, all four route cards, two route-economics
comparators per card, and project intervention controls. It also observed no
runtime or HTTP failures, no horizontal page overflow at 320, 390, 768, and 1440
pixels, and a bounded bottom composer. The generated workspace fit a 1,009-pixel
document at desktop width in this probe. The check used deterministic fallback,
no provider call, and no GPU; it verifies receiver behavior and layout only.

## Editing generated project pages and eliminating review overhead (2026-09-14)

The next live self-use pass found a deeper product gap. Free-form follow-up
generation received the prior cited prose but not the prior generated layout, so
the model could rewrite content without deliberately editing the page it had
already made. The interface also did not state what the successor retained or
changed. This fell short of Generation as Content: feedback had continuity at the
conversation level, but not at the generated artifact level.

The planner now receives a bounded representation of the exact predecessor's
safe `SurfacePlan` beside its cited brief. It may revise component inclusion,
order, grouping, emphasis, focus, and authored content. SciTaste derives the
resulting delta itself and renders it before the successor canvas. Fixed-label
warm-cache entries use the same mechanism after promotion into a project
conversation, preserving fast entry without reducing the product to a static
dashboard.

A real GLM-5.3-Flash conversation on self-project revision 475 first authored a
ten-component progress canvas. Feedback requesting the next gate produced
`turn-0002` in the same workspace: six components were retained, four removed,
and both layout and cited authored content changed. That edit reported 12,110
input tokens, 2,104 output tokens, USD 0.0011488407763553773, and 13,447 ms. The
browser showed the compact delta and edited canvas above the persistent bottom
composer.

The self-use pass also tested whether Tool Intelligence could replace ritual
prechecking with bounded judgment rather than introduce a second review model.
The same model call that drafted a route-bound program clarification returned a
`direct_path` advisory over the exact server-issued verification input. The
controller re-ran deterministic policy, admitted the advice only for the
eligible route, and preserved the existing scientific blocker. Proposal
`program-revision-ce3c369b31b43ad5c816` remains pending: no user decision,
publication, Core mutation, external action, or execution occurred. The call
reported 5,583 input tokens, 545 output tokens, USD 0.00044189133384461095, and
6,257 ms.

An earlier response in this pass failed schema admission after the provider had
already charged for generation. SciTaste previously discarded that cost evidence
and allowed the exact request to be retried. It now persists the known response
hash and telemetry and negative-caches only that exact cost-bearing rejection;
transport failures with no response remain retryable. These observations verify
artifact continuity, policy enforcement, and accounting behavior only. They do
not establish interaction-quality, research-quality, or efficiency superiority.

## Generating and editing the next Scientific Taste gate (2026-09-14)

The next self-use pass exercised Generation as Content on acquired research
evidence rather than on a synthetic project summary. SciTaste compiled the
approved ARIES slice into 196 natural manual-review candidates from 42 held-out
paper groups. It excluded 3,892 synthetic-review rows and kept observed revisions
and upstream alignments explicitly non-gold. The resulting population currently
covers only one of three target domains, has 103 candidates without an aligned
edit, and still lacks independent quality labels, decision-family stratification,
and privacy approval. It is therefore a curation input, not a benchmark or an
effect result.

The first live model generation exposed an information-boundary defect: the
bounded evidence digest preserved the project sections but removed scalar facts
inside repeated progress rows. The model could see that a Taste population
existed without seeing its exact counts or blockers. The digest now uses an
explicit safe-field projection for the current focus, evidence program,
lifecycle, candidate population, next gates, and project resource bindings. It
still excludes paths, locators, hashes, credentials, actions, and deep arbitrary
containers.

With that correction, GLM-5.3-Flash generated a compact decision canvas that
reported the exact 196 candidates, 42 groups, one-of-three domain coverage,
149/47 upstream alignment agreement/disagreement, 103 unaligned candidates, and
the remaining admission blockers. A feedback turn edited the same artifact so
quality labeling and privacy became parallel paths, joined at decision-family
stratification, with domain expansion preceding benchmark admission. The two
turns consumed 26,781 input and 4,514 output tokens at USD
0.002511946197864433. This is evidence of model-authored artifact continuity and
feedback-directed editing, not evidence that the proposed scientific plan is
correct.

Publishing the interaction as a program change surfaced a second contract gap.
The model interpreted within-stage guidance as permission to reorder the entire
remaining stage sequence. SciTaste retained each charged schema rejection in the
negative cache, exposed a content-free failure category, and narrowed the model
task to semantic fields; the receiver now injects invariant flags and applies
the exact change-kind contract. The subsequent proposal
`program-revision-2d78b1001879330710b8` targets
`qualify-scientific-taste-source-pilot` and requires two-of-three domains, dual
independent quality review, privacy review, and a decision-family result. It
remains pending and unapplied: the model generated and revised the planning
content, while the user boundary preserved Core authority.

This pass also demonstrates the intended relation between Generation as Content
and SciTaste Core. The two are parallel project surfaces: one flexibly generates
and edits explanations, canvases, and proposals; the other owns evidence,
resources, execution, and durable state. Their interaction is an explicit,
reviewable publication event. Tool Intelligence chose a direct path for the
local population compiler, so no standalone preflight was added; identity,
archive-safety, bounded-read, and atomic-publication checks remained intrinsic
because failure there would corrupt provenance or project state.
