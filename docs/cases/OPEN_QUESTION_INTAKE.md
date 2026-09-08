# Open-question intake self-iteration

This iteration addresses the next mainline gap identified after restart-safe
Full Workflow finalization: stage execution was project-owned, but a caller still
had to supply four configuration-driven scenario files without an explicit,
auditable research-question contract.

The new `ResearchBrief` fixes the open question, objective, project identity,
exact executable budget, required evidence types, success criteria, constraints,
and prohibited claims. Mutation-free inspection compares that contract with the
registered Discovery, Evidence, Communication, and Figure scenarios. Only a
closed match produces a self-hashed `WorkflowLaunchPlan` with `ready` status.
Models are recorded as `proposal-only`; deterministic admission retains execution
authority.

Formal execution copies the exact brief and four scenarios into the owning
`runs/<run-id>/intake/` directory and stages consume those copies. The run and
summary bind the launch-plan hash. Changed sources between inspection and copy,
unauthorized evidence requirements, budget mismatch, stored-input tampering, or
resume-plan drift all fail closed. An interrupted intake may fill only missing
artifacts whose siblings still verify; repair of a completed run is read-only for
the intake transaction.

The committed offline example is
`configs/workflows/full_open_question_offline_v1.yaml`, backed by
`configs/research/conflict_control_open_question_v1.yaml`. Its output remains an
`integration-fixture`, not a substantive paper. This v1 closes the ownership and
admission boundary for registered scenarios; it does not claim that the question
autonomously generated those scenarios or that the resulting scientific idea is
effective.

Implementation commit `dcfeda23484fa9a83b015cb7ae99adbebcc043a5`
passed 25 focused intake/Full Workflow tests. A clean detached worktree at that
exact commit passed 875 repository tests with one environment-dependent UI test
skipped because the clean tree intentionally had no local `outputs` fixture;
combined statement and branch coverage was 83 percent. Ruff format/check and
repository diff checks passed. No live model call, API token, API cost, or GPU
time was used.

The self-development project records this result at revision 198 in run
`2026-09-08__scitaste-native__open-question-intake-v1__seed-07`; its canonical
evidence is `mainline/evidence.json`, and the trusted project surface is
`surfaces/project-overview-rev198/`. The selected paper remains the ICLR 2027
submission draft v2, so an engineering iteration cannot silently replace the
reader-facing manuscript.
