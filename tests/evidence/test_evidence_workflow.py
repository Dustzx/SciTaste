from __future__ import annotations

from scitaste.discovery.loop import DiscoveryLoop, load_discovery_scenario
from scitaste.evidence.workflow import EvidenceWorkflow, load_evidence_scenario
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchStage


def test_supported_evidence_updates_state_and_advances_to_communication(tmp_path) -> None:
    scenario = load_evidence_scenario("configs/evidence/support_demo.yaml")

    summary = EvidenceWorkflow(seed=7).run(scenario, output_dir=tmp_path)
    state = StateStore(tmp_path).load()

    assert summary["claim_status"] == "supported"
    assert summary["route"] == "ADVANCE"
    assert state.claims[0].status == "supported"
    assert state.current_stage == ResearchStage.COMMUNICATION
    assert len(state.evidence_graph.items) == 1
    assert len(state.interpretation_history) == 1
    assert state.resource_usage.gpu_hours == 0.2
    assert state.resource_usage.experiments == 1.0


def test_stable_contradiction_pivots_without_discarding_evidence(tmp_path) -> None:
    scenario = load_evidence_scenario("configs/evidence/contradiction_demo.yaml")

    summary = EvidenceWorkflow(seed=7).run(scenario, output_dir=tmp_path)
    state = StateStore(tmp_path).load()

    assert summary["claim_status"] == "contradicted"
    assert summary["route"] == "PIVOT"
    assert state.current_stage == ResearchStage.PROBLEM_FORMULATION
    assert state.claims[0].contradicting_evidence_ids
    assert state.evidence_graph.items[0].contradicts_claim_ids == [state.claims[0].claim_id]
    assert state.active_problem_id == "problem-from-experiment-conflict-pilot"
    assert state.active_idea_id == "idea-from-experiment-conflict-pilot"
    assert len(DecisionLogger(tmp_path / "decisions.jsonl").read_all()) == 2


def test_phase4_pilot_state_can_resume_into_evidence_loop(tmp_path) -> None:
    discovery_dir = tmp_path / "discovery"
    evidence_dir = tmp_path / "evidence"
    DiscoveryLoop(seed=7).run(
        load_discovery_scenario("configs/experiments/discovery_strong.yaml"),
        output_dir=discovery_dir,
    )

    summary = EvidenceWorkflow(seed=7).run(
        load_evidence_scenario("configs/evidence/contradiction_demo.yaml"),
        output_dir=evidence_dir,
        state_path=discovery_dir / "research_state.json",
    )
    state = StateStore(evidence_dir).load()

    assert summary["selected_actions"][-4:] == [
        "PILOT",
        "ANALYZE",
        "COLLECT_EVIDENCE",
        "PIVOT",
    ]
    assert state.resource_usage.gpu_hours == 0.2
    assert state.resource_usage.experiments == 1.0
    assert state.current_stage == ResearchStage.PROBLEM_FORMULATION
