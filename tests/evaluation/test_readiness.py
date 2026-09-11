from __future__ import annotations

from pathlib import Path

from scitaste.evaluation import (
    EvaluationDecisionGate,
    EvaluationDecisionGateState,
    prepare_project_evaluation,
    summarize_evaluation_readiness,
)
from scitaste.project import ProjectEvaluationBundle
from scitaste.project.models import content_sha256

CORPUS = Path("docs/research/data/autoresearch_evaluation_resources_v2.yaml")


def _prepare(name: str, manifest: str) -> ProjectEvaluationBundle:
    return prepare_project_evaluation(
        project_id="decision-map-project",
        evaluation_id=name,
        manifest_path=manifest,
        resource_corpus_path=CORPUS,
        source_root=Path("."),
        evidence_root=Path("."),
    ).bundle


def _gate_map(bundle: ProjectEvaluationBundle):
    decision_map = summarize_evaluation_readiness(bundle)
    return decision_map, {item.gate_id: item for item in decision_map.gates}


def _replace_bundle(bundle: ProjectEvaluationBundle, **changes: object) -> ProjectEvaluationBundle:
    payload = bundle.model_dump(mode="json", exclude={"bundle_sha256"})
    payload.update(changes)
    payload["bundle_sha256"] = content_sha256(payload)
    return ProjectEvaluationBundle.model_validate(payload)


def test_decision_map_collapses_repeated_deepseek_diagnostics() -> None:
    bundle = _prepare(
        "deepseek-decision-map",
        "configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml",
    )

    decision_map, gates = _gate_map(bundle)

    expected_diagnostics = set(
        (
            *bundle.readiness_blocker_codes,
            *bundle.authorization_blocker_codes,
            *bundle.critic_blocking_codes,
            *bundle.cell_plan_blockers,
        )
    )
    assert decision_map.diagnostic_blocker_count == len(expected_diagnostics)
    assert decision_map.decision_blocker_count == 6
    assert decision_map.next_gate_id is EvaluationDecisionGate.TASK_SCOPE
    assert decision_map.unclassified_codes == ()
    assert gates[EvaluationDecisionGate.TASK_SCOPE].state is EvaluationDecisionGateState.BLOCKED
    assert len(gates[EvaluationDecisionGate.TASK_SCOPE].affected_ids) == 10
    assert len(gates[EvaluationDecisionGate.COMPARATOR_ADAPTERS].affected_ids) == 4
    assert (
        gates[EvaluationDecisionGate.RUNTIME_RESOURCES].state
        is EvaluationDecisionGateState.SATISFIED
    )
    assert decision_map.no_execution_performed is True


def test_api_pricing_and_remote_gpu_inventory_remain_visible_resource_gates() -> None:
    zhipu = _prepare(
        "zhipu-decision-map",
        "configs/evaluation/prelaunch/zhipu_glm53flash_pilot_v1.yaml",
    )
    gpu = _prepare(
        "gpu-decision-map",
        "configs/evaluation/prelaunch/qwen3vl2b_8x3090_robustness_v1.yaml",
    )

    for bundle in (zhipu, gpu):
        decision_map, gates = _gate_map(bundle)
        resource_gate = gates[EvaluationDecisionGate.RUNTIME_RESOURCES]
        assert resource_gate.state is EvaluationDecisionGateState.BLOCKED
        assert resource_gate.issue_count > 0
        assert decision_map.unclassified_codes == ()


def test_owner_approval_is_separate_from_scientific_readiness() -> None:
    source = _prepare(
        "approval-decision-map",
        "configs/evaluation/prelaunch/deepseek_v41flash_pilot_v2.yaml",
    )
    awaiting = _replace_bundle(
        source,
        status="awaiting_author_approval",
        ready_for_author_review=True,
        execution_authorized=False,
        readiness_blocker_codes=[],
        authorization_blocker_codes=["author_approval_required"],
        critic_blocking_codes=[],
        cell_plan_blockers=[],
    )
    awaiting_map, awaiting_gates = _gate_map(awaiting)
    assert awaiting_map.decision_blocker_count == 1
    assert awaiting_map.next_gate_id is EvaluationDecisionGate.OWNER_APPROVAL
    assert (
        awaiting_gates[EvaluationDecisionGate.OWNER_APPROVAL].state
        is EvaluationDecisionGateState.AWAITING_APPROVAL
    )

    authorized = _replace_bundle(
        awaiting,
        status="execution_authorized",
        execution_authorized=True,
        authorization_blocker_codes=[],
    )
    authorized_map, authorized_gates = _gate_map(authorized)
    assert authorized_map.decision_blocker_count == 0
    assert authorized_map.next_gate_id is None
    assert all(
        gate.state is EvaluationDecisionGateState.SATISFIED for gate in authorized_gates.values()
    )
