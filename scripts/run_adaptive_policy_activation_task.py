#!/usr/bin/env python3
"""Run exactly one issued adaptive-allocation activation task and advance state."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path, PurePosixPath

from prepare_newtonbench_development import prepare
from run_newtonbench_development import run

from scitaste.evaluation.adaptive_policy_activation import (
    complete_adaptive_policy_activation_task,
    inspect_adaptive_policy_activation,
    load_adaptive_policy_activation_approval,
    load_adaptive_policy_activation_episode_batch,
    load_adaptive_policy_activation_manifest,
    load_adaptive_policy_activation_no_run_plan,
    load_adaptive_policy_activation_state,
    load_adaptive_policy_activation_task_permit,
    save_adaptive_policy_activation_artifact,
    validate_adaptive_policy_activation_idea_binding,
    validate_adaptive_policy_activation_task_authority,
)
from scitaste.evaluation.interactive_research import load_interactive_research_run_receipt
from scitaste.project.runtime import ProjectRuntime


def execute(args: argparse.Namespace):
    if args.state_output.exists() or args.state_output.is_symlink():
        raise FileExistsError(args.state_output)

    workspace = args.workspace_root.resolve(strict=True)
    outputs_root = args.outputs_root.resolve()
    manifest, manifest_file_sha256 = load_adaptive_policy_activation_manifest(args.manifest)
    plan = load_adaptive_policy_activation_no_run_plan(args.plan)
    approval = load_adaptive_policy_activation_approval(args.approval)
    state = load_adaptive_policy_activation_state(args.state)
    permit = load_adaptive_policy_activation_task_permit(args.permit)
    inspection = inspect_adaptive_policy_activation(
        manifest,
        manifest_file_sha256=manifest_file_sha256,
        workspace_root=workspace,
    )
    if (
        not inspection.ready_for_owner_approval
        or inspection.manifest_file_sha256 != plan.manifest_file_sha256
        or inspection.manifest_fingerprint != plan.manifest_fingerprint
        or inspection.idea_revision_id != plan.idea_revision_id
        or inspection.idea_scientific_contract_sha256 != plan.idea_scientific_contract_sha256
    ):
        raise ValueError("activation task static or Idea binding changed after approval")
    validate_adaptive_policy_activation_task_authority(manifest, plan, approval, state, permit)
    validate_adaptive_policy_activation_idea_binding(plan, outputs_root=outputs_root)

    task = manifest.frozen_execution.tasks[permit.ordinal - 1]
    if (task.task_id, task.run_id, task.source_group_id) != (
        permit.task_id,
        permit.run_id,
        permit.source_group_id,
    ):
        raise ValueError("issued activation task differs from manifest ordinal")
    run_root = outputs_root / "projects" / manifest.project_id / "runs" / permit.run_id
    stage_root = run_root / "interactive_development"
    sampling_plan_path = stage_root / "SAMPLING_PLAN.json"
    protocol_path = stage_root / "PROTOCOL.json"
    receipt_path = stage_root / "RESULT" / "RECEIPT.json"
    batch_path = stage_root / "taste_episodes" / "BATCH.json"
    if run_root.is_symlink():
        raise ValueError(f"activation run directory cannot be a symlink: {run_root}")
    if receipt_path.is_file() and batch_path.is_file():
        receipt = load_interactive_research_run_receipt(receipt_path)
        batch = load_adaptive_policy_activation_episode_batch(batch_path)
        new_disk_bytes = _tree_bytes(run_root)
        advanced = complete_adaptive_policy_activation_task(
            manifest,
            plan,
            approval,
            state,
            permit,
            receipt,
            batch,
            new_disk_bytes=new_disk_bytes,
        )
        save_adaptive_policy_activation_artifact(advanced, args.state_output)
        return receipt, batch, advanced, new_disk_bytes
    if not args.allow_live:
        raise ValueError("activation task execution requires explicit --allow-live")
    prepared_only = run_root.is_dir() and _relative_files(run_root) == {
        "interactive_development/PROTOCOL.json",
        "interactive_development/SAMPLING_PLAN.json",
    }
    if run_root.exists() and not prepared_only:
        raise FileExistsError(
            f"activation run has ambiguous partial execution evidence; never rerun it: {run_root}"
        )

    limits = _bound_path(workspace, manifest.frozen_execution.limits.locator)
    task_path = _bound_path(workspace, task.locator)
    registry = _bound_path(workspace, manifest.frozen_execution.source_identity_registry.locator)
    backend = _bound_path(
        workspace, manifest.frozen_execution.agent_and_symbolic_judge.backend.locator
    )
    checkout = _bound_path(
        workspace,
        manifest.frozen_execution.checkout.locator,
        require_directory=True,
    )
    if not prepared_only:
        runtime = ProjectRuntime(outputs_root)
        expected_revision = runtime.open(manifest.project_id).revision
        prepare_args = argparse.Namespace(
            project_id=manifest.project_id,
            expected_revision=expected_revision,
            run_id=task.run_id,
            protocol_id=task.protocol_id,
            limits=str(limits),
            task=str(task_path),
            source_identity_registry=str(registry),
            agent_backend_config=str(backend),
            judge_backend_config=str(backend),
            checkout=str(checkout),
            repository_commit=manifest.frozen_execution.checkout.repository_commit,
            provider=manifest.frozen_execution.agent_and_symbolic_judge.provider_id,
            model=manifest.frozen_execution.agent_and_symbolic_judge.model_id,
            target_domain="interactive-scientific-law-discovery",
            target_venue="ICLR 2027",
            agent_policy_id="newtonbench-research-agent-v1",
            agent_prompt_version="newtonbench-agent-v1",
            agent_seed=task.agent_seed,
            judge_prompt_version="newtonbench-symbolic-equivalence-v1",
            judge_seed=task.judge_seed,
            taste_prompt_version="interactive-development-taste-v1",
            taste_seed=task.taste_seed,
            episode_sampling_rule=(
                "preassigned-action-stratum-v1"
                if manifest.schema_version == "1.1"
                else "earliest-executed-nonterminal-after-observation"
            ),
            episode_target_action=task.episode_target_action,
            episode_target_turn=task.episode_target_turn,
            candidate_credit_projection=(
                "allocation-local-v5"
                if manifest.schema_version == "1.1"
                else "action-local-scientific-v4"
            ),
            python_executable=sys.executable,
            bubblewrap_executable=shutil.which("bwrap") or "/usr/bin/bwrap",
            code_timeout_seconds=8,
            code_cpu_seconds=6,
            code_memory_mib=512,
            code_max_output_bytes=128_000,
            outputs_root=outputs_root,
        )
        _protocol, sampling_plan_path, protocol_path = prepare(prepare_args)
    run_args = argparse.Namespace(
        protocol=str(protocol_path),
        sampling_plan=str(sampling_plan_path),
        limits=str(limits),
        task=str(task_path),
        agent_backend_config=str(backend),
        judge_backend_config=str(backend),
        checkout=str(checkout),
        repository_commit=manifest.frozen_execution.checkout.repository_commit,
        agent_policy_id="newtonbench-research-agent-v1",
        agent_prompt_version="newtonbench-agent-v1",
        agent_seed=task.agent_seed,
        judge_prompt_version="newtonbench-symbolic-equivalence-v1",
        judge_seed=task.judge_seed,
        python_executable=sys.executable,
        bubblewrap_executable=shutil.which("bwrap") or "/usr/bin/bwrap",
        code_timeout_seconds=8,
        code_cpu_seconds=6,
        code_memory_mib=512,
        code_max_output_bytes=128_000,
        outputs_root=outputs_root,
    )
    receipt, batch = run(run_args)
    new_disk_bytes = _tree_bytes(run_root)
    advanced = complete_adaptive_policy_activation_task(
        manifest,
        plan,
        approval,
        state,
        permit,
        receipt,
        batch,
        new_disk_bytes=new_disk_bytes,
    )
    save_adaptive_policy_activation_artifact(advanced, args.state_output)
    return receipt, batch, advanced, new_disk_bytes


def _bound_path(root: Path, locator: str, *, require_directory: bool = False) -> Path:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        raise ValueError(f"activation input cannot be a symlink: {locator}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"activation input escapes workspace: {locator}")
    if require_directory and not resolved.is_dir():
        raise ValueError(f"activation input is not a directory: {locator}")
    if not require_directory and not resolved.is_file():
        raise ValueError(f"activation input is not a file: {locator}")
    return resolved


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"activation run evidence cannot contain a symlink: {path}")
        if path.is_file():
            total += path.stat().st_size
    return total


def _relative_files(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"activation run evidence cannot contain a symlink: {path}")
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--allow-live", action="store_true")
    return parser


def main() -> None:
    receipt, batch, state, new_disk_bytes = execute(build_parser().parse_args())
    print(
        json.dumps(
            {
                "run_id": receipt.run_id,
                "task_id": receipt.task_id,
                "terminal_status": receipt.status,
                "receipt_sha256": receipt.receipt_sha256,
                "batch_sha256": batch.batch_sha256,
                "candidate_count": len(batch.items),
                "state_sha256": state.state_sha256,
                "next_task_id": state.next_task_id,
                "new_disk_bytes": new_disk_bytes,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
