"""One bounded, no-model execution of the training-free shared-tool bridge."""

from types import SimpleNamespace

import pytest

from scitaste.evaluation.interactive_research import InteractiveResearchLimits
from scitaste.executor.newtonbench_agent_tools import NewtonBenchAgentToolEnvironment
from scitaste.executor.research_tools import ToolAction


def test_numeric_analysis_is_shared_bounded_and_not_an_experiment(tmp_path):
    from scitaste.evaluation.interactive_research import InteractiveResearchLimits
    from scitaste.executor.newtonbench_agent_tools import NewtonBenchAgentToolEnvironment
    from scitaste.executor.research_tools import ToolAction
    from scitaste.research_tool_loop import ResearchToolProposal
    from scitaste.schema.actions import MetaAction

    seen = []
    toolbox = SimpleNamespace(
        fingerprint="a" * 64,
        task_prompt="Fit measured observations",
        code_runner=object(),
        run_code=lambda code: seen.append(code) or {"stdout": "fit"},
    )
    limits = InteractiveResearchLimits(
        max_turns=3,
        max_experiments=2,
        max_experiments_per_turn=2,
        max_code_calls=1,
        max_total_tokens=1000,
        max_api_cost_usd=0,
    )
    env = NewtonBenchAgentToolEnvironment(toolbox=toolbox, limits=limits, log_root=tmp_path)
    proposal = ResearchToolProposal(
        tool="Run Code",
        arguments={"code": "print(1)"},
        rationale="Analyze observations, do not query the environment",
    )
    assert proposal.action(env, 0).type is MetaAction.PROBE
    assert "fit" in env.execute(ToolAction("Run Code", proposal.arguments))
    assert "budget exhausted" in env.execute(ToolAction("Run Code", proposal.arguments))
    assert seen == ["print(1)"]
    assert env.code_calls_used == 1
    assert env.experiments_used == 0


def test_experiment_submission_and_terminal_scoring(tmp_path):
    calls = []

    def score(submission):
        calls.append(("score", submission))
        return SimpleNamespace(model_dump_json=lambda: '{"fixture": true}')

    toolbox = SimpleNamespace(
        fingerprint="a" * 64,
        task_prompt="Infer the observed law.",
        code_runner=None,
        run_experiments=lambda requests: calls.append(("experiment", requests)) or {"y": 2},
        score=score,
    )
    limits = InteractiveResearchLimits(
        max_turns=4,
        max_experiments=1,
        max_experiments_per_turn=1,
        max_total_tokens=1000,
        max_api_cost_usd=0,
    )
    env = NewtonBenchAgentToolEnvironment(toolbox=toolbox, limits=limits, log_root=tmp_path)
    assert "Run Code" not in env.action_infos
    assert env.research_problem == toolbox.task_prompt
    assert len(env.interface_fingerprint) == 64
    query = ToolAction("Run Experiments", {"experiments": [{"parameters": {"x": 1}}]})
    assert '"y": 2' in env.execute(query)
    assert "budget exceeded" in env.execute(query)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="final submission"):
        env.score_submission()
    assert '"scored": false' in env.execute(
        ToolAction("Final Answer", {"final_solution": "y = 2*x", "best_score": 1})
    )
    assert len(calls) == 1  # No judge call or hidden scorer feedback to the agent.
    assert env.is_final()
    env.score_submission()
    assert calls[-1] == ("score", "y = 2*x")
    with pytest.raises(FileExistsError):
        env.score_submission()
    with pytest.raises(ValueError, match="terminal"):
        env.execute(query)
    with pytest.raises(FileExistsError):
        NewtonBenchAgentToolEnvironment(toolbox=toolbox, limits=limits, log_root=tmp_path)


def test_budget_end_without_submission_does_not_invent_score(tmp_path):
    toolbox = SimpleNamespace(fingerprint="a" * 64, task_prompt="Infer law", code_runner=None)
    limits = InteractiveResearchLimits(
        max_turns=1,
        max_experiments=1,
        max_experiments_per_turn=1,
        max_total_tokens=1000,
        max_api_cost_usd=0,
    )
    env = NewtonBenchAgentToolEnvironment(toolbox=toolbox, limits=limits, log_root=tmp_path)
    assert "unknown action" in env.execute(ToolAction("Read Hidden Law", {}))
    assert env.is_final()
    with pytest.raises(ValueError, match="final submission"):
        env.score_submission()


@pytest.mark.parametrize("abstain", [False, True])
def test_native_loop_counts_queries_without_claiming_scientific_success(tmp_path, abstain):
    import json

    from scitaste.backends.base import PreferenceResponse
    from scitaste.research_tool_loop import run_research_tool_loop
    from scitaste.state.research_state import ResearchState, ResourceBudget
    from scitaste.taste.controller import TasteController

    toolbox = SimpleNamespace(
        fingerprint="a" * 64,
        task_prompt="Infer law",
        code_runner=None,
        run_experiments=lambda requests: {"results": [2, 4]},
    )
    limits = InteractiveResearchLimits(
        max_turns=2,
        max_experiments=2,
        max_experiments_per_turn=2,
        max_total_tokens=1000,
        max_api_cost_usd=0,
    )
    env = NewtonBenchAgentToolEnvironment(
        toolbox=toolbox, limits=limits, log_root=tmp_path / "tools"
    )
    proposals = iter(
        [
            {
                "tool": "Run Experiments",
                "arguments": {"experiments": [{"parameters": {"x": 1}}, {"parameters": {"x": 2}}]},
                "rationale": "Measure two inputs",
            },
            {
                "tool": "Final Answer",
                "arguments": {"final_solution": "y=2*x"},
                "rationale": "Submit",
            },
        ]
    )

    class Backend:
        name = "fixture"

        def rank(self, request):
            selected = request.candidate_actions[-1 if abstain else 0]
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id=selected.action_id,
                rationale="Fixture selection, not measured efficacy",
                confidence=1,
                backend=self.name,
                model="fixture",
            )

    state = ResearchState(
        project_id="p",
        research_direction="Infer law",
        target_domain="physics",
        resource_budget=ResourceBudget(max_experiments=2),
    )
    outcome = run_research_tool_loop(
        state=state,
        controller=TasteController(
            utility_enabled=False, critics_enabled=False, preference_backend=Backend()
        ),
        proposer=lambda *_: next(proposals),
        environment=env,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        max_turns=2,
    )
    assert outcome["status"] == "controller-finished"
    assert state.resource_usage.experiments == (0 if abstain else 2)
    rows = [
        json.loads(line) for line in (tmp_path / "loop/TRAJECTORY.jsonl").read_text().splitlines()
    ]
    assert all(row["result"]["data"]["scientific_efficacy_established"] is False for row in rows)
    assert all("primary_value" not in row["result"]["data"] for row in rows)
    if abstain:
        assert env.submission is None
        with pytest.raises(ValueError, match="final submission"):
            env.score_submission()
    else:
        assert rows[0]["selected"]["expected_cost"]["experiments"] == 2
        assert rows[0]["result"]["cost"]["experiments"] == 2
        assert env.submission == "y=2*x"
