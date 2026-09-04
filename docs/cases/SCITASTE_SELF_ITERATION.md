# SciTaste self-iteration case

SciTaste's own development is a useful dogfooding case because each milestone
contains a problem, competing actions, evidence, costs, a selected intervention,
and an observable outcome. It is used for workflow usability and auditability,
not as evidence that SciTaste improves research quality.

## Phase 7.5 case

The case asks how to deepen AutoResearchClaw integration before Phase 8. It
compares three normalized ideas:

1. keep upstream immutable and strengthen the external contract adapter;
2. fork AutoResearchClaw and insert SciTaste control logic into its runner;
3. defer real integration and benchmark only mock/replay execution.

One real-substrate probe recorded that qwen3.8-max completed AutoResearchClaw
Stages 1–3, Stage 3 produced three validated artifacts, and the submodule remained
clean. The controller selected the external adapter with score `3.744`, versus
`1.280` for deferral and `-0.545` for a fork. The trajectory contains one probe
and ends at `PILOT`.

Run the case locally with:

```bash
scitaste discover \
  --config configs/cases/scitaste_phase75_self_iteration.yaml \
  --output outputs/scitaste-self-iteration-phase75 \
  --seed 7
```

The scenario and its expected selection are regression-tested. Generated state,
decision logs, and summaries remain ignored because they contain runtime paths
and timestamps.

## Phase 9 four-condition case

The Zhipu GLM-5.2 preacceptance is a second dogfooding episode. Four real system
conditions completed one frozen task, while failed gates exposed a resume-order
bug, a negation-sensitive evidence audit, a wrong derived grid count, an empty
factor slice, and an expensive per-example refit. The resulting fixes are
regression-tested and the failed Full attempt is retained alongside the raw run.

This episode supports claims about traceability and defect discovery only. It is
not evidence that Full SciTaste outperforms the other conditions: the cells were
continued after fixes, and the Full runtime is anomalous. Promotion of any lesson
from this episode into the Taste Library still requires a separate outcome review
and human verification.

## Anti-self-confirmation rules

- Self-iteration cases are excluded from headline Phase 8 effectiveness scores.
- Their primary claims are usability, traceability, and defect discovery—not
  scientific superiority.
- Negative evidence is retained, including long prompt latency, an upstream
  topic-specificity warning, run-ID discontinuity, and unavailable API cost.
- Candidate alternatives and scoring inputs are versioned before results are
  interpreted.
- Independent benchmark tasks and matched external baselines remain mandatory.

Future milestones can add cases to this series, but a successful implementation
must never be converted automatically into a retrieval-eligible Taste Case. That
promotion requires a separate outcome review and human verification.
