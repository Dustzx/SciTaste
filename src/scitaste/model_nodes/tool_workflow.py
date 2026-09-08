"""Deterministic project bridge from one semantic hotspot to one tool decision."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.runtime import (
    RuntimeInvocationReceipt,
    RuntimeInvocationTelemetry,
    RuntimeOutcome,
)
from scitaste.model_nodes.tool_execution import (
    ControlledToolExecutor,
    SemanticGapKind,
    SemanticHotspotKind,
    SemanticHotspotTrigger,
    ToolLeaseAdmissionError,
    ToolObservationStatus,
)
from scitaste.model_nodes.tool_execution_runtime import (
    TOOL_INTELLIGENCE_STAGE_PATH,
    DurableToolDecisionEnvelope,
    DurableToolExecutionReceipt,
    DurableToolExecutionRuntime,
)
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolName,
    ControlledToolProfile,
    ToolPlanInput,
    ToolPlanOutput,
    canonical_sha256,
)
from scitaste.project.runtime import ProjectRuntime


class ToolHotspotWorkflowError(ValueError):
    """Raised when the deterministic workflow integration contract is invalid."""


class ToolHotspotWorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolHotspotDecision(StrEnum):
    ACCEPT_AS_ADVICE = "accept-as-advice"
    REJECT = "reject"
    ESCALATE_TO_HUMAN = "escalate-to-human"
    REPLAN_REQUIRED = "replan-required"


class ToolHotspotWorkflowBudget(ToolHotspotWorkflowModel):
    """Hard per-hotspot envelope; cumulative model budgets remain authoritative."""

    schema_version: Literal["1.0"] = "1.0"
    max_model_invocations: Literal[1] = 1
    max_tool_invocations: Literal[1] = 1
    max_replans: int = Field(default=1, ge=0, le=3)
    max_total_tokens: int = Field(default=4_096, ge=1, le=1_000_000)
    max_api_cost_usd: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    max_model_latency_ms: float = Field(default=120_000, ge=1, allow_inf_nan=False)
    max_tool_latency_ms: float = Field(default=30_000, ge=1, allow_inf_nan=False)
    max_end_to_end_latency_ms: float = Field(default=150_000, ge=1, allow_inf_nan=False)
    max_observation_bytes: int = Field(default=262_144, ge=1, le=1_000_000)
    action_lease_ttl_seconds: int = Field(default=60, ge=1, le=300)


class DeterministicSemanticHotspotSignal(ToolHotspotWorkflowModel):
    """Typed fast-path failure from which deterministic code constructs a hotspot."""

    schema_version: Literal["1.0"] = "1.0"
    signal_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    hotspot_kind: SemanticHotspotKind
    semantic_gap: SemanticGapKind
    objective: str = Field(min_length=1, max_length=4_000)
    candidate_tool_names: tuple[ControlledToolName, ...] = Field(min_length=1, max_length=3)
    evidence_ids: tuple[
        Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=128)],
        ...,
    ] = Field(default=(), max_length=256)
    reason_codes: tuple[
        Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=128)],
        ...,
    ] = Field(min_length=1, max_length=16)
    deterministic_fast_path_result: Literal["unresolved"] = "unresolved"

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> DeterministicSemanticHotspotSignal:
        for name in ("candidate_tool_names", "evidence_ids", "reason_codes"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        return self


class SemanticHotspotDetector:
    """Validate a typed fast-path failure against live project/state authority."""

    def __init__(self, project_runtime: ProjectRuntime) -> None:
        self.project_runtime = project_runtime

    def detect(
        self,
        *,
        project_id: str,
        state_projection: ImmutableStateProjection,
        controlled_profile: ControlledToolProfile,
        signal: DeterministicSemanticHotspotSignal,
    ) -> SemanticHotspotTrigger:
        try:
            state_projection = ImmutableStateProjection.model_validate_json(
                state_projection.model_dump_json(exclude_computed_fields=True), strict=True
            )
            controlled_profile = ControlledToolProfile.model_validate_json(
                controlled_profile.model_dump_json(exclude_computed_fields=True), strict=True
            )
            signal = DeterministicSemanticHotspotSignal.model_validate_json(
                signal.model_dump_json(exclude_computed_fields=True), strict=True
            )
        except ValueError as exc:
            raise ToolHotspotWorkflowError("invalid semantic-hotspot detector input") from exc
        if state_projection.project_id != project_id:
            raise ToolHotspotWorkflowError("state projection belongs to another project")
        if set(signal.evidence_ids) - set(state_projection.evidence_ids):
            raise ToolHotspotWorkflowError("hotspot signal expands the typed evidence scope")
        if set(item.value for item in signal.candidate_tool_names) - set(
            controlled_profile.allowed_tool_names
        ):
            raise ToolHotspotWorkflowError("hotspot signal exceeds the controlled tool profile")
        snapshot = self.project_runtime.open(project_id)
        return SemanticHotspotTrigger(
            trigger_id=signal.signal_id,
            hotspot_kind=signal.hotspot_kind,
            semantic_gap=signal.semantic_gap,
            project_id=project_id,
            project_revision=snapshot.revision,
            project_snapshot_sha256=snapshot.snapshot_sha256,
            state_snapshot_id=state_projection.state_snapshot_id,
            objective=signal.objective,
            controlled_tool_profile_id=controlled_profile.profile_id,
            controlled_tool_profile_fingerprint=controlled_profile.fingerprint,
            candidate_tool_names=signal.candidate_tool_names,
            reason_codes=signal.reason_codes,
            evidence_ids=signal.evidence_ids,
        )


class ToolHotspotWorkflowRequest(ToolHotspotWorkflowModel):
    """One bounded planning/execution attempt for an explicitly named hotspot."""

    schema_version: Literal["1.0"] = "1.0"
    workflow_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    project_id: str
    run_id: str
    attempt_index: int = Field(default=0, ge=0, le=3)
    hotspot: SemanticHotspotTrigger
    model_request: ModelNodeFacadeRequest
    budget: ToolHotspotWorkflowBudget = Field(default_factory=ToolHotspotWorkflowBudget)
    advisory_only: Literal[True] = True
    state_transition_authorized: Literal[False] = False

    @model_validator(mode="after")
    def contract_is_closed(self) -> ToolHotspotWorkflowRequest:
        if self.attempt_index > self.budget.max_replans:
            raise ValueError("workflow attempt exceeds its bounded re-plan horizon")
        if self.model_request.node_name != "tool-plan":
            raise ValueError("Tool Intelligence workflow requires a tool-plan model request")
        if (self.model_request.project_id, self.model_request.run_id) != (
            self.project_id,
            self.run_id,
        ):
            raise ValueError("model request belongs to another project run")
        if self.hotspot.project_id != self.project_id:
            raise ValueError("semantic hotspot belongs to another project")
        if self.model_request.expected_project_revision != self.hotspot.project_revision:
            raise ValueError("model request and semantic hotspot project revisions differ")
        projection = self.model_request.state_projection
        if projection.state_snapshot_id != self.hotspot.state_snapshot_id:
            raise ValueError("model request and semantic hotspot state snapshots differ")
        try:
            node_input = ToolPlanInput.model_validate_json(
                json.dumps(
                    self.model_request.node_input,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                strict=True,
            )
        except ValueError as exc:  # pragma: no cover - facade request already validates this
            raise ValueError("workflow tool-plan input cannot be reconstructed") from exc
        if node_input.objective != self.hotspot.objective:
            raise ValueError("tool-plan objective differs from the semantic hotspot")
        if node_input.scope.project_id != self.project_id or (
            node_input.scope.state_snapshot_id != self.hotspot.state_snapshot_id
        ):
            raise ValueError("tool-plan scope differs from the semantic hotspot")
        if node_input.tool_profile.profile_id != self.hotspot.controlled_tool_profile_id or (
            node_input.tool_profile.fingerprint != self.hotspot.controlled_tool_profile_fingerprint
        ):
            raise ValueError("tool-plan profile differs from the semantic hotspot")
        if set(self.hotspot.candidate_tool_names) - set(
            self.model_request.policy.allowed_tool_names
        ):
            raise ValueError("semantic hotspot tools exceed the model policy")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class ToolHotspotWorkflowDecisionRecord(ToolHotspotWorkflowModel):
    """Stable non-authoritative outcome of one durable hotspot resolution attempt."""

    schema_version: Literal["1.0"] = "1.0"
    decision_id: str = Field(pattern=r"^decision-[0-9a-f]{24}$")
    workflow_id: str
    workflow_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str
    run_id: str
    attempt_index: int = Field(ge=0, le=3)
    hotspot_trigger_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_invocation_id: str
    model_outcome: RuntimeOutcome
    model_ledger_entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_request_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model_input_tokens: int = Field(ge=0)
    model_output_tokens: int = Field(ge=0)
    model_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    model_provider_invocation_count: int = Field(ge=0, le=1)
    selected_step_id: str | None = None
    tool_lease_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tool_observation_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tool_ledger_entry_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tool_handler_invocation_count: int = Field(ge=0, le=1)
    tool_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    decision: ToolHotspotDecision
    reasons: tuple[str, ...] = ()
    advice_payload: dict[str, JsonValue] | None = None
    resolved: bool
    manual_controller_steps_proxy: int = Field(ge=1, le=2)
    advisory_only: Literal[True] = True
    canonical_evidence: Literal[False] = False
    state_transition_authorized: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> ToolHotspotWorkflowDecisionRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls.model_validate(
            {
                **payload,
                "record_sha256": canonical_sha256(
                    unsigned.model_dump(mode="json", exclude={"record_sha256"})
                ),
            }
        )

    @model_validator(mode="after")
    def decision_is_coherent(self) -> ToolHotspotWorkflowDecisionRecord:
        tool_fields = (
            self.selected_step_id,
            self.tool_lease_fingerprint,
            self.tool_observation_fingerprint,
            self.tool_ledger_entry_sha256,
        )
        if any(value is not None for value in tool_fields) != all(
            value is not None for value in tool_fields
        ):
            raise ValueError("tool workflow evidence must be present as a complete group")
        if self.decision is ToolHotspotDecision.ACCEPT_AS_ADVICE:
            if self.advice_payload is None or not self.resolved:
                raise ValueError("accepted advice requires one resolved payload")
        elif self.advice_payload is not None or self.resolved:
            raise ValueError("only accepted advice can resolve a hotspot")
        if self.decision is not ToolHotspotDecision.ACCEPT_AS_ADVICE and not self.reasons:
            raise ValueError("non-accepted hotspot decisions require reasons")
        has_tool_evidence = all(value is not None for value in tool_fields)
        if self.decision is ToolHotspotDecision.ACCEPT_AS_ADVICE and not has_tool_evidence:
            raise ValueError("accepted advice requires complete durable tool evidence")
        if not has_tool_evidence and (
            self.tool_handler_invocation_count != 0 or self.tool_latency_ms != 0
        ):
            raise ValueError("tool telemetry requires complete durable tool evidence")
        expected_controller_steps = 1 + int(self.decision is ToolHotspotDecision.ESCALATE_TO_HUMAN)
        if self.manual_controller_steps_proxy != expected_controller_steps:
            raise ValueError("manual-controller proxy must track bridge and human steps")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("hotspot workflow decision hash drift")
        return self


class ToolHotspotWorkflowResult(ToolHotspotWorkflowModel):
    record: ToolHotspotWorkflowDecisionRecord
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_locator: str
    recovered: bool = False
    advisory_only: Literal[True] = True
    state_transition_authorized: Literal[False] = False


class ProjectToolIntelligenceBridge:
    """Resolve one typed hotspot while deterministic code retains final authority."""

    def __init__(
        self,
        model_facade: ModelNodeFacade,
        tool_runtime: DurableToolExecutionRuntime,
    ) -> None:
        self.model_facade = model_facade
        self.tool_runtime = tool_runtime

    def resolve(
        self,
        request: ToolHotspotWorkflowRequest,
        *,
        backend: StructuredModelBackend | None,
        allow_live: bool = False,
    ) -> ToolHotspotWorkflowResult:
        """Invoke/reuse one Tool Plan, execute/reuse one step, and decide."""

        request = self._roundtrip_request(request)
        decision_id = f"decision-{request.fingerprint[:24]}"
        existing = self.tool_runtime.load_decision(
            project_id=request.project_id,
            run_id=request.run_id,
            decision_id=decision_id,
        )
        if existing is not None:
            record = self._record_from_envelope(existing, request)
            return self._result(record, existing, recovered=True)

        facade_result = self.model_facade.execute(
            request.model_request,
            backend=backend,
            resume=True,
            allow_live=allow_live,
        )
        receipt = facade_result.receipt
        model_budget_reasons = _model_budget_reasons(request.budget, receipt.telemetry)
        node_result = cast(NodeResult[ToolPlanOutput] | None, facade_result.result)
        if (
            receipt.outcome is not RuntimeOutcome.ACCEPTED
            or node_result is None
            or node_result.status is not NodeResultStatus.ACCEPTED
            or node_result.proposal is None
        ):
            reasons = tuple(
                dict.fromkeys(
                    [
                        *model_budget_reasons,
                        *receipt.blockers,
                        *(node_result.rejection_reasons if node_result is not None else ()),
                        "Tool Plan was not accepted",
                    ]
                )
            )
            decision = (
                ToolHotspotDecision.REJECT
                if model_budget_reasons
                else _bounded_failure_decision(request, permit_replan=True)
            )
            return self._publish(
                request,
                decision_id,
                receipt,
                decision=decision,
                reasons=reasons,
            )
        if model_budget_reasons:
            return self._publish(
                request,
                decision_id,
                receipt,
                decision=ToolHotspotDecision.REJECT,
                reasons=model_budget_reasons,
            )

        eligible = sorted(
            (
                step
                for step in node_result.proposal.steps
                if not step.depends_on and step.tool_name in request.hotspot.candidate_tool_names
            ),
            key=lambda step: step.step_id,
        )
        if not eligible:
            reasons = ("accepted Tool Plan contains no eligible dependency-free step",)
            return self._publish(
                request,
                decision_id,
                receipt,
                decision=_bounded_failure_decision(request, permit_replan=True),
                reasons=reasons,
            )
        step = eligible[0]
        step_fingerprint = canonical_sha256(step.model_dump(mode="json"))
        lease = self.tool_runtime.find_lease(
            project_id=request.project_id,
            run_id=request.run_id,
            source_request_fingerprint=node_result.request.fingerprint,
            hotspot_trigger_fingerprint=request.hotspot.fingerprint,
            step_fingerprint=step_fingerprint,
        )
        if lease is None:
            executor = self.tool_runtime.executor_factory()
            if not isinstance(executor, ControlledToolExecutor):
                raise ToolHotspotWorkflowError(
                    "tool runtime executor factory returned an invalid executor"
                )
            try:
                lease = executor.issue_lease(
                    node_result,
                    hotspot=request.hotspot,
                    step_id=step.step_id,
                    ttl_seconds=request.budget.action_lease_ttl_seconds,
                    max_observation_bytes=request.budget.max_observation_bytes,
                )
            except ToolLeaseAdmissionError:
                reasons = ("Tool Plan failed deterministic action-lease admission",)
                return self._publish(
                    request,
                    decision_id,
                    receipt,
                    decision=ToolHotspotDecision.ESCALATE_TO_HUMAN,
                    reasons=reasons,
                )
        tool_receipt = self.tool_runtime.execute(
            project_id=request.project_id,
            run_id=request.run_id,
            lease=lease,
        )
        decision, reasons, advice = _decide_observation(request, tool_receipt)
        return self._publish(
            request,
            decision_id,
            receipt,
            decision=decision,
            reasons=reasons,
            tool_receipt=tool_receipt,
            selected_step_id=step.step_id,
            advice_payload=advice,
        )

    def _publish(
        self,
        request: ToolHotspotWorkflowRequest,
        decision_id: str,
        model_receipt: RuntimeInvocationReceipt,
        *,
        decision: ToolHotspotDecision,
        reasons: tuple[str, ...],
        tool_receipt: DurableToolExecutionReceipt | None = None,
        selected_step_id: str | None = None,
        advice_payload: dict[str, JsonValue] | None = None,
    ) -> ToolHotspotWorkflowResult:
        telemetry = model_receipt.telemetry
        record = ToolHotspotWorkflowDecisionRecord.create(
            decision_id=decision_id,
            workflow_id=request.workflow_id,
            workflow_request_fingerprint=request.fingerprint,
            project_id=request.project_id,
            run_id=request.run_id,
            attempt_index=request.attempt_index,
            hotspot_trigger_fingerprint=request.hotspot.fingerprint,
            model_invocation_id=request.model_request.invocation_id,
            model_outcome=model_receipt.outcome,
            model_ledger_entry_sha256=model_receipt.entry_sha256,
            model_request_fingerprint=model_receipt.request_fingerprint,
            model_input_tokens=telemetry.input_tokens,
            model_output_tokens=telemetry.output_tokens,
            model_cost_usd=telemetry.cost_usd,
            model_latency_ms=telemetry.latency_ms,
            model_provider_invocation_count=int(
                model_receipt.request_fingerprint is not None
                and not telemetry.cached
                and not telemetry.replayed
            ),
            selected_step_id=selected_step_id,
            tool_lease_fingerprint=(
                tool_receipt.lease_fingerprint if tool_receipt is not None else None
            ),
            tool_observation_fingerprint=(
                tool_receipt.observation.fingerprint if tool_receipt is not None else None
            ),
            tool_ledger_entry_sha256=(
                tool_receipt.ledger_entry_sha256 if tool_receipt is not None else None
            ),
            tool_handler_invocation_count=(
                int(tool_receipt.observation.handler_invoked) if tool_receipt is not None else 0
            ),
            tool_latency_ms=(
                tool_receipt.observation.tool_latency_ms if tool_receipt is not None else 0.0
            ),
            decision=decision,
            reasons=reasons,
            advice_payload=advice_payload,
            resolved=decision is ToolHotspotDecision.ACCEPT_AS_ADVICE,
            manual_controller_steps_proxy=1
            + int(decision is ToolHotspotDecision.ESCALATE_TO_HUMAN),
        )
        envelope = self.tool_runtime.publish_decision(
            project_id=request.project_id,
            run_id=request.run_id,
            decision_id=decision_id,
            payload=record.model_dump(mode="json", exclude_computed_fields=True),
        )
        return self._result(record, envelope, recovered=False)

    @staticmethod
    def _roundtrip_request(
        request: ToolHotspotWorkflowRequest,
    ) -> ToolHotspotWorkflowRequest:
        try:
            return ToolHotspotWorkflowRequest.model_validate_json(
                request.model_dump_json(exclude_computed_fields=True), strict=True
            )
        except ValueError as exc:
            raise ToolHotspotWorkflowError("invalid Tool Intelligence workflow request") from exc

    @staticmethod
    def _record_from_envelope(
        envelope: DurableToolDecisionEnvelope,
        request: ToolHotspotWorkflowRequest,
    ) -> ToolHotspotWorkflowDecisionRecord:
        try:
            record = ToolHotspotWorkflowDecisionRecord.model_validate_json(
                json.dumps(envelope.payload, ensure_ascii=False, allow_nan=False),
                strict=True,
            )
        except ValueError as exc:
            raise ToolHotspotWorkflowError("invalid durable hotspot decision") from exc
        if record.workflow_request_fingerprint != request.fingerprint:
            raise ToolHotspotWorkflowError("durable hotspot decision request drift")
        return record

    @staticmethod
    def _result(
        record: ToolHotspotWorkflowDecisionRecord,
        envelope: DurableToolDecisionEnvelope,
        *,
        recovered: bool,
    ) -> ToolHotspotWorkflowResult:
        locator = (
            f"projects/{record.project_id}/runs/{record.run_id}/"
            f"{TOOL_INTELLIGENCE_STAGE_PATH}/decisions/{record.decision_id}.json"
        )
        return ToolHotspotWorkflowResult(
            record=record,
            envelope_sha256=envelope.envelope_sha256,
            decision_locator=locator,
            recovered=recovered,
        )


def _model_budget_reasons(
    budget: ToolHotspotWorkflowBudget,
    telemetry: RuntimeInvocationTelemetry,
) -> tuple[str, ...]:
    reasons: list[str] = []
    total_tokens = telemetry.input_tokens + telemetry.output_tokens
    if total_tokens > budget.max_total_tokens:
        reasons.append("Tool Intelligence model token budget exceeded")
    if telemetry.cost_usd is None:
        reasons.append("Tool Intelligence model cost is unknown")
    elif telemetry.cost_usd > budget.max_api_cost_usd:
        reasons.append("Tool Intelligence model cost budget exceeded")
    if telemetry.latency_ms > budget.max_model_latency_ms:
        reasons.append("Tool Intelligence model latency budget exceeded")
    return tuple(reasons)


def _bounded_failure_decision(
    request: ToolHotspotWorkflowRequest,
    *,
    permit_replan: bool,
) -> ToolHotspotDecision:
    if permit_replan and request.attempt_index < request.budget.max_replans:
        return ToolHotspotDecision.REPLAN_REQUIRED
    return ToolHotspotDecision.ESCALATE_TO_HUMAN


def _decide_observation(
    request: ToolHotspotWorkflowRequest,
    receipt: DurableToolExecutionReceipt,
) -> tuple[ToolHotspotDecision, tuple[str, ...], dict[str, JsonValue] | None]:
    observation = receipt.observation
    latency_reasons: list[str] = []
    if observation.tool_latency_ms > request.budget.max_tool_latency_ms:
        latency_reasons.append("Tool Intelligence tool latency budget exceeded")
    if (
        observation.source_model_latency_ms + observation.tool_latency_ms
        > request.budget.max_end_to_end_latency_ms
    ):
        latency_reasons.append("Tool Intelligence end-to-end latency budget exceeded")
    if latency_reasons:
        return ToolHotspotDecision.REJECT, tuple(latency_reasons), None
    if observation.status is ToolObservationStatus.SUCCEEDED:
        return ToolHotspotDecision.ACCEPT_AS_ADVICE, (), observation.output_payload
    reasons = observation.rejection_reasons or ("bounded tool handler failed",)
    recoverable_drift = any(
        "project changed" in reason
        or "research state changed" in reason
        or "lease expired" in reason
        for reason in reasons
    )
    if recoverable_drift and request.attempt_index < request.budget.max_replans:
        return ToolHotspotDecision.REPLAN_REQUIRED, tuple(reasons), None
    if observation.status is ToolObservationStatus.FAILED or recoverable_drift:
        return ToolHotspotDecision.ESCALATE_TO_HUMAN, tuple(reasons), None
    return ToolHotspotDecision.REJECT, tuple(reasons), None


__all__ = [
    "DeterministicSemanticHotspotSignal",
    "ProjectToolIntelligenceBridge",
    "SemanticHotspotDetector",
    "ToolHotspotDecision",
    "ToolHotspotWorkflowBudget",
    "ToolHotspotWorkflowDecisionRecord",
    "ToolHotspotWorkflowError",
    "ToolHotspotWorkflowRequest",
    "ToolHotspotWorkflowResult",
]
