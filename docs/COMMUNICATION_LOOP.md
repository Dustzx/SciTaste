# Communication Loop

Phase 6 turns supported evidence into an auditable paper structure and routes
reviewer feedback to the research action it actually requires.

```text
Evidence
→ Narrative taste review
→ Section and paragraph contracts
→ Rhetorical-role taste retrieval
→ Contract-backed draft
→ Decomposed writing critics
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
- Writing taste is retrieved by rhetorical role. Unrelated role cases are not
  returned merely because their topical words overlap.
- Substance, narrative, claim/evidence, redundancy, style, venue style,
  terminology, citation, and global coherence are separate critics.
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
control and provenance, not language-model writing quality. A future live writer
must consume the same contracts and critic outputs without changing routing.
