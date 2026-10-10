import json

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.pending_observation import wait_for_terminal


def test_pending_wait_keeps_same_job_and_transient_failure(tmp_path):
    now = [0]
    calls = []
    pending = ExecutionResult(
        action_id="reserved", executor="remote", status=ExecutionStatus.PLANNED
    )
    terminal = pending.model_copy(
        update={"status": ExecutionStatus.SUCCEEDED, "cost": {"experiments": 1}}
    )

    def observe():
        calls.append(now[0])
        if len(calls) == 1:
            raise TimeoutError("transient observation failure")
        return terminal if len(calls) == 3 else pending

    def sleep(seconds):
        now[0] += seconds

    result = wait_for_terminal(
        pending,
        observe=observe,
        output=tmp_path / "wait.jsonl",
        max_seconds=180,
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert result.status == ExecutionStatus.SUCCEEDED
    assert calls == [45, 90, 135]
    assert result.cost == {"experiments": 1}
    records = [json.loads(line) for line in (tmp_path / "wait.jsonl").read_text().splitlines()]
    assert all(row["automatic_relaunch"] is False for row in records)
    still_pending = wait_for_terminal(
        pending,
        observe=lambda: pending,
        output=tmp_path / "timeout.jsonl",
        max_seconds=60,
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert still_pending.status == ExecutionStatus.PLANNED
