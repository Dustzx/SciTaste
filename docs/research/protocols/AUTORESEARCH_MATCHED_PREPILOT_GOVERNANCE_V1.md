# Matched AutoResearch prepilot governance protocol v1

Date: 2026-09-11

Status: frozen no-run protocol candidate. This document binds analysis and
integrity requirements for later API and local-GPU proposals. It does not admit
tasks or systems, approve spending, recruit reviewers, access a provider,
connect to a GPU host, download data, or authorize an experiment.

## 1. Scientific question and contribution lanes

The confirmatory question is whether SciTaste Native improves externally
measured research progress under matched tasks, model/backbone access, tools,
starting evidence, repair rules, and resource ceilings.

Publication contribution and experiment use are distinct:

- a **method or hybrid system** can become a system comparator only after its
  real pinned implementation and unchanged-core adapter pass;
- a **benchmark or hybrid evaluation artifact** can become a task or judge
  source only after exact assets, licensing, scoring, and source groups pass;
- a benchmark paper's bundled agent is not a method comparator by default; and
- a method paper's own benchmark is not an independent task source by default.

The headline lane requires SciTaste Native, a real direct-agent lower bound,
and at least two external systems backed by accepted archival papers. Preprints
may appear only in a separately labelled sensitivity lane. A system that cannot
be licensed or adapted remains unavailable; no pseudo-implementation may stand
in for it.

## 2. Primary outcome and estimand

The primary outcome is **task-normalized final objective progress** from the
frozen benchmark scorer. Each task's registered starting score maps to 0 and
its registered human or benchmark target maps to 1; extrapolation is retained
rather than clipped. If a task lacks a defensible starting and target anchor,
it cannot enter the confirmatory set.

The pilot estimand is the equally task-weighted mean paired difference between
SciTaste Native and the strongest admitted accepted external method score in
each matched task-by-seed block. The strongest comparator is computed inside
each block as the maximum over the full preregistered accepted-system set; a
failed comparator receives the failure floor and is not silently dropped.
SciTaste-versus-direct-agent and SciTaste-versus-each-system contrasts are
reported separately. The pilot estimates feasibility and variance only; it
cannot establish superiority.

The analysis unit is one task-by-seed matched block. Systems are not treated as
independent samples. Tasks receive equal weight in the headline aggregate;
seeds are averaged within task before the across-task estimate. Report the raw
task scores, normalized task scores, paired differences, failure rates, wall
time, tokens, cost, GPU allocation and active time, interventions, and artifact
completeness without collapsing them into one universal score.

Uncertainty uses a task-stratified paired bootstrap with a 95% interval and an
exact or Monte Carlo paired sign-flip test when the admitted task count permits.
Per-system secondary contrasts use Holm correction. Effect sizes and intervals
are reported regardless of significance. The later formal sample size must be
computed from a clean pilot without inspecting formal outcomes and bound in a
new power-analysis artifact; it may not be backfilled into a completed run.

## 3. Task freeze

Before any paid call or GPU cell, every selected task must have:

1. an official resource identity and immutable revision;
2. exact content-addressed assets and scorer;
3. verified code, data, checkpoint, and upstream licenses;
4. a declared starting score, target anchor, and failure floor;
5. a held-out flag and source-group identity;
6. no overlap with SciTaste development examples, prompts, Knowledge Library,
   Taste Library, adapter fixtures, or previous formal outputs; and
7. an executable no-model scorer preflight.

The pilot and formal task lists are immutable after their proposal hashes are
approved. A task defect stops the whole matched block. Repair produces a new
protocol and reruns every system on the affected task; it never removes only an
unfavourable cell.

## 4. Failure and missingness policy

The analysis follows intention-to-run over every frozen system-task-seed cell.
Timeouts, budget exhaustion, invalid artifacts, scorer failure attributable to
the system, and unrecoverable execution errors remain visible and receive the
registered task failure floor. Infrastructure-wide failures stop the block and
are not scored until the unchanged block is rerun.

Every attempt retains its request identity, response or process transcript,
exit state, usage, cost, wall time, allocated and active GPU time, artifacts,
and failure classification. No system-specific retry, manual rescue, silent
exclusion, best-of-run selection, or outcome-dependent early stop is allowed.

## 5. Repair and intervention policy

Adapters may translate file locations, provider syntax, and artifact schemas;
they may not change a system's search policy, prompts, agent topology, tools,
starting evidence, task objective, scorer, or failure semantics. Each external
checkout must be pinned, isolated, license-admitted, and compared with its
recorded upstream tree to prove the core remains unchanged.

A single fixed automated repair budget is declared per lane and applied to all
systems. Human intervention after launch is prohibited in confirmatory cells.
If safety requires intervention, the action is retained, the cell is labelled
intervened, and the matched block stops. Debugging after a stop creates a new
prepilot proposal and cannot alter the stopped ledger.

## 6. Leakage audit

Before launch, a deterministic audit hashes and scans:

- task titles, paper/source groups, datasets, starter code, expected metrics,
  and reference solutions;
- Knowledge and Taste records, retrieval indexes, prompts, examples, fixtures,
  caches, model-node recordings, and prior outputs; and
- external-system bundled examples, memories, and task-specific templates.

Exact duplication, source-family overlap, target-paper exposure, or answer-like
content blocks the task. Semantic screening may nominate cases for manual
review but cannot automatically waive a block. The audit tool version, inputs,
decisions, reviewer, and hashes are retained. Formal results never flow back
into the stores until the formal protocol is closed and archived.

## 7. Blinded judge protocol

Objective progress is primary. Human review supplies separate evidence about
research decisions and final packages. Each admitted artifact receives at least
two conflict-cleared reviewers who do not know the system condition. Formatting
is normalized without rewriting substantive content. Reviewers score distinct
dimensions—problem significance, novelty after literature checking,
methodological validity, evidence-to-claim support, reproducibility, and paper
clarity—and provide a confidence value and blocking-reason codes.

Artifact order and system aliases are randomized. Reviewers cannot see token,
cost, model, framework, or failure metadata until judgments are locked. A third
reviewer adjudicates prespecified material disagreements; adjudication never
replaces the original scores. The protocol reports inter-reviewer agreement,
dimension-level results, missing reviews, conflicts, and adjudication rates.
Automated reviewers are diagnostic only and cannot satisfy the independent
expert requirement.

## 8. Provider and GPU separation

DeepSeek V4.1 Flash and GLM-5.3-Flash use separate proposal, identity, pricing,
raw-response, and result ledgers. They are robustness replications and may not
be silently substituted or pooled as if they were one backbone. Any rolling
alias must record the served identity for every request and stop if that
identity cannot be recovered.

The Qwen3-VL-2B-Instruct 8xRTX-3090 lane is a separate small-model robustness
study. It cannot replace the frontier API comparison. GPU allocation and active
use are recorded separately, and the remote inventory and checkpoint must match
the approved content-addressed proposal before connection or transfer.

## 9. Temporal and authorization boundary

The executable repository commit, resource-corpus semantic hash, task assets,
system adapters, model identity and pricing, budgets, analysis, judge protocol,
and this document must all be bound before owner approval. Approval names the
exact proposal SHA-256 and expires when any bound byte changes.

Planning, inspection, and critic reports never authorize execution. The owner
must approve the exact provider/model/data/system/cell/cost or GPU-hour manifest
before the first external action. Scaling beyond one clean pilot block requires
a second approval and a new content-addressed proposal.
