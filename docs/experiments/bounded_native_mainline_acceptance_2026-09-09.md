# Bounded native mainline acceptance — 2026-09-09

## Scope

This acceptance closes SciTaste's bounded first-party product path from an open
research brief to a project-owned workflow and evidence-bound interaction layer.
It covers three integrated changes:

1. `b856a14` adds deterministic selection from a content-bound four-stage
   scenario catalog, a post-evidence Tool Intelligence hook, and a shared typed
   model ledger for source generation, evidence advice, and tool planning.
2. `9d763dd` carries an audited Generation as Content proposal through explicit
   deterministic approval or rejection and produces only a bounded handoff.
3. The documentation commit containing this record aligns the public product,
   architecture, roadmap, and self-development board with those boundaries.

The validated predecessor was `6d84f17`. No live provider, API credential, API
cost, or GPU was used by this acceptance.

## Executed acceptance

- `python -m ruff format --check .`: passed for 332 files.
- `python -m ruff check .`: passed.
- `python -m pytest -q --cov=scitaste --cov-report=term`: 950 passed in
  252.59 seconds; combined statement/branch coverage rounded to 83 percent.
- `node --check src/scitaste/generative_ui/static/app.js`: passed.
- `python -m build --wheel`: built `scitaste-0.1.0-py3-none-any.whl` with 169
  entries. All six required receiver assets—HTML, CSS, JavaScript, locale loader,
  and both locale catalogs—were present.
- `tests/generative_ui/test_locale_assets.py`: 6 passed.
- `git diff --check`: passed.

The repository suite executes real offline Full Workflow integration cases, not
only parser smoke tests. It materializes project runs, executes the admitted CPU
experiment through the configured isolation boundary, derives evidence,
constructs communication/figure outputs, registers the integration paper, and
verifies resume/tamper behavior. The Tool Intelligence case additionally issues
a durable lease and calls one exact project-owned read-only evidence handler.

## Defect discovered during closure

The first complete run exposed one real composition defect: a native-code
extension ledger entry could not be type-validated when a later built-in evidence
advisory opened the same ledger. The fix propagates the Full Workflow extension
registry through later model/tool nodes. A replacement integration test now runs
source generation and evidence advice consecutively and verifies both entries;
another test verifies evidence advice followed by Tool Intelligence. No ledger
validation was weakened or skipped.

## Accepted product boundary

The bounded native path can now:

- admit an explicit question, constraints, budget, evidence contract, and success
  criteria before mutation;
- select one complete registered research trajectory deterministically and own
  its exact catalog/scenario bytes;
- carry one `ResearchState` through Discovery, Evidence, Communication, review
  resolution, and editable Figure production;
- retrieve local Knowledge, admit and isolate a measured experiment, and package
  a project-owned Markdown/TeX/PDF integration artifact;
- invoke optional proposal-only semantic/source nodes and one leased read-only
  Tool Intelligence action through durable ledgers; and
- expose project evidence through Generation as Content, issue audited proposals,
  and record explicit bounded controller handoffs without UI-side execution.

## Gates intentionally still open

This record is engineering/product acceptance, not scientific-effectiveness or
publication acceptance. It does not satisfy the remaining Phase 9 exit gate:

- all 48 real commit-pinned matched-budget cells without manual continuation;
- a valid independent blinded expert panel;
- open-web retrieval and licensed snapshot governance;
- arbitrary portable environment construction and iterative provider-backed code
  repair;
- broader open-ended model-generated analysis, writing, and figures; or
- independent evidence that SciTaste is better than pinned external systems.

Sibyl and AI Scientist-v2 remain explicitly unavailable until real adapters are
implemented and accepted. No surrogate implementation or synthetic review is
used to mark those external gates complete.
