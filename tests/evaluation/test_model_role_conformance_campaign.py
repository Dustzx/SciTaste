from __future__ import annotations

import hashlib
from pathlib import Path

from scitaste.evaluation.model_role_conformance_campaign import (
    CampaignReadiness,
    ConformanceRunnerKind,
    inspect_bytebound_conformance_campaign,
    load_bytebound_campaign_plan,
    prepare_bytebound_conformance_campaign,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

REPOSITORY_ROOT = Path(__file__).parents[2]
CAMPAIGN_SPEC = (
    REPOSITORY_ROOT / "configs/evaluation/model_roles/scitaste_b0_bytebound_campaign_v1.yaml"
)


def _registered_project(outputs_root: Path) -> None:
    runtime = ProjectRuntime(outputs_root)
    snapshot = runtime.create(
        ProjectManifest(
            project_id="campaign-test",
            title="Campaign test",
            research_direction="Verify task-excluded role selection.",
            target_domain="autonomous-research",
            status="active",
        )
    )
    runtime.begin_run(
        "campaign-test",
        ProjectRun(
            run_id="b0-role-selection",
            provider="scitaste",
            model="role-conformance",
            condition="b0",
            seed=0,
            status="running",
            evidence_scope="engineering-only",
            stage_path="campaign",
        ),
        expected_revision=snapshot.revision,
    )


def test_prepare_builds_project_owned_exact_request_pack_without_execution(
    tmp_path: Path,
) -> None:
    outputs_root = tmp_path / "outputs"
    _registered_project(outputs_root)

    plan, plan_path = prepare_bytebound_conformance_campaign(
        CAMPAIGN_SPEC,
        project_id="campaign-test",
        run_id="b0-role-selection",
        outputs_root=outputs_root,
        repository_root=REPOSITORY_ROOT,
    )

    assert plan_path.is_relative_to(outputs_root / "projects/campaign-test")
    assert len(plan.requests) == 46
    assert (plan.expected_api_calls, plan.expected_local_dispatches) == (20, 26)
    assert plan.expected_max_gpu_hours == 6.0
    assert plan.expected_max_disk_bytes == 46 * 32 * 1024 * 1024
    assert set(plan.development_source_groups).isdisjoint(plan.formal_partition_source_groups)
    assert plan.execution_authorized is False
    assert plan.no_api_call_performed is True
    assert plan.no_gpu_work_performed is True

    for request in plan.requests:
        case_bytes = (REPOSITORY_ROOT / request.case_path).read_bytes()
        assert hashlib.sha256(case_bytes).hexdigest() == request.case_sha256
        assert request.case_payload.task_id == request.case_id
        request_file = plan_path.parent / "requests" / f"{request.request_id}.json"
        assert request_file.is_file()
        if request.runner_kind is ConformanceRunnerKind.MODEL_NODE_RUNTIME:
            assert request.existing_runner_binding is not None
            assert request.existing_runner_binding.materialized is False
            assert request.readiness is CampaignReadiness.REQUEST_PREPARED
            assert "model-node runtime execute" in (request.existing_runner_binding.next_command)
            assert "<RUNTIME_CONFIG_JSON>" in request.existing_runner_binding.next_command
            if request.resource.execution_kind.value == "local":
                assert request.resource.exact_checkpoint_hash_resolved is False
        else:
            assert request.existing_runner_binding is None
            assert request.readiness is CampaignReadiness.BLOCKED
            assert "embedding-dispatcher-not-implemented" in request.blockers

    assert load_bytebound_campaign_plan(plan_path).campaign_plan_sha256 == (
        plan.campaign_plan_sha256
    )


def test_status_compiles_no_receipts_as_incomplete_and_names_next_action(
    tmp_path: Path,
) -> None:
    outputs_root = tmp_path / "outputs"
    _registered_project(outputs_root)
    _, plan_path = prepare_bytebound_conformance_campaign(
        CAMPAIGN_SPEC,
        project_id="campaign-test",
        run_id="b0-role-selection",
        outputs_root=outputs_root,
        repository_root=REPOSITORY_ROOT,
    )

    status = inspect_bytebound_conformance_campaign(plan_path)

    assert status.completed_requests == 0
    assert status.selection_status.value == "incomplete"
    assert status.selection_ref is None
    assert status.headline_eligible is False
    if status.readiness is CampaignReadiness.REQUEST_PREPARED:
        assert status.request_prepared_ids
        assert status.launch_ready_requests == 0
        assert status.launch_ready_request_ids == ()
        assert status.next_action.startswith("materialize executor bindings")
    else:
        assert status.blocked_request_ids
