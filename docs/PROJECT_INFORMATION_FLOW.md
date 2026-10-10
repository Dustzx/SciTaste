# Project information flow for scientific writing

SciTaste should keep two truths distinct: the project remembers everything that
matters for audit, while the paper shows only what the reader needs to evaluate
its scientific claims. The self-development project's live editorial index is
`outputs/projects/scitaste-self-development/docs/README.md` (an ignored local
output); this file defines the reusable framework behavior.

## Information levels

| Level | Unit | Allowed transition |
|---|---|---|
| L0 source | Paper, dataset, model output, run, review, transcript | Record identity, scope, and original bytes; do not infer a result. |
| L1 verified finding | Protocol-bound result with failures and uncertainty | Check scorer, population, comparator, exclusions, and source identity. |
| L2 calibrated claim | Supported, contradicted, or unresolved scientific proposition | Relate finding to estimand and external validity; retain counterevidence. |
| L3 manuscript carrier | Figure, result table, worked example, algorithm, or proof | Select the minimum carrier that lets a reader judge L2. |
| L4 narrative | Title, abstract, section argument, conclusion | Include only claims backed by appropriate L3 carriers. |

The transition is revisited when a result or reviewer concern changes the
claim. It is not a monotonic confidence escalator: new evidence can demote or
contradict a claim, forcing title, abstract, figures, and conclusion to change
together. A proposal-only model may recommend a promotion/demotion with reasons;
the evidence and project-state layer validates identities and preserves history.

## Placement and bounded context

The project holds four small canonical editorial documents: scientific case,
evidence ledger, manuscript map, and decision index. Each document has one
question and an update trigger; raw transcripts and detailed per-run records
stay outside. A writing node should receive a bounded projection of the active
thesis, supporting and contradicting evidence, relevant limitations, and the
section's carrier duty. It should not receive every project log or infer that
every retrieved source belongs in the paper. Retrieval is for finding relevant
source records; promotion is a separate judgment about validity and value.

Main text explains the scientific question, method, estimand, decisive evidence,
and interpretation. Appendix holds material secondary analysis and protocol
choices. Reproduction artifacts hold commit hashes, task IDs, prompts, command
lines, receipts, and raw traces. A detail may be promoted when it changes a
scientific inference; neither exactness nor availability alone is sufficient.

## Current implementation boundary

The existing `PaperArgumentContract` and evidence-paper nodes bind claims,
evidence, limitations, and presentation carriers. The deterministic Writing
Taste assessor now flags obvious repository/task metadata in ordinary prose;
the semantic Writing Taste node is instructed to reason about placement and
missing carriers. These are *advisory* and do not establish paper quality.

The next framework increment is a project-owned structured editorial state that
persists L1–L3 links, records promotion/demotion decisions, and projects bounded
section-specific context into drafting and revision. It must update the paper
only after a claim/carrier change, with stale-manuscript detection. Merely adding
a regex, prompt, or central mega-document would not implement this behavior.
