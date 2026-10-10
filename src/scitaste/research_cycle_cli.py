"""Installed CLI entry for the live research cycle with explicit executor workspace."""

import json
import subprocess
import sys
from pathlib import Path

from scitaste.project.research_cycle import configure_parser


def register_research_cycle_cli(project_commands):
    parser = configure_parser(
        project_commands.add_parser(
            "research-cycle",
            help="Run/resume the live task-to-paper cycle using an explicit executor checkout",
        )
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Trusted checkout for legacy/unlearning or next-planning scripts; optional for Native",
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    parser.set_defaults(handler=run_research_cycle)
    prepare = project_commands.add_parser(
        "prepare-workspace-task", help="Bind a project study and explicit assets to a Native task"
    )
    for key in ("project", "design", "assets", "harness", "backend", "output"):
        prepare.add_argument("--" + key, type=Path, required=True)
    for key in ("study-id", "comparison-id"):
        prepare.add_argument("--" + key, required=True)
    prepare.add_argument("--comparison-arm", choices=("treatment", "comparator"), required=True)
    prepare.add_argument("--max-rounds", type=int, default=40)
    prepare.add_argument("--wall-seconds", type=int, default=1800)
    prepare.add_argument("--max-experiments", type=int)
    prepare.add_argument("--remote-resource", type=Path)
    prepare.add_argument(
        "--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    prepare.set_defaults(handler=prepare_workspace)


def prepare_workspace(args):
    from scitaste.executor.workspace_task import prepare_workspace_task

    keys = (
        "project",
        "design",
        "assets",
        "harness",
        "backend",
        "output",
        "study_id",
        "comparison_id",
        "comparison_arm",
        "max_rounds",
        "wall_seconds",
        "max_experiments",
        "remote_resource",
    )
    plan = prepare_workspace_task(**{key: getattr(args, key) for key in keys})
    print(
        json.dumps(
            {
                "task_id": plan["task_id"],
                "status": "prepared-not-executed",
                "task_origin": plan["task_origin"],
            }
        )
    )
    return 0


def run_research_cycle(args):
    if args.workspace is None and args.executor == "unlearning":
        raise ValueError("Unlearning still requires an explicit trusted workspace")
    workspace = args.workspace.resolve(strict=True) if args.workspace else Path.cwd()
    # These are executable backends, not part of a data-only project. Resolve
    # explicitly before changing the child's cwd, never import a caller's scripts.
    names = (
        (
            "pyproject.toml",
            "scripts/run_native_tools_development.py",
            "scripts/run_measured_paper_lifecycle.py",
            "scripts/plan_project_research.py",
        )
        if args.executor == "unlearning"
        else (
            "pyproject.toml",
            "scripts/run_native_benchmark_task.py",
            "scripts/run_native_report_lifecycle.py",
            "scripts/plan_project_research.py",
        )
    )
    for name in names if args.workspace else ():
        path = (workspace / name).resolve(strict=True)
        path.relative_to(workspace)
        if not path.is_file():
            raise ValueError("Research cycle requires the trusted executor checkout")
    command = [sys.executable, "-m", "scitaste.project.research_cycle", "--executor", args.executor]
    for name in (
        "project",
        "plan",
        "brief",
        "output",
        "baseline_run",
        "baseline_source",
        "figure_contract_repair",
        "task_context",
        "development_taste_library",
        "taste_deliberation_profile",
        "development_policy_refresh",
        "workflow_gaps",
        "execution_run",
        "report_delivery",
        "paper_backend",
        "review_profile",
        "venue_taste_profile",
        "credentials",
        "session_exchange",
        "paper_flow",
        "research_state",
    ):
        value = getattr(args, name)
        if value is not None:
            # User paths are relative to the invoking directory, not workspace.
            command.extend(["--" + name.replace("_", "-"), str(value.resolve())])
    for name in (
        "allow_api",
        "allow_execution",
        "acquire_next_resources",
        "acquire_planning_resources",
        "allow_network_download",
    ):
        if getattr(args, name):
            command.append("--" + name.replace("_", "-"))
    for resource in args.next_workspace_resources:
        command.extend(["--next-workspace-resources", str(resource.resolve())])
    for option in args.next_acquisition_option:
        command.extend(["--next-acquisition-option", str(option.resolve())])
    if args.objective:
        command.extend(["--objective", args.objective])
    if args.planning_backend:
        command.extend(["--planning-backend", str(args.planning_backend.resolve())])
    for name in (
        "planning_prepared_task",
        "planning_workspace_resources",
        "planning_evidence",
        "planning_acquisition_option",
    ):
        for value in getattr(args, name):
            command.extend(["--" + name.replace("_", "-"), str(value.resolve())])
    if args.next_planning_objective:
        command.extend(["--next-planning-objective", args.next_planning_objective])
    if args.paper_prefix:
        command.extend(["--paper-prefix", args.paper_prefix])
    if args.max_execution_continuations:
        command.extend(["--max-execution-continuations", str(args.max_execution_continuations)])
    for name in ("taste_decision_context", "taste_proposal_context", "taste_action_selection"):
        value = getattr(args, name, None)
        if value is not None:
            command.extend(["--" + name.replace("_", "-"), value])
    return subprocess.run(command, cwd=workspace, check=False).returncode
