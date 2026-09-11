# Roadmap

Status values: `done`, `in progress`, `next`, `planned`, `deferred`.

| Milestone | Status | Exit gate |
|---|---|---|
| Phase 0 — substrate control | done | official AutoResearchClaw release pinned; adapter and baseline dry-run work |
| Phase 1 — state/controller skeleton | done | nonlinear mock loop includes `PROBE` and `PIVOT`; unit/integration tests pass |
| Phase 2 — intrinsic calibration | done | reproducible Idea, Experiment, Evidence, Writing, and Review taste profiles |
| Phase 3 — taste library | done | knowledge/taste stores are independent; rights-scoped provenance, quarantine, and stage retrieval tested |
| Phase 4 — discovery loop | done | adaptive Hypothesis–Probe–Reformulate scenarios pass both integration cases |
| Phase 5 — evidence loop | done | claims update from evidence; gaps and contradictory-evidence pivots work |
| Phase 6 — communication loop | done | narrative/contracts/review obligations route to evidence and back to revision |
| Phase 7 — figures | done | figure contract produces editable, reviewed SVG/draw.io output |
| Phase 7.5 — real substrate gate | done | pinned upstream Stage 1–3 run yields validated artifacts and a SciTaste transition |
| Phase 8 — SciTasteBench | done | intrinsic/augmented evaluation is controlled and reproducible |
| Phase 9 — matched-budget study | in progress | protocol/planner/runner/integrity status done; 48 exact-protocol runs and external expert review pending |

The independent product path now also has a project-owned paper-review registry
and an eight-gate lifecycle projection from native idea through independent
pre-submission review. This closes the software control path, but the
`scitaste-self-development` project remains scientifically incomplete until one
paper source run binds verified native evidence and independent review artifacts
are collected.

The local Generation-as-Content receiver now presents this lifecycle through a
portfolio index, one stable home per project, project-owned research
conversations, and one immutable generated page per user question. Conversation
context is explicit and bounded; model/API credentials remain deployment
configuration and never belong to a project page.

Phase 9 now has a typed prelaunch resource gate and separate DeepSeek, Zhipu,
and 8 × RTX 3090/Qwen3-VL-2B proposals. All three deliberately remain blocked:
the accepted Benchmark subset, external/control adapters, independent reviewers,
and explicit hash-bound launch approval are not yet complete. Zhipu's official
model identity is now verified, while exact dated pricing and an authenticated
served revision remain blocked; remote GPU inventory is still a lane-specific
blocker. Exact no-run proposal bundles can now be registered under the owning
project and inspected on its Generation-as-Content home, but registration and
selection confer no execution authority.

The post-execution software path is also implemented: existing API or GPU cell
outputs can be admitted as project-owned immutable result bundles and shown
separately from proposals on the project home. Admission rechecks plan/resource
identity, budgets, artifacts, evidence class, blind reviews, and preregistered
contrasts. No formal SciTaste result has been produced or registered yet, and a
paper becomes top-venue evidence-complete only after a new paper revision binds
the exact selected result and an independent review closes against that paper.
That paper transition is now implemented as an explicit build option and a
self-hashed sidecar covering all paper artifacts. It remains unexercised by the
SciTaste self-development paper because no approved formal result exists yet;
the current draft and its prior reviews therefore stay correctly unbound.

The homepage now compresses repeated proposal diagnostics into seven stable
decision gates while retaining the exact codes underneath. For the current
DeepSeek prepilot, the API identity, dated pricing, and declared runtime budget
are ready, while task qualification, comparator adapters, analysis/replication,
integrity, blinded review, and owner approval remain open. This distinction
prevents a large repeated blocker count from obscuring the actual launch
decisions.

The research-landscape v6 fourth screen now separates 45 relevance-gated works
into 16 method, 6 hybrid, and 23 benchmark/evaluation contributions without
interpreting their counts as field prevalence. The newly recovered ICLR 2026
evidence is evaluation-heavy: InnovatorBench, InnoGym, ScienceBoard,
AutoExperiment, NewtonBench, MoSciBench, and MedAgentGym supply task or
environment evidence, while SciNav, MetaMuse, and reinforcement-learned MLE
agents supply method precedents. A benchmark's bundled baseline is not promoted
to a method comparator. Accepted MLR-Agent, AI-Researcher, Agent Laboratory,
and TinyScientist remain headline adapter candidates, while preprint-only AI
Scientist-v2 and AutoResearchClaw remain sensitivity candidates. The census is
still in progress because this screen recovered material additions; a focused
citation/resource screen and exact adapters/licenses remain open.

## Phase 2/3 progress

- Done: immutable fixed-candidate fixtures for Idea, Experiment, Evidence,
  Writing, and Review decisions.
- Done: provider-neutral backend contract, deterministic scripted backend,
  exact record/replay, retry policy, token usage, and an opt-in compatible API
  backend with no network calls in tests.
- Done: accuracy, Brier score, expected calibration error, confidence, and
  per-task reports.
- Done: separate typed Knowledge/Taste JSONL stores, provenance schema,
  stage/role-aware retrieval, and decision-log precedent IDs.
- Done: a five-case `qwen3.7-plus` live smoke profile is archived as an aggregate
  manifest with hashes; secrets, exact recordings, and raw responses remain local.
- Done: local JSON/JSONL ingestion, explicit Knowledge/Taste routing, content
  hashing, per-library deduplication, idempotency, and reject-by-default license
  policy. No external source content is committed or downloaded automatically.
- Done: rights-scope auditing distinguishes metadata, public comments, derived
  annotations, and article text; article text needs per-record permission.
- Done: deterministic ARIES/CASIMIR projections and a real-source acceptance run
  imported 29 metadata/annotation Knowledge Documents and quarantined 25 observed
  revision cases. Direct OpenReview collection remains user-managed because its
  API challenged the unattended request.
- Ongoing data operation: expand the local corpus and human-verify selected cases.
  This changes library population, not the Phase 3 code or acceptance gate.

## Phase 4 completion

- Structured, source-linked literature landscape construction.
- Separate Research Intuition and falsifiable Working Hypothesis formation.
- Cheap diagnostic probe plans with reproducibility, stability, effect size,
  boundary, alternative-explanation, and disposition records.
- Stable contradictions persist as observations and can trigger first-class
  `REFORMULATE_HYPOTHESIS` decisions.
- Problem formation, style-normalized divergent ideas, controller-ranked idea
  selection, and multi-slot portfolios.
- The required `hypothesize`, `probe`, `reformulate`, `ideate`, and
  `portfolio select` CLI operations are implemented rather than reserved. They
  compose through immutable state snapshots, validate scenario identity and
  stage preconditions, retain controller decisions/executor outcomes, and bind
  every new-step decision log by SHA-256. The monolithic `discover` command is a
  convenience orchestration path, not a separate discovery strategy.
- The same operations now have a ProjectRuntime-owned advancement API and CLI.
  One registered run owns immutable command steps, a self-hashed lineage head,
  optimistic revision reservations, current-run navigation, independent
  verification, and interruption recovery that never repeats a fully persisted
  pending step. Standalone output directories remain useful for fixtures, not
  the preferred durable project layout.
- The first operation may bind a strict local Knowledge corpus. Admission plans
  retrieval before bounded semantic generation; native execution must reproduce
  the planned IDs and scores, successor commands retain one binding, and
  independent verification replays corpus, plan, decision, state, and execution
  evidence without trusting an external source path.
- Stable contradictory pilot evidence can produce a new problem and idea.
- Integration acceptance: weak intuition takes two probes and reformulates;
  strong prior evidence takes one sanity probe. Both finish at `PILOT` through
  the same loop implementation.

## Phase 5 completion

- Typed claim/evidence graphs and five claim states: supported, partially
  supported, unsupported, contradicted, and overclaimed.
- Evidence-gap planning ranks information value and always specifies a
  falsification test, counterfactual, matched baseline, and negative control.
- Interpretation keeps raw result, observation, interpretation, and claim update
  distinct; leakage, confounders, artifacts, mismatch, or instability prevent
  direct claim promotion.
- Unsupported claims route to evidence collection, uncertain results to
  reproduction, supported claims forward, and stable contradictions to pivot.
- Phase 4 `PILOT` state can resume into `PILOT → ANALYZE → EVIDENCE`; a stable
  contradiction retains its evidence and creates a traceable problem/new idea.
- Resource checks use cumulative project usage, and `DROP` is terminal.

## Phase 6 completion

- Evidence-linked Narrative Spine must pass a taste review before drafting.
- Section and paragraph contracts reference canonical claim/evidence IDs.
- Rhetorical-role retrieval supplies traceable writing precedents.
- Nine distinct critics cover substance, narrative, claim/evidence, redundancy,
  style, venue style, terminology, citation, and global coherence.
- Hierarchical Writing Taste now spans twelve integrity, argument, narrative,
  evidence, reader, style, venue, and coherence dimensions. A deterministic
  assessor and proposal-only semantic node preserve material limitations and
  treat anti-defensive writing as one subordinate dimension rather than the
  complete writing objective.
- Venue Writing Taste profiles are now distinct from template compliance. The
  ICLR 2027 bundle co-locates a hash-bound submission contract, provenance
  record, five official reviewer-facing constructs, fifteen corpus-derived
  candidate principles, and six paper-archetype overlays. Paper builds and the
  semantic reviewer consume the exact profile context, while candidate guidance
  remains on hold and cannot affect submission eligibility.
- Reviewer feedback becomes typed concerns and research obligations with
  stage-specific actions rather than an unconditional rewrite.
- Acceptance trajectory: a missing-baseline concern selects `ADD_BASELINE`, the
  existing Evidence Loop records matched-baseline evidence, the obligation
  closes, and the paper returns to `COMMUNICATION` for revision 2.
- Venue-native publication packaging binds an official template archive and
  admitted assets by hash, requires a substantive long-form manuscript, renders
  anonymous TeX, and fails closed on compilation, page-limit, citation-closure,
  required-statement, identity, or internal-marker violations. The SciTaste
  framework manuscript exercises the ICLR 2027 contract with an 8-page main-text
  boundary; this is deterministic submission compliance, not paper acceptance.

## Phase 7 completion

- Figure-need assessment precedes rendering and records why prose alone is
  insufficient.
- A typed Figure Contract binds purpose, target claims, reader takeaway,
  entities, relations, forbidden emphasis, panels, and retrieved references.
- Deterministic semantic reconstruction exports stable object IDs to editable
  SVG and uncompressed draw.io XML.
- Ten visual critics separate scientific communication from aesthetics and run
  both before and after patching.
- Object-level patches preserve field-level old/new values and rationales in
  `ResearchState`.
- Acceptance trajectory detects forbidden executor emphasis in two critic
  dimensions, deduplicates it to one patch, and clears all final findings.
- A five-case Bailian `qwen3.8-max` visual-taste smoke run passed the fixed
  candidate protocol; raw responses remain local and ignored.

## Phase 7.5 completion

- AutoResearchClaw remains an unmodified `v0.5.0` submodule.
- Supported action mappings now enforce upstream prerequisites and output
  contracts instead of trusting subprocess exit codes.
- Artifact manifests preserve path, type, size, file count, and SHA-256.
- Stable SciTaste session identity spans upstream run-ID changes in one run
  directory; both IDs remain visible.
- Failed execution does not advance canonical state; successful execution logs
  the decision, result, transition, artifacts, and measured wall time.
- A Bailian `qwen3.8-max` live slice completed Stages 1–3 and imported all three
  Stage 3 artifacts. API cost remains unavailable because upstream produced no
  cost log.
- SciTaste's own adapter decision is preserved as a dogfooding case, explicitly
  excluded from Phase 8 headline effectiveness evaluation.

## Phase 8 completion

- A versioned independent smoke suite covers Idea, Experiment, Evidence, Writing,
  Review, and Visual fixed-pair decisions.
- Base, Knowledge RAG, Taste Library, Taste Critics, and Full SciTaste conditions
  construct isolated, fingerprinted requests through one backend contract.
- Reports include pairwise accuracy, expert agreement, confidence calibration,
  wrong-level decisions, per-task metrics, three transfer slices, style
  invariance, paraphrase consistency, and paired changes from Base.
- Self-referential cases are schema-blocked from headline metrics; the SciTaste
  self-iteration case remains dogfooding only.
- Ranking correlation is unavailable under the pair-selection response contract,
  and Phase 9 system outcomes are explicitly deferred rather than approximated.
- Base/Full paired outcomes now expose recoveries, regressions, and unresolved
  shared failures; same-suite, same-seed cross-model reports identify only
  model-limit candidates and remain diagnostic rather than causal evidence.
- Deterministic offline acceptance spans all conditions and stores content hashes;
  scripted scores verify the evaluator, not SciTaste effectiveness.

## Phase 9 progress

- A project-owned AutoResearch evaluation landscape now visualizes accepted
  work by lifecycle coverage, evidence signal, resource scale, estimand, and
  comparison readiness. It confirms that the literature synthesis is adequate
  for choosing the next planning work, while the experiment protocol remains on
  hold until exact held-out tasks, external adapters, pilot-based power, expert
  calibration, and the resource manifest are resolved.

- Architecture direction is now explicit: `scitaste-native` is the independent
  product default, while AutoResearchClaw is an optional baseline/compatibility
  adapter. The dependency-free native Phase 4--7 path is wired through one
  shared executor and failed execution cannot advance state.
- Project-owned native action evidence now chains every selected action to its
  pre-state, inputs, artifacts, result and predecessor. Full Workflow performs
  real local Knowledge Library retrieval and revalidates action/result bindings
  on resume.
- Provider-facing compatibility attempts now have a durable three-phase call
  protocol. Write-once prepared/start/result receipts bind the exact request,
  non-secret call specification, pre/post work trees, result, and distinct
  external-attempt counter. Prepared work can resume safely, a started call with
  no result cannot repeat, and a verified failed result is the only authority for
  incrementing the external attempt.
- Explicit Discovery advancement now shares the project ownership boundary:
  callers supply project/run identity and current revision while the workflow
  derives state and destination. This closes fragmented command output and
  concurrent-advance ambiguity for registered deterministic scenarios. Its
  first bounded semantic handler now synthesizes a typed hypothesis from the
  registered landscape while remaining project-ledgered, budgeted,
  non-executable, fail-closed, and reusable across command recovery. A second
  handler now reformulates from a registered parent contradiction, appends an
  ordered semantic history, and enforces cumulative scenario cost without
  changing controller authority. A third bounded handler now proposes a problem
  and three to eight evidence-bound divergent idea seeds while leaving all
  actions and portfolio selection to the controller. A project-owned native
  Knowledge context now supplies reproducible retrieved findings to the first
  semantic node while `SEARCH` remains controller-selected and independently
  verifiable. Open-web retrieval and comparative scientific-quality evidence
  remain pending.
- A registered CPU experiment now runs through a shell-free Bubblewrap launcher
  with no network and a read-only filesystem, resource ceilings, exact source/stdout/
  stderr retention, strict replicate records, and independently derived metrics.
  Evidence consumes those measured values instead of the configured result
  fixture. This is executable integration evidence, not scientific effectiveness.
- Native execution profiles now bind bounded dataset files/trees into immutable
  run-owned copies and mount them read-only at derived `/datasets/<id>` paths.
  GPU access remains default-deny; an explicit device identity and GPU-hour
  budget can admit exact NVIDIA nodes. The dataset-backed Full Workflow and an
  isolated local RTX 3090 inventory measurement pass. Profile schema `1.1` now
  additionally binds external Python base/package/model trees, mounts them
  read-only, selects the admitted interpreter, and rehashes them after execution.
  A three-case Qwen3-VL-2B text/vision CUDA acceptance passed on that 3090 with
  separate child-process GPU time; portable environment construction and broader
  model-quality evaluation remain pending.
- The default Full Workflow now passes that CPU source through a typed
  proposal/static-admission boundary. Exact proposal, policy, verdict, proposed
  source, and byte-identical admitted source are project-owned and hash-bound;
  rejected source remains auditable but cannot reach the runner. Static
  admission is defense in depth and does not replace Bubblewrap.
- Full Workflow can now obtain that source from a bounded provider-backed
  `native-code-proposal` node. The run checkpoints the exact trusted brief before
  access, records request/raw response/usage in the existing hash-chained model
  ledger, atomically projects only accepted output into a proposal, and still
  requires the independent AST gate plus Bubblewrap. Scripted end-to-end
  acceptance and no-second-call recovery are complete. A real GLM-5.3-Flash
  response was retained but rejected before materialization for unavailable
  price evidence; its candidate also failed syntax inspection, so no online code
  was executed.
- A deterministic static rejection can now trigger exactly one separately
  configured `native-code-repair` proposal. The repair input binds the original
  generation evidence and violation set; experiment identity, metrics, policy,
  paths, budgets, and execution authority remain controller-owned. The original
  negative evidence stays immutable, the replacement faces identical readmission,
  accepted initial source causes zero repair calls, and a second rejection is
  terminal. Offline end-to-end execution and no-second-call recovery pass;
  runtime-failure repair and priced live repair quality remain later gates.
- The measured result is now projected from canonical state and the original
  native execution/metrics records into Communication claim/evidence contracts.
  The audit draft retains trace markers, while the project paper is built from a
  clean reader-facing projection containing the measured mean, replicates,
  dispersion, and explicit synthetic-offline limitation.
- Native open-ended capability parity remains pending for open-web retrieval,
  runtime-failure diagnosis/repair, portable environment construction, and
  generative analysis, writing, and figures. Existing scenario-bound receipts
  are integration evidence, not a claim that these open-ended handlers are
  complete.
- Phase 9 evidence will distinguish component ablation on a common execution
  base from independent-system comparison of SciTaste Native against pinned
  external systems. Neither the current AutoResearchClaw-based cells nor native
  integration tests alone establish that SciTaste is better.
- The external-evaluation plan now treats `scitaste-self-development` as a
  process-only parent project and held-out benchmark attempts as separate formal
  child projects. A typed design contract blocks self-referential headline
  evidence, pseudo baselines, unmatched comparison blocks, incomplete
  statistical review, mutable feedback protocols, and unapproved launch bytes.
  The accepted-work audit identifies MLR-Bench as the primary idea-to-paper
  scaffold and EXP-Bench as the experiment-integrity scaffold. A tracked v4
  resource corpus adds TinyScientist and preserves its unresolved release-license
  conflict as a blocker. Endpoint schema v1.1 now prevents MLR-Bench's open-ended
  research-package rubric from being relabelled as objective progress: complete
  packages use blinded expert preference, while MLRC-Bench or another qualified
  fixed-scorer source forms a separate objective lane. Benchmark task-source and
  external comparison-system admission remain blocked pending frozen task bytes
  and licenses, adapters, mappings, sandbox/telemetry, power analysis, and the
  user's explicit resource-manifest approval.

- A content-hashed protocol covers diagnosis-friendly, clear-hypothesis,
  new-formulation, and ambiguous-direction tasks.
- AutoResearchClaw, Knowledge RAG, Taste Library, and Full SciTaste are enabled;
  Sibyl and AI Scientist-v2 remain explicitly unavailable pending pinned adapters.
- Three seeds generate 48 deterministic cells with opaque blind-review IDs and
  identical GPU, experiment, wall-time, API-cost, search, and token budgets.
- The evaluator rejects missing cells, failed execution, missing telemetry,
  over-budget usage, inconsistent experiment counts, internal/missing review,
  and unresolved protocol readiness markers.
- System metrics and deltas against AutoResearchClaw are implemented. Synthetic
  fixtures can only produce `acceptance_only`; headline eligibility requires real
  executions and valid external expert panels.
- A pinned, local-only Qwen3-VL-4B Transformers backend passed a Base/Full
  SciTasteBench smoke run on one RTX 3090. This clears local decision-backend
  feasibility, not the full matched-system execution gate.
- A shell-free, resumable `study run` harness now isolates cells, terminates
  timed-out process groups, measures allocated GPU/wall time, validates adapter
  counters and outcomes, and independently hashes in-cell artifacts.
- Study resume is now integrity-checked rather than status-only: self-hashed run
  and cell checkpoints bind protocol, plan, launcher, request, command, record,
  and evidence bytes; retries preserve failed attempts and concurrent writers
  cannot share an output root. A ProjectRuntime orchestration layer owns the
  study as one revision-guarded project run and distinguishes partial from
  complete matrices. `study project-run` exposes the same boundary without an
  unrelated free-form output directory.
- The bounded model-node engineering pilot now has a production-facing,
  project-owned CLI for planning, execution, resume, and verification. Resume
  dry-runs are mutation-free; completed prefixes and exact recordings are
  integrity-checked; live use requires configuration plus caller opt-in; and
  external measurements/review cannot be replaced with fixtures. This closes
  the orchestration implementation gate but does not accept ADR-022 or provide
  effectiveness evidence.
- Tool Intelligence now adds two normal durable nodes: one proposes an ordered,
  dependency-checked plan over three closed read-only capability schemas, and
  one proposes a repair against a content-bound supported output schema. The
  runtime validates project runs, scopes, arguments, budgets, identities, and
  exact replay while every model receipt remains advisory and non-executable.
  The v3 project boundary loads only content-addressed first-party sources and
  persists an expiring lease, exclusive claim, handler start/result,
  observation, decision envelope, and hash-chained ledger. Exact results replay
  without another handler call; ambiguous custom calls and stale revisions fail
  closed. An opt-in deterministic post-evidence hotspot now triggers that
  bounded read-only path inside Full Workflow, while the returned observation
  remains non-canonical and cannot enter the evidence graph. ADR-022 remains
  proposed pending independent review, broader effectiveness evidence, and
  external replication.
- A real project-owned GLM-5.3-Flash engineering probe completed all seven
  registered cases. The online response was schema-valid and exactly recorded,
  but deterministic token, latency, missing-cost, and action-allowlist gates
  rejected it. The report remains blocked on external intervention measurement,
  verified pricing/cost, an unsupported-action increase, and independent review;
  this validates enforcement, not effectiveness.
- A separate preregistered Tool Intelligence study has now exercised the full
  durable bridge for 36 live GLM-5.3-Flash treatment calls over 12 paired tasks
  and three seeds. It recorded 35/36 grounded resolutions versus 18/36 for the
  frozen router, six task-level improvements, zero regressions, six ties,
  exact McNemar p=0.03125, zero executed scope violations, 97,002 tokens, and
  USD 0.00727049 under the conservative registered price ledger. This is a
  narrow internal routing signal: the task set is project-authored, independent
  blinded domain review is still missing, external validity is unestablished,
  and the typed report cannot assert scientific effectiveness.
- A 16-cell Qwen3-VL-4B local pilot remains permanently non-headline. Its four
  conditions now have executable launchers backed by a loopback-only,
  bearer-protected OpenAI-compatible bridge to the exact local Transformers
  checkpoint; neither an API key nor a synthetic model response is substituted.
- The first project-owned RTX 3090 diagnosis/base cell made seven real local
  calls, completed AutoResearchClaw Stage 8 hypothesis generation and Stage 9
  experiment design, then failed before the next Stage 10 request when the
  cumulative 20,000-token pilot limit could no longer admit it. Exact nested
  telemetry records 10,131 prompt and 8,448 completion tokens, 267.754 seconds
  of model latency, zero API cost/searches/experiments, and 0.074909 allocated
  GPU-hours. It is transport and early-stage execution evidence, not a complete
  cell or an effectiveness result.
- That failure exposed a runner evidence-loss defect: the historical parent
  execution record contains unknown adapter counters although its child result
  is exact. Future non-zero launches now preserve any schema-valid failed child
  telemetry while still rejecting a child that claims success. The historical
  record is not rewritten retroactively.
- Completion-calibrated local runs now use a 200,000-token, three-hour pilot
  envelope and a content-addressed executable diagnosis kernel rather than
  relying on small-model code invention. Its canonical runner executes 1,944
  packets over the complete registered grid and reports source-verified method
  means, three-seed dispersion, factor effects, and reproducible failure
  boundaries. The observed boundary counts are 16 for majority vote, 0 for
  confidence weighted vote, and 3 for the position aware probe; the registered
  cross-method balanced accuracy is 0.923182.
- Clean v6--v8 cells all completed the real experiment and retained exact local
  usage, but were deliberately rejected before or at drafting. They exposed,
  in order, loss of factorial diagnostics in the generic analysis summary, an
  outline-checkpoint labeling mismatch, negation of an executed factor grid,
  and leakage of statistical shorthand/internal machine identifiers into prose.
  Diagnostics are now validated from the sole machine record, projected into
  every Stage 14 debate role, and checked again at analysis, outline, and draft.
  These are adapter integrity results, not a completed cell or effectiveness
  evidence; each historical run remains immutable.
- The evidence-bound v9 protocol passed offline/focused verification but its real
  attempt stopped before any admitted model token or experiment when the local
  RTX 3090 reported NVIDIA Xid 79 (GPU fallen off the bus). The zero-token
  attempt and 0.023591 allocated GPU-hours remain immutable. Resume is deferred
  until host-level GPU recovery; this operational failure neither establishes
  nor refutes complete Stage 8--18 feasibility.
- The formal protocol now pins `qwen3.8-max-2026-09-02`, a content-addressed
  no-live-search snapshot, and fixed-generator contracts for all four tasks.
- A first-party adapter runs unmodified AutoResearchClaw Stage 8–18 for the four
  core conditions. Knowledge and decision-precedent context remain isolated;
  Full additionally persists a real `TasteController` decision.
- Process-local controls disable hidden upstream retrieval, bound Qwen output,
  capture wire-token/cost telemetry, and reject generated experiment sources
  that violate the frozen-network policy.
- A real Qwen3.8-Max diagnosis/base preacceptance reached peer review with one
  valid generated experiment, a 0.828558 balanced-accuracy result, and a
  7,821-word paper draft. This validates one cell, not the four-condition or
  48-cell comparison.
- A clean commit-pinned formal base cell subsequently passed in one runner
  lifecycle with complete wall/GPU accounting, 138,157 provider tokens, one
  repaired real experiment, a 0.615945 registered aggregate, and Stage 18
  artifacts under predecessor protocol `20ee06e9...`. The current registered
  protocol is `ce09bf7d...`; later adapter fixes changed its implementation pin,
  so the earlier cell remains engineering evidence but is not one of the
  current matrix's reusable cells. All 48 current cells and their external
  blinded reviews remain pending.
- The Knowledge RAG preacceptance exposed a Stage 12 failure/Stage 13 repair
  provenance ambiguity and internal identifier leakage into its draft. The adapter
  now projects one hashed successful experiment into analysis/writing, separates
  publication language from audit identifiers, and rejects contradictory or
  internal-ID-bearing manuscripts. Analysis is now a pre-paper gate so a known-bad
  synthesis cannot consume drafting tokens; the outline is checked before drafting,
  and the resulting draft is independently gated before peer review. Three-seed
  evidence and dispersion cannot be flattened into an `N=1` summary. The adapter
  also preserves source-verified raw sandbox traces when upstream runtime repair
  retains only parsed metrics. Formal drafts now also require a complete 3×3 seed
  matrix, real dispersion, unique core sections, registered citations, and resolved
  figures. Passing drafts are deterministically packaged as self-contained
  Markdown/TeX/PDF deliverables without another model call. A later clean attempt
  exposed and regression-tested the quoted condition-summary stdout form before
  spending paper tokens. Two further clean attempts exposed seed-scoped metric
  blocks and `condition=<name> mean_ba=<value>` rows before paper generation.
  Those layouts are regression fixtures, and new executions must emit one
  internally verified machine-readable evidence record. A clean rerun remains
  required. A fourth clean attempt emitted that record but exposed an ambiguous
  initial-versus-repaired sandbox pairing; source-hash-based trace selection now
  regression-tests that case. A fifth attempt passed experiment acceptance and
  produced a correct three-seed analysis, exposing only an overly narrow
  corrective-language matcher before outline generation; that analysis now
  replays cleanly. A sixth attempt exposed disagreement between heuristic stdout
  metrics and the complete machine matrix; canonical condition means now win,
  and the primary aggregate is deterministically recomputed. Attempts 4–6 all
  replay through experiment acceptance under the combined fixes. A seventh
  attempt emitted a complete source-verified matrix but used a semantically
  equivalent nested `CONTRACT_SPEC` after upstream review regeneration. Strict
  field-by-field normalization now accepts that representation without modifying
  generated source; the failed run remains a fixture, while its Stage 13 output
  passes the corrected experiment gate only in an isolated offline replay. A new
  clean end-to-end rerun remains required. An eighth invocation produced a
  source-verified 3×3 matrix and canonical contract but rendered its human rows
  as `seed=<id>`; the original seed scanner rejected them. The corrected scanner
  accepts assignment-style identifiers, rejects `per seed` sample-count text,
  and replays that Stage 13 output at a derived aggregate of 0.803657979. The
  invocation's unintended second selected seed cell was stopped after the shared
  parser issue was known, and the entire directory remains a failed fixture.
  A ninth single-cell attempt confirmed the runner cap, but Stage 10 alignment
  regeneration discarded the canonical declaration while retaining scattered
  factor values; the strict gate rejected it before analysis at 64,678 tokens.
  Contract and machine-evidence requirements now appear in the Stage 10 system
  prompt used by initial generation, code-review fixes, and alignment
  regeneration. The scattered-value output remains rejected rather than being
  retrospectively inferred as compliant.
  A tenth single-cell attempt verified that the regeneration-safe prompt retains
  the canonical declaration and produced a valid 3×3 machine matrix, but the
  free-text seed scanner mistook `Total/seed: 648` for an identifier. Explicit
  seed-row parsing now replays that experiment gate at a derived aggregate of
  0.8069381276; the original run remains failed and was not resumed.
  An eleventh single-cell attempt passed the experiment and Stage 14 analysis
  gates, then stopped before drafting because the outline instruction `Do not
  infer N=1` was read as an affirmative claim. Prohibitive `do not infer/derive`
  language is now accepted while unqualified N=1 claims remain rejected.
  A twelfth attempt passed the experiment gate but stopped after Stage 14 because
  `do not serve as direct measurements of ... internal confidence` was treated
  as affirmative model-signal language. Synthetic-scope auditing now recognizes
  `do not` and `must not` limitations while preserving positive-claim rejection.
  A thirteenth attempt stopped before analysis because the seed-row scanner read
  the factor effect `seed: 0.008292` as seed zero while missing condition-first
  measurement rows. Decimal-safe matching and the explicit
  `Condition=... Seed=... BalancedAccuracy=...` form now cover that output.
  A fourteenth attempt passed the experiment gate but stopped after Stage 14
  because `collapsing the data into an N=1 ... summary is prohibited` was read as
  an affirmative collapse. Explicitly prohibited, forbidden, rejected, and
  avoided summaries are now corrective language; bare N=1 remains inadmissible.
  Current code replays v11 analysis/outline and v12/v14 analysis through their
  corrected gates. A fifteenth clean attempt could not start model work because
  Bailian returned provider code `Arrearage` on every request and recorded zero
  tokens. Online reruns are paused until the provider account returns to good
  standing; offline regression and artifact auditing remain available.
  A separate pilot-scoped Zhipu GLM-5.2 Knowledge RAG cell then completed the
  full experiment, analysis, drafting, packaging, and peer-review lifecycle at
  117,429 cumulative wire tokens. Its first two passes correctly stopped when
  the outline only promised a seed table and when the draft referenced a missing
  image. Source-verified outline checkpointing and missing-local-image removal
  now regression-test those provider-output forms. The final Markdown/TeX/PDF
  package is cross-provider engineering evidence only: the gate-driven direct
  continuation prevents duration comparison, 23 review concerns remain open,
  and no GLM result is mixed into the registered Qwen comparison.
  The same pilot protocol has now completed Base, Knowledge RAG, Taste Library,
  and Full SciTaste on the frozen diagnosis task through Stage 18. The four cells
  contain real experiments and self-contained Markdown/TeX/PDF packages. A
  replacement Full rerun reduced selected-experiment time from 734.58 seconds to
  0.63 seconds while preserving the 1,944-packet three-seed matrix. Using that
  replacement, the four conditions consumed 499,524 cumulative wire tokens.
  This clears four-condition
  engineering preacceptance, not effectiveness acceptance. Runs were continued
  after adapter gates exposed missing-stage resume, corrective `N=1` language,
  an incorrect contract-derived packet total, condition-first metric aliases,
  and corrective stale-failure language. The replacement was still continued
  after those adapter fixes, so runner duration remains excluded from matched
  efficiency claims despite the selected experiment's corrected performance.
  Interrupted and original artifacts are retained only as failure fixtures.
- Sibyl and AI Scientist-v2 are optional external integrations still to be
  implemented and acceptance-tested; no surrogate output is used while disabled.
- Pending before the exit gate: run all 48 commit-pinned cells without manual
  continuation, audit their artifacts, and collect external reviews.
- `study status` now scans project-owned aggregates without mutation, admits
  only exact-protocol records whose run/cell identities and evidence bytes
  rehash, excludes conflicting duplicates, and reports the next matched
  task/seed block. The 2026-09-09 scan classified 21 historical result files as
  foreign protocol revisions and counted 0/48 current records, preventing the
  predecessor Base acceptance from being reported as current progress.

## Self-development project

- `outputs/projects/scitaste-self-development/` is the canonical project-level
  record for SciTaste's own dogfooding iterations. It references the Phase 7.5
  adapter decision and Phase 9 defect-discovery evidence without moving raw runs.
- The bounded model-node infrastructure is implemented for review parsing,
  interpretation threats, and ambiguity-triggered action ranking. A fail-closed
  compatible live backend now pins provider/model and requires measured token,
  cost, latency, and pricing provenance before use.
- Normal project runs can now invoke those nodes through a durable runtime and
  narrow CLI/facade. Per-generation capability, per-node admission, and
  cumulative project budgets remain distinct; a restart-safe predecessor ledger
  retains every outcome and exact replay evidence. Nested symlinks, stale project
  revisions before/during a call, corrupted chains, and interrupted publication
  fail closed, while accepted advice remains non-executable.
- The first normal full-workflow consumer is complete: an opt-in evidence hook
  sends the actual immutable post-interpretation state to
  `interpretation-threat`, then binds its input, proposal, recording and runtime
  ledger into the evidence checkpoint. Scripted mode stays offline; a
  content-addressed GLM-5.3-Flash engineering condition requires a second caller
  authorization. Resume reuses completed entries or a complete recorded paid
  response without another provider call or double-counting; an ambiguous
  possibly-started call is never retried.
- A real `run full` GLM-5.3-Flash engineering condition completed all four
  stages, compiled its PDF and passed ledger verification. Its single advisory
  used 1,936 tokens and was rejected for unavailable cost plus an out-of-policy
  action, so it remains non-promotable evidence.
- A separate GLM-5.3-Flash source-generation probe reached the real endpoint and
  returned a structured response in 15.8 seconds using 1,260 input and 935 output
  tokens. Missing price provenance correctly rejected the node before file
  materialization; the retained candidate began with an invalid empty import and
  would also have failed deterministic code admission. The transport path is
  verified, but online source generation remains non-promotable and unexecuted.
- The provider-generation self-iteration is registered at self-development
  revision 147, while its complete offline Full Workflow acceptance is a
  separate canonical project, `scitaste-native-codegen-acceptance`. That project
  owns the verified ledger, generated/proposed/admitted source, three-replicate
  Bubblewrap result, and Markdown/TeX/PDF/SVG/draw.io paper bundle rather than
  scattering those artifacts across top-level stage directories.
- The versioned self-development pilot protocol and runner isolate
  deterministic, scripted, exact-replay, and Zhipu `GLM-5.3-Flash` live
  conditions. Canonical reports evaluate schema, gate-bypass, planned-case,
  replay, external manual-intervention, unsupported-reference, tool, cost, and
  independent-review gates. Missing live calls or external evidence block rather
  than being replaced with fixture results. The real engineering probe is now
  complete and blocked as designed; a priced, externally measured acceptance
  pilot remains pending.
- This exploratory self-project is excluded from the active Phase 9 registered
  comparison and from headline effectiveness claims.

## Project runtime progress

- Typed, backward-compatible project, run, paper, and snapshot schemas now make
  `outputs/projects/<project-id>/` an enforceable ownership boundary.
- Project creation and manifest mutation are atomic; file locks and monotonic
  expected revisions prevent silent concurrent-writer loss.
- Registered runs and paper bundles receive safe current aliases without moving
  historical evidence or modifying AutoResearchClaw.
- Existing FLOOR and SciTaste self-development manifests load through the same
  runtime, including alternate non-paper stage semantics and referenced runs.
- The project CLI supports create/status, run begin/select, paper
  register/select, and mutation-free dry-run validation.
- The trusted generative-UI adapter now converts the authoritative runtime view
  into project-relative, content-addressed manifest, run, stage, paper, and
  artifact evidence. It rejects missing paths and nested symlinks.
- `scitaste run full` now advances one state through the Phase 4--7 offline
  workflows inside one managed project run, retains readable per-stage records,
  registers a deterministic Markdown/TeX/PDF integration-fixture bundle, and
  records an evidence-bound UI snapshot. The bundle now carries a self-hashed
  manuscript assessment; requesting research-working-draft status fails closed
  on insufficient length, missing core sections, or known placeholders. Failed
  stage attempts remain auditable, while
  `--resume` reuses only a contiguous prefix whose self-hashed state, decisions,
  and required artifacts still validate; incomplete downstream work is archived
  before rerun and tampered completion records fail closed.
- Full Workflow finalization now has its own content-bound recovery transaction.
  Once all four stage records validate, resume can verify/reuse a registered
  paper, archive and rebuild only an unregistered partial paper or stale summary,
  complete the run metadata, and repair a missing post-completion surface without
  repeating any research-stage or provider action. Every paper file is hash-bound;
  registered paper or existing-surface drift blocks recovery.
- Full Workflow now has a strict open-question intake boundary. A `ResearchBrief`
  declares the question, objective, exact Discovery budget, evidence contract,
  success criteria, constraints, and prohibited claims before project mutation.
  Mutation-free inspection creates the same self-hashed launch plan used by a
  formal run; execution copies and consumes five hash-bound project inputs, and
  resume fails closed on plan or byte drift. This closes question-to-launch
  ownership for registered scenarios. Autonomous scenario synthesis and
  independently measured research-quality gain remain later gates.
- An opt-in scripted or double-gated live semantic advisory now participates
  after evidence interpretation through the normal model-node runtime. Its
  predecessor/input state, profile, policy, proposal, recording, ledger head,
  and stage artifacts are hash-bound; it has no state-transition or execution
  authority. Live interruption recovery consumes an already recorded response
  without a second provider call and refuses ambiguous repeats.
- A second opt-in Full Workflow hook generates proposal-only native experiment
  source through an additive typed runtime extension. Its pre-call brief,
  request, raw response, usage, extracted source, derived proposal, admission,
  and isolated execution are separately hash-bound. An accepted offline source
  runs only from `context/code/admitted/experiment.py`; interrupted downstream
  publication reuses the generation ledger instead of calling the backend again.
- Full Workflow now invokes Tool Intelligence from a deterministic post-evidence
  hotspot. The exact predecessor/current state, evidence summary, project
  revision, controlled profile, request, model ledger, tool lease, observation,
  and final advisory decision are project-owned and independently verified.
  Code generation, evidence advice, and tool planning may share one typed ledger;
  an earlier receipt is verified against its historical prefix rather than
  incorrectly compared with later cumulative totals.
- Open-question launch no longer requires the caller to choose four scenario
  files directly. The committed acceptance config uses a content-bound catalog;
  deterministic domain, budget, authorized-evidence, and keyword gates select a
  registered four-stage bundle and materialize the catalog plus selected inputs
  under the run. Arbitrary scenario synthesis remains outside this authority.
- Project-owned Discovery is the second normal model-node consumer. Its typed
  hypothesis, reformulation, and ideation nodes can replace scenario prose but
  cannot choose actions, rank/select ideas, call tools, mutate state, allocate
  actual budgets, or bypass project reservation. Offline self-iteration covers
  accepted content, invalid source/observation/hypothesis rejection, divergent
  proposal and cost bounds, cumulative budget admission, ordered history,
  project-owned native Knowledge retrieval, and no-second-call/no-second-search
  resume; live scientific-quality gain is not yet claimed.
- The AutoResearchClaw Stage 1–2 prerequisite and selected Stage 3 action now use
  the same project ownership/state contract. The bootstrap publishes a pre-call
  manifest, verified immutable source receipt, and interruption-safe paid-result
  recovery; Stage 3 binds that receipt rather than an arbitrary historical path.
  Selected-action recovery now also reuses an exact successful result after
  downstream interruption, binds its pre-call state/action/decision intent,
  revalidates the complete work tree and stage/cost evidence, verifies failures
  before retry, and blocks ambiguous or concurrent calls. Manifest `1.2` adds
  write-once prepared/start/result phase evidence, separates recovery attempts
  from external-call attempts, safely continues pre-call work, and admits a new
  call only after a prior failed result independently verifies.
  Full Stage 1–18 ownership and a priced, independently reviewed model-node
  effectiveness comparison remain pending; engineering evidence cannot be
  converted into an effectiveness claim.

## Generative interface progress

- Eleven trusted research components have closed data schemas and can populate
  only the workspace region of a fixed receiver-owned shell.
- Every surface is pinned to a ProjectRuntime revision and to hashes of the exact
  evidence it displays. Client events carry identity only and return
  proposal-only receipts; they cannot invoke tools or mutate research state.
- Surface openings, revisions, and accepted proposal receipts can be stored in a
  process-locked, hash-chained log whose complete semantic replay rejects
  tampering, reordering, truncation, stale revisions, and duplicate events.
- Deterministic fixtures cover project overview, paper status, blocked-run,
  next-step, and run-comparison surfaces.
- A trusted factory now projects the current ProjectRuntime state into a real
  project overview and the CLI transactionally publishes its surface, fixed-shell
  renderer document, and initial audit record without overwriting a destination.
- A packaged browser receiver and authenticated loopback-first API now discover
  authoritative projects, render every trusted component, reject stale or
  client-authored proposal payloads, and retain proposal receipts in project-local
  replayable audit epochs across restarts.
- The receiver now exposes seven server-owned evidence views for project, run,
  stage, paper, comparison, blocker, and pending-proposal navigation. Artifact
  inspection is limited to content-addressed evidence already visible in the
  current view; project switching clears stale catalogs, and audit storage binds
  every record plus lock/temp/replace operations to one project-owned directory.
- Project progress is now a first-class evidence view: observed completion,
  current work, blockers/failures, unavailable capabilities, paper state, and
  next-step candidates remain distinct and cite their project snapshot evidence.
- Evidence-derived quick intents and bounded free questions now resolve through
  one typed intent contract. A planner may only select, order, group, emphasize,
  and focus server-issued candidates; it cannot author data, HTML, actions, URLs,
  commands, or authority. Deterministic behavior remains the offline default.
- The `/api/v3/generative` receiver renders admitted plans as different native
  evidence workspaces, while `/api/v4` groups them into project-owned research
  topics and immutable turn pages. The default shell now opens on a project
  index, each project has its own home, and exact documents/surfaces persist
  across restart independently of the bounded in-memory cache. Loopback browsers
  establish a protected HttpOnly session without a credential field; explicit
  bearer clients and non-loopback gates remain supported. Optional structured
  model assistance is double-gated and requires finite byte, token, time, and
  measured-cost admission; invalid or unavailable output falls back safely.
- A read-only evaluator now fingerprints structural view-composition proxies and
  local service latency, while a loopback Chromium probe checks focus, reflow,
  target size, locale stability, and runtime errors at 1440/768/390/320 pixels.
  The self-hosted result found a 65.83-percent fixed-view structural proxy
  reduction but substantially slower deterministic generation and two
  12-component surfaces. These are engineering diagnostics, not observed click,
  task-time, comprehension, preference, or scientific-quality gains.
- Pending proposals now have deterministic controller endpoints in all three API
  families. Explicit approval/rejection is rebound to the current snapshot and
  server-owned action, recorded exactly once in the project audit chain, and
  yields only the registered read-only or approved-handoff boundary. Controlled
  proposals disappear from the pending view. The local UI still cannot mutate
  research state or execute tools; downstream services must consume the bounded
  handoff through their own contracts.

## Bounded native mainline closure

- The v1 product path is now closed from an open research brief through
  deterministic registered-scenario selection, project-owned Discovery,
  Evidence, Communication and Figure stages, isolated measured experiments,
  optional proposal-only model/code/tool nodes, publication packaging, project
  registration, and an evidence-bound interactive workspace.
- Every autonomy boundary remains narrower than execution: generated UI selects
  content, the proposal controller authorizes only a handoff, model nodes advise,
  and Tool Intelligence executes only a leased registered read-only handler.
- This is engineering/product completeness for the bounded native path, not a
  claim of autonomous open-domain research quality. Open-web retrieval,
  arbitrary environment construction, runtime-failure code repair, broader model-
  generated analysis/writing/figures, all 48 real matched-budget cells, and
  independent expert review remain Phase 9 capability/effectiveness gates.

## Writing Taste whole-paper closure

- Reviewer-driven long-form revision is now a distinct bounded model node. It
  revalidates the accepted source draft and target evidence projection, binds
  exact paper/packet/report hashes, and leaves evidence or experiment concerns
  blocked unless a later project state supplies a self-hashed closure proof.
  Proof-backed treatments must cite the exact new evidence; the node has no
  manuscript mutation, empirical execution, response-submission, or review-
  closure authority. Done: accepted revisions now materialize into registered
  Stage 19 bundles with a self-hashed trace, and author/original-reviewer records
  must bind the exact state-derived proof before a hard concern can close.
- A typed argument contract now joins central question/answer, registered
  claims, reciprocal evidence, reader-facing carriers, section delivery,
  high-attention entry points, and material limitations without treating a
  figure count as a universal quality rule.
- Venue paper builds can retain a self-hashed advisory assessment and recheck
  manuscript/carrier content. SciTaste itself now supplies a first explanatory
  control-loop figure and an evidence-boundary result table.
- The next acceptance gate is evidence, not more prose: complete the registered
  matched-budget cells and blinded expert review, then test the candidate
  reference-derived Writing Taste principles against accepted non-award and
  negative controls before promoting any of them to quality gates.

## Project controls

- One milestone owner and one acceptance issue per phase.
- Weekly triage: blockers, risks, decisions, and evidence of exit criteria.
- Every architecture change receives an ADR in `docs/ARCHITECTURE.md` or a
  dedicated `docs/adr/` record once ADR count grows.
- Generated research artifacts stay outside Git; manifests and hashes may be
  committed when needed for reproducibility.
- Generated runs are indexed through `outputs/INDEX.md`; each research project
  owns its runs and paper versions below `outputs/projects/<project-id>/`, while
  `outputs/papers/` remains an alias layer and historical run paths remain
  immutable for resume and audit.
- The submodule update cadence is milestone-bound, not automatic.

## Known integration issue

A real AutoResearchClaw Stage 1–3 slice has passed with a user-provided Bailian
key. Broader stages still require user-managed configuration and may incur
network/API/compute cost. CI therefore uses contract fixtures and dry-run rather
than contacting the provider.

Stage 1–2 bootstrap and one selected upstream stage now have a first-party
project-owned plan/execute/resume/status lifecycle with an immutable source
receipt, strict fresh completion evidence, incremental cost accounting,
configurable per-request and per-process token ceilings, and explicit live
authorization. A live GLM-5.3-Flash Stage 3 run passed the integration gate and
independent status rehash, while its unavailable API cost and ceiling-bound
  response keep it out of formal comparison. The new owned bootstrap-to-action
  handoff has also passed live execution and independent rehash; full Stage 1–18
  ownership and the 48-cell Phase 9 study are later gates.

Live taste calibration is also opt-in. Until credentials are provided, scripted
and replay backends support all implementation, regression, and integration work;
they must not be described as a real-model taste profile.
