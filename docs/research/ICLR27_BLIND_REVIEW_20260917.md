# Independent ICLR 2027 blind review — 2026-09-17

Status: **Strong Reject (3/10, confidence 5/5)**. This review was produced by an
independent Codex agent with no inherited conversation context. It inspected the
latest local manuscript, implementation, evaluation artifacts, and benchmark
governance files. It did not edit the repository.

## Decision

The current paper does not support the title *SciTaste: Improving Autonomous
Research through Scientific Taste*. The prospective NewtonBench study is negative
(SciTaste 1/12, Base 2/12), and the learned arm selects `REFINE` at all 48
nonterminal decisions. The latest manuscript itself acknowledges that improved
autonomous research has not been established.

The review identifies three independent missing arguments:

1. **Method validity.** The current estimator is a small hand-designed factorized
   scorer whose state conditionality, uncertainty semantics, signed credit,
   source balancing, and abstention have not survived independent confirmation.
2. **Benchmark validity.** The 36-case natural development set has reconstructed
   actions, dual-AI proxy labels, incomplete family coverage, public-model
   contamination risk, and unresolved exact-text release rights. It is not yet a
   public benchmark.
3. **External utility.** NewtonBench plus an internal zero-weight control is not a
   comparison against the accepted AutoResearch literature. The broad claim needs
   a scorer-owned external benchmark, a matched Native Base intervention, and at
   least one runnable strong external method or agent baseline.

## Manuscript findings

- The latest scientific content is `scitaste-iclr2027-submission-draft-v19`, but
  it is not a complete content-bound bundle and exceeds the currently frozen page
  budget.
- The manuscript has one conceptual figure and no benchmark-construction/split
  figure, paired-effect plot, task-level failure heatmap, component ablation, or
  external-system comparison.
- Formal negative evidence belongs in the scientific record. The formal-v1
  inactive treatment, single reused Heat task, self-development case, repeated
  36-case development estimates, and positive development-only selectors do not
  belong in the main effectiveness argument.

## Result after the review was commissioned

The subsequently executed 28-case source-group-disjoint reserve strengthens the
review rather than resolving it. Under the order-consistent endpoint, matched
Taste scored 46.4%, token-matched raw evidence 57.1%, mismatched Taste 67.9%, and
Base 60.7%. Matched minus mismatched was -21.4 points with six regressions, no
improvements, and a two-sided exact paired p-value of 0.03125. The old "matched"
assignment shared only a broad judgment family and used stable hash ordering; it
did not implement content-conditioned applicability.

## Required evidence portfolio

| Claim | Minimum credible evidence | Current state |
|---|---|---|
| Taste is a distinct mechanism | independent raw/matched/mismatched comparison with content-conditioned selection, abstention, order robustness, and no action collapse | contradicted for the current assignment policy |
| SciTasteBench is a valid instrument | complete family coverage, raw disagreements, construct audit, contamination/de-duplication audit, legal release or a reproducible licensed substitute, hidden split | incomplete |
| SciTaste improves research | external scorer-owned objective tasks, Full versus same-backbone Native Base, failures retained | only a negative internal NewtonBench study |
| SciTaste is competitive | at least one runnable accepted method/agent baseline on a compatible external task contract | not executed |
| SciTaste completes research | evidence-valid idea-to-paper packages including independent review and revision | planned, not demonstrated comparatively |

## Deadline routing

1. Retire same-family hash assignment and build a target-visible,
   content-conditioned applicability selector with an explicit abstention path.
2. Use consumed cases only for development and failure analysis; freeze a new
   untouched split before the next effect estimate.
3. Do not run a large external matrix until the selector passes action-diversity,
   state-sensitivity, and matched-over-mismatched development gates.
4. Once the mechanism is active, run the smallest compatible external objective
   comparison: Full, same-backbone Native Base, and one runnable official baseline.
5. Keep the current manuscript as a diagnostic evidence memo. Assemble a new
   submission manuscript only from admitted evidence, with the working title
   contracted if the external effect remains null or negative.

The review does not estimate acceptance or oral probability. Its verdict is a
claim-evidence assessment, not a forecast.
