from __future__ import annotations

import yaml
from pydantic import ValidationError

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.conditions import (
    NativeTasteCondition,
    build_native_condition_runtime,
    load_native_condition_matrix,
)

MATRIX = "configs/evaluation/native_taste_condition_matrix_v1.yaml"


def _case(
    case_id: str,
    *,
    domain: str,
    preferred: MetaAction,
) -> TasteCase:
    return TasteCase(
        case_id=case_id,
        stage="DISCOVERY",
        context_summary="Choose a bounded diagnostic action",
        candidate_actions=[MetaAction.PROBE.value, MetaAction.SEARCH.value],
        preferred_action=preferred.value,
        decision_principle="Use the registered domain-specific research precedent.",
        why_preferred="The precedent distinguishes the two matched actions.",
        provenance=[ProvenanceRecord(source_type="test", locator=f"fixture://{case_id}")],
        confidence=1.0,
        retrieval_eligible=True,
        domain_tags=[domain],
    )


def test_native_condition_matrix_is_exact_and_placebo_is_single_factor() -> None:
    inspection = load_native_condition_matrix(MATRIX)
    matrix = inspection.matrix

    assert len(matrix.profiles) == 6
    assert {item.condition_id for item in matrix.profiles} == set(NativeTasteCondition)
    full = matrix.profile(NativeTasteCondition.FULL).components
    placebo = matrix.profile(NativeTasteCondition.MISMATCHED_PLACEBO).components
    assert full.model_copy(update={"taste_retrieval": placebo.taste_retrieval}) == placebo
    assert matrix.component_only_effect_claims_forbidden is True
    assert len(inspection.file_sha256) == 64
    assert len(matrix.fingerprint) == 64


def test_native_condition_matrix_rejects_component_smuggling(tmp_path) -> None:
    payload = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["condition_id"] == "native-base")
    profile["components"]["knowledge_retrieval_enabled"] = True
    path = tmp_path / "drift.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    try:
        load_native_condition_matrix(path)
    except ValidationError as error:
        assert "native condition profile drift: native-base" in str(error)
    else:  # pragma: no cover - explicit assertion message
        raise AssertionError("component drift was accepted")


def test_full_and_placebo_retrieve_disjoint_taste_domains(tmp_path) -> None:
    library = TasteLibrary(tmp_path / "taste.jsonl")
    library.add(_case("matched-probe", domain="testing", preferred=MetaAction.PROBE))
    library.add(_case("mismatch-search", domain="biology", preferred=MetaAction.SEARCH))
    matrix = load_native_condition_matrix(MATRIX).matrix
    state = ResearchState(
        project_id="condition-runtime",
        research_direction="Choose a bounded diagnostic action",
        target_domain="testing",
    )
    actions = [
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe"),
        ResearchAction(action_id="search", type=MetaAction.SEARCH, description="Search"),
    ]

    full = build_native_condition_runtime(
        matrix.profile(NativeTasteCondition.FULL),
        seed=7,
        taste_library=library,
    ).controller.decide(state=state, candidate_actions=actions)
    placebo = build_native_condition_runtime(
        matrix.profile(NativeTasteCondition.MISMATCHED_PLACEBO),
        seed=7,
        taste_library=library,
    ).controller.decide(state=state, candidate_actions=actions)

    assert full.selected_action.type is MetaAction.PROBE
    assert full.retrieved_taste_cases == ["matched-probe"]
    assert placebo.selected_action.type is MetaAction.SEARCH
    assert placebo.retrieved_taste_cases == ["mismatch-search"]


def test_base_condition_is_utility_neutral_and_ignores_available_taste(tmp_path) -> None:
    library = TasteLibrary(tmp_path / "taste.jsonl")
    library.add(_case("matched-probe", domain="testing", preferred=MetaAction.PROBE))
    matrix = load_native_condition_matrix(MATRIX).matrix
    runtime = build_native_condition_runtime(
        matrix.profile(NativeTasteCondition.BASE),
        seed=11,
        taste_library=library,
    )
    state = ResearchState(
        project_id="condition-control",
        research_direction="Choose a bounded action",
        target_domain="testing",
    )
    actions = [
        ResearchAction(
            action_id="expensive",
            type=MetaAction.PROBE,
            description="High declared value",
            expected_value={"information_gain": 100.0},
        ),
        ResearchAction(
            action_id="neutral",
            type=MetaAction.SEARCH,
            description="No declared value",
        ),
    ]

    decision = runtime.controller.decide(state=state, candidate_actions=actions)

    assert decision.retrieved_taste_cases == []
    assert set(decision.candidate_scores.values()) == {0.0}
    assert "utility-neutral control policy" in decision.rationale
    assert runtime.knowledge_retrieval_enabled is False
    assert runtime.taste_context_enabled is False
