# Matched-budget formal preacceptance: diagnosis/base

Date: 2026-09-03

## Scope

This was a real, paid Qwen3.8-Max execution of one formal-protocol cell, not a
scripted fixture or a local smoke test. It used task `diagnosis-friendly-v1`,
condition `autoresearchclaw`, seed 7, the frozen search snapshot, and the pinned
unmodified AutoResearchClaw commit
`12d3fd809fa9658e91a0328c3280a0e462c78386`.

It is an engineering preacceptance result only. The protocol and adapter were
still being hardened during attempts v5-v10, and the successful cell predates
the final SciTaste implementation pin. It must not be combined with the future
four-condition or 48-cell frozen matrix as headline evidence.

## Successful observation

Attempt v10 executed the generated `diagnosis-factorial-v1` experiment with the
exact registered factors, seeds `[7, 19, 31]`, three conditions, and 1,944
synthetic samples. The selected run returned zero and reported balanced accuracy
`0.8285583333`. The adapter then completed result analysis, the continue/drop
decision, paper outline, a 7,821-word paper draft, and peer review.

The finalized launcher result observed before archival reported:

- status `succeeded`, evidence class `real`;
- one experiment, zero live-search queries;
- 190,688 LLM tokens and estimated API cost USD 0.52596333;
- one useful result, three proposed ideas, one valid idea, one pilot, and two
  discarded ideas;
- evidence sufficiency 1.0, ten mechanically checked claims, and zero unsupported
  claims under the mechanical audit;
- 36 simulated upstream reviewer concerns opened and none closed.

The 200,000-token ceiling correctly stopped an attempted second paper-revision
pass. The registered launcher therefore ends all conditions at `PEER_REVIEW`.
The paper and peer-review artifacts exist, while external blinded review and
concern adjudication remain pending.

## Content-addressed retained evidence

Local ignored run directory:
`outputs/formal-preacceptance-v10/cells/cell-a27c079cab910aa021ba/`

- `paper.md`: SHA-256
  `eb0a474b5a6ae3c42886cccac50e2fcff4edc95f30882b54c9e535999a68a937`
- `outcome_audit.json`: SHA-256
  `1062d417f8c240a78695cbf9f40acb2db659f113eee3182caf53dce35943bedb`
- `condition_trace.json`: SHA-256
  `9e3f72667e5a8d6186aad9e2da7b4365eb1f9e966aa8f5b66a0409bec129f8c2`
- `upstream_artifact_manifest.json`: SHA-256
  `0b5107b10d8ca9e68bc79bb37f54a2b4908909f48d43e9968b948265942502c1`

The manifest records 123 upstream artifacts. In particular it records the
paper-draft hash above and peer-review artifact hash
`e44554594883ad3c3ba4efc9873c1864c35862b31e33faf743493080fb882fab`.

After successful finalization, an operator error invoked `study run` again for
the same output directory instead of evaluation. That restart overwrote the
aggregate execution record and removed the raw token telemetry and later-stage
working directories before it was terminated. The already materialized paper,
condition trace, outcome audit, and content-addressed artifact manifest remain.
Consequently the retained aggregate currently says failed and must not be used
as the success record; the hashes above identify the preserved evidence. Future
runs use a new frozen output directory and the runner's normal successful-cell
resume behavior.

## Hardening learned from v5-v10

The preacceptance sequence exposed and fixed real integration failures:

- fenced/prose-wrapped generated source is rejected or repaired;
- every generated experiment must preserve the frozen task contract, including
  seeds and factor levels;
- iterative prompts cannot silently substitute a different benchmark;
- upstream metric strings are normalized into structured comparable metrics;
- no-network source policy is audited before paper generation;
- post-analysis experiment repair is disabled for matched-budget comparability;
- cumulative provider token usage is enforced exactly across resumed calls;
- refinement logs are compacted while preserving a full archive on clean runs;
- interrupted launchers terminate their complete process group.

## Limitations and next gate

The task is a deterministic CPU synthetic benchmark even though the formal cell
reserves the same GPU allocation for every condition. It is not evidence of
natural-corpus transfer or meaningful RTX 3090 utilization. The generated paper
also contains methodological concerns that require independent review; the
mechanical claim audit is not a scientific-quality score.

The next gate is a clean, commit-pinned four-condition run on this one task and
seed. Only after its artifacts and budgets pass audit should the complete 48-cell
matrix be launched. Headline eligibility additionally requires two independent,
condition-blinded reviewers per cell and conflict adjudication.
