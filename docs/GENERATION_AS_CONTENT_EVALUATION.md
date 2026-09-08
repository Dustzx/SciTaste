# Generation as Content Evaluation

This document defines how SciTaste's evidence-grounded generated workspace can
be evaluated without confusing interface quality with scientific effectiveness.
It records one self-hosted engineering pre-experiment and a paper-ready human
study protocol. The pre-experiment is not a user study.

## Claim boundary

The interface may reduce navigation, improve evidence discovery, and make the
proposal-only authority boundary easier to understand. None of those outcomes
by itself shows that SciTaste chooses better research actions or produces better
science. Interface results therefore belong in a separate evaluation layer and
must not be pooled with SciTasteBench preference accuracy or the matched-budget
end-to-end scientific outcomes.

Three evidence levels remain distinct:

1. contract and browser checks show that the implementation behaves as specified;
2. automated structural proxies identify likely benefits and regressions before
   recruiting participants;
3. a counterbalanced human comparison can support usability claims.

Only the third level can support claims about human task success, task time,
workload, usability, preference, or comprehension.

## Measurement basis

[ISO 9241-11:2018](https://www.iso.org/standard/63500.html) treats usability as
an outcome of use in a specified context. The formal study therefore covers
effectiveness, efficiency, and satisfaction rather than relying on appearance
or a single composite score. The original
[System Usability Scale](https://hci-studies.org/methods-and-measures/downloads/SUS_Brooke1996.pdf)
provides the post-condition usability instrument, while the official
[NASA-TLX](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/)
can measure workload when the study budget permits it.

Two recent primary generative-interface studies inform the comparison design.
Chen et al.'s
[Generative Interfaces for Language Models](https://aclanthology.org/2026.findings-acl.74/)
separates functional, interactive, and emotional perception and uses pairwise
human judgments. Google's
[Self-Evolving Systems](https://research.google/pubs/self-evolving-systems-moving-beyond-deterministic-interfaces-to-adaptive-generative-interfaces/)
uses a within-subject comparison, counterbalanced Latin-square ordering,
objective screen evidence, and SUS. SciTaste adopts the comparison structure,
not either paper's reported effect size.

SciTaste also needs domain-specific safety endpoints. The
[Guidelines for Human-AI Interaction](https://doi.org/10.1145/3290605.3300233)
emphasize making capabilities and limitations clear and preserving user control.
For this receiver, that becomes evidence-source comprehension, uncertainty
recognition, and correct understanding that an action is a proposal rather than
an execution.

Engineering accessibility checks use the normative WCAG 2.2 requirements for
[reflow at 320 CSS pixels](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)
and [24-by-24 CSS-pixel minimum targets](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).
Interaction to Next Paint may later measure immediate browser feedback, but it
must remain separate from the end-to-end asynchronous generation time: the
[INP definition](https://web.dev/articles/inp) explicitly does not measure all
eventual network and UI effects.

## Repeatable automated pre-experiment

`scitaste.generative_ui.evaluation` exposes two read-only measurements:

- `evaluate_project_task_proxies` measures how many distinct fixed source views
  contributed to one generated workspace, the rank of the goal-focused native
  component, visible evidence references, component count, and grounding;
- `benchmark_local_responses` measures in-process fixed progress, quick-intent
  catalog, and deterministic generated-progress latency. It makes no network or
  model call and labels its result as environment-specific.

Both outputs bind the project ID, snapshot revision/hash, closed planner mode,
interpretation boundary, and a stable fingerprint. They contain no project
prose, paper text, user question, credential, or human-outcome field. Run them
without modifying project outputs:

```bash
PYTHONPATH=src .venv/bin/python -m scitaste.generative_ui.evaluation \
  --outputs-root outputs \
  --project-id scitaste-self-development \
  --latency-samples 20 \
  --warmups 2
```

The dependency-free Chromium probe is run against a temporary copy of a real
project so audit initialization cannot modify repository outputs:

```bash
SCITASTE_UI_PROBE_URL=http://127.0.0.1:8766 \
SCITASTE_UI_PROBE_TOKEN="$SCITASTE_UI_TOKEN" \
SCITASTE_UI_PROBE_PROJECT=scitaste-self-development \
SCITASTE_UI_PROBE_QUICK_INTENT=review-project-progress \
node tests/generative_ui/browser_response_probe.mjs
```

The probe starts a fresh headless Chromium profile, enters the credential in the
page, opens the real progress view, activates the requested server-issued quick
intent, changes locale in place, and checks 1440, 768, 390, and 320 CSS-pixel
widths. `SCITASTE_UI_PROBE_QUICK_INTENT` defaults to
`review-project-progress`; setting it to another available quick-intent ID makes
comparison and paper views repeatable without changing the script. The probe
reports end-to-end browser observations, document reflow, target sizes,
generated-workspace focus, component count, locale-switch requests, and runtime
errors. It does not claim to measure subjective usability.

## 2026-09-08 self-hosted result

The deterministic pre-experiment read `scitaste-self-development` revision 180,
snapshot `ef370d7bb6eb...d5dc48`, directly from the current project record. No
runtime output or API response was committed.

| Structural proxy | Result |
|---|---:|
| Applicable quick-intent tasks | 4 |
| Mean distinct fixed source views represented | 3.25 |
| Generated workspaces per task | 1.00 |
| Mean fixed views avoided | 2.25 |
| Mean fixed-view reduction | 65.83% |
| Goal-focused component ranked first | 4/4 (100%) |
| Evidence-grounded components | 30/30 (100%) |
| Mean generated component count | 7.50 |

The 65.83% result is a navigation-structure proxy: it compares one generated
workspace with the number of distinct fixed pages needed to display the same
selected native component bundle. It is not an observed click reduction or task
time. Progress combined five source views, blocker diagnosis three, run
comparison three, and paper review two. Progress and paper review each reached
the 12-component cap, so the same result also exposes a plausible information-load
regression that requires human testing.

The structural report fingerprint was
`ec8da795e399...cc1b9d7f`. Twenty timed samples after two warmups produced:

| Local operation | median | p95 |
|---|---:|---:|
| Fixed project progress | 132.748 ms | 152.052 ms |
| Quick-intent catalog | 144.260 ms | 182.354 ms |
| Deterministic generated progress | 1,657.035 ms | 1,720.975 ms |

The latency report fingerprint was `c9e614b28309...166a803b`. Generated progress
was about 12.48 times the median fixed-progress service time. Thus this
pre-experiment finds a structural navigation benefit and a response-time cost;
it does not support an unqualified usability-improvement claim.

The final Chromium run observed 679.7 ms from connection to the fixed workspace
and 2,077.2 ms from the progress quick-intent click to the complete generated
workspace. These are single local end-to-end observations, not percentiles and
not INP. Locale switching issued zero requests; all four widths had no document
horizontal overflow, no enabled visible target below 24 CSS pixels, 12 intact
components, no runtime error, and the generated workspace focused at its visible
start.

The probe also drove a concrete responsive repair against the same project and
component count:

| Engineering A/B | main baseline `efae9d5` | repaired receiver |
|---|---:|---:|
| Generated response visible at 390 px | no; workspace top 2,036 px | yes; top 0 px |
| 768 px document height | 134,812 px | 28,134 px |
| 768 px document-height reduction | -- | 79.13% |

The repair makes generated cards single-column at the tablet breakpoint and
focuses then scrolls the generated workspace to its start. This is a measured
engineering improvement, but document height remains large because the progress
surface contains 12 components.

## 2026-09-08 agent-led temporary-project walkthrough

An additional exploratory session used a repository-external temporary outputs
root and the normal `scitaste run full` command, rather than a Generative UI test
fixture. The project `evidence-ui-research-experience` contained two completed
native offline runs, seeds 7 and 11. Each run executed 18 project-owned native
records across Discovery, Evidence, Communication, and Figure, including one
Bubblewrap-isolated measurement. Both observed a `correct_pivot_delta` of 0.10
and each produced a Markdown, TeX, PDF, assessment, build record, and editable
figure bundle. The generated manuscripts remained truthfully marked as 63-word
`integration-fixture` artifacts and `publication_ready: false`; this session
did not reclassify them as substantive research papers.

The agent then used the running authenticated receiver as a research-project
operator. This is an engineering walkthrough by the development agent, not an
external participant, independent researcher, or human-usability observation.
No temporary project output, screenshot, HTTP response, question, or credential
is committed.

| Researcher task | Observed result | Friction or missing integration |
|---|---|---|
| Understand completed work | Generated one evidence-bound progress workspace and put the canonical progress board first | 12 components; 390-pixel document height was 13,758 pixels |
| Find blockers or failures | Returned `no_matching_evidence` because both registered runs were complete | Safe and truthful, but the receiver does not explain how to record a newly discovered blocker |
| Compare seeds 7 and 11 | Generated a focused three-component comparison with both run identities | Scientific metrics were unavailable even though each run summary contains the measured delta; `ProjectRun` has no registered comparable-metric projection yet |
| Judge paper readiness | Required selection between the two registered paper versions, then showed `publication_ready: false` and verified artifacts | Clarification candidates are display-only; the user must retype an exact ID. The 12-component result repeats current/registered paper context and an artifact |
| Decide what to do next | Returned `no_matching_evidence` because no next gate was declared | Correctly avoids inventing advice, but provides no evidence-grounded route for recording or requesting that gate |
| Attempt an executable request | Refused a request to create an execution page and run a shell command; authority remained `none` | Expected safety behavior |

The paper path also completed the read-only artifact and proposal boundaries.
Inspecting the selected `main.md` returned 550 verified bytes with SHA-256
`b959ab9db1a6...77a7139`; proposing the current paper produced only a
`proposal_pending` receipt for `paper_selection`, with `execution_authority` set
to `none` and `deterministic_controller` as the next boundary. The visible button
label “Request paper approval” is nevertheless easy to confuse with publication
approval even though its typed meaning is paper selection.

Ten in-process samples after two warmups measured fixed progress at 54.539 ms
median/68.700 ms p95, quick-intent catalog construction at 55.543 ms/55.991 ms,
and generated progress at 534.585 ms/591.331 ms. The structural report covered
three available intents, represented a mean three fixed source views in one
generated workspace (63.89-percent structural reduction), ranked focused content
first in 3/3 cases, and grounded all 27 components. Browser quick-intent completion
was 753.5 ms for progress, 500.0 ms for run comparison, and 557.3 ms for paper
review in separate fresh-browser observations. These environment-specific
measurements are diagnostics, not user task time.

This walkthrough raises four implementation candidates for a later scoped Epic:
entity-scoped component selection and semantic duplicate removal; actionable but
still proposal-only clarification controls; an unambiguous paper-selection label;
and a trusted workflow-to-`ProjectRun` projection for comparable scientific
metrics and declared next gates. The first three fit the receiver boundary. The
last requires main-window ownership because the UI must not infer metrics or
research state from arbitrary artifacts.

## Paper evaluation protocol

The main paper should add a fourth, explicitly secondary interface evaluation
after software integrity, SciTasteBench, and matched-budget scientific outcomes.
It should not change the first three levels or elevate self-development results
into headline scientific metrics.

### Conditions and tasks

Use a within-subject comparison with counterbalanced condition and task order:

- **Fixed:** the current receiver with normal fixed-page navigation;
- **Generated:** the deterministic Generation-as-Content workspace over the
  exact same project snapshot and native component data.

Keep model-assisted planning as a later third condition only after provider,
latency, and budget identities are pinned. Each participant completes matched
instances of five research-management tasks:

1. summarize the project's observed state without inferring a completion percent;
2. identify a blocked or failed run and cite the evidence supporting that status;
3. compare two registered runs and locate the recorded differences;
4. determine the current paper/evidence state and locate its authoritative artifact;
5. propose a next step and state whether the interface executed, approved, or
   merely recorded it.

Use frozen non-self-development project snapshots, equivalent task difficulty,
and distinct instances between conditions to limit memory transfer. Record the
screen and identity-only receiver events, but never capture credentials or
unpublished paper contents in study telemetry.

### Endpoints

| Dimension | Primary or gate | Secondary diagnostics |
|---|---|---|
| Effectiveness | Evidence-grounded completion: correct answer, all required evidence identities, and no unsupported claim | partial accuracy, evidence inspection rate, correction count |
| Efficiency | Time to first correct evidence-grounded answer | route transitions, backtracks, scroll distance, evidence disclosures, end-to-end generation latency |
| Satisfaction | SUS after each condition | one seven-point post-task ease item; NASA-TLX once per condition if burden permits |
| Trust and control | Non-inferiority gate on proposal/execution and source-authority comprehension | confidence-versus-correctness calibration, unsafe-action acceptance |
| Accessibility | WCAG reflow and target-size engineering gate | keyboard completion and focus loss observed in human sessions |
| Preference | Blinded paired overall preference | information clarity, learnability, visual appeal, perceived evidence sufficiency |

Do not average these into an arbitrary single score. Pre-register evidence-grounded
completion as the primary endpoint, time as the main efficiency endpoint, and
authority comprehension as a non-inferiority safety gate. Report every endpoint
with paired effect sizes and confidence intervals. Analyze binary completion
with a paired or mixed-effects logistic model and log task time with a mixed
model containing participant and task-instance effects. Correct the secondary
comparisons, disclose exclusions and assistance, and retain failures.

Run a small formative pilot to verify task wording and instrumentation, then set
the confirmatory sample size from an a priori power analysis using the pilot
variance and smallest meaningful effect. Three to five internal users are useful
for defect discovery but cannot support the paper's effectiveness claim. Use a
validated language version of each questionnaire; do not machine-translate SUS
or NASA-TLX merely because the receiver supports Chinese labels.

### Paper claim ladder

- **Now:** SciTaste deterministically composes evidence-bound native components,
  keeps goal content first, passes responsive/safety checks, and reduces a fixed-view
  structural proxy while adding measurable generation latency.
- **After formative testing:** report defects and protocol changes only.
- **After the powered counterbalanced study:** claim improvement only for the
  endpoints whose intervals and multiplicity-corrected tests support it; retain
  null or negative results for workload, latency, and authority comprehension.
- **Never from this study alone:** claim improved scientific taste, research
  decision correctness, paper quality, or autonomous research yield.

The existing manuscript sentence that generated interfaces improve access to
evidence but do not themselves improve research decisions remains correct. The
human study can refine the first half of that statement without weakening the
second.

## Open issues revealed by the pre-experiment

- Progress and paper review can saturate the 12-component limit. A later study
  should compare bounded disclosure or relevance-based omission before simply
  increasing that limit.
- Deterministic progress generation has roughly 1.5 seconds of added local
  service work relative to fixed progress. Profiling should separate repeated
  snapshot hashing, candidate construction, validation, and browser rendering.
- The browser probe measures complete asynchronous response, not INP or a field
  p75. Immediate busy-state paint and INP need trusted user input and field/lab
  instrumentation.
- No external participant has yet completed the five-task protocol, so SUS,
  task-time, workload, preference, and authority-comprehension deltas remain
  unmeasured.
