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
