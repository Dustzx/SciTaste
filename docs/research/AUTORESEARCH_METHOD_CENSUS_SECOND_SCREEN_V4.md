# AutoResearch method census: independent second screen v4

Date: 2026-09-11

Status: second screen complete; census remains a candidate until the declared
saturation check and executable-artifact audit finish. This document authorizes
no repository installation, dataset download, model/API call, GPU allocation,
human study, or formal experiment.

## Question and unit of classification

This screen answers two different questions instead of counting every paper in
one lane:

1. **Method evidence:** which peer-reviewed systems change scientific decisions
   or carry out a meaningful portion of a research workflow?
2. **Evaluation infrastructure:** which peer-reviewed works contribute tasks,
   datasets, environments, rubrics, or judges on which systems can be measured?

A paper can be `hybrid` when it makes inseparable system and evaluation-resource
contributions. Its system may be considered as a comparator and its benchmark
as a task source, but those uses receive separate eligibility decisions. The
numbers in the resulting map are counts inside this relevance-gated corpus, not
an estimate of whether the field publishes more methods or benchmarks.

## Search protocol

The first screen covered the accepted ICLR/ICML/NeurIPS and NLP-venue entries
recorded by v3. The independent second screen used:

- official ICLR, ICML/PMLR, NeurIPS, ACL, NAACL, and Findings proceedings;
- the terms *autonomous research*, *scientific discovery agent*, *research
  agent*, *research idea generation*, *experiment design*, and *paper
  generation*;
- title/abstract screening followed by an official publication-page check; and
- official repository inspection when a paper claimed an executable artifact.

The date boundary is the date above. Inclusion requires an archival publication
and either (a) a system that changes at least two scientific decisions/stages or
executes a closed-loop domain experiment, or (b) a research-specific evaluation
resource with a reusable task, objective signal, rubric, or judge. Generic
office agents, pure literature QA/summarization, ordinary AutoML, proof search,
and benchmarks without a scientific-research decision are excluded. A paper may
be retained as `stage-specific`, `domain-boundary`, or `design-precedent` without
becoming a headline end-to-end comparator.

## Material additions recovered by the second screen

| Work | Archival evidence | Type | What is actually evaluated | SciTaste use |
|---|---|---|---|---|
| [ResearchAgent](https://aclanthology.org/2025.naacl-long.342/) | NAACL 2025 long paper | method | Literature-grounded problem, method, and experiment design with iterative reviewer feedback and human/model evaluation | stage-specific Taste precedent; it does not execute the proposed experiments |
| [BioDiscoveryAgent](https://proceedings.iclr.cc/paper_files/paper/2025/hash/4252dc94531833029000f85dc5fac792-Abstract-Conference.html) | ICLR 2025 | method | Closed-loop genetic perturbation choice, outcome reasoning, and hypothesis-space navigation | domain-boundary evidence for experiment-selection taste, not a general idea-to-paper baseline |
| [MOOSE-Chem](https://proceedings.iclr.cc/paper_files/paper/2025/hash/51fd9a7d1706023cb9f8210cc6ac357c-Abstract-Conference.html) | ICLR 2025 | hybrid | Inspiration retrieval, chemistry-hypothesis composition/ranking, plus a 51-paper expert-built benchmark | stage-specific Taste and benchmark precedent; no executed wet-lab validation |
| [ResearchTown](https://proceedings.mlr.press/v267/yu25i.html) | ICML 2025 | hybrid | Research-community simulation and ResearchBench node-masking evaluation for reading, writing, review, and interdisciplinary ideation | design precedent only; simulated community behavior is not scientific progress |
| [MLRC-Bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/82c96f3c90741ef2c9b248e65d9b5db0-Abstract-Datasets_and_Benchmarks_Track.html) | NeurIPS 2025 Datasets and Benchmarks | benchmark | Seven ML research competitions with objective task metrics; the best tested agent closes only 9.3% of the human gap | high-priority task-source candidate for implementation and external-progress endpoints |
| [AAAR-1.0](https://proceedings.mlr.press/v267/lou25c.html) | ICML 2025 | benchmark | Equation inference, experiment design, and paper-weakness identification | decision-level and reviewer-ability task-source candidate, not an end-to-end system |
| [MM-Agent / MM-Bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1ddd6c6909c2a7acf877ce0f84abf6eb-Abstract-Conference.html) | NeurIPS 2025 | hybrid | Open-ended problem analysis, mathematical formulation, computation, and report generation on 111 modeling problems | domain-boundary evidence; not a general autonomous-research comparator |
| [FRAME](https://aclanthology.org/2025.findings-acl.400/) | Findings of ACL 2025 | method | Feedback-refined medical paper generation over a paper-derived corpus with automated and human assessment | writing/evaluation precedent; not evidence of novel executed research |

The screen therefore expands the displayed corpus from 18 to 26 entries: nine
methods, five hybrids, and twelve benchmark/evaluation works. This is a corpus
composition statement only. It must never be rewritten as “benchmarks are more
common than methods” or any other prevalence claim.

## Publication evidence and runnable readiness are independent

Publication acceptance is not an execution-readiness proxy. The v4 candidate
contract therefore uses two orthogonal fields:

- `publication_status` records accepted archival evidence, preprint-only
  evidence, first-party code, a declared lower-bound baseline, or a human
  protocol;
- `evaluation_track` records headline system, sensitivity system, task source,
  or judge source.

The resulting no-run priority is:

1. **Headline external candidates:** MLR-Agent, AI-Researcher, and Agent
   Laboratory. Each is associated with an accepted archival paper and released
   code, but none is formal-ready until unchanged-core adapter, task, model,
   sandbox, telemetry, artifact, failure/resume, and license gates pass.
2. **First-party and lower bound:** SciTaste Native and the real prompt-only
   direct agent.
3. **Sensitivity systems:** AI Scientist-v2 and AutoResearchClaw remain real
   pinned artifacts but are preprint-only; Dolphin and CodeScientist remain
   accepted but stage- or intervention-mismatched. These cannot satisfy the
   requirement for two independent accepted external headline systems.
4. **Task sources:** MLR-Bench and MLRC-Bench are primary; EXP-Bench and
   AAAR-1.0 provide experiment-chain and decision/review coverage. A task source
   is never counted as a system comparator merely because its paper bundles a
   baseline agent.

AI-Researcher's official repository is pinned for metadata inspection, but no
root license file was present under the checked `LICENSE`, `LICENSE.md`, or
`LICENSE.txt` paths. It is therefore a high-priority accepted candidate and a
blocked code-admission candidate at the same time. Agent Laboratory exposes an
MIT license, but matched-task behavior and complete telemetry still require an
adapter audit. No pseudo-implementation may replace either system.

## Saturation and freeze decision

This second independent screen recovered eight material entries, so the census
has not reached the preregistered saturation rule. One further update must:

1. screen backward/forward citations and the unscreened rows of the consolidated
   56-system table;
2. rerun the official-proceedings query with the same inclusion rules;
3. record every exclusion with a reason; and
4. add no high-impact eligible work in two consecutive updates before the
   census gate can become `ready`.

The experiment freeze remains `hold`. The v4 map is sufficient to prioritize
no-run adapter and task audits; it is not sufficient to authorize a pilot or to
claim that the formal comparison set is final.
