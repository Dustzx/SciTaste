import pytest

from scitaste.backends.base import PreferenceResponse
from scitaste.executor.native_prepared_turn import load_turn, retain_turn
from scitaste.research_tool_loop import run_research_tool_loop
from scitaste.state.persistence import StateStore, snapshot_id
from scitaste.taste.controller import TasteController
from tests.executor.test_research_harness import environment, state


def test_exact_prepared_selection_resumes_without_reproposal(tmp_path):
    env, calls = environment(tmp_path)
    original = state()
    proposer_calls = []
    sync_calls = []

    def synchronize(current):
        sync_calls.append(True)
        current.resource_usage.wall_time_hours += 0.01

    env.synchronize_budget = synchronize

    def propose(*_):
        proposer_calls.append(True)
        return {
            "proposals": [
                {"tool": "Read", "arguments": {"file_path": "results.json"}, "rationale": "Inspect"}
            ]
        }

    class InterruptedController:
        def decide(self, **_):
            raise TimeoutError("Known model wait before tool admission")

    options = dict(
        environment=env,
        workspace=tmp_path / "loop",
        artifact_root=tmp_path,
        max_turns=1,
        max_proposals=2,
        proposer=propose,
    )
    with pytest.raises(TimeoutError):
        run_research_tool_loop(state=original, controller=InterruptedController(), **options)
    assert calls == []
    checkpoint = StateStore(tmp_path / "loop/state").load()
    frozen_snapshot = snapshot_id(checkpoint)

    class Backend:
        name = "fixture"

        def rank(self, request):
            assert snapshot_id(checkpoint) == frozen_snapshot
            return PreferenceResponse(
                request_id=request.request_id,
                request_fingerprint=request.fingerprint,
                selected_action_id="tool-0-0",
                rationale="Inspect once",
                confidence=1,
                backend=self.name,
                model="fixture",
            )

    run_research_tool_loop(
        state=checkpoint,
        controller=TasteController(
            utility_enabled=False, critics_enabled=False, preference_backend=Backend()
        ),
        resume_in_place=True,
        initial_history=[],
        **options,
    )
    assert len(proposer_calls) == 1
    assert len(sync_calls) == 2
    assert [name for name, _ in calls] == ["Read"]


def test_prepared_turn_rejects_state_and_interface_drift(tmp_path):
    current = state()
    path = tmp_path / "selection.json"
    retain_turn(path, state=current, history=[], interface="fixed")
    with pytest.raises(ValueError, match="exact pre-tool"):
        load_turn(path, state=current, history=[], interface="changed")
    current.resource_usage.experiments = 1
    with pytest.raises(ValueError, match="exact pre-tool"):
        load_turn(path, state=current, history=[], interface="fixed")


def test_initial_evidence_stage_loads_question_procedures(tmp_path):
    env, _ = environment(tmp_path)
    packet = env.research_harness.proposal_context(state(), [])
    assert [item["skill_id"] for item in packet["loaded_skills"]] == [
        "question-and-hypotheses",
        "controlled-experiment",
    ]
    assert packet["requested_skill_is_not_proof_of_procedure_use"] is True
