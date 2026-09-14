from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scitaste.project import ProjectIdeaRevisionBinding
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.taste import (
    LifecycleTastePolicyConfig,
    LifecycleTastePolicyUpdateMode,
    TasteAttributionReviewRole,
    TasteAttributionReviewVerdict,
    TasteController,
    TasteCreditAssignment,
    TasteCreditDirection,
    TasteEpisodeAttributionReview,
    TasteEpisodeEvidence,
    TasteEpisodeEvidenceRole,
    TasteEpisodeOutcome,
    TasteOutcomeFamily,
    TasteOutcomePolarity,
    admit_taste_episode,
    assess_lifecycle_taste_policy,
    compile_process_taste_episode_candidate,
    fit_lifecycle_taste_policy,
    inspect_taste_episode_admission,
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


def _actions() -> tuple[ResearchAction, ResearchAction]:
    return (
        ResearchAction(
            action_id="probe-boundary",
            type=MetaAction.PROBE,
            description="Probe the decision-reversing uncertainty.",
            expected_value={"information_gain": 0.2},
            tags=["diagnostic"],
        ),
        ResearchAction(
            action_id="scale-now",
            type=MetaAction.ADVANCE,
            description="Scale the current method immediately.",
            expected_value={"scientific_importance": 0.5},
            tags=["scale"],
        ),
    )


def _candidate(
    tmp_path: Path,
    ordinal: int,
    *,
    polarity: TasteOutcomePolarity = TasteOutcomePolarity.SUPPORTS,
):
    actions = _actions()
    decision = ResearchDecision(
        decision_id=f"decision-{ordinal:02d}",
        stage="DISCOVERY",
        state_snapshot_id=f"state-{ordinal:02d}",
        candidate_actions=list(actions),
        selected_action=actions[0],
        rationale="The probe has higher information gain.",
        confidence=0.8,
        executor_result_id=f"result-{ordinal:02d}",
        actual_outcome={"boundary_resolved": polarity is TasteOutcomePolarity.SUPPORTS},
    )
    decision_path = tmp_path / f"decision-{ordinal:02d}.json"
    outcome_path = tmp_path / f"outcome-{ordinal:02d}.json"
    decision_path.write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
    outcome_path.write_text(
        '{"boundary_resolved":true}\n'
        if polarity is TasteOutcomePolarity.SUPPORTS
        else '{"boundary_resolved":false}\n',
        encoding="utf-8",
    )
    outcome = TasteEpisodeOutcome(
        outcome_id=f"outcome-{ordinal:02d}",
        family=TasteOutcomeFamily.DESIGN,
        summary="The decision boundary was resolved.",
        horizon="next research decision",
        polarity=polarity,
        evidence_ids=(f"outcome-evidence-{ordinal:02d}",),
    )
    credit = TasteCreditAssignment(
        credit_id=f"credit-{ordinal:02d}",
        family=TasteOutcomeFamily.DESIGN,
        direction=(
            TasteCreditDirection.BENEFICIAL
            if polarity is TasteOutcomePolarity.SUPPORTS
            else TasteCreditDirection.HARMFUL
        ),
        outcome_ids=(outcome.outcome_id,),
        rationale="The selected action produced the decision-relevant observation.",
        confidence=0.9,
    )
    return compile_process_taste_episode_candidate(
        decision,
        candidate_id=f"process-episode-{ordinal:02d}",
        project_id="episode-project",
        source_project_revision=4 + ordinal,
        source_project_snapshot_sha256=f"{ordinal % 10}" * 64,
        idea_revision=_idea_binding(),
        producer_id=f"process-taste-miner-{ordinal:02d}",
        state_summary="A decision-reversing boundary is unresolved before scaling.",
        decision_principle="Probe a cheap decisive uncertainty before scale-up.",
        why_preferred="The probe can change whether scale-up is justified.",
        outcomes=(outcome,),
        credit_assignments=(credit,),
        applicability_conditions=("a cheap probe can reverse the scale decision",),
        failure_conditions=("the probe cannot distinguish the explanations",),
        counterfactual_probe="Advance directly if the boundary is independently established.",
        evidence=(
            TasteEpisodeEvidence(
                evidence_id=f"decision-evidence-{ordinal:02d}",
                role=TasteEpisodeEvidenceRole.DECISION,
                locator=decision_path.name,
                sha256=_sha(decision_path),
            ),
            TasteEpisodeEvidence(
                evidence_id=f"outcome-evidence-{ordinal:02d}",
                role=TasteEpisodeEvidenceRole.OUTCOME,
                locator=outcome_path.name,
                sha256=_sha(outcome_path),
            ),
        ),
        domain_tags=("testing",),
        venue_tags=("ICLR",),
    )


def _review(
    candidate,
    *,
    reviewer_id: str,
    preferred_action_id: str = "probe-boundary",
    role: TasteAttributionReviewRole = TasteAttributionReviewRole.PRIMARY,
    verdict: TasteAttributionReviewVerdict = TasteAttributionReviewVerdict.ACCEPT,
):
    accepted = verdict is TasteAttributionReviewVerdict.ACCEPT
    return TasteEpisodeAttributionReview(
        review_id=f"review-{candidate.candidate_id}-{reviewer_id}",
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        idea_revision_binding_sha256=candidate.idea_revision.binding_sha256,
        reviewer_id=reviewer_id,
        role=role,
        verdict=verdict,
        preferred_action_id=preferred_action_id if accepted else None,
        supported_credit_ids=(candidate.credit_assignments[0].credit_id,) if accepted else (),
        decision_trace_supported=True,
        outcome_trace_supported=True,
        alternatives_supported=True,
        credit_assignment_supported=accepted,
        transfer_scope_supported=True,
        reversal_probe_supported=True,
        attribution_confidence=0.9 if accepted else 0.2,
        rationale=(
            "The decision, delayed outcome, and counterfactual support this preference."
            if accepted
            else "The causal credit is not supported."
        ),
        reviewed_at=datetime(2026, 9, 14, tzinfo=UTC),
    )


def _admitted(
    tmp_path: Path,
    ordinal: int,
    *,
    preferred: str = "probe-boundary",
    polarity: TasteOutcomePolarity = TasteOutcomePolarity.SUPPORTS,
):
    candidate = _candidate(tmp_path, ordinal, polarity=polarity)
    reviews = (
        _review(candidate, reviewer_id=f"reviewer-a-{ordinal:02d}", preferred_action_id=preferred),
        _review(candidate, reviewer_id=f"reviewer-b-{ordinal:02d}", preferred_action_id=preferred),
    )
    return admit_taste_episode(
        candidate,
        reviews,
        admission_id=f"admitted-episode-{ordinal:02d}",
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )


def _policy(tmp_path: Path, *, mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED):
    episodes = tuple(_admitted(tmp_path, ordinal) for ordinal in range(1, 9))
    config = LifecycleTastePolicyConfig(
        policy_id=f"policy-{mode.value}",
        update_mode=mode,
        idea_revision=_idea_binding(),
        minimum_feature_support=3.0,
        require_stage_support=True,
        allow_cross_domain=False,
        shuffle_seed=17 if mode is LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT else 0,
    )
    return fit_lifecycle_taste_policy(episodes, config)


def test_two_independent_reviews_admit_one_training_episode(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    reviews = (
        _review(candidate, reviewer_id="reviewer-a"),
        _review(candidate, reviewer_id="reviewer-b"),
    )

    report = inspect_taste_episode_admission(
        candidate,
        reviews,
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )
    admitted = admit_taste_episode(
        candidate,
        reviews,
        admission_id="admitted-episode-01",
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    assert report.ready_for_policy_training is True
    assert report.preferred_action_id == "probe-boundary"
    assert admitted.policy_training_eligible is True
    assert admitted.policy_update_authorized is False
    assert admitted.training_weight == 0.9


def test_split_preference_requires_independent_adjudication(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    split = (
        _review(candidate, reviewer_id="reviewer-a"),
        _review(candidate, reviewer_id="reviewer-b", preferred_action_id="scale-now"),
    )

    before = inspect_taste_episode_admission(
        candidate,
        split,
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )
    adjudicated = inspect_taste_episode_admission(
        candidate,
        (
            *split,
            _review(
                candidate,
                reviewer_id="reviewer-c",
                preferred_action_id="probe-boundary",
                role=TasteAttributionReviewRole.ADJUDICATOR,
            ),
        ),
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    assert before.ready_for_policy_training is False
    assert {item.code for item in before.findings} == {"adjudication-required"}
    assert adjudicated.ready_for_policy_training is True
    assert adjudicated.preferred_action_id == "probe-boundary"


def test_episode_producer_cannot_review_its_own_credit(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    report = inspect_taste_episode_admission(
        candidate,
        (
            _review(candidate, reviewer_id=candidate.producer_id),
            _review(candidate, reviewer_id="reviewer-b"),
        ),
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    assert report.ready_for_policy_training is False
    assert "producer-review-conflict" in {item.code for item in report.findings}


def test_outcome_updated_policy_learns_preference_and_no_update_abstains(
    tmp_path: Path,
    research_state,
) -> None:
    learned = _policy(tmp_path)
    no_update = _policy(tmp_path, mode=LifecycleTastePolicyUpdateMode.NO_UPDATE)

    assessment = assess_lifecycle_taste_policy(
        learned,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(),
    )
    control = assess_lifecycle_taste_policy(
        no_update,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(),
    )

    assert learned.training_episode_count == 8
    assert learned.pairwise_comparison_count == 8
    assert assessment.abstained is False
    assert assessment.recommended_action_id == "probe-boundary"
    assert assessment.pairwise_probability is not None
    assert assessment.pairwise_probability > 0.9
    assert no_update.training_episode_count == 0
    assert control.abstained is True
    assert control.reason_codes == ("no-update-control",)


def test_shuffled_credit_control_reverses_two_action_training_labels(
    tmp_path: Path,
    research_state,
) -> None:
    shuffled = _policy(tmp_path, mode=LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT)

    assessment = assess_lifecycle_taste_policy(
        shuffled,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(),
    )

    assert assessment.abstained is False
    assert assessment.recommended_action_id == "scale-now"


def test_policy_abstains_without_current_idea_or_after_idea_revision(
    tmp_path: Path,
    research_state,
) -> None:
    policy = _policy(tmp_path)

    unverified = assess_lifecycle_taste_policy(
        policy,
        state=research_state,
        actions=_actions(),
    )
    stale = assess_lifecycle_taste_policy(
        policy,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(revision_id="lifecycle-taste-candidate-02"),
    )

    assert unverified.abstained is True
    assert unverified.reason_codes == ("idea-revision-unverified",)
    assert all(item.adjustment == 0.0 for item in unverified.action_scores)
    assert stale.abstained is True
    assert stale.reason_codes == ("idea-revision-stale",)
    assert stale.observed_idea_revision_id == "lifecycle-taste-candidate-02"


def test_success_and_failure_controls_use_disjoint_outcome_episodes(tmp_path: Path) -> None:
    episodes = (
        _admitted(tmp_path, 1, polarity=TasteOutcomePolarity.SUPPORTS),
        _admitted(tmp_path, 2, polarity=TasteOutcomePolarity.CHALLENGES),
    )
    success = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="success-only-policy",
            update_mode=LifecycleTastePolicyUpdateMode.SUCCESS_ONLY,
            idea_revision=_idea_binding(),
        ),
    )
    failure = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="failure-only-policy",
            update_mode=LifecycleTastePolicyUpdateMode.FAILURE_ONLY,
            idea_revision=_idea_binding(),
        ),
    )

    assert success.training_episode_ids == ("admitted-episode-01",)
    assert failure.training_episode_ids == ("admitted-episode-02",)


def test_policy_update_rejects_episode_from_another_idea_revision(tmp_path: Path) -> None:
    episode = _admitted(tmp_path, 1)
    config = LifecycleTastePolicyConfig(
        policy_id="stale-policy",
        update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
        idea_revision=_idea_binding(revision_id="lifecycle-taste-candidate-02"),
    )

    with pytest.raises(ValueError, match="another Idea revision"):
        fit_lifecycle_taste_policy((episode,), config)


def test_controller_applies_learned_policy_and_records_exact_trace(
    tmp_path: Path,
    research_state,
) -> None:
    policy = _policy(tmp_path)
    baseline = TasteController(seed=3, critics_enabled=False).decide(
        state=research_state,
        candidate_actions=_actions(),
    )
    learned = TasteController(
        seed=3,
        critics_enabled=False,
        lifecycle_policy=policy,
        lifecycle_policy_weight=2.0,
    ).decide(
        state=research_state,
        candidate_actions=_actions(),
        current_idea_revision=_idea_binding(),
    )

    assert baseline.selected_action.action_id == "scale-now"
    assert learned.selected_action.action_id == "probe-boundary"
    assert learned.lifecycle_taste_policy is not None
    assert learned.lifecycle_taste_policy.policy_sha256 == policy.policy_sha256
    assert learned.lifecycle_taste_policy.abstained is False
    assert learned.lifecycle_taste_policy.recommended_action_id == "probe-boundary"
    assert "Learned lifecycle Taste applied" in learned.rationale
