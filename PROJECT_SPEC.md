# SciTaste project specification

The authoritative source for implementation is **SciTaste Full Project Codex
Specification v1.1**, supplied with this repository workspace as
`../SciTaste_Full_Project_Codex_Spec_v1.1.md`.

This file records the repository contract so development does not silently drift
from that source:

1. SciTaste owns research control; execution substrates only execute selected
   actions.
2. The canonical control cycle is Observe → Generate Candidate Actions → Judge
   with Scientific Taste → Select → Execute → Update Research State.
3. Discovery is one adaptive Hypothesis–Probe–Reformulate loop. Idea-First and
   Evidence-First behavior are outcomes, not separate hard-coded pipelines.
4. The first complete system is training-free: base model, curated taste cases,
   retrieval, stage-specific critics, and the controller.
5. Knowledge and taste stores remain separate.
6. All state transitions and decisions are persistent and auditable.
7. Contradictory evidence is retained and may trigger evidence-backed ideation.
8. Work proceeds in the ordered phases and acceptance gates defined in
   [`docs/ROADMAP.md`](docs/ROADMAP.md).

Specification version: `v1.1`

Implementation baseline: `v0.1.0 / Phase 0–4 foundation`
