"""CLI wiring for resumable project lifecycle execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.lifecycle_workflow import LifecycleWorkflow, load_lifecycle_full_config
from scitaste.model_nodes.schemas import VenuePaperReviewProposal
from scitaste.review import VenueReviewResponse, VenueReviewVerification


def register_lifecycle_workflow_cli(
    lifecycle_commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    advance = lifecycle_commands.add_parser(
        "advance",
        help="Run native research and prepare review, stopping only at a real input boundary",
    )
    advance.add_argument("--project-id", required=True)
    advance.add_argument("--full-config", type=Path, required=True)
    advance.add_argument("--run-id", required=True)
    advance.add_argument("--review-id", required=True)
    advance.add_argument(
        "--review-scope",
        choices=["development", "independent_pre_submission"],
        default="development",
    )
    advance.add_argument(
        "--venue-taste-profile",
        type=Path,
        default=Path("configs/writing/venues/iclr-2027/taste.yaml"),
    )
    advance.add_argument("--seed", type=int, default=0)
    advance.add_argument("--allow-live-model-nodes", action="store_true")
    advance.add_argument(
        "--review-proposal",
        type=Path,
        help="optional structured reviewer proposal to admit after packet preparation",
    )
    advance.add_argument("--report-id", default="internal-model-review-001")
    advance.add_argument("--reviewer-id", default="internal-model-reviewer-001")
    advance.add_argument("--reviewer-provider", default="interactive-session")
    advance.add_argument("--reviewer-model", default="runtime-identity-unavailable")
    advance.add_argument(
        "--review-response",
        type=Path,
        help="optional response bound to the current/revised registered paper",
    )
    advance.add_argument(
        "--review-verification",
        type=Path,
        help="optional original-reviewer verification of the admitted response",
    )
    advance.add_argument(
        "--source-commit",
        help="exact Git commit for project-owned paper adoption and revision context",
    )
    advance.add_argument("--adoption-run-id")
    advance.add_argument("--revision-context-run-id")
    advance.add_argument("--target-manuscript-id")
    advance.add_argument(
        "--evaluation-evidence-run-id",
        action="append",
        default=[],
        help="admitted formal evidence handoff; repeat once per run",
    )
    advance.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    advance.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    advance.set_defaults(handler=_handle_advance)

    revise = lifecycle_commands.add_parser(
        "revise",
        help="Publish an exact concern-bearing review to Stage 19 revision handoff",
    )
    revise.add_argument("--project-id", required=True)
    revise.add_argument("--paper-directory", required=True)
    revise.add_argument("--review-id", required=True)
    revise.add_argument("--source-commit", required=True)
    revise.add_argument("--adoption-run-id")
    revise.add_argument("--revision-context-run-id")
    revise.add_argument("--target-manuscript-id")
    revise.add_argument("--evaluation-evidence-run-id", action="append", default=[])
    revise.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    revise.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    revise.set_defaults(handler=_handle_revise)


def _handle_advance(args: argparse.Namespace) -> int:
    config = load_lifecycle_full_config(args.full_config)
    if config.project_id != args.project_id:
        raise ValueError("--project-id differs from the full-workflow configuration")
    proposal = (
        VenuePaperReviewProposal.model_validate_json(
            args.review_proposal.read_text(encoding="utf-8"), strict=True
        )
        if args.review_proposal is not None
        else None
    )
    response = (
        VenueReviewResponse.model_validate_json(
            args.review_response.read_text(encoding="utf-8"), strict=True
        )
        if args.review_response is not None
        else None
    )
    verification = (
        VenueReviewVerification.model_validate_json(
            args.review_verification.read_text(encoding="utf-8"), strict=True
        )
        if args.review_verification is not None
        else None
    )
    report = LifecycleWorkflow(args.outputs_root, seed=args.seed).advance(
        full_config=config,
        run_id=args.run_id,
        review_id=args.review_id,
        review_scope=args.review_scope,
        venue_taste_profile=args.venue_taste_profile,
        allow_live_model_nodes=args.allow_live_model_nodes,
        review_proposal=proposal,
        report_id=args.report_id,
        reviewer_id=args.reviewer_id,
        reviewer_provider=args.reviewer_provider,
        reviewer_model=args.reviewer_model,
        review_response=response,
        review_verification=verification,
        source_commit=args.source_commit,
        adoption_run_id=args.adoption_run_id,
        revision_context_run_id=args.revision_context_run_id,
        target_manuscript_id=args.target_manuscript_id,
        evaluation_evidence_run_ids=tuple(sorted(args.evaluation_evidence_run_id)),
    )
    print(report.model_dump_json(indent=2))
    return 0


def _handle_revise(args: argparse.Namespace) -> int:
    workflow = LifecycleWorkflow(args.outputs_root)
    actions, handoff, blocker = workflow.prepare_revision_handoff(
        project_id=args.project_id,
        paper_directory=args.paper_directory,
        review_id=args.review_id,
        source_commit=args.source_commit,
        adoption_run_id=args.adoption_run_id,
        revision_context_run_id=args.revision_context_run_id,
        target_manuscript_id=args.target_manuscript_id,
        evaluation_evidence_run_ids=tuple(sorted(args.evaluation_evidence_run_id)),
    )
    payload = {
        "schema_version": "1.0",
        "status": "revision-handoff-published",
        "project_id": args.project_id,
        "actions": [item.model_dump(mode="json") for item in actions],
        "handoff": None if handoff is None else handoff.model_dump(mode="json"),
        "blocker": blocker.model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


__all__ = ["register_lifecycle_workflow_cli"]
