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
The older two-task Qwen prelaunch file remains historical and must not be used
as though MLR-Bench package-review tasks supplied objective progress.

The historical API Track B design has an exact 100-trajectory candidate matrix:
SciTaste Native, Direct Agent, MLR-Agent, Agent Laboratory, and TinyScientist
over ten MLR-Bench research briefs and two seeds. It names the now-contradicted
DeepSeek `deepseek-flash` / `DeepSeek-V4.1-Flash` identity, with ceilings of
1,500 calls, 15 million tokens, USD 100, 100 GiB, and 30 reviewer-hours. That
matrix is non-launchable: the 2026-09-12 official catalog recheck instead names
`deepseek-v4-flash` / `DeepSeek-V4-Flash-0731`; MLR-Agent and Agent Laboratory
do not preserve the historical common backbone unchanged; TinyScientist has
unresolved code/license gates; task bytes and held-out audit are absent; and
independent reviewers are not secured. Its 100 trajectories are a ceiling, not
a target that must be consumed before pilot variance and reviewer burden are
known.

Consequently the next project-owner decision is methodological, not a launch:

1. select a genuinely common model backbone that at least two accepted systems
   support without changing their scientific core; or
2. preregister a best-native-system comparison that explicitly treats model
   choice as a confound and does not call the contrast a matched-backbone effect.

After that choice, SciTaste must create a new immutable dossier and prelaunch
proposal. Source acquisition, runtime preflight, pilot execution, formal
scale-out, paper revision, internal model critique, two independent expert
reviews, and original-reviewer closure each remain separate stages and require
their own exact evidence or approval.

## Acquisition control status

The bounded MLR-Bench source request now has an executable control path, but not
an approval. SciTaste can create an immutable approval artifact bound to the
exact request hash and can later execute a separate, atomic, download-only
transaction. The downloader rejects request drift, missing evidence, redirects,
unexpected media types, byte-ceiling violations, destination collisions, and
partial publication. A successful transaction emits observed file hashes and a
self-hashed receipt while keeping ingestion and execution authority false.

This closes a product-control gap only. No source file has been downloaded, no
task package has been admitted, and no API/GPU cell has become launchable. The
exact pending request, command sequence, and authority boundary are documented
in [`DATA_ACQUISITION_APPROVAL.md`](DATA_ACQUISITION_APPROVAL.md).

The prelaunch schema can represent either decision without conflating them.
Schema `1.2` assigns a common resource to every `matched_backbone` cell, while a
`best_native` lane must bind one provider/model resource to each system and
declare `model_effects_confounded=true`. The compiled cell plan preserves those
per-system identities, and best-native results cannot satisfy the
matched-backbone headline gate.

## Why this is part of the product

The dossier is more than project prose. It provides a stable projection that a
CLI, project homepage, or Generation-as-Content surface can summarize without
inventing missing cells or hiding resource conflicts. It also makes the
framework diagnose when the limiting factor is experimental design or system
compatibility rather than the capability of the model used to draft the plan.
