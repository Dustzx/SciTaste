"""Project-owned study workspaces without a benchmark TaskRunner or task schema."""

import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath

from scitaste.model_nodes.research_design import ResearchDesignProposal
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.models import validate_entry_id
from scitaste.project.research_artifact import register_artifact


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def study_instructions(design, study_id, comparison_id, comparison_arm):
    if comparison_arm not in {"treatment", "comparator"}:
        raise ValueError("Select treatment or comparator explicitly")
    study = next((s for s in design.studies if s.study_id == study_id), None)
    comparison = next((c for c in design.comparisons if c.comparison_id == comparison_id), None)
    if (
        study is None
        or comparison is None
        or comparison_id not in study.comparison_ids
        or study.executor_id != "scitaste-native-workspace"
    ):
        raise ValueError("Study does not bind an executable Native component")
    hypotheses = [
        h.model_dump(mode="json")
        for h in design.hypotheses
        if h.hypothesis_id in study.hypothesis_ids
    ]
    if len(hypotheses) != len(set(study.hypothesis_ids)):
        raise ValueError("Study references undefined hypotheses")
    instructions = {
        "study": study.model_dump(mode="json"),
        "comparison": comparison.model_dump(mode="json"),
        "selected_arm_description": getattr(comparison, comparison_arm),
        "hypotheses": hypotheses,
        "execution_authorized": False,
        "scope": "one project-owned study component; absent arms remain unimplemented",
    }
    if design.scientific_reasoning is not None:
        instructions["scientific_reasoning"] = design.scientific_reasoning.model_dump(mode="json")
    return instructions


def asset_bindings(root, manifest):
    payload = json.loads(manifest.read_text())
    if set(payload) != {"files"} or not payload["files"]:
        raise ValueError("Declare a nonempty files mapping of project assets")
    bindings = {}
    for target, spec in payload["files"].items():
        relative = PurePosixPath(target)
        if (
            relative.is_absolute()
            or len(relative.parts) < 2
            or ".." in relative.parts
            or str(relative) != target
            or "\\" in target
            or relative.parts[0] not in {"data", "references", "code"}
        ):
            raise ValueError("Workspace assets must be canonical data/references/code files")
        if set(spec) != {"locator", "role", "use_constraints"}:
            raise ValueError("Asset needs locator, role and explicit use_constraints")
        if spec["role"] not in {"data", "reference", "starter-code"} or not spec["use_constraints"]:
            raise ValueError("Unknown asset role or missing use constraints")
        source = (root / spec["locator"]).resolve(strict=True)
        source.relative_to(root)
        if not source.is_file():
            raise ValueError("Declare individual asset files, not broad directories")
        bindings[target] = {
            **spec,
            "locator": source.relative_to(root).as_posix(),
            "sha256": sha(source),
        }
    names = set(bindings)
    if any(str(parent) in names for name in names for parent in PurePosixPath(name).parents):
        raise ValueError("Workspace file and directory targets conflict")
    return bindings


def prepare_workspace_task(
    *,
    project,
    design,
    study_id,
    comparison_id,
    comparison_arm,
    assets,
    harness,
    backend,
    output,
    max_rounds=40,
    wall_seconds=1800,
    max_experiments=None,
    remote_resource=None,
    resume=False,
):
    root = project.resolve(strict=True)
    if max_experiments is not None and (type(max_experiments) is not int or max_experiments < 0):
        raise ValueError("Experiment allocation must be a nonnegative integer")
    design, assets, harness, backend = (
        p.resolve(strict=True) for p in (design, assets, harness, backend)
    )
    for path in (design, assets, harness, output.resolve()):
        path.relative_to(root)
    validate_entry_id(output.name, field_name="project task identity")
    if not 1 <= max_rounds <= 120 or not 1 <= wall_seconds <= 10800:
        raise ValueError("Explicit bounded round/runtime envelope required")
    proposal = ResearchDesignProposal.model_validate_json(design.read_bytes())
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if (
        not current.artifact_verified
        or current.current_binding is None
        or proposal.idea_sha256 != current.current_binding.artifact_sha256
    ):
        raise ValueError("Design must target the current verified project idea")
    instructions = study_instructions(proposal, study_id, comparison_id, comparison_arm)
    files = asset_bindings(root, assets)
    remote_binding = None
    if remote_resource is not None:
        from scitaste.executor.remote_workspace_tool import RemoteWorkspaceResource

        resource_path = remote_resource.resolve(strict=True)
        resource_path.relative_to(root)
        resource = RemoteWorkspaceResource.model_validate_json(resource_path.read_bytes())
        if max_experiments is not None and max_experiments != resource.max_jobs:
            raise ValueError("Explicit experiment cap must match the remote job allocation")
        if resource.max_jobs * resource.wall_seconds > wall_seconds:
            raise ValueError("Remote reservations exceed the study wall-time envelope")
        remote_binding = {
            "locator": resource_path.relative_to(root).as_posix(),
            "sha256": sha(resource_path),
            "resource": resource.model_dump(mode="json"),
        }
    if not (harness / "agent_base/tools/tool_file.py").is_file():
        raise ValueError("Explicit tool-provider source is required")
    runtime = {}
    for path in harness.rglob("*.py"):
        if path.is_file():
            path.resolve(strict=True).relative_to(root)
            runtime[path.relative_to(root).as_posix()] = sha(path)
    plan = {
        "schema_version": "1.1",
        "workspace_kind": "project-study",
        "executor_id": "scitaste-native-workspace",
        "controller_owner": "scitaste-native",
        "project_id": root.name,
        "idea_revision": current.current_binding.model_dump(mode="json"),
        "task_id": output.name,
        "task_origin": "model-study-on-explicit-project-assets",
        "scope": "development component; not an official benchmark or complete comparison",
        "harness": harness.relative_to(root).as_posix(),
        "runtime_sources": runtime,
        "backend": {"path": str(backend), "sha256": sha(backend)},
        "asset_manifest": {"locator": assets.relative_to(root).as_posix(), "sha256": sha(assets)},
        "workspace_files": files,
        "task_assets": {row["locator"]: row["sha256"] for row in files.values()},
        "research_design": {
            "locator": design.relative_to(root).as_posix(),
            "sha256": sha(design),
            "study_id": study_id,
            "comparison_id": comparison_id,
            "comparison_arm": comparison_arm,
            "instructions": instructions,
        },
        "resource_envelope": {
            "max_api_liability_usd": 8,
            "report_reserve_usd": 1.5,
            "gpu_enabled": False,
            "max_rounds": max_rounds,
            "wall_seconds": wall_seconds,
            "max_output_tokens": 16384,
        },
        "condition": "scitaste-native-controller",
        "split_role": "development",
        "execution_authorized": False,
        "formal_evidence_eligible": False,
    }
    from scitaste.executor.research_harness import default_harness_binding

    if resume and (output / "PLAN.json").is_file():
        existing = json.loads((output / "PLAN.json").read_text())
        if "research_harness" in existing:
            plan["research_harness"] = existing["research_harness"]
            plan["isolate_workspace_commands"] = True
    else:
        plan["research_harness"] = default_harness_binding()
        plan["isolate_workspace_commands"] = True
    if max_experiments is not None:
        plan["resource_envelope"]["max_experiments"] = max_experiments
    output.mkdir(parents=True, exist_ok=resume)
    if remote_binding is not None:
        plan["remote_workspace"] = remote_binding
        plan["resource_envelope"]["gpu_enabled"] = bool(resource.gpu_indices)
        plan["resource_envelope"]["max_experiments"] = resource.max_jobs
        plan["resource_envelope"]["gpu_hours"] = (
            resource.max_jobs * resource.wall_seconds * len(resource.gpu_indices) / 3600
        )
    plan_path = output / "PLAN.json"
    if resume and plan_path.exists():
        if json.loads(plan_path.read_text()) != plan:
            raise ValueError("Retained prepared task differs from selected inputs")
    else:
        with plan_path.open("x") as stream:
            json.dump(plan, stream, indent=2)
    register_artifact(
        project=root,
        artifact=output / "PLAN.json",
        provider="deterministic",
        model="project-workspace-provisioner",
        condition=plan["condition"],
        status="prepared-not-executed",
    )
    return plan


def load_native_workspace_plan(project, plan_path):
    root = project.resolve(strict=True)
    plan_path = plan_path.resolve(strict=True)
    plan_path.relative_to(root)
    plan = json.loads(plan_path.read_text())
    if plan.get("workspace_kind") == "open-research-benchmark":
        from scitaste.benchmark.open_research import load_plan

        return load_plan(root, plan)
    if plan.get("workspace_kind") != "project-study":
        from scitaste.executor.benchmark_task import load_benchmark_task

        return load_benchmark_task(root, plan_path, executor_id="scitaste-native-workspace")
    if (
        plan["project_id"] != root.name
        or plan["executor_id"] != "scitaste-native-workspace"
        or plan["controller_owner"] != "scitaste-native"
        or (plan["resource_envelope"]["gpu_enabled"] and not plan.get("remote_workspace"))
    ):
        raise ValueError("Invalid Native CPU project task identity")
    if plan.get("remote_workspace"):
        from scitaste.executor.remote_workspace_tool import RemoteWorkspaceResource

        bound = plan["remote_workspace"]
        path = (root / bound["locator"]).resolve(strict=True)
        path.relative_to(root)
        resource = RemoteWorkspaceResource.model_validate_json(path.read_bytes())
        if sha(path) != bound["sha256"] or resource.model_dump(mode="json") != bound["resource"]:
            raise ValueError("Bound remote resources changed")
        envelope = plan["resource_envelope"]
        if (
            envelope.get("max_experiments") != resource.max_jobs
            or envelope.get("gpu_hours")
            != resource.max_jobs * resource.wall_seconds * len(resource.gpu_indices) / 3600
            or resource.max_jobs * resource.wall_seconds > envelope["wall_seconds"]
            or envelope["gpu_enabled"] != bool(resource.gpu_indices)
        ):
            raise ValueError("Remote resource envelope changed")
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if (
        not current.artifact_verified
        or current.current_binding is None
        or current.current_binding.artifact_sha256 != plan["idea_revision"]["artifact_sha256"]
    ):
        raise ValueError("Project idea changed; prepare a new workspace task")
    for table in (plan["task_assets"], plan["runtime_sources"]):
        for locator, expected in table.items():
            path = (root / locator).resolve(strict=True)
            path.relative_to(root)
            if sha(path) != expected:
                raise ValueError("Bound project task asset changed")
    if sha(Path(plan["backend"]["path"])) != plan["backend"]["sha256"]:
        raise ValueError("Bound backend configuration changed")
    bound = plan["research_design"]
    for row in (bound, plan["asset_manifest"]):
        path = (root / row["locator"]).resolve(strict=True)
        path.relative_to(root)
        if sha(path) != row["sha256"]:
            raise ValueError("Design or resource manifest changed")
    proposal = ResearchDesignProposal.model_validate_json((root / bound["locator"]).read_bytes())
    if (
        proposal.idea_sha256 != plan["idea_revision"]["artifact_sha256"]
        or study_instructions(
            proposal, bound["study_id"], bound["comparison_id"], bound["comparison_arm"]
        )
        != bound["instructions"]
        or asset_bindings(root, root / plan["asset_manifest"]["locator"]) != plan["workspace_files"]
    ):
        raise ValueError("Project task differs from its design/resources")
    return plan


def initialize_project_workspace(project, plan, workspace):
    """Materialize declared files and instructions only; never run model-generated code."""
    if plan.get("workspace_kind") == "open-research-benchmark":
        from scitaste.benchmark.open_research import initialize_workspace

        return initialize_workspace(project, plan, workspace)
    root = project.resolve(strict=True)
    workspace = workspace.resolve()
    workspace.relative_to(root)
    workspace.mkdir(parents=True, exist_ok=False)
    for target, source in plan["workspace_files"].items():
        path = (root / source["locator"]).resolve(strict=True)
        path.relative_to(root)
        if sha(path) != source["sha256"]:
            raise ValueError("Asset changed before workspace initialization")
        destination = workspace / target
        destination.resolve().relative_to(workspace)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    for directory in ("code", "outputs", "report/images"):
        (workspace / directory).mkdir(parents=True, exist_ok=True)
    instructions = (
        "# Project research task\n\nImplement the bound study component using the declared assets. "
        "Run actual CPU experiments within the task budget, retain code and outputs, then write "
        "report/report.md with observed results, figures and limitations. Negative/null results "
        "are valid. Do not claim official benchmark scoring or unexecuted comparison arms. "
        "Local GPU is disabled. Remote execution is allowed only when explicitly bound below. "
        "Assets and their constraints follow; no implicit permission for new resources.\n\n"
        + json.dumps(plan["research_design"]["instructions"], indent=2)
        + "\n\nDeclared assets:\n"
        + json.dumps(plan["workspace_files"], indent=2)
        + "\n\nBound remote resources (null means no remote tool):\n"
        + json.dumps(plan.get("remote_workspace"), indent=2)
    )
    with (workspace / "INSTRUCTIONS.md").open("x") as stream:
        stream.write(instructions)
    return workspace / "INSTRUCTIONS.md"
