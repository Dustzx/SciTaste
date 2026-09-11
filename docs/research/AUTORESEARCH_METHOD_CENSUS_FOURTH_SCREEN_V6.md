# AutoResearch evidence census: independent fourth screen v6

Date: 2026-09-11

Status: fourth screen complete; the corpus is not saturated because this update
still recovered material accepted method and evaluation work. This document
authorizes no repository installation, data download, model/API call, GPU
allocation, human study, or experiment execution.

## Decision before counting

The fourth screen preserves a contribution-first distinction:

1. A **method/system paper** must contribute an agent, search policy, algorithm,
   or workflow that changes scientific decisions. A benchmark's convenience
   baseline is not a method contribution by default.
2. A **benchmark/evaluation paper** contributes tasks, environments, datasets,
   rubrics, judges, or controlled diagnostic evidence. It may supply an
   experiment substrate, but it is not a system comparator.
3. A **hybrid paper** must make both contributions independently. Merely shipping
   a baseline agent with a benchmark is insufficient.

Publication status, contribution type, experiment role, executable readiness,
and formal-comparison eligibility remain separate decisions. Counts below
describe this bounded corpus only; they cannot estimate the prevalence or
acceptance rate of any paper type in the field.

## Fourth-screen protocol

The screen inspected the consolidated ICLR 2026 proceedings, the COLM 2025
MLGym record, and backward/forward references around the v5 system and task
anchors. Queries covered *research agent*, *scientific coding*, *scientific
workflow*, *innovation*, *replication*, *machine-learning engineering agent*,
and *multimodal scientific discovery*. Every included work was checked on an
official proceedings or conference-paper record.

Inclusion still requires either:

- a system that changes at least two scientific decisions/stages or performs a
  closed-loop domain experiment; or
- reusable research-specific tasks, environments, data, rubrics, judges, or a
  controlled capability study that directly informs SciTaste evaluation.

## Material additions

| Work | Archival evidence | Type | Actual contribution | SciTaste role |
|---|---|---|---|---|
| [MLGym](https://openreview.net/pdf?id=ryTr83DxRq) | COLM 2025 conference paper | benchmark | A Gym-style environment and 13 open-ended ML research tasks | Task/environment precedent; its bundled baseline does not become a method comparator |
| [InnovatorBench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/3d13d910b48ac2e672a32cfdf98be1bf-Abstract-Conference.html) | ICLR 2026 | benchmark | Twenty long-horizon LLM-research tasks plus ResearchGym, executable outputs, and multi-axis evaluation | High-priority task-source candidate after asset, cost, and adapter audit |
| [InnoGym](https://proceedings.iclr.cc/paper_files/paper/2026/hash/743514dfa1ef705f378424bd1effb57b-Abstract-Conference.html) | ICLR 2026 | benchmark | Eighteen tasks and an execution environment measuring both novelty and performance gain | Direct Scientific Taste outcome precedent; judge validity and task leakage remain open |
| [ScienceBoard](https://proceedings.iclr.cc/paper_files/paper/2026/hash/7a9745f251508a053425a256490b0665-Abstract-Conference.html) | ICLR 2026 | benchmark | A multimodal scientific-software environment and 169 human-validated tasks across six domains | GPU/multimodal robustness candidate, not an idea-to-paper method comparator |
| [AutoExperiment](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c97be322f9cd2923f8f48620a205f006-Abstract-Conference.html) | ICLR 2026 | benchmark | Progressive code masking from partial reproduction to experiment replication | Experiment-implementation stress test, outside headline idea-to-paper comparison |
| [NewtonBench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a0e1c2c40fc245b5fe7251ea33fbb045-Abstract-Conference.html) | ICLR 2026 | benchmark | 324 interactive scientific-law-discovery tasks across 12 physics domains | Exploration-versus-exploitation and discovery-validity precedent |
| [MoSciBench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c5bf5ddafabe070d214d3f9a6c7e2067-Abstract-Conference.html) | ICLR 2026 | benchmark | Eighty-eight end-to-end multimodal hypothesis-verification tasks in six domains | Cross-modal evidence-integration task source after resource audit |
| [MedAgentGym](https://proceedings.iclr.cc/paper_files/paper/2026/hash/911ca386fecaf7ebac35bb64733050fc-Abstract-Conference.html) | ICLR 2026 | benchmark | 72,413 executable biomedical-data-science tasks across 129 categories | Domain robustness and training-environment precedent, not a paper-production baseline |
| [SciNav](https://proceedings.iclr.cc/paper_files/paper/2026/hash/577cd5863ec73be4e6871340be0936ae-Abstract-Conference.html) | ICLR 2026 | method | Relative-judgment-guided top-k tree search for scientific coding | Accepted method precedent for comparative Taste decisions; stage-specific comparator only |
| [Reinforcement Learning for Machine Learning Engineering Agents](https://proceedings.iclr.cc/paper_files/paper/2026/hash/fe32a779aba1dc51a00861708944ee35-Abstract-Conference.html) | ICLR 2026 | method | Duration-aware asynchronous RL and verifier instrumentation for MLE agents | Resource-aware learning precedent; training intervention is not matched to SciTaste's inference-time method |
| [MetaMuse](https://proceedings.iclr.cc/paper_files/paper/2026/hash/85632be2cd69e9a0ef4ba054c096fac9-Abstract-Conference.html) | ICLR 2026 | method | External-stimulus, diversity/usefulness-aware creative algorithm search with executable validation | Strong stage-specific precedent for reference-derived Taste and useful novelty |

The composed corpus now contains 45 entries: 16 method, 6 hybrid, and 23
benchmark/evaluation entries. Twenty-two entries expose a method/system artifact;
29 expose evaluation infrastructure, with six hybrids belonging to both sets.
This bounded evidence set now contains more accepted benchmark/evaluation works
than method works, but it still does not support a field-wide prevalence claim.

## Exclusion ledger and boundary decisions

| Candidate | Decision | Reason |
|---|---|---|
| [ResearchRubrics](https://proceedings.iclr.cc/paper_files/paper/2026/hash/92808d4b229345ae40fce84b4bf038d0-Abstract-Conference.html) | external evaluation precedent | Expert-written deep-research rubrics are useful for content assessment, but the tasks produce desk-research reports rather than scientific decisions or executed evidence. |
| [DeepResearch Bench](https://proceedings.iclr.cc/paper_files/paper/2026/hash/465f22be10e07b301c6ed58f0472f704-Abstract-Conference.html) | external evaluation precedent | Measures research-report synthesis and citations without experimental or idea-to-evidence closure. |
| [IterResearch](https://proceedings.iclr.cc/paper_files/paper/2026/hash/3369a3b268a86804237ef4702ac99ed3-Abstract-Conference.html) | interaction precedent | A long-horizon deep-research method, but its endpoint is an evolving sourced report rather than executed scientific research. |
| [Eigen-Agent](https://proceedings.iclr.cc/paper_files/paper/2026/hash/230072eb053908b7f9d7aca0b36bd7f2-Abstract-Conference.html) | reasoning precedent | Improves scientific question answering; it does not make or close a scientific experiment decision. |
| What Does It Take to Be a Good AI Research Agent? | preprint-only sensitivity evidence | Important evidence for ideation diversity, but no archival acceptance was verified by the cutoff. |
| AIRS-Bench | preprint-only resource candidate | Potentially relevant frontier-research tasks, but no archival acceptance was verified by the cutoff. |
| AblationBench and FabScore | post-cutoff candidates | Relevant ICLR 2027-era evaluation submissions, but not accepted archival work at the fixed evidence date. |
| Darwin G\u00f6del Machine | Tool Intelligence precedent | Self-improves agent code on coding benchmarks; it does not conduct an idea-to-paper scientific workflow. |

An exclusion here means “not part of the matched scientific idea-to-paper
corpus,” not “low-quality” or “irrelevant to product design.”

## Consequences for the ICLR 2027 experiment

- The accepted literature now supplies many task and judge choices, but still a
  smaller executable pool of comparable full systems. This is an evaluation-
  design constraint, not evidence that SciTaste should compare itself only with
  benchmarks.
- The headline row remains a matched comparison of **systems**. InnovatorBench,
  InnoGym, ScienceBoard, MLGym, AutoExperiment, NewtonBench, MoSciBench, and
  MedAgentGym can only supply tasks, environments, or diagnostic axes unless a
  separately accepted method artifact passes system admission.
- InnovatorBench and InnoGym make “useful novelty” measurable through executable
  gain plus novelty. They are especially relevant to Scientific Taste, but
  neither score can replace blinded expert assessment of idea importance.
- ScienceBoard and MoSciBench provide principled candidates for the Qwen3-VL-2B
  GPU robustness lane. They do not justify using a small VLM as the common
  backbone for the API-based headline idea-to-paper comparison.
- SciNav and MetaMuse strengthen the mechanism comparison around relative
  judgment, diverse exploration, external stimuli, and usefulness-aware
  selection. They remain stage-specific methods, not end-to-end paper systems.
- Every formal task still requires exact asset, license, contamination,
  telemetry, compute, and scoring admission. Literature inclusion authorizes no
  execution.

## Saturation decision

This update recovered eleven material accepted works, so the census remains
`hold`. The operational comparison set may be version-frozen for a prepilot, but
the literature corpus cannot be called saturated. Under the preregistered rule,
two consecutive official-source updates with no high-impact eligible addition
are still required. The next screen should focus narrowly on the newly admitted
works' citations and exact executable-resource records rather than repeat broad
keyword search.
