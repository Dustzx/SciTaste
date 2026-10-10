"""Compile model-selected project assets into a fresh bounded Native task."""

import json
from pathlib import Path

from scitaste.executor.workspace_task import asset_bindings, prepare_workspace_task, sha
from scitaste.model_nodes.research_design import ResearchDesignProposal


def resource_option(project, manifest):
    root = project.resolve(strict=True)
    path = manifest.resolve(strict=True)
    path.relative_to(root)
    payload = json.loads(path.read_text())
    if set(payload) - {"remote_resource"} != {
        "assets",
        "harness",
        "backend",
        "max_rounds",
        "wall_seconds",
    }:
        raise ValueError("Workspace resources need assets, harness, backend and bounded runtime")
    assets = (root / payload["assets"]).resolve(strict=True)
    harness = (root / payload["harness"]).resolve(strict=True)
    assets.relative_to(root)
    harness.relative_to(root)
    backend = (root / payload["backend"]).resolve(strict=True)
    if not (harness / "agent_base/tools/tool_file.py").is_file():
        raise ValueError("Resource option lacks a workspace tool provider")
    if not 1 <= payload["max_rounds"] <= 120 or not 1 <= payload["wall_seconds"] <= 10800:
        raise ValueError("Resource runtime must be bounded")
    files = asset_bindings(root, assets)
    remote = None
    remote_binding = None
    if payload.get("remote_resource"):
        from scitaste.executor.remote_workspace_tool import RemoteWorkspaceResource

        remote_path = (root / payload["remote_resource"]).resolve(strict=True)
        remote_path.relative_to(root)
        remote = RemoteWorkspaceResource.model_validate_json(remote_path.read_bytes())
        if remote.max_jobs * remote.wall_seconds > payload["wall_seconds"]:
            raise ValueError("Remote resources exceed study runtime")
        remote_binding = {
            "locator": remote_path.relative_to(root).as_posix(),
            "sha256": sha(remote_path),
            "resource": remote.model_dump(mode="json"),
        }
    tool_sources = {}
    for source in harness.rglob("*.py"):
        if source.is_file():
            source.resolve(strict=True).relative_to(root)
            tool_sources[source.relative_to(root).as_posix()] = sha(source)
    binding = {
        "locator": path.relative_to(root).as_posix(),
        "sha256": sha(path),
        "assets_sha256": sha(assets),
        "backend_sha256": sha(backend),
        "tool_sources": tool_sources,
        "files": files,
        "remote_workspace": remote_binding,
    }
    return {
        "executor_id": "scitaste-native-workspace",
        "files": files,
        "max_rounds": payload["max_rounds"],
        "wall_seconds": payload["wall_seconds"],
        "gpu_enabled": bool(remote and remote.gpu_indices),
        "remote_workspace": remote_binding,
        "max_api_liability_usd": 8,
        "report_reserve_usd": 1.5,
        "scope": "Available development assets, not a prepared experiment or execution approval",
    }, binding


def compile_workspace_selection(*, project, design_path, resource_binding, output):
    root = project.resolve(strict=True)
    option, current = resource_option(root, root / resource_binding["locator"])
    if current != resource_binding:
        raise ValueError("Workspace resources changed during model planning")
    proposal = ResearchDesignProposal.model_validate_json(design_path.read_bytes())
    selection = proposal.workspace_selection
    if selection is None:
        raise ValueError("Design did not select workspace provisioning")
    if selection.resource_option_id != Path(current["locator"]).stem:
        raise ValueError("Selected resource identity differs from supplied binding")
    targets = selection.asset_targets
    if len(set(targets)) != len(targets) or set(targets) - option["files"].keys():
        raise ValueError("Model selected duplicate or undeclared assets")
    resource = json.loads((root / current["locator"]).read_text())
    output = output.resolve()
    output.relative_to(root)
    output.mkdir(parents=True, exist_ok=False)
    manifest = output / "SELECTED_ASSETS.json"
    files = {
        name: {key: value for key, value in option["files"][name].items() if key != "sha256"}
        for name in targets
    }
    with manifest.open("x") as stream:
        json.dump({"files": files}, stream, indent=2)
    task_output = output / (design_path.resolve(strict=True).parent.name + "-task")
    plan = prepare_workspace_task(
        project=root,
        design=design_path,
        study_id=selection.study_id,
        comparison_id=selection.comparison_id,
        comparison_arm=selection.comparison_arm,
        assets=manifest,
        harness=root / resource["harness"],
        backend=root / resource["backend"],
        output=task_output,
        max_rounds=resource["max_rounds"],
        wall_seconds=resource["wall_seconds"],
        remote_resource=root / resource["remote_resource"]
        if resource.get("remote_resource")
        else None,
    )
    with (output / "PROVISION.json").open("x") as stream:
        json.dump(
            {
                "resource_binding": current,
                "selection": selection.model_dump(mode="json"),
                "plan": str(task_output / "PLAN.json"),
                "plan_sha256": sha(task_output / "PLAN.json"),
                "execution_authorized": False,
            },
            stream,
            indent=2,
        )
    return plan
