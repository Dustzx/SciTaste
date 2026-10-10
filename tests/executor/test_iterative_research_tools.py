import json

import pytest

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.iterative_research_tools import IterativeResearchToolEnvironment
from scitaste.executor.research_task import IterativeResearchToolTask


def test_revision_uses_frozen_attempts_and_cumulative_budget(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "method.py").write_text("version = 0\n")
    task = IterativeResearchToolTask(
        task_id="iterative",
        source_group_id="source",
        research_problem="Improve",
        objective_direction="maximize",
        required_files=("method.py",),
        writable_files=("method.py",),
        execution_mode="gpu",
        wall_seconds=120,
        max_experiments=3,
        total_wall_seconds=180,
    )
    calls = []

    def factory(number, ceiling):
        def execute(candidate):
            calls.append((number, ceiling, candidate, (candidate / "method.py").read_text()))
            return ExecutionResult(
                action_id=f"attempt-{number}",
                executor="fixture",
                status=ExecutionStatus.SUCCEEDED,
                cost={"experiments": 1.0, "wall_time_hours": 110 / 3600},
                data={"cost_complete": True, "primary_value": number / 10},
            ).model_dump(mode="json")

        return execute

    env = IterativeResearchToolEnvironment(
        workspace=workspace, log_root=tmp_path / "tools", task=task, experiment_factory=factory
    )
    first = json.loads(env.run_experiment())
    assert first["cost"]["experiments"] == 1
    assert json.loads(env.run_experiment())["cost"] == {}
    assert len(calls) == 1
    env.write_file("method.py", "version = 1\n")
    env.run_experiment()
    assert calls[0][1] == 120 and calls[1][1] == 70
    assert (calls[0][2] / "method.py").read_text() == "version = 0\n"
    assert (calls[1][2] / "method.py").read_text() == "version = 1\n"
    with pytest.raises(ValueError, match="budget exhausted"):
        env.write_file("method.py", "version = 2\n")
    assert len(calls) == 2
