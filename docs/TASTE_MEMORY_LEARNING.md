# Outcome-gated continual Scientific Taste

SciTaste may learn from its own research trajectory, but an executed action is
not automatically a good precedent. A successful-looking outcome can be delayed,
confounded, incorrectly attributed, or useful only in a narrow context. If a
self-authored reflection immediately enters retrieval, the controller can amplify
one mistaken judgment across later decisions.

SciTaste therefore treats self-reflection as an untrusted candidate:

```text
executed ResearchDecision
        |
        v
quarantined TasteCase --------------------> excluded from retrieval
        |
        +-- bound decision record and actual-outcome hash
        +-- content-bound outcome record and observation IDs
        +-- two independent, invocation-separated AI or human reviews
        +-- one distinct adjudicator only when primary reviews split
        |
        v
retrieval-eligible outcome-calibrated precedent
```

This is the continual-learning path for project experience. It complements the
external-reference path in `evaluation/taste_corpus_curation.py`: external
high-quality sources are abstracted and reviewed before admission, while project
reflections are observed and reviewed after execution. Neither path equates raw
retrieval with Taste.

## Admission invariants

`TasteMemory.reflect` accepts only a decision containing both an executor result
identity and an actual outcome. It records the exact decision hash, actual-outcome
hash, selected and rejected actions, author, outcome horizon, and proposed
principle, but fixes `human_verified=false` and `retrieval_eligible=false`.
Production retrieval filters that record out.

`TasteMemory.admit` promotes the record only when all of these checks hold:

1. The stored quarantined case matches the case hash in the admission request.
2. A bounded, non-symlink local decision record matches its file hash and the
   semantic decision hash frozen by reflection. A separately bound outcome record
   matches its declared file hash, decision identity, executor result,
   actual-outcome hash, summary, horizon, and at least one observation identity.
3. Exactly two distinct primary reviewers bind the same case and outcome bytes.
   Neither reviewer may be the reflection author. Each review explicitly checks
   the decision trace, outcome trace, alternatives, principle, and transfer scope.
4. Two accepting primary reviews admit the case. Two rejecting reviews reject it.
   A split requires exactly one distinct adjudicator; a unanimous result cannot be
   overridden. Reviews cannot predate the outcome observation.

Admission changes only the local Taste record. It does not train a model,
authorize a tool, launch an experiment, or establish that SciTaste improves
research outcomes. Negative outcomes may still support a useful principle when
the reviewers judge the causal interpretation and transfer boundary sound;
success alone is not an admission criterion.

## CLI boundary

Create a quarantined reflection from an already executed decision:

```bash
.venv/bin/scitaste taste memory-reflect \
  --decision decision.json \
  --library outputs/projects/<project-id>/taste/records.jsonl \
  --outcome-summary "The diagnostic separated the competing explanations." \
  --decision-principle "Prefer a discriminating probe before scaling." \
  --outcome-horizon immediate \
  --author-id researcher-a
```

Inspect a hash-bound admission without mutation, then promote it explicitly:

```bash
.venv/bin/scitaste taste memory-admission \
  --manifest admission.yaml \
  --library outputs/projects/<project-id>/taste/records.jsonl \
  --evidence-root outputs/projects/<project-id> \
  --report admission-report.json \
  --require-ready

.venv/bin/scitaste taste memory-admission \
  --manifest admission.yaml \
  --library outputs/projects/<project-id>/taste/records.jsonl \
  --evidence-root outputs/projects/<project-id> \
  --admit --require-ready
```

The manifest and review records are typed attestations, not proof that the named
people exist. A formal longitudinal study must retain its reviewer recruitment,
identity/conflict records, outcome artifacts, and review packets under the
project evidence protocol. Unit-test reviewers are fixtures only and must never
be reported as human evidence.

For engineering progress and internally AI-reviewed source assets, SciTaste also
supports two isolated AI reviewers plus a distinct adjudicator on disagreement.
Those records bind model, invocation, and raw-response identities and always keep
`not_human_review=true`; they can close the operational review gate requested by
the project owner but never set `human_verified` or support a human-validity
claim.

The AI path is executable rather than a hand-written JSON convention. Prepare the
same candidate once for each of the two provider profiles, execute both configs
through the durable project model-node ledger, import their evidence bundles, and
then admit the panel:

```bash
.venv/bin/scitaste taste prepare-ai-attribution-review \
  --candidate episodes/candidate-001.json \
  --evidence-root outputs/projects/<project-id> \
  --profile-set configs/model_nodes/runtime_profiles.taste_attribution_review_v1.yaml \
  --profile-id zhipu-glm53-taste-attribution-review \
  --backend-config /ignored/live/zhipu-review.json \
  --seed 7 --output /ignored/runtime/review-a.json

.venv/bin/scitaste model-node runtime execute \
  --project-id <project-id> --run-id <registered-panel-run> \
  --invocation-id episode-001-review-a --expected-revision <printed-revision> \
  --config /ignored/runtime/review-a.json \
  --profile-set configs/model_nodes/runtime_profiles.taste_attribution_review_v1.yaml \
  --profile-id zhipu-glm53-taste-attribution-review --allow-live

.venv/bin/scitaste taste import-ai-attribution-review \
  --candidate episodes/candidate-001.json \
  --contract configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml \
  --project-id <project-id> --run-id <registered-panel-run> \
  --invocation-id episode-001-review-a --review-id episode-001-review-a \
  --reviewer-id zhipu-primary --role primary \
  --evidence-root outputs/projects/<project-id> \
  --output-directory taste/episodes/episode-001/reviews/zhipu
```

Repeat preparation, execution, and import with
`deepseek-v4flash-taste-attribution-review`, then run:

```bash
.venv/bin/scitaste taste admit-ai-reviewed-episode \
  --candidate episodes/candidate-001.json \
  --review taste/episodes/episode-001/reviews/zhipu/REVIEW.json \
  --review taste/episodes/episode-001/reviews/deepseek/REVIEW.json \
  --contract configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml \
  --review-package configs/evaluation/programs/iclr2027_lifecycle_evidence_review_package_v2.yaml \
  --workspace-root . --evidence-root outputs/projects/<project-id> \
  --admission-id episode-001-admitted \
  --output outputs/projects/<project-id>/taste/episodes/episode-001/ADMITTED.json
```

The two preparation commands create the same semantic prompt and sampling
packet; provider and budget envelopes remain separately bound in their runtime
ledger entries. Raw responses must differ, both calls must be real live/local
generation rather than replay or scripted fixtures, and a disagreement still
requires a third independent adjudicator.

## Scientific decision-family conditioning

Admitted episodes are not pooled into one generic quality score. A fixed
seven-family ontology separates scientific value, epistemic discrimination,
empirical diagnosticity, adaptive allocation, inferential discipline,
transfer/correction, and scientific communication. Two isolated AI assignments
must agree, or a third invocation adjudicates. The assignment is joined to
outcome-family metadata only after the outcome-blind family judgment.

Compile each assignment, then fit one independent head per observed family:

```bash
.venv/bin/scitaste taste assign-decision-family \
  --assignment-id episode-001-family-v1 \
  --episode admitted-episode-001.json \
  --decision-family adaptive-allocation \
  --review reviewer-a.json --review reviewer-b.json \
  --rationale "This decision allocates the next bounded experiment." \
  --output episode-001-family-v1.json

.venv/bin/scitaste taste fit-family-policy \
  --policy-id lifecycle-taste-v1 \
  --config lifecycle-policy.yaml \
  --episode admitted-episode-001.json \
  --assignment episode-001-family-v1.json \
  --output FAMILY_POLICY.json
```

Unobserved families abstain rather than borrowing another head. Native H4 uses
only the exact `adaptive-allocation` head, while its reproduction report binds
the complete parent policy, assignment population, and admitted episodes.

## Current evidence boundary

The implementation proves that unreviewed self-reflections cannot enter the
production retriever and that decision or outcome drift, author-review conflict,
missing adjudication, temporal inconsistency, and replay over an admitted record
fail closed. No real project reflection
has yet completed this new human gate, and no longitudinal effectiveness result
exists. The ICLR claim still requires held-out H1/H2/H3 experiments and
independent review; this mechanism makes future continual-learning evidence
admissible rather than supplying that evidence itself.
