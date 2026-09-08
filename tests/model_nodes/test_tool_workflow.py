from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    BoundEvidenceRecord,
    ControlledToolExecutor,
    ControlledToolProfile,
    CumulativeProjectBudget,
    DeterministicSemanticHotspotSignal,
    DurableToolExecutionRuntime,
    DurableToolFaultPoint,
    EvidenceInspectionHandler,
    EvidenceInspectPermission,
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
    ModelNodeProfile,
    ModelNodeRuntime,
    ModelNodeTrigger,
    NodeAdmissionBudget,
    NodePolicy,
    ProjectToolIntelligenceBridge,
    ProviderGenerationEnvelope,
    ReadOnlyToolHandlerDescriptor,
    RuntimeBackendMode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    SemanticGapKind,
    SemanticHotspotDetector,
    SemanticHotspotKind,
    SemanticHotspotTrigger,
    ToolHotspotDecision,
    ToolHotspotWorkflowBudget,
    ToolHotspotWorkflowRequest,
    ToolPlanInput,
    ToolScopeProjection,
    canonical_sha256,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

PROJECT_ID = "tool-workflow-project"
RUN_ID = "run-tool"


class MutableState:
    def __init__(self) -> None:
        self.snapshot_id = "state-7"

    def __call__(self) -> str:
        return self.snapshot_id


class CountingEvidenceHandler:
    def __init__(self, calls: list[int], *, state: MutableState | None = None) -> None:
        self.calls = calls
        self.state = state
        self.delegate = EvidenceInspectionHandler(
            [
                BoundEvidenceRecord(
                    evidence_id="evidence-1",
                    payload={"claim": "candidate is better", "value": 0.83},
                    provenance={"run_id": "run-candidate"},
                )
            ]
        )

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor:
        return self.delegate.descriptor

    def execute(self, arguments: object) -> dict[str, object]:
        self.calls.append(1)
        if self.state is not None:
            self.state.snapshot_id = "state-8"
        return self.delegate.execute(arguments)  # type: ignore[arg-type,return-value]


class InjectedCrash(RuntimeError):
    pass


def _project(tmp_path: Path) -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Tool workflow project",
            research_direction="Test the durable hotspot bridge.",
            status="active",
        )
    )
    for run_id in ("run-base", "run-candidate", RUN_ID):
        snapshot = runtime.begin_run(
            PROJECT_ID,
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model="deterministic",
                condition="test",
                seed=7,
                status="running",
                evidence_scope="engineering-test",
            ),
            expected_revision=snapshot.revision,
        )
    return runtime, snapshot


def _controlled_profile() -> ControlledToolProfile:
    return ControlledToolProfile(
        profile_id="workflow-readonly",
        profile_version="1.0.0",
        permissions=(
            EvidenceInspectPermission(allowed_evidence_ids=("evidence-1",), max_evidence_items=1),
        ),
        max_plan_steps=2,
        max_dependency_edges=0,
    )


def _model_profile() -> ModelNodeProfile:
    return ModelNodeProfile(
        profile_id="workflow-tool-plan",
        profile_version="1.0.0",
        provider="scripted",
        model="scripted-v1",
        allowed_node_names=("tool-plan",),
        live_execution_permitted=False,
        generation=ProviderGenerationEnvelope(
            max_request_bytes=100_000,
            max_output_tokens=512,
            context_window_tokens=32_768,
            deterministic_seed_supported=True,
        ),
        admission=NodeAdmissionBudget(
            max_request_bytes=100_000,
            max_input_tokens=2_000,
            max_output_tokens=512,
            max_total_tokens=2_512,
            max_latency_ms=30_000,
            max_response_cost_usd=0.05,
            allowed_tool_names=["evidence.inspect"],
            max_tool_call_proposals=0,
        ),
        cumulative_project=CumulativeProjectBudget(
            max_invocations=10,
            max_total_tokens=50_000,
            max_api_cost_usd=1,
        ),
    )


def _policy(profile: ModelNodeProfile) -> NodePolicy:
    return NodePolicy(
        policy_id="workflow-tool-policy",
        enabled=True,
        allowed_node_names=["tool-plan"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=["evidence.inspect"],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )


def _request(
    snapshot: object,
    *,
    budget: ToolHotspotWorkflowBudget | None = None,
    attempt_index: int = 0,
) -> ToolHotspotWorkflowRequest:
    controlled = _controlled_profile()
    objective = "Inspect project-owned evidence before selecting another action."
    node_input = ToolPlanInput(
        objective=objective,
        scope=ToolScopeProjection(
            project_id=PROJECT_ID,
            state_snapshot_id="state-7",
            evidence_ids=("evidence-1",),
        ),
        tool_profile=controlled,
    )
    profile = _model_profile()
    model_request = ModelNodeFacadeRequest(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        invocation_id="tool-plan-hotspot-1",
        request_id="tool-plan-hotspot-1",
        expected_project_revision=snapshot.revision,  # type: ignore[attr-defined]
        node_name="tool-plan",
        node_input=node_input.model_dump(mode="json"),
        state_projection=ImmutableStateProjection(
            project_id=PROJECT_ID,
            state_snapshot_id="state-7",
            state_revision=7,
            stage="EVIDENCE",
            evidence_ids=("evidence-1",),
        ),
        trigger=ModelNodeTrigger(
            trigger_id="hotspot-tool-plan",
            reason="A named semantic ambiguity exhausted the deterministic fast path.",
        ),
        profile=profile,
        policy=_policy(profile),
        backend_mode=RuntimeBackendMode.SCRIPTED,
        seed=11,
    )
    hotspot = SemanticHotspotTrigger(
        trigger_id="hotspot-1",
        hotspot_kind=SemanticHotspotKind.AMBIGUOUS_ACTION,
        semantic_gap=SemanticGapKind.COMPETING_INTERPRETATIONS,
        project_id=PROJECT_ID,
        project_revision=snapshot.revision,  # type: ignore[attr-defined]
        project_snapshot_sha256=snapshot.snapshot_sha256,  # type: ignore[attr-defined]
        state_snapshot_id="state-7",
        objective=objective,
        controlled_tool_profile_id=controlled.profile_id,
        controlled_tool_profile_fingerprint=controlled.fingerprint,
        candidate_tool_names=("evidence.inspect",),
        evidence_ids=("evidence-1",),
    )
    return ToolHotspotWorkflowRequest(
        workflow_id="hotspot-resolution-v1",
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        attempt_index=attempt_index,
        hotspot=hotspot,
        model_request=model_request,
        budget=budget or ToolHotspotWorkflowBudget(),
    )


def _backend(*, cost_usd: float = 0.01) -> ScriptedStructuredBackend:
    controlled = _controlled_profile()
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "tool-plan-hotspot-1": ScriptedStructuredReply(
                output_payload={
                    "tool_profile_id": controlled.profile_id,
                    "tool_profile_fingerprint": controlled.fingerprint,
                    "steps": [
                        {
                            "step_id": "inspect",
                            "depends_on": [],
                            "purpose": "Inspect one project-owned evidence record.",
                            "tool_name": "evidence.inspect",
                            "arguments": {
                                "evidence_ids": ["evidence-1"],
                                "include_provenance": True,
                            },
                        }
                    ],
                    "rationale": "One bounded read-only inspection is sufficient.",
                    "confidence": 0.9,
                },
                usage=Usage(input_tokens=12, output_tokens=8, cost_usd=cost_usd),
                latency_ms=5,
            )
        },
    )


def _tool_runtime(
    project: ProjectRuntime,
    state: MutableState,
    handler: CountingEvidenceHandler,
    *,
    crash_at: DurableToolFaultPoint | None = None,
) -> DurableToolExecutionRuntime:
    def factory() -> ControlledToolExecutor:
        return ControlledToolExecutor(
            project_runtime=project,
            state_snapshot_reader=state,
            handlers=[handler],
        )

    def fault(point: DurableToolFaultPoint) -> None:
        if point is crash_at:
            raise InjectedCrash(point.value)

    return DurableToolExecutionRuntime(
        project,
        executor_factory=factory,
        fault_hook=fault if crash_at is not None else None,
    )


def test_detector_constructs_a_hotspot_only_from_live_typed_authority(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = ImmutableStateProjection(
        project_id=PROJECT_ID,
        state_snapshot_id="state-7",
        state_revision=7,
        stage="EVIDENCE",
        evidence_ids=("evidence-1",),
    )
    signal = DeterministicSemanticHotspotSignal(
        signal_id="hotspot-1",
        hotspot_kind=SemanticHotspotKind.AMBIGUOUS_ACTION,
        semantic_gap=SemanticGapKind.COMPETING_INTERPRETATIONS,
        objective="Inspect project-owned evidence before selecting another action.",
        candidate_tool_names=("evidence.inspect",),
        evidence_ids=("evidence-1",),
        reason_codes=("matched-results-disagree",),
    )
    detector = SemanticHotspotDetector(project)

    hotspot = detector.detect(
        project_id=PROJECT_ID,
        state_projection=state,
        controlled_profile=_controlled_profile(),
        signal=signal,
    )

    assert hotspot.project_revision == snapshot.revision  # type: ignore[attr-defined]
    assert hotspot.state_snapshot_id == state.state_snapshot_id
    assert hotspot.deterministic_fast_path_exhausted is True

    escaped = signal.model_copy(update={"evidence_ids": ("evidence-unknown",)})
    with pytest.raises(ValueError, match="expands the typed evidence scope"):
        detector.detect(
            project_id=PROJECT_ID,
            state_projection=state,
            controlled_profile=_controlled_profile(),
            signal=escaped,
        )


def test_bridge_resolves_and_exactly_reuses_one_durable_advisory(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    tool_runtime = _tool_runtime(project, state, handler)
    bridge = ProjectToolIntelligenceBridge(ModelNodeFacade(ModelNodeRuntime(project)), tool_runtime)
    request = _request(snapshot)

    first = bridge.resolve(request, backend=_backend())
    second = bridge.resolve(request, backend=None)
    verification = tool_runtime.verify(project_id=PROJECT_ID, run_id=RUN_ID)

    assert first.record.decision is ToolHotspotDecision.ACCEPT_AS_ADVICE
    assert first.record.advice_payload is not None
    assert first.record.resolved is True
    assert first.record.manual_controller_steps_proxy == 1
    assert first.record.model_provider_invocation_count == 1
    assert first.record.tool_handler_invocation_count == 1
    assert second.record == first.record
    assert second.recovered is True
    assert len(calls) == 1
    assert verification.decision_count == 1


def test_bridge_rejects_over_budget_model_result_before_tool_admission(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    tool_runtime = _tool_runtime(project, state, handler)
    bridge = ProjectToolIntelligenceBridge(ModelNodeFacade(ModelNodeRuntime(project)), tool_runtime)
    budget = ToolHotspotWorkflowBudget(max_api_cost_usd=0.005)

    result = bridge.resolve(_request(snapshot, budget=budget), backend=_backend())
    model_verification = bridge.model_facade.verify(project_id=PROJECT_ID, run_id=RUN_ID)

    assert result.record.decision is ToolHotspotDecision.REJECT
    assert result.record.advice_payload is None
    assert "model cost budget exceeded" in result.record.reasons[0]
    assert calls == []
    assert model_verification.totals.cost_usd == 0.01


@pytest.mark.parametrize(
    ("attempt_index", "max_replans", "expected"),
    [
        (0, 1, ToolHotspotDecision.REPLAN_REQUIRED),
        (0, 0, ToolHotspotDecision.ESCALATE_TO_HUMAN),
    ],
)
def test_bridge_turns_concurrent_state_change_into_bounded_replan_or_escalation(
    tmp_path: Path,
    attempt_index: int,
    max_replans: int,
    expected: ToolHotspotDecision,
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls, state=state)
    bridge = ProjectToolIntelligenceBridge(
        ModelNodeFacade(ModelNodeRuntime(project)),
        _tool_runtime(project, state, handler),
    )
    budget = ToolHotspotWorkflowBudget(max_replans=max_replans)

    result = bridge.resolve(
        _request(snapshot, budget=budget, attempt_index=attempt_index),
        backend=_backend(),
    )

    assert result.record.decision is expected
    assert result.record.advice_payload is None
    assert result.record.manual_controller_steps_proxy == 1 + int(
        expected is ToolHotspotDecision.ESCALATE_TO_HUMAN
    )
    assert len(calls) == 1


def test_bridge_recovers_after_tool_ledger_publish_without_duplicate_execution(
    tmp_path: Path,
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    model_facade = ModelNodeFacade(ModelNodeRuntime(project))
    crashing = ProjectToolIntelligenceBridge(
        model_facade,
        _tool_runtime(
            project,
            state,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_LEDGER,
        ),
    )
    request = _request(snapshot)

    with pytest.raises(InjectedCrash):
        crashing.resolve(request, backend=_backend())
    resumed_runtime = _tool_runtime(project, state, handler)
    resumed = ProjectToolIntelligenceBridge(model_facade, resumed_runtime).resolve(
        request, backend=None
    )

    assert resumed.record.decision is ToolHotspotDecision.ACCEPT_AS_ADVICE
    assert len(calls) == 1
    assert resumed_runtime.verify(project_id=PROJECT_ID, run_id=RUN_ID).pending_attempt_count == 0


def test_typed_decision_tampering_is_rejected_even_with_recomputed_envelope_hash(
    tmp_path: Path,
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    tool_runtime = _tool_runtime(project, state, handler)
    bridge = ProjectToolIntelligenceBridge(ModelNodeFacade(ModelNodeRuntime(project)), tool_runtime)
    result = bridge.resolve(_request(snapshot), backend=_backend())
    decision_path = project.outputs_root / result.decision_locator
    envelope = json.loads(decision_path.read_text(encoding="utf-8"))
    envelope["payload"]["resolved"] = False
    envelope["payload_sha256"] = canonical_sha256(envelope["payload"])
    envelope["envelope_sha256"] = canonical_sha256(
        {key: value for key, value in envelope.items() if key != "envelope_sha256"}
    )
    decision_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="workflow decision payload"):
        tool_runtime.verify(project_id=PROJECT_ID, run_id=RUN_ID)
