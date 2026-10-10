"""Small CLI seam for generic project submission plans."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from scitaste.project.runtime import ProjectRuntime
from scitaste.project.submission_plan import (
    SubmissionPlanDraft,
    save_submission_plan,
    submission_plan_status,
)


def register_submission_plan_cli(commands: argparse._SubParsersAction) -> None:
    parser = commands.add_parser(
        "submission-plan", help="Project delivery milestones, not experiment execution"
    )
    operations = parser.add_subparsers(dest="submission_plan_command", required=True)
    status = operations.add_parser("status", help="Read internal and official deadlines separately")
    status.add_argument("--project-id", required=True)
    status.add_argument("--observed-at", help="Timezone-aware ISO-8601 timestamp")
    status.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    status.set_defaults(handler=_status)
    assign = operations.add_parser("set", help="CAS a complete plan revision; never launch work")
    assign.add_argument("--plan", type=Path, required=True)
    assign.add_argument("--expected-revision", type=int, required=True)
    assign.add_argument("--author", required=True)
    assign.add_argument("--reason", required=True)
    assign.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    assign.set_defaults(handler=_set)


def _status(args: argparse.Namespace) -> int:
    value = submission_plan_status(
        ProjectRuntime(args.outputs_root),
        args.project_id,
        observed_at=datetime.fromisoformat(args.observed_at) if args.observed_at else None,
    )
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def _set(args: argparse.Namespace) -> int:
    if args.plan.stat().st_size > 64_000:
        raise ValueError("submission plan input exceeds 64 kB")
    draft = SubmissionPlanDraft.model_validate_json(args.plan.read_text())
    runtime = ProjectRuntime(args.outputs_root)
    save_submission_plan(
        runtime,
        draft,
        expected_revision=args.expected_revision,
        author=args.author,
        reason=args.reason,
    )
    print(
        json.dumps(submission_plan_status(runtime, draft.project_id), ensure_ascii=False, indent=2)
    )
    return 0
