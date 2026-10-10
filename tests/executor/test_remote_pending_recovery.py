import json
from types import SimpleNamespace

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.remote_workspace_recovery import reconcile_pending_remote
from scitaste.state.research_state import ResourceUsage


def test_pending_recovery_observes_without_launching_and_preserves_parent(tmp_path, monkeypatch):
    import scitaste.executor.remote_workspace_recovery as module

    parent, output = tmp_path / "parent", tmp_path / "child"
    for path in (parent / "workspace", parent / "remote_jobs", output):
        path.mkdir(parents=True)
    (parent / "workspace/source.py").write_text("original source")
    raw = ExecutionResult(
        action_id="original-remote-job",
        status=ExecutionStatus.SUCCEEDED,
        executor="remote",
        cost={"experiments": 1, "gpu_hours": 0.2, "wall_time_hours": 0.1},
        data={"cost_complete": True},
    )

    class Observer:
        def __init__(self, **kwargs):
            assert kwargs["resume"] is True

        def call(self, arguments, **kwargs):
            assert kwargs["observation_only"] is True
            return raw.model_dump(mode="json")

    monkeypatch.setattr(module, "RunRemoteWorkspace", Observer)
    pending = ExecutionResult(
        action_id="selected",
        status=ExecutionStatus.PLANNED,
        executor="remote",
        data={"source_execution_action_id": "original-remote-job"},
    )
    row = {
        "selected": {
            "action_id": "selected",
            "parameters": {
                "tool": "Run Remote",
                "arguments": {},
                "tool_interface_sha256": "interface",
            },
        },
        "result": pending.model_dump(mode="json"),
    }
    state = SimpleNamespace(
        decision_history=[SimpleNamespace(actual_outcome=None)],
        resource_usage=ResourceUsage(),
        observations=[],
        revision=1,
    )
    recovery, receipt = reconcile_pending_remote(
        parent=parent,
        output=output,
        state=state,
        history=[row],
        plan={
            "remote_workspace": {
                "resource": {
                    "host": "assigned-host",
                    "python": "/usr/bin/python3",
                    "gpu_indices": [3, 4],
                    "max_jobs": 1,
                    "wall_seconds": 60,
                }
            }
        },
    )
    assert row["result"]["action_id"] == "selected"
    assert state.resource_usage.experiments == 1
    assert state.resource_usage.gpu_hours == 0.2
    assert receipt["relaunch_performed"] is False
    assert json.loads((recovery / "RECONCILIATION.json").read_text()) == receipt
    assert (parent / "workspace/source.py").read_text() == "original source"
