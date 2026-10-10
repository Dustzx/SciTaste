from __future__ import annotations

from types import SimpleNamespace

import pytest

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodSubmission,
    compile_decision_case,
)
from scitaste.evaluation.taste_evolution import (
    TasteEvolutionPlan,
    TasteEvolutionRound,
    TasteEvolutionTransfer,
    evaluate_taste_evolution_transfer,
    select_taste_evolution_round,
)

PARENT = "a" * 64
CANDIDATE = "b" * 64
NEXT_CANDIDATE = "c" * 64


def _case(group: str, prefix: str) -> SimpleNamespace:
    situation = SimpleNamespace(
        prefix_sha256=prefix * 64,
        hypothesis_structure=SimpleNamespace(value="competing-candidates"),
        evidence_relation=SimpleNamespace(value="underdetermined"),
        bottleneck=SimpleNamespace(value="functional-form-discrimination"),
        identifiability=SimpleNamespace(value="medium"),
        budget_pressure=SimpleNamespace(value="medium"),
        terminal_readiness=SimpleNamespace(value="not-ready"),
        decision_basis="Choose the next discriminative experiment.",
        anchors=(SimpleNamespace(quote="two competing explanations"),),
    )
    return SimpleNamespace(
        situation=situation,
        action_semantics_sha256="e" * 64,
        action_definitions=tuple(
            SimpleNamespace(action_id=item, semantic_role=item, description=f"Run {item}")
            for item in ("A", "B")
        ),
        execution_contract=SimpleNamespace(
            resource_limits={"max_experiments": 2.0},
            maximum_steps=2,
            timeout_seconds=120,
            contract_sha256="c" * 64,
        ),
        scorer_contract=SimpleNamespace(
            intention_to_treat_failure_utility=0.0,
            practical_equivalence_tolerance=0.0,
            contract_sha256="d" * 64,
        ),
        task_cluster_id=group,
        action_utility_estimates={"A": 0.2, "B": 0.8},
    )


def _plan(
    *,
    generation: int = 1,
    predecessor: TasteEvolutionRound | None = None,
    candidate: str = CANDIDATE,
    selection: tuple[str, ...] = ("selection-a", "selection-b"),
) -> TasteEvolutionPlan:
    return TasteEvolutionPlan.create(
        project_id="research-project",
        generation=generation,
        predecessor_round_sha256=None if predecessor is None else predecessor.round_sha256,
        parent_policy_sha256=(
            PARENT if predecessor is None else predecessor.active_development_policy_sha256
        ),
        candidate_policy_sha256=candidate,
        candidate_training_task_groups=("learning-a",),
        selection_task_groups=selection,
        reserved_transfer_task_groups=(f"transfer-{generation}",),
        minimum_mean_regret_reduction=0.01,
    )


def _run(
    plan: TasteEvolutionPlan,
    *,
    candidate_action: str = "B",
    predecessor: TasteEvolutionRound | None = None,
) -> TasteEvolutionRound:
    pairs = tuple(
        compile_decision_case(_case(group, prefix), native_action_id="A")
        for group, prefix in zip(plan.selection_task_groups, "fghijkl", strict=False)
    )
    requests = tuple(item[0] for item in pairs)
    keys = tuple(item[1] for item in pairs)
    parent_decisions = tuple(
        DecisionMethodSubmission(
            method_id="parent",
            method_manifest_sha256=plan.parent_policy_sha256,
            request_sha256=request.request_sha256,
            selected_action_id="A",
            input_tokens=0,
            output_tokens=0,
            inference_cost_usd=0.0,
        )
        for request in requests
    )
    candidate_decisions = tuple(
        DecisionMethodSubmission(
            method_id="candidate",
            method_manifest_sha256=plan.candidate_policy_sha256,
            request_sha256=request.request_sha256,
            selected_action_id=candidate_action,
            input_tokens=0,
            output_tokens=0,
            inference_cost_usd=0.0,
        )
        for request in requests
    )
    return select_taste_evolution_round(
        plan, requests, keys, parent_decisions, candidate_decisions, predecessor=predecessor
    )


def test_accepts_changed_policy_and_rejects_non_improvement() -> None:
    accepted = _run(_plan())
    assert accepted.disposition == "accepted"
    assert accepted.active_development_policy_sha256 == CANDIDATE
    assert accepted.mean_task_regret_reduction == pytest.approx(0.6)
    assert not accepted.rsi_effect_claim_authorized
    assert not accepted.deployed_policy_changed
    assert TasteEvolutionRound.model_validate_json(accepted.model_dump_json()) == accepted

    second = _run(
        _plan(
            generation=2,
            predecessor=accepted,
            candidate=NEXT_CANDIDATE,
            selection=("selection-c", "selection-d"),
        ),
        candidate_action="A",
        predecessor=accepted,
    )
    assert second.disposition == "rejected"
    assert second.active_development_policy_sha256 == CANDIDATE
    assert len(second.used_selection_task_groups) == 4


def test_rejects_leakage_and_lineage_reuse() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        _plan(selection=("learning-a", "selection-b"))
    first = _run(_plan())
    with pytest.raises(ValueError, match="reuse a selection task"):
        _run(
            _plan(
                generation=2,
                predecessor=first,
                candidate=NEXT_CANDIDATE,
                selection=("selection-a", "selection-c"),
            ),
            predecessor=first,
        )
    with pytest.raises(ValueError, match="active lineage"):
        stale = _plan(
            generation=2,
            predecessor=first,
            candidate=NEXT_CANDIDATE,
            selection=("selection-c", "selection-d"),
        ).model_copy(update={"parent_policy_sha256": PARENT})
        _run(stale, predecessor=first)
    with pytest.raises(ValueError, match="reserved transfer task"):
        _run(
            _plan(
                generation=2,
                predecessor=first,
                candidate=NEXT_CANDIDATE,
                selection=("selection-c", "transfer-1"),
            ),
            predecessor=first,
        )


def test_transfer_uses_reserved_tasks_without_changing_selection() -> None:
    selected = _run(_plan())
    request, key = compile_decision_case(_case("transfer-1", "z"), native_action_id="A")
    decisions = tuple(
        DecisionMethodSubmission(
            method_id=label,
            method_manifest_sha256=policy_hash,
            request_sha256=request.request_sha256,
            selected_action_id=action,
            input_tokens=0,
            output_tokens=0,
            inference_cost_usd=0.0,
        )
        for label, policy_hash, action in (
            ("parent", PARENT, "A"),
            ("candidate", CANDIDATE, "B"),
        )
    )
    transfer = evaluate_taste_evolution_transfer(
        selected, (request,), (key,), (decisions[0],), (decisions[1],)
    )
    assert transfer.mean_task_regret_reduction == pytest.approx(0.6)
    assert transfer.selection_unchanged
    assert not transfer.rsi_effect_claim_authorized
    assert TasteEvolutionTransfer.model_validate_json(transfer.model_dump_json()) == transfer
    with pytest.raises(ValueError, match="reserved groups"):
        evaluate_taste_evolution_transfer(
            selected,
            (request,),
            (key.model_copy(update={"task_cluster_id": "selection-a"}),),
            (decisions[0],),
            (decisions[1],),
        )
