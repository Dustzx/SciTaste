# AutoResearch method census candidate v3

Date: 2026-09-11

Status: accepted-method census candidate plus targeted evaluation resources.
This document authorizes no dataset download, repository installation, model
call, GPU allocation, human study, or formal experiment.

## Why v2 was still too narrow

The v2 map correctly stopped treating method, benchmark, and hybrid papers as
interchangeable, but its 15-paper display was deliberately restricted to
selected ICLR, ICML, and NeurIPS evaluation precedents. That scope omitted
accepted NLP-venue AutoResearch methods and made the method lane look smaller
than the evidence search justified.

The v3 search starts from the two locally archived system surveys, screens
their computational AutoResearch rows, and checks candidate publication status
against official proceedings. This pass adds three accepted systems that meet
all of the following inclusion criteria:

1. the system changes at least two scientific-research decisions or stages;
2. it produces or executes code, experiments, analyses, or a research report;
3. the work is an archival peer-reviewed paper rather than only a benchmark
   leaderboard entry; and
4. an official proceedings page states the system and its evaluated research
   behavior.

This is not yet an exhaustive publication census. A second independent screen,
deduplication against the complete 56-system survey table, forward/backward
citation update, and executable-artifact audit remain open. Consequently, v3
changes the census gate from `blocked` to `candidate`, not to `ready`.

## Newly admitted accepted methods

| Method | Venue | What the paper evaluates | SciTaste comparison role |
|---|---|---|---|
| [Agent Laboratory](https://aclanthology.org/2025.findings-emnlp.320/) | Findings of EMNLP 2025 | A human-provided idea proceeds through literature review, experimentation, and report writing; model variants, human involvement, final-paper judgments, and reported cost reduction are evaluated. | Direct system candidate after task, model, intervention, telemetry, and artifact mappings pass. |
| [Dolphin](https://aclanthology.org/2025.acl-long.1056/) | ACL 2025 | Experiment results feed the next idea round on several topics and an MLE-bench subset; external task improvement is the primary signal. | Closed-loop decision/execution comparator; not automatically a full paper-quality comparator. |
| [CodeScientist](https://aclanthology.org/2025.findings-acl.692/) | Findings of ACL 2025 | Hundreds of experiments produce 19 candidate discoveries; six survive a combination of external paper review, code review, and replication attempts. | Strong method and evaluation precedent; semi-automated inputs and human curation must remain explicit in any comparison. |

The accepted display now contains six primary method papers, two hybrid
system-resource papers, and ten targeted benchmark/evaluation papers. The ten
benchmark rows remain a design-relevance sample, so the resulting 6/2/10 counts
still do **not** estimate the publication prevalence of methods versus
benchmarks.

## Experiment-design consequence

The ICLR 2027 plan requires two non-overlapping inventories:

- **System comparators** come from the method or decomposed hybrid lane. A
  system enters a matched run only after its unchanged core can consume an
  equivalent task package and expose failures, interventions, artifacts,
  tokens, cost, wall time, allocated accelerator time, and active use.
- **Evaluation resources** come from the benchmark lane. They supply tasks,
  environments, rubrics, judges, or human-calibration precedent; citing or
  using such a resource does not imply that its bundled baseline agent ran.

For direct comparison, Agent Laboratory joins MLR-Agent, AI Scientist-v2, and
AutoResearchClaw as an adapter-audit candidate. Dolphin is initially scoped to
the iterative decision/execution layer. CodeScientist is initially a
semi-automated sensitivity comparator and a precedent for code review plus
replication. CycleResearcher remains a paper/review-output comparison rather
than executable experiment evidence. DeepScientist remains a frontier-scale
reference until an affordable semantically matched condition exists.

No method becomes formally ready from literature evidence alone. Exact task
compatibility, licenses, repository commits, provider/model modes, sandboxes,
telemetry, failure policy, and pilot variance still govern launch.
