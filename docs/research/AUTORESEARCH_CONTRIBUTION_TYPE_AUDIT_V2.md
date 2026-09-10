# AutoResearch contribution-type audit v2

Date: 2026-09-11

Status: literature and protocol-design evidence only. This document authorizes
no model call, dataset download, external-system installation, API spend, GPU
allocation, human study, or formal experiment.

## Correction

The v1 evaluation landscape is a targeted collection of accepted evaluation
precedents, not a publication census. Its rows mixed three different kinds of
paper and therefore made a benchmark-heavy sample look like a claim about the
whole field. That inference is not supported.

This revision assigns every accepted paper one **primary contribution type**:

- `method`: the main contribution changes how an autonomous research system
  reasons, searches, learns, executes, or revises;
- `benchmark`: the main contribution is a task collection, environment, rubric,
  judge, or capability measurement, even if the paper also implements a baseline
  agent; and
- `hybrid`: a method/system and a new evaluation resource are both central
  contributions and cannot be separated without misrepresenting the paper.

The type of a paper is not its role in SciTaste's experiment. A benchmark paper
may provide a task source, a method paper may provide a system comparator, and
either may only be a design precedent. Bundled artifacts are recorded separately
so, for example, the MLR-Agent inside MLR-Bench does not turn the accepted
Datasets and Benchmarks paper into a method-paper baseline by implication.

## Targeted accepted sample

The revised visualization contains 15 representative ICLR, ICML, and NeurIPS
papers through 2026-09-11:

| Primary type | Count | Papers |
|---|---:|---|
| Method/system | 3 | CycleResearcher; DeepScientist; AI Research Agents for Machine Learning |
| Hybrid | 2 | AI-Researcher with Scientist-Bench; Predicting Empirical AI Research Outcomes with Language Models |
| Benchmark/evaluation | 10 | MLR-Bench; EXP-Bench; PaperBench; RE-Bench; MLE-bench; MLAgentBench; AstaBench; DiscoveryWorld; ScienceAgentBench; Can LLMs Generate Novel Research Ideas? |

The sample is benchmark-heavy, but the count must not be reported as an estimate
of publication prevalence: works were selected for experiment-design relevance,
not by an exhaustive search and fixed inclusion protocol. It does establish the
narrower conclusion that accepted method papers exist and are not interchangeable
with benchmarks. It also shows why the SciTaste paper needs two separate related-
work views: methods explain what system mechanisms must be compared, while
benchmarks explain where and how those systems can be evaluated.

## Newly surfaced method and Taste precedents

- [AI Research Agents for Machine Learning: Search, Exploration, and
  Generalization in MLE-bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/328b81881da145412f2bc56c998dfb6a-Abstract-Conference.html)
  is a NeurIPS 2025 method paper. It formalizes research agents as search
  policies and studies operators with Greedy, MCTS, and evolutionary search on
  the already-existing MLE-bench. It belongs in the method lane, not in the
  benchmark lane.
- [Predicting Empirical AI Research Outcomes with Language
  Models](https://proceedings.neurips.cc/paper_files/paper/2025/hash/03f99ca79b87c513d0b502e737a41a41-Abstract-Conference.html)
  contributes both an outcome-prediction benchmark and a retrieval-plus-fine-
  tuned prediction system. It is especially relevant to Scientific Taste because
  it tests whether historical research evidence can improve idea prioritization
  before expensive execution.
- [Can LLMs Generate Novel Research Ideas?](https://proceedings.iclr.cc/paper_files/paper/2025/hash/ea94957d81b1c1caf87ef5319fa6b467-Abstract-Conference.html)
  is an accepted evaluation study with human ideation and blinded review. It is
  evidence for how to evaluate one early lifecycle stage, not a full autonomous-
  research method comparator.
- [ScienceAgentBench](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html)
  is an accepted benchmark of executable data-driven discovery tasks. It is a
  task/evaluation precedent, not a competing end-to-end method.

## Consequence for SciTaste

The comparison plan must maintain three separate inventories:

1. **method comparators**: systems whose mechanisms and executable artifacts can
   receive an equivalent task package under a matched policy;
2. **task and judge resources**: benchmarks, environments, rubrics, and human-
   calibration protocols; and
3. **design precedents**: accepted evidence that informs an estimand or protocol
   but is neither installed nor described as a direct baseline.

Hybrid papers must be decomposed at the artifact boundary. SciTaste may use
Scientist-Bench as a task source without claiming AI-Researcher ran, or adapt
AI-Researcher as a comparator only after its system artifact passes the normal
license, adapter, telemetry, model, and resource gates.

This correction does not freeze the ICLR 2027 experiment. A systematic method
census, exact executable comparator audit, and held-out task manifest remain
open. The UI must display this limitation before showing contribution counts.
