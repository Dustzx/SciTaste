# Bailian intrinsic calibration smoke run

This manifest contains aggregate results and hashes only. API credentials,
request recordings, and raw model responses are not committed.

## Run contract

- Date: 2026-09-02 (Asia/Shanghai)
- Provider: Alibaba Cloud Model Studio, mainland China compatible endpoint
- Model: `qwen3.7-plus`
- Backend style: OpenAI-compatible Chat Completions with JSON mode
- Suite: `scitaste-intrinsic-smoke`, version `1.0`
- Seed: `0`
- Cases: 5 fixed-candidate judgments
- Retrieval: disabled (intrinsic mode)
- Semantic attempts: `[1, 1, 1, 1, 1]`

## Aggregate result

| Metric | Value |
|---|---:|
| Accuracy | 1.000 |
| Mean confidence | 0.956 |
| Brier score | 0.00208 |
| Expected calibration error | 0.044 |
| Input tokens | 932 |
| Output tokens | 2,494 |

Each of Idea, Experiment, Evidence, Writing, and Review contains one case and was
correct. This is a connectivity and calibration-pipeline smoke run, not a
statistically sufficient model comparison.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| Local exact recording (ignored by Git) | `9274f6eef850455ae1cf49bf66cbe1536302f07ed3a72e15f2014001881575e1` |
| Local calibration report (ignored by Git) | `804f30d6a3871fd722279fd5de77546e93a867f5dbca9255258afc5238b555ef` |
| Calibration suite | `c8ae322614bdc7b8a2baefb6c1b0b8b1daee6f4c905818f211b8d258cac08cad` |
| Backend configuration | `447a4926577ecebe069c44904e9e243ffada65f634838d23a237cc1098de3e9a` |

One preliminary run returned a schema-incomplete response for a Writing case.
That run was excluded, and the backend was hardened with bounded semantic-format
repair retries before this clean run. Transport and semantic retries remain
visible rather than silently changing model or provider.
