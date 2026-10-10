"""Project-owned task envelopes for the existing ResearchClawBench executor."""

import hashlib
import json
from pathlib import Path

from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.research_artifact import register_artifact


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_benchmark_task(
    *,
    project: Path,
    benchmark: Path,
    harness: Path,
    backend: Path,
    task_id: str,
    output: Path,
    max_rounds: int = 40,
    wall_seconds: int = 1800,
    controller_owner: str = "researchharness",
):
    root = project.resolve(strict=True)
    if controller_owner not in {"researchharness", "scitaste-native"}:
        raise ValueError("Unknown controller owner")
    benchmark, harness, backend = (p.resolve(strict=True) for p in (benchmark, harness, backend))
    output.resolve().relative_to(root)
    # Task and executable assets are explicit project-local acquisitions. Do not
    # infer them from a model-supplied shell command or change the upstream task.
    for path in (benchmark, harness):
        path.relative_to(root)
    if Path(task_id).name != task_id or task_id in {".", ".."}:
        raise ValueError("Task ID must be a directory name")
    if not 1 <= max_rounds <= 120 or not 1 <= wall_seconds <= 10800:
        raise ValueError("Explicit bounded round/runtime envelope required")
    task = (benchmark / "tasks" / task_id).resolve(strict=True)
    task.relative_to(benchmark / "tasks")
    visible = [task / "task_info.json"]
    for name in ("data", "related_work"):
        if (task / name).exists():
            visible.extend(sorted(p for p in (task / name).rglob("*") if p.is_file()))
    assets = {}
    for path in visible:
        path.resolve(strict=True).relative_to(task)
        if path.is_symlink():
            raise ValueError("Task assets must not escape through symlinks")
        assets[path.relative_to(root).as_posix()] = _sha(path)
    code = {}
    for directory in (benchmark / "evaluation", harness):
        if not directory.is_dir():
            raise ValueError(f"Missing execution dependency: {directory.name}")
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".md"}:
                path.resolve(strict=True).relative_to(root)
                code[path.relative_to(root).as_posix()] = _sha(path)
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if not current.artifact_verified or current.current_binding is None:
        raise ValueError("Task preparation requires the current verified project idea")
    plan = {
        "schema_version": "1.0",
        "executor_id": (
            "scitaste-native-workspace"
            if controller_owner == "scitaste-native"
            else "researchclawbench-arm"
        ),
        "controller_owner": controller_owner,
        "project_id": root.name,
        "idea_revision": current.current_binding.model_dump(mode="json"),
        "benchmark": benchmark.relative_to(root).as_posix(),
        "harness": harness.relative_to(root).as_posix(),
        "task_id": task_id,
        "task_assets": assets,
        "runtime_sources": code,
        "backend": {"path": str(backend), "sha256": _sha(backend)},
        "condition": (
            "scitaste-native-controller" if controller_owner == "scitaste-native" else "native-base"
        ),
        "split_role": "development",
        "resource_envelope": {
            "gpu_enabled": False,
            "max_rounds": max_rounds,
            "wall_seconds": wall_seconds,
            "max_output_tokens": 16384,
        },
        "execution_authorized": False,
        "formal_evidence_eligible": False,
        "task_origin": "upstream-visible-task-not-autonomously-invented",
        "scope": "one-real-task-arm-not-external-framework-comparison",
    }
    output.mkdir(parents=True, exist_ok=False)
    artifact = output / "PLAN.json"
    with artifact.open("x") as stream:
        json.dump(plan, stream, indent=2)
    register_artifact(
        project=root,
        artifact=artifact,
        provider="deterministic",
        model="benchmark-task-provisioner",
        condition="prepared-cpu-api-task",
        status="prepared-not-executed",
    )
    return plan


def load_benchmark_task(project: Path, plan_path: Path, *, executor_id="researchclawbench-arm"):
    root = project.resolve(strict=True)
    plan_path = plan_path.resolve(strict=True)
    plan_path.relative_to(root)
    plan = json.loads(plan_path.read_text())
    if plan["project_id"] != root.name or plan["executor_id"] != executor_id:
        raise ValueError("Task belongs to a different project or executor")
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if (
        not current.artifact_verified
        or current.current_binding is None
        or current.current_binding.artifact_sha256 != plan["idea_revision"]["artifact_sha256"]
    ):
        raise ValueError("Project idea changed; prepare a new task envelope")
    for bindings in (plan["task_assets"], plan["runtime_sources"]):
        for locator, digest in bindings.items():
            path = (root / locator).resolve(strict=True)
            path.relative_to(root)
            if _sha(path) != digest:
                raise ValueError("Bound task/runtime asset changed")
    if _sha(Path(plan["backend"]["path"])) != plan["backend"]["sha256"]:
        raise ValueError("Task API configuration changed")
    if plan.get("research_design"):
        from scitaste.model_nodes.research_design import ResearchDesignProposal

        bound = plan["research_design"]
        prepared = (root / bound["source_plan"]["locator"]).resolve(strict=True)
        prepared.relative_to(root)
        if _sha(prepared) != bound["source_plan"]["sha256"]:
            raise ValueError("Original prepared task changed")
        original = json.loads(prepared.read_text())
        if {k: v for k, v in original.items() if k != "research_design"} != {
            k: v for k, v in plan.items() if k != "research_design"
        }:
            raise ValueError(
                "Design compilation altered frozen task resources or execution settings"
            )
        source = (root / bound["locator"]).resolve(strict=True)
        source.relative_to(root)
        if _sha(source) != bound["sha256"]:
            raise ValueError("Selected research design changed")
        design = ResearchDesignProposal.model_validate_json(source.read_bytes())
        selection = design.task_selection
        study = next(s for s in design.studies if s.study_id == bound["study_id"])
        comparison = next(
            c for c in design.comparisons if c.comparison_id == bound["comparison_id"]
        )
        if (
            design.idea_sha256 != plan["idea_revision"]["artifact_sha256"]
            or study.executor_id != executor_id
            or selection is None
            or selection.task_option_id != prepared.parent.name
            or selection.study_id != study.study_id
            or selection.comparison_id != comparison.comparison_id
            or selection.comparison_arm != bound["comparison_arm"]
            or comparison.comparison_id not in study.comparison_ids
        ):
            raise ValueError("Selected design/task/component differs")
        expected = {
            "study": study.model_dump(mode="json"),
            "comparison": comparison.model_dump(mode="json"),
            "selected_arm_description": getattr(comparison, selection.comparison_arm),
            "hypotheses": [
                h.model_dump(mode="json")
                for h in design.hypotheses
                if h.hypothesis_id in study.hypothesis_ids
            ],
            "scope": "one planned task component; no whole comparison completed",
            "execution_authorized": False,
        }
        if bound["instructions"] != expected:
            raise ValueError("Task instructions differ from bound design")
    return plan
