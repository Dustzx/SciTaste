import json

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.research_tools import ResearchToolEnvironment


def test_reserved_experiment_observes_without_relaunch(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "model.py").write_text("x = 1\n")

    class Callback:
        launches = 0
        observations = 0

        def __call__(self, path):
            self.launches += 1
            return ExecutionResult(
                action_id="one", executor="fixture", status=ExecutionStatus.PLANNED
            ).model_dump(mode="json")

        def observe(self):
            self.observations += 1
            return ExecutionResult(
                action_id="one", executor="fixture", status=ExecutionStatus.SUCCEEDED
            ).model_dump(mode="json")

    callback = Callback()
    env = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "logs",
        research_problem="fixture",
        experiment=callback,
    )
    assert json.loads(env.run_experiment())["status"] == "PLANNED"
    assert json.loads(env.run_experiment())["status"] == "SUCCEEDED"
    assert json.loads(env.run_experiment())["status"] == "SUCCEEDED"
    assert callback.launches == 1 and callback.observations == 1
    assert json.loads((tmp_path / "logs/EXPERIMENT_RESULT.json").read_text())["status"] == "PLANNED"
