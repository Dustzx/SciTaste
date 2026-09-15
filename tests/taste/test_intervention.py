from __future__ import annotations

from pathlib import Path

import pytest

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.state.resources import remaining_budget
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.episode_learning import LifecycleTastePolicyUpdateMode
from scitaste.taste.intervention import (
    TasteInterventionActionBinding,
    TasteInterventionComparison,
    TasteInterventionCondition,
    TasteInterventionContract,
    TasteInterventionDimension,
    TasteInterventionHypothesis,
    TasteSelectorMode,
    load_taste_intervention_contract,
    save_taste_intervention_contract,
    taste_precedent_pool_sha256,
)
from scitaste.taste.retriever import TasteRetriever


def _idea_binding() -> ProjectIdeaRevisionBinding:
    return ProjectIdeaRevisionBinding.create(
        project_id="test-project",
        observed_project_revision=3,
        observed_project_snapshot_sha256="1" * 64,
        revision_id="idea-v1",
        status="accepted",
        record_locator="runs/run-v1/idea/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=True,
        paper_claim_authority=True,
    )


def _actions() -> tuple[ResearchAction, ...]:
    return (
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Probe first"),
        ResearchAction(
            action_id="experiment",
            type=MetaAction.EXPERIMENT,
            description="Run the main experiment",
        ),
    )


def _contract(
    state: ResearchState,
    *,
    contract_id: str,
    hypothesis: TasteInterventionHypothesis,
    condition: TasteInterventionCondition,
    dimension: TasteInterventionDimension,
    selector: TasteSelectorMode,
    update_mode: LifecycleTastePolicyUpdateMode | None = None,
    policy_sha256: str | None = None,
    training_sha256: str | None = None,
    weight: float = 0.0,
    prompt_version: str = "native-taste-policy-v1",
    precedent_pool_sha256: str | None = None,
    selector_runtime_sha256: str = "c" * 64,
    controller_backbone_sha256: str = "d" * 64,
) -> TasteInterventionContract:
    actions = _actions()
    policy_source_groups = (
        () if hypothesis is TasteInterventionHypothesis.TASTE_SELECTION else ("source-train",)
    )
    precedent_source_groups = (
        () if selector is TasteSelectorMode.DISABLED else ("source-precedent",)
    )
    heldout_source_groups = ("source-heldout",)
    return TasteInterventionContract.create(
        contract_id=contract_id,
        hypothesis=hypothesis,
        condition=condition,
        changed_dimension=dimension,
        benchmark_id="scitastebench-v2",
        task_id="decision-case-001",
        benchmark_local_state_sha256=snapshot_id(state).removeprefix("state-"),
        action_menu=tuple(TasteInterventionActionBinding.from_action(item) for item in actions),
        precedent_pool_sha256=(precedent_pool_sha256 or taste_precedent_pool_sha256(())),
        selector_runtime_sha256=selector_runtime_sha256,
        controller_backbone_sha256=controller_backbone_sha256,
        source_identity_registry_sha256="5" * 64,
        canonical_source_group_ids=tuple(
            sorted(
                (
                    *policy_source_groups,
                    *precedent_source_groups,
                    *heldout_source_groups,
                )
            )
        ),
        policy_source_group_ids=policy_source_groups,
        precedent_source_group_ids=precedent_source_groups,
        heldout_source_group_ids=heldout_source_groups,
        selector_mode=selector,
        lifecycle_update_mode=update_mode,
        lifecycle_policy_sha256=policy_sha256,
        policy_training_corpus_sha256=training_sha256,
        lifecycle_policy_weight=weight,
        decision_provider="scitaste-native",
        decision_model="deterministic-utility-controller",
        prompt_version=prompt_version,
        seed=4,
        resource_budget_sha256=content_sha256(
            remaining_budget(state.resource_budget, state.resource_usage)
        ),
        tool_policy_sha256="6" * 64,
        repair_policy_sha256="7" * 64,
        executor_sha256="8" * 64,
        task_sha256="9" * 64,
        idea_revision_binding_sha256=_idea_binding().binding_sha256,
    )


def test_h2b_pair_changes_only_selector_mode(research_state: ResearchState) -> None:
    left = _contract(
        research_state,
        contract_id="h2b-deliberative",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.DELIBERATIVE_SELECTION,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.DELIBERATIVE,
    )
    right = _contract(
        research_state,
        contract_id="h2b-lexical",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.LEXICAL_RETRIEVAL,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.LEXICAL,
    )

    comparison = TasteInterventionComparison.create(
        comparison_id="h2b-selector-pair",
        left=left,
        right=right,
    )

    assert comparison.comparison_sha256


def test_pair_rejects_prompt_drift(research_state: ResearchState) -> None:
    left = _contract(
        research_state,
        contract_id="h2b-deliberative",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.DELIBERATIVE_SELECTION,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.DELIBERATIVE,
    )
    right = _contract(
        research_state,
        contract_id="h2b-lexical",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.LEXICAL_RETRIEVAL,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.LEXICAL,
        prompt_version="drifted-prompt-v2",
    )

    with pytest.raises(ValueError, match="prompt_version"):
        TasteInterventionComparison.create(
            comparison_id="h2b-invalid-pair",
            left=left,
            right=right,
        )


def test_h4_pair_keeps_identical_policy_and_changes_only_weight(
    research_state: ResearchState,
) -> None:
    common = {
        "hypothesis": TasteInterventionHypothesis.OBJECTIVE_PROGRESS,
        "dimension": TasteInterventionDimension.POLICY_WEIGHT,
        "selector": TasteSelectorMode.DELIBERATIVE,
        "update_mode": LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
        "policy_sha256": "a" * 64,
        "training_sha256": "b" * 64,
    }
    enabled = _contract(
        research_state,
        contract_id="h4-policy-on",
        condition=TasteInterventionCondition.LEARNED_POLICY_ON,
        weight=1.0,
        **common,
    )
    disabled = _contract(
        research_state,
        contract_id="h4-policy-off",
        condition=TasteInterventionCondition.LEARNED_POLICY_OFF,
        weight=0.0,
        **common,
    )

    assert TasteInterventionComparison.create(
        comparison_id="h4-policy-weight-pair",
        left=enabled,
        right=disabled,
    ).comparison_sha256


def test_h3_pair_changes_update_and_policy_but_not_estimator_corpus(
    research_state: ResearchState,
) -> None:
    common = {
        "hypothesis": TasteInterventionHypothesis.LIFECYCLE_CREDIT,
        "dimension": TasteInterventionDimension.CREDIT_UPDATE,
        "selector": TasteSelectorMode.DELIBERATIVE,
        "training_sha256": "b" * 64,
        "weight": 1.0,
    }
    updated = _contract(
        research_state,
        contract_id="h3-updated",
        condition=TasteInterventionCondition.OUTCOME_UPDATED,
        update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
        policy_sha256="a" * 64,
        **common,
    )
    no_update = _contract(
        research_state,
        contract_id="h3-no-update",
        condition=TasteInterventionCondition.NO_UPDATE,
        update_mode=LifecycleTastePolicyUpdateMode.NO_UPDATE,
        policy_sha256="e" * 64,
        **common,
    )

    assert TasteInterventionComparison.create(
        comparison_id="h3-credit-update-pair",
        left=updated,
        right=no_update,
    ).comparison_sha256

    drifted = _contract(
        research_state,
        contract_id="h3-no-update-drifted",
        condition=TasteInterventionCondition.NO_UPDATE,
        update_mode=LifecycleTastePolicyUpdateMode.NO_UPDATE,
        policy_sha256="e" * 64,
        training_sha256="f" * 64,
        hypothesis=TasteInterventionHypothesis.LIFECYCLE_CREDIT,
        dimension=TasteInterventionDimension.CREDIT_UPDATE,
        selector=TasteSelectorMode.DELIBERATIVE,
        weight=1.0,
    )
    with pytest.raises(ValueError, match="policy_training_corpus_sha256"):
        TasteInterventionComparison.create(
            comparison_id="h3-estimator-drift",
            left=updated,
            right=drifted,
        )


def test_controller_persists_validated_h2b_lexical_contract(
    tmp_path: Path,
    research_state: ResearchState,
) -> None:
    library = _taste_library(tmp_path)
    controller = TasteController(
        seed=4,
        mode=TasteMode.AUGMENTED,
        retriever=TasteRetriever(library),
    )
    pool_sha256, selector_sha256 = controller.intervention_runtime_hashes(
        state=research_state,
        candidate_actions=_actions(),
    )
    contract = _contract(
        research_state,
        contract_id="h2b-lexical",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.LEXICAL_RETRIEVAL,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.LEXICAL,
        precedent_pool_sha256=pool_sha256,
        selector_runtime_sha256=selector_sha256,
        controller_backbone_sha256=controller.intervention_backbone_sha256,
    )

    decision = controller.decide(
        state=research_state,
        candidate_actions=_actions(),
        current_idea_revision=_idea_binding(),
        intervention_contract=contract,
    )

    assert decision.taste_intervention is not None
    assert decision.taste_intervention.contract_sha256 == contract.contract_sha256
    assert decision.taste_intervention.condition_id == "lexical-taste-retrieval"
    assert decision.taste_intervention.policy_source_groups_sha256 == content_sha256(())
    assert decision.taste_intervention.heldout_source_groups_sha256 == content_sha256(
        ("source-heldout",)
    )
    assert decision.model_dump(mode="json")["taste_intervention"]["trace_sha256"]


def test_controller_rejects_runtime_action_drift(
    tmp_path: Path,
    research_state: ResearchState,
) -> None:
    library = _taste_library(tmp_path)
    controller = TasteController(
        seed=4,
        mode=TasteMode.AUGMENTED,
        retriever=TasteRetriever(library),
    )
    pool_sha256, selector_sha256 = controller.intervention_runtime_hashes(
        state=research_state,
        candidate_actions=_actions(),
    )
    contract = _contract(
        research_state,
        contract_id="h2b-lexical",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.LEXICAL_RETRIEVAL,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.LEXICAL,
        precedent_pool_sha256=pool_sha256,
        selector_runtime_sha256=selector_sha256,
        controller_backbone_sha256=controller.intervention_backbone_sha256,
    )
    actions = list(_actions())
    actions[0] = actions[0].model_copy(update={"description": "Changed after randomization"})

    with pytest.raises(ValueError, match="action menu"):
        controller.decide(
            state=research_state,
            candidate_actions=actions,
            current_idea_revision=_idea_binding(),
            intervention_contract=contract,
        )


def test_contract_round_trip_is_content_bound(
    tmp_path: Path,
    research_state: ResearchState,
) -> None:
    contract = _contract(
        research_state,
        contract_id="h2b-lexical-roundtrip",
        hypothesis=TasteInterventionHypothesis.TASTE_SELECTION,
        condition=TasteInterventionCondition.LEXICAL_RETRIEVAL,
        dimension=TasteInterventionDimension.SELECTOR,
        selector=TasteSelectorMode.LEXICAL,
    )
    path = save_taste_intervention_contract(contract, tmp_path / "CONTRACT.json")

    assert load_taste_intervention_contract(path) == contract
    with pytest.raises(FileExistsError):
        save_taste_intervention_contract(contract, path)


def _taste_library(tmp_path: Path) -> TasteLibrary:
    library = TasteLibrary(tmp_path / "taste.jsonl")
    library.add(
        TasteCase(
            case_id="precedent-probe",
            stage="DISCOVERY",
            context_summary="Test uncertainty before committing to an experiment",
            candidate_actions=["PROBE", "EXPERIMENT"],
            preferred_action="PROBE",
            rejected_actions=["EXPERIMENT"],
            decision_principle="Probe before commitment.",
            why_preferred="The probe separates the leading explanations.",
            provenance=[
                ProvenanceRecord(
                    source_type="test",
                    locator="fixture://precedent-probe",
                    metadata={"canonical_source_group_id": "source-precedent"},
                )
            ],
            confidence=1.0,
            domain_tags=["testing"],
            retrieval_eligible=True,
        )
    )
    return library
