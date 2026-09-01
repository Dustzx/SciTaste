from __future__ import annotations

from scitaste.data.store import TasteLibrary
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController
from scitaste.taste.memory import TasteMemory


def test_executed_decision_becomes_traceable_taste_memory(tmp_path, research_state) -> None:
    actions = [
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe"),
        ResearchAction(action_id="idea", type=MetaAction.IDEATE, description="Ideate"),
    ]
    decision = TasteController(seed=2).decide(
        state=research_state,
        candidate_actions=actions,
    )
    decision.executor_result_id = "result-1"
    decision.actual_outcome = {"observation": "The boundary was stable."}
    updated = apply_transition(research_state, decision)
    library = TasteLibrary(tmp_path / "taste.jsonl")

    case = TasteMemory(library).reflect(
        updated.decision_history[0],
        outcome_summary="The boundary was stable.",
        decision_principle="Prefer informative low-cost actions.",
        domain_tags=["testing"],
    )

    assert library.get(case.case_id) == case
    assert case.provenance[0].source_type == "decision_log"
    assert case.provenance[0].version == decision.decision_id
