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
from scitaste.evaluation.model_role_conformance_campaign import (
    inspect_bytebound_conformance_campaign,
    load_bytebound_campaign_plan,
    materialize_conformance_executor_bindings,
    prepare_bytebound_conformance_campaign,
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

    prepare_campaign = subcommands.add_parser(
        "prepare-campaign",
        help="Build a project-owned byte-bound B0 request pack without execution",
    )
    prepare_campaign.add_argument("--spec", type=Path, required=True)
    prepare_campaign.add_argument("--project-id", required=True)
    prepare_campaign.add_argument("--run-id", required=True)
    prepare_campaign.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    prepare_campaign.add_argument("--repository-root", type=Path, default=Path("."))
    _add_log_level_option(prepare_campaign)
    prepare_campaign.set_defaults(handler=_handle_prepare_campaign)

    campaign_status = subcommands.add_parser(
        "campaign-status",
        help="Compile existing actual receipts and report campaign readiness",
    )
    campaign_status.add_argument("--plan", type=Path, required=True)
    _add_log_level_option(campaign_status)
    campaign_status.set_defaults(handler=_handle_campaign_status)

    campaign_request = subcommands.add_parser(
        "campaign-request",
        help="Print one exact request and its existing-runner command template",
    )
    campaign_request.add_argument("--plan", type=Path, required=True)
    campaign_request.add_argument("--request-id", required=True)
    _add_log_level_option(campaign_request)
    campaign_request.set_defaults(handler=_handle_campaign_request)

    materialize_bindings = subcommands.add_parser(
        "materialize-bindings",
        help="Render content-bound configs for the existing model-node runtime",
    )
    materialize_bindings.add_argument("--plan", type=Path, required=True)
    materialize_bindings.add_argument("--repository-root", type=Path, default=Path("."))
    _add_log_level_option(materialize_bindings)
    materialize_bindings.set_defaults(handler=_handle_materialize_bindings)


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


def _handle_prepare_campaign(args: argparse.Namespace) -> int:
    plan, path = prepare_bytebound_conformance_campaign(
        args.spec,
        project_id=args.project_id,
        run_id=args.run_id,
        outputs_root=args.outputs_root,
        repository_root=args.repository_root,
    )
    print(plan.model_dump_json(indent=2))
    print(f"saved: {path}")
    return 0


def _handle_campaign_status(args: argparse.Namespace) -> int:
    status = inspect_bytebound_conformance_campaign(args.plan)
    print(status.model_dump_json(indent=2))
    return (
        0
        if status.readiness.value
        in {
            "request-prepared",
            "launch-ready",
            "complete",
        }
        else 1
    )


def _handle_campaign_request(args: argparse.Namespace) -> int:
    plan = load_bytebound_campaign_plan(args.plan)
    request = next(
        (item for item in plan.requests if item.request_id == args.request_id),
        None,
    )
    if request is None:
        raise ValueError(f"unknown campaign request {args.request_id!r}")
    print(request.model_dump_json(indent=2))
    print(f"request_sha256: {request.request_sha256}")
    return 0


def _handle_materialize_bindings(args: argparse.Namespace) -> int:
    _, path = materialize_conformance_executor_bindings(
        args.plan,
        repository_root=args.repository_root,
    )
    status = inspect_bytebound_conformance_campaign(path)
    print(status.model_dump_json(indent=2))
    return 0 if status.launch_ready_requests else 1


__all__ = ["register_model_role_cli"]
