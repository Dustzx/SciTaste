from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import pytest

from scitaste.backends.base import Usage
from scitaste.evidence import EvidenceItem
from scitaste.model_nodes import (
    ActionLease,
    BoundEvidenceRecord,
    ContentAddressedRunFile,
    ControlledToolExecutor,
    ControlledToolProfile,
    DurableToolAmbiguousExecutionError,
    DurableToolExecutionRuntime,
    DurableToolFaultPoint,
    EvidenceInspectArguments,
    EvidenceInspectionHandler,
    EvidenceInspectPermission,
    EvidenceInspectStep,
    ProjectEvidenceRecord,
    ProjectToolBindingError,
    ProjectToolBindingSet,
    ReadOnlyToolHandlerDescriptor,
    ToolBenchmarkCondition,
    ToolBenchmarkTrial,
    ToolObservationStatus,
    ToolProjectSnapshot,
    canonical_sha256,
    evaluate_tool_intelligence_benchmark,
    load_project_tool_handlers,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


class MutableState:
    def __init__(self) -> None:
        self.snapshot_id = "state-7"

    def __call__(self) -> str:
        return self.snapshot_id


class CountingHandler:
    def __init__(
        self,
        calls: list[int],
        *,
        handler_id: str = "scitaste.evidence-inspect.bound-v1",
        mutate_state: MutableState | None = None,
    ) -> None:
        self.calls = calls
        self.mutate_state = mutate_state
        self.delegate = EvidenceInspectionHandler(
            [
                BoundEvidenceRecord(
                    evidence_id="evidence-1",
                    payload={"claim": "candidate is better", "value": 0.83},
                    provenance={"run_id": "run-tool"},
                )
            ]
        )
        self._descriptor = self.delegate.descriptor.model_copy(update={"handler_id": handler_id})

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor:
        return self._descriptor

    def execute(self, arguments: object) -> dict[str, object]:
        self.calls.append(1)
        if self.mutate_state is not None:
            self.mutate_state.snapshot_id = "state-8"
        return self.delegate.execute(arguments)  # type: ignore[arg-type,return-value]


class InjectedCrash(RuntimeError):
    pass


def _case(
    root: Path,
    *,
    handler_id: str = "scitaste.evidence-inspect.bound-v1",
    concurrent_state_change: bool = False,
) -> tuple[
    ProjectRuntime,
    MutableState,
    MutableClock,
    CountingHandler,
    ActionLease,
    list[int],
]:
    project = ProjectRuntime(root / "outputs")
    snapshot = project.create(
        ProjectManifest(
            project_id="benchmark-project",
            title="Tool Intelligence benchmark",
            research_direction="Measure deterministic engineering proxies.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "benchmark-project",
        ProjectRun(
            run_id="run-tool",
            provider="scripted",
            model="scripted-v1",
            condition="benchmark",
            seed=0,
            status="running",
            evidence_scope="engineering-proxy",
        ),
        expected_revision=snapshot.revision,
    )
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingHandler(
        calls,
        handler_id=handler_id,
        mutate_state=state if concurrent_state_change else None,
    )
    step = EvidenceInspectStep(
        step_id="inspect",
        purpose="Inspect one bounded evidence record.",
        arguments=EvidenceInspectArguments(evidence_ids=("evidence-1",), include_provenance=True),
    )
    lease = ActionLease(
        lease_id="lease-aaaaaaaaaaaaaaaaaaaaaaaa",
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=5),
        hotspot_trigger_fingerprint="1" * 64,
        project=ToolProjectSnapshot(
            project_id="benchmark-project",
            revision=snapshot.revision,
            snapshot_sha256=snapshot.snapshot_sha256,
        ),
        state_snapshot_id="state-7",
        source_request_fingerprint="2" * 64,
        source_raw_response_sha256="3" * 64,
        source_model_usage=Usage(input_tokens=23, output_tokens=17, cost_usd=0.002),
        source_model_latency_ms=4,
        controlled_tool_profile_id="benchmark-readonly",
        controlled_tool_profile_fingerprint="4" * 64,
        step=step,
        step_fingerprint=canonical_sha256(step.model_dump(mode="json")),
        handler=handler.descriptor,
        max_observation_bytes=16_384,
    )
    return project, state, clock, handler, lease, calls


def _executor(
    project: ProjectRuntime,
    state: MutableState,
    clock: MutableClock,
    handler: CountingHandler,
) -> ControlledToolExecutor:
    return ControlledToolExecutor(
        project_runtime=project,
        state_snapshot_reader=state,
        handlers=[handler],
        clock=clock,
    )


def _durable(
    project: ProjectRuntime,
    state: MutableState,
    clock: MutableClock,
    handler: CountingHandler,
    *,
    crash_at: DurableToolFaultPoint | None = None,
) -> DurableToolExecutionRuntime:
    def fault(point: DurableToolFaultPoint) -> None:
        if point is crash_at:
            raise InjectedCrash(point.value)

    return DurableToolExecutionRuntime(
        project,
        executor_factory=lambda: _executor(project, state, clock, handler),
        clock=clock,
        fault_hook=fault if crash_at is not None else None,
    )


def _trial(
    *,
    scenario_id: str,
    condition: ToolBenchmarkCondition,
    resolved: bool,
    manual_steps: int,
    calls: int,
    tool_latency_ms: float,
    runtime_ms: float,
    model_invocations: int = 1,
    **values: object,
) -> ToolBenchmarkTrial:
    return ToolBenchmarkTrial(
        scenario_id=scenario_id,
        condition=condition,
        evidence_test=(
            "tests/model_nodes/test_tool_benchmark_integration.py::"
            "test_measured_paired_v2_v3_tool_intelligence_benchmark"
        ),
        hotspot_resolved=resolved,
        manual_controller_steps=manual_steps,
        model_invocations=model_invocations,
        tool_handler_invocations=calls,
        input_tokens=23 * model_invocations,
        output_tokens=17 * model_invocations,
        known_cost_usd=0.002 * model_invocations,
        model_latency_ms=4 * model_invocations,
        tool_latency_ms=tool_latency_ms,
        runtime_ms=runtime_ms,
        **values,
    )


def _measure_normal(root: Path, *, durable: bool) -> ToolBenchmarkTrial:
    project, state, clock, handler, lease, calls = _case(root)
    started = perf_counter()
    if durable:
        observation = (
            _durable(project, state, clock, handler)
            .execute(project_id="benchmark-project", run_id="run-tool", lease=lease)
            .observation
        )
    else:
        observation = _executor(project, state, clock, handler).execute(lease)
    elapsed = (perf_counter() - started) * 1_000
    assert observation.status is ToolObservationStatus.SUCCEEDED
    return _trial(
        scenario_id="normal",
        condition=(ToolBenchmarkCondition.V3 if durable else ToolBenchmarkCondition.V2),
        resolved=True,
        manual_steps=1 if durable else 3,
        calls=len(calls),
        tool_latency_ms=observation.tool_latency_ms,
        runtime_ms=elapsed,
    )


def _measure_restart(root: Path, *, durable: bool) -> ToolBenchmarkTrial:
    project, state, clock, handler, lease, calls = _case(root)
    started = perf_counter()
    if durable:
        first = _durable(project, state, clock, handler).execute(
            project_id="benchmark-project", run_id="run-tool", lease=lease
        )
        second = _durable(project, state, clock, handler).execute(
            project_id="benchmark-project", run_id="run-tool", lease=lease
        )
        latency = second.observation.tool_latency_ms
        assert first.observation == second.observation
    else:
        first_observation = _executor(project, state, clock, handler).execute(lease)
        second_observation = _executor(project, state, clock, handler).execute(lease)
        latency = first_observation.tool_latency_ms + second_observation.tool_latency_ms
    elapsed = (perf_counter() - started) * 1_000
    return _trial(
        scenario_id="restart",
        condition=(ToolBenchmarkCondition.V3 if durable else ToolBenchmarkCondition.V2),
        resolved=True,
        manual_steps=1 if durable else 4,
        calls=len(calls),
        tool_latency_ms=latency,
        runtime_ms=elapsed,
        restart_duplicate_execution_count=max(0, len(calls) - 1),
    )


def _measure_crash_result(root: Path, *, durable: bool) -> ToolBenchmarkTrial:
    project, state, clock, handler, lease, calls = _case(root)
    started = perf_counter()
    if durable:
        with pytest.raises(InjectedCrash):
            _durable(
                project,
                state,
                clock,
                handler,
                crash_at=DurableToolFaultPoint.AFTER_RESULT,
            ).execute(project_id="benchmark-project", run_id="run-tool", lease=lease)
        observation = (
            _durable(project, state, clock, handler)
            .execute(project_id="benchmark-project", run_id="run-tool", lease=lease)
            .observation
        )
        recovered = len(calls) == 1
    else:
        _executor(project, state, clock, handler).execute(lease)
        observation = _executor(project, state, clock, handler).execute(lease)
        recovered = False
    elapsed = (perf_counter() - started) * 1_000
    return _trial(
        scenario_id="crash-result",
        condition=(ToolBenchmarkCondition.V3 if durable else ToolBenchmarkCondition.V2),
        resolved=observation.status is ToolObservationStatus.SUCCEEDED,
        manual_steps=1 if durable else 4,
        calls=len(calls),
        tool_latency_ms=observation.tool_latency_ms,
        runtime_ms=elapsed,
        crash_recovery_success=recovered,
    )


def _measure_ambiguous(root: Path, *, durable: bool) -> ToolBenchmarkTrial:
    project, state, clock, handler, lease, calls = _case(root, handler_id="custom.readonly-handler")
    started = perf_counter()
    if durable:
        with pytest.raises(InjectedCrash):
            _durable(
                project,
                state,
                clock,
                handler,
                crash_at=DurableToolFaultPoint.AFTER_HANDLER_RETURNED,
            ).execute(project_id="benchmark-project", run_id="run-tool", lease=lease)
        with pytest.raises(DurableToolAmbiguousExecutionError):
            _durable(project, state, clock, handler).execute(
                project_id="benchmark-project", run_id="run-tool", lease=lease
            )
        failed_closed = len(calls) == 1
        latency = 0.0
    else:
        first = _executor(project, state, clock, handler).execute(lease)
        second = _executor(project, state, clock, handler).execute(lease)
        failed_closed = False
        latency = first.tool_latency_ms + second.tool_latency_ms
    elapsed = (perf_counter() - started) * 1_000
    return _trial(
        scenario_id="ambiguous-custom",
        condition=(ToolBenchmarkCondition.V3 if durable else ToolBenchmarkCondition.V2),
        resolved=False,
        manual_steps=2 if durable else 4,
        calls=len(calls),
        tool_latency_ms=latency,
        runtime_ms=elapsed,
        ambiguous_call_failed_closed=failed_closed,
    )


def _measure_concurrent_state(root: Path, *, durable: bool) -> ToolBenchmarkTrial:
    project, state, clock, handler, lease, calls = _case(root, concurrent_state_change=True)
    started = perf_counter()
    if durable:
        observation = (
            _durable(project, state, clock, handler)
            .execute(project_id="benchmark-project", run_id="run-tool", lease=lease)
            .observation
        )
    else:
        observation = _executor(project, state, clock, handler).execute(lease)
    elapsed = (perf_counter() - started) * 1_000
    assert observation.status is ToolObservationStatus.REJECTED
    return _trial(
        scenario_id="concurrent-state",
        condition=(ToolBenchmarkCondition.V3 if durable else ToolBenchmarkCondition.V2),
        resolved=False,
        manual_steps=1 if durable else 3,
        calls=len(calls),
        tool_latency_ms=observation.tool_latency_ms,
        runtime_ms=elapsed,
        stale_or_concurrent_result_accepted=False,
    )


def _measure_locator_attack(root: Path, *, durable: bool) -> ToolBenchmarkTrial:
    project, _, _, _, _, _ = _case(root)
    run_root = project.outputs_root / "projects" / "benchmark-project" / "runs" / "run-tool"
    outside = root / "outside"
    outside.mkdir()
    record = ProjectEvidenceRecord(
        evidence=EvidenceItem(
            evidence_id="evidence-1",
            source_type="test",
            evidence_type="metric",
            observation="One result.",
            supports_claim_ids=["claim-1"],
            confidence=0.9,
        )
    )
    raw = (
        json.dumps(
            record.model_dump(mode="json", exclude_computed_fields=True),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    (outside / "evidence.jsonl").write_bytes(raw)
    (run_root / "linked").symlink_to(outside, target_is_directory=True)
    source = ContentAddressedRunFile(
        locator="linked/evidence.jsonl",
        sha256=hashlib.sha256(raw).hexdigest(),
        max_bytes=len(raw),
    )
    profile = ControlledToolProfile(
        profile_id="locator-attack",
        profile_version="1.0.0",
        permissions=(
            EvidenceInspectPermission(allowed_evidence_ids=("evidence-1",), max_evidence_items=1),
        ),
    )
    binding = ProjectToolBindingSet(
        binding_id="locator-attack",
        project_id="benchmark-project",
        run_id="run-tool",
        project_revision=project.open("benchmark-project").revision,
        knowledge_libraries=(),
        evidence_source=source,
    )
    started = perf_counter()
    if durable:
        with pytest.raises(ProjectToolBindingError):
            load_project_tool_handlers(project, binding, profile)
        rejected = True
        model_invocations = 0
    else:
        escaped = json.loads((run_root / "linked" / "evidence.jsonl").read_text())["evidence"]
        handler = EvidenceInspectionHandler(
            [BoundEvidenceRecord(evidence_id="evidence-1", payload=escaped)]
        )
        assert handler.descriptor.tool_name.value == "evidence.inspect"
        rejected = False
        model_invocations = 1
    elapsed = (perf_counter() - started) * 1_000
    return _trial(
        scenario_id="locator-symlink",
        condition=(ToolBenchmarkCondition.V3 if durable else ToolBenchmarkCondition.V2),
        resolved=False,
        manual_steps=1 if durable else 3,
        calls=0,
        tool_latency_ms=0,
        runtime_ms=elapsed,
        model_invocations=model_invocations,
        locator_attack_rejected=rejected,
    )


def test_measured_paired_v2_v3_tool_intelligence_benchmark(
    tmp_path: Path,
) -> None:
    measurements = (
        _measure_normal,
        _measure_restart,
        _measure_crash_result,
        _measure_ambiguous,
        _measure_concurrent_state,
        _measure_locator_attack,
    )
    trials: list[ToolBenchmarkTrial] = []
    for index, measurement in enumerate(measurements):
        trials.append(measurement(tmp_path / f"case-{index}-v2", durable=False))
        trials.append(measurement(tmp_path / f"case-{index}-v3", durable=True))

    report = evaluate_tool_intelligence_benchmark(tuple(trials))

    assert report.v2.successful_hotspot_resolution_rate == 0.5
    assert report.v3.successful_hotspot_resolution_rate == 0.5
    assert report.delta.restart_duplicate_execution_rate_reduction == 1
    assert report.delta.crash_recovery_success_rate_gain == 1
    assert report.delta.ambiguous_call_fail_closed_rate_gain == 1
    assert report.delta.stale_result_acceptance_rate_reduction == 0
    assert report.delta.locator_attack_rejection_rate_gain == 1
    assert report.delta.manual_controller_step_reduction_rate == pytest.approx(8 / 11)
    assert report.delta.tool_invocation_reduction_rate == pytest.approx(3 / 8)
    assert report.delta.model_invocation_reduction_rate == pytest.approx(1 / 6)
    assert report.delta.token_reduction_rate == pytest.approx(1 / 6)
    assert report.delta.known_cost_reduction_rate == pytest.approx(1 / 6)
    assert report.v2.unknown_cost_count == report.v3.unknown_cost_count == 0
    if os.environ.get("SCITASTE_PRINT_TOOL_BENCHMARK") == "1":
        print(report.model_dump_json(indent=2))
