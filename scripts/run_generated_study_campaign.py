"""Register a compiled study and delegate execution/resume to the existing runner.

No model text is interpreted as a shell command or resource authorization.
Launcher configuration and optional activation are separately supplied artifacts.
"""

import argparse
import fcntl
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.campaign_activation import load_evaluation_campaign_activation
from scitaste.evaluation.campaign_execution import (
    EvaluationCampaignLaunchConfig,
    ProjectEvaluationCampaignRunner,
    load_evaluation_campaign_launch_config,
)
from scitaste.evaluation.cell_plan import load_evaluation_cell_plan
from scitaste.evaluation.prelaunch import load_prelaunch_manifest
from scitaste.evaluation.project_materialization import prepare_project_evaluation
from scitaste.evaluation.research_design_binding import (
    CampaignResearchDesignBinding,
    validate_research_design_binding,
)
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.models import validate_entry_id


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_launch(project, compilation, launch_config):
    """Resolve exact compiled artifacts before any project write or process launch."""
    root = project.resolve(strict=True)
    compilation = compilation.resolve(strict=True)
    compilation.relative_to(root)
    receipt = json.loads((compilation / "COMPILATION.json").read_text())
    plan = load_evaluation_cell_plan(compilation / "CELL_PLAN.json")
    manifest = load_prelaunch_manifest(compilation / "PRELAUNCH.json").manifest
    binding = CampaignResearchDesignBinding.model_validate_json(
        (compilation / "DESIGN_BINDING.json").read_bytes()
    )
    implementation = json.loads((compilation / "IMPLEMENTATION_CONTRACT.json").read_text())
    if (
        receipt["plan_sha256"] != plan.plan_sha256
        or receipt["design_sha256"] != binding.design_sha256
        or receipt["implementation_contract_sha256"]
        != sha(compilation / "IMPLEMENTATION_CONTRACT.json")
        or plan.proposal_sha256 != manifest.proposal_sha256
        or implementation["proposal_sha256"] != manifest.proposal_sha256
        or implementation["design_sha256"] != binding.design_sha256
    ):
        raise ValueError("Compiled study artifacts differ from their recorded identity")
    runtime = ProjectRuntime(root.parent.parent)
    idea = inspect_current_idea_revision(runtime, root.name)
    if not idea.artifact_verified or idea.current_binding is None:
        raise ValueError("Current verified project idea required")
    validate_research_design_binding(
        binding, project_root=root, idea_sha256=idea.current_binding.artifact_sha256, plan=plan
    )
    original = load_evaluation_campaign_launch_config(launch_config)
    if original.research_design is not None and original.research_design != binding:
        raise ValueError("Supplied launcher is already bound to a different design")
    required = {cell.system_id for cell in plan.cells}
    if required - original.launchers.keys():
        raise ValueError("Selected study includes a system with no implemented launcher")
    configured = EvaluationCampaignLaunchConfig.model_validate(
        {
            **original.model_dump(mode="json"),
            "schema_version": "1.2",
            "research_design": binding.model_dump(mode="json"),
        }
    )
    return runtime, manifest, plan, configured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "compilation", "launch-config", "resource-corpus", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    parser.add_argument("--activation", type=Path)
    parser.add_argument("--allow-execution", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed-cells", action="store_true")
    parser.add_argument("--max-cells", type=int)
    args = parser.parse_args()
    root, output = args.project.resolve(strict=True), args.output.resolve()
    output.relative_to(root)
    for identity in (args.evaluation_id, args.run_id):
        validate_entry_id(identity, field_name="generated study identity")
    if args.retry_failed_cells and not args.resume:
        raise ValueError("Failed-assignment retry requires explicit resume")
    runtime, manifest, plan, config = prepare_launch(root, args.compilation, args.launch_config)
    activation = load_evaluation_campaign_activation(args.activation) if args.activation else None
    contract = {
        "schema_version": "1.0",
        "project_id": root.name,
        "evaluation_id": args.evaluation_id,
        "run_id": args.run_id,
        "compilation": str(args.compilation.resolve().relative_to(root)),
        "compilation_sha256": sha(args.compilation / "COMPILATION.json"),
        "manifest_file_sha256": sha(args.compilation / "PRELAUNCH.json"),
        "proposal_sha256": manifest.proposal_sha256,
        "plan_sha256": plan.plan_sha256,
        "launch_config_sha256": config.config_sha256,
        "resource_corpus_sha256": sha(args.resource_corpus),
        "activation_file_sha256": sha(args.activation) if args.activation else None,
        "scientific_adequacy_established": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract_path = output / "CONTRACT.json"
        if contract_path.exists():
            if json.loads(contract_path.read_text()) != contract:
                raise ValueError("Generated campaign inputs changed; preserve previous run")
        else:
            with contract_path.open("x") as stream:
                json.dump(contract, stream, indent=2)
            with (output / "LAUNCH_CONFIG.json").open("x") as stream:
                stream.write(config.model_dump_json(indent=2))
        snapshot = runtime.open(root.name)
        if args.evaluation_id not in snapshot.evaluation_locators:
            prepared = prepare_project_evaluation(
                project_id=root.name,
                evaluation_id=args.evaluation_id,
                manifest_path=args.compilation / "PRELAUNCH.json",
                resource_corpus_path=args.resource_corpus,
                source_root=args.source_root,
                evidence_root=args.evidence_root,
            )
            published_plan = json.loads(prepared.artifact_payloads["CELL_PLAN.json"])
            if published_plan["plan_sha256"] != plan.plan_sha256:
                raise ValueError("Registration recompiled a different study plan")
            runtime.publish_evaluation(
                root.name,
                prepared.bundle,
                artifact_payloads=prepared.artifact_payloads,
                expected_revision=snapshot.revision,
            )
        else:
            registered = runtime.open_evaluation(root.name, args.evaluation_id)
            if registered.proposal_sha256 != manifest.proposal_sha256:
                raise ValueError("Evaluation ID belongs to a different proposal")
        registered = runtime.open_evaluation(root.name, args.evaluation_id)
        evaluation_root = root / "evaluations" / args.evaluation_id
        registered_plan = load_evaluation_cell_plan(
            evaluation_root / registered.files["cell_plan"].locator
        )
        if registered_plan.plan_sha256 != plan.plan_sha256 or registered.files[
            "resource_corpus"
        ].sha256 != sha(args.resource_corpus):
            raise ValueError("Registered plan or resource corpus differs from supplied study")
        runner = ProjectEvaluationCampaignRunner(runtime, config, evidence_root=args.evidence_root)
        summary = runner.run(
            project_id=root.name,
            evaluation_id=args.evaluation_id,
            run_id=args.run_id,
            allow_execution=args.allow_execution,
            dry_run=not args.allow_execution,
            resume=args.resume,
            retry_failed_cells=args.retry_failed_cells,
            activation=activation,
            max_cells=args.max_cells,
        )
        # Every observation is retained, including blocked or interrupted campaigns.
        index = 1
        while (output / f"OBSERVATION-{index:04d}.json").exists():
            index += 1
        with (output / f"OBSERVATION-{index:04d}.json").open("x") as stream:
            stream.write(summary.model_dump_json(indent=2))
        print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
