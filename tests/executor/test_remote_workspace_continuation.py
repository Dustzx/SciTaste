import hashlib
import json
from types import SimpleNamespace

from scitaste.executor.workspace_continuation import restore_workspace


def test_completed_remote_ledger_is_inherited(tmp_path, monkeypatch):
    import scitaste.executor.workspace_continuation as module

    parent, child = tmp_path / "parent", tmp_path / "child"
    for path in (parent / "workspace", parent / "logs/provider_calls", parent / "loop", child):
        path.mkdir(parents=True)
    (parent / "CONTRACT.json").write_text(
        json.dumps(
            {
                "plan_sha256": "plan",
                "max_turns": 10,
                "plan": {
                    "remote_workspace": {"resource": {}},
                    "resource_envelope": {"wall_seconds": 300},
                },
            }
        )
    )
    (parent / "RESULT.json").write_text(
        json.dumps(
            {
                "status": "native-workspace-interrupted",
                "duration_seconds": 30,
            }
        )
    )
    result = {
        "result_id": "remote-result",
        "status": "SUCCEEDED",
        "cost": {"experiments": 1, "gpu_hours": 0},
        "data": {"cost_complete": True},
    }
    selected = {"parameters": {"tool": "Run Remote"}}
    (parent / "loop/TRAJECTORY.jsonl").write_text(
        json.dumps(
            {
                "selected": selected,
                "result": result,
            }
        )
        + "\n"
    )
    decision = SimpleNamespace(
        selected_action=SimpleNamespace(model_dump=lambda **kw: selected), actual_outcome=result
    )
    state = SimpleNamespace(decision_history=[decision], executor_context={})
    monkeypatch.setattr(module, "StateStore", lambda *args: SimpleNamespace(load=lambda: state))
    monkeypatch.setattr(
        module, "provider_ledger_accounting", lambda *a: {"unresolved_reservations": 0}
    )
    job = parent / "remote_jobs/identity"
    (job / "job/staging").mkdir(parents=True)
    (job / "REQUEST.json").write_text("{}")
    (job / "EXECUTION_RESULT.json").write_text(json.dumps(result))
    (job / "job/staging/JOB.json").write_text("{}")
    (job / "job/BINDING.json").write_text(
        json.dumps(
            {
                "manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
                "remote": "/data/zfx/scitaste/native-workspaces/original-job",
            }
        )
    )
    restored, _, lineage = restore_workspace(
        project=tmp_path,
        parent=parent,
        output=child,
        plan_sha256="plan",
    )
    assert restored is state
    assert lineage["inherited_remote_job_files"]
    assert (child / "remote_jobs/identity/job/BINDING.json").read_bytes() == (
        job / "job/BINDING.json"
    ).read_bytes()
    assert lineage["inherited_duration_seconds"] == 30
