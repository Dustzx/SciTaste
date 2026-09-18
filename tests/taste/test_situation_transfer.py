from __future__ import annotations

from scitaste.evaluation.scientific_situation_transfer import (
    BudgetPressure,
    EvidenceRelation,
    FormalObjectiveForkSituationCase,
    HypothesisStructure,
    IdentifiabilityBand,
    ObjectiveForkActionDefinition,
    ObjectiveForkConstructionManifest,
    ObjectiveForkExecutionContract,
    ObjectiveForkReplicateOutcome,
    ObjectiveForkScorerContract,
    ObjectiveForkTaskBinding,
    ScientificActionSemanticBinding,
    ScientificBottleneck,
    ScientificSituation,
    ScientificSituationActionMap,
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


def _action_definition(action_id: str, role: str) -> ObjectiveForkActionDefinition:
    return ObjectiveForkActionDefinition.create(
        action_id=action_id,
        semantic_role=role,
        description=f"Execute the registered {role} intervention.",
        executor_id="fixture-executor-v1",
        command_template=("fixture", "--action", action_id, "--seed", "{seed_block_id}"),
    )


def _formal_case(study_id: str, task_cluster_id: str, suffix: str):
    utilities = {"diagnostic": (0.8, 0.9, 0.85), "scale": (0.2, 0.3, 0.25)}
    definitions = (
        _action_definition("diagnostic", "bounded diagnostic"),
        _action_definition("scale", "full experiment"),
    )
    definition_hashes = {item.action_id: item.definition_sha256 for item in definitions}
    outcomes = tuple(
        ObjectiveForkReplicateOutcome.create(
            action_id=action,
            replicate_id=f"{study_id}-{action}-seed-{index}",
            seed_block_id=f"seed-{index}",
            requested_action_definition_sha256=definition_hashes[action],
            action_compliance="compliant",
            action_trace_sha256=suffix * 64,
            executed=True,
            objective_observed=True,
            raw_metric_value=value,
            utility=value,
        )
        for action, values in utilities.items()
        for index, value in enumerate(values)
    )
    return FormalObjectiveForkSituationCase.create(
        study_id=study_id,
        task_cluster_id=task_cluster_id,
        situation=_situation(study_id, task_cluster_id),
        task_binding=ObjectiveForkTaskBinding(
            task_locator=f"fixture://{study_id}",
            task_sha256="4" * 64,
            environment_sha256="5" * 64,
            code_sha256="6" * 64,
            prefix_state_sha256=_situation(study_id, task_cluster_id).prefix_sha256,
            split_assignment="development",
        ),
        available_actions=("diagnostic", "scale"),
        action_definitions=definitions,
        execution_contract=ObjectiveForkExecutionContract.create(
            contract_id="paired-budget-v1",
            allowed_tools=("fixture-tool",),
            budget_limit=100.0,
            budget_unit="tokens",
            maximum_steps=10,
            timeout_seconds=60,
            network_access=False,
            seed_block_ids=("seed-0", "seed-1", "seed-2"),
            minimum_action_compliance_rate=0.8,
        ),
        scorer_contract=ObjectiveForkScorerContract.create(
            scorer_id="fixture-scorer-v1",
            implementation_sha256="7" * 64,
            metric_name="objective score",
            metric_direction="higher",
            raw_scale_minimum=0.0,
            raw_scale_maximum=1.0,
            utility_contract_id="shared-utility-v1",
            practical_equivalence_tolerance=0.05,
            intention_to_treat_failure_utility=0.0,
        ),
        construction_manifest=ObjectiveForkConstructionManifest.create(
            source_collection_id="fixture-source",
            source_version="v1",
            construction_protocol_sha256="8" * 64,
            constructor_provider="fixture",
            constructor_model="fixture",
            split_assignment="development",
            contamination_audit_protocol="exact ID and semantic overlap audit v1",
            contamination_corpora=("fixture-training-corpus",),
            contamination_report_sha256="9" * 64,
        ),
        replicate_outcomes=outcomes,
    )


def _action_map(source: FormalObjectiveForkSituationCase) -> ScientificSituationActionMap:
    source_definitions = {item.action_id: item for item in source.action_definitions}
    target_definitions = {
        "experiment": _action_definition("experiment", "full experiment"),
        "probe": _action_definition("probe", "bounded diagnostic"),
    }
    return ScientificSituationActionMap.create(
        source_study_id=source.study_id,
        bindings=(
            ScientificActionSemanticBinding(
                source_action_id="scale",
                source_action_definition_sha256=source_definitions["scale"].definition_sha256,
                target_action=target_definitions["experiment"],
                mapping_rationale="Both actions commit the full remaining budget.",
                boundary_conditions=("The full-budget action is feasible.",),
                mapping_confidence=0.95,
            ),
            ScientificActionSemanticBinding(
                source_action_id="diagnostic",
                source_action_definition_sha256=source_definitions[
                    "diagnostic"
                ].definition_sha256,
                target_action=target_definitions["probe"],
                mapping_rationale="Both actions run a bounded uncertainty-resolving probe.",
                boundary_conditions=("Competing explanations remain live.",),
                mapping_confidence=0.95,
            ),
        ),
        adjudicator_provider="fixture",
        adjudicator_model="fixture",
        request_fingerprint="a" * 64,
        response_sha256="b" * 64,
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
    action_maps = tuple(_action_map(source) for source in sources)
    decision = select_by_scientific_situation(
        target=target,
        sources=sources,
        available_actions={"probe", "experiment"},
        thresholds=ScientificSituationTransferThresholds(
            require_formal_sources=True,
            minimum_effective_support=2.0,
            maximum_standard_error=0.2,
        ),
        action_maps=action_maps,
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
    bindings = tuple(
        ScientificSituationPrecedentBinding(
            source_study_id=source.study_id,
            target_taste_case_id=candidate.case_id,
            applicability_supports=supports,
            action_map=action_map,
            relevance_confidence=0.9,
            rationale="Both registered boundary conditions hold in the target state.",
        )
        for source, candidate, action_map in zip(
            sources,
            candidates,
            action_maps,
            strict=True,
        )
    )

    compilation = compile_scientific_situation_control_packet(
        target=target,
        sources=sources,
        decision=decision,
        input_data=input_data,
        bindings=bindings,
    )

    assert decision.selected_action == "probe"
    assert decision.contrast_uncertainty_method == "paired-seed-block-task-clustered"
    assert decision.minimum_paired_seed_blocks == 3
    assert all(item.replicate_aware_uncertainty for item in decision.estimates)
    assert compilation.compilation_findings == ()
    assert compilation.packet.abstained is False
    assert compilation.packet.recommended_action_id == "probe"
    assert {item.case_id for item in compilation.packet.selected_precedents} == {
        "taste-one",
        "taste-two",
    }


def test_formal_transfer_refuses_post_selection_action_interpretation() -> None:
    target = _situation("target-study", "target-cluster")
    decision = select_by_scientific_situation(
        target=target,
        sources=(
            _formal_case("source-one", "cluster-one", "2"),
            _formal_case("source-two", "cluster-two", "3"),
        ),
        available_actions={"probe", "experiment"},
        thresholds=ScientificSituationTransferThresholds(require_formal_sources=True),
    )

    assert decision.abstained is True
    assert decision.abstention_reasons == ("no-validated-preselection-action-map",)
    assert decision.estimates == ()
