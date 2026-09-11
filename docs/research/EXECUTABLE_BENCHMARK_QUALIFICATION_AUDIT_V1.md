# Executable benchmark qualification for the ICLR 2027 evidence stack

Status: **metadata scope accepted for author review; no repository clone, task-data
download, environment creation, API call, GPU work, or experiment is authorized**.

Audit date: 2026-09-12. The machine-readable candidate is
[`configs/evaluation/candidates/mlrc_3090_objective_progress_v1.yaml`](../../configs/evaluation/candidates/mlrc_3090_objective_progress_v1.yaml).
It is checked against the v7 external-resource corpus and the shared v2 compute
catalog. The CLI treats every unverified license, asset, environment, provider,
host, and hidden-test condition as a blocker rather than filling it with a
surrogate.

## Decision

Use **MLRC-Bench** as the first objective-progress source to qualify. Its
[accepted NeurIPS 2025 paper](https://proceedings.neurips.cc/paper_files/paper/2025/hash/82c96f3c90741ef2c9b248e65d9b5db0-Abstract-Datasets_and_Benchmarks_Track.html)
evaluates repository-level proposal and implementation work with task-defined
objective metrics and reports seven research competitions. This directly tests
whether Scientific Taste produces ideas that survive implementation, rather
than only sounding preferable to a judge.

The current 8×RTX 3090 host does **not** make all seven tasks comparable to the
published protocol. Four tasks were run on one 16 GB device in the paper and
fit the registered 24 GB-per-device guarantee. Three were run on one 48 GB
device and remain excluded. Combining memory across two 3090 cards without an
upstream distributed contract would change the task semantics.

The four-task slice is therefore **transfer-and-mechanism evidence**, not the
whole paper and not a population-level proof. The headline ICLR claim still
requires the decision benchmark, complete idea-to-paper packages, accepted
external-system comparisons, ablations, independent expert review, and the
negative/mismatched-Taste control defined in the main evaluation contract.

## Candidate comparison

| Resource | Archival status | What it actually tests | Executable status for current resources | Assigned role |
|---|---|---|---|---|
| [MLRC-Bench](https://github.com/yunx-z/MLRC-Bench/tree/0d26417034811d2d4587646c4520cc305ea09dd6) | NeurIPS 2025 Datasets & Benchmarks | research method proposal and implementation against objective competition metrics | four 16 GB tasks are capacity-compatible; assets/environments remain unqualified | primary objective-progress source |
| [EXP-Bench](https://github.com/Just-Curieous/EXP-Bench/tree/401573342845fe24963d4384e6849d53f046dd23) | ICLR 2026 | hypothesis-to-conclusion experiment integrity over 461 tasks | dataset metadata is public, but source-environment reproduction is not yet closed | secondary experiment-integrity lane |
| [MLGym](https://github.com/facebookresearch/MLGym/tree/9d40c1b5035202018cd7091fb4e83a9c68b377c0) | COLM 2025 | baseline improvement across 13 ML/game tasks | several low-cost tasks are plausible; primary code is CC-BY-NC and multi-GPU tasks require separate audit | development/stress lane, not title evidence |
| [InnovatorBench](https://github.com/GAIR-NLP/InnovatorBench/tree/934ead34675a0fc610618094dabeaf7bdcb44818) | ICLR 2026 | long-horizon research engineering across 20 tasks | most tasks declare 8×80 GB GPU and very high RAM; the few lighter tasks require external services or contain unresolved config issues | defer under current hardware |
| [InnoGym](https://proceedings.iclr.cc/paper_files/paper/2026/hash/743514dfa1ef705f378424bd1effb57b-Abstract-Conference.html) | ICLR 2026 | performance gain plus extracted/judged novelty on 18 tasks | the official repository URL stated by the paper was unavailable during this audit | metric/design precedent only |

Benchmark and method contributions remain separate. These resources can supply
tasks, environments, metrics, or design precedent; their bundled agents do not
become external method comparators without an independent unchanged-core,
license, model, task, telemetry, and artifact audit.

## Exact MLRC-Bench candidate

The upstream code identity is the official `yunx-z/MLRC-Bench` repository at
commit `0d26417034811d2d4587646c4520cc305ea09dd6`. The separate official
[Hugging Face metadata package](https://huggingface.co/datasets/yunx-z/MLRC-Bench/tree/6ba0e2efb8397879ff5390335c6ba36482a66831)
is pinned at `6ba0e2efb8397879ff5390335c6ba36482a66831` and must not be
mistaken for the executable task assets.

| Accepted task | Paper device memory | Paper test ceiling | Current qualification |
|---|---:|---:|---|
| Temporal Action Localisation | 16 GB | 0.5 h | first preflight candidate; Apache-2.0 attribution is present, but nine Google Drive assets have no locally verified hashes and the environment has not been reproduced |
| Machine Unlearning | 16 GB | 0.5 h | blocked; Kaggle terms, credentials, CASIA-SURF test access, and manual notebook submission are unresolved |
| Next Product Recommendation | 16 GB | 0.5 h | blocked; the preparation script requires interactive AIcrowd login and competition data/ground-truth terms are unresolved |
| Cross-Domain Meta Learning | 16 GB | 3.5 h | first preflight candidate; the 30 OpenML Meta-Album records report CC BY-NC 4.0, but exact files and the environment are not yet content-bound locally |
| LLM Merging | 48 GB | 1 h | excluded: single-device memory exceeds every registered 3090 |
| Backdoor Trigger Recovery | 48 GB | 0.5 h | excluded: single-device memory exceeds every registered 3090 |
| Rainfall Prediction (`weather_forcast` upstream path) | 48 GB | 0.5 h | excluded: single-device memory exceeds every registered 3090 |

The first rational acquisition proposal should cover only Cross-Domain Meta
Learning and Temporal Action Localisation. It must enumerate every URL,
destination, size ceiling, expected hash where upstream supplies one, license,
and redirect policy. Where upstream does not publish a hash, acquisition may
record observed bytes but cannot claim an upstream checksum. Machine Unlearning
and Next Product Recommendation require a separate owner decision about platform
terms and interactive credentials.

## Matched causal slice

The candidate binds the same `deepseek-flash` / `DeepSeek-V4.1-Flash` API
resource across three SciTaste Native conditions:

1. Base without Taste;
2. Full SciTaste;
3. Full pipeline with deliberately mismatched Taste precedents.

For planning, four tasks × three conditions × three seeds gives 36 internal run
units. The five-hour agent ceiling gives a conservative 180 GPU-hour bound,
below the existing 192 GPU-hour cap. This number is accounting metadata, not a
claim that repetition count implies rigor. The task is the sampling unit;
uncertainty is estimated across task effects, seeds quantify within-task
stability, and the formal analysis must show every task rather than only an
aggregate. The four-task slice cannot authorize a broad task-population claim.

Zhipu GLM-5.3-Flash is reserved for a separately powered provider-robustness
study after the primary design is frozen. Pooling it with DeepSeek would
confound method and provider effects. Qwen3-VL-2B remains a local runtime and
small-model robustness resource, not the frontier controller for this MLRC
comparison.

## Current machine result

`scitaste evaluation executable-candidate` currently establishes:

- seven accepted tasks form one exact selected/excluded partition;
- four selected tasks fit the registered 24 GB-per-device guarantee;
- three excluded tasks require an additional 48 GB single-device resource;
- Temporal Action Localisation and Cross-Domain Meta Learning are the only
  first-preflight candidates;
- metadata review is ready, while acquisition, local preflight, and experiment
  readiness are false;
- download, API, GPU, and execution authority are all false.

Any candidate-file, benchmark commit, resource-corpus, compute-catalog, memory,
status, or report-byte drift fails closed.
