# Matched idea-to-paper package-preference prepilot governance v2

Date: 2026-09-11

Status: frozen no-run protocol candidate. This protocol authorizes no provider
request, GPU process, remote connection, task download, external-system checkout,
reviewer recruitment, or experiment cell.

## 1. Why this protocol is separate

MLR-Bench supplies open-ended workshop-derived research briefs and evaluates the
resulting idea, proposal, experiment trace, and paper with research-quality
rubrics. It does not supply a fixed objective target value for each of its ten
published end-to-end tasks. Therefore those tasks cannot use the objective-
progress endpoint in `AUTORESEARCH_MATCHED_PREPILOT_GOVERNANCE_V1.md`.

This v2 protocol governs the distinct **idea-to-paper research-package** lane.
The v1 protocol remains applicable to independently admitted tasks with a fixed
scorer, starting value, target anchor, and failure floor, such as a qualified
MLRC-Bench or executable benchmark lane. Scores from the two protocols are
never pooled.

## 2. Scientific question

Under matched starting briefs, information access, model revision, tools,
repair rules, and resource ceilings, does SciTaste Native produce complete
research packages that independent blinded experts prefer for scientific value
and evidence validity over packages produced by real accepted AutoResearch
systems?

The pilot may establish adapter feasibility, failure modes, reviewer workload,
and variance. It cannot establish superiority, field-wide effectiveness, ICLR
readiness, or an official review outcome.

## 3. Experimental unit and systems

The experimental unit is one system-task-seed trajectory. A complete trajectory
retains the initial brief, literature evidence, idea decisions, proposal,
commands, code, experiment inputs and outputs, failed attempts, final paper,
resource telemetry, and intervention ledger.

The matched lane contains SciTaste Native, a direct execution-capable agent, and
only real pinned external systems. At least two external systems backed by
accepted archival papers must pass licensing, unchanged-core, task-equivalence,
model, sandbox, telemetry, artifact, and failure-resume gates before a broad
external-system claim is eligible. Unavailable systems receive no imitation or
pseudo-implementation.

## 4. Task contract

The MLR-Bench ten-task list is a candidate scope because the accepted paper uses
it for experimentation, writing, and end-to-end comparison. Each starting input
is a research brief derived from one ICLR 2025 workshop. The brief and its
source group are distinct from a task-specific executable dataset or objective
scorer.

Before launch, every selected task must have:

1. a pinned repository and dataset revision;
2. exact bytes and SHA-256 for the starting brief;
3. an explicit license for those starting bytes;
4. a unique source-group identifier;
5. an audit against SciTaste development examples, Knowledge/Taste records,
   prompts, fixtures, prior outputs, and the current manuscript;
6. a declared runtime acquisition policy for any code, data, checkpoints, or
   papers fetched after launch; and
7. a fixed output and review contract shared by every system.

The top-level MIT license covers the released MLR-Bench repository and dataset
package. It does not automatically establish the license, availability, or
fitness of arbitrary downstream assets that a research agent later chooses.
Those acquisitions remain per-trajectory evidence and can stop a matched block.

## 5. Primary endpoint

The single primary endpoint is condition-blinded expert pairwise preference for
the complete research package, jointly considering scientific value and
evidence validity. Reviewers may choose system A, system B, or a tie. They do not
see framework, provider, model, cost, or condition identity before locking the
judgment.

The fixed review dimensions are:

- significance of the problem and contribution;
- novelty after checking the supplied and cited literature;
- methodological validity;
- whether executed evidence supports each material claim;
- reproducibility and artifact completeness; and
- clarity sufficient to inspect the science.

Fluency, formatting, or an agent's self-review cannot by itself satisfy the
endpoint. Fabricated results, unexecuted methodology, unsupported citations,
and hidden manual rescue remain explicit adverse outcomes.

## 6. Reviewer and automated-judge contract

Every primary comparison receives at least two conflict-checked independent
expert reviewers. System aliases and left/right order are randomized. Material
disagreement follows a prespecified third-reviewer adjudication rule while the
original ratings remain retained.

MLR-Judge or any other model judge is secondary and diagnostic. It may measure
rubric agreement and scale exploratory analyses only after calibration on the
actual SciTaste comparison population. It cannot replace the independent human
primary endpoint. Reviewer expertise, conflicts, missing reviews, agreement,
adjudication, time, and confidence are all reported.

## 7. Estimand and analysis

The primary estimand is the task-averaged probability that a blinded reviewer
prefers SciTaste Native to a preregistered accepted external comparator, with
ties retained as ties. Each accepted comparator contrast is reported rather
than selecting the most favourable comparator after observing results.

The formal analysis uses a paired preference model with task blocks and reviewer
effects. It reports wins, ties, losses, effect sizes, 95-percent intervals, and
a task-clustered bootstrap sensitivity analysis. Confirmatory comparator
contrasts use a prespecified multiplicity correction. Tasks, not reviews or
paragraphs, determine effective sample size. A clean pilot estimates variance
and reviewer burden; a new content-addressed power analysis fixes the formal
sample size before formal outputs are opened.

Secondary endpoints include dimension scores, unsupported-claim rate, executed-
evidence coverage, experiment validity, reproducibility, correct pivot/stop
decisions, wall time, tokens, cost, intervention, and active versus allocated
accelerator time. They are never collapsed into an undocumented composite.

## 8. Matching, failures, and repairs

All systems receive equivalent starting briefs and registered information,
search, tool, wall-time, token, cost, experiment, and hardware ceilings wherever
their native semantics permit. An official-configuration sensitivity analysis
is separate from the matched-backbone analysis.

All frozen system-task-seed cells follow intention-to-run. Timeout, budget
exhaustion, invalid evidence, build failure, missing paper, and unrecoverable
adapter error remain outcomes. Infrastructure-wide failure stops the block.
System-specific manual rescue, outcome-dependent retry, silent exclusion, and
best-of-run selection are prohibited.

Adapters may translate provider syntax, file locations, and artifact schemas.
They may not rewrite upstream prompts, topology, search policy, task objective,
tools, or failure semantics. Any substantive repair creates a new proposal and
reruns the full affected matched block.

## 9. Provider, GPU, and temporal separation

DeepSeek V4.1 Flash and GLM-5.3-Flash require separate proposals, hashes,
pricing records, served-model attestations, cells, and estimates. Qwen3-VL-2B-
Instruct on eight RTX 3090 GPUs is a separate small-model or experimental-
workload robustness lane and cannot replace the frontier matched-backbone lane.

The SciTaste executable commit, external repositories, task bytes, adapter
evidence, judge protocol, budgets, and analysis are frozen before approval. A
source change after the first cell creates a new protocol version. Formal
outputs never enter Knowledge or Taste stores until the formal study is closed.

## 10. Authorization boundary

Static inspection and a green prelaunch report do not authorize execution. The
project owner must approve the exact proposal SHA-256 after receiving every
model/revision, task and dataset, repository commit, environment, planned cell,
API-cost ceiling, GPU-hour ceiling, reviewer-hour ceiling, output directory,
retention policy, launch command, and stop rule. One clean matched block must
stop for inspection before any scale-out approval.
