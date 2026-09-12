from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.generative_ui import (
    ProjectProgressQuery,
    TrustedComponent,
    WorkspaceSurfaceFactory,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.review import (
    ProjectReviewRoutingBundle,
    ReviewConcernResolution,
    ReviewerIdentity,
    ReviewFeedback,
    VenueCriterionAssessment,
    VenueReviewReport,
    VenueReviewResponse,
    import_venue_review_report,
    inspect_project_review_followup_design,
    inspect_project_review_iteration,
    inspect_project_review_routing,
    prepare_project_review_followup_design,
    prepare_project_review_iteration,
    prepare_project_review_routing,
    prepare_venue_review,
    publish_project_review_followup_design,
    publish_project_review_iteration,
    publish_project_review_routing,
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


def test_registered_review_routes_to_open_project_obligations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = _project(runtime)
    source_run_id = "source-state-run"
    snapshot = runtime.begin_run(
        "review-project",
        ProjectRun(
            run_id=source_run_id,
            provider="scitaste-native",
            model="deterministic-controller",
            condition="review-routing-source",
            seed=0,
            status="complete",
            evidence_scope="test-only",
            stage_path="state",
        ),
        expected_revision=snapshot.revision,
    )
    source_state = ResearchState(
        project_id="review-project",
        research_direction="Test project-owned review routing.",
        target_domain="autonomous-research",
    )
    source_locator = f"runs/{source_run_id}/state/research_state.json"
    source_path = runtime.projects_root / "review-project" / source_locator
    source_path.write_text(source_state.model_dump_json(indent=2) + "\n", encoding="utf-8")

    snapshot = _paper(runtime, snapshot, "paper-routing-v1", text="# Paper routing v1\n")
    snapshot, packet, _ = prepare_venue_review(
        runtime,
        project_id="review-project",
        paper_directory="paper-routing-v1",
        review_id="routing-round",
        round_number=1,
        review_scope="independent_pre_submission",
        venue_taste_profile=_PROFILE,
        expected_revision=snapshot.revision,
    )
    report = _report(
        packet.packet_sha256,
        report_id="routing-report",
        reviewer_id="routing-expert",
        concern_id="routing-evidence",
        requires_new_experiment=True,
    )
    snapshot, _ = import_venue_review_report(
        runtime,
        project_id="review-project",
        review_id="routing-round",
        report=report,
        expected_revision=snapshot.revision,
    )
    assert (
        main(
            [
                "project",
                "paper",
                "review",
                "route-state",
                "--project-id",
                "review-project",
                "--review-id",
                "routing-round",
                "--report-id",
                "routing-report",
                "--source-state",
                source_locator,
                "--run-id",
                "review-obligations-v1",
                "--source-commit",
                "a" * 40,
                "--expected-revision",
                str(snapshot.revision),
                "--outputs-root",
                str(runtime.outputs_root),
                "--dry-run",
            ]
        )
        == 0
    )
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["bundle"]["open_obligation_ids"] == ["obligation-routing-evidence"]
    assert dry_run["scientific_evidence_established"] is False
    prepared = prepare_project_review_routing(
        runtime,
        project_id="review-project",
        review_id="routing-round",
        report_id="routing-report",
        source_state_locator=source_locator,
        run_id="review-obligations-v1",
        source_commit="a" * 40,
        expected_revision=snapshot.revision,
    )

    assert prepared.bundle.open_obligation_ids == ("obligation-routing-evidence",)
    assert prepared.bundle.new_evidence_count == 0
    assert prepared.bundle.scientific_evidence_established is False
    assert runtime.open("review-project").revision == snapshot.revision

    published, bundle = publish_project_review_routing(
        runtime,
        prepared=prepared,
        expected_revision=snapshot.revision,
    )
    assert published.revision == snapshot.revision + 2
    assert ProjectReviewRoutingBundle.model_validate(bundle).record_sha256 == bundle.record_sha256
    assert (
        inspect_project_review_routing(runtime, "review-project", "review-obligations-v1") == bundle
    )
    registered = next(item for item in published.manifest.runs if item.run_id == bundle.run_id)
    assert registered.status == "complete-review-routed"
    assert registered.model_calls == 0

    assert (
        main(
            [
                "project",
                "paper",
                "review",
                "plan-iteration",
                "--project-id",
                "review-project",
                "--review-id",
                "routing-round",
                "--routing-run-id",
                "review-obligations-v1",
                "--run-id",
                "review-iteration-v1",
                "--source-commit",
                "a" * 40,
                "--expected-revision",
                str(published.revision),
                "--outputs-root",
                str(runtime.outputs_root),
                "--dry-run",
            ]
        )
        == 0
    )
    iteration_dry_run = json.loads(capsys.readouterr().out)
    assert iteration_dry_run["authorizes_execution"] is False
    assert iteration_dry_run["plan"]["owner_approval_step_ids"] == [
        "execute-experiment-routing-evidence"
    ]
    prepared_iteration = prepare_project_review_iteration(
        runtime,
        project_id="review-project",
        review_id="routing-round",
        routing_run_ids=("review-obligations-v1",),
        run_id="review-iteration-v1",
        source_commit="a" * 40,
        expected_revision=published.revision,
    )
    published, iteration = publish_project_review_iteration(
        runtime,
        prepared=prepared_iteration,
        expected_revision=published.revision,
    )
    assert published.revision == snapshot.revision + 4
    assert iteration.next_step_ids == ("design-experiment-routing-evidence",)
    assert iteration.authorizes_execution is False
    assert (
        inspect_project_review_iteration(runtime, "review-project", "review-iteration-v1")
        == iteration
    )
    planned_run = next(
        item for item in published.manifest.runs if item.run_id == "review-iteration-v1"
    )
    assert planned_run.status == "complete-review-iteration-planned"
    assert planned_run.model_calls == 0

    mapping_path = tmp_path / "review-followup-mapping.yaml"
    mapping_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "mapping_id": "review-followup-test-v1",
                "project_id": "review-project",
                "review_id": "routing-round",
                "review_iteration_run_id": "review-iteration-v1",
                "paper_title": ("SciTaste: Improving Autonomous Research through Scientific Taste"),
                "mappings": [
                    {
                        "concern_id": "routing-evidence",
                        "objective": "title_effectiveness",
                        "treatment_kind": "registered_study_bundle",
                        "study_ids": [
                            "taste-abstraction-mechanism",
                            "taste-specificity-mechanism",
                            "taste-selection-mechanism",
                            "native-objective-progress",
                        ],
                        "rationale": ("Bind the concern to every registered title-critical study."),
                        "claim_action": None,
                        "title_change_authorized": False,
                    }
                ],
                "authorizes_download": False,
                "authorizes_api_calls": False,
                "authorizes_gpu_work": False,
                "authorizes_human_recruitment": False,
                "authorizes_execution": False,
            }
        ),
        encoding="utf-8",
    )
    evidence_program = (
        _ROOT / "configs/evaluation/programs/iclr2027_scitaste_evidence_program_v1.yaml"
    )
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(ValueError, match="source commit is unavailable"):
        prepare_project_review_followup_design(
            runtime,
            project_id="review-project",
            review_iteration_run_id="review-iteration-v1",
            mapping_path=mapping_path,
            evidence_program_path=evidence_program,
            run_id="review-followup-invalid-source",
            source_commit="f" * 40,
            expected_revision=published.revision,
        )
    prepared_followup = prepare_project_review_followup_design(
        runtime,
        project_id="review-project",
        review_iteration_run_id="review-iteration-v1",
        mapping_path=mapping_path,
        evidence_program_path=evidence_program,
        run_id="review-followup-design-v1",
        source_commit=source_commit,
        expected_revision=published.revision,
    )
    published, followup = publish_project_review_followup_design(
        runtime,
        prepared=prepared_followup,
        expected_revision=published.revision,
    )
    assert published.revision == snapshot.revision + 6
    assert followup.primary_model_id is None
    assert followup.fixed_formal_sample_size is None
    assert followup.authorizes_execution is False
    assert (
        inspect_project_review_followup_design(
            runtime, "review-project", "review-followup-design-v1"
        )
        == followup
    )
    followup_run = next(
        item for item in published.manifest.runs if item.run_id == "review-followup-design-v1"
    )
    assert followup_run.status == "complete-review-followup-designed"
    assert followup_run.model_calls == 0
    progress = WorkspaceSurfaceFactory(runtime).build(
        ProjectProgressQuery(project_id="review-project")
    )
    progress_board = next(
        item
        for item in progress.renderer.components
        if item.renderer == TrustedComponent.PROJECT_PROGRESS_BOARD
    )
    iteration_row = progress_board.data["review_iterations"][0]
    assert iteration_row["run_id"] == "review-iteration-v1"
    assert iteration_row["next_step_ids"] == ["design-experiment-routing-evidence"]
    assert iteration_row["authorizes_execution"] is False
    assert iteration_row["followup_design"]["run_id"] == "review-followup-design-v1"
    assert iteration_row["followup_design"]["hypothesis_ids"] == [
        "H1_taste_abstraction",
        "H2_taste_specificity",
        "H2b_taste_selection",
        "H3_native_effect",
    ]
    assert iteration_row["followup_design"]["primary_model_state"] == "unselected"
    design_step = next(
        item
        for item in iteration_row["steps"]
        if item["step_id"] == "design-experiment-routing-evidence"
    )
    assert design_step["study_ids"] == [
        "taste-abstraction-mechanism",
        "taste-specificity-mechanism",
        "taste-selection-mechanism",
        "native-objective-progress",
    ]
    assert {item["stage"] for item in iteration_row["lanes"]} == {
        "evidence",
        "writing",
        "review",
    }
    assert "review_iteration" in {
        item["kind"] for item in progress_board.data["next_step_candidates"]
    }

    routed_path = (
        runtime.projects_root
        / "review-project/runs/review-obligations-v1/review_routing/research_state.json"
    )
    routed_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ResearchState"):
        inspect_project_review_routing(runtime, "review-project", "review-obligations-v1")


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
