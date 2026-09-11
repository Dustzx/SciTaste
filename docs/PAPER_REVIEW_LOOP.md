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

The additive `evidence-paper-revision` node enforces the same boundary at the
long-form manuscript layer. It may revise text-only concerns and integrate new
evidence only when a later project-state proof binds the new evidence, target
claims, evidence type, and any completed experiment. Without that proof, the
typed treatment remains pending and the node is not invoked when every concern
is blocked. Even a proof-backed revision is only a manuscript proposal: review
closure still requires a registered new paper, an author response, and exact
verification by the original reviewer.

An already registered, substantive venue paper does not have to be regenerated
to enter this loop. First adopt its exact Markdown, bibliography, and
whole-paper argument contract as a semantic source:

```bash
.venv/bin/scitaste project paper adopt-for-revision \
  --project-id <project-id> --paper-directory <paper-directory> \
  --run-id <adoption-run-id> --source-commit <40-character-commit> \
  --expected-revision <revision> --outputs-root outputs --dry-run
```

The adopter detaches renderer-owned citation commands, binds every cited key to
the registered bibliography, maps contract claims and material limitations,
and then replays current semantic draft admission. It preserves normalized
reader-facing prose exactly while deliberately assigning zero evidence and
marking every adopted claim unsupported. Removing `--dry-run` publishes the
self-hashed source input and proposal as a zero-model-call project run; it does
not rewrite the paper or establish scientific effectiveness.

Compile the exact revision-node input after reports have been admitted:

```bash
.venv/bin/scitaste project paper review revision-input \
  --project-id <project-id> --review-id <review-id> \
  --source-adoption-run-id <adoption-run-id> \
  --target-manuscript-id <new-paper-directory> \
  --evaluation-evidence-run-id <optional-formal-evidence-run> \
  --expected-revision <revision> --output <new-revision-input.json> \
  --outputs-root outputs
```

This read-only compiler rehashes the adopted paper and complete review round,
normalizes only exact section-label spellings such as `evaluation-results` to
`Evaluation Results`, and partitions concerns into text-only, proof-backed, or
blocked sets. Formal evidence is admitted only through a previously verified
evaluation-to-research-state transition from the same review round. Numeric
tokens become writable only when they already occur in the source paper or in
an admitted evidence summary. The source title is immutable unless a separate
typed input explicitly authorizes title revision; the project compiler keeps
that authority disabled. The optional output is created exclusively and is
never overwritten.

An accepted revision is materialized without another model call:

```bash
.venv/bin/scitaste project paper build-revision \
  --project-id <project-id> --review-id <review-id> \
  --directory-name <new-paper-directory> \
  --run-id <revision-run-id> --invocation-id <accepted-invocation-id> \
  --bibliography <verified-references.bib> --stage 19 \
  --expected-revision <revision> --outputs-root outputs
```

This command replays the model-node ledger and current admission rules; binds
the source paper draft, revision, or deterministic adoption trace, packet,
every report, target manuscript, and
bibliography; and rehashes each closure proof's project-owned opening/closing
`ResearchState` plus completed experiment result. It emits
`PAPER_REVISION_TRACE.json` beside the reader-facing Markdown, TeX, and PDF.
A proof lacking project-relative state locators remains usable only as advisory
node input and cannot cross this materialization gate.

Each `addressed` response resolution declares one basis: `prose_revision`,
`registered_evidence`, or `registered_experiment`. Hard concerns must name the
exact trace-bound proof, evidence IDs, and experiment IDs. `contested` and
`accepted_limitation` remain legitimate response dispositions but cannot claim
evidence closure. When an original reviewer marks a hard concern closed, its
verification must bind that same proof hash. Round inspection repeats these
checks, so an older or manually edited response cannot retain a false closed
status.

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

The deterministic adapter converts only an accepted, chain-verified runtime
entry into a `VenueReviewReport` with `reviewer_kind=internal_model`, explicit
requested and returned identities, request/result/recording hashes, profile and
prompt identity, and a report self-hash. The primary CLI path names the owning
run and invocation; provider, model, and proposal content are derived from the
verified ledger rather than typed by the operator:

```bash
.venv/bin/scitaste project paper review import-model-report \
  --project-id <project-id> --review-id <review-id> \
  --report-id <report-id> --reviewer-id <reviewer-id> \
  --run-id <project-run-id> --invocation-id <model-node-invocation-id> \
  --expected-revision <revision> --outputs-root outputs
```

The importer replays the complete model-node ledger and rejects a failed,
planned, rejected, missing, duplicate, wrong-node, wrong-round, cross-packet, or
identity-drifted entry. The older `--proposal --provider --model` mode remains
readable for historical workflows, but it has no runtime-ledger provenance and
should not be used for new project evidence.

The current DeepSeek V4.1 Flash review profile and inert, conservatively
peak-priced backend example reserve a 32,768-token output ceiling for this
whole-paper node. DeepSeek's 2026-09-11 official catalog names callable ID
`deepseek-flash`, version `DeepSeek-V4.1-Flash`, and explicitly states that the
older `deepseek-v4-flash` name is compatibility-routed to V4.1. Older profile,
proposal, and run bytes remain immutable history and are never relabelled.
This is neither the old 2,048-token probe limit nor a global SciTaste setting.
The backend remains `live_enabled=false` in Git; a local ignored runtime config
and explicit live switches are still required. A model report may close a
development round after verified revision, but it never satisfies independent
expert review.

The v3 reviewer prompt carries a closed-world contract in both the request
payload and generated JSON Schema. Claim IDs, section IDs, evidence types, and
action types are restricted to the exact current packet/policy vocabularies;
empty vocabularies permit only `[]` or `null`. A concern's category must also
match the deterministic review-action route, and experiment-producing actions
must carry coherent experiment/evidence flags. Schema-valid but invented or
internally contradictory concerns therefore remain untrusted and fail closed
rather than entering a paper round.

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
