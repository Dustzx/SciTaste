from __future__ import annotations

import pytest

from scitaste.evidence import (
    ClaimGraph,
    ClaimRelation,
    ClaimStatus,
    ClaimStrength,
    ClaimType,
    EvidenceGraph,
    EvidenceItem,
    EvidenceLoop,
    InterpretationContext,
    InterpretationCritic,
    InterpretationDisposition,
    ResultRecord,
    ScientificClaim,
)
from scitaste.schema.actions import MetaAction


def _claim(
    claim_id: str = "claim-performance",
    *,
    strength: ClaimStrength = ClaimStrength.MODERATE,
    required: list[str] | None = None,
    importance: float = 0.8,
) -> ScientificClaim:
    return ScientificClaim(
        claim_id=claim_id,
        text="The method improves held-out performance under matched compute.",
        claim_type=ClaimType.PERFORMANCE,
        strength=strength,
        required_evidence_types=required or ["held-out benchmark"],
        scientific_importance=importance,
        claim_relevance=0.9,
    )


def _result(result_id: str = "result-01") -> ResultRecord:
    return ResultRecord(
        result_id=result_id,
        experiment_id=f"experiment-{result_id}",
        summary="Raw evaluation completed.",
        metrics={"accuracy": 0.82},
        cost={"gpu_hours": 0.1},
    )


def test_supported_evidence_updates_claim_and_advances() -> None:
    claim = _claim()
    loop = EvidenceLoop(ClaimGraph(claims=[claim]))
    review = InterpretationCritic().review(
        _result(),
        InterpretationContext(
            claim_id=claim.claim_id,
            evidence_type="held-out benchmark",
            expected="The matched method should outperform the baseline.",
            observed="The method improves accuracy by 4 points under matched compute.",
            relation=ClaimRelation.SUPPORTS,
            reproducible=True,
            stability=0.9,
            statistical_uncertainty=0.05,
        ),
    )

    outcome = loop.add_review(review)

    assert review.result.summary == "Raw evaluation completed."
    assert review.observation.statement.startswith("The method improves")
    assert review.interpretation.disposition == InterpretationDisposition.SUPPORT
    assert review.claim_assessment.may_update_claim is True
    assert outcome.gaps[0].status == ClaimStatus.SUPPORTED
    assert claim.status == ClaimStatus.SUPPORTED
    assert claim.supporting_evidence_ids == ["evidence-result-01-claim-performance"]
    assert outcome.route.action.type == MetaAction.ADVANCE


def test_uncertain_interpretation_does_not_promote_metric_to_claim() -> None:
    claim = _claim()
    loop = EvidenceLoop(ClaimGraph(claims=[claim]))
    review = InterpretationCritic().review(
        _result("result-uncertain"),
        InterpretationContext(
            claim_id=claim.claim_id,
            evidence_type="held-out benchmark",
            expected="The matched method should outperform the baseline.",
            observed="The metric increases, but the evaluation set overlaps training data.",
            relation=ClaimRelation.SUPPORTS,
            reproducible=True,
            stability=0.95,
            statistical_uncertainty=0.05,
            alternative_explanations=["memorization"],
            data_leakage=True,
        ),
    )

    outcome = loop.add_review(review)

    assert review.interpretation.disposition == InterpretationDisposition.UNCERTAIN
    assert "data leakage" in review.interpretation.validity_threats
    assert review.claim_assessment.may_update_claim is False
    assert claim.supporting_evidence_ids == []
    assert outcome.gaps[0].status == ClaimStatus.UNSUPPORTED
    assert outcome.route.action.type == MetaAction.REPRODUCE


def test_stable_contradiction_triggers_pivot_and_preserves_evidence() -> None:
    claim = _claim()
    loop = EvidenceLoop(ClaimGraph(claims=[claim]))
    review = InterpretationCritic().review(
        _result("result-contradiction"),
        InterpretationContext(
            claim_id=claim.claim_id,
            evidence_type="held-out benchmark",
            expected="The matched method should outperform the baseline.",
            observed="The method is consistently worse than the matched baseline.",
            relation=ClaimRelation.CONTRADICTS,
            reproducible=True,
            stability=0.92,
            statistical_uncertainty=0.04,
        ),
    )

    outcome = loop.add_review(review)

    assert review.interpretation.disposition == InterpretationDisposition.CONTRADICTION
    assert outcome.gaps[0].status == ClaimStatus.CONTRADICTED
    assert claim.contradicting_evidence_ids == ["evidence-result-contradiction-claim-performance"]
    assert outcome.route.action.type == MetaAction.PIVOT
    assert outcome.route.action.parameters["contradicted_claim_ids"] == [claim.claim_id]
    assert loop.evidence.items[0].observation.startswith("The method is consistently worse")


def test_unstable_contradiction_routes_to_reproduction_not_pivot() -> None:
    claim = _claim()
    loop = EvidenceLoop(ClaimGraph(claims=[claim]))
    review = InterpretationCritic().review(
        _result("result-unstable"),
        InterpretationContext(
            claim_id=claim.claim_id,
            evidence_type="held-out benchmark",
            expected="The matched method should outperform the baseline.",
            observed="One seed is worse than the baseline.",
            relation=ClaimRelation.CONTRADICTS,
            reproducible=False,
            stability=0.3,
            statistical_uncertainty=0.4,
        ),
    )

    outcome = loop.add_review(review)

    assert review.interpretation.disposition == InterpretationDisposition.UNCERTAIN
    assert outcome.route.action.type == MetaAction.REPRODUCE
    assert outcome.route.action.type != MetaAction.PIVOT
    assert claim.contradicting_evidence_ids == []


def test_unsupported_claim_triggers_complete_evidence_action() -> None:
    claim = _claim(required=["held-out benchmark", "negative control"])

    outcome = EvidenceLoop(ClaimGraph(claims=[claim])).assess()

    assert outcome.gaps[0].status == ClaimStatus.UNSUPPORTED
    assert outcome.route.action.type == MetaAction.COLLECT_EVIDENCE
    assert outcome.route.experiment_plan is not None
    plan = outcome.route.experiment_plan
    assert plan.claim_id == claim.claim_id
    assert plan.target_evidence_type == "held-out benchmark"
    assert plan.falsification_test
    assert plan.counterfactual
    assert plan.matched_baseline
    assert plan.negative_control
    assert plan.action.parameters["falsification_test"] == plan.falsification_test


def test_strong_claim_with_one_support_is_overclaimed_and_requests_more_evidence() -> None:
    claim = _claim(strength=ClaimStrength.STRONG)
    claims = ClaimGraph(claims=[claim])
    loop = EvidenceLoop(claims)

    outcome = loop.add_evidence(
        EvidenceItem(
            evidence_id="evidence-single-run",
            source_type="experiment",
            evidence_type="held-out benchmark",
            experiment_id="experiment-one",
            observation="One matched run supports the claim.",
            supports_claim_ids=[claim.claim_id],
            confidence=0.9,
            stability=0.9,
        )
    )

    assert outcome.gaps[0].status == ClaimStatus.OVERCLAIMED
    assert outcome.route.action.type == MetaAction.COLLECT_EVIDENCE


def test_graph_rejects_unknown_claim_and_information_value_breaks_ties() -> None:
    important = _claim("claim-important", importance=1.0)
    secondary = _claim("claim-secondary", importance=0.2)
    claims = ClaimGraph(claims=[secondary, important])

    outcome = EvidenceLoop(claims).assess()

    assert outcome.route.experiment_plan is not None
    assert outcome.route.experiment_plan.claim_id == important.claim_id
    with pytest.raises(ValueError, match="unknown claims"):
        EvidenceGraph().add(
            EvidenceItem(
                evidence_id="orphan",
                source_type="experiment",
                evidence_type="benchmark",
                observation="An orphan observation.",
                supports_claim_ids=["missing"],
                confidence=0.9,
            ),
            claims,
        )
