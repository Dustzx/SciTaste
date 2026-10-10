"""Compile explicit development task selections from registered protocol resources.

Model prose never supplies dataset paths, scoring code or resource approvals.
"""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from scitaste.evaluation.cell_plan import compile_evaluation_cell_plan
from scitaste.evaluation.development_selection import development_task_eligible
from scitaste.evaluation.prelaunch import ExperimentPrelaunchManifest
from scitaste.evaluation.research_design_binding import (
    CampaignResearchDesignBinding,
    validate_research_design_binding,
)
from scitaste.model_nodes.research_design import ResearchDesignProposal
from scitaste.project import ProjectRuntime, inspect_current_idea_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "design", "template", "selection", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--study-id", required=True)
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    design_path = args.design.resolve(strict=True)
    design_path.relative_to(root)
    args.output.resolve().relative_to(root)
    design = ResearchDesignProposal.model_validate_json(design_path.read_bytes())
    study = next((s for s in design.studies if s.study_id == args.study_id), None)
    if study is None:
        raise ValueError("Unknown study")
    selection = json.loads(args.selection.read_text())
    if set(selection) != {"manifest_id", "lane_id", "task_ids", "comparisons"}:
        raise ValueError(
            "Selection must name manifest, one existing lane, task IDs and comparisons"
        )
    template = ExperimentPrelaunchManifest.model_validate(yaml.safe_load(args.template.read_text()))
    if template.study_scope != "pilot":
        raise ValueError(
            "Do not resample formal/robustness protocols through the development compiler"
        )
    lanes = [lane for lane in template.lanes if lane.lane_id == selection["lane_id"]]
    if len(lanes) != 1:
        raise ValueError("Select one registered execution lane")
    selected = selection["task_ids"]
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Task selection must be nonempty and unique")
    tasks = {t.task_id: t for t in template.tasks}
    if set(selected) - set(lanes[0].task_ids):
        raise ValueError("Selected tasks are absent from the registered lane")
    if any(
        not development_task_eligible(tasks[key], study_scope=template.study_scope)
        for key in selected
    ):
        raise ValueError(
            "Task has no explicit development-use split; use its dedicated assignment path"
        )
    pairs = selection["comparisons"]
    systems = {system for pair in pairs.values() for system in pair.values()}
    if systems - set(lanes[0].system_ids):
        raise ValueError("Selected systems are absent from the registered lane")
    payload = template.model_dump(mode="json")
    lane = lanes[0].model_dump(mode="json")
    lane.update(
        system_ids=sorted(systems),
        task_ids=selected,
        planned_cells=len(systems) * len(selected) * len(lane["seeds"]) * lane["repetitions"],
    )
    if lane.get("system_api_models"):
        lane["system_api_models"] = [
            m for m in lane["system_api_models"] if m["system_id"] in systems
        ]
    identity_input = json.dumps(
        {
            "design_sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
            "selection": selection,
            "output": str(args.output.resolve().relative_to(root)),
        },
        sort_keys=True,
    ).encode()
    compiled_identity = "generated-study-" + hashlib.sha256(identity_input).hexdigest()[:20]
    # Never inherit an old campaign's write targets, even when a model echoes
    # the template manifest ID. These new directories are project-owned.
    retention_root = args.output.resolve().relative_to(Path.cwd().resolve()).as_posix()
    payload["retention"].update(
        output_root=retention_root + "/campaign",
        archive_root=retention_root + "/archive",
    )
    payload.update(
        manifest_id=compiled_identity,
        protocol_id=compiled_identity,
        scientific_question=study.question,
        claim_allowed="Development execution observations only; design-to-endpoint and sampling "
        "semantics are not yet verified.",
        claim_forbidden="No formal effectiveness, generalization or causal Taste claim follows "
        "from compilation or inherited resource readiness.",
        systems=[s for s in payload["systems"] if s["system_id"] in systems],
        tasks=[tasks[key].model_dump(mode="json") for key in selected],
        lanes=[lane],
        launch_order=[lane["lane_id"]],
        approval={},
    )
    manifest = ExperimentPrelaunchManifest.model_validate(payload)
    plan = compile_evaluation_cell_plan(manifest)
    binding = CampaignResearchDesignBinding(
        design_locator=str(design_path.relative_to(root)),
        design_sha256=hashlib.sha256(design_path.read_bytes()).hexdigest(),
        study_id=args.study_id,
        plan_sha256=plan.plan_sha256,
        comparisons=pairs,
    )
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if not current.artifact_verified or current.current_binding is None:
        raise ValueError("Verified current project idea required")
    validate_research_design_binding(
        binding, project_root=root, idea_sha256=current.current_binding.artifact_sha256, plan=plan
    )
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    for filename, value in (
        ("PRELAUNCH.json", manifest),
        ("CELL_PLAN.json", plan),
        ("DESIGN_BINDING.json", binding),
    ):
        (output / filename).write_text(value.model_dump_json(indent=2) + "\n")
    implementation = {
        "schema_version": "1.0",
        "proposal_sha256": manifest.proposal_sha256,
        "design_sha256": binding.design_sha256,
        "template_protocol_id": template.protocol_id,
        "systems": {
            system.system_id: system.model_dump(mode="json") for system in manifest.systems
        },
        "primary_endpoint": manifest.primary_endpoint,
        "registered_analysis": manifest.analysis.model_dump(mode="json")
        if manifest.analysis
        else None,
        "requested_comparisons": [
            c.model_dump(mode="json") for c in design.comparisons if c.comparison_id in pairs
        ],
        "requested_primary_outcome": study.primary_outcome,
        "treatment_semantic_equivalence_verified": False,
        "metric_semantic_equivalence_verified": False,
        "interpretation": (
            "Implementation refs and registered analysis describe configured behavior. "
            "Model comparison prose is a proposal, not implementation evidence."
        ),
    }
    implementation_path = output / "IMPLEMENTATION_CONTRACT.json"
    implementation_path.write_text(json.dumps(implementation, indent=2) + "\n")
    (output / "COMPILATION.json").write_text(
        json.dumps(
            {
                "status": "development-matrix-compiled-not-authorized",
                "template_sha256": hashlib.sha256(args.template.read_bytes()).hexdigest(),
                "selection_sha256": hashlib.sha256(args.selection.read_bytes()).hexdigest(),
                "design_sha256": binding.design_sha256,
                "plan_sha256": plan.plan_sha256,
                "compiled_manifest_id": compiled_identity,
                "requested_manifest_id": selection["manifest_id"],
                "implementation_contract_sha256": hashlib.sha256(
                    implementation_path.read_bytes()
                ).hexdigest(),
                "task_ids": selected,
                "system_ids": sorted(systems),
                "assignment_count": len(plan.cells),
                "requested_primary_outcome": study.primary_outcome,
                "configured_primary_endpoint": manifest.primary_endpoint,
                "metric_semantic_equivalence_verified": False,
                "sampling_semantic_equivalence_verified": False,
                "execution_authorized": False,
                "remaining": "Bind compatible score endpoints and assess sampling semantics; "
                "register the plan through the existing evaluation workflow before launch.",
            },
            indent=2,
        )
    )
    print(json.dumps({"status": "compiled-not-executed", "assignments": len(plan.cells)}))


if __name__ == "__main__":
    main()
