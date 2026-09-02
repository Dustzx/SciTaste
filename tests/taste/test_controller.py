from __future__ import annotations

import pytest

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.research_state import ResearchState
from scitaste.taste.controller import NoViableActionError, TasteController, TasteMode
from scitaste.taste.retriever import TasteRetriever


def test_controller_prefers_information_value_and_logs_all_candidates(
    research_state: ResearchState,
) -> None:
    probe = ResearchAction(
        action_id="probe",
        type=MetaAction.PROBE,
        description="Cheap diagnostic",
        expected_cost={"gpu_hours": 0.1, "experiments": 1.0},
        expected_value={"information_gain": 0.95, "problem_validity": 0.9},
    )
    implement = ResearchAction(
        action_id="implement",
        type=MetaAction.EXPERIMENT,
        description="Expensive premature implementation",
        expected_cost={"gpu_hours": 1.5, "experiments": 3.0},
        expected_value={"information_gain": 0.2, "problem_validity": 0.2},
    )

    decision = TasteController(seed=4).decide(
        state=research_state,
        candidate_actions=[implement, probe],
    )

    assert decision.selected_action == probe
    assert set(decision.candidate_scores) == {"probe", "implement"}
    assert decision.retrieved_taste_cases == []
    assert decision.state_snapshot_id.startswith("state-")


def test_controller_rejects_actions_over_hard_budget(research_state: ResearchState) -> None:
    impossible = ResearchAction(
        action_id="impossible",
        type=MetaAction.EXPERIMENT,
        description="Exceed all available compute",
        expected_cost={"gpu_hours": 20.0},
        expected_value={"scientific_importance": 1.0},
    )

    with pytest.raises(NoViableActionError, match="gpu_hours"):
        TasteController().decide(state=research_state, candidate_actions=[impossible])


def test_infeasible_alternative_remains_json_auditable(research_state: ResearchState) -> None:
    feasible = ResearchAction(
        action_id="feasible",
        type=MetaAction.PROBE,
        description="Affordable probe",
    )
    impossible = ResearchAction(
        action_id="impossible",
        type=MetaAction.EXPERIMENT,
        description="Unaffordable experiment",
        expected_cost={"gpu_hours": 20.0},
    )

    decision = TasteController().decide(
        state=research_state,
        candidate_actions=[impossible, feasible],
    )
    restored = ResearchDecision.model_validate_json(decision.model_dump_json())

    assert restored.candidate_scores["impossible"] is None
    assert restored.selected_action == feasible


def test_fixed_seed_breaks_ties_deterministically(research_state: ResearchState) -> None:
    actions = [
        ResearchAction(action_id="a", type=MetaAction.SEARCH, description="A"),
        ResearchAction(action_id="b", type=MetaAction.PROBE, description="B"),
    ]

    first = TasteController(seed=11).decide(state=research_state, candidate_actions=actions)
    second = TasteController(seed=11).decide(state=research_state, candidate_actions=actions)

    assert first.selected_action.action_id == second.selected_action.action_id


def test_empty_candidate_set_is_invalid(research_state: ResearchState) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        TasteController().decide(state=research_state, candidate_actions=[])


def test_augmented_controller_logs_and_uses_retrieved_precedent(
    tmp_path, research_state: ResearchState
) -> None:
    library = TasteLibrary(tmp_path / "taste.jsonl")
    library.add(
        TasteCase(
            case_id="precedent-probe",
            stage="DISCOVERY",
            context_summary="Test reliable autonomous research decisions with uncertainty",
            candidate_actions=["PROBE", "IDEATE"],
            preferred_action="PROBE",
            decision_principle="Probe before commitment.",
            why_preferred="The diagnostic is cheap.",
            provenance=[ProvenanceRecord(source_type="test", locator="fixture://probe")],
            confidence=1.0,
            retrieval_eligible=True,
            domain_tags=["testing"],
        )
    )
    actions = [
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe uncertainty"),
        ResearchAction(action_id="idea", type=MetaAction.IDEATE, description="Commit now"),
    ]
    decision = TasteController(
        mode=TasteMode.AUGMENTED,
        retriever=TasteRetriever(library),
        precedent_weight=1.0,
    ).decide(state=research_state, candidate_actions=actions)

    assert decision.selected_action.action_id == "probe"
    assert decision.retrieved_taste_cases == ["precedent-probe"]
    assert decision.candidate_scores["probe"] > decision.candidate_scores["idea"]
