from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    ActionLease,
    BoundEvidenceRecord,
    ControlledToolExecutor,
    DurableToolAmbiguousExecutionError,
    DurableToolExecutionRuntime,
    DurableToolFaultPoint,
    DurableToolRuntimeConflictError,
    DurableToolRuntimeError,
    EvidenceInspectArguments,
    EvidenceInspectionHandler,
    EvidenceInspectStep,
    ReadOnlyToolHandlerDescriptor,
    ToolObservationStatus,
    ToolProjectSnapshot,
    canonical_sha256,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class MutableState:
    def __init__(self) -> None:
        self.snapshot_id = "state-7"

    def __call__(self) -> str:
        return self.snapshot_id


class CountingEvidenceHandler:
    def __init__(
        self,
        calls: list[int],
        *,
        handler_id: str = "scitaste.evidence-inspect.bound-v1",
        on_execute: object | None = None,
    ) -> None:
        self.calls = calls
        self.on_execute = on_execute
        delegate = EvidenceInspectionHandler(
            [
                BoundEvidenceRecord(
                    evidence_id="evidence-1",
                    payload={"claim": "candidate is better", "value": 0.83},
                    provenance={"run_id": "run-tool"},
                )
            ]
        )
        self.delegate = delegate
        self._descriptor = delegate.descriptor.model_copy(update={"handler_id": handler_id})

    @property
    def descriptor(self) -> ReadOnlyToolHandlerDescriptor:
        return self._descriptor

    def execute(self, arguments: object) -> dict[str, object]:
        self.calls.append(1)
        if callable(self.on_execute):
            self.on_execute()
        return self.delegate.execute(arguments)  # type: ignore[arg-type,return-value]


class InjectedCrash(RuntimeError):
    pass


def _project(tmp_path: Path) -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="tool-project",
            title="Tool project",
            research_direction="Test durable bounded tools.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        "tool-project",
        ProjectRun(
            run_id="run-tool",
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


def _lease(snapshot: object, handler: CountingEvidenceHandler, clock: MutableClock) -> ActionLease:
    project_snapshot = ToolProjectSnapshot(
        project_id="tool-project",
        revision=snapshot.revision,  # type: ignore[attr-defined]
        snapshot_sha256=snapshot.snapshot_sha256,  # type: ignore[attr-defined]
    )
    step = EvidenceInspectStep(
        step_id="step-evidence-inspect",
        purpose="Resolve one bounded uncertainty.",
        arguments=EvidenceInspectArguments(evidence_ids=("evidence-1",), include_provenance=True),
    )
    return ActionLease(
        lease_id="lease-aaaaaaaaaaaaaaaaaaaaaaaa",
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=5),
        hotspot_trigger_fingerprint="1" * 64,
        project=project_snapshot,
        state_snapshot_id="state-7",
        source_request_fingerprint="2" * 64,
        source_raw_response_sha256="3" * 64,
        source_model_usage=Usage(input_tokens=23, output_tokens=17, cost_usd=0.002),
        source_model_latency_ms=4,
        controlled_tool_profile_id="readonly-single-step",
        controlled_tool_profile_fingerprint="4" * 64,
        step=step,
        step_fingerprint=canonical_sha256(step.model_dump(mode="json")),
        handler=handler.descriptor,
        max_observation_bytes=16_384,
    )


def _runtime(
    project: ProjectRuntime,
    state: MutableState,
    clock: MutableClock,
    handler: CountingEvidenceHandler,
    *,
    crash_at: DurableToolFaultPoint | None = None,
) -> DurableToolExecutionRuntime:
    def executor_factory() -> ControlledToolExecutor:
        return ControlledToolExecutor(
            project_runtime=project,
            state_snapshot_reader=state,
            handlers=[handler],
            clock=clock,
        )

    def fault_hook(point: DurableToolFaultPoint) -> None:
        if point is crash_at:
            raise InjectedCrash(point.value)

    return DurableToolExecutionRuntime(
        project,
        executor_factory=executor_factory,
        clock=clock,
        fault_hook=fault_hook if crash_at is not None else None,
    )


def test_durable_execution_is_exactly_reused_after_restart(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    first = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )
    second = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )
    verification = _runtime(project, state, clock, handler).verify(
        project_id="tool-project", run_id="run-tool"
    )

    assert first.observation.status is ToolObservationStatus.SUCCEEDED
    assert first.recovered_without_handler is False
    assert second.observation == first.observation
    assert second.recovered_without_handler is True
    assert len(calls) == 1
    assert verification.lease_count == 1
    assert verification.observation_count == 1
    assert verification.ledger_entry_count == 1
    assert verification.archived_attempt_count == 1
    assert verification.pending_attempt_count == 0
    assert verification.handler_invocation_count == 1
    assert verification.input_tokens == 23
    assert verification.output_tokens == 17
    assert verification.known_cost_usd == 0.002
    assert verification.unknown_cost_count == 0


@pytest.mark.parametrize(
    "crash_at",
    [DurableToolFaultPoint.AFTER_CLAIM, DurableToolFaultPoint.AFTER_HANDLER_STARTED],
)
def test_first_party_handler_recovers_incomplete_claim(
    tmp_path: Path, crash_at: DurableToolFaultPoint
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(project, state, clock, handler, crash_at=crash_at).execute(
            project_id="tool-project", run_id="run-tool", lease=lease
        )

    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )

    assert receipt.observation.status is ToolObservationStatus.SUCCEEDED
    assert len(calls) == 1


def test_completed_pending_result_recovers_without_duplicate_handler_call(
    tmp_path: Path,
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_RESULT,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)

    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )

    assert len(calls) == 1
    assert receipt.recovered_without_handler is True
    assert receipt.observation.status is ToolObservationStatus.SUCCEEDED


def test_first_party_handler_return_without_result_is_safely_replayed(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_HANDLER_RETURNED,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)
    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )

    assert receipt.observation.status is ToolObservationStatus.SUCCEEDED
    assert receipt.recovered_without_handler is False
    assert len(calls) == 2


def test_published_observation_recovers_ledger_without_duplicate_call(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_OBSERVATION,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)

    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )

    assert len(calls) == 1
    assert receipt.recovered_without_handler is True
    assert receipt.ledger_index == 0


def test_published_ledger_recovers_pending_cleanup_without_duplicate_call(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_LEDGER,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)
    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )
    verification = _runtime(project, state, clock, handler).verify(
        project_id="tool-project", run_id="run-tool"
    )

    assert len(calls) == 1
    assert receipt.recovered_without_handler is True
    assert verification.pending_attempt_count == 0
    assert verification.archived_attempt_count == 1


def test_unsafe_handler_interruption_is_persistently_ambiguous(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls, handler_id="custom.readonly-handler")
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_HANDLER_RETURNED,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)
    with pytest.raises(DurableToolAmbiguousExecutionError):
        _runtime(project, state, clock, handler).execute(
            project_id="tool-project", run_id="run-tool", lease=lease
        )
    with pytest.raises(DurableToolAmbiguousExecutionError):
        _runtime(project, state, clock, handler).execute(
            project_id="tool-project", run_id="run-tool", lease=lease
        )

    verification = _runtime(project, state, clock, handler).verify(
        project_id="tool-project", run_id="run-tool"
    )
    assert len(calls) == 1
    assert verification.pending_attempt_count == 1
    assert verification.ambiguous_attempt_count == 1


def test_stale_project_rejection_retains_cost_without_invoking_handler(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)
    project.update("tool-project", expected_revision=snapshot.revision, status="changed")

    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )
    verification = _runtime(project, state, clock, handler).verify(
        project_id="tool-project", run_id="run-tool"
    )

    assert receipt.observation.status is ToolObservationStatus.REJECTED
    assert receipt.observation.handler_invoked is False
    assert "project changed before handler execution" in (receipt.observation.rejection_reasons)
    assert calls == []
    assert verification.known_cost_usd == 0.002
    assert verification.handler_invocation_count == 0


def test_concurrent_state_change_rejects_but_persists_returned_payload_and_cost(
    tmp_path: Path,
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []

    def mutate_state() -> None:
        state.snapshot_id = "state-8"

    handler = CountingEvidenceHandler(calls, on_execute=mutate_state)
    lease = _lease(snapshot, handler, clock)

    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )
    verification = _runtime(project, state, clock, handler).verify(
        project_id="tool-project", run_id="run-tool"
    )

    assert receipt.observation.status is ToolObservationStatus.REJECTED
    assert receipt.observation.output_payload is None
    assert receipt.observation.untrusted_output_payload is not None
    assert receipt.observation.handler_invoked is True
    assert verification.known_cost_usd == 0.002
    assert verification.handler_invocation_count == 1


def test_handler_identity_drift_is_recorded_as_a_rejected_observation(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    original_calls: list[int] = []
    original = CountingEvidenceHandler(original_calls)
    lease = _lease(snapshot, original, clock)
    drifted_calls: list[int] = []
    drifted = CountingEvidenceHandler(
        drifted_calls, handler_id="scitaste.evidence-inspect.changed-v1"
    )

    receipt = _runtime(project, state, clock, drifted).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )

    assert receipt.observation.status is ToolObservationStatus.REJECTED
    assert receipt.observation.handler_invoked is False
    assert "registered handler identity changed" in (receipt.observation.rejection_reasons[0])
    assert original_calls == drifted_calls == []


def test_cross_process_lock_fails_closed_without_publishing_a_claim(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)
    stage = (
        project.outputs_root
        / "projects"
        / "tool-project"
        / "runs"
        / "run-tool"
        / "tool_intelligence"
    )
    stage.mkdir()
    lock_path = stage / ".runtime.lock"

    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DurableToolRuntimeConflictError):
            _runtime(project, state, clock, handler).execute(
                project_id="tool-project", run_id="run-tool", lease=lease
            )

    assert calls == []
    assert not (stage / "pending").exists()


def test_nested_symlink_and_ledger_tampering_are_detected(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)
    runtime = _runtime(project, state, clock, handler)
    runtime.execute(project_id="tool-project", run_id="run-tool", lease=lease)
    stage = (
        project.outputs_root
        / "projects"
        / "tool-project"
        / "runs"
        / "run-tool"
        / "tool_intelligence"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (stage / "pending" / "escaped").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DurableToolRuntimeError, match="unsafe entry"):
        runtime.verify(project_id="tool-project", run_id="run-tool")

    (stage / "pending" / "escaped").unlink()
    ledger_path = next((stage / "ledger").glob("*.json"))
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    payload["tool_latency_ms"] = payload["tool_latency_ms"] + 1
    ledger_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DurableToolRuntimeError, match="invalid durable evidence"):
        runtime.verify(project_id="tool-project", run_id="run-tool")


def test_duplicate_lease_identifier_with_changed_content_fails_closed(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)
    runtime = _runtime(project, state, clock, handler)
    runtime.execute(project_id="tool-project", run_id="run-tool", lease=lease)
    drifted = lease.model_copy(update={"max_observation_bytes": 8_192})

    with pytest.raises(DurableToolRuntimeError, match="lease identity drift"):
        runtime.execute(project_id="tool-project", run_id="run-tool", lease=drifted)

    assert len(calls) == 1


def test_interrupted_lease_publication_is_visible_and_recoverable(tmp_path: Path) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)

    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_LEASE,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)
    before = _runtime(project, state, clock, handler).verify(
        project_id="tool-project", run_id="run-tool"
    )
    receipt = _runtime(project, state, clock, handler).execute(
        project_id="tool-project", run_id="run-tool", lease=lease
    )

    assert before.incomplete_lease_count == 1
    assert receipt.observation.status is ToolObservationStatus.SUCCEEDED
    assert len(calls) == 1


def test_interrupted_pending_result_publication_is_detected_before_replay(
    tmp_path: Path,
) -> None:
    project, snapshot = _project(tmp_path)
    state = MutableState()
    clock = MutableClock()
    calls: list[int] = []
    handler = CountingEvidenceHandler(calls)
    lease = _lease(snapshot, handler, clock)
    with pytest.raises(InjectedCrash):
        _runtime(
            project,
            state,
            clock,
            handler,
            crash_at=DurableToolFaultPoint.AFTER_HANDLER_STARTED,
        ).execute(project_id="tool-project", run_id="run-tool", lease=lease)
    pending = (
        project.outputs_root
        / "projects"
        / "tool-project"
        / "runs"
        / "run-tool"
        / "tool_intelligence"
        / "pending"
        / lease.lease_id
    )
    (pending / ".result.json.interrupted.tmp").write_text("partial", encoding="utf-8")

    with pytest.raises(DurableToolRuntimeError, match="interrupted publication"):
        _runtime(project, state, clock, handler).execute(
            project_id="tool-project", run_id="run-tool", lease=lease
        )

    assert calls == []
