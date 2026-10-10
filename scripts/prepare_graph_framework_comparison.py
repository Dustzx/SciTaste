"""Freeze real Native/AutoResearchClaw research on staged scientific task data."""
# ruff: noqa: E501 -- Frozen explanatory contract literals.

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.forecasting_task_data import export_stage as export_forecasting_stage
from scitaste.benchmark.graph_task_data import export_stage as export_graph_stage
from scitaste.benchmark.hpatches_task_data import export_stage as export_hpatches_stage
from scitaste.benchmark.microscopy_task_data import CLAIM_RUBRIC
from scitaste.benchmark.microscopy_task_data import export_stage as export_microscopy_stage
from scitaste.benchmark.molecular_task_data import export_stage as export_molecular_stage
from scitaste.benchmark.open_research import digest, prepare_native
from scitaste.benchmark.pde_task_data import export_stage as export_pde_stage
from scitaste.benchmark.perturbation_task_data import export_stage as export_perturbation_stage
from scitaste.benchmark.population_shift_task_data import export_stage as export_population_stage
from scitaste.benchmark.qm9_task_data import export_stage as export_qm9_stage
from scitaste.benchmark.user_shift_task_data import export_stage as export_user_shift_stage
from scitaste.benchmark.weightspace_task_data import export_stage as export_weightspace_stage
from scitaste.model_nodes.session_exchange import retain_json


def prepare(
    root,
    pack,
    output,
    wall_seconds,
    max_requests,
    startup_receipt=None,
    research_title=None,
    metadata_timeout_seconds=None,
    paper_reserve_seconds=None,
    development_taste_library=None,
    native_only=False,
    taste_decision_context="legacy-full",
    taste_proposal_context="disabled",
    include_mlr_agent=False,
    raw_reference_context=None,
    reference_assets=(),
    matched_parent_campaign=None,
    taste_action_selection="enabled",
):
    root, pack, output = root.resolve(strict=True), pack.resolve(strict=True), output.resolve()
    output.relative_to(root / "evaluations")
    if not 1 <= wall_seconds <= 28800 or not 1 <= max_requests <= 160:
        raise ValueError("Explicit bounded lifecycle allocation required")
    if paper_reserve_seconds is None:
        paper_reserve_seconds = wall_seconds // 4
    if type(paper_reserve_seconds) is not int or not 0 <= paper_reserve_seconds < wall_seconds:
        raise ValueError("Paper reserve must be within the unchanged lifecycle ceiling")
    if research_title is not None and (
        not research_title.strip() or len(research_title) > 240 or "\n" in research_title
    ):
        raise ValueError("Use a short single-line research title")
    if metadata_timeout_seconds is not None and not 0 < metadata_timeout_seconds <= 900:
        raise ValueError("Explicit metadata connect/read bound must be in (0, 900]")
    from scitaste.taste.context_projection import (
        BOUNDED_RESEARCH_CONTEXT,
        REVIEWED_PROPOSAL_CONTEXT,
    )

    if taste_decision_context not in {"legacy-full", BOUNDED_RESEARCH_CONTEXT}:
        raise ValueError("Unknown frozen Taste decision-context version")
    if taste_proposal_context not in {
        "disabled",
        REVIEWED_PROPOSAL_CONTEXT,
        "reviewed-inquiry-v1",
        "source-passages-v1",
    }:
        raise ValueError("Unknown frozen Taste proposal-context version")
    if (
        taste_proposal_context in {REVIEWED_PROPOSAL_CONTEXT, "reviewed-inquiry-v1"}
        and development_taste_library is None
    ):
        raise ValueError("Pre-proposal lessons require a source-reviewed frozen library")
    if (taste_proposal_context == "source-passages-v1") != (raw_reference_context is not None):
        raise ValueError("Raw-source treatment requires its frozen source packet")
    if raw_reference_context is not None and development_taste_library is not None:
        raise ValueError("Raw-source control cannot enable conditional Taste")
    if taste_action_selection not in {"enabled", "disabled"}:
        raise ValueError("Unknown frozen Taste action-selection policy")
    if taste_action_selection == "disabled" and (
        development_taste_library is None
        or taste_proposal_context not in {REVIEWED_PROPOSAL_CONTEXT, "reviewed-inquiry-v1"}
    ):
        raise ValueError("Generation-only Taste requires reviewed pre-proposal experience")
    if include_mlr_agent and native_only:
        raise ValueError("A Native-only ablation cannot assign an external main comparator")
    manifest = json.loads((pack / "PACK.json").read_text())
    if manifest.get("authoring_development_only"):
        raise ValueError("An incomplete authoring view cannot become a full research assignment")
    task_id = manifest["task_id"]
    exporters = {
        "graph-evidence-transfer": export_graph_stage,
        "molecular-force-risk": export_molecular_stage,
        "microscopy-structure-restoration": export_microscopy_stage,
        "weightspace-evidence-transfer": export_weightspace_stage,
        "natural-reviewer-shift": export_user_shift_stage,
        "molecular-gap-extrapolation": export_qm9_stage,
        "confidence-guided-geometry": export_hpatches_stage,
        "stable-physical-rollout": export_pde_stage,
        "cross-series-forecasting": export_forecasting_stage,
        "population-shift-calibration": export_population_stage,
        "combinatorial-perturbation": export_perturbation_stage,
    }
    if task_id not in exporters:
        raise ValueError("No scientific staged-task exporter for this task")
    molecular = task_id == "molecular-force-risk"
    microscopy = task_id == "microscopy-structure-restoration"
    weightspace = task_id == "weightspace-evidence-transfer"
    user_shift = task_id == "natural-reviewer-shift"
    qm9 = task_id == "molecular-gap-extrapolation"
    hpatches = task_id == "confidence-guided-geometry"
    pde = task_id == "stable-physical-rollout"
    forecasting = task_id == "cross-series-forecasting"
    population_shift = task_id == "population-shift-calibration"
    perturbation = task_id == "combinatorial-perturbation"
    if population_shift:
        admission = json.loads((pack / "TASK_REVIEW.json").read_text())
        if (
            admission.get("task_id") != task_id
            or not admission.get("review_completed")
            or admission.get("verdict") != "admit-for-prospective-comparison"
            or admission.get("blocking_issues")
        ):
            raise ValueError("The fixed population task needs its actual bounded admission")
    if perturbation:
        admission = json.loads((pack / "TASK_ADMISSION.json").read_text())
        if not admission.get("review_completed") or admission.get("blocking_issues"):
            raise ValueError("The perturbation task needs actual source-bound admission")
        if admission.get("verdict") != "admit-for-prospective-comparison":
            raise ValueError("Conditional task review must be resolved before assignment")
    export_stage = exporters[task_id]
    output.mkdir(parents=True, exist_ok=False)
    export_stage(pack, output / "discovery")
    public = output / "discovery"
    for reference in reference_assets:
        reference = reference.resolve(strict=True)
        reference.relative_to(root)
        destination = public / reference.name
        if destination.exists():
            raise ValueError("Reference asset would overwrite task data")
        shutil.copy2(reference, destination)
    source = pack / "public" / task_id / "TASK.md"
    shutil.copy2(source, output / "TASK.md")
    # Reuse the already acquired original overall rubric; label this adaptation.
    old = root / "evaluations/mlrbench-scsl-system-comparison-20260930-v1"
    shutil.copy2(old / "RUBRIC.md", output / "RUBRIC.md")
    rubric_source = (
        root
        / "evaluations/acquisitions/mlr-agent-native-source-v1/mlrbench/evals/overall_review.py"
    )
    envelope = {
        "wall_seconds": wall_seconds,
        "max_requests": max_requests,
        "cpu_threads": 2,
        "gpu_enabled": False,
        "experiment_seconds": 1800,
        "native_paper_reserve_seconds": paper_reserve_seconds,
        "budget_basis": "Real fixed graph references completed in 41 s; allow larger researcher-selected CPU models and discrimination studies. Lifecycle includes session/literature/writing overhead; not a promise of sufficiency or a benchmark-wide limit.",
    }
    additions = f"""

# Shared execution and delivery contract

Both real systems receive the same discovery files under their workspace data/.
For AutoResearchClaw the task workspace is /work, independent of its stage sandbox
working directory. For SciTaste the runtime supplies the absolute workspace path.
Use these real graphs; synthetic replacements are not acceptable main evidence.
Installed Python 3.12, numpy/scipy/sklearn/pandas/matplotlib/torch CPU are available.
Two CPU threads, no GPU or supplier API calls, no new data/weights. Public literature
access is permitted; fetching original graph archives/labels, other project/run
materials or credentials is prohibited. Network restriction is instruction-level,
not a certified internet label firewall; this is a development assignment.
Lifecycle ceiling: {wall_seconds} seconds and {max_requests} model replies, including
planning, experimentation and writing/revision. Do not pad research with repetition.
Select an informative program and controls within this envelope; report failures.
Plan to retain {paper_reserve_seconds} seconds of this ceiling for paper delivery and
review/revision, not an additional budget. SciTaste Native enforces an earlier
research deadline for this reserve; AutoResearchClaw retains its own unchanged
stage scheduler. This configuration difference is disclosed, not a common upstream
scheduler modification or a claim of identical internal budgets.

To request the confirmation phase, put SUBMISSION.json and every listed source file
in workspace submission/ (AutoResearchClaw: /work/submission/). Follow data/SUBMISSION.example.json
but replace all placeholders with your own actual hypotheses and policies. The
entrypoint must accept --data DIRECTORY --output DIRECTORY and write exactly
tolokers--METHOD.npz for each declared method, containing node_id and probabilities
for the target test_mask nodes only. It must work without manual edits after freeze.
Write submission/READY only after all files are complete.
The freeze must be self-contained: list and include every required local module,
including runtime-generated helpers used by the framework's experiment sandbox.
Such helpers are NOT automatically installed in the evaluator. Installed public
Python dependencies are available, but the framework's /work or stage directory
is not mounted. Relative imports/assets must resolve from the declared frozen
submission; development success is not evidence that the bundle is complete.
Use no validation/test labels in fitting. The benchmark service snapshots submitted
source, exposes the redacted target only inside the evaluator sandbox, executes
the frozen program on CPU, and then
retains a single confirmation score packet at confirmation_feedback.json in the
workspace. You may inspect that file when it exists. Do not execute the confirmation
yourself or edit the freeze while awaiting feedback. If it fails, retain the failure;
do not substitute development scores for the missing target. It is a common evaluator
service, not an agent selecting hypotheses or modifying your program.

After confirmation, update your scientific interpretation and complete the paper.
The overall paper should use actual measured results and include related work,
method, experiments, meaningful limitations, and appropriate review/revision.
Produce report/report.md plus ordinary upstream-native artifacts. No target
confirmation claim without the actual score packet. Primary/control results may
be negative. The fixed reference programs are not AutoResearch method baselines.
For framework-required scalar monitoring, use primary_metric for ONE named
development metric and explicitly identify its graph; do not average different metrics.
"""
    if molecular:
        additions = additions.replace(
            "Use these real graphs; synthetic replacements are not acceptable main evidence.",
            "Use these real molecular observations; synthetic replacements are not acceptable main evidence.",
        ).replace("original graph archives/labels", "original source archives/force labels")
        additions = (
            additions.replace(
                "tolokers--METHOD.npz for each declared method, containing node_id and probabilities\nfor the target test_mask nodes only.",
                "aspirin--METHOD.npz for each declared method, containing frame_id, forces[N,21,3]\nand risk_score[N] for all released query geometries.",
            )
            .replace(
                "Use no validation/test labels in fitting.",
                "Follow the strict fitting/calibration budget and risk-policy boundary; never fit on query forces.",
            )
            .replace(
                "redacted target only inside the evaluator sandbox",
                "target fitting/calibration labels and force-redacted query geometries only inside the evaluator sandbox",
            )
            .replace(
                "For framework-required scalar monitoring, use primary_metric for ONE named\ndevelopment metric and explicitly identify its graph; do not average different metrics.",
                "For framework-required scalar monitoring, use primary_metric for one explicitly\nnamed development molecule/endpoint (negative force MAE for maximize monitoring).\nRetain force MAE and selective risk separately; do not average unlike scientific endpoints.",
            )
        )
        envelope["budget_basis"] = (
            "Fixed molecular author references took under two seconds per phase, but do not estimate "
            "learned-model or scientific-search cost. Reuse the four-hour/80-reply development "
            "whole-task configuration; includes experiment, model/session/literature and writing. "
            "Two CPU threads, no GPU in this particular cohort; not a formal benchmark-wide budget."
        )
    if microscopy:
        additions = additions.replace(
            "Use these real graphs; synthetic replacements are not acceptable main evidence.",
            "Use these real microscopy observations; synthetic replacements are not acceptable main evidence.",
        ).replace(
            "original graph archives/labels", "original microscopy archives/reference captures"
        )
        additions = (
            additions.replace(
                "tolokers--METHOD.npz for each declared method, containing node_id and probabilities\nfor the target test_mask nodes only.",
                "twophoton--bBUDGET--METHOD.npz for every declared method and every budget in\n1, 2, 4, 8, 16, containing fov_id and restored[N,512,512] in [0,1].\nRead QUERY.json and query.npz; each invocation sees only ONE target query budget.\nAll methods/budgets must complete before one joint scoring packet is released.",
            )
            .replace(
                "Use no validation/test labels in fitting.",
                "Fit predictor parameters only on train FOVs; calibration may select procedures.\nNever use confirmation reference images or other target query budgets.",
            )
            .replace(
                "redacted target only inside the evaluator sandbox",
                "target train/calibration fields and ONE reference-redacted query budget per offline process",
            )
            .replace(
                "For framework-required scalar monitoring, use primary_metric for ONE named\ndevelopment metric and explicitly identify its graph; do not average different metrics.",
                "For framework-required scalar monitoring, use primary_metric for ONE named\ndevelopment modality and capture-budget PSNR. Retain all five budget endpoints\nseparately. Do not choose the favorable budget after confirmation or turn an\nunvalidated spatial-frequency diagnostic into a biological-fidelity claim.",
            )
        )
        envelope["budget_basis"] = (
            "Fixed CPU microscopy controls took 12.47 s development and 8.46 s target inference; "
            "these do not estimate learned-model or scientific-search cost. Same four-hour/80-reply "
            "development allocation, including all five isolated confirmation processes and "
            "session/literature/writing time. No GPU in this cohort; not a formal benchmark-wide limit."
        )
        additions += """

## Prediction-directory scope

For each isolated invocation, --output DIRECTORY is the prediction directory.
Its top-level NPZ files must be exactly the declared current-budget control
predictions; no fitted spectra, cached inputs, reference arrays or other NPZs may
appear there. Put auxiliary fit artifacts in a separate subdirectory, not in the
prediction directory's top level. Preserve their provenance without substituting
them for control predictions. Do not emit another budget's predictions or omit a
declared control. The collector checks this exact set before any private scoring.
"""
    if weightspace:
        additions = f"""

# Shared execution and delivery contract

Both actual frameworks receive the same discovery files under workspace data/.
AutoResearchClaw workspace is /work, independent of stage sandbox working directory;
SciTaste receives its absolute workspace path. Use the actual trained subjects and
real supplied CIFAR observations; synthetic replacements are not main evidence.
Python 3.12 numpy/scipy/sklearn/pandas/matplotlib/torch CPU, two compute threads.
No local/remote GPU use in this research cohort, supplier APIs or new data/weights.
The already completed subject-generation GPU cost is separate shared benchmark
authoring cost, not free agent compute. Parameter optimization on permitted
calibration labels is legal; SciTaste controller training is not required.
Public literature access is allowed. Do not retrieve original CIFAR/test archives,
other runs/private labels/credentials. Network limits are instruction-level;
no certified public-source contamination firewall is claimed.
Lifecycle ceiling: {wall_seconds} seconds and {max_requests} responses, including
research, experiment, confirmation, writing and review/revision. Plan to reserve
{paper_reserve_seconds} seconds from the SAME allocation for paper delivery.
Native enforces its paper reserve; ARC's upstream scheduler remains unchanged.
This difference is disclosed rather than claimed as identical internal allocation.

Write SUBMISSION.json and every declared source under submission/; use the
unchanged public example wire format below with actual hypotheses/policies.
Include your required research_cnn.py and helpers; only submitted files and
installed Python dependencies are mounted in confirmation. After every file
is complete, write submission/READY. The common evaluator snapshots the source
before target inputs, runs it unchanged without network or private labels, and
scores all predeclared contexts/methods together once. The entrypoint accepts
--data DIRECTORY --output DIRECTORY and follows QUERY.json. Emit exactly
CONTEXT--METHOD.npz for all contexts/methods, containing image_id/probabilities.
Auxiliary fit artifacts must be in subdirectories. Do not repair or refreeze the
submission after READY or manually run target scoring. The service writes
confirmation_feedback.json. Wait for and inspect it before finalizing the paper;
if the source fails, preserve the failure and missing scores. No invented target
numbers or replacement by development results.

Retain actual measurements/code/figures, an initial report, evidence-based critique
and appropriate revision. Finish report/report.md plus ordinary native artifacts.
Negative/inconclusive conclusions are acceptable. Cite actual literature without
invented metadata. For an upstream scalar primary_metric use ONE named development
context's accuracy (maximize) and identify it; do not average NLL and accuracy.
"""
        envelope["budget_basis"] = (
            "Prospective four-hour/80-reply whole-task development allocation, including "
            "all frozen confirmation and paper work. Subject generation is shared authoring "
            "cost, not a runtime or scientific sufficiency estimate. No research GPU in this cohort."
        )
    if user_shift:
        additions = f"""

# Shared execution and delivery contract

All assigned real systems receive identical source-sampled train/ID-validation/
OOD-validation JSONL files. The task workspace is /work for external systems;
SciTaste receives its absolute path. Python 3.12 CPU, two threads, no supplier
API, new source data/weights or GPU. Public literature access is allowed, but
retrieving original review archives, private labels, other runs or credentials is
prohibited. These network restrictions are instruction-level, not certified.
Lifecycle ceiling: {wall_seconds} seconds and {max_requests} model responses,
including research, source-frozen confirmation, writing and revision. Reserve
{paper_reserve_seconds} seconds within that same ceiling for paper delivery.
Native enforces its paper reserve; external frameworks keep their original stage
schedulers. Allocation differences and source-memory contamination are disclosed.

The frozen entrypoint receives train.jsonl, id_val.jsonl, ood_val.jsonl and query.jsonl
in --data DIRECTORY, plus QUERY.json and the SAME public PROTOCOL.json supplied
during discovery. PROTOCOL.json contains no target labels. Predict all released target review IDs using
the unchanged declared methods and controls. Emit exactly amazon--METHOD.npz in
--output DIRECTORY, each with integer review_id and normalized probabilities[N,5].
Every helper is submitted; no workspace cache/checkpoint is mounted. Fit/retrain
only on supplied training data. Target text is released only after submission/READY;
target labels are never visible. The shared service freezes source, executes offline
and releases ONE joint feedback packet for all controls. Inspect
confirmation_feedback.json before the final paper. No source repair or refreeze
after READY, invented target numbers, or development scores in place of failures.

Execute real experiments and discriminating controls; retain code, measurements,
figures and an initial paper, evidence-based critique and justified revision.
Produce report/report.md and framework-native artifacts. Negative results are valid.
For any framework scalar primary_metric, choose ONE named development metric and
identify it (e.g. OOD-validation 10th-percentile reviewer accuracy). Keep overall
accuracy, reviewer percentile and NLL separate; do not invent a composite score.
This is one natural-distribution task with users as within-task uncertainty units,
not many independent tasks or the complete official WILDS evaluation.
For precise interpretation of PROTOCOL.json, all retained reviews means all rows
in INCLUDED official splits (0/1/2/3); ID-test (4) and unlabeled splits (11/12/13)
are not included. Reviewer selection uses ascending SHA256 of
"scitaste-user-shift-v1:" + original reviewerID, taking the first 1024 training,
128 OOD-validation and 256 test reviewers. Original private IDs and class
aggregates are not released. Do not fit representation, normalizers, predictive
parameters or selector thresholds on query texts/groups; query inputs are for
frozen inference only. Report reviewer-level uncertainty/variation, never review
rows as independent research episodes. The text benchmark uses research-only
source permissions and must not be redistributed as an openly licensed corpus.
"""
        envelope["budget_basis"] = (
            "Four-hour/80-response prospective whole-task development envelope based on "
            "observed real-system lifecycle overhead, not subject-model size or a formal "
            "benchmark-wide cutoff. Includes confirmation, literature and paper work. "
            "The shared two-GB source acquisition is benchmark authoring cost."
        )
    if qm9:
        additions = f"""

# Shared execution and delivery contract

All assigned genuine systems receive identical QM9 discovery files under data/.
External-framework workspace is /work; Native gets its absolute workspace path.
Python 3.12 numpy/scipy/sklearn/torch CPU/matplotlib, two compute threads.
No GPU, supplier API, new data/weights, original QM9 archive/labels, other runs or
credentials. Public literature access is allowed; data restrictions are
instruction-level and do not establish absence from model prior exposure.
Total lifecycle: {wall_seconds} seconds and {max_requests} model responses,
including research, experiment, confirmation and writing. Reserve
{paper_reserve_seconds} seconds from that same ceiling for paper/review work.
Native enforces its reserve; external systems keep their native schedulers.
The experiment limit is 1,800 seconds within the same lifecycle, not extra time.

Choose real hypotheses, procedures and meaningful controls. SUBMISSION.json and
all listed helpers belong in submission/. Follow the inlined example with actual
policies, not placeholders. Once complete, write submission/READY. The common
service freezes source before mounting train, public validations, QUERY.json and
redacted small/large query geometries, executes it unchanged offline, and scores
all declared procedures jointly once. Entry point --data DIRECTORY --output
DIRECTORY emits small--METHOD.npz and large--METHOD.npz containing only
molecule_id and gap_ev. Fit only on train; public validation selects procedures.
No caches, private labels or other workspace files are mounted. Do not refreeze,
repair after READY, or run the private evaluator yourself. Inspect the actual
confirmation_feedback.json before finishing the paper. Retain failures/missing
values, no replacement by exploratory scores.

Retain executed code, measurements, figures, an initial paper and appropriate
evidence-based critique/revision. Produce report/report.md and original upstream
artifacts. Use actual measured outcomes and references, with truthful limits.
If a framework needs primary_metric, report negative large-validation MAE (eV)
for maximize monitoring; identify this endpoint, not a cross-metric mixture.
These scalar monitoring values are not the complete scientific evidence.
"""
        envelope["budget_basis"] = (
            "Prospective four-hour/80-response complete-research setting based on observed "
            "framework overhead; two CPU threads, no GPU. Not a QM9 SOTA configuration, "
            "source-paper default, latency prediction or scientific-sufficiency guarantee."
        )
    if hpatches:
        additions = f"""

# Shared execution and delivery contract

All assigned genuine systems receive identical discovery/validation correspondences
under data/. External workspaces are /work; Native receives its absolute workspace.
Python 3.12 numpy/scipy/sklearn/matplotlib and OpenCV 4.11.0, two CPU threads.
No GPU, supplier API, new data/weights, original HPatches archives/identities,
other runs or credentials. Public literature access is allowed, but source-data
restrictions are instruction-level, not proof of absence from model prior exposure.
Total lifecycle: {wall_seconds} seconds and {max_requests} model responses,
including experiments, source confirmation and writing. Retain
{paper_reserve_seconds} seconds of this same ceiling for paper/review work.
Native enforces its reserve; external frameworks retain their own stage schedulers.
Each experiment/confirmation limit is 1,800 seconds within this total, not extra.

Investigate actual hypotheses about confidence-ranked robust inference with
meaningful alternative explanations, controls, failure conditions and compute costs.
Do not merely assert PROSAC always wins or equate iteration caps with equal work.
The common correspondences are SIFT-derived; results concern inference on these
inputs, not an end-to-end learned matcher, SLAM system or a new feature backbone.

Freeze SUBMISSION.json and all required helpers in submission/, then write READY.
In addition to the example fields, declare exactly one string primary_method
belonging to methods BEFORE READY. This is the deployed procedure for system-level
task comparison, chosen from public evidence; contrasting procedures remain
scientific controls. Do not select it from private confirmation or retrospectively
report your best control as the system result. Negative answers are valid.
Entrypoint --data DIRECTORY --output DIRECTORY must independently replay any frozen
public calibration and emit illumination--METHOD.npz and viewpoint--METHOD.npz
for every declared method. Fields are pair_id (integer), homography (N,3,3 finite),
valid (boolean) and seconds (N finite nonnegative; self-reported timing).
All pairs, including failed estimates, must be present. Public discovery/validation
NPZs, QUERY.json and redacted query NPZs are mounted; query homographies/labels,
model caches, your work/stage directory and undeclared helpers are never mounted.
No fitting, calibration or source edits using private labels. The trusted service
freezes source, runs it unchanged offline on CPU and scores every procedure on
both change types jointly once. No source repair/refreeze after READY.

Read actual confirmation_feedback.json before scientific interpretation and paper
delivery. Retain missing/failed results; no public-score substitution. Report AUC
at 5px separately for illumination and viewpoint, along with meaningful controls,
failure fraction and computation. Scene groups, not image pairs, are the sampling
units within this ONE research task. For scalar framework monitoring use the
mean of the two public validation AUC@5px values for your named primary procedure,
explicitly described; retain both separate values in scientific evidence.
Deliver report/report.md plus ordinary upstream artifacts, actual executed code,
measured figures, initial paper and appropriate evidence-based critique/revision.
"""
        envelope["budget_basis"] = (
            "Prospective four-hour/80-response whole-task CPU envelope based on observed "
            "framework overhead; public geometry controls ran in under a second. Larger "
            "scientist-selected discrimination studies remain bounded. Not an upstream "
            "paper configuration, equal algorithmic-work claim or sufficiency guarantee."
        )
    if pde:
        additions = f"""

# Shared execution and delivery contract

All real systems receive identical permitted public trajectory files under data/.
External workspaces are /work; Native receives its absolute workspace path.
Python 3.12 numpy/scipy/sklearn/matplotlib/torch CPU, two compute threads.
No GPU, supplier API, additional weights/data, original solution archives,
other viscosity tables, other runs or credentials. Public literature access is
allowed; this instruction-level boundary does not certify absence of prior exposure.
Total lifecycle: {wall_seconds} seconds and {max_requests} responses, including
experiments, confirmation and writing. Reserve {paper_reserve_seconds} seconds
of the SAME ceiling for paper/review work. Native enforces that reserve; real
external frameworks retain their original schedulers. Experiment and confirmation
limits are 1,800 seconds within the lifecycle, not extra time.

Form competing explanations for whole-trajectory accuracy, stability, conservation
and resolved structure. A known numerical solver, conserved mean or successful
program is not by itself a new scientific contribution. Training-based refers to
fitting the experimental subject, never training the research controller. Fit
predictive/representation coefficients only on the permitted early training prefixes;
public discovery/validation select fixed configurations. Late-time public validation
is visible, so confirmation tests new initial identities, not unseen temporal laws.
The provided equation coefficient is 0.01/pi. The source-to-coarse-grid conversion
creates a closure approximation; do not present numerical outputs as physical data.

Freeze SUBMISSION.json and every source/helper in submission/, declaring exactly
one public-evidence-selected primary_method from methods, then write submission/READY once.
The entrypoint accepts --data DIRECTORY --output DIRECTORY. It independently
replays any fitting/calibration using the permitted train/discovery/validation
files plus QUERY.json and early/late query initial fields. Emit precisely
early--METHOD.npz and late--METHOD.npz for every declared method, with integer
trajectory_id[N], finite real state[N,len(time),256], boolean valid[N], and
finite nonnegative seconds[N]. All trajectories including failures stay present.
No private states, workspace caches or undeclared helpers are mounted. The trusted
service snapshots source before target inputs and executes it unchanged offline.
It scores all declared procedures and both horizons jointly once. No refreeze,
post-READY source repair, private winner selection or manual target execution.

Read actual confirmation_feedback.json before scientific interpretation and paper
delivery. Complete-trajectory normalized RMSE is the primary prediction endpoint;
failures remain missing rather than a survivor mean. Keep early/late errors,
conservation, Fourier diagnostics and runtime distinct. Individual timesteps/cells
are not independent research tasks. For a scalar framework primary_metric use
negative public validation late normalized RMSE of the named primary procedure
for maximize monitoring, not a composite scientific-quality score.
Retain actual executed code, measurements, informative figures, initial manuscript
and appropriate evidence-based critique/revision. Finish report/report.md plus
upstream-native artifacts. Negative findings and justified narrower claims are valid.
"""
        envelope["budget_basis"] = (
            "Prospective four-hour/80-response whole-research envelope based on observed "
            "system overhead, not a full PDEBench training configuration. Five public "
            "ordinary controls ran in about ten seconds; their cost excludes framework "
            "research, literature and writing. Two CPU threads, no GPU for this cohort."
        )
    if forecasting:
        additions = f"""

# Shared execution and delivery contract

All genuine systems receive the same permitted histories and public future
validation under data/. External workspaces are /work; Native gets its absolute
workspace path. Python 3.12 numpy/scipy/sklearn/matplotlib/torch CPU, two threads.
No GPU, supplier API, additional data/weights, original series metadata/archive,
other runs or credentials. Public literature access is allowed; source boundaries
are instruction-level, not evidence that the backbone has never seen M4.
Total lifecycle: {wall_seconds} seconds and {max_requests} model responses,
including scientific research, experiments, source confirmation and writing.
Reserve {paper_reserve_seconds} seconds of this SAME ceiling for paper/review.
Native enforces that reserve; external frameworks retain their own schedulers.
Experiment/confirmation limits are 1,800 seconds within this total, not extra.

Form competing explanations about cross-series pooling, scale, seasonality,
model capacity and usable recent history. Standard normalizers or lower forecast
error alone are not a new discovery. Training means fitting the experimental
subject, not the research controller. Fit global parameters only on rolling
windows inside the permitted training histories. Public discovery/validation
future values select fixed procedures but never fit global parameters. Local
estimation from each query's observed history is permitted only as a predeclared
rule; no cross-query update or access to original held-out futures. Ignore padded
zeros using history_length; neither sectors nor absolute calendar are released.

Freeze SUBMISSION.json and all required source/helpers in submission/, with one
public-selected primary_method belonging to methods, then write submission/READY once.
Entrypoint --data DIRECTORY --output DIRECTORY independently replays its declared
fits/calibration using train, discovery, validation, QUERY.json and redacted
monthly query histories. Emit monthly--METHOD.npz for every declared procedure,
with exactly series_id[N] integers, forecast[N,18] finite real values, valid[N]
booleans and seconds[N] finite nonnegative self-reported inference times. Include
all series including failures. The trusted service freezes source before targets,
runs it unchanged offline and scores all procedures jointly once. No private
future, undeclared cache/helper, post-READY source repair or private winner choice.

Read actual confirmation_feedback.json before interpreting results and writing
the paper. Mean per-series MASE is the complete prediction endpoint; keep median,
tail, separate sMAPE, failures and cost distinct. Scale is the mean lag-12 absolute
difference of each permitted observed history, with a declared 1e-8 floor. A
declared failure leaves the complete endpoint missing, not a survivor average.
The input-only recent-change partition is not a verified structural break. This
is a capped-history new-series monthly subset, not an official full M4 ranking,
OWA score, unseen temporal-law or sector-transfer experiment. Series/horizons are
within-task units, not thousands of independent scientific research tasks.
For maximize-style framework monitoring, primary_metric is negative validation
mean MASE of the named primary procedure; never mix scientific-quality metrics.
Retain executed code, measurements, informative figures, an initial manuscript
and appropriate evidence-based critique/revision. Finish report/report.md plus
upstream artifacts. Honest negative findings and narrower claims are valid.
"""
        envelope["budget_basis"] = (
            "Prospective four-hour/80-response whole-research CPU envelope based on observed "
            "system overhead, not original M4/Monash model training defaults. Five ordinary "
            "public controls ran in about two seconds; this excludes research and writing. "
            "Two CPU threads and no GPU. Strong scientific contribution remains unproven."
        )
    if population_shift:
        additions = f"""

# Shared execution and delivery contract

All genuine systems receive identical public source populations under data/.
External workspaces are /work; Native receives its absolute workspace path.
Python 3.12 numpy/scipy/sklearn/pandas/matplotlib/torch CPU, two threads.
No GPU, supplier API, additional data/weights, original ACS archives, private
persons/labels, other runs or credentials. Public literature access is permitted.
The boundary is instruction-level, not proof of controller pretraining independence.
Total lifecycle: {wall_seconds} seconds and {max_requests} responses, including
research, source confirmation and paper/revision. Reserve {paper_reserve_seconds}
seconds of this same ceiling for paper work. Experiment/confirmation each have
1,800 seconds within that ceiling; these are not extra allocations. Native
enforces the paper reserve; external systems retain their native schedulers.

Form competing explanations involving representation, discrimination, prevalence
and calibration. Fit predictor/calibration parameters only on train.npz;
household-aware cross-fitting within training is permitted. Discovery/validation
labels select fixed configurations, never fit parameters. All eligible persons
in each source household remain together. Use ACS survey weights within the
sampled eligible source population, not as national or causal certification.
A new name for a standard calibrator or a favorable score is not new science.
Threshold changes are not probability recalibration. California later changes
time; New York later changes both time and geography. Preserve these limitations.

Freeze every helper and SUBMISSION.json in submission/, declare all methods and
one public-selected primary_method, then write submission/READY once. Entrypoint
--data DIRECTORY --output DIRECTORY independently replays its train-only fit.
Mounted data contain QUERY.json, train/discovery/validation and two redacted
query populations, not private labels or your workspace caches. Emit exactly
california_later--METHOD.npz and new_york_later--METHOD.npz at the output root
for every declared method. Each file contains precisely person_id[N] int64,
probabilities[N,2] finite normalized values, valid[N] booleans and seconds[N]
finite nonnegative inference cost. Do not put public/diagnostic NPZs at the
output root: the exact root NPZ contract rejects undeclared outputs. Non-NPZ
reports and public diagnostics in a separate subdirectory are permitted.
The trusted service freezes source before queries, executes it offline once,
and retains every declared method/population, including malformed/missing
outputs. Any failure leaves the complete primary unavailable, never a survivor
score, zero or a substituted private winner. No post-READY repair/refreeze.

Read actual confirmation_feedback.json before claims and paper delivery.
Report complete survey-weighted Brier separately on both populations; AUC,
fixed-0.5 accuracy, calibration-in-the-large, group diagnostics and cost remain
separate. Group TPR below twenty positive persons is unavailable, not zero or
fairness assurance. For maximize-style framework monitoring only,
primary_metric = negative pooled PUBLIC validation survey-weighted Brier of
the frozen primary. Preserve each scientific population score independently.
Retain actual code, measurements, informative evidence-linked figures and
report/report.md plus native framework artifacts. Genuine negative findings,
abstention and unresolved mechanisms are valid; successful prose cannot replace
research. No re-identification, individual deployment or redistribution authority
is conferred by this local statistical task.
"""
        envelope["budget_basis"] = (
            "Prospective four-hour/80-response whole-research CPU envelope, matching "
            "the preceding independent task cohort. Three ordinary train-only "
            "public controls fit in 0.36 seconds; this excludes research/writing "
            "and establishes neither model superiority nor task sufficiency."
        )
    if perturbation:
        additions = f"""

# Shared execution and delivery contract

Genuine frameworks receive identical public K562 condition-level evidence under
data/. External workspaces are /work; Native receives its absolute workspace.
Python 3.12 numpy/scipy/sklearn/pandas/matplotlib/torch CPU, two threads; no GPU,
supplier API, new data/weights, source archive, private labels, other runs or
credentials. Public literature is permitted. The source boundary is instructional,
not proof of absent pretrained exposure. Whole lifecycle: {wall_seconds} seconds
and {max_requests} replies including research, confirmation and writing. Reserve
{paper_reserve_seconds} seconds of the same ceiling for paper/review. Experiment
and confirmation limits each are 1,800 seconds within, not additional budgets.

The research question concerns unseen double-perturbation conditions whose
single constituents are observed in fitting. It is one assay, cell line and source,
not unseen genes, cell types, cell-level biological replicates or clinical evidence.
Cells of each unordered condition stay together. Fit parameters/preprocessing
only on train.npz; public discovery/validation expression selects complete rules
but never fits them. Shared readouts are the 1,000 largest fitting-control mean
expression genes. Pseudobulk means average stored log1p expression, not log1p
count pseudobulk. No original global differential-expression annotations are used.
Original archive 101 singles/125 doubles differs from a published filtered
100/124 study: do not claim exact reproduction or modern foundation-model ranking.

Investigate competing explanations such as additive amplitude bias, shared
low-dimensional interactions and specificity versus global shrinkage. Distinguish
prediction improvement from biological mechanism. A positive amplitude change
can improve RMSE while leaving centered correlation unchanged. Include appropriate
ordinary controls, informative negative outcomes and measurement/scope limitations;
no source paper or reference control determines a preferred answer or primary.

Freeze all helpers and SUBMISSION.json in submission/, with one public-selected
primary_method in methods, then write READY once. Method identifiers must use
ASCII letters/digits/underscores only (no decimals, hyphens or path separators);
these are output identifiers, not required paper notation. Entrypoint accepts
--data DIRECTORY --output DIRECTORY and independently replays its train-only fit.
It receives train/discovery/validation, QUERY.json and the redacted query. Emit
unseen_combinations--METHOD.npz for EVERY declared method at the output root,
with precisely condition_id[N] int64, expression[N,1000] finite real values,
valid[N] booleans, seconds[N] finite nonnegative inference costs. Public/auxiliary
NPZ files must be nested elsewhere, never at the output root. Retain all failed
conditions with valid=false; any failure leaves the complete primary missing,
never a survivor mean, zero or private winner. No post-READY source repair/refreeze.

The trusted service snapshots source before redacted queries, runs it unchanged
offline once and retains every declared method/condition. Read actual
confirmation_feedback.json before paper claims. Primary mean condition RMSE over
fixed readouts stays separate from control-centered Pearson delta, additive-relative
MSE, residual correlation, undefined-correlation counts and within-condition
split-half measurement diagnostics. Correlation can be undefined; do not invent
zero values or infer mechanism from score. Cells/readouts/pairs are within-task
units, not independent research tasks. For framework maximize-style monitoring
only, primary_metric is negative mean PUBLIC validation condition RMSE for the
named frozen primary. Preserve raw measurements, code, informative figures and
report/report.md plus native artifacts. No raw/derived redistribution authority,
human-review certification or formal benchmark eligibility is implied.
"""
        envelope["budget_basis"] = (
            "Same prospective four-hour/80-response whole-research CPU envelope as "
            "independent cohorts. Three ordinary public expression controls ran in "
            "0.04 seconds; this is not a task-difficulty certificate or a prediction "
            "of research/model-generation cost. No modern foundation-model claim."
        )
    if include_mlr_agent:
        additions = additions.replace("Both real systems", "All three real systems").replace(
            "Both actual frameworks", "All three actual frameworks"
        )
        additions += (
            "\nMLR-Agent uses its genuine native stage sequence and real coding CLI, "
            "with the same local-session model transport and two-thread CPU envelope. "
            "Its workspace is /work; results/results.md and results/paper.md remain "
            "its upstream delivery paths. Supplied data/ is research evidence: preserve "
            "it even when a framework's generic cleanup prompt suggests deleting "
            "downloaded files. No original provider web-search engine is simulated, "
            "and no native post-paper review/revision is invented.\n"
        )
    # Both systems must receive the wire format, even if their native observation
    # formatter truncates stdout from code that reads the public example. This is
    # interface information, not a supplied scientific solution. Existing sealed
    # campaigns are never regenerated in place.
    submission_example = public / "SUBMISSION.example.json"
    interface = (
        "\n# Exact shared submission wire format\n\n"
        "The public example is repeated verbatim below for both systems. Replace "
        "its placeholders; it does not prescribe your research method.\n\n```json\n"
        + submission_example.read_text().rstrip()
        + "\n```\n"
    )
    execution_text = source.read_text() + additions + interface
    if matched_parent_campaign is not None:
        parent = json.loads(matched_parent_campaign.read_text())
        if (
            not native_only
            or development_taste_library is not None
            or taste_proposal_context != "disabled"
            or parent["task_id"] != task_id
            or parent["pack"]["sha256"] != digest(pack / "PACK.json")
            or parent["resource_envelope"] != envelope
            or parent["native_taste"]["decision_context"] != taste_decision_context
        ):
            raise ValueError("Matched OFF requires the same task, budget and decision context")
        from scitaste.benchmark.open_research import verified_asset

        execution_text = verified_asset(root, parent["execution_brief"]).read_text()
    (output / "EXECUTION_BRIEF.md").write_text(execution_text)

    def binding(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    confirmation_sources = {}
    if (
        weightspace
        or user_shift
        or microscopy
        or qm9
        or hpatches
        or pde
        or forecasting
        or population_shift
        or perturbation
    ):
        repository = Path(__file__).resolve().parents[1]
        for name in (
            "scripts/serve_perturbation_confirmation.py"
            if perturbation
            else "scripts/serve_population_confirmation.py"
            if population_shift
            else "scripts/serve_pde_confirmation.py"
            if pde or forecasting
            else "scripts/serve_graph_confirmation.py",
            "src/scitaste/benchmark/perturbation_task_data.py"
            if perturbation
            else "src/scitaste/benchmark/population_shift_task_data.py"
            if population_shift
            else "src/scitaste/benchmark/forecasting_task_data.py"
            if forecasting
            else "src/scitaste/benchmark/hpatches_task_data.py"
            if hpatches
            else "src/scitaste/benchmark/pde_task_data.py"
            if pde
            else "src/scitaste/benchmark/qm9_task_data.py"
            if qm9
            else "src/scitaste/benchmark/user_shift_task_data.py"
            if user_shift
            else "src/scitaste/benchmark/microscopy_task_data.py"
            if microscopy
            else "src/scitaste/benchmark/weightspace_task_data.py",
            "src/scitaste/benchmark/graph_task_data.py",
            "src/scitaste/executor/workspace_sandbox.py",
        ):
            retained = output / "confirmation-runtime" / name
            retained.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repository / name, retained)
            confirmation_sources[name] = binding(retained)
        if population_shift or perturbation:
            # The new runner reuses only the unchanged genuine-native path
            # adapter; include that implementation in its prospective binding.
            name = "scripts/serve_pde_confirmation.py"
            retained = output / "confirmation-runtime" / name
            retained.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repository / name, retained)
            confirmation_sources[name] = binding(retained)

    shutil.copy2(old / "NATIVE_TASTE_PROFILE.json", output / "NATIVE_TASTE_PROFILE.json")
    treatment = {"mode": "off", "binding": None}
    if development_taste_library is not None:
        from scitaste.taste.research_tool_deliberation import workspace_taste_binding

        library = development_taste_library.resolve(strict=True)
        library.relative_to(root)
        profile = output / "NATIVE_TASTE_PROFILE.json"
        frozen_binding, _ = workspace_taste_binding(library, profile)
        treatment = {
            "mode": "reviewed-development",
            "library": binding(library),
            "profile": binding(profile),
            "binding": frozen_binding,
        }
    treatment.update(
        decision_context=taste_decision_context,
        proposal_context=taste_proposal_context,
    )
    if taste_action_selection == "disabled":
        treatment["action_selection"] = "disabled"

    contract = {
        "schema_version": "1.0",
        "campaign_id": output.name,
        "frozen_at": datetime.now(UTC).isoformat(),
        "benchmark": "SciTasteBench",
        "task_id": task_id,
        "source_commit": manifest.get("source_commit"),
        "source_brief": binding(source),
        "brief": binding(output / "TASK.md"),
        "execution_brief": binding(output / "EXECUTION_BRIEF.md"),
        "rubric": binding(output / "RUBRIC.md"),
        "rubric_source": binding(rubric_source),
        "pack": binding(pack / "PACK.json"),
        "researcher_assets": {
            p.name: binding(p) for p in public.iterdir() if p.name != "RELEASE.json"
        },
        "arms": (
            ["scitaste-native"]
            if native_only
            else ["scitaste-native", "autoresearchclaw"]
            + (["mlr-agent"] if include_mlr_agent else [])
        ),
        "resource_envelope": envelope,
        "confirmation_execution_seconds": 1800,
        "confirmation_cost_in_lifecycle": True,
        "confirmation_runtime_sources": confirmation_sources,
        **(
            {
                "confirmation_handoff": "aggregate-model-attachment.v1",
                "confirmation_handoff_scope": "ARC receives the identical trusted evaluator "
                "aggregate as an explicit bound model-request attachment after READY; "
                "Native/MLR retain ordinary workspace feedback access. Prospective adapter "
                "configuration, not a native upstream capability or old-result recovery.",
            }
            if hpatches or pde or forecasting or population_shift or perturbation
            else {}
        ),
        **(
            {"confirmation_public_metadata": {"PROTOCOL.json": binding(public / "PROTOCOL.json")}}
            if user_shift
            else {}
        ),
        "population": (
            "One authored Norman K562 family; conditions/readouts/cells are within-task "
            "units. Same assay and fitting constituent singles; unknown pretraining exposure "
            "and dependence. Not unseen-cell-type/clinical/official GEARS evidence."
            if perturbation
            else "One authored ACS statistical-research family; persons and household groups "
            "are within-task units, not independent research tasks. Unknown repeated-person, "
            "geographic and model-pretraining dependence; no national/causal/real-income inference."
            if population_shift
            else "One authored M4 monthly adaptation; series/horizons are within-task units, "
            "not independent research tasks. Capped histories and public future selection; "
            "original calendar/sector hidden and model exposure unknown."
            if forecasting
            else "One authored PDEBench adaptation; initial fields are within-task units, "
            "not independent tasks. Numerical simulation, one viscosity and public late-time "
            "selection; prior source exposure unknown."
            if pde
            else "One prospective authored HPatches family; scene groups are within-task units, "
            "not independent research tasks. Source image/model prior exposure unknown."
            if hpatches
            else "One prospective authored QM9 family; molecular identities are within-task units, "
            "not independent research tasks. Prior source exposure in model training unknown."
            if qm9
            else "One natural reviewer-shift family; official source reviewers are within-task units, not research tasks"
            if user_shift
            else "One authored development weightspace family; independent training blocks and "
            "initialization contexts are replications, not additional research tasks"
            if weightspace
            else "one authored development research family; 3 source contexts, not 3 tasks"
        ),
        "endpoints": [
            "primary-method complete mean condition RMSE; Pearson delta, additive-relative MSE, residual correlation, failure/cost/noise separately"
            if perturbation
            else "primary-method complete weighted Brier by population; AUC/calibration/group/failure/cost separately"
            if population_shift
            else "primary-method complete mean MASE; median/tail, sMAPE, failures and runtime separately"
            if forecasting
            else "primary-method late normalized RMSE, early prediction/conservation/Fourier/failure/runtime diagnostics separately"
            if pde
            else "primary-method corner AUC@5px separately by illumination/viewpoint; failure/runtime diagnostics"
            if hpatches
            else "large confirmation MAE (eV), small MAE/RMSE/tail diagnostics separately"
            if qm9
            else "overall accuracy and official 10th-percentile reviewer accuracy separately"
            if user_shift
            else "task-native per-budget PSNR/SSIM"
            if microscopy
            else "task-native per-context accuracy/NLL"
            if weightspace
            else "task-native force MAE/selective risk"
            if molecular
            else "task-native per-graph metric",
            "frozen-program execution",
            "claim support",
            "paper quality",
            "review response",
        ],
        "paper_rubric_adaptation": "Original MLR-Bench overall text rubric; not official MLRJudge or human gold",
        "comparison_scope": "real framework configurations, same assets and ceilings; differing tools/control flow and instruction-level network restrictions disclosed",
        "submission_interface_inlined": True,
        "submission_contract_revision": (
            "single-primary-complete-condition-expression.v1"
            if perturbation
            else "single-primary-complete-population-probability.v1"
            if population_shift
            else "single-primary-complete-forecast.v1"
            if forecasting
            else "single-primary-complete-trajectory.v1"
            if pde
            else "single-primary-self-contained-geometry.v1"
            if hpatches
            else "self-contained-source-and-prediction-scope.v2"
        ),
        **(
            {
                "submission_path_policy": "executed-native-layout.v1",
                "submission_path_scope": (
                    "Direct workspace submission or first completed ARC native sandbox run "
                    "with READY; unchanged genuine source, no reconstruction, score-based "
                    "selection or extra experiment. Prospective adapter, not upstream capability."
                ),
            }
            if pde or forecasting or population_shift or perturbation
            else {}
        ),
        "model_source": "isolated session model responses; provider identity, tokens and cost unverified",
        "formal_evidence_eligible": False,
        "native_taste": treatment,
        **(
            {"raw_reference_context": binding(raw_reference_context)}
            if raw_reference_context
            else {}
        ),
        "taste_scope": (
            "Frozen source-reviewed development library; applicability and benefit remain unestablished"
            if development_taste_library is not None
            else "Native without an external Taste library; this configuration does not measure Full Taste"
        ),
        "missing_policy": "Retain all assignments and failures; never impute missing scores",
    }
    if population_shift:
        contract["task_admission"] = binding(pack / "TASK_REVIEW.json")
        contract["confirmation_runner"] = "scripts/serve_population_confirmation.py"
        contract["source_redistribution_approved"] = False
    if perturbation:
        contract["task_admission"] = binding(pack / "TASK_ADMISSION.json")
        contract["confirmation_runner"] = "scripts/serve_perturbation_confirmation.py"
        contract["source_redistribution_approved"] = False
    if include_mlr_agent:
        contract["mlr_agent_configuration"] = {
            "assignment_timing": "prospective; frozen before any framework outcomes",
            "source_commit": "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824",
            "coding_cli": "real installed Codex CLI; version and hash retained at launch",
            "literature_configuration": "native ordinary text model, not supplier web-search",
            "native_review_revision_available": False,
            "model_alias_is_not_backbone_identity": True,
        }
    if matched_parent_campaign is not None:
        contract["matched_parent_campaign"] = binding(matched_parent_campaign.resolve(strict=True))
        contract["matched_brief_scope"] = "Exact parent execution brief retained; only Taste "
        "enablement and Native-only assignment differ. No scientific outcome was used."
    protocol = json.loads((public / "PROTOCOL.json").read_text())
    if "claim_rubric" not in protocol:
        if not microscopy:
            raise ValueError("Task has no frozen claim-level rubric")
        # Early microscopy packs retain narrative obligations only. Bind their
        # equivalent machine-readable rubric in a new campaign, never modify the
        # immutable pack, raw data, split, reference results or an existing campaign.
        retain_json(
            output / "CLAIM_RUBRIC.json",
            {
                "task_id": task_id,
                "claims": CLAIM_RUBRIC,
                "basis": [binding(public / "TASK.md"), binding(public / "REVIEW_PROTOCOL.json")],
                "scope": "Public task obligations formalized before framework execution; not new data or calibrated judgments",
            },
        )
        contract["claim_rubric"] = binding(output / "CLAIM_RUBRIC.json")
    if startup_receipt is not None:
        contract["startup_recovery"] = binding(startup_receipt.resolve(strict=True))
    if research_title is not None:
        contract["external_research_title"] = research_title
        contract["external_task_mapping"] = (
            "short title plus unchanged brief in native stage extras"
        )
    if metadata_timeout_seconds is not None:
        contract["metadata_timeout_seconds"] = metadata_timeout_seconds
        contract["metadata_transport_scope"] = (
            "Declared ARC runtime environment: bound only requests lacking an explicit timeout; "
            "preserve pinned native stages, queries and retries. Per connect/read operation, "
            "not a total search deadline or a scientific policy. Not a best-native configuration."
        )
    retain_json(output / "CAMPAIGN.json", contract)
    prepare_native(
        root,
        output / "CAMPAIGN.json",
        root / "evaluations/acquisitions/researchharness-runtime-v1",
        output / "native-plan",
    )
    assignments = {
        "scitaste-native": {
            "run": f"evaluations/{output.name}-native",
            "lifecycle": f"evaluations/{output.name}-native-lifecycle",
        },
    }
    if not native_only:
        assignments["autoresearchclaw"] = {"run": f"evaluations/{output.name}-arc"}
    if include_mlr_agent:
        assignments["mlr-agent"] = {"run": f"evaluations/{output.name}-mlr-agent"}
    retain_json(output / "ASSIGNMENTS.json", assignments)
    return {"campaign": str(output), "assigned_arms": list(assignments), "task_families": 1}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "pack", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--wall-seconds", type=int, required=True)
    p.add_argument("--max-requests", type=int, required=True)
    p.add_argument("--startup-receipt", type=Path)
    p.add_argument("--research-title")
    p.add_argument("--metadata-timeout-seconds", type=float)
    p.add_argument("--paper-reserve-seconds", type=int)
    p.add_argument("--development-taste-library", type=Path)
    p.add_argument(
        "--taste-decision-context",
        choices=("legacy-full", "bounded-research-source-v1"),
        default="legacy-full",
    )
    p.add_argument(
        "--taste-proposal-context",
        choices=(
            "disabled",
            "reviewed-conditional-v1",
            "reviewed-inquiry-v1",
            "source-passages-v1",
        ),
        default="disabled",
    )
    p.add_argument(
        "--include-mlr-agent",
        action="store_true",
        help="Freeze a genuine third-framework comparator prospectively in the same campaign",
    )
    p.add_argument("--raw-reference-context", type=Path)
    p.add_argument("--reference-asset", type=Path, action="append", default=[])
    p.add_argument("--matched-parent-campaign", type=Path)
    p.add_argument("--taste-action-selection", choices=("enabled", "disabled"), default="enabled")
    p.add_argument(
        "--native-only",
        action="store_true",
        help="Freeze only a Native ablation assignment; do not assign or rerun the external framework",
    )
    a = p.parse_args()
    print(
        json.dumps(
            prepare(
                a.project,
                a.pack,
                a.output,
                a.wall_seconds,
                a.max_requests,
                a.startup_receipt,
                a.research_title,
                a.metadata_timeout_seconds,
                a.paper_reserve_seconds,
                a.development_taste_library,
                a.native_only,
                a.taste_decision_context,
                a.taste_proposal_context,
                a.include_mlr_agent,
                a.raw_reference_context,
                a.reference_asset,
                a.matched_parent_campaign,
                a.taste_action_selection,
            )
        )
    )
