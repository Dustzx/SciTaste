from __future__ import annotations

import hashlib
from pathlib import Path

from scitaste.project import ProjectIdeaRevisionBinding
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.taste import (
    TasteCreditAssignment,
    TasteCreditDirection,
    TasteEpisodeEvidence,
    TasteEpisodeEvidenceRole,
    TasteEpisodeOutcome,
    TasteInterventionOperation,
    TasteOutcomeFamily,
    TasteOutcomePolarity,
    TasteSupervisionScope,
    compile_human_taste_intervention_candidate,
    compile_process_taste_episode_candidate,
    inspect_taste_episode_candidate,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _idea_binding(*, revision_id: str = "lifecycle-taste-candidate-01"):
    return ProjectIdeaRevisionBinding.create(
        project_id="episode-project",
        observed_project_revision=3,
        observed_project_snapshot_sha256="1" * 64,
        revision_id=revision_id,
        status="candidate",
        record_locator="runs/idea-run/idea_refinement/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=False,
        paper_claim_authority=False,
    )


def _decision(*, executed: bool = True) -> ResearchDecision:
    actions = [
        ResearchAction(
            action_id="probe-boundary",
            type=MetaAction.PROBE,
            description="Probe the uncertain boundary.",
        ),
        ResearchAction(
            action_id="scale-now",
            type=MetaAction.EXPERIMENT,
            description="Scale the current experiment immediately.",
        ),
    ]
    return ResearchDecision(
        decision_id="decision-01",
        stage="experiment",
        state_snapshot_id="state-01",
        candidate_actions=actions,
        selected_action=actions[0],
        rationale="The probe has higher information gain.",
        confidence=0.7,
        executor_result_id="result-01" if executed else None,
        actual_outcome={"boundary_resolved": True} if executed else None,
    )


def _evidence(tmp_path: Path, *, human: bool = False):
    decision = tmp_path / "decision.json"
    observation = tmp_path / ("intervention.json" if human else "outcome.json")
    decision.write_text('{"decision_id":"decision-01"}\n', encoding="utf-8")
    observation.write_text('{"boundary_resolved":true}\n', encoding="utf-8")
    return (
        TasteEpisodeEvidence(
            evidence_id="decision-evidence",
            role=TasteEpisodeEvidenceRole.DECISION,
            locator=decision.name,
            sha256=_sha(decision),
        ),
        TasteEpisodeEvidence(
            evidence_id="human-evidence" if human else "outcome-evidence",
            role=(
                TasteEpisodeEvidenceRole.HUMAN_INTERVENTION
                if human
                else TasteEpisodeEvidenceRole.OUTCOME
            ),
            locator=observation.name,
            sha256=_sha(observation),
        ),
    )


def test_process_taste_candidate_is_reviewable_but_cannot_update_policy(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    outcome = TasteEpisodeOutcome(
        outcome_id="resolved-boundary",
        family=TasteOutcomeFamily.DESIGN,
        summary="The probe isolated the unstable factor before scaling.",
        horizon="next experiment decision",
        polarity=TasteOutcomePolarity.SUPPORTS,
        evidence_ids=("outcome-evidence",),
    )
    credit = TasteCreditAssignment(
        credit_id="credit-probe",
        family=TasteOutcomeFamily.DESIGN,
        direction=TasteCreditDirection.BENEFICIAL,
        outcome_ids=(outcome.outcome_id,),
        rationale="The resolving observation was produced only by the selected probe.",
        confidence=0.7,
    )
    binding = _idea_binding()
    candidate = compile_process_taste_episode_candidate(
        _decision(),
        candidate_id="process-episode-01",
        project_id="episode-project",
        source_project_revision=4,
        source_project_snapshot_sha256="4" * 64,
        idea_revision=binding,
        producer_id="tool-intelligence-node-01",
        state_summary="One factor boundary is uncertain before a costly scale-up.",
        decision_principle="Probe a decision-reversing uncertainty before scaling.",
        why_preferred="The probe can distinguish whether scale-up is justified.",
        outcomes=(outcome,),
        credit_assignments=(credit,),
        applicability_conditions=("a cheap probe can reverse the scale decision",),
        failure_conditions=("the probe cannot distinguish the competing explanations",),
        counterfactual_probe="Scale directly if the boundary is already independently known.",
        evidence=evidence,
    )

    report = inspect_taste_episode_candidate(
        candidate,
        evidence_root=tmp_path,
        current_idea_revision=binding,
    )

    assert report.evidence_verified is True
    assert report.current_idea_revision_matches is True
    assert report.ready_for_independent_review is True
    assert report.retrieval_eligible is False
    assert report.policy_update_authorized is False
    assert report.findings == ()


def test_changed_idea_revision_makes_process_episode_stale(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    outcome = TasteEpisodeOutcome(
        outcome_id="resolved-boundary",
        family=TasteOutcomeFamily.DESIGN,
        summary="The boundary was resolved.",
        horizon="next decision",
        polarity=TasteOutcomePolarity.SUPPORTS,
        evidence_ids=("outcome-evidence",),
    )
    candidate = compile_process_taste_episode_candidate(
        _decision(),
        candidate_id="process-episode-01",
        project_id="episode-project",
        source_project_revision=4,
        source_project_snapshot_sha256="4" * 64,
        idea_revision=_idea_binding(),
        producer_id="tool-intelligence-node-01",
        state_summary="A boundary is uncertain.",
        decision_principle="Probe before scaling.",
        why_preferred="The probe is diagnostic.",
        outcomes=(outcome,),
        credit_assignments=(
            TasteCreditAssignment(
                credit_id="credit-probe",
                family=TasteOutcomeFamily.DESIGN,
                direction=TasteCreditDirection.BENEFICIAL,
                outcome_ids=(outcome.outcome_id,),
                rationale="The probe resolved the boundary.",
                confidence=0.7,
            ),
        ),
        applicability_conditions=("the probe is diagnostic",),
        failure_conditions=("the probe is nondiagnostic",),
        counterfactual_probe="Do not probe when the boundary is already known.",
        evidence=evidence,
    )

    report = inspect_taste_episode_candidate(
        candidate,
        evidence_root=tmp_path,
        current_idea_revision=_idea_binding(revision_id="lifecycle-taste-candidate-02"),
    )

    assert report.current_idea_revision_matches is False
    assert report.ready_for_independent_review is False
    assert {finding.code for finding in report.findings} == {"idea-revision-stale"}


def test_gac_intervention_waits_for_outcome_and_stays_project_scoped(tmp_path: Path) -> None:
    binding = _idea_binding()
    candidate = compile_human_taste_intervention_candidate(
        _decision(executed=False),
        candidate_id="human-episode-01",
        project_id="episode-project",
        source_project_revision=4,
        source_project_snapshot_sha256="4" * 64,
        idea_revision=binding,
        producer_id="generation-as-content-turn-01",
        operation=TasteInterventionOperation.REPRIORITIZE,
        supervision_scope=TasteSupervisionScope.PROJECT,
        state_summary="The user prioritizes a diagnostic experiment.",
        decision_principle="Resolve the causal ambiguity before scaling.",
        why_preferred="The current result cannot distinguish two explanations.",
        applicability_conditions=("the ambiguity changes the next experiment",),
        failure_conditions=("the distinction has no bearing on the claim",),
        counterfactual_probe=(
            "Reverse this preference if both explanations predict the same result."
        ),
        evidence=_evidence(tmp_path, human=True),
    )

    report = inspect_taste_episode_candidate(
        candidate,
        evidence_root=tmp_path,
        current_idea_revision=binding,
    )

    assert candidate.supervision_scope is TasteSupervisionScope.PROJECT
    assert report.evidence_verified is True
    assert report.attribution_proposed is False
    assert report.ready_for_independent_review is False
    assert {finding.code for finding in report.findings} == {"outcome-attribution-pending"}
