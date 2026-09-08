# Full Workflow finalization recovery self-iteration

This self-iteration closes a specific autonomy gap in `scitaste run full`: a
process interruption after Discovery, Evidence, Communication, and Figure had
all completed previously required manual inspection before paper publication
could continue. The intervention is engineering evidence only; it does not show
that the generated research or manuscript is scientifically effective.

Before publication, the workflow now writes a self-hashed `finalization/PLAN.json`
that binds the workflow configuration, all four stage records, final state,
reader-facing manuscript source, editable figures, and intended paper identity.
The registered paper manifest closes every declared file under a SHA-256 map.
Resume may therefore reuse a paper only after verifying all artifacts and the
manuscript assessment against that plan.

Failure injection covers five distinct boundaries. A summary-write interruption
reuses the already registered paper; incomplete unregistered paper files move
intact beneath `failed_attempts/finalization/paper/` before rebuilding; changed
registered paper bytes fail closed; a summary left by an interrupted completion
metadata update is archived before replacement; and a completed run with a
missing UI snapshot binding verifies all durable evidence before writing only
that view. Every accepted recovery executed zero completed research stages and
zero provider calls a second time.

Implementation commit `d614ed7353760a76f57aa4dbcb4096c7ed031ee5`
plus its repository-format follow-up `251d7d4` passed 33 focused Full Workflow
tests and 870 repository tests at 83 percent
combined statement and branch coverage. Ruff, repository diff checks, and the
immutable AutoResearchClaw pin
`12d3fd809fa9658e91a0328c3280a0e462c78386` also passed.

The canonical local evidence is
`outputs/projects/scitaste-self-development/runs/2026-09-08__scitaste-native__full-workflow-finalization-recovery-v1__seed-07/mainline/evidence.json`.
At revision 194, the self-development project selects that run while retaining
the ICLR 2027 submission draft as its current paper. No live model call, API
token, API cost, or GPU time was used for this recovery acceptance.

The remaining mainline autonomy gap is earlier in the trajectory: an open
research question still needs configuration-driven scenario inputs before Full
Workflow starts. Closing finalization prevents wasted repeated work, but it does
not yet turn those scenario fixtures into model-grounded autonomous planning or
supply Phase 9 effectiveness and external-review evidence.
