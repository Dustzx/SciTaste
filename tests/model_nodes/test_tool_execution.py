from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.data.models import KnowledgeDocument, ProvenanceRecord
from scitaste.model_nodes import (
    BoundEvidenceRecord,
    ControlledToolExecutor,
    ControlledToolProfile,
    EvidenceInspectionHandler,
    EvidenceInspectPermission,
    KnowledgeQueryHandler,
    KnowledgeQueryPermission,
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    RegisteredRunComparePermission,
    RegisteredRunComparisonHandler,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    SemanticGapKind,
    SemanticHotspotKind,
    SemanticHotspotTrigger,
    ToolCallProposal,
    ToolLeaseAdmissionError,
    ToolObservationStatus,
    ToolPlanInput,
    ToolPlanNode,
    ToolScopeProjection,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class MutableState:
    def __init__(self, snapshot_id: str = "state-7") -> None:
        self.snapshot_id = snapshot_id

    def __call__(self) -> str:
        return self.snapshot_id


def _project(tmp_path: Path) -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="tool-project",
            title="Tool project",
            research_direction="Test bounded semantic tools.",
            status="active",
        )
    )
    for run_id in ("run-base", "run-candidate"):
        snapshot = runtime.begin_run(
            "tool-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model="deterministic",
                condition="test",
                seed=7,
                status="complete",
                evidence_scope="engineering-test",
            ),
            expected_revision=snapshot.revision,
        )
    return runtime, snapshot


def _profile(tool_name: str) -> ControlledToolProfile:
    if tool_name == "knowledge.query":
        permission = KnowledgeQueryPermission(
            allowed_library_ids=("knowledge-main",),
            max_library_ids=1,
            max_query_chars=200,
            max_top_k=5,
        )
    elif tool_name == "evidence.inspect":
        permission = EvidenceInspectPermission(
            allowed_evidence_ids=("evidence-1", "evidence-2"),
            max_evidence_items=2,
        )
    else:
        permission = RegisteredRunComparePermission(
            allowed_run_ids=("run-base", "run-candidate"),
            allowed_metric_names=("accuracy",),
            max_runs=2,
            max_metrics=1,
        )
    return ControlledToolProfile(
        profile_id="readonly-single-step",
        profile_version="1.0.0",
        permissions=(permission,),
        max_plan_steps=2,
        max_dependency_edges=1,
    )


def _step(
    tool_name: str,
    *,
    depends_on: list[str] | None = None,
    step_id: str | None = None,
) -> dict[str, object]:
    if tool_name == "knowledge.query":
        arguments: dict[str, object] = {
            "query": "matched evidence methods",
            "library_ids": ["knowledge-main"],
            "top_k": 2,
        }
    elif tool_name == "evidence.inspect":
        arguments = {
            "evidence_ids": ["evidence-1", "evidence-2"],
            "include_provenance": True,
        }
    else:
        arguments = {
            "run_ids": ["run-base", "run-candidate"],
            "metric_names": ["accuracy"],
        }
    return {
        "step_id": step_id or f"step-{tool_name.replace('.', '-')}",
        "depends_on": depends_on or [],
        "purpose": "Resolve one bounded semantic uncertainty.",
        "tool_name": tool_name,
        "arguments": arguments,
    }


def _accepted_result(
    tool_name: str,
    *,
    extra_steps: list[dict[str, object]] | None = None,
) -> tuple[object, ToolPlanInput, ControlledToolProfile]:
    profile = _profile(tool_name)
    node_input = ToolPlanInput(
        objective="Resolve one semantic hotspot with project-owned data.",
        scope=ToolScopeProjection(
            project_id="tool-project",
            state_snapshot_id="state-7",
            library_ids=("knowledge-main",),
            evidence_ids=("evidence-1", "evidence-2"),
            run_ids=("run-base", "run-candidate"),
            metric_names=("accuracy",),
        ),
        tool_profile=profile,
    )
    steps = [_step(tool_name), *(extra_steps or [])]
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "tool-request": ScriptedStructuredReply(
                output_payload={
                    "tool_profile_id": profile.profile_id,
                    "tool_profile_fingerprint": profile.fingerprint,
                    "steps": steps,
                    "rationale": "One read-only observation can resolve the hotspot.",
                    "confidence": 0.8,
                },
                latency_ms=4,
                usage=Usage(input_tokens=23, output_tokens=17, cost_usd=0.002),
            )
        },
    )
    result = ToolPlanNode().run(
        node_input,
        context=NodeContext(
            project_id="tool-project",
            stage="EVIDENCE",
            state_snapshot_id="state-7",
            cumulative_api_cost_usd=0,
            evidence_ids=["evidence-1", "evidence-2"],
        ),
        backend=backend,
        policy=NodePolicy(
            policy_id="tool-policy",
            enabled=True,
            allowed_node_names=["tool-plan"],
            expected_backend="scripted",
            expected_model="scripted-v1",
            allowed_tool_names=[tool_name],
            max_input_tokens=200,
            max_output_tokens=200,
            max_total_tokens=400,
            max_api_cost_usd=0.1,
            max_latency_ms=1_000,
        ),
        request_id="tool-request",
    )
    assert result.proposal is not None
    return result, node_input, profile


def _hotspot(snapshot, profile: ControlledToolProfile, tool_name: str) -> SemanticHotspotTrigger:
    return SemanticHotspotTrigger(
        trigger_id="hotspot-1",
        hotspot_kind=SemanticHotspotKind.AMBIGUOUS_ACTION,
        semantic_gap=SemanticGapKind.COMPETING_INTERPRETATIONS,
        project_id="tool-project",
        project_revision=snapshot.revision,
        project_snapshot_sha256=snapshot.snapshot_sha256,
        state_snapshot_id="state-7",
        objective="Resolve one semantic hotspot with project-owned data.",
        controlled_tool_profile_id=profile.profile_id,
        controlled_tool_profile_fingerprint=profile.fingerprint,
        candidate_tool_names=(tool_name,),
        evidence_ids=("evidence-1", "evidence-2"),
    )


def _evidence_handler() -> EvidenceInspectionHandler:
    return EvidenceInspectionHandler(
        [
            BoundEvidenceRecord(
                evidence_id="evidence-1",
                payload={"claim": "candidate is better", "value": 0.83},
                provenance={"run_id": "run-candidate"},
            ),
            BoundEvidenceRecord(
                evidence_id="evidence-2",
                payload={"claim": "baseline result", "value": 0.79},
                provenance={"run_id": "run-base"},
            ),
        ]
    )


def test_semantic_hotspot_executes_one_real_bounded_evidence_inspection(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[_evidence_handler()],
    )
    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
    )

    observation = executor.execute(lease)

    assert observation.status is ToolObservationStatus.SUCCEEDED
    assert observation.output_payload is not None
    assert len(observation.output_payload["items"]) == 2
    assert observation.source_model_usage.cost_usd == 0.002
    assert observation.canonical_evidence is False
    assert observation.executable is False
    assert observation.project_revision_before == snapshot.revision
    assert observation.project_revision_after == snapshot.revision


def test_builtin_knowledge_and_run_handlers_execute_deterministically(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    provenance = ProvenanceRecord(source_type="test", locator="memory://paper")
    knowledge = KnowledgeQueryHandler(
        {
            "knowledge-main": [
                KnowledgeDocument(
                    document_id="doc-method",
                    title="Matched evidence methods",
                    content="matched evidence methods and controlled comparisons",
                    provenance=[provenance],
                ),
                KnowledgeDocument(
                    document_id="doc-other",
                    title="Unrelated note",
                    content="unrelated material",
                    provenance=[provenance],
                ),
            ]
        }
    )
    comparison = RegisteredRunComparisonHandler(
        {
            "run-base": {"accuracy": 0.79},
            "run-candidate": {"accuracy": 0.83},
        }
    )
    for tool_name, handler, expected_key in (
        ("knowledge.query", knowledge, "items"),
        ("registered-run.compare", comparison, "rows"),
    ):
        result, _, profile = _accepted_result(tool_name)
        executor = ControlledToolExecutor(
            project_runtime=runtime,
            state_snapshot_reader=state,
            handlers=[handler],
        )
        lease = executor.issue_lease(
            result,
            hotspot=_hotspot(snapshot, profile, tool_name),
            step_id=f"step-{tool_name.replace('.', '-')}",
        )
        observation = executor.execute(lease)
        assert observation.status is ToolObservationStatus.SUCCEEDED
        assert observation.output_payload is not None
        assert observation.output_payload[expected_key]


def test_rejected_result_and_dependent_step_never_gain_a_lease(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    result, _, profile = _accepted_result(
        "evidence.inspect",
        extra_steps=[
            _step(
                "evidence.inspect",
                depends_on=["step-evidence-inspect"],
                step_id="dependent-inspection",
            )
        ],
    )
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=MutableState(),
        handlers=[_evidence_handler()],
    )
    rejected = result.model_copy(
        update={
            "status": NodeResultStatus.REJECTED,
            "proposal": None,
            "untrusted_proposal": result.proposal,
            "rejection_reasons": ["test rejection"],
        }
    )
    with pytest.raises(ToolLeaseAdmissionError, match="accepted tool-plan"):
        executor.issue_lease(
            rejected,
            hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
            step_id="step-evidence-inspect",
        )

    with pytest.raises(ToolLeaseAdmissionError, match="dependency-free"):
        executor.issue_lease(
            result,
            hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
            step_id="dependent-inspection",
        )


def test_provider_native_tool_call_cannot_be_leased(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    result, _, profile = _accepted_result("evidence.inspect")
    response = result.response.model_copy(
        update={
            "tool_calls": [
                ToolCallProposal(name="evidence.inspect", arguments={"evidence_ids": []})
            ]
        }
    )
    tampered = result.model_copy(update={"response": response})
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=MutableState(),
        handlers=[_evidence_handler()],
    )

    with pytest.raises(ToolLeaseAdmissionError, match="provider-native"):
        executor.issue_lease(
            tampered,
            hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
            step_id="step-evidence-inspect",
        )


def test_proposal_or_lease_tampering_fails_at_a_deterministic_boundary(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    result, _, profile = _accepted_result("evidence.inspect")
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=MutableState(),
        handlers=[_evidence_handler()],
    )
    tampered_proposal = result.proposal.model_copy(update={"rationale": "tampered"})
    tampered_result = result.model_copy(update={"proposal": tampered_proposal})
    with pytest.raises(ToolLeaseAdmissionError, match="differs from its source response"):
        executor.issue_lease(
            tampered_result,
            hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
            step_id="step-evidence-inspect",
        )

    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
    )
    tampered_lease = lease.model_copy(update={"step_fingerprint": "0" * 64})
    with pytest.raises(ToolLeaseAdmissionError, match="action lease fails"):
        executor.execute(tampered_lease)


def test_project_or_state_drift_blocks_lease_admission(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[_evidence_handler()],
    )
    runtime.update(
        "tool-project",
        expected_revision=snapshot.revision,
        status="updated",
    )
    with pytest.raises(ToolLeaseAdmissionError, match="project changed"):
        executor.issue_lease(
            result,
            hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
            step_id="step-evidence-inspect",
        )

    current = runtime.open("tool-project")
    state.snapshot_id = "state-8"
    with pytest.raises(ToolLeaseAdmissionError, match="research state changed"):
        executor.issue_lease(
            result,
            hotspot=_hotspot(current, profile, "evidence.inspect"),
            step_id="step-evidence-inspect",
        )


def test_stale_pre_call_revision_rejects_without_invoking_handler(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")

    class CountingHandler:
        def __init__(self) -> None:
            self.delegate = _evidence_handler()
            self.calls = 0

        @property
        def descriptor(self):
            return self.delegate.descriptor

        def execute(self, arguments):
            self.calls += 1
            return self.delegate.execute(arguments)

    handler = CountingHandler()
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[handler],
    )
    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
    )
    runtime.update(
        "tool-project",
        expected_revision=snapshot.revision,
        status="changed-before-call",
    )

    observation = executor.execute(lease)

    assert observation.status is ToolObservationStatus.REJECTED
    assert handler.calls == 0
    assert "project changed before handler execution" in observation.rejection_reasons


def test_concurrent_project_change_preserves_output_and_model_cost_as_untrusted(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")
    delegate = _evidence_handler()

    class ConcurrentChangeHandler:
        descriptor = delegate.descriptor

        def execute(self, arguments):
            output = delegate.execute(arguments)
            runtime.update(
                "tool-project",
                expected_revision=snapshot.revision,
                status="changed-during-call",
            )
            return output

    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[ConcurrentChangeHandler()],
    )
    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
    )

    observation = executor.execute(lease)

    assert observation.status is ToolObservationStatus.REJECTED
    assert observation.output_payload is None
    assert observation.untrusted_output_payload is not None
    assert observation.output_sha256 is not None
    assert observation.source_model_usage.cost_usd == 0.002
    assert observation.project_revision_before == snapshot.revision
    assert observation.project_revision_after == snapshot.revision + 1
    assert "project changed during handler execution" in observation.rejection_reasons


def test_concurrent_state_change_rejects_the_returned_observation(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")
    delegate = _evidence_handler()

    class ConcurrentStateHandler:
        descriptor = delegate.descriptor

        def execute(self, arguments):
            output = delegate.execute(arguments)
            state.snapshot_id = "state-8"
            return output

    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[ConcurrentStateHandler()],
    )
    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
    )

    observation = executor.execute(lease)

    assert observation.status is ToolObservationStatus.REJECTED
    assert observation.untrusted_output_payload is not None
    assert observation.state_snapshot_id_before == "state-7"
    assert observation.state_snapshot_id_after == "state-8"
    assert "research state changed during handler execution" in observation.rejection_reasons


def test_lease_expiry_reuse_and_handler_drift_fail_closed(tmp_path: Path) -> None:
    runtime, snapshot = _project(tmp_path)
    clock = MutableClock()
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")
    handler = _evidence_handler()
    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[handler],
        clock=clock,
    )
    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
        ttl_seconds=1,
    )
    clock.advance(2)
    expired = executor.execute(lease)
    reused = executor.execute(lease)
    assert expired.status is ToolObservationStatus.REJECTED
    assert expired.rejection_reasons == ("action lease expired before handler execution",)
    assert reused.rejection_reasons == ("action lease was already consumed",)

    class MutableDescriptorHandler:
        def __init__(self) -> None:
            self.delegate = _evidence_handler()
            self.current = self.delegate.descriptor

        @property
        def descriptor(self):
            return self.current

        def execute(self, arguments):
            return self.delegate.execute(arguments)

    mutable = MutableDescriptorHandler()
    fresh_executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[mutable],
        clock=clock,
    )
    fresh_lease = fresh_executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
    )
    mutable.current = mutable.current.model_copy(update={"handler_version": "1.0.1"})
    drifted = fresh_executor.execute(fresh_lease)
    assert drifted.status is ToolObservationStatus.REJECTED
    assert "handler identity changed" in drifted.rejection_reasons[0]


@pytest.mark.parametrize("mode", ["exception", "non-json", "oversized"])
def test_handler_failure_and_invalid_output_are_non_authoritative(
    tmp_path: Path,
    mode: str,
) -> None:
    runtime, snapshot = _project(tmp_path)
    state = MutableState()
    result, _, profile = _accepted_result("evidence.inspect")
    descriptor = _evidence_handler().descriptor

    class InvalidHandler:
        @property
        def descriptor(self):
            return descriptor

        def execute(self, arguments):
            if mode == "exception":
                raise RuntimeError("provider detail must not enter the receipt")
            if mode == "non-json":
                return {"bad": object()}
            return {"large": "x" * 1_000}

    executor = ControlledToolExecutor(
        project_runtime=runtime,
        state_snapshot_reader=state,
        handlers=[InvalidHandler()],
    )
    lease = executor.issue_lease(
        result,
        hotspot=_hotspot(snapshot, profile, "evidence.inspect"),
        step_id="step-evidence-inspect",
        max_observation_bytes=100 if mode == "oversized" else None,
    )
    observation = executor.execute(lease)

    if mode == "oversized":
        assert observation.status is ToolObservationStatus.REJECTED
        assert observation.untrusted_output_payload is None
        assert observation.output_sha256 is not None
    else:
        assert observation.status is ToolObservationStatus.FAILED
        assert observation.failure_type in {"RuntimeError", "ValidationError"}
    assert observation.output_payload is None
    assert observation.canonical_evidence is False
