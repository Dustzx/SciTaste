# Communication Loop

Phase 6 turns supported evidence into an auditable paper structure and routes
reviewer feedback to the research action it actually requires.

```text
Evidence
→ Narrative taste review
→ Section and paragraph contracts
→ Hierarchical Writing Taste retrieval
→ Contract-backed draft
→ Decomposed writing critics
→ Deterministic and optional semantic Writing Taste review
→ Structured reviewer concerns
→ Research obligations
→ Evidence / method / claim / communication action
→ Obligation closure
→ Paper revision
```

## Invariants

- Writing does not start until the Narrative Spine references known evidence and
  only supported or partially supported contribution claims.
- Section and paragraph contracts contain claim and evidence identifiers checked
  against the canonical `ResearchState`.
- Writing taste is retrieved by writing level, section type, rhetorical role,
  transition, claim strength, citation density, dimension, venue, and context.
- Scientific integrity, claim calibration, and positive scope outrank
  anti-defensive style. Material limitations cannot be omitted or demoted by a
  model proposal.
- Substance, narrative, claim/evidence, redundancy, style, venue style,
  terminology, citation, and global coherence remain separate critics; a
  hierarchical Writing Taste assessor adds cross-level diagnoses without
  replacing them.
- An evidence-bearing reviewer concern creates an obligation and routes to the
  Evidence Loop. A rewritten paragraph cannot close it.
- Evidence closes an obligation only when it is new, targets the relevant claim,
  and has the required evidence type.
- Closed obligations remain in state for audit even though the compatibility
  field is named `open_research_obligations`.

## Offline acceptance

```bash
scitaste write \
  --config configs/writing/reviewer_experiment_demo.yaml \
  --output outputs/communication-demo \
  --seed 7
```

The scenario starts with controlled pilot evidence, drafts Introduction and
Results from contracts, receives a missing-baseline concern, runs a matched
baseline through the existing Evidence Loop, closes the obligation, and writes a
second paper revision. `scitaste review` exposes the same complete acceptance
workflow for review-focused automation.

The generated prose is intentionally deterministic and minimal. It validates
control and provenance, not language-model writing quality. The optional
`writing-taste` semantic node can propose a bounded paper strategy and findings,
but it cannot edit the manuscript or suppress registered limitations. A future
live writer must consume the same contracts and critic outputs without changing
routing. See [`WRITING_TASTE.md`](WRITING_TASTE.md).

Project-owned venue reports enter this loop through
`project paper review route-state`. The command revalidates the complete review
round, requires a ResearchState owned by a registered project run, and publishes
a self-hashed routing run containing the routed state and routing record. It
opens one obligation per concern but records no new evidence, performs no model
call, and cannot close the review. Evidence-requiring concerns that omit an
evidence type receive fail-closed category defaults for comparative
effectiveness, matched external baselines, or multi-task validity.

After execution, `project paper review admit-evaluation-evidence` accepts only
the project's selected result when the registered assessment is formal,
complete, headline-eligible, and positive under every preregistered primary
contrast. It adds typed evidence and a completed experiment record to a new
immutable ResearchState revision, then closes only obligations from the named
routing run. Real external methods are required for baseline evidence; at least
two matched held-out tasks are required for multi-task evidence. A result that
does not bind a concern's target claim cannot close that claim-specific
obligation.

`project paper review evaluation-closure-proofs` converts each actually closed
experimental obligation into a self-hashed `PaperRevisionClosureProof` that
binds the opening state, closing state, result record, evidence IDs, and
experiment ID. The proof can enter the existing proposal-only paper-revision
node. It does not revise a paper, submit an author response, or close review;
those remain separate registered transitions, and only the original reviewers
can verify their concerns as closed.

## Venue-native submission gate

Research manuscripts can be packaged through an exact venue contract after the
content-level writing loop. For ICLR 2027, the contract binds the complete
official template ZIP by SHA-256 and admits only individually hashed style,
bibliography, and support files. It refuses unsafe ZIP paths, archive drift, and
unregistered substitutions.

```bash
export SCITASTE_ICLR2027_TEMPLATE=/absolute/path/to/iclr-2027-style-files.zip
.venv/bin/scitaste project paper build \
  --project-id <project-id> \
  --directory-name <paper-version> \
  --source manuscripts/<project>/main.md \
  --bibliography manuscripts/<project>/references.bib \
  --venue-config configs/writing/venues/iclr-2027/submission.yaml \
  --paper-archetype empirical-system \
  --expected-revision <revision> \
  --select --outputs-root outputs
```

The build first requires the source to pass the existing long-form research
draft gate. It then renders anonymous venue-native TeX, compiles with pdfLaTeX,
measures the main-text boundary from a renderer-owned label, and checks the
9-page limit, one-paragraph abstract, citation/BibTeX closure, required AI Use
Statement and its one-page limit, terminal statement order, duplicate BibTeX
keys, obvious identity markers, and internal audit markers. The bundle owns
the self-hashed venue, manuscript, and Writing Taste assessments plus the build
log and exact template assets. The Writing Taste assessment is also available
in paper-build dry-runs and is hash-bound by the registered paper manifest.

The venue submission config is co-located with `taste.yaml` and
`provenance.yaml`. A paper build automatically loads that sibling profile,
checks that its venue identity matches the template, selects only principles
applicable to `--paper-archetype`, and writes the self-hashed
`VENUE_TASTE_CONTEXT.json`. The context contains guidance supplied to semantic
review; it is not an automated judgment of whether the manuscript follows that
guidance. An unspecified archetype applies only cross-archetype principles and
records the conditional guidance it omitted.

`eligible_for_submission` means these deterministic packaging checks passed; it
does not certify novelty, factual correctness, external-review acceptance, or
scientific effectiveness. The registered paper therefore remains
`publication_ready: false` until those separate obligations close.
