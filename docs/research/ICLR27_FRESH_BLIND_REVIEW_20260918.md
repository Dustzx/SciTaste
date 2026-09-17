# Fresh-context ICLR 2027 review — 2026-09-18

Review mode: an independent agent received no conversation history. It located
the latest manuscript and inspected only artifacts it independently considered
necessary. No files were edited by the reviewer.

## Verdict

**2/10, Strong Reject; confidence 5/5.** The framing is important and the
negative evidence is unusually candid, but the current artifact is a
well-instrumented failed prototype rather than an ICLR-level learning method.

Two additional isolated review passes independently returned **3/10** and
**2/10**, both Strong Reject. All three agreed on the same claim-bearing gaps:
the local mechanism has not beaten raw and mismatched controls, the proposed
benchmark lacks formal construct validation, the local and downstream
treatments are not yet identical, and no all-task accepted external comparison
exists. The external-evaluation review further concluded that SciTasteBench plus
MLRC-Bench and MLR-Bench can support a scoped ML-research-agent claim, while the
broader autonomous-research title additionally requires a scorer-owned workload
outside that task family or an explicit scope reduction.

A separate context-isolated construct review inspected only the 13-pair
SciTasteBench package, schema, study design, and latest development report. It
accepted **0/13 pairs unchanged**: six require reconstruction and seven should
be rejected. Eleven counterfactual twins retain prose that contradicts the
changed fact; several registered changes are compound; all 26 states force an
action rather than containing genuine abstention cases; scalar utilities are
author-defined; the labels have only AI-proxy validation; and explicit boundary
fact/action wording creates shortcut cues. This audit consumes the population.
It cannot be repaired and relabelled as hidden evidence.

## Fatal findings

1. The current effectiveness claim is false: the prospective policy solved
   1/12 tasks versus 2/12 for Base and selected `REFINE` at all 48 nonterminal
   decisions.
2. The later 28-case source-disjoint confirmation reverses the paper's only
   positive mechanism signal: matched Taste is below both token-matched raw and
   mismatched Taste; the recorded analysis rejects mechanism confirmation.
3. Current SciTasteBench populations contain no actual boundary-crossing
   transfer or abstention cases. Reversing candidate order measures position
   bias, not whether a scientific preference reverses when a decisive fact
   changes.
4. The active factorized preference estimator is supported by too few episodes,
   uses hand-set correlated feature weights, and calls a heuristic score a
   posterior without calibration.
5. The text-card mechanism study and the downstream factorized policy evaluate
   two different mechanisms. Success of one would not validate the other.
6. The external evidence is one benchmark family, one model, mostly one seed,
   no strong external agent, and no outcome-update or action-prior controls.

## Benchmark judgment

The existing suite is an executable **internal AI-proxy development
instrument**, not yet a benchmark contribution. A benchmark claim requires:

- licensed public data, immutable splits, provenance, and reconstruction;
- genuine apply/reverse/abstain boundary pairs across all decision contexts;
- candidate feasibility and ambiguity audit;
- raw independent judgments, adjudication, and reliability;
- contamination and temporal-leakage analysis;
- a datasheet and executable scorer; and
- pair-level statistics rather than treating calls as independent samples.

The replacement population must additionally pass a semantic-difference audit,
two pair-blinded expert construct audits per pair, a frozen component-wise
utility contract, stable action semantics and feasibility across twins, and
matched shortcut controls. At least 12 formal pairs must cross an
action-to-abstention boundary. The current 13 pairs remain useful only for
method development and failure analysis.

The review directly motivates the boundary-counterfactual pair specification in
`scitaste.benchmark.boundary_pairs` and the revised study design in
`SCITASTEBENCH_ICLR27_STUDY_DESIGN.md`.

## External evidence judgment

For the title *Improving Autonomous Research*, an official external
peer-reviewed benchmark and a runnable strong system baseline are mandatory.
SciTasteBench alone cannot validate SciTaste because the method and instrument
share assumptions. An official objective task such as MLRC-Bench or a qualified
EXP-Bench/ScienceAgentBench route must complement the internal mechanism study.

## Manuscript evidence boundary

Hashes, schemas, smoke tests, repair histories, and consumed development scores
belong in the reproducibility package or development ledger. They cannot fill a
main result table. The manuscript needs benchmark-construction and validity
figures, pair-level effect plots, calibration/risk--coverage, learning curves,
and external objective results generated only from frozen evidence.

## Decision for the next iteration

Do not spend remaining time polishing the current narrative around failed
development evidence. First build real boundary pairs and a state-conditional
method on consumed development data; then freeze one version, run an independent
mechanism confirmation, and execute a small official external comparison. If
those gates remain negative, the scientifically defensible submission is a
falsification/diagnostic paper and must drop the effectiveness title.
