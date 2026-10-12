# Track-A Taste mechanism pilot suite

SciTasteBench Track A asks a narrow mechanism question: does a grounded,
contrastive Taste abstraction help a decision model use a scientific precedent
more effectively than the same precedent's raw source projection, and does that
benefit disappear when the abstraction comes from a deliberately mismatched
domain? The current suite is an AI-only natural pilot. It is not formal ICLR
evidence and it does not replace human or expert construct validation.

## Frozen three-arm comparison

Every runnable target receives exactly three requests:

| Arm | Precedent content | Mechanism contrast |
| --- | --- | --- |
| `raw-source-rag` | canonical source projection | H1 baseline |
| `abstracted-matched-taste` | AI-reviewed grounded Taste abstraction of the same source | H1 treatment and H2 matched arm |
| `abstracted-mismatched-taste` | AI-reviewed grounded Taste abstraction from another domain and source group | H2 negative control |

The materializer replays the pilot-plan bindings before producing requests. In
each case it fixes the target prompt, candidate-action order, provider, exact
declared model name, sampling values, output schema, and byte/token budgets.
Condition and relation labels, source identities, and the historical observed
action remain outside model-visible requests. Token counts must be measured
with the runtime tokenizer before execution; over-budget requests must stop
rather than truncate silently.

The historical action is only a `source_observed_action`. Agreement with it is
a natural-outcome diagnostic, not correctness, accuracy, an expert label, or a
gold answer. The suite therefore permits only observed-action agreement and
natural-outcome proxy reporting.

## Partial coverage is first-class

The accepted abstraction set may cover fewer than all sixteen planned
precedents. SciTaste generates a triplet only when both the target's matched and
mismatched precedents were operationally accepted by the AI-only review. It
does not synthesize a substitute for rejected, failed, or absent abstractions.

`STATUS.json` records all sixteen abstraction states and all twenty-four target
states. Its status is:

- `blocked` when no target is runnable;
- `partial` when at least one but fewer than twenty-four targets is runnable;
- `ready` only at complete twenty-four-target coverage with no blocker.

For an available suite, `SUITE_MANIFEST.json` binds every generated execution
config. Controller-only metadata preserves the experimental relation and the
natural proxy; each nested `model_visible_request` is the only request surface
allowed to reach the decision model. Materialization authorizes no API call,
GPU work, retry, experiment, or spend.

## Natural-pilot and formal boundaries

The tracked natural-pilot specification is
`configs/evaluation/pilots/scitastebench_track_a_ai_suite_v1.yaml`. It declares
an explicit pilot-only reference-quality override because this pilot diagnoses
the currently observed abstraction pipeline. It can never be relabeled as
formal evidence.

A later `formal-candidate` specification must be a new immutable artifact. The
materializer then requires one self-hashed, ledger-bound
`ReferenceQualityQualification` with a `qualify` verdict for every planned
precedent. All five reference-quality dimensions must have been satisfied
upstream. Missing or rejected qualifications block every formal-candidate
execution config; the natural-pilot override cannot cross that boundary.

## Current no-call preparation

The first real preparation against `preparation-v2/PLAN.json` was intentionally
run without an accepted abstraction set. It produced only:

`outputs/projects/scitaste-self-development/evaluations/scitastebench-track-a-ai-pilot-v1/suite-preparation-v1/STATUS.json`

The status is `blocked`, with zero runnable targets and the explicit
`accepted-abstraction-set-missing` blocker. This verifies the no-fabrication
path without consuming API or GPU resources. Once the AI-only review emits its
accepted set, rerun to a new output directory; immutable prior preparations are
never overwritten.

Prepare a new immutable status or suite with:

```bash
.venv/bin/scitaste evaluation track-a-suite-materialize \
  --plan outputs/projects/scitaste-self-development/evaluations/scitastebench-track-a-ai-pilot-v1/preparation-v2/PLAN.json \
  --accepted-set '<AI-only accepted-set JSON>' \
  --output outputs/projects/scitaste-self-development/evaluations/scitastebench-track-a-ai-pilot-v1/suite-preparation-v2
```

Omit `--accepted-set` to exercise the strict blocked/no-call path. Add
`--require-ready` only when complete twenty-four-target coverage is required;
partial suites otherwise return successfully so the available pilot cases can
be inspected without concealing missing coverage.

Replay every status, manifest, and generated config binding with:

```bash
.venv/bin/scitaste evaluation track-a-suite-inspect \
  --status outputs/projects/scitaste-self-development/evaluations/scitastebench-track-a-ai-pilot-v1/suite-preparation-v1
```

Programmatic callers may use `materialize_track_a_pilot_suite(...)` and
`inspect_track_a_pilot_suite(...)` from
`scitaste.evaluation.taste_mechanism_suite`.
