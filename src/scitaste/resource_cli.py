"""CLI wiring for shared compute resource inspection and observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.resources import (
    ComputeResourceRuntime,
    inspect_compute_resource_catalog,
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

    observe = resource_commands.add_parser(
        "observe",
        help="Register one typed resource observation without executing a workload",
    )
    observe.add_argument("--catalog", type=Path, required=True)
    observe.add_argument("--observation", type=Path, required=True)
    observe.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(observe)
    observe.set_defaults(handler=_handle_resource_observe)

    status = resource_commands.add_parser(
        "status",
        help="Report shared definitions and the latest registered observations",
    )
    status.add_argument("--catalog", type=Path, required=True)
    status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level_option(status)
    status.set_defaults(handler=_handle_resource_status)


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


def _handle_resource_status(args: argparse.Namespace) -> int:
    status = ComputeResourceRuntime(args.outputs_root).status(args.catalog)
    print(status.model_dump_json(indent=2))
    return 0
