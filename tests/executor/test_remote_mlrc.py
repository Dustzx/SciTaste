from __future__ import annotations

import subprocess

import pytest

from scitaste.executor.base import ExecutionStatus, ResearchExecutor
from scitaste.executor.native import SciTasteNativeExecutor
from scitaste.executor.remote_mlrc import RemoteMLRCActionHandler, RemoteMLRCBinding
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState, ResourceBudget


def binding(observation_only=False):
    return RemoteMLRCBinding(
        candidate_id="candidate-1",
        host="4090-2",
        python="/task/env/bin/python",
        bundle="/task/run/bundle",
        bundle_manifest_sha256="a" * 64,
        data_root="/task/data/development",
        output_root="/task/run/result",
        gpu_index=3,
        observation_only=observation_only,
        action="euclidean-prototypes" if observation_only else "agent-candidate",
    )


def state():
    return ResearchState(project_id="p", research_direction="research", target_domain="general")


def action(observation_only=False):
    return ResearchAction(
        action_id="selected-1",
        type=MetaAction.ANALYZE if observation_only else MetaAction.EXPERIMENT,
        description="Selected research action",
        parameters={"candidate_id": "candidate-1"},
    )


def test_native_remote_action_reconnects_without_relaunch(tmp_path, monkeypatch):
    handler = RemoteMLRCActionHandler(
        project_id="p", binding=binding(), workspace=tmp_path, allow_launch=True
    )
    calls = []

    def request(launch, action_sha256):
        assert len(action_sha256) == 64
        calls.append(launch)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("ssh", 1)
        return {"status": "complete", "receipt": {"overall_score": 0.2, "elapsed_seconds": 60}}

    monkeypatch.setattr(handler, "_request", request)
    native = SciTasteNativeExecutor(handlers={MetaAction.EXPERIMENT: handler})
    assert isinstance(native, ResearchExecutor)
    assert native.execute(state(), action()).status == ExecutionStatus.PLANNED
    result = native.execute(state(), action())
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.data["primary_value"] == 0.2
    assert result.cost["experiments"] == 1
    assert native.execute(state(), action()) == result
    assert calls == [True, False]


def test_historical_analysis_does_not_claim_new_experiment(tmp_path, monkeypatch):
    handler = RemoteMLRCActionHandler(
        project_id="p", binding=binding(True), workspace=tmp_path, allow_launch=True
    )

    def request(launch, action_sha256):
        assert not launch
        return {"status": "complete", "receipt": {"overall_score": 0.2, "elapsed_seconds": 60}}

    monkeypatch.setattr(handler, "_request", request)
    result = SciTasteNativeExecutor(handlers={MetaAction.ANALYZE: handler}).execute(
        state(), action(True)
    )
    assert result.cost == {}
    assert result.data["historical_import_not_native_execution"]


def test_remote_action_scope_and_budget_checked_before_network(tmp_path, monkeypatch):
    handler = RemoteMLRCActionHandler(
        project_id="p", binding=binding(), workspace=tmp_path, allow_launch=True
    )
    monkeypatch.setattr(handler, "_request", lambda *args: pytest.fail("network must not run"))
    exhausted = state().model_copy(update={"resource_budget": ResourceBudget(max_experiments=0)})
    with pytest.raises(ValueError, match="budget"):
        handler(exhausted, action())
    with pytest.raises(ValueError, match="different project"):
        handler(state().model_copy(update={"project_id": "other"}), action())
    with pytest.raises(ValueError, match="registered remote binding"):
        handler(state(), action(True))
