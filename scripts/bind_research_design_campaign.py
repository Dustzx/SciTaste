"""Attach a scientific design to an existing campaign launcher without executing it."""

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.campaign_execution import (
    EvaluationCampaignLaunchConfig,
    load_evaluation_campaign_launch_config,
)
from scitaste.evaluation.cell_plan import load_evaluation_cell_plan
from scitaste.evaluation.research_design_binding import (
    CampaignResearchDesignBinding,
    validate_research_design_binding,
)
from scitaste.project import ProjectRuntime, inspect_current_idea_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "design", "plan", "launch-config", "mapping", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--study-id", required=True)
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    design = args.design.resolve(strict=True)
    design.relative_to(root)
    args.output.resolve().relative_to(root)
    plan = load_evaluation_cell_plan(args.plan)
    original = load_evaluation_campaign_launch_config(args.launch_config)
    binding = CampaignResearchDesignBinding(
        design_locator=str(design.relative_to(root)),
        design_sha256=hashlib.sha256(design.read_bytes()).hexdigest(),
        study_id=args.study_id,
        plan_sha256=plan.plan_sha256,
        comparisons=json.loads(args.mapping.read_text()),
    )
    current = inspect_current_idea_revision(ProjectRuntime(root.parent.parent), root.name)
    if not current.artifact_verified or current.current_binding is None:
        raise ValueError("Current verified project idea required")
    validate_research_design_binding(
        binding, project_root=root, idea_sha256=current.current_binding.artifact_sha256, plan=plan
    )
    systems = {
        s for pair in binding.comparisons.values() for s in (pair.treatment, pair.comparator)
    }
    if systems - original.launchers.keys():
        raise ValueError("Study comparison has no configured system launcher")
    configured = EvaluationCampaignLaunchConfig.model_validate(
        {
            **original.model_dump(mode="json"),
            "schema_version": "1.2",
            "research_design": binding.model_dump(mode="json"),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(configured.model_dump_json(indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "bound-not-executed",
                "config_sha256": configured.config_sha256,
                "execution_authorized": False,
                "scientific_adequacy_established": False,
            }
        )
    )


if __name__ == "__main__":
    main()
