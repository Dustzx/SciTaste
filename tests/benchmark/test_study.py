from __future__ import annotations

import pytest
from pydantic import ValidationError

from scitaste.benchmark.study import (
    MatchedStudyEvaluator,
    MatchedStudyPlanner,
    load_study_protocol,
)
from scitaste.benchmark.study_models import (
    CellStatus,
    EvidenceClass,
    ExpertPanelReview,
    ReviewSource,
    StudyArtifact,
    StudyExecutionRecord,
    StudyOutcome,
    StudyResults,
    StudyStatus,
    StudyUsage,
    SystemCondition,
)

PROTOCOL_PATH = "configs/experiments/matched_budget_study_v1.yaml"


def ready_protocol():
    protocol = load_study_protocol(PROTOCOL_PATH)
    return protocol.model_copy(
        update={
            "base_model_revision": "bailian-qwen3.8-max-locked-test-revision",
            "search_access": protocol.search_access.model_copy(
                update={"frozen_snapshot": "sha256:" + "b" * 64}
            ),
        }
    )


def synthetic_results(protocol) -> StudyResults:
    plan = MatchedStudyPlanner().plan(protocol)
    records = []
    reviews = []
    for cell in plan.cells:
        records.append(
            StudyExecutionRecord(
                cell_id=cell.cell_id,
                status=CellStatus.SUCCEEDED,
                evidence_class=EvidenceClass.SYNTHETIC,
                usage=StudyUsage(
                    gpu_hours=1.0,
                    experiments=2,
                    wall_time_hours=1.5,
                    api_cost_usd=0.5,
                    search_queries=4,
                    llm_tokens=12000,
                ),
                outcome=StudyOutcome(
                    useful_results=1,
                    proposed_ideas=2,
                    valid_ideas=1,
                    pilots=1,
                    discarded_ideas=1,
                    unproductive_experiments=1,
                    total_experiments=2,
                    gpu_hours_before_useful_signal=0.75,
                    pivots=1,
                    correct_pivots=1,
                    evidence_sufficiency=0.7,
                    reviewer_concerns_opened=2,
                    reviewer_concerns_closed=1,
                    total_claims=4,
                    unsupported_claims=1,
                ),
                artifacts=[StudyArtifact(path="paper.md", sha256="a" * 64)],
            )
        )
        reviews.append(
            ExpertPanelReview(
                blind_id=cell.blind_id,
                source=ReviewSource.SYNTHETIC,
                reviewer_identity_hashes=[
                    f"reviewer-a-{cell.blind_id}",
                    f"reviewer-b-{cell.blind_id}",
                ],
                rubric_version=protocol.expert_panel.rubric_version,
                problem_quality=0.7,
                idea_quality=0.7,
                evidence_quality=0.7,
                story_quality=0.7,
                writing_quality=0.7,
                figure_quality=0.7,
                final_preference_score=0.7,
            )
        )
    return StudyResults(
        protocol_sha256=protocol.sha256,
        records=records,
        expert_reviews=reviews,
    )


def test_planner_builds_deterministic_matched_matrix() -> None:
    protocol = load_study_protocol(PROTOCOL_PATH)

    first = MatchedStudyPlanner().plan(protocol)
    second = MatchedStudyPlanner().plan(protocol)

    assert len(first.cells) == 48
    assert first.sha256 == second.sha256
    assert len({cell.cell_id for cell in first.cells}) == 48
    assert len({cell.blind_id for cell in first.cells}) == 48
    assert {cell.budget for cell in first.cells} == {protocol.budget}
    assert set(first.disabled_conditions) == {
        SystemCondition.SIBYL,
        SystemCondition.AI_SCIENTIST_V2,
    }
    assert first.readiness_blockers == []


def test_synthetic_complete_matrix_is_acceptance_only() -> None:
    protocol = ready_protocol()

    report = MatchedStudyEvaluator().evaluate(protocol, synthetic_results(protocol))

    assert report.status == StudyStatus.ACCEPTANCE_ONLY
    assert report.headline_eligible is False
    assert report.blockers == []
    assert report.completed_cells == report.planned_cells == 48
    assert set(report.by_condition) == {
        SystemCondition.AUTORESEARCHCLAW,
        SystemCondition.KNOWLEDGE_RAG,
        SystemCondition.TASTE_LIBRARY,
        SystemCondition.FULL_SCITASTE,
    }
    metrics = report.by_condition[SystemCondition.FULL_SCITASTE]
    assert metrics.cell_count == 12
    assert metrics.research_yield_per_gpu_hour == 1.0
    assert metrics.idea_yield == 0.5
    assert metrics.reviewer_concern_closure_rate == 0.5
    assert metrics.final_expert_preference == 0.7
    comparison = report.comparisons_to_autoresearchclaw[SystemCondition.FULL_SCITASTE]
    assert comparison.comparable_cell_count == 12
    assert comparison.research_yield_delta == 0.0
    assert comparison.final_expert_preference_delta == 0.0


def test_real_complete_matrix_with_external_reviews_is_headline_eligible() -> None:
    protocol = ready_protocol()
    synthetic = synthetic_results(protocol)
    real = synthetic.model_copy(
        update={
            "records": [
                record.model_copy(update={"evidence_class": EvidenceClass.REAL})
                for record in synthetic.records
            ],
            "expert_reviews": [
                review.model_copy(update={"source": ReviewSource.EXTERNAL})
                for review in synthetic.expert_reviews
            ],
        }
    )

    report = MatchedStudyEvaluator().evaluate(protocol, real)

    assert report.status == StudyStatus.ELIGIBLE
    assert report.headline_eligible is True
    assert report.blockers == []


def test_pilot_scope_cannot_become_headline_evidence() -> None:
    protocol = load_study_protocol("configs/experiments/matched_budget_local_pilot_v1.yaml")
    synthetic = synthetic_results(protocol)
    real = synthetic.model_copy(
        update={
            "records": [
                record.model_copy(
                    update={
                        "evidence_class": EvidenceClass.REAL,
                        "usage": record.usage.model_copy(
                            update={
                                "gpu_hours": 0.1,
                                "wall_time_hours": 0.1,
                                "api_cost_usd": 0,
                                "search_queries": 0,
                                "llm_tokens": 100,
                            }
                        ),
                    }
                )
                for record in synthetic.records
            ],
            "expert_reviews": [
                review.model_copy(update={"source": ReviewSource.EXTERNAL})
                for review in synthetic.expert_reviews
            ],
        }
    )

    report = MatchedStudyEvaluator().evaluate(protocol, real)

    assert report.status == StudyStatus.ACCEPTANCE_ONLY
    assert report.headline_eligible is False


def test_budget_or_telemetry_violation_blocks_study() -> None:
    protocol = ready_protocol()
    results = synthetic_results(protocol)
    first = results.records[0]
    bad_usage = first.usage.model_copy(update={"gpu_hours": 5.0, "api_cost_usd": None})
    bad_record = first.model_copy(update={"usage": bad_usage})
    invalid = results.model_copy(update={"records": [bad_record, *results.records[1:]]})

    report = MatchedStudyEvaluator().evaluate(protocol, invalid)

    assert report.status == StudyStatus.INCOMPLETE
    assert report.headline_eligible is False
    assert any("resource budget exceeded" in blocker for blocker in report.blockers)
    assert any("incomplete resource telemetry" in blocker for blocker in report.blockers)
    audit = next(audit for audit in report.audits if audit.cell_id == first.cell_id)
    assert audit.budget_violations == ["gpu_hours"]
    assert audit.missing_telemetry == ["api_cost_usd"]


def test_missing_cells_and_internal_review_are_not_headline_eligible() -> None:
    protocol = ready_protocol()
    results = synthetic_results(protocol)
    internal_review = results.expert_reviews[0].model_copy(update={"source": ReviewSource.INTERNAL})
    incomplete = results.model_copy(
        update={
            "records": results.records[1:],
            "expert_reviews": [internal_review, *results.expert_reviews[1:]],
        }
    )

    report = MatchedStudyEvaluator().evaluate(protocol, incomplete)

    assert report.status == StudyStatus.INCOMPLETE
    assert len(report.missing_cell_ids) == 1
    assert "internal reviews cannot satisfy external expert evaluation" in report.blockers


def test_outcome_schema_rejects_impossible_counts() -> None:
    protocol = ready_protocol()
    outcome = synthetic_results(protocol).records[0].outcome.model_dump(mode="json")
    outcome["valid_ideas"] = outcome["proposed_ideas"] + 1

    with pytest.raises(ValidationError, match="valid_ideas"):
        StudyOutcome.model_validate(outcome)


def test_failed_execution_can_be_recorded_without_fake_outputs() -> None:
    protocol = ready_protocol()
    cell = MatchedStudyPlanner().plan(protocol).cells[0]
    failed = StudyExecutionRecord(
        cell_id=cell.cell_id,
        status=CellStatus.FAILED,
        evidence_class=EvidenceClass.REAL,
        usage=StudyUsage(
            gpu_hours=0.1,
            experiments=0,
            wall_time_hours=0.1,
            api_cost_usd=0.1,
            search_queries=0,
            llm_tokens=100,
        ),
        error="Executor failed before producing an artifact.",
    )
    results = StudyResults(
        protocol_sha256=protocol.sha256,
        records=[failed],
        expert_reviews=[],
    )

    report = MatchedStudyEvaluator().evaluate(protocol, results)

    assert report.status == StudyStatus.INCOMPLETE
    assert any("execution did not succeed" in blocker for blocker in report.blockers)


def test_results_must_match_protocol_fingerprint() -> None:
    protocol = ready_protocol()
    results = synthetic_results(protocol).model_copy(update={"protocol_sha256": "0" * 64})

    with pytest.raises(ValueError, match="fingerprint"):
        MatchedStudyEvaluator().evaluate(protocol, results)
