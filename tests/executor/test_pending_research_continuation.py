import json
from types import SimpleNamespace

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.research_continuation import restore_terminal_research
from scitaste.state.research_state import ResourceUsage


def test_recovery_attaches_existing_outcome_without_relaunch(tmp_path, monkeypatch):
    import scitaste.executor.research_continuation as module

    parent, output = tmp_path / "parent", tmp_path / "child"
    for path in (
        parent / "candidate",
        parent / "tools/experiments/attempt-001",
        parent / "logs/provider_calls",
        parent / "loop",
        output,
    ):
        path.mkdir(parents=True)
    (parent / "CONTRACT.json").write_text('{"task": "fixed"}')
    (parent / "RESULT.json").write_text('{"status": "execution-unresolved"}')
    selected = {
        "action_id": "selected",
        "parameters": {"tool": "Run Experiment", "tool_interface_sha256": "interface"},
    }
    pending = ExecutionResult(
        action_id="selected",
        executor="remote",
        status=ExecutionStatus.PLANNED,
        data={"source_execution_action_id": "parent-attempt-001"},
    )
    row = {"selected": selected, "result": pending.model_dump(mode="json")}
    original = json.dumps(row) + "\n"
    (parent / "loop/TRAJECTORY.jsonl").write_text(original)
    decision = SimpleNamespace(
        selected_action=SimpleNamespace(model_dump=lambda **kwargs: selected),
        actual_outcome=None,
        executor_result_id=None,
    )
    state = SimpleNamespace(
        decision_history=[decision], resource_usage=ResourceUsage(), observations=[], revision=1
    )
    monkeypatch.setattr(module, "StateStore", lambda *args: SimpleNamespace(load=lambda: state))
    monkeypatch.setattr(
        module,
        "provider_ledger_accounting",
        lambda *args: {"unresolved_reservations": 0, "calls": 2},
    )
    measured = ExecutionResult(
        action_id="parent-attempt-001",
        executor="remote",
        status=ExecutionStatus.SUCCEEDED,
        cost={"experiments": 1, "gpu_hours": 0.1, "wall_time_hours": 0.1},
        data={"cost_complete": True},
    )
    calls = []

    def observe(attempt):
        calls.append(attempt)
        return measured.model_dump(mode="json")

    restored, history, lineage = restore_terminal_research(
        parent,
        output,
        expected={"task": "fixed"},
        pending_observer=observe,
    )
    assert calls == ["attempt-001"]
    assert restored.resource_usage.experiments == 1
    assert restored.resource_usage.gpu_hours == 0.1
    assert history[-1]["result"]["action_id"] == "selected"
    assert lineage["pending_reconciliation"]["relaunch_performed"] is False
    assert (parent / "loop/TRAJECTORY.jsonl").read_text() == original
    assert not (parent / "tools/experiments/attempt-001/RESULT.json").exists()
    assert (output / "tools/experiments/attempt-001/RESULT.json").is_file()
