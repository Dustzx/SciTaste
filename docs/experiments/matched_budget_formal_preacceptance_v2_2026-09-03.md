# Matched-budget formal preacceptance v2: diagnosis/base

Date: 2026-09-03

## Result

A real Qwen3.8-Max `autoresearchclaw` cell completed the frozen diagnosis task
from hypothesis generation through peer review. This is the first cleanly
materialized formal-run success after the v5-v10 adapter-hardening sequence. It
is still engineering preacceptance, not a four-condition comparison or headline
study result.

Run identity:

- protocol SHA-256:
  `f755f711d487e3601b2d1c2bf9dcddcca0d69bb56fbff553a4ee6f3c355443d6`;
- cell: `cell-15504de1e69da24e3871`;
- task/condition/seed: `diagnosis-friendly-v1`, `autoresearchclaw`, 7;
- upstream commit:
  `12d3fd809fa9658e91a0328c3280a0e462c78386`;
- local ignored directory:
  `outputs/formal-core-preacceptance-v2-2026-09-03/run/`.

Measured launcher counters:

- 144,082 exact provider tokens;
- estimated API cost USD 0.39465667;
- zero live-search queries;
- one selected experiment;
- balanced accuracy 0.5 from the explicit overall-mean output;
- 8,286-word paper draft and a completed Stage 18 peer review;
- 31 upstream simulated-review concerns opened and zero closed.

The generated experiment initially failed because it used `np.default_rng`.
AutoResearchClaw's single registered Stage 13 repair changed this to executable
code and the repaired experiment returned zero. The result is intentionally a
negative result: every condition reported balanced accuracy 0.5 and the
analysis scored experiment quality 1/10. SciTaste preserved both the numerical
result and the quality criticism rather than converting them into a favorable
claim.

## Retained artifacts

- `paper.md`: SHA-256
  `dfdc5b6587878d63388001a4bacf2fc5c47af27d1366eead82615f97661de5a0`;
- `outcome_audit.json`: SHA-256
  `55517504f925192d3742fd0c3219f1418a25b06e08e8af7e61b7066fc9f32669`;
- `condition_trace.json`: SHA-256
  `9e3f72667e5a8d6186aad9e2da7b4365eb1f9e966aa8f5b66a0409bec129f8c2`;
- `upstream_artifact_manifest.json`: SHA-256
  `d1be1316ae5e43a8200551690ee80096c94a6edbc514ca546b075ab2d08d5f1e`.

The manifest contains 97 content-addressed upstream artifacts.

## Integration findings

The first frozen attempt correctly failed because generated code asserted that
ablation outputs had to differ. Equal effects are valid negative evidence, so
the code-generation and repair contracts now prohibit outcome-dependent
assertions while retaining structural assertions and strict return-code checks.

The second attempt exposed an upstream record shape in which a successful
`sandbox_after_fix` object omitted stdout while the same iteration's successful
`sandbox` object retained the complete output. The adapter now selects the
richest successful record and prefers an explicit overall primary-metric mean,
preventing a standard-deviation line from contaminating the metric.

Stage 14-18 was resumed from the preserved 51,371-token checkpoint and the
provider-token counter remained cumulative. A subsequent result-only
finalization made no model calls. Because that finalization was invoked through
the study runner only after a manual resume, the v2 aggregate's displayed
runner-owned wall/GPU duration covers only finalization and is not a valid
whole-cell time measurement. The outcome audit retains stage durations, but this
cell is excluded from comparative timing. The runner now accumulates its own
time across normal failed/interrupted retries so future frozen batches do not
have this limitation.

## Next gate

Freeze the post-v2 adapter commit, rerun the same task/seed under all four core
conditions from clean cell directories, and audit complete resource telemetry.
Only then proceed to all 48 cells and independent condition-blinded review.
