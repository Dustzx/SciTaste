"""CLI wiring for the project-owned complete autonomous-research controller."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from scitaste.project.research_program import (
    ResearchProgramRuntime,
    ResearchProgramTransitionDisposition,
)

_DEFAULT_PROGRAM = Path(
    "configs/evaluation/programs/"
    "iclr2027_scitaste_capability_driven_autoresearch_program_v4.yaml"
)
_DEFAULT_MODEL_INVENTORY = Path("configs/resources/assets/model_role_inventory_v1.yaml")


def register_research_program_cli(
    project_commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    program = project_commands.add_parser(
        "program",
        help="Control a project-owned complete autonomous-research lifecycle",
    )
    commands = program.add_subparsers(dest="project_program_command", required=True)

    initialize = commands.add_parser(
        "initialize",
        help="Bind the capability-driven experiment program and task-excluded model inventory",
    )
    initialize.add_argument("--project-id", required=True)
    initialize.add_argument("--expected-revision", type=int, required=True)
    initialize.add_argument("--program", type=Path, default=_DEFAULT_PROGRAM)
    initialize.add_argument("--model-inventory", type=Path, default=_DEFAULT_MODEL_INVENTORY)
    initialize.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    _add_log_level(initialize)
    initialize.set_defaults(handler=_handle_initialize)

    status = commands.add_parser(
        "status",
        help="Verify the entire transition chain and report the next actionable phase",
    )
    _add_identity(status)
    _add_log_level(status)
    status.set_defaults(handler=_handle_status)

    advance = commands.add_parser(
        "advance",
        help="Bind completed artifacts, record a stop, or resume without launching work",
    )
    _add_identity(advance)
    advance.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="ARTIFACT_ID=PROJECT_RELATIVE_LOCATOR",
        help="repeat once for every exact artifact required by the current phase",
    )
    advance.add_argument(
        "--disposition",
        choices=[
            ResearchProgramTransitionDisposition.COMPLETED.value,
            ResearchProgramTransitionDisposition.BLOCKED.value,
            ResearchProgramTransitionDisposition.FAILED.value,
        ],
        default=ResearchProgramTransitionDisposition.COMPLETED.value,
    )
    advance.add_argument("--reason", default=None)
    advance.add_argument(
        "--review-outcome",
        choices=["agreement", "disagreement", "accepted", "revision_required"],
        default=None,
    )
    advance.add_argument(
        "--revision-target",
        choices=[
            "experiment-plan-frozen",
            "development-execution",
            "evidence-admission",
            "paper-assembly",
            "review-driven-revision",
        ],
        default=None,
        help="exact return phase when final AI review requires more work",
    )
    advance.add_argument(
        "--attest-artifacts-complete",
        action="store_true",
        help="attest that every supplied artifact was completed outside this controller",
    )
    advance.add_argument(
        "--resume",
        action="store_true",
        help="resume only a blocked or failed current phase; no artifacts are accepted",
    )
    advance.add_argument(
        "--recorded-at",
        default=None,
        help="timezone-aware ISO-8601 event time; defaults to the current UTC time",
    )
    _add_log_level(advance)
    advance.set_defaults(handler=_handle_advance)


def _add_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))


def _add_log_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )


def _handle_initialize(args: argparse.Namespace) -> int:
    status = ResearchProgramRuntime(args.outputs_root).initialize(
        project_id=args.project_id,
        program_path=args.program,
        model_inventory_path=args.model_inventory,
        expected_revision=args.expected_revision,
    )
    print(status.model_dump_json(indent=2))
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    status = ResearchProgramRuntime(args.outputs_root).status(
        project_id=args.project_id,
        program_id=args.program_id,
    )
    print(status.model_dump_json(indent=2))
    return 0


def _handle_advance(args: argparse.Namespace) -> int:
    runtime = ResearchProgramRuntime(args.outputs_root)
    recorded_at = _parse_time(args.recorded_at)
    if args.resume:
        if (
            args.artifact
            or args.reason is not None
            or args.review_outcome is not None
            or args.revision_target is not None
            or args.attest_artifacts_complete
            or args.disposition != ResearchProgramTransitionDisposition.COMPLETED.value
        ):
            raise ValueError("--resume cannot be combined with result or disposition options")
        status = runtime.resume(
            project_id=args.project_id,
            program_id=args.program_id,
            recorded_at=recorded_at,
        )
    else:
        status = runtime.advance(
            project_id=args.project_id,
            program_id=args.program_id,
            artifact_locators=_parse_artifacts(args.artifact),
            disposition=ResearchProgramTransitionDisposition(args.disposition),
            reason=args.reason,
            review_outcome=args.review_outcome,
            revision_target=args.revision_target,
            recorded_at=recorded_at,
            attest_artifacts_complete=args.attest_artifacts_complete,
        )
    print(status.model_dump_json(indent=2))
    return 0


def _parse_artifacts(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        artifact_id, separator, locator = value.partition("=")
        if not separator or not artifact_id or not locator:
            raise ValueError("--artifact must be ARTIFACT_ID=PROJECT_RELATIVE_LOCATOR")
        if artifact_id in parsed:
            raise ValueError(f"duplicate --artifact ID: {artifact_id}")
        parsed[artifact_id] = locator
    return parsed


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("--recorded-at must be timezone-aware")
    return parsed


__all__ = ["register_research_program_cli"]
