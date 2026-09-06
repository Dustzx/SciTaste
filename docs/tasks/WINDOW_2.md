# Window 2 Dispatch: Tool Intelligence — Controlled Semantic Tools

Assignment token: `W2-tool-intelligence-20260906-r1`

Status: `active`

This dispatch is authorized directly by the project owner on 2026-09-06. It
follows the integrated project-scoped model-node runtime and implements the next
Tool Intelligence increment identified in `docs/INNOVATION_MAP.md`: more
first-party semantic tools and controlled execution profiles. The prior runtime
Epic was integrated into `main` as `37ee0ba` and must not be continued from its
old feature-branch head.

## Workspace

- worktree: `/home/good/zfx/papers/SciTaste-worktrees/tool-intelligence`
- branch: `feat/tool-intelligence-v1`
- base: the latest clean `main` containing this assignment token
- do not implement this Epic in `/home/good/zfx/papers/SciTaste`

Create the branch and worktree from the dispatch-bearing `main`. Do not merge,
push, or rebase; the main window owns integration.

## Objective

Deliver a production-quality, proposal-only Tool Intelligence vertical slice.
A bounded model node may propose an ordered plan over explicit first-party,
read-only semantic capabilities, or propose a repair for a previously rejected
structured payload. Deterministic code alone validates capability scope,
arguments, dependencies, budgets, state identity, and the repaired target
schema. No accepted model-node result may execute a tool, mutate canonical
state, authorize spending, open network access, or become an accepted result of
another node without that node's complete deterministic validation.

This Epic advances implementation substrate only. It does not establish an
autonomy or effectiveness claim and does not by itself satisfy ADR-022's pilot
acceptance gates.

## Owned paths

- `src/scitaste/model_nodes/**`;
- `tests/model_nodes/**`;
- `configs/model_nodes/**` for non-secret, disabled examples;
- `docs/TOOL_INTELLIGENCE.md`;
- the smallest compatibility changes required in
  `src/scitaste/model_node_runtime_cli.py` and focused integration tests.

Do not edit `full_workflow.py`, generative UI, project-runtime ownership code,
central roadmap/architecture/changelog/README documents, generated `outputs/`,
credentials, model weights, or `third_party/autoresearchclaw/**`. If an exit
gate genuinely requires one of those paths, stop and report the integration
change to main rather than expanding ownership.

## Work packages

### WP1 — Controlled capability contracts

1. Add strict, versioned, content-addressed contracts for a controlled semantic
   tool profile, per-tool permissions, typed proposal arguments, and ordered
   proposal steps. The initial catalog must contain only bounded read-only
   capabilities over project-owned data: Knowledge query, Evidence inspection,
   and registered-run comparison.
2. Make side effects explicit and fixed off for this version: no filesystem
   writes, process launch, network access, canonical-state mutation, or direct
   execution authority.
3. Bind permitted library/evidence/run identifiers and per-tool ceilings in the
   profile. Reject duplicates, unknown identifiers, unbounded queries, invalid
   dependencies, cycles, forward references, and profile/policy allowlist drift.
4. Preserve all existing public model-node recordings and request fingerprints;
   introduce additive models or explicit schema-version migration rather than
   silently changing existing contracts.

### WP2 — First-party proposal nodes

1. Add `ToolPlanNode`: it receives an explicit objective and controlled tool
   profile and returns an ordered, typed, proposal-only plan. It must reference
   only identifiers present in the immutable context and the profile.
2. Add `StructuredRepairNode`: it receives one bounded invalid JSON value,
   sanitized validation diagnostics, and a pinned supported target-node/schema
   identity. It may propose a repaired payload, but deterministic code must
   validate the target schema and label the result only as a repair proposal.
3. A repaired payload is never silently substituted into the failed invocation,
   never hides the original failure/cost evidence, and must be submitted as a
   new invocation through the original node to gain any normal proposal status.
4. Provider-native function calls remain untrusted telemetry. They cannot be
   conflated with accepted Tool Plan steps or executed by either node.

### WP3 — Runtime, facade, and exact replay

1. Register both nodes with the existing project-scoped runtime, facade, strict
   config loader, plan/execute/resume/status/verify, and exact replay path.
2. Ensure capability/profile fingerprints, target schema identity, state and
   project revisions, provider/model identity, token/cost/latency effects, and
   predecessor ledger hash are durable and replay-bound.
3. Keep planning and scripted/replay execution network-free. No real provider
   call is authorized by this dispatch; committed examples must be disabled and
   contain neither credentials nor fabricated pricing.
4. Machine-readable receipts must continue to expose `advisory_only=true` and
   `executable=false`; they must not contain raw provider bodies or secrets.

### WP4 — Adversarial verification and documentation

1. Cover valid plans and repairs plus schema failure, unknown tool, malformed or
   over-limit arguments, scope escape, dependency cycle/forward reference,
   provider-native tool-call confusion, target-schema mismatch, replay miss,
   changed capability profile, stale revision, budget rejection, and restart.
2. Prove that an accepted repair proposal is not an accepted target-node
   proposal and that no test path invokes a tool, process, network service, or
   state mutation.
3. Document the authority/data flow, initial catalog, profile semantics,
   extension rules, threat model, and remaining execution/effectiveness limits
   in `docs/TOOL_INTELLIGENCE.md`.
4. Run the focused model-node suite, Ruff, `git diff --check`, and `make check`.

## Epic exit gate

The Epic is complete only when a normal registered project can plan, execute in
scripted mode, resume, verify, and exactly replay both new nodes through the
durable runtime; every tool-plan step is typed and deterministically admitted
against a content-addressed read-only profile; invalid repairs fail closed; all
receipts remain non-executable; the focused and repository-wide checks pass; and
the worktree is clean with one or a small number of cohesive commits.

No live provider call, real tool execution, generated-code admission, or ADR-022
status change is authorized. Report commit SHAs, changed files, exact tests,
known limits, and recommended integration order to main.
