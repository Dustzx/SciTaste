# API provider strategy

Verified: 2026-09-05. Prices and model availability change; always re-check the
linked official page before purchasing credits or fixing an experiment manifest.

## Recommended deployment

1. **Primary development — Alibaba Cloud Model Studio (Bailian/Qwen).** It has
   domestic billing and region-specific endpoints, and supports OpenAI-compatible
   APIs. Start with a balanced Qwen model and record every response for replay.
2. **Low-cost independent judge — DeepSeek official API.** Use it for divergent
   generation, stress tests, and a second reviewer. Keep it independent from the
   primary model to reduce same-model confirmation bias.
3. **Frontier reference evaluator — OpenAI official API, only from a supported
   country/territory and compliant account/deployment.** Prefer the Responses API.
   Use a balanced model for routine judgments and a flagship model only for a
   small, pre-registered hard subset.
4. **Optional broad comparison — Gemini direct.** Its official OpenAI-compatible
   endpoint lowers integration cost; direct native APIs remain preferable when a
   provider-specific feature is required.
5. **Exploration only — OpenRouter.** It is useful for quickly comparing many
   models, but an intermediary changes routing, billing, availability, and data
   governance. Pin the provider, disable fallback, and deny data collection for
   reproducible experiments. Move final paper baselines to direct vendor APIs.

## Procurement and connection matrix

| Route | SciTaste role | Advantages | Main constraint | Current adapter |
|---|---|---|---|---|
| Alibaba Cloud Model Studio direct | default primary in mainland China | domestic account/billing, regional endpoints, Qwen catalog | endpoint and key are region-specific | OpenAI-compatible |
| DeepSeek official direct | low-cost second model/reviewer | simple compatible endpoint and a distinct model family | capacity and model aliases can change | OpenAI-compatible |
| OpenAI official direct | frontier reference in supported regions | Responses API, Batch, strong model tiers | mainland China is not on the official supported-country list | OpenAI-compatible Responses |
| Gemini API direct | cross-family comparison | official OpenAI compatibility and Batch pricing | Google account/region/data terms | OpenAI-compatible |
| Zhipu BigModel/Z.ai direct | bounded model-node pilots and independent comparison | domestic general API, GLM-5.3-Flash, compatible request shape | Coding Plan and prepaid balance use different endpoints and terms | OpenAI-compatible |
| Anthropic direct | optional independent critic | strong long-context reviewer family | native Messages behavior differs from the current adapter | native adapter still pending |
| OpenRouter | short-lived model scouting | one interface for many providers | intermediary routing, privacy, and reproducibility | OpenAI-compatible, provider pinned |
| Local open-weight runtime | confidential or zero-marginal-call experiments | data stays under project control | hardware, serving, and model quality | direct text-only Transformers or any compatible server |

For a university or company deployment, buy credits/contracts from the model
vendor or its named cloud platform under the institution's account. Do not buy a
shared key from a marketplace seller. A cloud reseller is acceptable only when
it is an authorized contracting route and the actual provider/model, retention,
region, and subprocessors are documented.

## Recommended rollout

1. Develop with `scripted` and `replay`; no account is needed.
2. Create one direct Bailian account and a project-scoped key with a small spend
   cap. Run the five-case calibration and record it.
3. Add a direct DeepSeek key only for cross-model review and robustness checks.
4. If the deployment and billing entity are in an OpenAI-supported region, run a
   small pre-registered reference subset through the Responses API. Do not route
   around regional restrictions.
5. Add Gemini or Claude only when model-family diversity materially improves the
   experiment. More vendors also mean more data-processing agreements and more
   reproducibility work.

The live command is always explicit:

```bash
scitaste taste calibrate \
  --backend openai-compatible \
  --config configs/backends/bailian.example.yaml \
  --suite configs/taste/intrinsic_calibration_v1.yaml \
  --record outputs/bailian/recording.jsonl \
  --output outputs/bailian
```

For the bounded-node GLM-5.3-Flash engineering probe, the provider currently
requires thinking to remain enabled. The committed compatible payload uses
`thinking.type=enabled` plus `reasoning_effort=low`. Its deliberately unpriced
mode can verify transport/schema behavior but always fails the cost gate; do not
reuse it for an acceptance or matched-cost claim.

The same provider can be exercised inside the normal project workflow with
`configs/workflows/full_zhipu_model_advisory_probe_v1.yaml`. A real execution
also requires `scitaste run full --allow-live-model-nodes`; dry-run reports both
gates without reading the key or contacting the endpoint. The 2,048-token value
in this engineering backend is a ceiling for that bounded semantic request, not
a global limit on SciTaste coding, experiment or manuscript workloads.

An existing local Qwen checkpoint can instead run without a server or API key:

```bash
export SCITASTE_LOCAL_MODEL_PATH=/absolute/path/to/Qwen3-VL-4B-Instruct
scitaste taste calibrate \
  --backend local-transformers \
  --config configs/backends/local_transformers_qwen3vl4b.example.yaml \
  --record outputs/local-qwen/recording.jsonl \
  --output outputs/local-qwen
```

The direct backend uses local files only, greedy decoding, and a pinned upstream
revision. It deliberately exposes only text decisions even when the checkpoint
also supports vision.

For Phase 7 visual-taste connectivity, replace the suite with
`configs/taste/visual_calibration_v1.yaml`. The committed Bailian example pins
`qwen3.8-max`; confirm account entitlement and current provider availability
before a new run because model aliases can change.

Avoid unregistered resellers or shared-key relay services. They obscure model
version, token accounting, retention, rate limits, and legal responsibility—the
exact variables SciTaste needs to log and control.

## Architecture rules

- Secrets are environment variables; YAML stores only the environment-variable
  name.
- Capture provider, exact model ID, endpoint style, request fingerprint, seed,
  token usage, latency, and raw response hash in every run.
- Use `RecordingBackend` on the first live run and `ReplayBackend` for tests and
  deterministic analyses.
- Do not silently fail over during benchmarks. A fallback model is a different
  experimental condition.
- Keep per-project spending caps and a provider allowlist.
- Redact unpublished paper text, reviewer data, credentials, and personal data
  unless the selected provider contract explicitly permits the transfer.

## Official references

- OpenAI: <https://developers.openai.com/api/docs/guides/latest-model>
- OpenAI supported regions: <https://developers.openai.com/api/docs/supported-countries>
- OpenAI Batch API: <https://developers.openai.com/api/docs/guides/batch>
- Alibaba Cloud Model Studio: <https://help.aliyun.com/zh/model-studio/what-is-model-studio/>
- Alibaba model pricing: <https://help.aliyun.com/zh/model-studio/model-pricing>
- DeepSeek pricing: <https://api-docs.deepseek.com/quick_start/pricing>
- Gemini OpenAI compatibility: <https://ai.google.dev/gemini-api/docs/openai>
- Gemini pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Anthropic API overview: <https://docs.anthropic.com/en/api/overview>
- OpenRouter privacy and routing: <https://openrouter.ai/docs/guides/privacy/data-collection>
- Zhipu/Z.ai model connection and endpoint guidance: <https://zcode.z.ai/cn/docs/configuration>
- Zhipu OpenAI-compatible API: <https://docs.bigmodel.cn/cn/guide/develop/openai/introduction>
- Zhipu thinking configuration: <https://docs.bigmodel.cn/cn/guide/capabilities/thinking>
