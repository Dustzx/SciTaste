from __future__ import annotations

from scitaste.discovery.evidence_to_idea import (
    ContradictoryPilotEvidence,
    EvidenceToIdeaEngine,
)
from scitaste.discovery.ideas import IdeaSeed
from scitaste.discovery.loop import DiscoveryLoop, load_discovery_scenario
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchStage, WorkingHypothesisStatus


def test_weak_intuition_is_probed_reformulated_and_matures(tmp_path) -> None:
    scenario = load_discovery_scenario("configs/experiments/discovery_weak.yaml")

    summary = DiscoveryLoop(seed=7).run(scenario, output_dir=tmp_path)
    state = StateStore(tmp_path).load()
    decisions = DecisionLogger(tmp_path / "decisions.jsonl").read_all()

    assert summary["trajectory_class"] == "evidence-first-like"
    assert summary["probe_count"] == 2
    assert summary["selected_actions"] == [
        "SEARCH",
        "FORM_INTUITION",
        "FORM_WORKING_HYPOTHESIS",
        "PROBE",
        "REFORMULATE_HYPOTHESIS",
        "PROBE",
        "VALIDATE_HYPOTHESIS",
        "FORMULATE_PROBLEM",
        "IDEATE",
        "SELECT_IDEA",
    ]
    assert state.working_hypotheses[0].status == WorkingHypothesisStatus.CONTRADICTED
    assert state.working_hypotheses[0].contradicting_evidence_ids
    assert state.working_hypotheses[1].derived_from_hypothesis_ids == [
        state.working_hypotheses[0].hypothesis_id
    ]
    assert state.observations[0].expected is False
    assert state.problem_candidates[0].supporting_evidence_ids == [
        item.observation_id for item in state.observations
    ]
    assert state.active_idea_id == state.idea_portfolio.primary_idea_id
    assert state.current_stage == ResearchStage.PILOT
    assert len(decisions) == state.revision
    assert all(decision.actual_outcome is not None for decision in decisions)


def test_strong_hypothesis_needs_only_one_sanity_probe(tmp_path) -> None:
    scenario = load_discovery_scenario("configs/experiments/discovery_strong.yaml")

    summary = DiscoveryLoop(seed=7).run(scenario, output_dir=tmp_path)
    state = StateStore(tmp_path).load()

    assert summary["trajectory_class"] == "idea-first-like"
    assert summary["probe_count"] == 1
    assert "REFORMULATE_HYPOTHESIS" not in summary["selected_actions"]
    assert summary["selected_actions"].count("PROBE") == 1
    assert state.working_hypotheses[0].status == WorkingHypothesisStatus.SUPPORTED
    assert state.current_stage == ResearchStage.PILOT


def test_contradictory_pilot_evidence_becomes_problem_and_idea() -> None:
    result = EvidenceToIdeaEngine().transform(
        ContradictoryPilotEvidence(
            pilot_id="pilot-17",
            idea_id="idea-original",
            expected="Performance improves uniformly across evidence conditions.",
            observed="Performance collapses only when support and contradiction are balanced.",
            stable=True,
            stability=0.9,
            boundary_conditions=["balanced conflicting evidence"],
            explanation_gap="The original scalar score cannot explain the boundary.",
            importance="The boundary predicts expensive incorrect research pivots.",
        ),
        idea_seed=IdeaSeed(
            generator="evidence-backed",
            hypothesis="Explicit conflict topology prevents collapse at the observed boundary.",
            proposed_mechanism="Represent support and contradiction as separate typed edges.",
            expected_validation=["matched boundary experiment"],
            expected_cost={"gpu_hours": 0.2},
            expected_value={"problem_validity": 0.95},
            main_risk="Edge labels may be noisy.",
        ),
    )

    assert result.observation.expected is False
    assert result.problem.supporting_evidence_ids == [result.observation.observation_id]
    assert result.idea.source_problem_ids == [result.problem.problem_id]
    assert result.idea.source_observation_ids == [result.observation.observation_id]
