import time

from scitaste.executor.harness_tools import HarnessToolEnvironment
from scitaste.executor.remote_workspace_tool import RemoteWorkspaceResource, RunRemoteWorkspace
from scitaste.executor.research_tool_handler import ResearchToolActionHandler
from scitaste.research_tool_loop import ResearchToolProposal
from scitaste.state.research_state import ResearchState


def test_remote_tool_returns_original_action_cost_and_artifacts(tmp_path, monkeypatch):
    import scitaste.executor.remote_workspace_tool as module

    launches = []

    class Job:
        def __init__(self, *, output, **kwargs):
            self.output = output
            output.mkdir(parents=True, exist_ok=True)

        def submit(self, **kwargs):
            launches.append(kwargs)
            (self.output / "BINDING.json").write_text("{}")

        def observe(self):
            return {"status": "succeeded", "duration_seconds": 2}

        def collect(self, files):
            for name in files:
                path = self.output / "collected" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("observed output")

    monkeypatch.setattr(module, "RemoteWorkspaceJob", Job)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "run.py").write_text("print('experiment')")
    resource = RemoteWorkspaceResource(
        host="assigned-host",
        python="/usr/bin/python3",
        gpu_indices=(2,),
        max_jobs=1,
        wall_seconds=60,
    )
    tool = RunRemoteWorkspace(resource=resource, output=tmp_path / "jobs", run_id="run")
    environment = HarnessToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="research",
        tool_map={tool.name: tool},
        source_binding={},
        wall_seconds=120,
    )
    state = ResearchState(project_id="p", research_direction="research", target_domain="general")
    action = ResearchToolProposal(
        tool="Run Remote",
        arguments={"files": ["run.py"], "argv": ["python", "run.py"], "artifacts": ["result.json"]},
        rationale="Execute selected study",
    ).action(environment, 0)
    result = ResearchToolActionHandler(project_id="p", environment=environment)(state, action)
    assert result.status.value == "SUCCEEDED"
    assert result.action_id == action.action_id
    assert result.cost["experiments"] == 1
    assert result.cost["gpu_hours"] == 2 / 3600
    assert len(result.artifacts) == 3
    assert len(launches) == 1
    cached = tool.call(
        action.parameters["arguments"], workspace_root=workspace, runtime_deadline=time.time() + 120
    )
    assert cached["cost"] == {}
    assert len(launches) == 1
