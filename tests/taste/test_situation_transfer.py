from __future__ import annotations

from scitaste.evaluation.scientific_situation_transfer import (
    BudgetPressure,
    EvidenceRelation,
    FormalObjectiveForkSituationCase,
    HypothesisStructure,
    IdentifiabilityBand,
    ObjectiveForkReplicateOutcome,
    ScientificBottleneck,
    ScientificSituation,
    ScientificSituationTransferThresholds,
    TerminalReadiness,
    select_by_scientific_situation,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.deliberation import (
    TasteBoundarySupport,
    TasteDecisionFact,
    TasteDeliberationCandidate,
    TasteDeliberationInput,
)
from scitaste.taste.situation_transfer import (
    ScientificActionSemanticBinding,
    ScientificSituationPrecedentBinding,
    compile_scientific_situation_control_packet,
)


def _situation(study_id: str, task_cluster_id: str) -> ScientificSituation:
    return ScientificSituation.create(
        study_id=study_id,
        task_cluster_id=task_cluster_id,
        prefix_sha256="a" * 64,
        hypothesis_structure=HypothesisStructure.COMPETING_CANDIDATES,
        evidence_relation=EvidenceRelation.UNDERDETERMINED,
        bottleneck=ScientificBottleneck.FUNCTIONAL_FORM,
        identifiability=IdentifiabilityBand.MEDIUM,
        budget_pressure=BudgetPressure.MEDIUM,
        terminal_readiness=TerminalReadiness.NOT_READY,
        anchors=(
            {"field_id": "state", "quote": "competing explanations"},
            {"field_id": "budget", "quote": "two experiments remain"},
        ),
        decision_basis="A bounded probe can distinguish the live candidates.",
        abstraction_confidence=0.9,
        extractor_provider="fixture",
        extractor_model="fixture",
        request_fingerprint="b" * 64,
        response_sha256="c" * 64,
    )


def _formal_case(study_id: str, task_cluster_id: str, suffix: str):
    utilities = {"probe": (0.8, 0.9, 0.85), "experiment": (0.2, 0.3, 0.25)}
    outcomes = tuple(
        ObjectiveForkReplicateOutcome(
            action_id=action,
            replicate_id=f"{study_id}-{action}-{index}",
            executed=True,
            objective_observed=True,
            utility=value,
            result_sha256=suffix * 64,
        )
        for action, values in utilities.items()
        for index, value in enumerate(values)
    )
    return FormalObjectiveForkSituationCase(
        study_id=study_id,
        task_cluster_id=task_cluster_id,
        situation=_situation(study_id, task_cluster_id),
        available_actions=("experiment", "probe"),
        utility_contract_id="shared-utility-v1",
        action_semantics_sha256="d" * 64,
        practical_equivalence_tolerance=0.05,
        intention_to_treat_failure_utility=0.0,
        replicate_outcomes=outcomes,
        action_utility_estimates={
            action: sum(values) / len(values) for action, values in utilities.items()
        },
        result_sha256="e" * 64,
    )


def _candidate(case_id: str, source: str) -> TasteDeliberationCandidate:
    return TasteDeliberationCandidate(
        case_id=case_id,
        case_sha256="f" * 64,
        taste_grounding_sha256="1" * 64,
        source_identities=(source,),
        stage="EXPERIMENT",
        context_summary="Competing explanations remain under a bounded budget.",
        evidence_state="The alternatives remain underdetermined.",
        candidate_actions=("probe", "experiment"),
        preferred_action="probe",
        rejected_actions=("experiment",),
        decision_principle="Resolve decision-relevant uncertainty before commitment.",
        why_preferred="Repeated objective forks favored the bounded probe.",
        applies_when=(
            "Competing explanations remain live.",
            "A bounded diagnostic remains feasible.",
        ),
        fails_when=(
            "One explanation is already decisive.",
            "No diagnostic budget remains.",
        ),
        counterfactual_probe="Would decisive evidence reverse the choice?",
        confidence=0.9,
        broad_retrieval_score=0.8,
    )


def test_formal_objective_transfer_compiles_to_canonical_control_packet() -> None:
    target = _situation("target-study", "target-cluster")
    sources = (
        _formal_case("source-one", "cluster-one", "2"),
        _formal_case("source-two", "cluster-two", "3"),
    )
    decision = select_by_scientific_situation(
        target=target,
        sources=sources,
        available_actions={"probe", "experiment"},
        thresholds=ScientificSituationTransferThresholds(
            require_formal_sources=True,
            minimum_effective_support=2.0,
            maximum_standard_error=0.2,
        ),
    )
    facts = (
        TasteDecisionFact(
            fact_id="fact-competing",
            kind="hypothesis",
            text="Competing explanations remain live.",
            boundary_candidate=True,
        ),
        TasteDecisionFact(
            fact_id="fact-budget",
            kind="obligation",
            text="A bounded diagnostic remains feasible.",
        ),
        TasteDecisionFact(
            fact_id="fact-stage",
            kind="stage",
            text="The project is selecting its next experiment.",
        ),
    )
    actions = (
        ResearchAction(action_id="probe", type=MetaAction.PROBE, description="Run probe"),
        ResearchAction(
            action_id="experiment",
            type=MetaAction.EXPERIMENT,
            description="Run full experiment",
        ),
    )
    candidates = (
        _candidate("taste-one", "source-group-one"),
        _candidate("taste-two", "source-group-two"),
    )
    input_data = TasteDeliberationInput(
        decision_id="taste-target",
        state_snapshot_id="state-target",
        stage="EXPERIMENT",
        current_actions=actions,
        decision_facts=facts,
        candidates=candidates,
        maximum_selected_cases=2,
    )
    supports = (
        TasteBoundarySupport(
            boundary_condition="Competing explanations remain live.",
            decision_fact_ids=("fact-competing",),
        ),
        TasteBoundarySupport(
            boundary_condition="A bounded diagnostic remains feasible.",
            decision_fact_ids=("fact-budget",),
        ),
    )
    semantics = (
        ScientificActionSemanticBinding(
            source_action_id="probe",
            target_action_id="probe",
            relation="aligned",
        ),
        ScientificActionSemanticBinding(
            source_action_id="experiment",
            target_action_id="experiment",
            relation="opposed",
        ),
    )
    bindings = tuple(
        ScientificSituationPrecedentBinding(
            source_study_id=source.study_id,
            target_taste_case_id=candidate.case_id,
            applicability_supports=supports,
            action_semantics=semantics,
            relevance_confidence=0.9,
            rationale="Both registered boundary conditions hold in the target state.",
        )
        for source, candidate in zip(sources, candidates, strict=True)
    )

    compilation = compile_scientific_situation_control_packet(
        target=target,
        sources=sources,
        decision=decision,
        input_data=input_data,
        bindings=bindings,
    )

    assert decision.selected_action == "probe"
    assert all(item.replicate_aware_uncertainty for item in decision.estimates)
    assert compilation.compilation_findings == ()
    assert compilation.packet.abstained is False
    assert compilation.packet.recommended_action_id == "probe"
    assert {item.case_id for item in compilation.packet.selected_precedents} == {
        "taste-one",
        "taste-two",
    }
