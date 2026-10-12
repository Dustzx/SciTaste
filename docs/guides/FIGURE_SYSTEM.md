# Figure System

Phase 7 turns a scientific claim and its supporting prose into editable,
critic-reviewed vector artifacts.

```text
Paper/claim state
→ Figure need assessment
→ claim-linked Figure Contract
→ visual-role taste retrieval
→ bounded draft request
→ semantic object reconstruction
→ initial SVG/draw.io
→ communication + aesthetics critics
→ object-level patches
→ final SVG/draw.io
```

## Figure Contract

The contract records the figure purpose, target claim IDs, intended reader
takeaway, required and optional entities, required relations, forbidden
emphasis, panel plan, and reference IDs. Entity, relation, and panel references
are validated before rendering; target claims resolve against the canonical
`ResearchState`.

The SVG exporter assigns stable IDs and semantic `data-*` attributes to every
panel, entity, and relation. The draw.io exporter writes uncompressed
`mxGraphModel` XML whose nodes and edges remain independently editable.

## Review and patching

The critic reports ten dimensions: purpose clarity, argument support, hierarchy,
density, panel logic, text/figure consistency, redundancy, misleading emphasis,
editability, and publication readiness. Each finding is explicitly classified as
communication or aesthetics so cosmetic feedback cannot obscure a scientific
misrepresentation.

Patch history names the object, field, old value, new value, and rationale. The
workflow reruns all critics after patching and rejects a final artifact with any
remaining warning.

## Offline acceptance

```bash
scitaste figure build \
  --config configs/visual/mechanism_demo.yaml \
  --output outputs/figure-demo \
  --seed 7
```

The fixture intentionally over-emphasizes the executor even though the claim says
SciTaste owns research decisions. Two critic dimensions detect that shared defect;
one deduplicated object patch restores normal emphasis. The final SVG and draw.io
files pass all ten dimensions. Draft generation is deterministic and offline; a
future image-model adapter must preserve this same contract and semantic
reconstruction boundary.
