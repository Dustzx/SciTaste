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
  --venue-config configs/writing/iclr2027_submission_v1.yaml \
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

`eligible_for_submission` means these deterministic packaging checks passed; it
does not certify novelty, factual correctness, external-review acceptance, or
scientific effectiveness. The registered paper therefore remains
`publication_ready: false` until those separate obligations close.
