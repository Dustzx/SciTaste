# ICLR 2027 evaluation contract addendum v2

Date: 2026-09-12

This addendum narrows the task and estimand interpretation of
[`ICLR_2027_EVALUATION_PLAN.md`](ICLR_2027_EVALUATION_PLAN.md) after inspecting
the acquired MLR-Bench ten-brief bytes. It authorizes no API call, GPU job,
human study, task ingestion, or formal execution. Frozen v1 proposals remain
historical evidence and are not edited in place.

## Confirmatory claim architecture

The paper has one title-supporting causal estimand:

> Under the same native executor, controller model, starting information, tools,
> and budgets, what is the paired effect of enabling matched, precedent-informed
> and critic-checked scientific Taste on expert-aligned decisions and
> evidence-valid research outcomes?

This effect is estimated inside SciTaste Native. Base, Knowledge, Taste,
critics, Full, and mismatched-Taste placebo conditions randomize only the
decision policy components. Track A supplies high-powered decision evidence;
an executable Track C slice tests whether that mechanism changes empirical
outcomes. A positive effect on prose or model-judge scores alone is
insufficient.

The external-system estimand is separately labelled descriptive/ecological:

> Under each real system's pinned best-native model configuration and a common
> task/output budget, which complete research packages are preferred and what
> evidence failures and resource costs occur?

Because model choice is not controlled, every such lane must use
`comparison_regime=best_native`, `model_effects_confounded=true`, and a claim
boundary that forbids causal scaffold or Taste attribution. It supports external
validity and failure analysis, not the title-level causal estimate.

This hierarchy resolves the earlier false choice. SciTaste need not weaken an
accepted external implementation merely to manufacture a common backbone, and
it must not call a best-native contrast matched. A direct agent may still share
the primary SciTaste model as a low-control comparator, but it does not replace
the native Base ablation.

## MLR-Bench ten-brief boundary

The acquired ten-file cohort is exact and MIT-licensed at the benchmark-package
level. It is suitable for stagewise idea/proposal evaluation and a bounded
brief-only package prepilot. It is not an empirical end-to-end task population:
all ten items omit frozen runtime assets and objective scores, their executable
signals remain unverified, and held-out overlap remains pending. The former
100-trajectory v6 matrix must not launch from these files.

The content-bound finding is recorded in
[`research/MLR_BENCH_TEN_BRIEF_QUALIFICATION_AUDIT_V1.md`](research/MLR_BENCH_TEN_BRIEF_QUALIFICATION_AUDIT_V1.md).
An executable population such as an admitted EXP-Bench or MLRC-Bench subset is
required before the paper can claim improvement in evidence validity or real
research progress.

## Formal title gate

“SciTaste: Improving Autonomous Research through Scientific Taste” remains
permitted only if:

1. the within-SciTaste matched causal contrast is positive with a prespecified
   uncertainty analysis on held-out natural decisions;
2. the direction survives mismatched-Taste placebo and component ablations;
3. at least one held-out executable task population shows improved empirical
   evidence validity or task progress rather than paper fluency alone; and
4. blinded independent experts validate the primary endpoint and the submitted
   paper closes its evidence-bound review obligations.

Otherwise the bounded title “SciTaste: Scientific Taste for Autonomous
Research” is used. Broad superiority over external systems is a separate claim
and requires at least two admitted accepted systems regardless of the title
gate above.
