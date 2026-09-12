# Decision-gap-driven Scientific Reference mining

Status: implemented and exercised with a real GLM-5.3-Flash query plan plus
credential-free OpenAlex and Crossref metadata. The current accepted cohort is
ready only for a separately authorized source-quality screen. No source body,
GPU, human review, or experiment was used.

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
profiles have no tool permission. Query schema 1.1 additionally freezes a
metadata-anchor vocabulary, a minimum anchor count, and a maximum query length.
The v2 prompt asks for short bibliographic queries rather than prose describing
how somebody else should search. Accepting a proposal still never performs the
search; the connector has its own explicit network switch and resource envelope.

## First-party metadata connector and replay

`scitaste evaluation reference-search` executes an accepted live-ledger plan
against both OpenAlex and Crossref. It makes credential-free HTTPS GET requests,
disables redirects, requests a fixed metadata field set, bounds every response
and the complete transaction, and rejects a work object containing abstract,
body, content, or full-text fields. Every request URL and raw metadata response
is retained by hash in an atomically published bundle. A failed transaction
does not publish a partial result.

The connector reconciles DOI identities across indexes. Agreeing titles become
`cross-index-corroborated`; contradictory titles become
`cross-index-conflict` and cannot enter the cohort. Administrative records such
as peer-review reports, supplementary files, and numbered conference abstracts
are also excluded at the metadata boundary. These checks are identity and
record-type hygiene, not source-quality judgments.

`scitaste evaluation reference-search-replay` recompiles an entire verified
bundle from its frozen responses. Its receipt names the source receipt hash and
requires `network_request_count=0`. This makes selector changes comparable on
exactly the same search evidence and prevents a better network sample from being
misreported as a better Scientific Taste rule. Receipt schema 1.3 binds the
exact NEED, PROPOSAL, CONFIG, RUN, REPORT, normalized request URLs, and response
bytes. Schema-aware hashing preserves verification of earlier 1.1 and 1.2
receipts instead of silently rewriting historical evidence.

## Coverage-controlled cohort freezing

Each search batch records only metadata hypotheses: source group, locator,
candidate decision patterns, possible evidence role, domain facet, and rights
and isolation state. `source_body_read=false` and `quality_assessed=false` are
schema invariants. Held-out, self-development, rights-blocked, and unknown-
isolation results cannot enter the selectable pool.

The deterministic compiler selects candidates greedily by marginal coverage of
the registered decision patterns, evidence roles, all six query families, and
domains. A domain claim inherited from a query is not enough: schema-1.2 runs
must ground each covered domain in its separately registered title-anchor set
and minimum match count. This prevents a record containing only the word
"autonomous" from establishing coverage of autonomous research. Source-group
novelty and new-family coverage precede query/title overlap, provider
corroboration, result rank, and a stable hash. Normalized duplicate titles are
selected at most once. A hard per-source group cap prevents many records from
one paper, repository, review thread, or trajectory from masquerading as
diversity. Venue and citation fields may be retained as discovery metadata, but
they never enter the selection priority; changing them leaves the selected
cohort unchanged.

This is a bounded set-cover heuristic, not a learned quality score. A later
Reference Quality rejection is expected and remains visible.

## Saturation and stopping

Search stops only after all registered decision-pattern, evidence-role, query-
family, grounded-domain, and source-group floors are reachable and at least two
consecutive completed batches add no required scientific coverage. A new source
identity resets saturation only until the preregistered source-group floor is
met: an open scholarly index can always return another paper, so total-literature
exhaustion is neither claimed nor used as a stopping rule. The owner can set a
longer two-to-five batch saturation window and a finite batch ceiling before
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

## Real self-iteration evidence and current boundary

The self-development project used this component on 2026-09-13. The first live
plan and 36-request search were retained as a failed diagnostic: its selector
admitted unrelated records and one DOI/title conflict. Replaying the same 281
candidates exposed further failures in relevance, domain grounding, and record
type handling. None was relabelled as success.

The repaired run used one rejected and one accepted GLM-5.3-Flash proposal. The
accepted proposal contains 12 concise queries spanning all six families. Four
OpenAlex/Crossref passes made 48 requests, retained 350,848 response bytes, and
parsed 473 first-seen candidates. The record-aware, conjunctive-domain v6
selector replayed that exact receipt with zero model and zero network calls. The
v7 integrity replay kept the same frozen transaction and selection while binding
all control and derived files under receipt schema 1.3. It froze 12 source
groups, covers all six families and all three grounded domains, and reports
`cohort_ready_for_reference_quality=true`. V6 remains a valid historical
receipt and is marked superseded, not failed.

This is connector and cohort-construction evidence, not evidence that the 12
sources are high quality or that SciTaste improves research. Several candidates
are deliberately broad comparator or transfer records. Source bodies have not
been accessed, and the prestige-blind Reference Quality, independent human
review, Taste abstraction, and H0--H3 outcome studies remain later gates. The
AAAR, ARIES, OpenReview, and MLR-Bench source manifest remains a separate
hand-curated screen and is not retrospective proof that autonomous mining works.
