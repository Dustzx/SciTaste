"""Focused CLI registration for project-owned model-node pilot runs."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.model_nodes.pilot_orchestration import ProjectPilotOrchestrator
from scitaste.project import ProjectRuntime


def register_model_node_pilot_cli(commands: argparse._SubParsersAction) -> None:
    model_node = commands.add_parser(
        "model-node",
        help="Plan, execute, resume, and verify bounded model-node pilots",
    )
    model_node_commands = model_node.add_subparsers(
        dest="model_node_command",
        required=True,
    )
    pilot = model_node_commands.add_parser("pilot", help="Project-owned pilot operations")
    pilot_commands = pilot.add_subparsers(dest="model_node_pilot_command", required=True)

    plan = pilot_commands.add_parser("plan", help="Validate a pilot without writing or calling")
    _add_execution_identity(plan)
    plan.add_argument("--allow-live", action="store_true")
    _add_log_level(plan)
    plan.set_defaults(handler=_handle_plan)

    execute = pilot_commands.add_parser(
        "execute",
        help="Create or resume a project-owned pilot run",
    )
    _add_execution_identity(execute)
    execute.add_argument("--resume", action="store_true")
    execute.add_argument("--allow-live", action="store_true")
    execute.add_argument("--dry-run", action="store_true")
    _add_log_level(execute)
    execute.set_defaults(handler=_handle_execute)

    status = pilot_commands.add_parser(
        "status",
        help="Verify project-owned pilot checkpoints, recordings, and report",
    )
    status.add_argument("--project-id", required=True)
    status.add_argument("--run-id", required=True)
    status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level(status)
    status.set_defaults(handler=_handle_status)


def _add_execution_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _handle_plan(args: argparse.Namespace) -> int:
    summary = ProjectPilotOrchestrator(ProjectRuntime(args.outputs_root)).plan(
        project_id=args.project_id,
        run_id=args.run_id,
        expected_revision=args.expected_revision,
        config_path=args.config,
        allow_live=args.allow_live,
    )
    print(summary.model_dump_json(indent=2))
    return 0


def _handle_execute(args: argparse.Namespace) -> int:
    orchestrator = ProjectPilotOrchestrator(ProjectRuntime(args.outputs_root))
    if args.dry_run:
        summary = orchestrator.plan(
            project_id=args.project_id,
            run_id=args.run_id,
            expected_revision=args.expected_revision,
            config_path=args.config,
            allow_live=args.allow_live,
        )
    else:
        summary = orchestrator.execute(
            project_id=args.project_id,
            run_id=args.run_id,
            expected_revision=args.expected_revision,
            config_path=args.config,
            resume=args.resume,
            allow_live=args.allow_live,
        )
    print(summary.model_dump_json(indent=2))
    return 0 if summary.acceptance_status in {"pass", "not_evaluated"} else 1


def _handle_status(args: argparse.Namespace) -> int:
    summary = ProjectPilotOrchestrator(ProjectRuntime(args.outputs_root)).status(
        project_id=args.project_id,
        run_id=args.run_id,
    )
    print(summary.model_dump_json(indent=2))
    return 0


__all__ = ["register_model_node_pilot_cli"]
