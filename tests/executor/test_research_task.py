import pytest

from scitaste.executor.research_task import ResearchToolTask
from scitaste.executor.research_tools import ResearchToolEnvironment


def test_non_model_entrypoint_and_minimizing_cpu_task(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "solver.py").write_text("def solve(): return 1\n")
    (workspace / "score.py").write_text("def score(): return 1\n")
    task = ResearchToolTask(
        task_id="cpu-solver-development",
        source_group_id="solver-source",
        research_problem="Minimize solver error",
        objective_direction="minimize",
        required_files=("solver.py", "score.py"),
        writable_files=("solver.py",),
        execution_mode="cpu",
        wall_seconds=30,
    )
    environment = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem=task.research_problem,
        task=task,
        experiment=lambda _: pytest.fail("no experiment requested"),
    )
    environment.write_file("solver.py", "def solve(): return 2\n")
    assert "30-second" in environment.action_infos["Run Experiment"].description
    assert environment.interface_descriptor["task"]["objective_direction"] == "minimize"
    with pytest.raises(ValueError, match="writable surface"):
        environment.write_file("score.py", "def score(): return 999\n")
