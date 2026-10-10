# CVPR 2027 mainline exit criteria

Updated 2026-09-25. Target: a domain-general SciTaste method, evaluated
concretely in vision research. The [official CVPR schedule](https://cvpr.thecvf.com/Conferences/2027/Dates)
sets registration for 2026-11-10, paper submission for 2026-11-16, and
supplement for 2026-11-23, all Anywhere on Earth. These criteria distinguish
an engineering-complete research instrument from an empirically convincing
paper; passing the former does not imply the latter.

## Scope decision

The [CVPR 2027 call for papers](https://cvpr.thecvf.com/Conferences/2027/CallForPapers)
lists "AI for Science and Scientific Discovery" under its broader computer
vision and pattern-recognition scope. We therefore keep SciTaste's controller,
task/executor contracts, and Scientific Taste domain-general while presenting
substantive visual-research evidence for this venue. The call does not say that
an Auto Research method must only operate on visual tasks; conversely, its
science topic alone does not establish a fit for a paper with no meaningful
vision contribution. Non-vision complete-system transfer is part of testing
the general claim, not a replacement for the CVPR-facing visual results.

SciTasteBench v1 is an **outcome-grounded research-decision benchmark**, not an
end-to-end Auto Research leaderboard. Its released core should be executable
shared-prefix action forks plus a chronological delayed-credit track. Natural
paper/review decisions may be an explicitly labelled proxy extension only
after source rights, label authority, and independent validity are resolved.
Complete research-agent comparisons belong on unchanged external benchmarks
unless an agent-compatible SciTasteBench task mode is actually implemented.
The SA/D/L/P study layers are a causal research program; P does not become
SciTasteBench-owned data by naming it a layer.

## First exit: benchmark design and engineering

The benchmark engineering milestone is complete only when one versioned
package contains:

1. A documented unit of independence (source research task), representative
   and development-defined discriminative populations, source-disjoint
   development/selection/test roles, and a manifest of every admitted and
   rejected case. States and seeds are repeated measurements, never extra
   independent tasks.
2. An outcome-hidden policy request with identical state, feasible action
   semantics, visible media and source budgets for all methods; a separate
   scorer-owned branch-outcome vault; and executable branch continuation under
   the **same** task, model, tool, wall-time, token/API/GPU limits across split
   roles. Failures, ties, missing objectives, action noncompliance, and
   abstention retain explicit predefined treatment.
3. A release runner that can reproduce case construction and scores from
   pinned data/runtime bytes, plus a dataset card covering provenance,
   licenses, contamination risks, split policy, scorer semantics, and known
   limitations. At least one real vision research state must complete an
   action-fork-to-official-scorer path; a media attachment or a synthetic
   fixture alone does not close the CVPR-facing instrument.
4. Real direct decision, outcome-conditioned reflection, and budget-matched
   planning/search policy implementations on the same outcome-hidden interface,
   alongside SciTaste. Raw evidence, generic memory, mismatched Taste, and gate
   removals remain mechanism controls, not named method baselines. A complete
   external agent is never reduced to a prompt or a fixed-menu policy and then
   reported as that agent's end-to-end result.
5. One reproducible development evaluation that emits task-level regret,
   tie-aware correctness, valid-case coverage, failures, action changes,
   inference/resource cost, and raw case outcomes without opening a fresh
   formal split. Engineering acceptance does **not** require SciTaste to win.

Current state: typed fork/scoring contracts and a development interface exist;
direct and two-stage planning were executed on the 30-case NewtonBench
development cohort, but their decisions differ in only one case and their
actual API consumption is not matched. A separate 5-source/5-target
retrospective development partition ran outcome-conditioned reflection on
15 targets: it changed no direct decisions at 4.75 times the cost ceiling.
This is not prospective learning. One real image-conditioned development
request has now yielded different direct/planning decisions; the associated
remote GPU pair completed on the replacement 4090: Euclidean 0.184874 versus
normalized 0.106298. The common image-bearing dataset export reproduces both
policy scores. Genuine tool search is still missing, and
these weak-differentiation results do not complete the independent-method suite;
the first NewtonBench cohorts are narrow and have a 600-s/120-s split-contract
shift, many ties and missing objectives. One genuine visual action fork is now
complete, but a complete independent policy-baseline suite, validated public release,
and agent-compatible whole-system mode remain missing. The 36 natural development cases
are unbalanced AI-proxy records, not a formal set; the proposed 120-case natural
formal release has zero admissions. Thus design is **promising but not frozen
for release**, and engineering completion is **not yet achieved**. The detailed
counts and counterexamples live in `docs/SCITASTEBENCH.md` and the project's
`SCITASTEBENCH_QUALITY_AUDIT.md`; do not copy those run details into the paper.

## Second exit: research and paper quality

Once the instrument is runnable, SciTaste itself must show a credible
idea-to-experiment-to-evidence-to-paper-to-review-and-revision loop, not merely
stage completion. The decisive evidence is prospective, source-disjoint task
outcomes: task-native visual metrics on unchanged external benchmarks against
the same Native executor without Taste and at least one real named agent;
decision regret against independent policies on SciTasteBench; behavior-change
traces that connect the two; failures, cost and visual error slices. Negative
results remain in the analysis and can force a narrower method claim.

The final project is **not** considered complete because of a passing test
suite, a rendered PDF, a favorable AI review, or one positive development
task. Completion requires both (a) efficient autonomous exploration that
produces a defensible idea and independently scored experimental results and
(b) a full paper that the assistant's evidence/novelty/method review and the
owner's visual/technical inspection both judge to have credible CVPR oral
potential. This is a demanding decision criterion, not a guarantee of oral
acceptance. If the measured effect fails, revise the method, claim, or venue
route; do not preserve the original title by hiding adverse evidence.

## Resource and execution route

Future GPU experiments default to the user-supplied remote
`4090-2` (8×RTX 4090), with files under `/data/zfx`. The previous 3090 queue
was cancelled before either arm ran; the replacement pair uses one available
4090 sequentially. The local 3090 remains an inventory asset and
historical development provenance, not a default experiment target. Use the
remote host's available cards selectively; an eight-card host is not a reason
to run eight redundant arms. Before a GPU launch, bind the exact task split,
model, data/checkpoint bytes, per-arm card count and wall ceiling, expected
storage, and stop/resume rule. The project may use currently available
DeepSeek, GLM, or Qwen APIs for research-agent and decision nodes, recording
the actual served identity, budget, and costs; API access does not convert
proxy labels into objective outcomes. Do not schedule a new local-GPU arm by
reusing an old resource proposal.
The prior 3090 observation found all eight devices occupied. The replacement
4090 observation found five idle cards; the current job selected GPU 3. Do not
preempt other workloads or assume that this observation reserves future capacity.

## Immediate order

1. Freeze the SciTasteBench v1 release scope and engineering contract above.
   The three text-only development policies have now been run; do not keep
   tuning their prompts on the consumed targets. The real visual fork and its
   frozen image decisions are now scored and exported; repair the
   split-budget mismatch only in a **new** cohort,
   and establish source rights and release reproducibility.
2. Connect SciTaste Native and a real named agent to the now-reproduced MLRC
   Meta-Learning development environment, then add independent visual tasks
   without opening a test set as a development convenience.
3. Only after the interfaces and populations are credible, freeze and run the
   formal comparisons on the remote host; route measured outcomes back into
   method revision and the CVPR paper, with an independent review of the
   resulting claims and the owner's visual inspection.
