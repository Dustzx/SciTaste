# Qwen3-VL-4B local RTX 3090 smoke run

This record contains aggregate facts and hashes only. Exact prompts, responses,
and generated reports remain under ignored `outputs/`.

## Run contract

- Date: 2026-09-03 (Asia/Shanghai)
- GPU: NVIDIA GeForce RTX 3090, 24,576 MiB
- Model: `Qwen/Qwen3-VL-4B-Instruct`
- Upstream revision: `ebb281ec70b05090aa6165b016eac8ec08e71b17`
- Runtime: PyTorch `2.5.1+cu121`, Transformers `4.57.6`
- Backend: direct local Transformers, text-only, greedy decoding
- Suite: `scitastebench-independent-smoke`, version `1.0`
- Conditions: Base and Full SciTaste
- Seed: `7`
- Calls: 16 fixed-candidate judgments; 8 headline cases per condition
- Semantic attempts: 16 total (one per call)

The checkpoint was read from an existing local path. The backend used
`local_files_only=True` and did not contact a model provider.

## Aggregate result

| Metric | Base | Full SciTaste |
|---|---:|---:|
| Pairwise accuracy | 1.000 | 1.000 |
| Expert agreement | 0.895 | 0.895 |
| Mean confidence | 0.9375 | 0.94625 |
| Brier score | 0.005 | 0.002988 |
| Expected calibration error | 0.0625 | 0.05375 |
| Wrong-level decision rate | 0.000 | 0.000 |

Paired outcomes were 0 improvements, 0 regressions, and 8 unchanged because Base
already selected all eight preferred actions. This is a ceiling-limited
connectivity and feasibility result, not evidence that augmentation is
ineffective or that Full SciTaste improves research outcomes.

Across all 16 calls, the backend consumed 3,752 input and 1,527 output tokens.
Aggregate backend latency was 51.62 seconds; median was 2.86 seconds, with a
2.23–9.21 second range. A preceding cold-cache single-call probe spent about 195
seconds loading checkpoint shards and used about 8.5 GiB of process GPU memory.
The benchmark then reused one resident model instance.

## Integrity

| Artifact | SHA-256 |
|---|---|
| Model config | `edac7703329133edfc53e46ac0081835144c99d7eebf28b71c732694d435224d` |
| Model index | `58a7841d7bff2548dd91577d216274a83cf1b500bc6a534b809d6c1b1707cf2b` |
| Model shard 1 | `30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9` |
| Model shard 2 | `046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6` |
| Local benchmark report | `4f942bf392ba51e28bcd159dce01a151d142952cbecfa6687b9596ed6eaeb69a` |
| Local exact recording | `626e492c7a779f5fb5529f7808701bb44c505eb4849e16bfc9ca4f518fa3eee0` |

The next effectiveness step needs harder, non-ceiling cases and repeated seeds.
This result does not represent a Phase 9 matched-budget system cell because it
does not execute a complete research workflow or include frozen search,
six-dimensional telemetry, real artifacts, and blinded external review.
