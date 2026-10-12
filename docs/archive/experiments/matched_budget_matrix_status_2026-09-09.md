# Phase 9 exact-protocol matrix status — 2026-09-09

## Result

The current formal matrix is operationally **0/48**, not 1/48. A read-only
repository scan found 21 `study_results.json` files, but every one belongs to a
different protocol fingerprint. No historical result was silently adopted.

Current identity:

- study: `scitaste-matched-budget-v1`;
- protocol SHA-256:
  `ce09bf7d3ad22db09d40fc4368b03e3b903b3087b571cc1ecfecbb081690587c`;
- plan SHA-256:
  `c510998914b7be5a2874698478b73131c7483b44d4128b1a75a84947581d22d5`;
- planned cells: 48;
- integrity-verified current records: 0;
- valid external reviews: 0;
- status: `incomplete`, `headline_eligible=false`;
- status projection SHA-256:
  `27c46a4efd1d90a9527cc31e8b38e59a321e20d0b9864128853782feea2cdbfe`.

The first proposed execution batch is the complete four-condition block for
`diagnosis-friendly-v1`, seed 7, repetition 0. The CLI reports exact cell IDs so
the project runner can launch that matched block without selecting cells by
directory recency.

## Why the earlier Base success does not count

The real Base acceptance completed under protocol
`20ee06e9da9400a60d51732a774da4761af273f5ee4bad95d1804004405eaf30`.
It remains evidence that the adapter once completed Stage 8–18 in one runner
lifecycle. Later correctness fixes changed the formal implementation pin and
therefore the protocol, plan, cell, and blind identities. Importing that result
into `ce09...` would compare non-identical systems and violate the preregistered
contract. It is retained as historical engineering evidence only.

## Implemented status boundary

`scitaste study status` now:

1. discovers project-owned aggregate result files without launching a provider;
2. classifies exact, foreign, and invalid protocol sources;
3. admits exact-protocol records only after the run manifest, cell checkpoint,
   request, aggregate/owned execution record, and all checkpoint evidence bytes
   revalidate;
4. rejects linked/escaping evidence, tampering, unknown cells or blinded review
   identities, and conflicting duplicate records;
5. reports the next incomplete matched task/seed/repetition block and the next
   review block separately;
6. writes nothing unless an explicit `--output` path is supplied.

The existing local v9 record was also inspected against its own protocol. Its
run and cell identities revalidated, and it was correctly counted as one failed
cell with 15 missing cells after the RTX 3090 Xid 79 event. This cross-check
shows that the formal 0/48 result comes from protocol incompatibility rather
than failure to discover project-owned records.

## Verification

- focused matched-study tests: 55 passed;
- complete repository suite: 967 passed;
- Ruff format and lint: passed;
- `git diff --check`: passed;
- network/model calls: zero.

This is an execution-readiness and evidence-accounting result. It is not a
research-effectiveness result and does not replace the 48 real cells or the
condition-blinded external panel.
