from __future__ import annotations

import pytest

from scitaste.review.closure import close_satisfied_obligations
from scitaste.review.obligations import create_obligation
from scitaste.review.parser import ReviewFeedback, parse_feedback
from scitaste.review.routing import ReviewActionRouter
from scitaste.schema.actions import MetaAction
from scitaste.state.research_state import EvidenceItem, ResearchState, ScientificClaim


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("clarity", MetaAction.CLARIFY_EXISTING_TEXT),
        ("missing_evidence", MetaAction.ADD_EXPERIMENT),
        ("missing_baseline", MetaAction.ADD_BASELINE),
        ("analysis", MetaAction.ADD_ANALYSIS),
        ("method", MetaAction.REVISE_METHOD),
        ("overclaim", MetaAction.NARROW_CLAIM),
        ("error", MetaAction.CORRECT_ERROR),
        ("limitation", MetaAction.ACKNOWLEDGE_LIMITATION),
        ("validity", MetaAction.ADD_EXPERIMENT),
    ],
)
def test_review_categories_route_to_stage_specific_actions(category, expected) -> None:
    concern = parse_feedback(
        [
            ReviewFeedback(
                concern_id="c1",
                category=category,
                severity="high",
                text="Structured concern",
            )
        ]
    )[0]

    assert ReviewActionRouter().route(concern).type == expected


@pytest.mark.parametrize(
    "values",
    [
        {"requires_new_experiment": True},
        {"required_evidence_types": ["matched baseline"]},
    ],
)
def test_review_feedback_rejects_inconsistent_evidence_requirements(values) -> None:
    with pytest.raises(ValueError, match="require new evidence"):
        ReviewFeedback(
            concern_id="invalid-evidence-gate",
            category="missing_evidence",
            severity="high",
            text="This requirement is internally inconsistent.",
            **values,
        )


def test_obligation_closes_only_with_new_matching_evidence() -> None:
    claim = ScientificClaim(
        claim_id="claim-1",
        text="A controlled claim",
        claim_type="performance",
        strength="moderate",
        required_evidence_types=["matched baseline"],
    )
    state = ResearchState(
        project_id="review",
        research_direction="test",
        target_domain="testing",
        claims=[claim],
        current_stage="REVIEW",
    )
    concern = parse_feedback(
        [
            ReviewFeedback(
                concern_id="c1",
                category="missing_baseline",
                severity="high",
                target_claim_ids=["claim-1"],
                text="Add a matched baseline",
                requires_new_evidence=True,
                requires_new_experiment=True,
                required_evidence_types=["matched baseline"],
            )
        ]
    )[0]
    state.reviewer_concerns.append(concern)
    action = ReviewActionRouter().route(concern)
    state.open_research_obligations.append(create_obligation(concern, action, state))
    assert close_satisfied_obligations(state) == []

    state.evidence_graph.items.append(
        EvidenceItem(
            evidence_id="evidence-1",
            source_type="experiment",
            evidence_type="matched baseline",
            observation="The advantage remains under equal compute.",
            supports_claim_ids=["claim-1"],
            confidence=0.9,
        )
    )

    closed = close_satisfied_obligations(state)
    assert [item.obligation_id for item in closed] == ["obligation-c1"]
    assert state.reviewer_concerns[0].status == "closed"


def test_obligation_closure_can_be_limited_to_one_review_scope() -> None:
    state = ResearchState(
        project_id="review",
        research_direction="test",
        target_domain="testing",
    )
    for concern_id in ("selected", "historical"):
        concern = parse_feedback(
            [
                ReviewFeedback(
                    concern_id=concern_id,
                    category="missing_evidence",
                    severity="high",
                    text="Add comparative evidence.",
                    requires_new_evidence=True,
                    requires_new_experiment=True,
                )
            ]
        )[0]
        state.reviewer_concerns.append(concern)
        state.open_research_obligations.append(
            create_obligation(concern, ReviewActionRouter().route(concern), state)
        )
    state.evidence_graph.items.append(
        EvidenceItem(
            evidence_id="formal-comparison",
            source_type="experiment",
            evidence_type="comparative effectiveness experiment",
            observation="The formal comparison passed its registered analysis.",
            confidence=1.0,
        )
    )

    closed = close_satisfied_obligations(
        state,
        obligation_ids=("obligation-selected",),
    )

    assert [item.obligation_id for item in closed] == ["obligation-selected"]
    assert state.open_research_obligations[1].status == "open"
    assert state.reviewer_concerns[1].status == "open"


@pytest.mark.parametrize(
    ("category", "expected_type"),
    [
        ("missing_evidence", "comparative effectiveness experiment"),
        ("missing_baseline", "matched external baseline comparison"),
        ("validity", "multi-task validity experiment"),
    ],
)
def test_broad_evidence_concerns_receive_fail_closed_evidence_types(
    category: str,
    expected_type: str,
) -> None:
    concern = parse_feedback(
        [
            ReviewFeedback(
                concern_id=f"broad-{category}",
                category=category,
                severity="high",
                text="The broad paper-level concern still requires specific evidence.",
                requires_new_evidence=True,
                requires_new_experiment=True,
            )
        ]
    )[0]
    state = ResearchState(
        project_id="review",
        research_direction="test",
        target_domain="testing",
    )
    obligation = create_obligation(concern, ReviewActionRouter().route(concern), state)

    assert obligation.required_evidence_types == [expected_type]
    state.reviewer_concerns.append(concern)
    state.open_research_obligations.append(obligation)
    state.evidence_graph.items.append(
        EvidenceItem(
            evidence_id="unrelated-evidence",
            source_type="experiment",
            evidence_type="unrelated result",
            observation="This evidence must not close a broad paper concern.",
            confidence=0.9,
        )
    )
    assert close_satisfied_obligations(state) == []
