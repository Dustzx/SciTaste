"""SciTaste command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from scitaste.backends.openai_compatible import (
    OpenAICompatibleBackend,
    load_openai_compatible_config,
)
from scitaste.backends.replay import RecordingBackend, ReplayBackend
from scitaste.backends.scripted import ScriptedPreferenceBackend
from scitaste.data.store import build_libraries
from scitaste.demo import run_nonlinear_demo
from scitaste.executor.autoresearchclaw import AutoResearchClawExecutor
from scitaste.taste.intrinsic import (
    IntrinsicTasteCalibrator,
    load_calibration_suite,
    save_calibration_report,
)


def _add_common_options(
    parser: argparse.ArgumentParser,
    *,
    default_output: str,
    default_backend: str = "mock",
) -> None:
    parser.add_argument("--seed", type=int, default=0, help="Deterministic selection seed")
    parser.add_argument("--output", type=Path, default=Path(default_output))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--backend", default=default_backend)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scitaste", description="Scientific taste controller")
    parser.add_argument("--version", action="version", version="SciTaste 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    baseline = commands.add_parser("baseline", help="Execution-substrate baseline commands")
    baseline_commands = baseline.add_subparsers(dest="baseline_command", required=True)
    baseline_run = baseline_commands.add_parser("run", help="Run the original substrate")
    baseline_run.add_argument("--topic", required=True)
    baseline_run.add_argument("--to-stage", default=None)
    _add_common_options(baseline_run, default_output="outputs/baseline")
    baseline_run.set_defaults(handler=_handle_baseline_run)

    run = commands.add_parser("run", help="End-to-end workflows")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    demo = run_commands.add_parser("demo", help="Run the Phase 1 nonlinear mock loop")
    _add_common_options(demo, default_output="outputs/demo")
    demo.set_defaults(handler=_handle_demo)
    full = run_commands.add_parser("full", help="Run the complete future SciTaste workflow")
    _add_common_options(full, default_output="outputs/full")
    full.set_defaults(handler=_handle_planned, milestone="Phase 4-7")

    taste = commands.add_parser("taste", help="Scientific-taste calibration")
    taste_commands = taste.add_subparsers(dest="taste_command", required=True)
    calibrate = taste_commands.add_parser("calibrate", help="Run a fixed-candidate suite")
    _add_common_options(
        calibrate,
        default_output="outputs/calibration",
        default_backend="scripted",
    )
    calibrate.add_argument("--replay", type=Path, default=None)
    calibrate.add_argument("--record", type=Path, default=None)
    calibrate.add_argument(
        "--suite",
        type=Path,
        default=Path("configs/taste/intrinsic_calibration_v1.yaml"),
    )
    calibrate.set_defaults(handler=_handle_taste_calibrate)

    library = commands.add_parser("library", help="Knowledge and taste libraries")
    library_commands = library.add_subparsers(dest="library_command", required=True)
    library_build = library_commands.add_parser("build", help="Build separate local stores")
    _add_common_options(library_build, default_output="outputs/library")
    library_build.set_defaults(handler=_handle_library_build)
    _add_single_planned(commands, "discover", "Phase 4")
    _add_single_planned(commands, "hypothesize", "Phase 4")
    _add_single_planned(commands, "probe", "Phase 4")
    _add_single_planned(commands, "reformulate", "Phase 4")
    _add_single_planned(commands, "ideate", "Phase 4")
    _add_nested_planned(commands, "portfolio", "select", "Phase 4")
    _add_nested_planned(commands, "evidence", "plan", "Phase 5")
    _add_single_planned(commands, "write", "Phase 6")
    _add_single_planned(commands, "review", "Phase 6")
    _add_nested_planned(commands, "figure", "build", "Phase 7")
    _add_nested_planned(commands, "benchmark", "run", "Phase 8")
    return parser


def _add_single_planned(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    milestone: str,
) -> None:
    command = commands.add_parser(name)
    _add_common_options(command, default_output=f"outputs/{name}")
    command.set_defaults(handler=_handle_planned, milestone=milestone)


def _add_nested_planned(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    operation: str,
    milestone: str,
) -> None:
    command = commands.add_parser(name)
    operations = command.add_subparsers(dest=f"{name}_command", required=True)
    leaf = operations.add_parser(operation)
    _add_common_options(leaf, default_output=f"outputs/{name}-{operation}")
    leaf.set_defaults(handler=_handle_planned, milestone=milestone)


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a mapping")
    return data


def _handle_demo(args: argparse.Namespace) -> int:
    if args.backend != "mock":
        raise ValueError("Phase 1 demo supports only --backend mock")
    if args.dry_run:
        print(json.dumps({"status": "planned", "workflow": "nonlinear-demo"}, indent=2))
        return 0
    summary = run_nonlinear_demo(
        output_dir=args.output,
        seed=args.seed,
        config=_load_config(args.config),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _handle_baseline_run(args: argparse.Namespace) -> int:
    executor = AutoResearchClawExecutor(config_path=args.config, dry_run=args.dry_run)
    result = executor.baseline_run(
        topic=args.topic,
        output_dir=args.output,
        to_stage=args.to_stage,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status.value in {"PLANNED", "SUCCEEDED"} else 1


def _handle_taste_calibrate(args: argparse.Namespace) -> int:
    suite = load_calibration_suite(args.suite)
    if args.dry_run:
        print(
            json.dumps(
                {"status": "planned", "suite_id": suite.suite_id, "cases": len(suite.cases)},
                indent=2,
            )
        )
        return 0
    if args.backend == "scripted":
        missing = [case.case_id for case in suite.cases if case.scripted_selection_id is None]
        if missing:
            raise ValueError(f"scripted selections missing for: {', '.join(missing)}")
        backend = ScriptedPreferenceBackend(
            {case.case_id: case.scripted_selection_id for case in suite.cases}
        )
    elif args.backend == "replay":
        if args.replay is None:
            raise ValueError("--backend replay requires --replay PATH")
        backend = ReplayBackend(args.replay)
    elif args.backend == "openai-compatible":
        if args.config is None:
            raise ValueError("--backend openai-compatible requires --config PATH")
        backend = OpenAICompatibleBackend(load_openai_compatible_config(args.config))
    else:
        raise ValueError("supported calibration backends: scripted, replay, openai-compatible")
    if args.record:
        backend = RecordingBackend(backend, args.record)
    report = IntrinsicTasteCalibrator(backend, seed=args.seed).evaluate(suite)
    report_path = args.output / "calibration_report.json"
    save_calibration_report(report, report_path)
    print(
        json.dumps(
            {
                "suite_id": report.suite_id,
                "backend": report.backend,
                "model": report.model,
                "accuracy": report.overall.accuracy,
                "report": str(report_path),
            },
            indent=2,
        )
    )
    return 0


def _handle_library_build(args: argparse.Namespace) -> int:
    config_path = args.config or Path("configs/taste/library_seed_v1.yaml")
    if args.dry_run:
        config = _load_config(config_path)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "knowledge_count": len(config.get("knowledge_documents", [])),
                    "taste_count": len(config.get("taste_cases", [])),
                },
                indent=2,
            )
        )
        return 0
    manifest = build_libraries(config_path, args.output)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def _handle_planned(args: argparse.Namespace) -> int:
    payload = {
        "status": "planned",
        "milestone": args.milestone,
        "message": "Command contract is reserved; implementation has not passed its roadmap gate.",
    }
    print(json.dumps(payload, indent=2))
    return 0 if args.dry_run else 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))
    try:
        return int(args.handler(args))
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
