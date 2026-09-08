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
