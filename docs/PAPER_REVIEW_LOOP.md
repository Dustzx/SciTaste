# Project-owned paper review loop

SciTaste represents pre-submission review as a content-bound project stage,
not as a free-form chat transcript or an acceptance predictor:

```text
registered paper revision
→ anonymous venue packet
→ structured reviewer reports
→ research-action obligations
→ registered revised paper
→ original-reviewer verification
→ internal closure or independent pre-submission closure
```

The current venue packet follows the four questions in the official ICLR 2027
reviewer guidance: whether the paper asks a specific question, motivates and
places it in the literature, supports its claims rigorously, and offers
significant value to the community. Reports retain a summary, strengths and
weaknesses, an accept/reject recommendation with one or two decision reasons,
questions, optional feedback, and typed decision-relevant concerns. SciTaste
does not invent a numeric conference score where the venue guidance does not
define one.

## Authority boundary

Reviewer identity is explicit:

- `internal_model` is development feedback and cannot be independent;
- `independent_model` is a separately operated model critique, not expert
  review;
- `independent_expert` requires a cleared conflict check.

Model records include provider and model identity. No model-only round can pass
the independent-expert gate. Independent pre-submission closure requires at
least two unique independent experts, a response covering every admitted
concern, a new registered paper revision when concerns exist, and verification
by each original reviewer on the exact revised paper bytes.

Every record states `official_decision_authority=false` and
`scientific_quality_established=false`. Even an independently closed round is
pre-submission evidence; only the conference process can issue an official
decision.

## CLI

Prepare a review packet without calling a model:

```bash
.venv/bin/scitaste project paper review prepare \
  --project-id <project-id> --review-id <review-id> \
  --paper-directory <registered-paper-directory> \
  --venue-taste-profile configs/writing/venues/iclr-2027/taste.yaml \
  --scope development --expected-revision <revision> \
  --outputs-root outputs --dry-run
```

Remove `--dry-run` to register the packet. Reviewer reports, author responses,
and reviewer verifications are supplied as typed JSON with `import-report`,
`respond`, and `verify-response`. `status` independently rehashes the complete
round before returning it. Import commands validate their input before an
atomic project write; they intentionally do not accept `--dry-run` as a
substitute for creating a valid record.

```bash
.venv/bin/scitaste project paper review status \
  --project-id <project-id> --review-id <review-id> \
  --outputs-root outputs
```

Review concerns can also be projected through the existing action router. That
projection creates research obligations for evidence, method, claim, or
communication work; it does not directly mutate canonical state or close a
concern with prose alone.

## Bounded model reviewer

`venue-paper-review` is a proposal-only model node for an exact anonymous paper
packet. Its input binds the packet hash, paper-text hash, registered claims,
known sections, permitted evidence types, and the four venue questions. Its
output contains review content only; it cannot choose its identity, claim to be
an expert, add a numerical conference score, call tools, modify the paper, or
close concerns.

Build an exact runtime configuration before authorizing any provider call:

```bash
.venv/bin/scitaste project paper review runtime-config \
  --project-id <project-id> --review-id <review-id> \
  --profile-set configs/model_nodes/runtime_profiles.deepseek_v41_venue_review_v2.yaml \
  --profile-id deepseek-v41flash-venue-review \
  --backend-config <ignored-local-backend-config.yaml> \
  --permitted-evidence-type matched-method-comparison \
  --expected-revision <revision> --output <ignored-runtime-config.json> \
  --outputs-root outputs
```

This operation is network-free. It verifies the registered paper bytes and
review round, freezes the permitted evidence vocabulary in the hashed node
input, binds the paper packet to the immutable state projection, loads a
content-addressed profile, and writes a no-secret runtime config without
overwriting an existing file. `model-node runtime plan` can then validate that
config without provider access; live execution still requires every independent
runtime switch.

The deterministic adapter converts an accepted proposal into a
`VenueReviewReport` with `reviewer_kind=internal_model`, explicit provider/model
identity, and a self-hash. The CLI imports it with:

```bash
.venv/bin/scitaste project paper review import-model-report \
  --project-id <project-id> --review-id <review-id> \
  --proposal <venue-paper-review-proposal.json> \
  --report-id <report-id> --reviewer-id <reviewer-id> \
  --provider deepseek --model deepseek-flash \
  --expected-revision <revision> --outputs-root outputs
```

The current DeepSeek V4.1 Flash review profile and inert, peak-priced backend
example reserve a 32,768-token output ceiling for this whole-paper node. The
retained V4 profile is historical and must not be silently relabeled as V4.1.
This is neither the old 2,048-token probe limit nor a global SciTaste setting.
The backend remains `live_enabled=false` in Git; a local ignored runtime config
and explicit live switches are still required. A model report may close a
development round after verified revision, but it never satisfies independent
expert review.

## Lifecycle projection

`scitaste project lifecycle status` verifies the project registry and derives
eight ordered gates:

1. native idea/discovery;
2. native evidence;
3. continuous source-run lineage from idea and evidence into the paper;
4. a registered Stage 17+ paper;
5. deterministic venue submission eligibility;
6. admitted review reports;
7. reviewer-verified response closure;
8. two-expert independent pre-submission closure.

The lineage rule is deliberately strict. Unrelated discovery, evidence, and
paper artifacts stored under the same project cannot be combined into a false
idea-to-paper claim. The project homepage renders the same eight gates as a
Generation as Content lifecycle rail, backed by the exact registered evidence
rather than a manually entered completion percentage.
