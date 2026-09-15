"""CLI for no-call model-role conformance planning and selection."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.model_role_conformance import (
    compile_model_role_selection,
    inspect_model_role_conformance,
    load_model_role_plan,
    load_model_role_selection,
    plan_model_role_conformance,
    save_model_role_document,
)


def register_model_role_cli(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    model_role = commands.add_parser(
        "model-role",
        help="Plan and compile task-excluded model-role conformance evidence",
    )
    subcommands = model_role.add_subparsers(dest="model_role_command", required=True)

    plan = subcommands.add_parser(
        "plan",
        help="Bind a candidate suite to the current inventory without running models",
    )
    plan.add_argument("--suite", type=Path, required=True)
    plan.add_argument("--repository-root", type=Path, default=Path("."))
    plan.add_argument("--output", type=Path, required=True)
    _add_log_level_option(plan)
    plan.set_defaults(handler=_handle_plan)

    compile_selection = subcommands.add_parser(
        "compile-selection",
        help="Compile exact role bindings only from existing actual receipts",
    )
    compile_selection.add_argument("--plan", type=Path, required=True)
    compile_selection.add_argument("--receipt", type=Path, action="append", default=[])
    compile_selection.add_argument("--evidence-root", type=Path, default=Path("."))
    compile_selection.add_argument("--output", type=Path, required=True)
    _add_log_level_option(compile_selection)
    compile_selection.set_defaults(handler=_handle_compile_selection)

    status = subcommands.add_parser(
        "status",
        help="Show receipt completeness, role readiness, and headline independence",
    )
    status.add_argument("--plan", type=Path, required=True)
    status.add_argument("--receipt", type=Path, action="append", default=[])
    status.add_argument("--selection", type=Path, default=None)
    status.add_argument("--evidence-root", type=Path, default=Path("."))
    _add_log_level_option(status)
    status.set_defaults(handler=_handle_status)


def _add_log_level_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _handle_plan(args: argparse.Namespace) -> int:
    plan = plan_model_role_conformance(args.suite, repository_root=args.repository_root)
    path = save_model_role_document(plan, args.output)
    print(plan.model_dump_json(indent=2))
    print(f"saved: {path}")
    return 0


def _handle_compile_selection(args: argparse.Namespace) -> int:
    plan = load_model_role_plan(args.plan)
    manifest = compile_model_role_selection(
        plan,
        args.receipt,
        evidence_root=args.evidence_root,
    )
    path = save_model_role_document(manifest, args.output)
    print(manifest.model_dump_json(indent=2))
    print(f"saved: {path}")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    plan = load_model_role_plan(args.plan)
    selection = load_model_role_selection(args.selection) if args.selection else None
    status = inspect_model_role_conformance(
        plan,
        args.receipt,
        evidence_root=args.evidence_root,
        selection=selection,
    )
    print(status.model_dump_json(indent=2))
    return 0


__all__ = ["register_model_role_cli"]
