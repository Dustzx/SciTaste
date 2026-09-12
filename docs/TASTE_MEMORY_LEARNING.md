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
        +-- two independent, conflict-cleared human reviews
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

## Current evidence boundary

The implementation proves that unreviewed self-reflections cannot enter the
production retriever and that decision or outcome drift, author-review conflict,
missing adjudication, temporal inconsistency, and replay over an admitted record
fail closed. No real project reflection
has yet completed this new human gate, and no longitudinal effectiveness result
exists. The ICLR claim still requires held-out H1/H2/H3 experiments and
independent review; this mechanism makes future continual-learning evidence
admissible rather than supplying that evidence itself.
