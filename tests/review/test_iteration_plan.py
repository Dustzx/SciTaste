from __future__ import annotations

from collections.abc import Iterable

import pytest
from pydantic import ValidationError

from scitaste.project.models import content_sha256
from scitaste.review import (
    ProjectReviewIterationPlan,
    ProjectReviewRoutingBundle,
    ReviewerIdentity,
    ReviewFeedback,
    ReviewIterationWorkKind,
    VenueCriterionAssessment,
    VenueReviewReport,
    VenueReviewRound,
    compile_review_iteration_plan,
    route_venue_review_to_state,
)
from scitaste.state.research_state import ResearchState

_SHA = "a" * 64
_COMMIT = "b" * 40
_CRITERIA = (
    "specific_question",
    "motivation_and_literature",
    "claim_support_and_rigor",
    "significance_and_community_value",
)


def _report(report_id: str, concerns: Iterable[ReviewFeedback]) -> VenueReviewReport:
    return VenueReviewReport.create(
        report_id=report_id,
        packet_sha256=_SHA,
        review_scope="development",
        reviewer=ReviewerIdentity(
            reviewer_id=f"reviewer-{report_id}",
            reviewer_kind="internal_model",
            independent=False,
            conflict_status="unverified",
            provider="test-provider",
            model_name="test-reviewer",
        ),
        summary="The paper needs a bounded research iteration before another review.",
        strengths=("The central scientific question is explicit.",),
        weaknesses=("The current evidence and exposition leave open concerns.",),
        criteria=tuple(
            VenueCriterionAssessment(
                criterion=criterion,
                assessment="partially_satisfied",
                rationale=f"The {criterion} criterion needs another bounded pass.",
            )
            for criterion in _CRITERIA
        ),
        initial_recommendation="reject",
        decision_reasons=("Decision-relevant concerns remain unresolved.",),
        concerns=tuple(concerns),
        confidence="high",
    )


def _round(reports: tuple[VenueReviewReport, ...]) -> VenueReviewRound:
    concern_ids = tuple(sorted(item.concern_id for report in reports for item in report.concerns))
    return VenueReviewRound.create(
        project_id="iteration-project",
        review_id="development-review",
        paper_directory="paper-v1",
        venue_id="iclr-2027",
        round_number=1,
        review_scope="development",
        status="revision_required",
        packet_sha256=_SHA,
        report_sha256={item.report_id: item.report_sha256 for item in reports},
        unresolved_concern_ids=concern_ids,
    )


def _routing_bundle(
    *,
    run_id: str,
    report: VenueReviewReport,
    source: ResearchState,
    routed: ResearchState,
    concern_ids: tuple[str, ...],
    action_ids: tuple[str, ...],
    obligation_ids: tuple[str, ...],
    routing_record_sha256: str,
) -> ProjectReviewRoutingBundle:
    return ProjectReviewRoutingBundle.create(
        project_id="iteration-project",
        run_id=run_id,
        review_id="development-review",
        report_id=report.report_id,
        report_sha256=report.report_sha256,
        source_commit=_COMMIT,
        source_state_locator="runs/source/state/research_state.json",
        source_state_file_sha256=_SHA,
        source_state_sha256=content_sha256(source),
        routed_state_file_sha256=_SHA,
        routed_state_sha256=content_sha256(routed),
        routing_record_file_sha256=_SHA,
        routing_record_sha256=routing_record_sha256,
        concern_ids=concern_ids,
        obligation_ids=obligation_ids,
        open_obligation_ids=obligation_ids,
    )


def _route(
    report: VenueReviewReport,
    state: ResearchState,
    run_id: str,
) -> tuple[ResearchState, ProjectReviewRoutingBundle]:
    routed, record = route_venue_review_to_state(report, state)
    bundle = _routing_bundle(
        run_id=run_id,
        report=report,
        source=state,
        routed=routed,
        concern_ids=record.concern_ids,
        action_ids=record.action_ids,
        obligation_ids=record.obligation_ids,
        routing_record_sha256=record.record_sha256,
    )
    return routed, bundle


def test_review_iteration_plan_builds_approval_gated_research_to_response_dag() -> None:
    report = _report(
        "report-a",
        (
            ReviewFeedback(
                concern_id="clarify",
                category="clarity",
                severity="medium",
                text="Clarify the stated boundary condition.",
            ),
            ReviewFeedback(
                concern_id="clarity-with-evidence",
                category="clarity",
                severity="high",
                text="Clarify the boundary using a registered robustness analysis.",
                requires_new_evidence=True,
                required_evidence_types=["registered robustness analysis"],
            ),
            ReviewFeedback(
                concern_id="baseline",
                category="missing_baseline",
                severity="critical",
                text="Add a matched autonomous-research baseline.",
                requires_new_evidence=True,
                requires_new_experiment=True,
                required_evidence_types=["matched external baseline comparison"],
            ),
            ReviewFeedback(
                concern_id="analysis",
                category="analysis",
                severity="high",
                text="Analyze the observed failure modes.",
                requires_new_evidence=True,
                required_evidence_types=["registered research analysis"],
            ),
            ReviewFeedback(
                concern_id="method",
                category="method",
                severity="high",
                text="Revise and validate the reference abstraction method.",
                requires_new_evidence=True,
                requires_new_experiment=True,
                required_evidence_types=["method revision validation"],
            ),
            ReviewFeedback(
                concern_id="overclaim",
                category="overclaim",
                severity="high",
                text="Narrow the unsupported generalization claim.",
            ),
        ),
    )
    source = ResearchState(
        project_id="iteration-project",
        research_direction="Test reviewer-driven iteration planning.",
        target_domain="autonomous-research",
    )
    routed, routing = _route(report, source, "routing-a")

    plan = compile_review_iteration_plan(
        project_id="iteration-project",
        run_id="iteration-a",
        source_commit=_COMMIT,
        review_round=_round((report,)),
        reports=(report,),
        routing=(routing,),
        routed_state=routed,
    )

    kinds = {item.step_id: item.kind for item in plan.steps}
    assert kinds["revise-text-clarify"] == ReviewIterationWorkKind.PROSE_REVISION
    assert (
        kinds["analyze-evidence-clarity-with-evidence"] == ReviewIterationWorkKind.EVIDENCE_ANALYSIS
    )
    assert kinds["design-experiment-baseline"] == ReviewIterationWorkKind.EXPERIMENT_DESIGN
    assert kinds["execute-experiment-baseline"] == ReviewIterationWorkKind.EXPERIMENT_EXECUTION
    assert kinds["propose-method-method"] == ReviewIterationWorkKind.METHOD_REVISION_PROPOSAL
    assert kinds["validate-method-method"] == ReviewIterationWorkKind.METHOD_VALIDATION
    assert kinds["revise-text-overclaim"] == ReviewIterationWorkKind.CLAIM_REVISION
    assert plan.owner_approval_step_ids == (
        "execute-experiment-baseline",
        "validate-method-method",
    )
    assert plan.execution_approval_required is True
    assert plan.authorizes_execution is False
    assert plan.no_execution_performed is True
    assert plan.ready_for_paper_revision is False

    close = next(item for item in plan.steps if item.kind == ReviewIterationWorkKind.REVISION_INPUT)
    assert set(close.depends_on) == {
        "revise-text-clarify",
        "analyze-evidence-clarity-with-evidence",
        "execute-experiment-baseline",
        "analyze-evidence-analysis",
        "validate-method-method",
        "revise-text-overclaim",
    }
    assert plan.steps[-3].depends_on == ("compile-review-revision-input",)
    assert plan.steps[-2].depends_on == ("build-reviewed-paper-revision",)
    assert plan.steps[-1].depends_on == ("submit-review-response",)


def test_review_iteration_plan_requires_a_complete_cumulative_multi_report_chain() -> None:
    first = _report(
        "report-a",
        (
            ReviewFeedback(
                concern_id="first-concern",
                category="clarity",
                severity="medium",
                text="Clarify the first report concern.",
            ),
        ),
    )
    second = _report(
        "report-b",
        (
            ReviewFeedback(
                concern_id="second-concern",
                category="overclaim",
                severity="high",
                text="Narrow the second report claim.",
            ),
        ),
    )
    source = ResearchState(
        project_id="iteration-project",
        research_direction="Test a cumulative reviewer routing chain.",
        target_domain="autonomous-research",
    )
    first_state, first_routing = _route(first, source, "routing-a")
    final_state, second_routing = _route(second, first_state, "routing-b")
    round_record = _round((first, second))

    plan = compile_review_iteration_plan(
        project_id="iteration-project",
        run_id="iteration-multi",
        source_commit=_COMMIT,
        review_round=round_record,
        reports=(first, second),
        routing=(first_routing, second_routing),
        routed_state=final_state,
    )
    assert plan.concern_ids == ("first-concern", "second-concern")
    assert plan.routing_run_ids == ("routing-a", "routing-b")

    with pytest.raises(ValueError, match="cover every concern-bearing"):
        compile_review_iteration_plan(
            project_id="iteration-project",
            run_id="iteration-incomplete",
            source_commit=_COMMIT,
            review_round=round_record,
            reports=(first, second),
            routing=(second_routing,),
            routed_state=final_state,
        )
    with pytest.raises(ValueError, match="cumulative state chain"):
        compile_review_iteration_plan(
            project_id="iteration-project",
            run_id="iteration-reversed",
            source_commit=_COMMIT,
            review_round=round_record,
            reports=(first, second),
            routing=(second_routing, first_routing),
            routed_state=final_state,
        )


def test_review_iteration_plan_rejects_rewritten_dependency_graph() -> None:
    report = _report(
        "report-a",
        (
            ReviewFeedback(
                concern_id="clarify",
                category="clarity",
                severity="medium",
                text="Clarify the scope.",
            ),
        ),
    )
    source = ResearchState(
        project_id="iteration-project",
        research_direction="Test plan integrity.",
        target_domain="autonomous-research",
    )
    routed, routing = _route(report, source, "routing-a")
    plan = compile_review_iteration_plan(
        project_id="iteration-project",
        run_id="iteration-a",
        source_commit=_COMMIT,
        review_round=_round((report,)),
        reports=(report,),
        routing=(routing,),
        routed_state=routed,
    )
    payload = plan.model_dump(mode="json")
    payload["steps"][-1]["objective"] = "A rewritten terminal objective."

    with pytest.raises(ValidationError, match="plan hash mismatch"):
        ProjectReviewIterationPlan.model_validate(payload)
