# GLM-5.3-Flash native-code generation engineering probe

Date: 2026-09-07

This run tested the new provider-to-proposal boundary, not scientific
effectiveness. It used the project-owned Full Workflow configuration
`configs/workflows/full_zhipu_glm53_flash_code_generation_probe_v1.yaml`, a
fresh temporary outputs root, explicit live authorization, and a credential from
the ignored `ZAI_API_KEY` environment variable.

## Provider observations

- The authenticated `/models` endpoint returned `glm-5.3-flash` as an available
  model ID.
- A request attempting `thinking.type=disabled` returned HTTP 400/provider code
  `1210`: this model requires thinking and accepts a reasoning effort instead.
- The committed condition therefore uses `thinking.type=enabled` and
  `reasoning_effort=low`.
- That request returned HTTP 200 in 15,781.86 ms with provider identity
  `zhipu-direct/glm-5.3-flash`, 1,260 input tokens, and 935 output tokens.
- The exact decoded response is retained only in the ignored temporary run. Its
  raw-response SHA-256 is
  `3457bbf77ec790d212fbe1b5a92d90923320388d95eb18b7e2da992050b3cb0d`; the
  recording SHA-256 is
  `7c1050992aa740c2d0932edcdd280f87ecc84f8bc6efe6a7c3faccff357c454b`.

The provider's authenticated model list establishes availability, not pricing.
The current public [Zhipu product pricing](https://bigmodel.cn/pricing) and
[Z.AI pricing overview](https://docs.z.ai/guides/overview/pricing) did not list a
GLM-5.3-Flash token rate at the time of the run. The condition therefore remained
an explicit unpriced engineering probe.

## Gate result

The response satisfied the outer structured-output schema and included all
three registered metric names plus the SciTaste measurement marker. The runtime
still rejected it before source materialization because API cost telemetry was
not derivable from confirmed rates. Independent read-only inspection of the
retained untrusted payload found:

- 2,663 UTF-8 source bytes;
- source SHA-256
  `905f9ae762f3cad45224cad18fcda68abaed5ea03ad007c9f88314dd5c066229`;
- invalid Python at line 1: the proposal began with an empty `import` statement.

Consequently no `generated.py`, deterministic admission context, admitted source,
experiment process, workflow stage, or paper was created from this live response.
This is the intended boundary: schema-valid model content is neither valid code
nor execution authority.

An earlier call began but produced no complete recording. It was recorded as a
failed unknown-cost attempt and was not resumed or retried under the same
invocation. Later diagnostics used fresh project/run identities.

## Acceptance meaning

Accepted evidence:

- authenticated model discovery;
- real Chat Completions transport;
- structured response parsing;
- exact request/response/usage recording;
- cost-gate rejection before source publication;
- malformed-source observability without execution.

Not accepted:

- provider pricing or total cost;
- live source-code admission;
- live isolated execution;
- automatic repair;
- scientific validity, quality gain, or matched efficiency.
