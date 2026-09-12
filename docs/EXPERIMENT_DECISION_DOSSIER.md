# Experiment decision dossier

The decision dossier is SciTaste's compact, machine-checked view of the work
between an evaluation idea and an authorized experiment. It exists because an
aggregate statement such as "run API and GPU experiments" hides the decisions
that determine whether the result can support a paper claim.

The current ICLR 2027 dossier is
`configs/evaluation/campaigns/iclr2027_self_development_v1.yaml`. It binds the
exact paper title, scientific questions, model-selection state and identities
where selected, data
scope, comparison systems, matrix arithmetic, resource ceilings, claim
boundaries, dependency stages, and source documents. The dossier itself is
strictly no-run: it cannot authorize downloads, remote-host access, provider
calls, GPU work, or reviewer recruitment.

Inspect it with:

```bash
.venv/bin/scitaste evaluation decision-dossier \
  --manifest configs/evaluation/campaigns/iclr2027_self_development_v1.yaml \
  --evidence-root . --require-artifacts
```

Use `--output /path/to/REPORT.json` to materialize only the deterministic
inspection report. This still performs no external action.

## Current decision

The decision-level Track A design is intentionally marked `design_only`. Schema
1.2 records its model as `unselected` and its compute budget as unallocated.
Its minimum mechanism matrix is Base, same-source raw RAG, same-source abstracted
Taste, and source-disjoint mismatched Taste over a 120-case natural-data floor
and two action-order arms. It does **not** claim an exact model-call or cell
count because the natural cases, human labels, source-disjoint split, blinded
review protocol, model-conformance result, and power analysis do not yet exist.
The local and remote Qwen checkpoints remain feasibility assets rather than
scientific design inputs.
The older Qwen/MLR-Bench objective-progress proposal remains historical. The
new 12-trajectory Qwen proposal instead names two MLRC objective-task
candidates, a separate claim contract, and explicit unresolved asset gates.

The current dossier records two exact but blocked historical prepilots. The
native v11 causal lane contains six SciTaste conditions over two MLRC
objective-task candidates and one seed: 12 Qwen3-VL-2B trajectories under one
shared GPU resource. Its v3 preflight separately verifies the bounded model path
and human-governed corpus-construction runtime without claiming that the real
corpora exist. The external lane contains SciTaste Native, Agent Laboratory, and
TinyScientist over the same two candidates and one seed: six trajectories with
DeepSeek V4.1 Flash, o3-mini, and GPT-4o-2024-08-06 explicitly bound per system.
The latter is best-native, model-confounded, and now non-launchable because the
DeepSeek identity has been superseded. The historical 100-trajectory
DeepSeek/MLR-Bench matrix remains evidence of an infeasible matched design, not
an active quota.

The current title-level scientific strategy is narrowed in
[`ICLR_2027_EXPERIMENT_STRATEGY_V1.md`](ICLR_2027_EXPERIMENT_STRATEGY_V1.md):
abstracted Taste versus raw-source RAG, matched versus mismatched Taste, and
Full versus Native Base are separate confirmation obligations. The earlier
dual-estimand architecture remains documented in
[`ICLR_2027_EVALUATION_ADDENDUM_V2.md`](ICLR_2027_EVALUATION_ADDENDUM_V2.md).
Real external systems occupy a separate best-native lane with model effects
explicitly confounded; it measures ecological package performance and failure
modes, not a causal Taste effect.

That strategy is now encoded separately in
[`iclr2027_scitaste_evidence_program_v1.yaml`](../configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml).
It is the scientific authority; this dossier remains a historical resource and
workflow projection. The evidence program gives InnovatorBench objective
progress, MLR-Bench full-lifecycle, and EXP-Bench integrity-diagnostic roles,
while Agent Laboratory, AI-Researcher, and DeepScientist occupy the accepted
method-candidate set. Its current no-run inspection is scientifically coherent
but blocks acquisition, experiment, and authorization. The Qwen and provider
identities below therefore cannot select or revise the experiment design.

That choice is now materialized in schema-1.3 prelaunch proposals and a
schema-1.2 campaign dossier. Source acquisition, runtime preflight, pilot
execution, formal scale-out, paper revision, internal model critique, two
independent expert reviews, and original-reviewer closure remain separate stages
and require their own exact evidence or approval.

## Acquisition control status

The owner-approved bounded request has now completed. Ten exact Markdown briefs
were downloaded atomically from the pinned MLR-Bench commit: 31,345 bytes with
receipt SHA-256 `96975fdea75c...`. Approval and data movement remained separate,
and the receipt still grants neither ingestion nor execution authority.

Post-acquisition qualification found that the files are broad workshop research
briefs. They are ready for a stagewise or brief-only package prepilot, but not
for formal empirical end-to-end or objective-progress binding: runtime assets,
an executable signal, objective scores, and the held-out audit are absent. See
[`research/MLR_BENCH_TEN_BRIEF_QUALIFICATION_AUDIT_V1.md`](research/MLR_BENCH_TEN_BRIEF_QUALIFICATION_AUDIT_V1.md).

The prelaunch schema represents the resulting two estimands without conflating
them. Schema `1.2` assigns a common resource to every `matched_backbone` cell,
while a `best_native` lane must bind one provider/model resource to each system
and declare `model_effects_confounded=true`. Schema `1.3` binds the exact claim
kind and full contrast family. The compiled cell plan preserves those
per-system identities and the claim hash; best-native results cannot satisfy the
native Taste or matched-external claim gates.

## Why this is part of the product

The dossier is more than project prose. It provides a stable projection that a
CLI, project homepage, or Generation-as-Content surface can summarize without
inventing missing cells or hiding resource conflicts. It also makes the
framework diagnose when the limiting factor is experimental design or system
compatibility rather than the capability of the model used to draft the plan.
