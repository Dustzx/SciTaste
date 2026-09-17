from datetime import UTC, datetime, timedelta

from scitaste.evidence.venue_gap import (
    AcceptedNearestNeighbour,
    AcceptedNeighbourEvidenceProfile,
    AcceptedPaperKind,
    CurrentEvidenceComponentBinding,
    EvidenceDirection,
    EvidenceMaturity,
    SubmissionEvidencePosition,
    VenueClaimCentrality,
    VenueClaimEvidenceContract,
    VenueComparisonProfile,
    VenueContributionAxis,
    VenueEvidenceComponent,
    VenueEvidenceCriterion,
    VenueEvidenceScaleFact,
    VenueEvidenceScaleMetric,
    VenueEvidenceScaleStatus,
    VenueEvidenceSignal,
    VenueGapAction,
    VenueGapActionKind,
    VenueGapDimension,
    VenueGapManifest,
    VenueInnovationClaim,
    VenueInnovationEvidenceStatus,
    assess_venue_gap,
)
from scitaste.project.deadlines import (
    ProjectDeadlineStatus,
    ProjectVenueMilestoneStatus,
    VenueMilestoneKind,
)


def test_single_development_result_cannot_mark_top_venue_program_ready() -> None:
    dimensions = tuple(sorted(VenueGapDimension, key=lambda item: item.value))
    empirical = tuple(
        dimension
        for dimension in dimensions
        if dimension is not VenueGapDimension.NARRATIVE_CONTRIBUTION
    )
    neighbours = tuple(
        AcceptedNearestNeighbour(
            paper_id=f"accepted-neighbour-{index}",
            title=f"Accepted neighbour {index}",
            venue="ICLR",
            year=2026,
            paper_kind=AcceptedPaperKind.METHOD,
            source_url=f"https://example.org/paper-{index}",
            closest_capability="autonomous research",
            reported_evidence=("multi-task comparison",),
        )
        for index in (1, 2)
    )
    actions = (
        VenueGapAction(
            action_id="broad-experiment",
            title="Run the missing objective evidence program",
            kind=VenueGapActionKind.EXPERIMENT,
            closes_dimensions=empirical,
            produces_evidence_types=("result",),
            produces_components=(
                VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
                VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
            ),
            estimated_hours=24,
            expected_information_gain=0.9,
            feasibility=0.8,
        ),
        VenueGapAction(
            action_id="write-paper",
            title="Polish the narrative",
            kind=VenueGapActionKind.WRITING,
            closes_dimensions=(VenueGapDimension.NARRATIVE_CONTRIBUTION,),
            produces_evidence_types=("result",),
            estimated_hours=2,
            expected_information_gain=0.9,
            feasibility=1.0,
        ),
    )
    criteria = tuple(
        VenueEvidenceCriterion(
            dimension=dimension,
            claim=f"Claim for {dimension.value}",
            requirement="Independent admitted evidence",
            required_evidence_types=("result",),
            nearest_neighbour_ids=(
                ("accepted-neighbour-1", "accepted-neighbour-2")
                if dimension is VenueGapDimension.INNOVATION
                else ()
            ),
            scientific_importance=1.0,
            reviewer_rejection_risk=1.0,
            candidate_action_ids=("broad-experiment", "write-paper"),
        )
        for dimension in dimensions
    )
    manifest = VenueGapManifest(
        manifest_id="test-venue-gap",
        project_id="test-project",
        target_venue="ICLR 2027",
        paper_title="A paper",
        central_contribution="One central contribution",
        nearest_neighbours=neighbours,
        criteria=criteria,
        evidence=(
            VenueEvidenceSignal(
                evidence_id="one-local-table",
                family_id="one-local-study",
                dimension=VenueGapDimension.MECHANISM,
                evidence_type="result",
                summary="One favorable controlled table",
                maturity=EvidenceMaturity.DEVELOPMENT_ONLY,
            ),
        ),
        candidate_actions=actions,
    )
    now = datetime(2026, 9, 17, tzinfo=UTC)
    deadline = ProjectDeadlineStatus.model_construct(
        project_id="test-project",
        project_revision=3,
        project_snapshot_sha256="1" * 64,
        venue_id="iclr-2027",
        status_sha256="2" * 64,
        milestones=(
            ProjectVenueMilestoneStatus(
                milestone_id="paper",
                kind=VenueMilestoneKind.PAPER_SUBMISSION,
                deadline_at=now + timedelta(days=8),
                hard_deadline=True,
                completed=False,
                overdue=False,
                seconds_remaining=8 * 24 * 3600,
                required_outcomes=("submit",),
                external_action_required=True,
            ),
        ),
    )
    comparison = VenueComparisonProfile(
        profile_id="test-venue-comparison",
        project_id="test-project",
        venue_gap_manifest_id="test-venue-gap",
        target_paper_kind=AcceptedPaperKind.METHOD,
        innovation_claims=(
            VenueInnovationClaim(
                claim_id="conditional-scientific-policy",
                axis=VenueContributionAxis.DECISION_MECHANISM,
                contribution="Condition scientific actions on the observed research state.",
                nearest_neighbour_ids=(
                    "accepted-neighbour-1",
                    "accepted-neighbour-2",
                ),
                closest_overlap="Accepted agents also revise research artifacts.",
                falsifiable_difference=(
                    "State-matched preferences should improve objective downstream outcomes."
                ),
                effect_evidence_ids=("one-local-table",),
            ),
        ),
        accepted_evidence_profiles=(
            AcceptedNeighbourEvidenceProfile(
                paper_id="accepted-neighbour-1",
                components=(
                    VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
                    VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
                ),
                scale_facts=(
                    VenueEvidenceScaleFact(
                        metric=VenueEvidenceScaleMetric.AUTHENTIC_RESEARCH_TASKS,
                        value=100,
                        scope="peer-reviewed research workflows",
                        source_basis="reported benchmark task count",
                    ),
                    VenueEvidenceScaleFact(
                        metric=VenueEvidenceScaleMetric.COMPETITIVE_SYSTEMS,
                        value=5,
                        scope="matched research-agent systems",
                        source_basis="reported system comparison",
                    ),
                ),
            ),
            AcceptedNeighbourEvidenceProfile(
                paper_id="accepted-neighbour-2",
                components=(
                    VenueEvidenceComponent.HUMAN_EXPERT_VALIDATION,
                    VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
                    VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
                ),
            ),
        ),
        current_evidence_components=(
            CurrentEvidenceComponentBinding(
                component=VenueEvidenceComponent.MECHANISM_ABLATION,
                evidence_ids=("one-local-table",),
            ),
        ),
        current_scale_facts=(
            VenueEvidenceScaleFact(
                metric=VenueEvidenceScaleMetric.AUTHENTIC_RESEARCH_TASKS,
                value=12,
                scope="synthetic held-out task states",
                source_basis="registered objective evaluation",
            ),
        ),
        claim_evidence_contracts=(
            VenueClaimEvidenceContract(
                claim_id="conditional-scientific-policy",
                centrality=VenueClaimCentrality.CENTRAL,
                required_components=(
                    VenueEvidenceComponent.MECHANISM_ABLATION,
                    VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
                ),
                minimum_independent_families=2,
            ),
        ),
    )

    assessment = assess_venue_gap(manifest, deadline, comparison)

    assert assessment.submission_position is SubmissionEvidencePosition.NOT_YET_COMPETITIVE
    assert assessment.admitted_evidence_family_count == 0
    assert assessment.evidence_portfolio.admitted_empirical_family_count == 0
    assert assessment.evidence_portfolio.below_neighbour_reported_component_floor is True
    assert "No held-out" in assessment.evidence_portfolio.diagnosis
    assert len(assessment.unresolved_dimensions) == len(VenueGapDimension)
    assert assessment.next_actions[0].action_id == "broad-experiment"
    assert assessment.next_actions[0].closes_accepted_components == (
        VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
        VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
    )
    assert assessment.next_actions[0].comparable_accepted_paper_ids == (
        "accepted-neighbour-1",
        "accepted-neighbour-2",
    )
    assert assessment.evidence_program_decision.mode.value == (
        "build-accepted-comparable-portfolio"
    )
    assert assessment.evidence_program_decision.next_action_id == "broad-experiment"
    assert assessment.evidence_program_decision.paper_level_claims_authorized is False
    assert assessment.evidence_program_decision.paper_polish_is_next_action is False
    assert assessment.evidence_program_decision.blocking_central_claim_ids == (
        "conditional-scientific-policy",
    )
    assert assessment.evidence_program_decision.missing_accepted_components == (
        VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
        VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
    )
    assert assessment.evidence_program_decision.scale_shortfall_metrics == (
        VenueEvidenceScaleMetric.AUTHENTIC_RESEARCH_TASKS,
        VenueEvidenceScaleMetric.COMPETITIVE_SYSTEMS,
    )
    assert assessment.acceptance_prediction_made is False
    assert assessment.venue_comparison is not None
    assert assessment.venue_comparison.current_admitted_family_count == 0
    assert assessment.venue_comparison.current_admitted_component_count == 0
    assert assessment.venue_comparison.evidence_shape_complete_for_review is False
    assert assessment.venue_comparison.target_paper_kind is AcceptedPaperKind.METHOD
    assert assessment.venue_comparison.same_venue_neighbour_count == 2
    assert assessment.venue_comparison.latest_same_venue_year == 2026
    assert assessment.venue_comparison.same_venue_recency_gap_years == 1
    assert assessment.venue_comparison.same_venue_lineage_present is True
    assert len(assessment.venue_comparison.accepted_neighbour_gaps) == 2
    first_neighbour_gap = assessment.venue_comparison.accepted_neighbour_gaps[0]
    assert first_neighbour_gap.paper_id == "accepted-neighbour-1"
    assert first_neighbour_gap.component_shape_matched is False
    assert first_neighbour_gap.quality_equivalence_claimed is False
    assert first_neighbour_gap.scale_reference_matched is False
    assert tuple(item.status for item in first_neighbour_gap.scale_gaps) == (
        VenueEvidenceScaleStatus.BELOW_ACCEPTED_REFERENCE,
        VenueEvidenceScaleStatus.CURRENT_MISSING,
    )
    assert first_neighbour_gap.missing_or_unadmitted_components == (
        VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
        VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
    )
    assert assessment.venue_comparison.claim_contracts_complete is True
    assert assessment.venue_comparison.central_claim_arguments_complete is False
    assert assessment.venue_comparison.claim_arguments[0].complete_for_review is False
    assert assessment.venue_comparison.claim_arguments[0].missing_or_unadmitted_components == (
        VenueEvidenceComponent.MECHANISM_ABLATION,
        VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
    )
    assert assessment.venue_comparison.innovation_claims[0].evidence_status is (
        VenueInnovationEvidenceStatus.DEVELOPMENT_ONLY
    )
    assert assessment.venue_comparison.missing_or_unadmitted_accepted_majority_components == (
        VenueEvidenceComponent.OBJECTIVE_HIDDEN_EVALUATION,
        VenueEvidenceComponent.STRONG_SYSTEM_BASELINES,
    )

    admitted_negative = manifest.evidence[0].model_copy(
        update={
            "maturity": EvidenceMaturity.ADMITTED,
            "direction": EvidenceDirection.CONTRADICTING,
            "headline_eligible": False,
            "objective_measurement": True,
            "held_out": True,
        }
    )
    contradicted = assess_venue_gap(
        manifest.model_copy(update={"evidence": (admitted_negative,)}),
        deadline,
        comparison,
    )

    assert contradicted.submission_position is SubmissionEvidencePosition.CONTRADICTED
    assert contradicted.evidence_program_decision.mode.value == (
        "repair-contradicted-core-claim"
    )
    assert contradicted.evidence_portfolio.admitted_empirical_family_count == 1
    assert contradicted.evidence_portfolio.contradicting_empirical_family_count == 1
    assert contradicted.venue_comparison is not None
    assert contradicted.venue_comparison.innovation_claims[0].evidence_status is (
        VenueInnovationEvidenceStatus.CONTRADICTED
    )
