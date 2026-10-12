# Zhipu GLM-5.3-Flash bounded-model-node engineering probe

Date: 2026-09-05  
Project: `scitaste-self-development`  
Evidence scope: engineering only  
Effectiveness claim: false  
Retrieval eligibility: false

## Question

Can the project-owned bounded-model-node path contact the real Zhipu general API,
retain the exact exchange before semantic parsing, resume safely after a failed
paid response, and enforce deterministic gates without promoting the model's
proposal?

This is a SciTaste self-development episode. It tests the tool-intelligence
implementation against its own project runtime; it is not evidence that the
model improves scientific outcomes.

## Registered execution

The executable configuration is
`configs/model_nodes/pilot_orchestration.zhipu_glm53_unpriced_probe.yaml`. It
contains six offline baseline/scripted/replay cases and one real
`live_structured_node` case. Provider and model are pinned to
`zhipu-direct/glm-5.3-flash`, retries are zero, and the key is resolved only from
`ZAI_API_KEY` at invocation time.

The official API accepted the model on the general prepaid Chat Completions
route. A preflight call also established that this model rejects disabled
thinking; the working payload pins enabled thinking with low reasoning effort.
No verified account-route rate was available, so the run deliberately used
`unpriced_engineering_probe=true`. This makes missing cost telemetry a mandatory
rejection and prevents acceptance by construction.

## Failed run retained

Run `2026-09-05__zhipu-glm-5.3-flash__model-node-probe-01` is retained with
status `failed`. Its first online failure occurred before project-level HTTP
retention was implemented. Resume then captured and archived the provider
exchange under the failed attempt:

- provider model: `glm-5.3-flash`;
- finish reason: `length`;
- usage: 1,001 input + 512 output = 1,513 tokens;
- raw-response SHA-256:
  `39a99cf58d8d7e2fd7fa0158518ddcfe62b8df42d0639156e7f1ebdc168a32cc`;
- archived recording SHA-256:
  `1996c2a92f23c186b67f65dad84ff1e0283ff4db4414e7bd1501cd99d6169634`.

Because the 512-token ceiling truncated the structured result, the configuration
was not modified under the same run identity. A new content-addressed run raised
only the transport output ceiling to 2,048 tokens.

## Completed engineering run

Run `2026-09-05__zhipu-glm-5.3-flash__model-node-probe-02` completed seven of
seven cases with no planned-only case:

| Field | Observed |
|---|---:|
| Invoked cases | 5 |
| Accepted / rejected / not applicable | 4 / 1 / 1 |
| Schema-valid invoked cases | 5 / 5 |
| Input / output / total tokens | 1,020 / 602 / 1,622 |
| Total latency | 16,033.033 ms |
| Exact replay coverage | 1.0 |
| Gate bypasses / unbounded tool calls | 0 / 0 |
| Measured cost | unavailable |

The real case alone used 1,001 input and 587 output tokens and ended normally.
Its JSON passed the typed schema, but the deterministic node rejected it for
input/output/total token ceilings, unavailable cost, latency, and the
unallowlisted `ADD_ANALYSIS` action. That last proposal produces one
unsupported-reference/action safety failure; it is evidence that the gate
worked, not a successful semantic-node result.

The final report is blocked by missing external manual-intervention
measurements, incomplete price/cost telemetry, and missing independent outcome
review. It is not acceptance evidence.

## Integrity anchors

- protocol SHA-256:
  `64ed26df3f05949711430759b4b391125b50201c304b2875485b3ce9e8b7a5d8`
- orchestration configuration SHA-256:
  `384afc1104f9ee98fae2bb9334918d7fe0fdb0d95b36a399081825deca97dc0e`
- live recording file SHA-256:
  `457b1c7a9377165728a5802e6ede552d2d57a7b0406ed45dcacf0c5bfa7d5304`
- report SHA-256:
  `c7777c790f6b37e654aa48d079176ac20ea340e2dce12e165774fb03694c7cb3`
- verification SHA-256:
  `2528e4f8bdf9ebd009946f0f2fe1996d226a1fbdac6183409b2f7a7412fa0781`

Generated request and response bodies remain in the ignored project directory;
they are not copied into Git. Authorization headers and key values are absent
from both recordings and CLI summaries.

## Outcome and next gate

The adapter, real-provider compatibility, exact exchange retention, failed-
attempt archive, checkpoint hashing, and deterministic rejection boundary are
now exercised on a real response. ADR-022 remains proposed. Promotion requires
a fresh registered comparison with verified pricing, realistic per-node budgets,
external manual-intervention measurements, zero unsupported-action increase,
and independent outcome review.
