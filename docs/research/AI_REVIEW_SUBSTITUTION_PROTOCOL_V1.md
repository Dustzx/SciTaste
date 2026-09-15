# AI review substitution protocol v1

Status: **active operational policy; AI/nonhuman evidence; no external execution
authorized**.

The owner instructed SciTaste on 2026-09-15 to replace currently manual review
work with independent agents. The machine-readable amendment is
[`iclr2027_scitaste_ai_review_amendment_v1.yaml`](../../configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml).
It is a typed, self-hashed panel contract
(`58d9e82db0e39163c6f42ac4909ee6e19f2549c22b8fa0d940dfe19a7dac6b94`)
that binds, but does not silently mutate, lifecycle evidence program v2.
The central lifecycle evidence-review package binds the amendment's exact file,
semantic contract hash, and base-program identity; AI admission additionally
requires that expected authority hash rather than accepting a free-standing
self-signed contract.

## What agents now replace

Two condition-blinded AI roles independently review each Taste episode's
decision trace, alternatives, delayed outcome, causal-credit proposal, transfer
scope, and reversal probe. A third role sees a disagreement packet only when
the primary roles split. The same separation applies to internal paper red-team
and protocol audits. Primary roles must use distinct model identities as well
as distinct reviewer, run, and raw-response identities. Every review records
the provider, exact model revision, prompts, sampling configuration, reviewer-
visible packet, raw response, normalization report, execution receipt, and a
replayable claim-leakage firewall report.

The repository contract
`AITasteEpisodeAttributionReview` allows these disclosed reviews to admit an
episode for policy training only when the exact panel contract and every bound
artifact byte are supplied. Admission reports distinguish `ai`,
`legacy-unverified`, and `mixed` evidence. The identity is persisted in both
the admitted episode and fitted policy; `human_validity_claim_allowed` remains
false. The legacy review type's `human_performed=true` is treated as an
unverified historical self-attestation, never as human-validity evidence.

## Scientific interpretation

This substitution removes the staffing dependency but changes the estimand.
H1, H2, H2b, and the decision-level portion of H3 become AI-panel and natural-
outcome proxy results. They may report agreement, calibration, abstention,
transfer errors, reversals, and sensitivity across independently run models.
They may not be called human preference, expert agreement, or expert-aligned
scientific quality.

H4 remains the strongest title-level evidence because its primary endpoint is
owned by held-out executable-task scorers rather than a reviewing agent. Under
the AI-only route the stronger “Improving Autonomous Research through
Scientific Taste” title remains frozen even if proxy H3 and objective H4 are
positive, because those results do not independently establish the Scientific
Taste construct. The active title is “SciTaste: Grounded Scientific Taste for
Autonomous Research.” A later independent construct-validation study may
change that boundary prospectively.

SciTasteBench under this route is an AI-reviewed natural research instrument,
not a human-validated benchmark. Independent human validation can be added
later without reinterpreting the AI-only run.

## Agent firewall

For each candidate:

1. A and B receive identical evidence bytes, prompts, rubric, and sampling
   configuration but execute with distinct model and run identities.
2. Neither sees condition identity, the other response, formal held-out
   outcomes outside the attribution window, or paper claims.
3. Deterministic code re-hashes every required artifact, validates the firewall
   report, checks packet equality, contract identity, model/run separation,
   response non-duplication, producer conflict, and contradictions before
   admission.
4. C receives only the bound disagreement packet and cannot override a
   deterministic integrity blocker.
5. Raw responses, normalized records, prompt/model identity, token/cost receipt,
   and all vetoes are retained, including failures.

The AI panel can replace operational review effort. It cannot create human
construct validity by declaration.
