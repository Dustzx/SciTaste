"""CLI registration for no-run MLR-Bench and EXP-Bench lifecycle bridges."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scitaste.evaluation.lifecycle_benchmark_bridge import (
    BenchmarkBridgeKind,
    inspect_lifecycle_benchmark_bridge,
    load_lifecycle_benchmark_bridge_plan,
    materialize_lifecycle_task_package,
    plan_lifecycle_benchmark_bridge,
    save_lifecycle_benchmark_bridge_plan,
)


def register_lifecycle_benchmark_bridge_cli(
    evaluation_commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    bridge = evaluation_commands.add_parser(
        "lifecycle-benchmark",
        help="Plan or materialize no-run E3/E4 lifecycle task packages",
    )
    commands = bridge.add_subparsers(dest="lifecycle_benchmark_command", required=True)

    plan = commands.add_parser("plan", help="Inspect existing acquired bytes and save a plan")
    plan.add_argument(
        "--benchmark",
        choices=[item.value for item in BenchmarkBridgeKind],
        required=True,
    )
    plan.add_argument("--request", type=Path, required=True)
    plan.add_argument("--acquisition-root", type=Path, required=True)
    plan.add_argument("--program", type=Path, required=True)
    plan.add_argument("--workspace-root", type=Path, default=Path("."))
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--require-materializable", action="store_true")
    _add_log_level(plan)
    plan.set_defaults(handler=_handle_plan)

    materialize = commands.add_parser(
        "materialize",
        help="Project only verified local bytes into a new task package",
    )
    materialize.add_argument("--plan", type=Path, required=True)
    materialize.add_argument("--workspace-root", type=Path, default=Path("."))
    materialize.add_argument("--output", type=Path, required=True)
    _add_log_level(materialize)
    materialize.set_defaults(handler=_handle_materialize)

    status = commands.add_parser(
        "status",
        help="Recheck source bytes and optional materialized task package",
    )
    status.add_argument("--plan", type=Path, required=True)
    status.add_argument("--workspace-root", type=Path, default=Path("."))
    status.add_argument("--package-root", type=Path, default=None)
    status.add_argument("--require-acquisition-ready", action="store_true")
    status.add_argument("--require-admission-ready", action="store_true")
    _add_log_level(status)
    status.set_defaults(handler=_handle_status)


def _handle_plan(args: argparse.Namespace) -> int:
    plan = plan_lifecycle_benchmark_bridge(
        args.benchmark,
        request_path=args.request,
        acquisition_root=args.acquisition_root,
        program_path=args.program,
        workspace_root=args.workspace_root,
    )
    saved = save_lifecycle_benchmark_bridge_plan(plan, args.output)
    print(
        json.dumps(
            {
                "plan_path": str(saved),
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "benchmark_id": plan.benchmark_id.value,
                "task_count": len(plan.task_package.tasks) if plan.task_package else 0,
                "source_group_count": (
                    plan.task_package.source_group_count if plan.task_package else 0
                ),
                "scientific_use": (plan.task_package.scientific_use if plan.task_package else None),
                "ready_to_materialize": plan.ready_to_materialize,
                "ready_for_controller_acquisition_binding": (
                    plan.ready_for_controller_acquisition_binding
                ),
                "ready_for_controller_admission_binding": False,
                "blockers": [item.model_dump(mode="json") for item in plan.findings],
                "authorizes_download": False,
                "authorizes_api_calls": False,
                "authorizes_gpu_work": False,
                "authorizes_execution": False,
                "authorizes_scoring": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if args.require_materializable and not plan.ready_to_materialize:
        return 1
    return 0


def _handle_materialize(args: argparse.Namespace) -> int:
    plan = load_lifecycle_benchmark_bridge_plan(args.plan)
    receipt = materialize_lifecycle_task_package(
        plan,
        workspace_root=args.workspace_root,
        output_root=args.output,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                **receipt.model_dump(mode="json"),
                "authorizes_execution": False,
                "authorizes_scoring": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    plan = load_lifecycle_benchmark_bridge_plan(args.plan)
    status = inspect_lifecycle_benchmark_bridge(
        plan,
        workspace_root=args.workspace_root,
        package_root=args.package_root,
    )
    print(status.model_dump_json(indent=2))
    if args.require_acquisition_ready and not status.ready_for_controller_acquisition_binding:
        return 1
    if args.require_admission_ready and not status.ready_for_controller_admission_binding:
        return 1
    return 0


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scitaste.evaluation.lifecycle_benchmark_bridge_cli",
        description="No-run lifecycle benchmark bridge",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    register_lifecycle_benchmark_bridge_cli(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(["lifecycle-benchmark", *arguments])
    try:
        return int(args.handler(args))
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main", "register_lifecycle_benchmark_bridge_cli"]
