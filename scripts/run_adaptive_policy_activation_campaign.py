#!/usr/bin/env python3
"""Run or resume the exact approved adaptive-policy activation campaign.

This operator composes the existing one-use task, local-review, and deterministic
finalization runners.  Every state is append-only.  It never retries or replaces
a consumed task/review, and it cannot start without both the exact approval
artifact and explicit API/local-execution flags.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finalize_adaptive_policy_activation import execute as finalize_activation
from run_adaptive_policy_activation_review import execute as execute_review
from run_adaptive_policy_activation_task import execute as execute_task

from scitaste.evaluation.adaptive_policy_activation import (
    close_adaptive_policy_activation_empty_review,
    complete_adaptive_policy_activation_finalization,
    complete_adaptive_policy_activation_review,
    issue_adaptive_policy_activation_review,
    issue_adaptive_policy_activation_task,
    load_adaptive_policy_activation_approval,
    load_adaptive_policy_activation_episode_batch,
    load_adaptive_policy_activation_finalization_result,
    load_adaptive_policy_activation_manifest,
    load_adaptive_policy_activation_no_run_plan,
    load_adaptive_policy_activation_review_result,
    load_adaptive_policy_activation_state,
    save_adaptive_policy_activation_artifact,
)
from scitaste.evaluation.adaptive_policy_campaign import (
    AdaptivePolicyActivationAction,
    AdaptivePolicyActivationJournal,
    next_adaptive_policy_activation_action,
)
from scitaste.evaluation.adaptive_policy_e2_handoff import (
    load_adaptive_policy_e2_handoff_receipt,
    materialize_adaptive_policy_e2_successor,
)


def execute(args: argparse.Namespace) -> dict[str, object]:
    if not args.allow_live or not args.allow_local:
        raise ValueError(
            "campaign execution requires both --allow-live and --allow-local; "
            "approval alone never launches API or GPU work"
        )
    if args.max_actions is not None and args.max_actions < 1:
        raise ValueError("--max-actions must be positive")

    workspace = args.workspace_root.resolve(strict=True)
    outputs_root = args.outputs_root.resolve(strict=True)
    manifest, _ = load_adaptive_policy_activation_manifest(args.manifest)
    plan = load_adaptive_policy_activation_no_run_plan(args.plan)
    approval = load_adaptive_policy_activation_approval(args.approval)
    initial = load_adaptive_policy_activation_state(args.state)
    activation_root = (
        outputs_root
        / "projects"
        / manifest.project_id
        / "evaluations"
        / "taste-policy-activation"
        / manifest.campaign_id
    )
    journal_root = (
        activation_root / "execution-journal"
        if args.journal_root is None
        else args.journal_root.resolve()
    )
    _require_under(journal_root, activation_root.resolve())
    journal = AdaptivePolicyActivationJournal(journal_root)
    state = journal.bootstrap(initial)

    actions = 0
    while True:
        action = next_adaptive_policy_activation_action(state)
        if action is AdaptivePolicyActivationAction.COMPLETE:
            break
        if args.max_actions is not None and actions >= args.max_actions:
            break

        if action is AdaptivePolicyActivationAction.ISSUE_TASK:
            permit, advanced = issue_adaptive_policy_activation_task(
                manifest, plan, approval, state
            )
            journal.save_task_permit(permit)
            journal.append_state(advanced)
            state = advanced
        elif action is AdaptivePolicyActivationAction.EXECUTE_TASK:
            permit_path, permit = journal.active_task_permit(state)
            state_output = journal.state_output_path(state.sequence + 1, "task-complete")
            execute_task(
                argparse.Namespace(
                    manifest=args.manifest,
                    plan=args.plan,
                    approval=args.approval,
                    state=journal.state_path(state),
                    permit=permit_path,
                    state_output=state_output,
                    workspace_root=workspace,
                    outputs_root=outputs_root,
                    allow_live=True,
                )
            )
            state = journal.adopt_runner_state(state_output)
            if state.terminal_evidence[-1].permit_sha256 != permit.permit_sha256:
                raise ValueError("task runner advanced a different activation permit")
        elif action is AdaptivePolicyActivationAction.ISSUE_REVIEW:
            task = _next_review_task(state)
            batch_path = (
                outputs_root
                / "projects"
                / manifest.project_id
                / "runs"
                / task.run_id
                / "interactive_development"
                / "taste_episodes"
                / "BATCH.json"
            )
            batch = load_adaptive_policy_activation_episode_batch(batch_path)
            permit, advanced = issue_adaptive_policy_activation_review(
                manifest,
                plan,
                approval,
                state,
                batch,
                workspace_root=workspace,
            )
            journal.save_review_permit(permit)
            journal.append_state(advanced)
            state = advanced
        elif action is AdaptivePolicyActivationAction.EXECUTE_REVIEW:
            permit_path, permit = journal.active_review_permit(state)
            result_output = journal.result_path(
                f"review-{permit.ordinal:02d}-{permit.task_id}.json"
            )
            state_output = journal.state_output_path(state.sequence + 1, "review-complete")
            if result_output.is_file() and not result_output.is_symlink():
                result = load_adaptive_policy_activation_review_result(result_output)
                advanced = complete_adaptive_policy_activation_review(
                    manifest,
                    plan,
                    approval,
                    state,
                    permit,
                    result,
                    workspace_root=workspace,
                )
                save_adaptive_policy_activation_artifact(advanced, state_output)
            else:
                execute_review(
                    argparse.Namespace(
                        manifest=args.manifest,
                        plan=args.plan,
                        approval=args.approval,
                        state=journal.state_path(state),
                        permit=permit_path,
                        result_output=result_output,
                        state_output=state_output,
                        workspace_root=workspace,
                        outputs_root=outputs_root,
                        allow_local=True,
                    )
                )
            state = journal.adopt_runner_state(state_output)
        elif action is AdaptivePolicyActivationAction.CLOSE_EMPTY_REVIEW:
            advanced = close_adaptive_policy_activation_empty_review(
                manifest, plan, approval, state
            )
            journal.append_state(advanced)
            state = advanced
        elif action is AdaptivePolicyActivationAction.FINALIZE:
            result_output = journal.result_path("FINALIZATION.json")
            state_output = journal.state_output_path(state.sequence + 1, "finalized")
            if result_output.is_file() and not result_output.is_symlink():
                result = load_adaptive_policy_activation_finalization_result(result_output)
                advanced = complete_adaptive_policy_activation_finalization(
                    manifest,
                    plan,
                    approval,
                    state,
                    result,
                    workspace_root=workspace,
                )
                save_adaptive_policy_activation_artifact(advanced, state_output)
            else:
                finalize_activation(
                    argparse.Namespace(
                        manifest=args.manifest,
                        plan=args.plan,
                        approval=args.approval,
                        state=journal.state_path(state),
                        result_output=result_output,
                        state_output=state_output,
                        workspace_root=workspace,
                        outputs_root=outputs_root,
                    )
                )
            state = journal.adopt_runner_state(state_output)
        else:  # pragma: no cover - enum exhaustiveness guard
            raise AssertionError(action)
        actions += 1

    next_action = next_adaptive_policy_activation_action(state)
    handoff = _materialize_e2_handoff_if_ready(
        args,
        manifest=manifest,
        state=state,
        workspace=workspace,
        outputs_root=outputs_root,
        activation_root=activation_root,
    )
    return {
        "campaign_id": state.campaign_id,
        "status": state.status,
        "sequence": state.sequence,
        "state_sha256": state.state_sha256,
        "actions_completed_this_invocation": actions,
        "next_action": next_action.value,
        "completed_trajectory_count": state.completed_trajectory_count,
        "reviewed_candidate_count": len(state.review_evidence),
        "admitted_episode_count": state.admitted_episode_count,
        "consumed_api_calls": state.consumed_api_calls,
        "consumed_api_tokens": state.consumed_api_tokens,
        "consumed_local_review_generations": state.consumed_local_review_generations,
        "consumed_local_review_gpu_hours": state.consumed_local_review_gpu_hours,
        "journal_root": journal_root.relative_to(workspace).as_posix(),
        "e2_handoff": handoff,
        "formal_effect_claim_established": False,
    }


def _next_review_task(state):
    task_id = state.next_review_task_id
    if task_id is None:
        task = next((item for item in state.tasks if item.status == "review-pending"), None)
    else:
        task = next((item for item in state.tasks if item.task_id == task_id), None)
    if task is None or task.status != "review-pending":
        raise ValueError("activation journal cannot identify the next review candidate")
    return task


def _materialize_e2_handoff_if_ready(
    args: argparse.Namespace,
    *,
    manifest,
    state,
    workspace: Path,
    outputs_root: Path,
    activation_root: Path,
) -> dict[str, object]:
    if state.status != "finalized" or state.finalization is None:
        return {"status": "awaiting-activation-finalization"}
    if not state.finalization.activation_ready_for_e2_development:
        return {
            "status": "not-ready",
            "policy_refresh_status": state.finalization.policy_refresh_status,
            "target_domain_state_probe_status": (
                state.finalization.target_domain_state_probe_status
            ),
        }
    output_directory = (
        activation_root / "e2-successor"
        if args.e2_output_directory is None
        else args.e2_output_directory.resolve()
    )
    _require_under(output_directory, activation_root.resolve())
    receipt_path = output_directory / "HANDOFF.json"
    if output_directory.exists():
        receipt = load_adaptive_policy_e2_handoff_receipt(receipt_path)
        if (
            receipt.activation_state_sha256 != state.state_sha256
            or receipt.activation_result_sha256 != state.finalization.result_sha256
        ):
            raise ValueError("existing E2 handoff belongs to another activation result")
    else:
        predecessor = workspace.joinpath(
            *Path(manifest.activation_gate.target_e2_manifest.locator).parts
        )
        _, _, receipt, _ = materialize_adaptive_policy_e2_successor(
            manifest,
            state.finalization,
            state,
            predecessor_manifest_path=predecessor,
            output_directory=output_directory,
            workspace_root=workspace,
            outputs_root=outputs_root,
            implementation_commit=args.implementation_commit,
            successor_manifest_id=args.successor_manifest_id,
        )
    return {
        "status": "static-handoff-ready",
        "manifest_id": receipt.successor_manifest_id,
        "manifest_sha256": receipt.successor_manifest_sha256,
        "receipt_sha256": receipt.receipt_sha256,
        "owner_execution_approval_still_required": True,
    }


def _require_under(candidate: Path, parent: Path) -> None:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(parent):
        raise ValueError("activation journal must remain under the campaign evidence root")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--journal-root", type=Path, default=None)
    parser.add_argument("--e2-output-directory", type=Path, default=None)
    parser.add_argument("--successor-manifest-id", default=None)
    parser.add_argument("--implementation-commit", default=None)
    parser.add_argument("--max-actions", type=int, default=None)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-local", action="store_true")
    return parser


def main() -> None:
    print(json.dumps(execute(build_parser().parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
