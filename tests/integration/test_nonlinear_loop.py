from __future__ import annotations

import json

import pytest

from scitaste.demo import run_nonlinear_demo
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchStage


def test_demo_probes_contradiction_then_pivots_to_a_mature_idea(tmp_path) -> None:
    summary = run_nonlinear_demo(output_dir=tmp_path, seed=7)
    state = StateStore(tmp_path).load()
    decisions = DecisionLogger(tmp_path / "decisions.jsonl").read_all()

    assert summary["selected_actions"] == [
        "FORM_WORKING_HYPOTHESIS",
        "PROBE",
        "PIVOT",
        "IDEATE",
        "SELECT_IDEA",
    ]
    assert state.current_stage == ResearchStage.PILOT
    assert state.working_hypotheses[0].status == "contradicted"
    assert state.observations[0].expected is False
    assert state.active_problem_id == "demo-problem-conflict"
    assert state.active_idea_id == "demo-idea-conflict-controller"
    assert len(decisions) == state.revision == 5
    assert all(decision.actual_outcome is not None for decision in decisions)
    assert json.loads((tmp_path / "demo_summary.json").read_text())["final_stage"] == "PILOT"


def test_demo_refuses_to_corrupt_an_existing_decision_log(tmp_path) -> None:
    run_nonlinear_demo(output_dir=tmp_path)

    with pytest.raises(FileExistsError, match="refusing to append"):
        run_nonlinear_demo(output_dir=tmp_path)
