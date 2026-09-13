# Hosted-model identity for formal evidence

SciTaste treats a hosted model as a time-bounded experimental stratum, not as
the text written in an API `model` parameter. This matters because a provider
can retain one callable alias while changing the served model. Rejecting every
rolling alias would make realistic API evaluation impossible; silently calling
the alias an immutable checkpoint would make the evidence irreproducible.

The current no-run protocol is
`configs/evaluation/model_identity/iclr2027_api_identity_v3.yaml`. It requires:

- an identity-only, task-excluded sentinel before and after every window;
- another sentinel after a bounded number of calls;
- exact endpoint, interface, requested and returned model, request ID,
  timestamps, request/response hashes, status, and usage capture;
- raw request and response retention;
- immediate window closure when identity is missing or changes; and
- separate analysis strata across windows, revisions, and providers, with no
  pooled confirmatory estimate.

DeepSeek and Zhipu currently have different evidence:

- DeepSeek's current official catalog names callable ID `deepseek-v4-flash` and
  family `DeepSeek-V4-Flash`. Catalog v6 binds its current public tariff. The
  earlier `deepseek-flash` / `DeepSeek-V4.1-Flash` snapshot remains historical
  evidence only. A formal window still needs an explicitly approved
  authenticated start/end attestation.
- Zhipu's official page names callable ID `glm-5.3-flash`, but does not disclose
  an immutable served revision or an exact machine-readable API tariff on that
  page. It therefore uses a shorter temporal-only stratum and remains ineligible
  for pilot approval until an exact price ceiling is independently bound.

An authenticated historical call is availability evidence only. It cannot open
a future formal window, and the conformance pilot and formal study must use
different windows. Candidate selection happens before formal outcomes; pilot
content cannot enter the formal test.

The protocol and activation compiler authorize no API call. A later live pilot
must be a separate hash-bound owner-approved transaction with an exact request,
request/token/cost ceilings, credential binding, and abort behavior.

For that later transaction, `ApiIdentityWindowAttestation` is the closed receipt
contract and `inspect_api_identity_window` is the admission boundary. The
verifier rejects an overlong window, non-bracketing sentinel timestamps,
unapproved returned identity, provider/interface drift, failed calls, reused
request IDs, template drift, and excessive calls between sentinels. An admitted
conformance window establishes only API identity; it never establishes
scientific effectiveness or formal-study eligibility.
