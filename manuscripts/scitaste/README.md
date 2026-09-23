# SciTaste framework manuscript

`main.md` is the tracked source for **SciTaste: Selective Transfer of Scientific
Experience in Autonomous Research**. `references.bib` contains its primary
references. `argument_contract.yaml` binds the draft's paper-level question,
claims, evidence carriers, entry points, and material limitations to registered
research evidence. The current title is deliberately bounded because the first
registered matched ResearchHarness Taste intervention is complete but does not
authorize an improvement claim; it is not an execution of the independent
SciTaste Native lifecycle. `assets/fig1-scitaste-control.svg` is the canonical editable
source for the first figure and the PDF is the publication-rendering asset. The
older draw.io file is retained only as design history; it is not authoritative.

The reader-facing Markdown, generated TeX, compiled PDF, bibliography, build
record, and manuscript assessment are registered as a versioned paper bundle
inside `outputs/projects/scitaste-self-development/papers/`. Generated files are
not committed. The current artifact is a research working draft, not a
publication-ready or empirically accepted paper. Development and engineering
effects are quarantined from the rendered claim-bearing results. The frozen
SciTasteBench diagnostic, Outcome Learning study, and matched 10-domain
ResearchClawBench comparison are reported as null or adverse evidence;
independent construct validation and a successful selective-transfer mechanism
remain open.

`result_carriers.yaml` is the paper's result-table contract. It separates
headline system comparisons, matched causal ablations, mechanism diagnostics,
and ecological leaderboard context before prose is rendered. Run

```bash
python scripts/audit_manuscript_result_carriers.py \
  --manuscript manuscripts/scitaste/main.md \
  --contract manuscripts/scitaste/result_carriers.yaml
```

before a paper build. Every Markdown result table must carry a
`result-carrier` marker; unregistered tables and main-text ecological
leaderboards fail the gate.
