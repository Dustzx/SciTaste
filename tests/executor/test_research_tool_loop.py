import json

import pytest

from scitaste.backends.base import PreferenceResponse
from scitaste.executor.research_tools import ResearchToolEnvironment
from scitaste.research_tool_loop import run_research_tool_loop, tool_decision_context
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import TasteController


@pytest.mark.parametrize("pending", [False, True])
def test_explicit_experiment_limit_finishes_without_model_calls(tmp_path, pending):
    from scitaste.state.research_state import ResourceBudget, ResourceUsage

    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "model.py").write_text("x = 1\n")
    environment = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="Deliver existing results",
        experiment=lambda _: pytest.fail("Must not relaunch an experiment"),
    )
    state = ResearchState(
        project_id="p",
        research_direction="Research",
        target_domain="general",
        resource_budget=ResourceBudget(max_experiments=1),
        resource_usage=ResourceUsage(experiments=1),
    )
    result = run_research_tool_loop(
        state=state,
        controller=None,
        proposer=lambda *_: pytest.fail("No post-budget model call"),
        environment=environment,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        initial_history=[{"result": {"status": "PLANNED" if pending else "SUCCEEDED"}}],
        finish_at_experiment_limit=True,
    )
    assert result["status"] == (
        "execution-unresolved" if pending else "experiment-budget-exhausted"
    )
    assert result["controller_completion_claimed"] is False
    assert json.loads((tmp_path / "loop/RESOURCE_STOP.json").read_text()) == result
    assert not list((tmp_path / "loop").glob("decision-*.json"))


def test_multiple_proposals_are_alternatives_not_an_execution_sequence(tmp_path):
    from scitaste.research_tool_loop import ResearchToolProposalBatch

    workspace = tmp_path / "candidate"
    workspace.mkdir()
    source = workspace / "model.py"
    source.write_text("x = 1\n")
    proposals = [
        {
            "tool": "Write File",
            "arguments": {"file_name": "model.py", "content": "x = 2\n"},
            "rationale": "Revise",
        },
        {"tool": "Read File", "arguments": {"file_name": "model.py"}, "rationale": "Inspect first"},
    ]
    with pytest.raises(ValueError, match="differ in action"):
        ResearchToolProposalBatch(proposals=[proposals[0], {**proposals[0], "rationale": "Again"}])

    class Backend:
        name = "fixture"

        def rank(self, request):
            assert {item.action_id for item in request.candidate_actions} == {
                "tool-0-0",
                "tool-0-1",
                "stop-0",
            }
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id="tool-0-1",
                rationale="Read before changing",
                confidence=1,
                backend=self.name,
                model="fixture",
            )

    environment = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="Inspect",
        experiment=lambda _: pytest.fail("No experiment selected"),
    )
    result = run_research_tool_loop(
        state=ResearchState(project_id="p", research_direction="Research", target_domain="general"),
        controller=TasteController(
            utility_enabled=False, critics_enabled=False, preference_backend=Backend()
        ),
        proposer=lambda *_: {"proposals": proposals},
        environment=environment,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        max_turns=1,
        max_proposals=2,
    )
    assert result["status"] == "turn-budget-exhausted"
    assert source.read_text() == "x = 1\n"
    assert len(environment.trace.steps) == 1
    assert environment.trace.steps[0].action.name == "Read File"
    decision = json.loads((tmp_path / "loop/decision-000.json").read_text())
    assert len(decision["candidate_actions"]) == 3


def test_controller_can_reject_proposed_write_before_execution(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    original = workspace / "model.py"
    original.write_text("x = 1\n")

    class Backend:
        name = "fixture"

        def rank(self, request):
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id="stop-0",
                rationale="Reject this proposed edit.",
                confidence=1,
                backend=self.name,
                model="fixture",
            )

    env = ResearchToolEnvironment(
        workspace=workspace,
        log_root=tmp_path / "tools",
        research_problem="Inspect",
        experiment=lambda _: None,
    )
    result = run_research_tool_loop(
        state=ResearchState(project_id="p", research_direction="Research", target_domain="general"),
        controller=TasteController(
            utility_enabled=False, critics_enabled=False, preference_backend=Backend()
        ),
        proposer=lambda *args: {
            "tool": "Write File",
            "arguments": {"file_name": "model.py", "content": "x = 2\n"},
            "rationale": "Propose edit",
        },
        environment=env,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
    )
    assert result["status"] == "controller-finished"
    assert original.read_text() == "x = 1\n"
    decision = json.loads((tmp_path / "loop/decision-000.json").read_text())
    assert decision["selected_action"]["action_id"] == "stop-0"
    assert decision["actual_outcome"] is None
    from scitaste.state.persistence import DecisionLogger, StateStore

    bound = DecisionLogger(tmp_path / "loop/decisions.jsonl").read_all()
    assert len(bound) == 1
    assert bound[0].executor_result_id == bound[0].actual_outcome["result_id"]
    assert bound[0].actual_outcome["status"] == "SUCCEEDED"
    states = StateStore(tmp_path / "loop/state")
    before = states.load(bound[0].state_snapshot_id)
    assert before.decision_history == []
    assert states.load().decision_history[0].executor_result_id == bound[0].executor_result_id


@pytest.mark.parametrize("direction,relation", [("maximize", "below"), ("minimize", "above")])
def test_observed_score_context_respects_metric_direction(direction, relation):
    from scitaste.state.research_state import ResourceBudget, ResourceUsage

    state = ResearchState(
        project_id="p",
        research_direction="research",
        target_domain="general",
        resource_budget=ResourceBudget(max_experiments=1),
        resource_usage=ResourceUsage(experiments=1),
        executor_context={"baseline_score": 0.2, "objective_direction": direction},
    )
    history = [
        {
            "selected": {"parameters": {"tool": "Run Experiment"}},
            "result": {"status": "SUCCEEDED", "data": {"primary_value": 0.1}},
        }
    ]
    context = tool_decision_context(state, history)
    assert context["remaining_experiments"] == "zero"
    assert context["best_vs_baseline"] == relation
    assert context["failure_count"] == "zero"
    assert "evidence_confidence" not in context
