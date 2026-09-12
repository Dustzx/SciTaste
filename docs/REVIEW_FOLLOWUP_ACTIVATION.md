# Review follow-up activation

The activation dossier is the boundary between an ICLR evidence design and any
real experiment. It answers a narrower question than the historical campaign
dossier: given the five exact studies requested by the latest review, what can
the owner decide now, and what still prevents a valid launch?

The current manifest is
`configs/evaluation/activation/iclr2027_review_followup_v2.yaml`. It binds:

- the five-study review follow-up design through its evidence-program hash;
- every selected task-source and accepted-method proposal;
- the shared compute catalog and the SciTaste project resource binding;
- DeepSeek V4 Flash and GLM-5.3-Flash as unselected API candidates;
- local Qwen checkpoints as diagnostic assets, never as a paper backbone; and
- a two-reviewer, blinded, conflict-screened, adjudicated endpoint protocol.

The compiler derives all study, source, system, model, statistics, human, and
compute blockers. It cannot set a primary model, sample size, repetitions,
budget, approval, or execution authority. Existing resources therefore cannot
silently redefine the paper's scientific question.

The first bounded owner decision is only whether to acquire 20 pinned
InnovatorBench task-config files and one pinned EXP-Bench metadata table, under
an aggregate 8 MiB ceiling. The decision package does not approve even that
download. SciTasteBench construction, executable task packages, adapter
qualification, model conformance, power analysis, reviewer recruitment, and
formal execution remain separate later gates.

Compile a dry-run projection after the implementation and manifest are present
in the named Git commit:

```bash
.venv/bin/scitaste project paper review activate-followup \
  --project-id scitaste-self-development \
  --followup-design-run-id \
    2026-09-12__scitaste-native__review-followup-design-v3__seed-00 \
  --manifest \
    configs/evaluation/activation/iclr2027_review_followup_v2.yaml \
  --workspace-root . \
  --run-id 2026-09-12__scitaste-native__review-followup-activation-v1__seed-00 \
  --source-commit "$(git rev-parse HEAD)" \
  --expected-revision "<current-project-revision>" \
  --dry-run
```

Omit `--dry-run` only to register the deterministic dossier under the project.
That registration still performs no download, repository checkout, API call,
SSH connection, GPU work, model load, human recruitment, or experiment.

The earlier `iclr2027_self_development_v1.yaml` campaign is retained as
historical provenance for Qwen3-VL-2B and early MLR feasibility work. It is not
the current launch authority and cannot substitute for this review-bound
activation dossier.
