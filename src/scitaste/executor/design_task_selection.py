"""Compile model-selected study components using frozen prepared task resources."""

import hashlib
import json
from pathlib import Path

from scitaste.executor.project_task import load_project_task, prepare_project_task
from scitaste.executor.unlearning_resource import RemoteUnlearningResource
from scitaste.executor.workspace_task import load_native_workspace_plan, prepare_workspace_task
from scitaste.model_nodes.research_design import ResearchDesignProposal


def task_option(project: Path, path: Path):
    root = project.resolve(strict=True)
    path = path.resolve(strict=True)
    path.relative_to(root)
    payload = json.loads(path.read_text())
    if payload.get("executor_id") == "scitaste-native-workspace":
        plan = load_native_workspace_plan(root, path)
        if plan.get("workspace_kind") == "project-study":
            task_description = plan["research_design"]["instructions"]
        else:
            info = root / plan["benchmark"] / "tasks" / plan["task_id"] / "task_info.json"
            task_description = json.loads(info.read_text())
        return {
            "executor_id": "scitaste-native-workspace",
            "task_id": plan["task_id"],
            "task": task_description,
            "resource": plan["resource_envelope"],
            "implementation": "SciTaste Native controller on frozen visible task assets. "
            "The study question and selected comparison arm become execution instructions; "
            "this does not substitute another framework, activate full Taste, or implement "
            "the absent comparison arm. Original task assets and scorer are unchanged.",
            "scope": "prepared-study-component",
            "task_origin": plan["task_origin"],
        }, {
            "locator": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "idea_revision": plan["idea_revision"],
        }
    iterative = payload["task"]["schema_version"] == "1.1"
    task, _, binding = load_project_task(
        root, path, adapter=payload["adapter"], iterative=iterative
    )
    template = Path(payload["task_template_locator"])
    if hashlib.sha256(template.read_bytes()).hexdigest() != payload["task_template_sha256"]:
        raise ValueError("Original task template changed")
    if payload["adapter"] != "unlearning" or not iterative or not payload.get("remote_resource"):
        raise ValueError("Current lifecycle selection requires resource-bound iterative unlearning")
    resource = RemoteUnlearningResource.model_validate(payload["remote_resource"])
    return {
        "executor_id": "native-" + payload["adapter"],
        "task": task.model_dump(mode="json"),
        "resource": resource.model_dump(mode="json"),
        "implementation": "Native bounded candidate-code research on the frozen development "
        "task/scorer; method code is generated during execution. One arm only. "
        "No external-framework comparison or automatic learned-policy treatment is implied.",
        "scope": "prepared-study-component",
    }, binding


def compile_selected_task(
    *, project: Path, design_path: Path, source_plan: Path, expected_plan_sha256: str, output: Path
):
    root = project.resolve(strict=True)
    design = ResearchDesignProposal.model_validate_json(design_path.read_bytes())
    selection = design.task_selection
    if selection is None:
        raise ValueError("Design contains no selected task")
    if source_plan.resolve().parent.name != selection.task_option_id:
        raise ValueError("Selected task identity differs from supplied prepared plan")
    _, binding = task_option(root, source_plan)
    if binding["sha256"] != expected_plan_sha256:
        raise ValueError("Prepared task changed during planning")
    payload = json.loads(source_plan.read_text())
    study = next(s for s in design.studies if s.study_id == selection.study_id)
    compiled_plan = output / "PLAN.json"
    if payload.get("workspace_kind") == "project-study":
        output.mkdir(parents=True, exist_ok=True)
        task_output = output / (design_path.resolve().parent.name + "-task")
        compiled_plan = task_output / "PLAN.json"
        result = prepare_workspace_task(
            project=root,
            design=design_path,
            study_id=selection.study_id,
            comparison_id=selection.comparison_id,
            comparison_arm=selection.comparison_arm,
            assets=root / payload["asset_manifest"]["locator"],
            harness=root / payload["harness"],
            backend=Path(payload["backend"]["path"]),
            output=task_output,
            resume=True,
            max_rounds=payload["resource_envelope"]["max_rounds"],
            wall_seconds=payload["resource_envelope"]["wall_seconds"],
            max_experiments=payload["resource_envelope"].get("max_experiments"),
            remote_resource=root / payload["remote_workspace"]["locator"]
            if payload.get("remote_workspace")
            else None,
        )
    elif payload.get("executor_id") == "scitaste-native-workspace":
        if (
            design.idea_sha256 != payload["idea_revision"]["artifact_sha256"]
            or study.executor_id != payload["executor_id"]
            or selection.comparison_id not in study.comparison_ids
        ):
            raise ValueError("Design does not bind this Native task/idea/component")
        comparison = next(
            c for c in design.comparisons if c.comparison_id == selection.comparison_id
        )
        design_path = design_path.resolve(strict=True)
        design_path.relative_to(root)
        output = output.resolve()
        output.relative_to(root)
        result = {
            **payload,
            "research_design": {
                "locator": design_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
                "study_id": study.study_id,
                "comparison_id": comparison.comparison_id,
                "comparison_arm": selection.comparison_arm,
                "source_plan": binding,
                "instructions": {
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
                },
            },
        }
        output.mkdir(parents=True, exist_ok=False)
        with (output / "PLAN.json").open("x") as stream:
            json.dump(result, stream, indent=2)
        from scitaste.project.research_artifact import register_artifact

        register_artifact(
            project=root,
            artifact=output / "PLAN.json",
            provider="deterministic",
            model="design-task-compiler",
            condition="model-selected-native-component",
            status="prepared-not-executed",
            run_id=design_path.resolve().parent.name + "-task",
        )
    else:
        result = _compile_unlearning(root, payload, study, selection, design_path, output)
    from scitaste.model_nodes.session_exchange import retain_json

    retain_json(
        output / "SELECTION.json",
        {
            "source_plan": binding,
            "selection": selection.model_dump(mode="json"),
            "compiled_plan_sha256": hashlib.sha256(compiled_plan.read_bytes()).hexdigest(),
            "compiled_plan": str(compiled_plan.resolve()),
            "execution_authorized": False,
            "complete_study_implemented": False,
        },
    )
    return result


def _compile_unlearning(root, payload, study, selection, design_path, output):
    result = prepare_project_task(
        project=root,
        task_path=Path(payload["task_template_locator"]),
        adapter=payload["adapter"],
        candidate_source=root / payload["candidate_source"],
        study_question=study.question,
        output=output,
        design_path=design_path,
        study_id=selection.study_id,
        comparison_id=selection.comparison_id,
        comparison_arm=selection.comparison_arm,
        remote_resource=RemoteUnlearningResource.model_validate(payload["remote_resource"]),
    )
    return result
