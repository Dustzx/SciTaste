"""Source-bound planning inventory; code presence is not execution readiness."""

import hashlib
from pathlib import Path

_CAPABILITIES = {
    "review-directed-native-research": (
        "src/scitaste/project/review_research.py",
        "Prepare a separate source-bound Native task from an actual paper review. "
        "ADD_ANALYSIS routes to retained-evidence computation even without new-training "
        "flags. Only explicitly declared own-run public artifacts are exposed; original "
        "assignments and assessed manuscripts remain unchanged. Current entry supports "
        "CPU postprocessing without refits/downloads; general new-data experiments need "
        "separate resource binding. One actual continuation completed computation, report, "
        "review/revision and PDF in 27.39 minutes; the numerical concern was substantially "
        "addressed but contribution/significance remained rejected. Preparation grants "
        "neither execution nor review closure; no causal Taste effect was established.",
    ),
    "prepared-source-maintenance": (
        "src/scitaste/project/source_maintenance.py",
        "Repository-backed supervisor sequences a previously prepared source through "
        "actual quality/abstraction nodes, independent reviews and a separate successor "
        "library freeze. A retained-source replay produced the exact four-case successor "
        "without new calls. Live model/review suppliers and an explicit code root are "
        "required; arbitrary web discovery and automatic active-library replacement "
        "are not implemented. Qualified admission is not scientific effectiveness.",
    ),
    "project-resource-acquisition-handoff": (
        "src/scitaste/project/acquisition_selection.py",
        "Select item IDs from declared pinned acquisition options, reuse existing receipts "
        "or schedule explicit bounded downloads, then prepare Native resource bundles with "
        "source/license/use constraints. One real model-selected retained reference handoff "
        "completed without downloads or experiments. New network acquisition, arbitrary "
        "source discovery, ingestion and experimental readiness are not implied.",
    ),
    "scitaste-native-workspace": (
        "src/scitaste/executor/native_workspace.py",
        "Model-backed SciTaste Native controller over workspace "
        "tools, with alternatives/stop selection, persistent state and prospective decision "
        "capture. Prepared CPU/API tasks may use a benchmark task or project-owned "
        "study instructions and declared asset files without a benchmark TaskRunner. "
        "A fresh project-owned CPU study completed execution, report, review/revision and "
        "experience disposition with explicit operator recovery; uninterrupted autonomy is "
        "not established. A session-assisted retained-data analysis actually consulted a "
        "reviewed Taste library and abstained from unsupported transfer, then delivered "
        "paper review/revision and feedback-informed planning. Known session waits can "
        "resume source/workspace-bound checkpoints without replaying committed tools; "
        "arbitrary in-flight tool crashes remain fail-closed. "
        "Raw feedback is not an official "
        "score; quarantined experience requires attribution before admission. No upstream "
        "agent loop is used; full Taste augmentation and generic task invention are not implied.",
    ),
    "project-workspace-provisioning": (
        "src/scitaste/executor/workspace_provision.py",
        "Compile model-selected declared asset subsets into fresh bounded Native CPU/API "
        "study tasks without a benchmark TaskRunner or pre-existing task. A live design "
        "selected and compiled a resource bundle. Initial resource registration is explicit; "
        "no autonomous download, generic remote GPU provisioning or automatic execution.",
    ),
    "native-remote-workspace-tool": (
        "src/scitaste/executor/remote_workspace_tool.py",
        "Native Run Remote tool executes trusted project code under a frozen host/device/job/time "
        "envelope, waits on the same detached job, collects artifacts and reports costs. "
        "One assistant-selected retained-result CPU analysis completed on 4090-2 with real SSH "
        "and artifact return; no online Native ranking or GPU use was demonstrated in that run. "
        "Generic remote continuation remains unsupported. Cwd separation is not an OS sandbox.",
    ),
    "native-project-lifecycle": (
        "src/scitaste/project/native_workspace_cycle.py",
        "Package-owned Native execution-to-report-to-review/revision/PDF, experience "
        "disposition and optional feedback-based next planning. Existing results are reused. "
        "Post-paper planning can compile a new workspace selection without executing it. "
        "Negative results continue normally; unrestricted autonomous recovery is not implemented.",
    ),
    "objective-to-native-cycle": (
        "src/scitaste/project/cycle_planning.py",
        "The research-cycle entry accepts an objective and declared task/resource options, "
        "invokes planning/provisioning, and forwards its exact compiled Native selection. "
        "Accepted workflow-only planning does not start an experiment. Actual session intake "
        "and nonexecution were exercised; a fresh positive whole-chain run is not yet proven. "
        "No undeclared resource discovery or unlimited automatic research iterations.",
    ),
    "prepared-benchmark-task": (
        "scripts/run_project_benchmark_task.py",
        "Project/current-Idea-bound real ResearchClawBench CPU/API task with frozen visible "
        "assets, runtime sources and backend configuration. Uses the existing native-base "
        "ResearchHarness arm, terminal result delivery and optional paper continuation. "
        "Not automatic task invention, full Taste control or decision-level experience capture.",
    ),
    "native-perception": (
        "scripts/run_mlrc_native_development_loop.py",
        "Existing MLRC temporal action localization Native development runner on a prepared "
        "remote dataset/model bundle. Can serve as a component of the registered development "
        "hybrid protocol; does not implement external-framework system comparisons.",
    ),
    "native-unlearning": (
        "scripts/run_native_tools_development.py",
        "Bounded GPU CIFAR-10 ResNet-18 unlearning candidate edits and measurements; "
        "iterative execution and prepared-study paper handoff exist. Not a full "
        "multi-system benchmark runner or arbitrary dataset adapter.",
    ),
    "native-meta": (
        "scripts/run_native_tools_development.py",
        "Single bounded few-shot meta-learning candidate on a prepared remote bundle; "
        "requires adapter assets. No generic iterative meta campaign integration.",
    ),
    "researchclawbench-arm": (
        "scripts/run_researchclawbench_system_arm.py",
        "ResearchClawBench task-level native-base/full-scitaste agent arms with optional "
        "official scoring. Requires benchmark checkout, task and provider configuration. "
        "These are configured conditions, not by themselves distinct external frameworks.",
    ),
    "newtonbench-counterfactual": (
        "scripts/run_newtonbench_counterfactual.py",
        "Shared-prefix NewtonBench action-counterfactual rollouts; mechanism evidence, "
        "not a complete idea-to-paper system comparison.",
    ),
    "scitastebench-decision-comparison": (
        "scripts/compare_scitastebench_decision_methods.py",
        "Prepare public decision requests/private scoring keys and score submissions. "
        "Does not run arbitrary external autonomous-research systems or generate tasks.",
    ),
    "external-formal-result-import": (
        "src/scitaste/evaluation/external_formal_study.py",
        "Import preregistered ResearchClawBench study protocols and verify measured "
        "arm results into project evidence. Import/verification only; cannot execute studies.",
    ),
    "prepared-study-lifecycle": (
        "scripts/run_project_research_cycle.py",
        "Prepared idea-bound iterative unlearning through results, paper/review/revision "
        "and experience disposition. Study question, source and task must be supplied; "
        "not autonomous task invention or a broad comparative campaign.",
    ),
}


def planning_capabilities(code_root: Path | None = None):
    root = code_root.resolve(strict=True) if code_root else None
    package = Path(__file__).resolve().parent.parent
    descriptions, provenance = {}, {}
    for identity, (locator, description) in _CAPABILITIES.items():
        if locator.startswith("src/scitaste/"):
            path = (package / locator.removeprefix("src/scitaste/")).resolve(strict=True)
            path.relative_to(package)
            source_origin = "installed-package"
        elif root is not None:
            path = (root / locator).resolve(strict=True)
            path.relative_to(root)
            source_origin = "explicit-code-root"
        else:
            continue
        descriptions[identity] = description
        provenance[identity] = {
            "source_locator": locator,
            "source_origin": source_origin,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "description": description,
            "execution_readiness_verified": False,
        }
    return descriptions, provenance


def design_handoff(proposal, *, design_sha256, capabilities):
    """Expose per-study missing work, without synthesizing shell commands or approval."""
    rows = []
    for study in proposal.studies:
        capability = capabilities.get(study.executor_id)
        rows.append(
            {
                "study_id": study.study_id,
                "selected_next": (
                    proposal.next_work_item is None and study.study_id == proposal.next_study_id
                ),
                "question": study.question,
                "executor_id": study.executor_id,
                "capability": capability,
                "declared_gaps": list(study.execution_gaps),
                "resource_requirements": study.required_models_data_and_compute,
                "status": "needs-adapter" if capability is None else "needs-execution-binding",
                "execution_authorized": False,
            }
        )
    return {
        "schema_version": "1.0",
        "design_sha256": design_sha256,
        "studies": rows,
        "next_work_item": (
            proposal.next_work_item.model_dump(mode="json") if proposal.next_work_item else None
        ),
        "scientific_adequacy_established": False,
        "execution_authorized": False,
        "note": "Model-proposed needs only. No shell command, dataset or formal assignment "
        "is created by this handoff. Missing gaps do not establish readiness.",
    }
