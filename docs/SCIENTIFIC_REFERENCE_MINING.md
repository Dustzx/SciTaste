# Decision-gap-driven Scientific Reference mining

Status: implemented at the query-planning, metadata-cohort, diversity, and
saturation boundaries. No search provider, source body, download, API, GPU,
human review, or experiment is invoked by this contract.

## What this layer solves

Reference quality cannot be recovered by taking the most famous or most
lexically similar papers. It also cannot be measured before looking at the
decision-bearing source content. SciTaste therefore treats finding and judging
references as two different scientific operations:

```text
current decision + evidence gaps
        │
        ▼
contrastive query plan ──► metadata-only broad search ──► frozen audit cohort
                                                               │
                                                               ▼
                                               prestige-blind Reference Quality
                                                               │
                                                               ▼
                                                grounded Taste abstraction
```

The mining layer maximizes the chance that the later quality screen sees
informative alternatives and failures. It does not call a candidate “high
quality.”

## Query portfolio, not one relevance query

The `reference-mining` proposal-only node receives a closed scientific decision:
the live alternatives, exact evidence-gap identities, desired decision patterns,
domain facets, and a finite search budget. It must cover six complementary query
families:

1. direct decisions;
2. alternatives or comparators;
3. negative or null results;
4. failures or limitations;
5. replications or reappraisals;
6. cross-domain transfer.

The required candidate pool explicitly includes challenge, boundary, and
alternative evidence roles. This prevents a fluent model from turning search
into a confirmation-only bibliography. The planner may adapt query wording, but
its schema cannot request tools or claim source quality. Deterministic validation
rejects missing families, invented targets, budget overflow, and explicit
prestige-ranking instructions.

Candidate API profiles are provided for GLM-5.3-Flash and DeepSeek Flash. Both
profiles have no tool permission. A controller must separately authorize and
record any future search connector; accepting a query proposal never performs
the search.

## Coverage-controlled cohort freezing

Each search batch records only metadata hypotheses: source group, locator,
candidate decision patterns, possible evidence role, domain facet, and rights
and isolation state. `source_body_read=false` and `quality_assessed=false` are
schema invariants. Held-out, self-development, rights-blocked, and unknown-
isolation results cannot enter the selectable pool.

The deterministic compiler selects candidates greedily by marginal coverage of
the registered decision patterns, evidence roles, and domains. Source-group
novelty breaks scientific ties before a stable candidate hash. A hard per-source
group cap prevents many records from one paper, repository, review thread, or
trajectory from masquerading as diversity. Venue and citation fields may be
retained as discovery metadata, but they never enter the selection priority;
changing them leaves the selected cohort unchanged.

This is a bounded set-cover heuristic, not a learned quality score. A later
Reference Quality rejection is expected and remains visible.

## Saturation and stopping

Search stops only after all registered decision-pattern, evidence-role, domain,
and source-group floors are reachable and at least two consecutive completed
batches add no new eligible source group or required coverage. The owner can set
a longer two-to-five batch saturation window and a finite batch ceiling before
search begins.

Three terminal states are distinct:

- `coverage-and-saturation`: the audit cohort can proceed to a separately
  authorized Reference Quality screen;
- `batch-budget-exhausted`: the search ceiling was reached, with missing
  coverage reported rather than silently relaxed;
- `search-incomplete`: available batches do not yet establish saturation.

Only the first can set `cohort_ready_for_reference_quality=true`. Even then, the
receipt grants no search, download, content-read, model, human-review, admission,
or experiment authority.

## Scientific role and evidence boundary

H0 compares content-grounded qualification with prestige-only selection from
the *same frozen broad pool*. Decision-gap-driven mining constructs that common
pool before either selection rule sees it, so the experiment does not favor
SciTaste by giving its arm a better search universe. Source count and downstream
budgets remain matched.

This mining policy is a method component and an efficiency/coverage safeguard,
not an additional confirmatory hypothesis. Diagnostics can report coverage,
duplicate yield, rejected-source reasons, and search cost. The title-level claim
still depends on H0--H3 outcomes under the registered evidence program.

## Current honest boundary

The implementation provides the typed node, deterministic validation, cohort
compiler, immutable content-free report, CLI, and bounded provider profiles. No
real search batches have been collected through it. The existing AAAR, ARIES,
OpenReview, and MLR-Bench source manifest remains a hand-curated metadata screen,
not retrospective evidence that autonomous mining works.
