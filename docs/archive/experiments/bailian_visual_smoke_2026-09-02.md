# Bailian visual-taste calibration smoke run

This manifest contains aggregate results and hashes only. API credentials,
request recordings, raw responses, and case rationales are not committed.

## Run contract

- Date: 2026-09-02 (Asia/Shanghai)
- Provider: Alibaba Cloud Model Studio, mainland China compatible endpoint
- Model: `qwen3.8-max`
- Backend style: OpenAI-compatible Chat Completions with JSON mode
- Suite: `scitaste-visual-smoke`, version `1.0`
- Seed: `7`
- Cases: 5 fixed-candidate visual-taste judgments
- Retrieval: disabled (intrinsic calibration)
- Semantic attempts: `[1, 1, 1, 1, 1]`
- HTTP result: five successful responses

## Aggregate result

| Metric | Value |
|---|---:|
| Accuracy | 1.000 (5/5) |
| Mean confidence | 0.952 |
| Brier score | 0.00256 |
| Expected calibration error | 0.048 |
| Input tokens | 1,131 |
| Output tokens | 1,043 |
| Mean request latency | 6,143.63 ms |
| Minimum / maximum latency | 5,126.55 / 8,067.77 ms |

The cases cover contract-before-render, editable reconstruction, misleading
emphasis, visual overclaim, and panel density. This is a connectivity and protocol
smoke run, not a statistically sufficient estimate or model comparison.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| Local exact recording (ignored by Git) | `3462f7f20c60d0746d99488f80274cbe4c7d201960842c8803ae9e24ff82d471` |
| Local calibration report (ignored by Git) | `5bb4dfcf5e7552874c6cd5ba1c781d3990257bf07c0636112dc16571a00b6785` |
| Visual calibration suite | `8ebe6d9d2a4e6c8eac0756399fbf438322d5ba2799d1db2e22d2ea2208e305ea` |
| Backend configuration | `0a1bf6f1a393b2529165a8a175029d2e93817266ec7ad612a446df101c308ad6` |

All five responses satisfied the JSON contract on their first semantic attempt;
no provider or model fallback was used. An offline exact replay reproduced every
selection, confidence, rationale, usage count, and response hash; only the
expected backend/cache metadata differed.
