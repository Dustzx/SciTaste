# Knowledge RAG publication preacceptance status — 2026-09-03

## Outcome

Knowledge RAG has not yet earned a clean end-to-end formal acceptance. Attempts
7–14 progressively exercised the selected-experiment, analysis, and outline
gates with real Qwen3.8-Max calls and real CPU experiment execution. Each failed
directory remains explicitly inadmissible and is never resumed or promoted into
a formal result.

The implementation currently passes 183 repository tests in the clean formal
worktree. AutoResearchClaw remains unmodified at
`12d3fd809fa9658e91a0328c3280a0e462c78386`.

## Latest verified behavior

- Attempts 7–10 exposed equivalent-contract, assignment-style seed, Stage 10
  regeneration, and summary-line seed parsing boundaries before paper spending.
- Attempt 11 passed the source-verified experiment and Stage 14 analysis gates,
  then stopped before drafting on a negated N=1 instruction.
- Attempts 12 and 14 passed the experiment gate, then stopped on explicitly
  negated/corrective analysis language.
- Attempt 13 emitted a complete machine matrix but exposed ambiguity between a
  decimal `seed` factor effect and an integer seed identifier.
- With the current implementation, isolated copies of v12 and v14 analysis pass
  the analysis audit; an isolated v11 copy passes both analysis and outline
  audits. These are adapter regression results, not retrospective formal runs.

The latest clean dry-run protocol hash before provider failure was
`ce09bf7d3ad22db09d40fc4368b03e3b903b3087b571cc1ecfecbb081690587c`;
its plan hash was
`c510998914b7be5a2874698478b73131c7483b44d4128b1a75a84947581d22d5`.
It contained 48 planned cells and no readiness blocker, with Sibyl and AI
Scientist-v2 still explicitly unavailable.

## Current external blocker

Attempt 15 failed before billable token accounting. A minimal diagnostic request
to the same Bailian model endpoint returned HTTP 400 with provider code
`Arrearage` and stated that account access is denied until the account is in good
standing. The adapter recorded zero tokens and zero cost for the failed run.

After the provider account is restored, the next admissible action is a new
single-cell Knowledge RAG run with `--max-cells 1` from Stage 8 through Stage 18.
No failed attempt should be resumed. A successful cell will still be only one
preacceptance observation; the four-condition preacceptance, all 48 cells, and
external blinded review remain outstanding before headline conclusions.
