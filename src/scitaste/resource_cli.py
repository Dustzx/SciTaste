"""CLI wiring for shared compute resource inspection and observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.resources import (
    ComputeResourceRuntime,
    inspect_compute_resource_catalog,
    inspect_project_resource_binding,
    inspect_resource_access,
)


def register_resource_cli(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    resources = commands.add_parser(
        "resource",
        help="Inspect and maintain shared API/GPU resources above project directories",
    )
    resource_commands = resources.add_subparsers(dest="resource_command", required=True)

    inspect = resource_commands.add_parser(
        "inspect",
        help="Validate a secret-free compute catalog and its local evidence",
    )
    _add_catalog_options(inspect)
    inspect.set_defaults(handler=_handle_resource_inspect)

    initialize = resource_commands.add_parser(
        "init",
        help="Create the outputs/resources registry without probing or running work",
    )
    _add_catalog_options(initialize)
    initialize.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    initialize.set_defaults(handler=_handle_resource_init)

    update_catalog = resource_commands.add_parser(
        "update-catalog",
        help="Advance the registry to a new content-bound catalog without deleting history",
    )
    _add_catalog_options(update_catalog)
    update_catalog.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    update_catalog.set_defaults(handler=_handle_resource_update_catalog)

    observe = resource_commands.add_parser(
        "observe",
        help="Register one typed resource observation without executing a workload",
    )
    observe.add_argument("--catalog", type=Path, required=True)
    observe.add_argument("--observation", type=Path, required=True)
    observe.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(observe)
    observe.set_defaults(handler=_handle_resource_observe)

    inspect_binding = resource_commands.add_parser(
        "inspect-project-binding",
        help="Validate one project's explicit API/GPU/checkpoint resource binding",
    )
    inspect_binding.add_argument("--catalog", type=Path, required=True)
    inspect_binding.add_argument("--binding", type=Path, required=True)
    _add_log_level_option(inspect_binding)
    inspect_binding.set_defaults(handler=_handle_resource_inspect_project_binding)

    bind_project = resource_commands.add_parser(
        "bind-project",
        help="Register one exact project resource binding in outputs/resources",
    )
    bind_project.add_argument("--catalog", type=Path, required=True)
    bind_project.add_argument("--binding", type=Path, required=True)
    bind_project.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(bind_project)
    bind_project.set_defaults(handler=_handle_resource_bind_project)

    update_project = resource_commands.add_parser(
        "update-project-binding",
        help="Advance one project resource binding and archive its predecessor",
    )
    update_project.add_argument("--catalog", type=Path, required=True)
    update_project.add_argument("--binding", type=Path, required=True)
    update_project.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(update_project)
    update_project.set_defaults(handler=_handle_resource_update_project_binding)

    status = resource_commands.add_parser(
        "status",
        help="Report shared definitions and the latest registered observations",
    )
    status.add_argument("--catalog", type=Path, required=True)
    status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(status)
    status.set_defaults(handler=_handle_resource_status)

    access_status = resource_commands.add_parser(
        "access-status",
        help="Report local credential bindings without exposing values or contacting resources",
    )
    access_status.add_argument("--catalog", type=Path, required=True)
    access_status.add_argument("--credential-file", type=Path, default=None)
    access_status.add_argument("--output", type=Path, default=None)
    access_status.add_argument(
        "--require-all-bindings",
        action="store_true",
        help="return nonzero when any catalog credential binding is absent",
    )
    _add_log_level_option(access_status)
    access_status.set_defaults(handler=_handle_resource_access_status)


def _add_catalog_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    _add_log_level_option(parser)


def _add_log_level_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _handle_resource_inspect(args: argparse.Namespace) -> int:
    inspection = inspect_compute_resource_catalog(
        args.catalog,
        evidence_root=args.evidence_root,
    )
    print(inspection.model_dump_json(indent=2))
    return 0 if inspection.evidence_verified else 1


def _handle_resource_init(args: argparse.Namespace) -> int:
    runtime = ComputeResourceRuntime(args.outputs_root)
    snapshot = runtime.initialize(args.catalog, evidence_root=args.evidence_root)
    print(
        json.dumps(
            {
                "status": "initialized-shared-resource-registry",
                "registry_root": str(runtime.root),
                "registry": snapshot.model_dump(mode="json"),
                "secret_values_loaded": False,
                "remote_probe_performed": False,
                "workload_executed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_resource_observe(args: argparse.Namespace) -> int:
    runtime = ComputeResourceRuntime(args.outputs_root)
    record = runtime.register_observation(args.catalog, args.observation)
    print(
        json.dumps(
            {
                "status": "registered-resource-observation",
                "record": record.model_dump(mode="json"),
                "secret_values_loaded": False,
                "remote_probe_performed": False,
                "workload_executed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_resource_update_catalog(args: argparse.Namespace) -> int:
    runtime = ComputeResourceRuntime(args.outputs_root)
    snapshot = runtime.update_catalog(args.catalog, evidence_root=args.evidence_root)
    print(
        json.dumps(
            {
                "status": "updated-shared-resource-catalog",
                "registry_root": str(runtime.root),
                "registry": snapshot.model_dump(mode="json"),
                "observations_preserved": True,
                "secret_values_loaded": False,
                "remote_probe_performed": False,
                "workload_executed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_resource_inspect_project_binding(args: argparse.Namespace) -> int:
    inspection = inspect_project_resource_binding(args.catalog, args.binding)
    print(inspection.model_dump_json(indent=2))
    return 0 if inspection.valid else 1


def _handle_resource_bind_project(args: argparse.Namespace) -> int:
    runtime = ComputeResourceRuntime(args.outputs_root)
    record = runtime.register_project_binding(args.catalog, args.binding)
    print(
        json.dumps(
            {
                "status": "registered-project-resource-binding",
                "record": record.model_dump(mode="json"),
                "secret_values_loaded": False,
                "remote_probe_performed": False,
                "workload_executed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_resource_update_project_binding(args: argparse.Namespace) -> int:
    runtime = ComputeResourceRuntime(args.outputs_root)
    record = runtime.update_project_binding(args.catalog, args.binding)
    print(
        json.dumps(
            {
                "status": "updated-project-resource-binding",
                "record": record.model_dump(mode="json"),
                "predecessor_archived": True,
                "secret_values_loaded": False,
                "remote_probe_performed": False,
                "workload_executed": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_resource_status(args: argparse.Namespace) -> int:
    status = ComputeResourceRuntime(args.outputs_root).status(args.catalog)
    print(status.model_dump_json(indent=2))
    return 0


def _handle_resource_access_status(args: argparse.Namespace) -> int:
    status = inspect_resource_access(
        args.catalog,
        credential_file=args.credential_file,
    )
    serialized = status.model_dump_json(indent=2) + "\n"
    if args.output is not None:
        target = args.output.expanduser()
        if target.is_symlink():
            raise ValueError("resource access status output must not be a symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return int(args.require_all_bindings and bool(status.missing_credential_resource_ids))
