# Experiment decision dossier

The decision dossier is SciTaste's compact, machine-checked view of the work
between an evaluation idea and an authorized experiment. It exists because an
aggregate statement such as "run API and GPU experiments" hides the decisions
that determine whether the result can support a paper claim.

The current ICLR 2027 dossier is
`configs/evaluation/campaigns/iclr2027_self_development_v1.yaml`. It binds the
exact paper title, scientific questions, model and checkpoint identities, data
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

The local Track A design is intentionally marked `design_only`. It identifies
Qwen3-VL-2B-Instruct, eight RTX 3090 devices, the six mechanism conditions, a
120-case natural-data floor, two order arms, 1,440 minimum model decisions, a
16 allocated-GPU-hour ceiling, and a 100-GiB storage ceiling. It does **not**
claim an executable cell matrix because the natural cases, human labels,
source-disjoint split, and remote checkpoint attestation do not yet exist.
The older Qwen/MLR-Bench objective-progress proposal remains historical. The
new 12-trajectory Qwen proposal instead names two MLRC objective-task
candidates, a separate claim contract, and explicit unresolved asset gates.

The active dossier now records two additional exact but blocked prepilots. The
native v11 causal lane contains six SciTaste conditions over two MLRC
objective-task candidates and one seed: 12 Qwen3-VL-2B trajectories under one
shared GPU resource. Its v3 preflight separately verifies the bounded model path
and human-governed corpus-construction runtime without claiming that the real
corpora exist. The external lane contains SciTaste Native, Agent Laboratory, and
TinyScientist over the same two candidates and one seed: six trajectories with
DeepSeek V4.1 Flash, o3-mini, and GPT-4o-2024-08-06 explicitly bound per system.
The latter is best-native and model-confounded. The historical 100-trajectory
DeepSeek/MLR-Bench matrix remains evidence of an infeasible matched design, not
an active quota.

The methodological choice is now resolved in
[`ICLR_2027_EVALUATION_ADDENDUM_V2.md`](ICLR_2027_EVALUATION_ADDENDUM_V2.md).
The title-supporting causal estimate is a matched, randomized intervention over
SciTaste Native's Taste components. Real external systems occupy a separate
best-native lane with model effects explicitly confounded. The latter measures
ecological package performance and failure modes, not a causal Taste effect.

That choice is now materialized in schema-1.3 prelaunch proposals and a
schema-1.1 campaign dossier. Source acquisition, runtime preflight, pilot
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
