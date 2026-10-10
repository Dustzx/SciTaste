# Recursive Scientific Taste policy development

SciTaste is a domain-general autonomous research system. Its controller and
Scientific Taste decide over pre-decision evidence, feasible research actions,
and a budget; a task-specific executor, observations, and scorer instantiate
that interface. Visual research is one evaluation domain, **not** a vision-only
fork of SciTaste or a new controller ontology; a CVPR target does not narrow the
autonomous-research architecture to vision.
The shared decision request optionally carries exact, verified pre-decision
image/video evidence artifacts in addition to text anchors. The policy sees
the same artifact bindings under a fixed information budget; private action
utilities remain with the scorer. This is an input capability, not a claim
that a real visual action-fork cohort has already been executed.

## What recurses

The first self-improvement target is the *decision policy*, not the whole code
base. Let policy `g` complete research, receive independently scored outcomes,
and add eligible decision episodes to a development corpus. The existing
project Taste refresh can fit a candidate `g+1`. A frozen
`TasteEvolutionPlan` binds the parent and candidate policy identities, their
training task groups, separate selection task groups, a reserved transfer
population, and a minimum task-mean regret reduction. Both policies then
submit decisions for the same outcome-hidden requests. The scorer joins them
to private action utilities only after submission.

Procedural skills explain how to carry out an action; the harness governs its
execution authority. The backbone, proposal mechanism, skills, harness and tool
verification policy must remain fixed within a policy-attribution study. A change
to those components creates a separately bound system revision, not a Taste-only
successor. Generated project views and user feedback may propose typed edits, but
do not select or deploy a successor; assisted interventions must remain disclosed.

`select_taste_evolution_round` accepts the candidate as the next **development
parent** only when its task-cluster mean regret improves beyond the frozen
threshold. It otherwise keeps the parent and retains the rejected round in an
immutable, self-hashed lineage. A later generation cannot reuse any prior
selection task group. `evaluate_taste_evolution_transfer` reads an accepted
generation on separately reserved, source-disjoint tasks; its result cannot
change the selection. The selector neither generates the new model, deploys
it, nor authorizes a scientific RSI claim.

The runnable no-call entry point is
`scripts/select_taste_policy_successor.py --plan PLAN.json --requests REQUESTS.jsonl
--private-keys KEYS.jsonl --parent PARENT.jsonl --candidate CANDIDATE.jsonl
--output ROUND.json`. For generation 2+, also pass `--predecessor ROUND.json`.
The four case/decision inputs use the existing JSONL format (JSON arrays are
also accepted) of the existing
`DecisionMethodRequest`, private `DecisionScoringKey`, and
`DecisionMethodSubmission` schemas. Parent/candidate submissions must bind the
policy hashes from the plan. Output creation is exclusive and never overwrites
a previous round. The task-context and scorer contracts must be identical
within a round, whether the workload is training-free or training-based.

## Evidence boundary

This mechanism closes the *selection* software path, not the empirical RSI
claim. AIDE² [rewrites its agent harness and reports repeated accepted code
revisions plus held-out transfer](https://arxiv.org/abs/2609.26457). SciTaste
currently revises Scientific Taste policies; a stronger future route may also
propose bounded controller, memory, or tool changes, each requiring its own
candidate artifact and unchanged external task contract. Do not label a single
policy refresh, prompt revision, retrospective replay, or self-development
history as proven recursive self-improvement.

The existing NewtonBench outcome-learning v2 report was tuned and analyzed on
already opened development populations. Its apparent gain is useful mechanism
development but is ineligible for a new untouched selection or transfer claim.
No prospective SciTaste policy generation has yet passed this selector on a
fresh sealed population, and no independent cross-domain transfer generation exists.
For the paper, first collect complete-task system evidence; policy succession
becomes a separate longitudinal result only if multiple generations
and truly untouched transfer tasks are observed. The original general title
also requires evidence beyond a single vision benchmark family or an explicit
scope qualification in the abstract and conclusion.
