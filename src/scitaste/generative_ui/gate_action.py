"""Project-owned owner decisions for the current Generation as Content gate.

The generated project home may explain and revise the scientific plan, but an
external action still needs an exact deterministic envelope.  This module
projects the current action into that envelope and records an owner's bounded
decision.  It never starts a model, opens a network connection, or reserves a
GPU.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation import compile_effective_experiment_program
from scitaste.evaluation.aaar_quality_calibration import AaarQualityCalibrationPlan
from scitaste.evaluation.program_action import route_effective_program_action
from scitaste.generative_ui.evidence_program import (
    find_current_action_run,
    find_iclr_evidence_program_run,
    load_iclr_evidence_program_report,
)
from scitaste.generative_ui.planning_directive import (
    load_latest_planning_directive,
    planning_control_from_publication,
)
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.facade import ModelNodeFacade, ModelNodeFacadeRequest
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeOutcome
from scitaste.model_nodes.runtime_config import (
    LocalRuntimeBackend,
    load_model_node_runtime_config,
)
from scitaste.model_nodes.verification_policy import VerificationRoute
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256
from scitaste.resources import (
    ComputeResourceRuntime,
    GpuHostDefinition,
    ModelCheckpointDefinition,
    ObservationStatus,
    load_compute_resource_catalog,
)
from scitaste.resources.registry import (
    RegisteredProjectResourceBinding,
    ResourceRegistrySnapshot,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_CONTROL_BYTES = 16 * 1_048_576
_AUTHORIZATION_LIFETIME = timedelta(hours=24)


class GateActionInvocation(BaseModel):
    """One exact already-materialized invocation; the input itself stays private."""

    model_config = _CONFIG

    invocation_id: SafeIdentifier
    source_id: SafeIdentifier
    selection_role: Literal["maximum-context-stress", "maximum-redaction-stress"]
    config_locator: str = Field(min_length=1, max_length=1_000)
    config_sha256: Sha256
    state_revision: int = Field(ge=0)
    exact_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)


class GateActionResource(BaseModel):
    """One project binding actually consumed by the proposed action."""

    model_config = _CONFIG

    resource_id: SafeIdentifier
    binding_id: SafeIdentifier
    role: SafeIdentifier
    kind: Literal["gpu_host", "model_checkpoint"]
    status: Literal[ObservationStatus.VERIFIED] = ObservationStatus.VERIFIED


class ProjectGateActionPacket(BaseModel):
    """Exact current action envelope shown before an owner decision."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    packet_id: SafeIdentifier
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    dossier_id: SafeIdentifier
    dossier_sha256: Sha256
    effective_program_sha256: Sha256
    stage_id: SafeIdentifier
    route_sha256: Sha256
    action_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=255)
    action_plan_locator: str = Field(min_length=1, max_length=1_000)
    action_plan_file_sha256: Sha256
    action_plan_sha256: Sha256
    action_kind: Literal["local-reference-quality-calibration"]
    purpose: str = Field(min_length=1, max_length=1_000)
    claim_boundary: str = Field(min_length=1, max_length=1_000)
    provider: Literal["local-transformers"]
    model: str = Field(min_length=1, max_length=300)
    source_state_revision: int = Field(ge=0)
    resource_binding_record_sha256: Sha256
    resources: tuple[GateActionResource, GateActionResource]
    invocations: tuple[GateActionInvocation, GateActionInvocation]
    model_call_ceiling: Literal[2] = 2
    gpu_device_count: Literal[1] = 1
    gpu_device_class: Literal["NVIDIA GeForce RTX 3090"]
    maximum_gpu_hours: float = Field(gt=0, le=1.0)
    maximum_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)
    network_access: Literal[False] = False
    api_calls: Literal[0] = 0
    source_upload: Literal[False] = False
    execution_guard_mode: Literal["inline-at-execution"] = "inline-at-execution"
    standalone_preflight_required: Literal[False] = False
    inline_guard_codes: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    verification_route: Literal[VerificationRoute.OWNER_APPROVAL]
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    owner_decision_required: Literal[True] = True
    ready_for_owner_decision: Literal[True] = True
    action_performed: Literal[False] = False
    authorizes_execution: Literal[False] = False
    packet_sha256: Sha256

    @model_validator(mode="after")
    def packet_is_closed(self) -> ProjectGateActionPacket:
        if {item.kind for item in self.resources} != {"gpu_host", "model_checkpoint"}:
            raise ValueError("gate action requires one GPU host and one checkpoint")
        if len({item.resource_id for item in self.resources}) != len(self.resources):
            raise ValueError("gate-action resource IDs must be unique")
        if len({item.invocation_id for item in self.invocations}) != len(self.invocations):
            raise ValueError("gate-action invocation IDs must be unique")
        if len({item.source_id for item in self.invocations}) != len(self.invocations):
            raise ValueError("gate-action sources must be unique")
        if self.maximum_input_tokens != max(item.exact_input_tokens for item in self.invocations):
            raise ValueError("gate-action maximum input tokens differ from invocations")
        if self.maximum_output_tokens != max(
            item.maximum_output_tokens for item in self.invocations
        ):
            raise ValueError("gate-action maximum output tokens differ from invocations")
        expected = content_sha256(self.model_dump(mode="json", exclude={"packet_sha256"}))
        if self.packet_sha256 != expected:
            raise ValueError("gate-action packet hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectGateActionPacket:
        payload = {"schema_version": "1.0", **values}
        payload.pop("packet_sha256", None)
        unsigned = cls.model_construct(packet_sha256="0" * 64, **payload)
        return cls(
            **payload,
            packet_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"packet_sha256"})
            ),
        )


class GateActionDecisionRequest(BaseModel):
    """Explicit decision over one exact current packet."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    packet_id: SafeIdentifier
    packet_sha256: Sha256
    expected_snapshot_revision: int = Field(ge=0)
    expected_snapshot_sha256: Sha256
    decision: Literal["authorize", "reject"]
    decided_by: str = Field(min_length=1, max_length=200)
    confirm_exact_scope: Literal[True]

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class GateActionDecisionRecord(BaseModel):
    """Immutable bounded authority; authorization is not execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    decision_id: SafeIdentifier
    project_id: ProjectIdentifier
    packet_id: SafeIdentifier
    packet_sha256: Sha256
    request_fingerprint: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    decision: Literal["authorized", "rejected"]
    decided_by: str = Field(min_length=1, max_length=200)
    decided_at: datetime
    authorization_expires_at: datetime | None = None
    authorization_scope: Literal["exact-local-reference-quality-calibration"] | None = None
    model_call_ceiling: int = Field(ge=0, le=2)
    maximum_gpu_hours: float = Field(ge=0, le=1.0)
    authorizes_local_model_calls: bool
    authorizes_gpu_work: bool
    authorizes_api_calls: Literal[False] = False
    authorizes_network_access: Literal[False] = False
    authorizes_source_upload: Literal[False] = False
    authorizes_execution: bool
    execution_performed: Literal[False] = False
    standalone_preflight_performed: Literal[False] = False
    verification_route: Literal[VerificationRoute.OWNER_APPROVAL]
    decision_sha256: Sha256

    @model_validator(mode="after")
    def decision_is_closed(self) -> GateActionDecisionRecord:
        if self.decided_at.utcoffset() is None:
            raise ValueError("gate-action decision time must include a timezone")
        authorized = self.decision == "authorized"
        if authorized:
            if (
                self.authorization_expires_at is None
                or self.authorization_expires_at.utcoffset() is None
                or self.authorization_expires_at <= self.decided_at
                or self.authorization_scope is None
            ):
                raise ValueError("authorized gate action requires a bounded lifetime and scope")
        elif self.authorization_expires_at is not None or self.authorization_scope is not None:
            raise ValueError("rejected gate action cannot contain authorization metadata")
        if any(
            value != authorized
            for value in (
                self.authorizes_local_model_calls,
                self.authorizes_gpu_work,
                self.authorizes_execution,
            )
        ):
            raise ValueError("gate-action authority differs from the owner decision")
        if self.model_call_ceiling != (2 if authorized else 0):
            raise ValueError("gate-action call ceiling differs from the owner decision")
        if self.maximum_gpu_hours != (1.0 if authorized else 0.0):
            raise ValueError("gate-action GPU ceiling differs from the owner decision")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("gate-action decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> GateActionDecisionRecord:
        payload = {"schema_version": "1.0", **values}
        payload.pop("decision_sha256", None)
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


class ProjectGateActionView(BaseModel):
    """Current packet and its decision, if one remains valid for this snapshot."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal[
        "unavailable",
        "ready_for_owner_decision",
        "authorized",
        "rejected",
        "authorization_expired",
    ]
    packet: ProjectGateActionPacket | None = None
    decision: GateActionDecisionRecord | None = None
    reason_code: SafeIdentifier
    model_call_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    network_access_performed: Literal[False] = False

    @model_validator(mode="after")
    def view_is_consistent(self) -> ProjectGateActionView:
        if self.status == "unavailable":
            if self.packet is not None or self.decision is not None:
                raise ValueError("unavailable gate-action view cannot contain a packet")
            return self
        if self.packet is None:
            raise ValueError("available gate-action view requires a packet")
        decision_states = {"authorized", "rejected", "authorization_expired"}
        if (self.status in decision_states) != (self.decision is not None):
            raise ValueError("gate-action view decision state is inconsistent")
        return self


class GateActionExecutionItem(BaseModel):
    """One completed bounded invocation projected without raw model content."""

    model_config = _CONFIG

    invocation_id: SafeIdentifier
    source_id: SafeIdentifier
    outcome: Literal["accepted", "rejected", "failed", "blocked", "not_applicable"]
    entry_sha256: Sha256
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    blocker_count: int = Field(ge=0)


class GateActionExecutionReceipt(BaseModel):
    """Content-addressed evidence that the separately authorized action ran."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    execution_id: SafeIdentifier
    project_id: ProjectIdentifier
    action_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=255)
    packet_id: SafeIdentifier
    packet_sha256: Sha256
    decision_id: SafeIdentifier
    decision_sha256: Sha256
    executed_at: datetime
    items: tuple[GateActionExecutionItem, ...] = Field(min_length=1, max_length=2)
    accepted_count: int = Field(ge=0, le=2)
    rejected_count: int = Field(ge=0, le=2)
    failed_count: int = Field(ge=0, le=2)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    model_calls_performed: int = Field(ge=0, le=2)
    gpu_work_performed: bool
    network_access_performed: Literal[False] = False
    api_calls_performed: Literal[0] = 0
    source_uploaded: Literal[False] = False
    standalone_preflight_performed: Literal[False] = False
    execution_complete: bool
    scientific_effectiveness_established: Literal[False] = False
    authorizes_further_execution: Literal[False] = False
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def receipt_is_closed(self) -> GateActionExecutionReceipt:
        if self.executed_at.utcoffset() is None:
            raise ValueError("gate-action execution time must include a timezone")
        outcomes = [item.outcome for item in self.items]
        if self.accepted_count != outcomes.count("accepted"):
            raise ValueError("gate-action accepted count differs from its items")
        if self.rejected_count != outcomes.count("rejected"):
            raise ValueError("gate-action rejected count differs from its items")
        if self.failed_count != sum(
            outcome in {"failed", "blocked", "not_applicable"} for outcome in outcomes
        ):
            raise ValueError("gate-action failure count differs from its items")
        if self.total_input_tokens != sum(item.input_tokens for item in self.items):
            raise ValueError("gate-action input-token total differs from its items")
        if self.total_output_tokens != sum(item.output_tokens for item in self.items):
            raise ValueError("gate-action output-token total differs from its items")
        called = sum(item.outcome in {"accepted", "rejected"} for item in self.items)
        if self.model_calls_performed != called:
            raise ValueError("gate-action model-call count differs from its outcomes")
        if self.gpu_work_performed != (called > 0):
            raise ValueError("gate-action GPU-use state differs from its model calls")
        if self.execution_complete != (self.failed_count == 0):
            raise ValueError("gate-action completion differs from its outcomes")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("gate-action execution receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> GateActionExecutionReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class ProjectGateActionService:
    """Resolve current action packets and append exact owner decisions."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        self.runtime = runtime

    def current(self, project_id: str, *, now: datetime | None = None) -> ProjectGateActionView:
        try:
            packet = build_current_gate_action_packet(self.runtime, project_id)
        except (FileNotFoundError, OSError, ValueError):
            return ProjectGateActionView(
                status="unavailable",
                reason_code="current-gate-action-unavailable",
            )
        decision = _latest_decision(self.runtime, packet)
        if decision is None:
            return ProjectGateActionView(
                status="ready_for_owner_decision",
                packet=packet,
                reason_code="exact-action-awaits-owner-decision",
            )
        if decision.decision == "rejected":
            return ProjectGateActionView(
                status="rejected",
                packet=packet,
                decision=decision,
                reason_code="exact-action-rejected-by-owner",
            )
        observed_at = now or datetime.now(UTC)
        assert decision.authorization_expires_at is not None
        if observed_at >= decision.authorization_expires_at:
            return ProjectGateActionView(
                status="authorization_expired",
                packet=packet,
                decision=decision,
                reason_code="exact-action-authorization-expired",
            )
        return ProjectGateActionView(
            status="authorized",
            packet=packet,
            decision=decision,
            reason_code="exact-action-authorized-not-executed",
        )

    def decide(
        self,
        request: GateActionDecisionRequest | dict[str, object],
        *,
        now: datetime | None = None,
    ) -> GateActionDecisionRecord:
        parsed = (
            request
            if isinstance(request, GateActionDecisionRequest)
            else GateActionDecisionRequest.model_validate(request)
        )
        packet = build_current_gate_action_packet(self.runtime, parsed.project_id)
        if (
            packet.packet_id != parsed.packet_id
            or packet.packet_sha256 != parsed.packet_sha256
            or packet.snapshot_revision != parsed.expected_snapshot_revision
            or packet.snapshot_sha256 != parsed.expected_snapshot_sha256
        ):
            raise ValueError("gate-action decision is stale or targets another packet")
        existing = _latest_decision(self.runtime, packet)
        if existing is not None:
            requested = "authorized" if parsed.decision == "authorize" else "rejected"
            if (
                existing.decision == requested
                and existing.request_fingerprint == parsed.fingerprint
            ):
                return existing
            raise ValueError("this exact gate-action packet already has an owner decision")

        decided_at = now or datetime.now(UTC)
        if decided_at.utcoffset() is None:
            raise ValueError("gate-action decision time must include a timezone")
        authorized = parsed.decision == "authorize"
        prototype = GateActionDecisionRecord.create(
            decision_id="pending-gate-action-decision",
            project_id=packet.project_id,
            packet_id=packet.packet_id,
            packet_sha256=packet.packet_sha256,
            request_fingerprint=parsed.fingerprint,
            snapshot_revision=packet.snapshot_revision,
            snapshot_sha256=packet.snapshot_sha256,
            decision="authorized" if authorized else "rejected",
            decided_by=parsed.decided_by,
            decided_at=decided_at,
            authorization_expires_at=(
                decided_at + _AUTHORIZATION_LIFETIME if authorized else None
            ),
            authorization_scope=(
                "exact-local-reference-quality-calibration" if authorized else None
            ),
            model_call_ceiling=2 if authorized else 0,
            maximum_gpu_hours=1.0 if authorized else 0.0,
            authorizes_local_model_calls=authorized,
            authorizes_gpu_work=authorized,
            authorizes_execution=authorized,
            verification_route=packet.verification_route,
        )
        record = GateActionDecisionRecord.create(
            **prototype.model_dump(
                mode="python",
                exclude={"decision_id", "decision_sha256"},
            ),
            decision_id=f"gate-decision-{prototype.decision_sha256[:20]}",
        )
        _save_decision(self.runtime, record)
        return record


def build_current_gate_action_packet(
    runtime: ProjectRuntime,
    project_id: str,
) -> ProjectGateActionPacket:
    """Project the exact current local calibration without executing a preflight."""

    snapshot = runtime.open(project_id)
    program_run = find_iclr_evidence_program_run(snapshot)
    if program_run is None:
        raise ValueError("project has no ICLR evidence program")
    report, _ = load_iclr_evidence_program_report(runtime.projects_root / project_id, program_run)
    publication = load_latest_planning_directive(runtime, project_id)
    control = planning_control_from_publication(publication) if publication is not None else None
    effective = compile_effective_experiment_program(report, project_id=project_id, control=control)
    route = route_effective_program_action(report, effective)
    if (
        route.stage_id != "qualify-scientific-taste-source-pilot"
        or route.verification.route is not VerificationRoute.OWNER_APPROVAL
    ):
        raise ValueError("current program gate has no supported owner action packet")
    action_run = find_current_action_run(snapshot, route.stage_id)
    if action_run is None or action_run.artifact is None:
        raise ValueError("current program gate lacks an exact action run")
    if action_run.status != "planned-awaiting-owner-resource-review":
        raise ValueError("current gate action is not awaiting an owner resource decision")
    plan_path = _project_file(runtime, project_id, action_run.artifact)
    raw = _bounded_file(plan_path)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("gate-action plan must contain a JSON object")
    recorded_plan_sha256 = payload.pop("report_sha256", None)
    plan = AaarQualityCalibrationPlan.model_validate(payload)
    if recorded_plan_sha256 != plan.report_sha256:
        raise ValueError("gate-action plan semantic hash mismatch")
    if plan.project_id != project_id or plan.intended_run_id != action_run.run_id:
        raise ValueError("gate-action plan belongs to another project run")
    if plan.exact_token_count_status != "verified-local-tokenizer":
        raise ValueError("gate-action plan lacks exact tokenizer evidence")

    profile_source = Path(plan.profile_set_locator).resolve(strict=True)
    profile_raw = _bounded_file(profile_source)
    if hashlib.sha256(profile_raw).hexdigest() != plan.profile_set_file_sha256:
        raise ValueError("gate-action profile-set hash drifted")
    profiles = load_model_node_profile_set(profile_source)
    try:
        profile = profiles.profiles[plan.profile_id]
    except KeyError as exc:
        raise ValueError("gate-action profile is unavailable") from exc
    if profile.fingerprint != plan.profile_sha256 or not profile.local_execution_permitted:
        raise ValueError("gate-action profile identity drifted")

    invocations: list[GateActionInvocation] = []
    plan_root = plan_path.parent
    for item in plan.items:
        config_path = _relative_file(plan_root, item.runtime_config_locator)
        loaded = load_model_node_runtime_config(config_path)
        config = loaded.config
        if loaded.source_sha256 != item.runtime_config_sha256:
            raise ValueError("gate-action invocation config hash drifted")
        if not isinstance(config.backend, LocalRuntimeBackend):
            raise ValueError("gate-action invocation must use the local backend")
        if (
            config.backend.config.model_identity != plan.model
            or config.state_projection.project_id != project_id
            or config.state_projection.evidence_ids != (item.source_id,)
            or item.exact_input_tokens is None
        ):
            raise ValueError("gate-action invocation identity drifted")
        invocation_id = config.request_id or f"calibrate-{item.source_id}"
        invocations.append(
            GateActionInvocation(
                invocation_id=invocation_id,
                source_id=item.source_id,
                selection_role=item.selection_role,
                config_locator=config_path.relative_to(
                    runtime.projects_root / project_id
                ).as_posix(),
                config_sha256=loaded.source_sha256,
                state_revision=config.state_projection.state_revision,
                exact_input_tokens=item.exact_input_tokens,
                maximum_output_tokens=profile.generation.max_output_tokens,
            )
        )
    resources, binding_sha256 = _resolve_resources(runtime, project_id, plan)
    source_revisions = {item.state_revision for item in invocations}
    if len(source_revisions) != 1:
        raise ValueError("gate-action invocations use different state revisions")
    return ProjectGateActionPacket.create(
        packet_id=f"gate-action-{plan.plan_id}",
        project_id=project_id,
        snapshot_revision=snapshot.revision,
        snapshot_sha256=snapshot.snapshot_sha256,
        dossier_id=report.dossier_id,
        dossier_sha256=report.dossier_sha256,
        effective_program_sha256=effective.program_sha256,
        stage_id=route.stage_id,
        route_sha256=route.route_sha256,
        action_run_id=action_run.run_id,
        action_plan_locator=action_run.artifact,
        action_plan_file_sha256=hashlib.sha256(raw).hexdigest(),
        action_plan_sha256=plan.report_sha256,
        action_kind="local-reference-quality-calibration",
        purpose=(
            "Calibrate the prestige-blind Reference Quality instrument on two admitted "
            "AAAR stress cases before using it in the Scientific Taste experiment."
        ),
        claim_boundary=(
            "Instrument calibration only; this cannot establish source quality, Taste "
            "effectiveness, benchmark superiority, or paper-level evidence."
        ),
        provider=plan.provider,
        model=plan.model,
        source_state_revision=source_revisions.pop(),
        resource_binding_record_sha256=binding_sha256,
        resources=resources,
        invocations=tuple(invocations),
        gpu_device_class=plan.gpu_device_class,
        maximum_gpu_hours=plan.maximum_gpu_hours,
        maximum_input_tokens=max(item.exact_input_tokens for item in invocations),
        maximum_output_tokens=max(item.maximum_output_tokens for item in invocations),
        inline_guard_codes=(
            "packet-identity-at-use",
            "project-revision-at-use",
            "checkpoint-hash-at-load",
            "model-node-budget-at-call",
        ),
        verification_route=route.verification.route,
        verification_reason_codes=route.verification.reason_codes,
    )


def require_authorized_gate_action(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    packet_sha256: str,
    decision_id: str,
    decision_sha256: str,
    now: datetime | None = None,
) -> tuple[ProjectGateActionPacket, GateActionDecisionRecord]:
    """Resolve exact unexpired authority for an executor without doing a preflight run."""

    packet = build_current_gate_action_packet(runtime, project_id)
    if packet.packet_sha256 != packet_sha256:
        raise ValueError("authorized gate-action packet is no longer current")
    decision = _load_decision(runtime, project_id, packet.packet_id, decision_id)
    if (
        decision.packet_sha256 != packet.packet_sha256
        or decision.decision_sha256 != decision_sha256
        or decision.decision != "authorized"
        or not decision.authorizes_execution
    ):
        raise ValueError("gate-action decision does not authorize this packet")
    observed_at = now or datetime.now(UTC)
    assert decision.authorization_expires_at is not None
    if observed_at >= decision.authorization_expires_at:
        raise ValueError("gate-action authorization expired")
    return packet, decision


def execute_authorized_gate_action(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    packet_sha256: str,
    decision_id: str,
    decision_sha256: str,
    expected_project_revision: int,
    allow_local: bool,
    resume: bool = False,
    now: datetime | None = None,
) -> GateActionExecutionReceipt:
    """Execute the exact two-item local action with no separate preflight pass."""

    if not allow_local:
        raise ValueError("authorized gate action still requires the local-execution switch")
    packet, decision = require_authorized_gate_action(
        runtime,
        project_id=project_id,
        packet_sha256=packet_sha256,
        decision_id=decision_id,
        decision_sha256=decision_sha256,
        now=now,
    )
    snapshot = runtime.open(project_id)
    if (
        snapshot.revision != expected_project_revision
        or packet.snapshot_revision != expected_project_revision
    ):
        raise ValueError("gate-action project revision changed after owner authorization")

    plan_path = _project_file(runtime, project_id, packet.action_plan_locator)
    plan_payload = json.loads(_bounded_file(plan_path))
    if not isinstance(plan_payload, dict):
        raise ValueError("gate-action plan must contain a JSON object")
    recorded_plan_sha256 = plan_payload.pop("report_sha256", None)
    plan = AaarQualityCalibrationPlan.model_validate(plan_payload)
    if plan.report_sha256 != recorded_plan_sha256:
        raise ValueError("gate-action plan semantic hash mismatch at execution")
    profiles = load_model_node_profile_set(Path(plan.profile_set_locator).resolve(strict=True))
    profile = profiles.profiles[plan.profile_id]

    loaded_configs = [
        load_model_node_runtime_config(_project_file(runtime, project_id, item.config_locator))
        for item in packet.invocations
    ]
    backend_configs = []
    for loaded in loaded_configs:
        if not isinstance(loaded.config.backend, LocalRuntimeBackend):
            raise ValueError("gate-action execution requires the local backend")
        backend_configs.append(loaded.config.backend.config)
    if any(config != backend_configs[0] for config in backend_configs[1:]):
        raise ValueError("gate-action invocations do not share one checkpoint runtime")
    backend = loaded_configs[0].config.build_backend(packet.invocations[0].invocation_id)
    facade = ModelNodeFacade(
        ModelNodeRuntime(runtime, node_types=first_party_node_types())
    )

    rows: list[GateActionExecutionItem] = []
    for item, loaded in zip(packet.invocations, loaded_configs, strict=True):
        config = loaded.config
        request = ModelNodeFacadeRequest(
            project_id=project_id,
            run_id=packet.action_run_id,
            invocation_id=item.invocation_id,
            request_id=config.request_id,
            expected_project_revision=expected_project_revision,
            node_name=config.node_name,
            node_input=config.node_input,
            state_projection=config.state_projection,
            trigger=config.trigger,
            profile=profile,
            policy=config.policy,
            backend_mode=config.backend_mode,
            seed=config.seed,
        )
        result = facade.execute(
            request,
            backend=backend,
            resume=resume,
            allow_local=True,
        )
        receipt = result.receipt
        rows.append(
            GateActionExecutionItem(
                invocation_id=item.invocation_id,
                source_id=item.source_id,
                outcome=receipt.outcome.value,
                entry_sha256=receipt.entry_sha256,
                input_tokens=receipt.telemetry.input_tokens,
                output_tokens=receipt.telemetry.output_tokens,
                latency_ms=receipt.telemetry.latency_ms,
                blocker_count=len(receipt.blockers),
            )
        )
        if receipt.outcome in {RuntimeOutcome.BLOCKED, RuntimeOutcome.FAILED}:
            break
    outcomes = [item.outcome for item in rows]
    executed_at = now or datetime.now(UTC)
    execution = GateActionExecutionReceipt.create(
        execution_id=f"gate-execution-{packet.packet_sha256[:20]}",
        project_id=project_id,
        action_run_id=packet.action_run_id,
        packet_id=packet.packet_id,
        packet_sha256=packet.packet_sha256,
        decision_id=decision.decision_id,
        decision_sha256=decision.decision_sha256,
        executed_at=executed_at,
        items=tuple(rows),
        accepted_count=outcomes.count("accepted"),
        rejected_count=outcomes.count("rejected"),
        failed_count=sum(
            outcome in {"failed", "blocked", "not_applicable"} for outcome in outcomes
        ),
        total_input_tokens=sum(item.input_tokens for item in rows),
        total_output_tokens=sum(item.output_tokens for item in rows),
        model_calls_performed=sum(
            outcome in {"accepted", "rejected"} for outcome in outcomes
        ),
        gpu_work_performed=any(
            outcome in {"accepted", "rejected"} for outcome in outcomes
        ),
        execution_complete=not any(
            outcome in {"failed", "blocked", "not_applicable"} for outcome in outcomes
        ),
    )
    execution_locator = (
        f"runs/{packet.action_run_id}/gate_action_execution/RECEIPT.json"
    )
    _atomic_json(
        runtime.projects_root / project_id / execution_locator,
        execution.model_dump(mode="json"),
    )
    runtime.update_run(
        project_id,
        packet.action_run_id,
        expected_revision=expected_project_revision,
        status=(
            "complete-reference-quality-calibration"
            if execution.execution_complete
            else "failed-reference-quality-calibration"
        ),
        gate_action_packet_sha256=packet.packet_sha256,
        gate_action_decision_sha256=decision.decision_sha256,
        gate_action_execution_artifact=execution_locator,
        gate_action_execution_sha256=execution.receipt_sha256,
        model_calls=execution.model_calls_performed,
        input_tokens=execution.total_input_tokens,
        output_tokens=execution.total_output_tokens,
        gpu_work_performed=execution.gpu_work_performed,
        network_access_performed=False,
        api_calls=0,
        standalone_preflight_performed=False,
        scientific_effectiveness_established=False,
    )
    return execution


def _resolve_resources(
    runtime: ProjectRuntime,
    project_id: str,
    plan: AaarQualityCalibrationPlan,
) -> tuple[tuple[GateActionResource, GateActionResource], str]:
    registry_path = runtime.outputs_root / "resources" / "REGISTRY.json"
    registry = ResourceRegistrySnapshot.model_validate_json(_bounded_file(registry_path))
    if registry.calculated_sha256() != registry.registry_sha256:
        raise ValueError("gate-action resource registry hash mismatch")
    repository_root = runtime.outputs_root.parent.resolve()
    catalog_source = Path(registry.catalog_source).expanduser()
    catalog_path = (
        catalog_source if catalog_source.is_absolute() else repository_root / catalog_source
    ).resolve(strict=True)
    if not catalog_path.is_relative_to(repository_root):
        raise ValueError("gate-action resource catalog escapes the repository")
    loaded_catalog = load_compute_resource_catalog(catalog_path)
    ComputeResourceRuntime(runtime.outputs_root).open(loaded_catalog)

    binding_root = runtime.outputs_root / "resources" / "projects" / project_id
    record = RegisteredProjectResourceBinding.model_validate_json(
        _bounded_file(binding_root / "RECORD.json")
    )
    source = _bounded_file(binding_root / "RESOURCE_BINDING.yaml")
    if (
        record.calculated_sha256() != record.record_sha256
        or len(source) != record.source_size_bytes
        or hashlib.sha256(source).hexdigest() != record.source_sha256
        or record.binding.project_id != project_id
        or record.binding.catalog_semantic_sha256 != loaded_catalog.semantic_sha256
    ):
        raise ValueError("gate-action project resource binding drifted")

    selected: list[GateActionResource] = []
    for binding in record.binding.bindings:
        if binding.status is not ObservationStatus.VERIFIED:
            continue
        definition = loaded_catalog.catalog.resource(binding.resource_id)
        if isinstance(definition, GpuHostDefinition) and (
            definition.location == "local"
            and definition.device_count >= plan.gpu_device_count
            and definition.device_name == plan.gpu_device_class
            and "reference-quality-calibration" in binding.required_for
        ):
            selected.append(
                GateActionResource(
                    resource_id=binding.resource_id,
                    binding_id=binding.binding_id,
                    role=binding.role,
                    kind="gpu_host",
                    status=binding.status,
                )
            )
        if isinstance(definition, ModelCheckpointDefinition) and (
            definition.checkpoint_sha256 == plan.checkpoint_sha256
            and definition.checkpoint_bytes == plan.checkpoint_bytes
            and Path(definition.local_path).expanduser().resolve() == Path(plan.checkpoint_path)
            and "reference-quality-calibration" in binding.required_for
        ):
            selected.append(
                GateActionResource(
                    resource_id=binding.resource_id,
                    binding_id=binding.binding_id,
                    role=binding.role,
                    kind="model_checkpoint",
                    status=binding.status,
                )
            )
    by_kind = {item.kind: item for item in selected}
    if set(by_kind) != {"gpu_host", "model_checkpoint"}:
        raise ValueError("gate-action resources are not exactly bound to this project")
    return (by_kind["gpu_host"], by_kind["model_checkpoint"]), record.record_sha256


def _latest_decision(
    runtime: ProjectRuntime,
    packet: ProjectGateActionPacket,
) -> GateActionDecisionRecord | None:
    root = _decision_root(runtime, packet.project_id, packet.packet_id)
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError("gate-action decision store is unsafe")
    matches: list[GateActionDecisionRecord] = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_CONTROL_BYTES:
            raise ValueError("gate-action decision record is unsafe")
        record = GateActionDecisionRecord.model_validate_json(path.read_bytes())
        if path.name != f"{record.decision_id}.json":
            raise ValueError("gate-action decision filename differs from its identity")
        if record.project_id != packet.project_id or record.packet_id != packet.packet_id:
            raise ValueError("gate-action decision belongs to another packet")
        if record.packet_sha256 == packet.packet_sha256:
            matches.append(record)
    if len(matches) > 1:
        raise ValueError("exact gate-action packet has multiple owner decisions")
    return matches[0] if matches else None


def _save_decision(runtime: ProjectRuntime, record: GateActionDecisionRecord) -> None:
    root = _decision_root(runtime, record.project_id, record.packet_id)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("gate-action decision store cannot be a symlink")
    target = root / f"{record.decision_id}.json"
    if os.path.lexists(target):
        observed = GateActionDecisionRecord.model_validate_json(_bounded_file(target))
        if observed == record:
            return
        raise FileExistsError(target)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".gate-decision-", dir=root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(record.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _load_decision(
    runtime: ProjectRuntime,
    project_id: str,
    packet_id: str,
    decision_id: str,
) -> GateActionDecisionRecord:
    path = _decision_root(runtime, project_id, packet_id) / f"{decision_id}.json"
    record = GateActionDecisionRecord.model_validate_json(_bounded_file(path))
    if (
        record.project_id != project_id
        or record.packet_id != packet_id
        or record.decision_id != decision_id
    ):
        raise ValueError("gate-action decision identity mismatch")
    return record


def _decision_root(runtime: ProjectRuntime, project_id: str, packet_id: str) -> Path:
    return runtime.projects_root / project_id / ".generative-ui" / "gate-actions" / packet_id


def _project_file(runtime: ProjectRuntime, project_id: str, locator: str) -> Path:
    root = (runtime.projects_root / project_id).resolve(strict=True)
    path = _relative_file(root, locator)
    if not path.is_relative_to(root):  # pragma: no cover - _relative_file already enforces this
        raise ValueError("gate-action file escapes its project")
    return path


def _relative_file(root: Path, locator: str) -> Path:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("gate-action locator is unsafe")
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("gate-action locator contains a symlink")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("gate-action locator escapes its root")
    return resolved


def _bounded_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("gate-action control file must be bounded and regular")
    return path.read_bytes()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or os.path.lexists(path):
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "GateActionDecisionRecord",
    "GateActionDecisionRequest",
    "GateActionExecutionItem",
    "GateActionExecutionReceipt",
    "GateActionInvocation",
    "GateActionResource",
    "ProjectGateActionPacket",
    "ProjectGateActionService",
    "ProjectGateActionView",
    "build_current_gate_action_packet",
    "execute_authorized_gate_action",
    "require_authorized_gate_action",
]
