"""CLI registration for project-owned AutoResearchClaw action runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.executor.project_workflow import (
    ProjectSubstrateActionWorkflow,
    load_project_substrate_config,
)


def register_project_substrate_cli(
    substrate_commands: argparse._SubParsersAction,
) -> None:
    project = substrate_commands.add_parser(
        "project",
        help="Plan, execute, resume, and verify a project-owned substrate action",
    )
    commands = project.add_subparsers(dest="substrate_project_command", required=True)

    plan = commands.add_parser("plan", help="Validate an action without writing or calling")
    _add_execution_identity(plan)
    plan.add_argument("--resume", action="store_true")
    plan.add_argument("--allow-live", action="store_true")
    _add_log_level(plan)
    plan.set_defaults(handler=_handle_plan)

    execute = commands.add_parser(
        "execute",
        help="Create or resume an auditable project-owned substrate action",
    )
    _add_execution_identity(execute)
    execute.add_argument("--resume", action="store_true")
    execute.add_argument(
        "--allow-live",
        action="store_true",
        help="Explicitly authorize the configured provider call",
    )
    execute.add_argument("--dry-run", action="store_true")
    _add_log_level(execute)
    execute.set_defaults(handler=_handle_execute)

    status = commands.add_parser(
        "status",
        help="Verify the registered manifest, immutable input, and output evidence",
    )
    status.add_argument("--project-id", required=True)
    status.add_argument("--run-id", required=True)
    status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level(status)
    status.set_defaults(handler=_handle_status)


def _add_execution_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--source-run",
        type=Path,
        default=None,
        help="AutoResearchClaw run snapshot to import; omit only with --resume",
    )
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--seed", type=int, default=0)


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _plan(args: argparse.Namespace) -> dict[str, object]:
    return ProjectSubstrateActionWorkflow(seed=args.seed).plan(
        load_project_substrate_config(args.config),
        outputs_root=args.outputs_root,
        run_id=args.run_id,
        source_run_dir=args.source_run,
        resume=args.resume,
        allow_live=args.allow_live,
    )


def _handle_plan(args: argparse.Namespace) -> int:
    print(json.dumps(_plan(args), indent=2, ensure_ascii=False))
    return 0


def _handle_execute(args: argparse.Namespace) -> int:
    if args.dry_run:
        summary = _plan(args)
    else:
        summary = ProjectSubstrateActionWorkflow(seed=args.seed).run(
            load_project_substrate_config(args.config),
            outputs_root=args.outputs_root,
            run_id=args.run_id,
            source_run_dir=args.source_run,
            resume=args.resume,
            allow_live=args.allow_live,
        )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] in {"planned", "complete"} else 1


def _handle_status(args: argparse.Namespace) -> int:
    summary = ProjectSubstrateActionWorkflow().status(
        outputs_root=args.outputs_root,
        project_id=args.project_id,
        run_id=args.run_id,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


__all__ = ["register_project_substrate_cli"]
