# AI-only grounded Taste abstraction review

This path removes a human-return dependency from the operational Track-A pilot
without turning an AI judgment into human or expert validity evidence. It links
an executed grounded-abstraction `BATCH.json` to two blind AI reviews and, only
when they disagree or report uncertainty, one identity-distinct AI
adjudication.

## Evidence boundary

`ai-abstraction-review-prepare` verifies the complete model-node ledger before
it creates reviewer requests. An item is admitted only when all of the following
hold:

- the ledger outcome and typed grounded-abstraction result are `accepted`;
- the entry is a verified live or local model generation;
- project, run, revision, node, profile, provider, model, runtime configuration,
  request fingerprint, and source projection match the batch plan;
- the exact raw recording hash and the deterministic grounding checks pass.

For every admitted item the bridge materializes an accepted-result copy and a
runtime receipt derived from the already verified ledger entry. This derivation
does not claim another provider call. The bridge binds both files, the original
ledger entry, raw recording, runtime configuration, source projection, and all
relevant hashes in `BRIDGE.json`.

Rejected, failed, planned, and missing entries are recorded as exclusions and
are never exposed to reviewers. A failed entry retains its archived failure
receipt, backend-started observation, and unknown-cost state where applicable.
The bridge also reports accepted source-domain and decision-family coverage.

Current natural-pilot sources do not yet bind Reference Quality qualification.
Accordingly, bridge and final-review outputs authorize only pilot operations;
they do not authorize formal benchmark admission, retrieval, training, or a
human-validity claim.

## Commands

Prepare the evidence bridge and the two identity-distinct primary requests:

```bash
scitaste evaluation ai-abstraction-review-prepare \
  --locator-root . \
  --outputs-root outputs \
  --batch outputs/projects/<project>/runs/<run>/taste_abstraction/<batch>/BATCH.json \
  --protocol configs/evaluation/pilots/scitastebench_track_a_ai_abstraction_review_v1.yaml \
  --output outputs/projects/<project>/runs/<run>/taste_abstraction-review/<review>
```

The command performs no model, API, GPU, human-contact, or experiment action.
The provider or agent that produces each response must consume the exact request
under `review-pack/requests/` and return the required structured JSON. Provider
API/local-model receipts must describe an actually observed successful
execution; they cannot be synthesized from a response file.

When a Codex agent is deliberately used as a reviewer, the protocol identity
must truthfully use an agent-labelled provider. Import its exact structured
response as an agent execution, not as an API receipt:

```bash
scitaste evaluation ai-abstraction-review-agent-import \
  --request <request.json> \
  --raw-response <agent-response.json> \
  --agent-session-id <session-id> \
  --agent-runtime <runtime-containing-codex> \
  --started-at <timezone-aware-iso-time> \
  --completed-at <timezone-aware-iso-time> \
  --output <agent-receipt.json>
```

The imported receipt has `provider_kind=agent`,
`agent_execution_observed=true`, `model_call_observed=false`, and
`exact_model_identity_verified=false`. It is hash-bound evidence that the agent
returned the file; it is not evidence of a provider HTTP call or independently
verified underlying model identity.

After two exact responses and receipts exist, lock them before any adjudicator
sees work:

```bash
scitaste evaluation ai-abstraction-review-primary-lock \
  --pack <review-pack> \
  --raw-response <primary-a.json> --raw-response <primary-b.json> \
  --execution-receipt <primary-a-receipt.json> \
  --execution-receipt <primary-b-receipt.json> \
  --output <primary-lock-dir>
```

The lock creates an adjudication request only if the two primaries disagree or
return `needs-dispute`. That request contains all and only disputed items and no
primary opinions. Import or bind the third AI result under the same rules, then
finalize:

```bash
scitaste evaluation ai-abstraction-review-finalize \
  --primary-reviews <primary-lock-dir> \
  --adjudication-raw-response <third-ai.json> \
  --adjudication-receipt <third-ai-receipt.json> \
  --output <accepted-set.json>
```

Omit both adjudication arguments when the primary lock has no disputes. A
partial pair, unresolved dispute, extra adjudication, identity mismatch,
response/request mismatch, or altered evidence fails closed.

## Interpretation

This workflow replaces a blocking manual operation with a reproducible AI-only
gate. Every request, response, execution/import receipt, normalized row,
dispute, and final decision is content-addressed. All public models retain
`reviewer_kind=ai`, `not_human_review=true`, and an explicit prohibition on
human/expert validity claims. Independent human evaluation remains a different
endpoint if it is later needed for construct validity or paper claims.
