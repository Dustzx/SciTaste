from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.project import PaperManifest, ProjectManifest, ProjectRuntime
from scitaste.review import (
    ReviewConcernResolution,
    ReviewerIdentity,
    ReviewFeedback,
    VenueCriterionAssessment,
    VenueReviewReport,
    VenueReviewResponse,
    import_venue_review_report,
    prepare_venue_review,
    route_venue_review_to_state,
    submit_venue_review_response,
)
from scitaste.review.model_report import build_venue_paper_review_material
from scitaste.state.research_state import ResearchState

_ROOT = Path(__file__).resolve().parents[2]
_PROFILE = _ROOT / "configs/writing/venues/iclr-2027/taste.yaml"
_CRITERIA = (
    "specific_question",
    "motivation_and_literature",
    "claim_support_and_rigor",
    "significance_and_community_value",
)


def _project(runtime: ProjectRuntime) -> object:
    return runtime.create(
        ProjectManifest(
            project_id="review-project",
            title="Review project",
            research_direction="Close paper concerns through research obligations.",
            target_venue="ICLR 2027",
            status="active",
        )
    )


def _paper(
    runtime: ProjectRuntime,
    snapshot: object,
    directory: str,
    *,
    text: str,
) -> object:
    root = runtime.projects_root / "review-project" / "papers" / directory
    root.mkdir(parents=True)
    (root / "main.md").write_text(text, encoding="utf-8")
    return runtime.register_paper(
        "review-project",
        PaperManifest(
            paper_id=directory,
            project_id="review-project",
            title="Scientific Taste for Autonomous Research",
            date="2026-09-11",
            provider="scitaste-native",
            model="deterministic-writer",
            condition="venue-draft",
            task="self-development",
            seed=0,
            stage=17,
            status="venue-submission-draft",
            evidence_scope="test-only",
            files={"source-markdown": "main.md"},
            venue_id="iclr-2027",
            eligible_for_submission=True,
        ),
        directory_name=directory,
        expected_revision=snapshot.revision,
    )


def _criteria() -> tuple[VenueCriterionAssessment, ...]:
    return tuple(
        VenueCriterionAssessment(
            criterion=criterion,
            assessment="partially_satisfied",
            rationale=f"The {criterion} evidence needs one bounded clarification.",
        )
        for criterion in _CRITERIA
    )


def _report(
    packet_sha256: str,
    *,
    report_id: str,
    reviewer_id: str,
    concern_id: str,
    target_claim_ids: tuple[str, ...] = (),
    requires_new_experiment: bool = False,
) -> VenueReviewReport:
    return VenueReviewReport.create(
        report_id=report_id,
        packet_sha256=packet_sha256,
        review_scope="independent_pre_submission",
        reviewer=ReviewerIdentity(
            reviewer_id=reviewer_id,
            reviewer_kind="independent_expert",
            independent=True,
            conflict_status="cleared",
            expertise=("autonomous research",),
        ),
        summary="The system question is promising but one claim needs stronger support.",
        strengths=("The scientific question is identifiable.",),
        weaknesses=("One decision-relevant claim is under-supported.",),
        criteria=_criteria(),
        initial_recommendation="reject",
        decision_reasons=("The central evidence chain is incomplete.",),
        questions=("Does the added analysis close the stated alternative explanation?",),
        concerns=(
            ReviewFeedback(
                concern_id=concern_id,
                category="missing_evidence",
                severity="high",
                text="Add evidence that distinguishes the alternative explanation.",
                target_claim_ids=list(target_claim_ids),
                requires_new_evidence=True,
                requires_new_experiment=requires_new_experiment,
                required_evidence_types=["controlled analysis"],
            ),
        ),
        confidence="high",
    )


def test_review_round_rejects_manuscript_bytes_as_new_evidence(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = _paper(runtime, _project(runtime), "paper-v1", text="# Paper v1\n")
    snapshot, packet, round_record = prepare_venue_review(
        runtime,
        project_id="review-project",
        paper_directory="paper-v1",
        review_id="iclr-round-1",
        round_number=1,
        review_scope="independent_pre_submission",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
        select=True,
    )

    assert round_record.status == "prepared"
    assert packet.official_decision_authority is False
    assert snapshot.manifest.current_review == "iclr-round-1"

    reports = (
        _report(
            packet.packet_sha256,
            report_id="report-a",
            reviewer_id="expert-a",
            concern_id="evidence-a",
        ),
        _report(
            packet.packet_sha256,
            report_id="report-b",
            reviewer_id="expert-b",
            concern_id="evidence-b",
        ),
    )
    for report in reports:
        snapshot, round_record = import_venue_review_report(
            runtime,
            project_id="review-project",
            review_id="iclr-round-1",
            report=report,
            expected_revision=snapshot.revision,
        )
    assert round_record.status == "revision_required"
    assert set(round_record.unresolved_concern_ids) == {"evidence-a", "evidence-b"}

    snapshot = _paper(
        runtime,
        snapshot,
        "paper-v2",
        text="# Paper v2\n\nThe controlled analysis now rules out the alternative.\n",
    )
    revised = next(item for item in snapshot.papers if item.directory_name == "paper-v2")
    evidence_locator = "papers/paper-v2/main.md"
    evidence_path = runtime.projects_root / "review-project" / evidence_locator
    response = VenueReviewResponse.create(
        response_id="response-v1",
        packet_sha256=packet.packet_sha256,
        source_report_sha256=tuple(sorted(item.report_sha256 for item in reports)),
        revised_paper_directory="paper-v2",
        revised_paper_manifest_sha256=revised.manifest_sha256,
        resolutions=tuple(
            ReviewConcernResolution(
                concern_id=concern.concern_id,
                disposition="addressed",
                response="The revised result section adds the requested controlled analysis.",
                evidence_sha256={
                    evidence_locator: hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                },
            )
            for report in reports
            for concern in report.concerns
        ),
    )
    with pytest.raises(ValueError, match="paper revision trace"):
        submit_venue_review_response(
            runtime,
            project_id="review-project",
            review_id="iclr-round-1",
            expected_revision=snapshot.revision,
            response=response,
        )


def test_review_round_rejects_duplicate_concern_ids_across_reports(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = _paper(runtime, _project(runtime), "paper-v1", text="# Paper v1\n")
    snapshot, packet, _round = prepare_venue_review(
        runtime,
        project_id="review-project",
        paper_directory="paper-v1",
        review_id="duplicate-concern-round",
        round_number=1,
        review_scope="independent_pre_submission",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
    )
    first = _report(
        packet.packet_sha256,
        report_id="report-first",
        reviewer_id="expert-first",
        concern_id="shared-concern",
    )
    snapshot, _round = import_venue_review_report(
        runtime,
        project_id="review-project",
        review_id="duplicate-concern-round",
        report=first,
        expected_revision=snapshot.revision,
    )
    duplicate = _report(
        packet.packet_sha256,
        report_id="report-second",
        reviewer_id="expert-second",
        concern_id="shared-concern",
    )

    with pytest.raises(ValueError, match="unique across the complete round"):
        import_venue_review_report(
            runtime,
            project_id="review-project",
            review_id="duplicate-concern-round",
            report=duplicate,
            expected_revision=snapshot.revision,
        )


def test_model_review_material_is_bound_to_registered_paper_bytes(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    paper_text = "# Paper v1\r\n\r\nA content-bound claim.\r\n"
    snapshot = _paper(runtime, _project(runtime), "paper-v1", text=paper_text)
    _snapshot, packet, _round_record = prepare_venue_review(
        runtime,
        project_id="review-project",
        paper_directory="paper-v1",
        review_id="model-review-r1",
        round_number=1,
        review_scope="development",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
        select=True,
    )

    material = build_venue_paper_review_material(
        runtime,
        project_id="review-project",
        review_id="model-review-r1",
        permitted_evidence_types=("controlled-analysis", "controlled-analysis"),
    )

    assert material.review_id == "model-review-r1"
    assert material.paper_locator == "papers/paper-v1/main.md"
    assert material.node_input.packet_sha256 == packet.packet_sha256
    assert material.node_input.paper_text == paper_text
    assert material.node_input.permitted_evidence_types == ("controlled-analysis",)
    assert material.section_ids == ()

    paper_path = runtime.projects_root / "review-project" / "papers/paper-v1/main.md"
    paper_path.write_text("# Drifted paper\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from its packet"):
        build_venue_paper_review_material(
            runtime,
            project_id="review-project",
            review_id="model-review-r1",
        )


def test_model_identity_and_state_routing_cannot_masquerade_as_expert_evidence() -> None:
    with pytest.raises(ValidationError, match="cannot be marked independent"):
        ReviewerIdentity(
            reviewer_id="model-a",
            reviewer_kind="internal_model",
            independent=True,
            conflict_status="cleared",
            provider="provider",
            model_name="model",
        )

    report = VenueReviewReport.create(
        report_id="internal-report",
        packet_sha256="1" * 64,
        review_scope="development",
        reviewer=ReviewerIdentity(
            reviewer_id="model-a",
            reviewer_kind="internal_model",
            independent=False,
            conflict_status="unverified",
            provider="provider",
            model_name="model",
        ),
        summary="A bounded internal review.",
        strengths=("The question is visible.",),
        weaknesses=("The evidence boundary is unclear.",),
        criteria=_criteria(),
        initial_recommendation="reject",
        decision_reasons=("The evidence boundary needs clarification.",),
        concerns=(
            ReviewFeedback(
                concern_id="clarify-boundary",
                category="overclaim",
                severity="high",
                text="Narrow the claim to the observed evidence.",
            ),
        ),
        confidence="medium",
    )
    state = ResearchState(
        project_id="review-project",
        research_direction="Test review routing.",
        target_domain="autonomous research",
    )

    routed, record = route_venue_review_to_state(report, state)

    assert state.reviewer_concerns == []
    assert routed.revision == state.revision + 1
    assert routed.reviewer_concerns[0].concern_id == "clarify-boundary"
    assert routed.open_research_obligations[0].action_type == "NARROW_CLAIM"
    assert record.report_sha256 == report.report_sha256
