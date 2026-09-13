from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scitaste.generative_ui import gate_action as gate_action_module
from scitaste.generative_ui.gate_action import (
    GateActionDecisionRequest,
    GateActionInvocation,
    GateActionResource,
    ProjectGateActionPacket,
    ProjectGateActionService,
    require_authorized_gate_action,
)
from scitaste.project import ProjectManifest, ProjectRuntime


def _runtime(tmp_path) -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="gate-project",
            title="Gate project",
            research_direction="Authorize an exact local calibration.",
            status="active",
        )
    )
    return runtime, snapshot


def _packet(snapshot) -> ProjectGateActionPacket:
    return ProjectGateActionPacket.create(
        packet_id="gate-action-reference-quality-v1",
        project_id="gate-project",
        snapshot_revision=snapshot.revision,
        snapshot_sha256=snapshot.snapshot_sha256,
        dossier_id="iclr-evidence-program",
        dossier_sha256="a" * 64,
        effective_program_sha256="b" * 64,
        stage_id="qualify-scientific-taste-source-pilot",
        route_sha256="c" * 64,
        action_run_id="local-quality-calibration",
        action_plan_locator="evaluations/calibration/REPORT.json",
        action_plan_file_sha256="d" * 64,
        action_plan_sha256="e" * 64,
        action_kind="local-reference-quality-calibration",
        purpose="Calibrate one bounded project instrument on two stress cases.",
        claim_boundary="This calibration cannot establish scientific effectiveness.",
        provider="local-transformers",
        model="Qwen/Qwen3-VL-2B-Instruct@local-snapshot",
        source_state_revision=snapshot.revision,
        resource_binding_record_sha256="f" * 64,
        resources=(
            GateActionResource(
                resource_id="gpu-host-local-3090",
                binding_id="development-gpu-local",
                role="development-gpu",
                kind="gpu_host",
                status="verified",
            ),
            GateActionResource(
                resource_id="qwen3-vl-2b-local",
                binding_id="verified-local-qwen3vl2b",
                role="verified-checkpoint",
                kind="model_checkpoint",
                status="verified",
            ),
        ),
        invocations=(
            GateActionInvocation(
                invocation_id="calibrate-source-one",
                source_id="source-one",
                selection_role="maximum-context-stress",
                config_locator="evaluations/calibration/invocations/source-one.json",
                config_sha256="1" * 64,
                state_revision=snapshot.revision,
                exact_input_tokens=24_670,
                maximum_output_tokens=8_192,
            ),
            GateActionInvocation(
                invocation_id="calibrate-source-two",
                source_id="source-two",
                selection_role="maximum-redaction-stress",
                config_locator="evaluations/calibration/invocations/source-two.json",
                config_sha256="2" * 64,
                state_revision=snapshot.revision,
                exact_input_tokens=6_759,
                maximum_output_tokens=8_192,
            ),
        ),
        gpu_device_class="NVIDIA GeForce RTX 3090",
        maximum_gpu_hours=1.0,
        maximum_input_tokens=24_670,
        maximum_output_tokens=8_192,
        inline_guard_codes=(
            "packet-identity-at-use",
            "project-revision-at-use",
            "checkpoint-hash-at-load",
            "model-node-budget-at-call",
        ),
        verification_route="owner_approval",
        verification_reason_codes=(
            "declared-owner-boundary-requires-owner",
            "external-authority-requires-owner",
        ),
    )


def _request(packet: ProjectGateActionPacket, decision: str = "authorize"):
    return GateActionDecisionRequest(
        project_id=packet.project_id,
        packet_id=packet.packet_id,
        packet_sha256=packet.packet_sha256,
        expected_snapshot_revision=packet.snapshot_revision,
        expected_snapshot_sha256=packet.snapshot_sha256,
        decision=decision,
        decided_by="project-owner",
        confirm_exact_scope=True,
    )


def test_owner_authorization_is_exact_bounded_and_still_does_not_execute(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, snapshot = _runtime(tmp_path)
    packet = _packet(snapshot)
    monkeypatch.setattr(
        gate_action_module,
        "build_current_gate_action_packet",
        lambda runtime, project_id: packet,
    )
    now = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
    service = ProjectGateActionService(runtime)

    before = service.current("gate-project", now=now)
    decision = service.decide(_request(packet), now=now)
    after = service.current("gate-project", now=now)

    assert before.status == "ready_for_owner_decision"
    assert decision.decision == "authorized"
    assert decision.authorization_expires_at == now + timedelta(hours=24)
    assert decision.authorizes_local_model_calls is True
    assert decision.authorizes_gpu_work is True
    assert decision.authorizes_execution is True
    assert decision.authorizes_api_calls is False
    assert decision.authorizes_network_access is False
    assert decision.execution_performed is False
    assert decision.standalone_preflight_performed is False
    assert after.status == "authorized"
    assert runtime.open("gate-project").revision == snapshot.revision
    assert list((runtime.projects_root / "gate-project" / "runs").iterdir()) == []

    resolved_packet, resolved_decision = require_authorized_gate_action(
        runtime,
        project_id="gate-project",
        packet_sha256=packet.packet_sha256,
        decision_id=decision.decision_id,
        decision_sha256=decision.decision_sha256,
        now=now,
    )
    assert resolved_packet == packet
    assert resolved_decision == decision


def test_rejection_and_stale_identity_cannot_grant_authority(tmp_path, monkeypatch) -> None:
    runtime, snapshot = _runtime(tmp_path)
    packet = _packet(snapshot)
    monkeypatch.setattr(
        gate_action_module,
        "build_current_gate_action_packet",
        lambda runtime, project_id: packet,
    )
    service = ProjectGateActionService(runtime)
    now = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="stale"):
        service.decide(
            _request(packet).model_copy(update={"packet_sha256": "0" * 64}),
            now=now,
        )
    rejected = service.decide(_request(packet, "reject"), now=now)

    assert rejected.decision == "rejected"
    assert rejected.authorizes_execution is False
    assert service.current("gate-project", now=now).status == "rejected"
    with pytest.raises(ValueError, match="already has"):
        service.decide(_request(packet, "authorize"), now=now)
