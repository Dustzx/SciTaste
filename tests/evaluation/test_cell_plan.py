from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.evaluation import (
    AnalysisContract,
    IntegrityContract,
    ReadinessStatus,
    SystemRole,
    compile_evaluation_cell_plan,
    load_prelaunch_manifest,
    save_evaluation_cell_plan,
)

MANIFEST_PATH = Path("configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml")
CURRENT_MANIFEST_PATH = Path("configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v6.yaml")
HASH = "a" * 64


def _ready_manifest():
    manifest = load_prelaunch_manifest(MANIFEST_PATH).manifest
    systems = tuple(
        system.model_copy(
            update={
                "availability": ReadinessStatus.VERIFIED,
                "real_implementation": True,
                "implementation_ref": system.implementation_ref
                or f"direct-agent@{manifest.source_commit}",
                **(
                    {
                        "adapter_preflight_ref": f"adapters/{system.system_id}.json",
                        "adapter_preflight_sha256": HASH,
                    }
                    if system.role in {SystemRole.CONTROL, SystemRole.METHOD_COMPARATOR}
                    else {}
                ),
            }
        )
        for system in manifest.systems
    )
    tasks = tuple(
        task.model_copy(
            update={
                "license_status": ReadinessStatus.VERIFIED,
                "asset_status": ReadinessStatus.VERIFIED,
                "held_out": True,
                "source_group_disjoint": True,
            }
        )
        for task in manifest.tasks
    )
    human_review = manifest.human_review.model_copy(
        update={
            "recruitment_status": ReadinessStatus.VERIFIED,
            "rubric_status": ReadinessStatus.VERIFIED,
            "adjudication_status": ReadinessStatus.VERIFIED,
        }
    )
    return manifest.model_copy(
        update={
            "systems": systems,
            "tasks": tasks,
            "human_review": human_review,
            "analysis": AnalysisContract(
                primary_outcome="Blinded research-package score.",
                estimand="Mean paired system difference over held-out tasks.",
                analysis_unit="System-task-seed trajectory.",
                aggregation_method="Task-stratified paired mean.",
                uncertainty_method="Task and seed cluster bootstrap.",
            ),
            "integrity": IntegrityContract(
                preregistration_ref="protocol/preregistration.md",
                preregistration_sha256=HASH,
                task_freeze_ref="protocol/task-freeze.json",
                task_freeze_sha256=HASH,
                failure_policy_ref="protocol/failure-policy.md",
                failure_policy_sha256=HASH,
                repair_policy_ref="protocol/repair-policy.md",
                repair_policy_sha256=HASH,
                leakage_audit_ref="protocol/leakage-audit.json",
                leakage_audit_sha256=HASH,
                judge_protocol_ref="protocol/judge-protocol.md",
                judge_protocol_sha256=HASH,
            ),
        }
    )


def test_current_v41_proposal_compiles_exact_blocked_matrix_without_running() -> None:
    manifest = load_prelaunch_manifest(MANIFEST_PATH).manifest

    plan = compile_evaluation_cell_plan(manifest)

    assert len(plan.lanes) == 1
    assert len(plan.cells) == 50
    assert plan.lanes[0].ready_cells == 0
    assert plan.lanes[0].blocked_cells == 50
    assert plan.ready_for_launch_preparation is False
    assert plan.proposal_author_approved is False
    assert plan.authorizes_execution is False
    assert plan.no_provider_call_performed is True
    assert plan.no_gpu_work_performed is True
    assert plan.no_task_download_performed is True
    assert "system:direct-agent:pending" in plan.plan_blockers
    assert "system:direct-agent:adapter-preflight-unbound" in plan.plan_blockers
    assert "protocol:analysis-contract-missing" in plan.plan_blockers
    assert "protocol:integrity-contract-missing" in plan.plan_blockers
    assert all(cell.system_id not in cell.review_blind_id for cell in plan.cells)
    assert len({cell.cell_id for cell in plan.cells}) == 50
    assert len({cell.review_blind_id for cell in plan.cells}) == 50
    assert compile_evaluation_cell_plan(manifest) == plan
    resource = plan.lanes[0].resource
    assert resource.max_input_tokens_per_call == 100_000
    assert resource.max_output_tokens_per_call == 32_768
    assert resource.max_requests == 1_500
    assert resource.max_total_tokens == 15_000_000
    assert resource.max_cost == 100.0


def test_package_preference_v6_proposal_compiles_two_seed_no_run_matrix() -> None:
    manifest = load_prelaunch_manifest(CURRENT_MANIFEST_PATH).manifest

    plan = compile_evaluation_cell_plan(manifest)

    assert len(plan.cells) == 100
    assert plan.lanes[0].ready_cells == 0
    assert plan.lanes[0].blocked_cells == 100
    assert "protocol:analysis-contract-missing" not in plan.plan_blockers
    assert "protocol:integrity-contract-missing" not in plan.plan_blockers
    assert manifest.primary_endpoint.value == "blinded_package_preference"
    assert all(task.signal_kind.value == "research_package_review" for task in manifest.tasks)
    assert plan.authorizes_execution is False
    assert plan.no_provider_call_performed is True
    assert plan.no_gpu_work_performed is True
    assert plan.no_task_download_performed is True


def test_fully_declared_cells_are_preparation_ready_but_never_authorized() -> None:
    plan = compile_evaluation_cell_plan(_ready_manifest())

    assert plan.ready_for_launch_preparation is True
    assert plan.plan_blockers == ()
    assert all(cell.ready_for_launch_preparation for cell in plan.cells)
    assert all(not cell.readiness_blockers for cell in plan.cells)
    assert plan.lanes[0].ready_cells == 50
    assert plan.authorizes_execution is False


def test_cell_identity_changes_with_the_proposal_and_preserves_declared_order() -> None:
    manifest = _ready_manifest()
    first = compile_evaluation_cell_plan(manifest)
    lane = manifest.lanes[0].model_copy(
        update={"seeds": (19,), "planned_cells": len(manifest.systems) * len(manifest.tasks)}
    )
    changed = compile_evaluation_cell_plan(manifest.model_copy(update={"lanes": (lane,)}))

    assert first.proposal_sha256 != changed.proposal_sha256
    assert first.plan_sha256 != changed.plan_sha256
    assert {cell.cell_id for cell in first.cells}.isdisjoint(
        {cell.cell_id for cell in changed.cells}
    )
    assert tuple(cell.cell_id for cell in first.cells) == first.lanes[0].cell_ids


def test_plan_materialization_is_canonical_and_rejects_symlink_target(tmp_path: Path) -> None:
    plan = compile_evaluation_cell_plan(_ready_manifest())
    target = tmp_path / "cell-plan.json"

    assert save_evaluation_cell_plan(plan, target) == target
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["plan_sha256"] == plan.plan_sha256
    assert loaded["authorizes_execution"] is False

    symlink = tmp_path / "linked.json"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="cannot be a symlink"):
        save_evaluation_cell_plan(plan, symlink)
