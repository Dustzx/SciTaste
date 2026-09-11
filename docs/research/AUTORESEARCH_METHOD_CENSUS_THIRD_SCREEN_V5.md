# AutoResearch evidence census: independent third screen v5

Date: 2026-09-11

Status: third screen complete; the corpus is not saturated because this update
still recovered material method and evaluation work. This document authorizes
no repository installation, data download, model/API call, GPU allocation,
human study, or experiment execution.

## The three publication lanes are not interchangeable

The census keeps three contribution types separate before it asks whether an
artifact is suitable for a SciTaste experiment:

1. **Method/system papers** introduce an agent, algorithm, or workflow that
   changes how scientific decisions are made. These are the only papers whose
   released systems can become method comparators.
2. **Benchmark/evaluation papers** introduce tasks, environments, datasets,
   rubrics, judges, or controlled capability studies. These can supply
   measurement infrastructure, but their bundled baseline is not automatically
   a method comparator.
3. **Hybrid papers** make both contributions. Their system and evaluation
   artifact receive independent admission decisions.

The current corpus composition must not be used to claim that the field accepts
more benchmark papers or more method papers. Search terms, venue coverage, the
date boundary, and the inclusion rule all affect these counts.

## Third-screen protocol

The third screen repeated the official-proceedings search over ICLR, ICML/PMLR,
NeurIPS, ACL, NAACL, EMNLP, Findings, and system-demonstration proceedings. It
added the terms *AI co-scientist*, *automated scientist*, *open-ended scientific
discovery*, *scientific idea generation*, *research-agent framework*, and
*research reproduction*. Candidate abstracts were classified by their primary
scientific claim and then checked on the official archival page.

Inclusion still requires either:

- a system that changes at least two scientific decisions/stages, or performs a
  closed-loop domain experiment; or
- reusable research-specific tasks, environments, data, rubrics, judges, or a
  controlled capability study that directly informs evaluation design.

Acceptance, relevance, released code, licensing, adapter feasibility, and
formal experiment eligibility remain separate fields.

## Material additions

| Work | Archival evidence | Type | Actual contribution | SciTaste role |
|---|---|---|---|---|
| [Virtual Scientists (VIRSCI)](https://aclanthology.org/2025.acl-long.1368/) | ACL 2025 long paper | method | Multi-agent generation, evaluation, and revision of scientific ideas, with human/model assessment and collaboration ablations | Stage-specific method and Taste-search precedent; not an idea-to-paper executor |
| [AutoDiscovery](https://proceedings.neurips.cc/paper_files/paper/2025/hash/23b127521af7ca7a42f5cdb7507be4f2-Abstract-Conference.html) | NeurIPS 2025 main track | method | Open-ended question selection and discovery driven by Bayesian surprise under a fixed budget | Strong selection-objective precedent for Scientific Taste; domain-boundary rather than a paper-production baseline |
| [TinyScientist](https://aclanthology.org/2025.emnlp-demos.41/) | EMNLP 2025 system demonstrations | method | Interactive and extensible research-agent framework spanning ideation, experimentation, writing, review, and human control | Accepted end-to-end system candidate; code/license and unchanged-core adapter gates remain open |
| [Quest2DataAgent](https://aclanthology.org/2025.emnlp-demos.36/) | EMNLP 2025 system demonstrations | method | Research-question decomposition, scientific data retrieval, quality evaluation, and visualization in two domains | Data-acquisition and evidence-quality precedent; stage-specific only |
| [SafeScientist / SciSafetyBench](https://aclanthology.org/2025.emnlp-main.116/) | EMNLP 2025 main conference | hybrid | Safety-aware AI-scientist workflow plus 240 high-risk scientific tasks and tool-risk evaluation | Safety/integrity precedent; intervention-mismatched sensitivity system and evaluation source |
| [HeurekaBench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/12d25b1673452b017fe9c866d9f494a0-Abstract-Conference.html) | ICLR 2026 | benchmark | Exploratory end-to-end questions grounded in experimental datasets, studies, code, and verified workflows | High-priority domain task-source candidate after asset/license audit |
| [Automated LLM Speedrunning Benchmark](https://proceedings.neurips.cc/paper_files/paper/2025/hash/27e7f21d16fb840f3720ac87ad896220-Abstract-Datasets_and_Benchmarks_Track.html) | NeurIPS 2025 Datasets and Benchmarks | benchmark | Reproduction and improvement of NanoGPT under an objective execution signal | Narrow but objective replication/progress endpoint; not a general research method |
| [All That Glitters is Not Novel](https://aclanthology.org/2025.acl-long.1249/) | ACL 2025 long paper | benchmark/evaluation | Controlled expert plagiarism audit of AI-generated research documents | Judge and leakage-audit precedent; not a reusable autonomous-research system |

The composed corpus now contains 34 entries: 13 method, 6 hybrid, and 15
benchmark/evaluation entries. Nineteen entries expose a method/system artifact;
21 expose evaluation infrastructure, with six hybrids belonging to both sets.
These are overlapping evidence lanes, not mutually exclusive experiment roles
and not prevalence estimates.

## Explicit exclusions from this update

| Candidate | Exclusion reason |
|---|---|
| AutoML-Agent | A strong accepted full-pipeline AutoML method, but starts from a supplied ML task and optimizes model construction; it does not make the research-question-to-evidence contribution required by this census. |
| WebThinker | Deep web research and report synthesis without scientific experiment or research-decision closure; relevant engineering context, outside the scientific-agent comparison set. |
| Exploring Multi-Agent LLM Dialogues for Research Ideation | Useful ablation evidence about dialogue structure, but no separately reusable research system or task source beyond the included VIRSCI/ResearchAgent lane. |
| Foundation Models for Scientific Discovery | Position paper; useful taxonomy context but neither an executable comparator nor an evaluation resource. |
| Generic agent-instruction, scientific-QA, and scientific-reasoning benchmarks | Measure prerequisite skills rather than autonomous research decisions or end-to-end scientific progress. |

Exclusion from the experiment corpus is not a judgment of paper quality.

## Consequences for the ICLR 2027 design

- The main system comparison must use accepted method or hybrid systems, a real
  direct-agent lower bound, and SciTaste Native. Benchmark papers remain task or
  judge sources.
- TinyScientist is added as an accepted headline candidate, but is `reference`
  only until its exact implementation, license, adapter, telemetry, failure, and
  artifact contracts pass.
- VIRSCI, AutoDiscovery, Quest2DataAgent, and SafeScientist test important
  stages or interventions. They do not automatically become headline
  end-to-end comparators.
- HeurekaBench, the speedrunning benchmark, and the plagiarism audit expand
  task/judge design options without increasing the method-baseline count.
- The published numbers and claims in these papers are literature evidence;
  none is a SciTaste experimental result.

## Saturation decision

This update recovered eight material entries, including four accepted method
systems and one hybrid system. The census therefore remains `hold`. A fourth
screen must inspect backward/forward citations and the remaining consolidated
table, publish an exclusion ledger, and then apply the preregistered rule: two
consecutive updates with no high-impact eligible addition before the comparison
set may be called saturated. Adapter and task eligibility remain independent
blocking gates even after literature saturation.
