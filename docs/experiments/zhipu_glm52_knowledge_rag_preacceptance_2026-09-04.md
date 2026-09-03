# Zhipu GLM-5.2 Knowledge RAG preacceptance — 2026-09-04

## Status

The cross-provider engineering preacceptance cell succeeded through peer review.
This confirms that the existing OpenAI-compatible adapter can run the SciTaste
study pipeline against Zhipu while Bailian is unavailable. It is acceptance-only
evidence: the pilot-scoped result must not be mixed with the registered
Qwen3.8-Max comparison or used for a duration claim.

## Registered execution

- Protocol: `configs/experiments/matched_budget_study_zhipu_glm52_preacceptance_v1.yaml`
- Launcher: `configs/experiments/study_launchers_zhipu_glm52_preacceptance_v1.yaml`
- Provider endpoint: `https://open.bigmodel.cn/api/paas/v4`
- Model observed on every wire call: `glm-5.2`
- Protocol SHA-256: `43e0e87319c469c8d70378405bf56d10f0a078226e331ea2a27343e4c9ba10a2`
- Plan SHA-256: `aba320515433888880bebbe0cd6f894d08671d710ca6fb92d29650034e639265`
- Cell: `diagnosis-friendly-v1 × knowledge_rag`, seed 7,
  `cell-4a8c7e417934abf65578`
- Output root (Git-ignored):
  `outputs/zhipu-glm52-knowledge-rag-preacceptance-v1-2026-09-04/`

## Result

- Runner status: `succeeded`; real evidence; one executed experiment.
- Wire usage: 22 calls, 81,709 input tokens, 35,720 output tokens, 117,429 total
  tokens, all attributed to `glm-5.2`.
- Adapter-estimated API cost: USD 0.31478167. This is telemetry, not a Zhipu
  invoice and must not be treated as authoritative billing data.
- Selected primary aggregate: balanced accuracy 0.000000. All three registered
  synthetic decision rules reported 0.000000 for seeds 7, 19, and 31; this is a
  negative benchmark result, not a model-quality score.
- Outcome audit: evidence sufficiency 1.0, seven audited manuscript claims, zero
  unsupported claims, and 23 peer-review concerns left open at the registered
  Stage 18 endpoint.
- Packaged manuscript: 5,461 Markdown words; standalone Markdown, TeX,
  bibliography, three observed experiment charts, and a successfully compiled
  14-page PDF.

## Gate-driven repairs

The first pass completed the experiment and analysis stages, then stopped at the
pre-draft gate after 72,665 tokens. GLM-5.2 promised that the paper would include
a complete seed table but did not materialize the method-specific means and
standard deviations in the outline. The adapter now appends a deterministic
checkpoint made only from the source-verified selected-experiment matrix; it does
not create or change observations.

The resumed draft stopped at the pre-review gate after 105,052 tokens because it
referenced `charts/framework_diagram.png`, which did not exist. The adapter now
removes only unresolved local Markdown image markup and its adjacent caption.
Existing images are retained; remote or path-escaping images remain hard
failures. The already audited draft then continued directly to peer review to
avoid regenerating earlier stages.

Because this gate-driven continuation included a direct adapter resume between
runner invocations, its runner wall/GPU duration is not comparable with a
single-lifecycle cell. Token accounting is cumulative and complete.

## Artifact hashes

- `manuscript/main.md`: `27ebab8491be9f80c9308eb0d479dac2a2420af20b238e17d62783218e80df36`
- `manuscript/main.tex`: `01e3d1585dbd3e1b420bbe563e25d0e901544ae0ada8a8d0bff596a6693a02f7`
- `manuscript/main.pdf`: `23cc8861dc793ab47fc3ffff0e05a58eb751e91011ca13dfc46ce525f270cbd4`
- `manuscript/references.bib`: `e103d6d89367235c5c2ea94628892bf8e8719276c3ac03d8ac16ce1d9b91b869`
- `selected_experiment_evidence.json`: `0d9830091b14e07b74b21a032a2fc83719b453ecd2caee61faac67aa557dc6b9`
- `outcome_audit.json`: `1ef7caade99943c81061f675b3de15f6637629fb683cbbc773c7b222ec05da65`
- `execution_record.json`: `b6aad0903ca4d98288fd5ae3f63eb0735c8db6ead7eb98dbdef1b27c845ca153`
- `stage-18/reviews.md`: `745b69dc5894481305d59fdca97bacd34de7a1bd50e35084cbc4f34e0cbedd25`

## Remaining boundary

This run clears provider connectivity and one Knowledge RAG lifecycle. It does
not clear the four-condition preacceptance, the 48-cell matched study, external
blinded review, or publication-quality revision. A same-provider four-condition
pilot is the next useful portability check. The registered headline experiment
must later run every compared condition on the same frozen model/provider.
