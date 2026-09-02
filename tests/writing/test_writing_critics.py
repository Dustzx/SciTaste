from __future__ import annotations

from scitaste.state.research_state import (
    EvidenceGraph,
    EvidenceItem,
    NarrativeSpine,
    ResearchState,
    ScientificClaim,
    SectionContract,
    WritingState,
)
from scitaste.writing.critics import WritingCriticSuite
from scitaste.writing.narrative import review_narrative


def test_narrative_and_critics_reject_unsupported_or_uncited_claims() -> None:
    claim = ScientificClaim(
        claim_id="claim-1",
        text="Unsupported claim",
        claim_type="performance",
        strength="strong",
        required_evidence_types=["benchmark"],
        status="unsupported",
    )
    evidence = EvidenceItem(
        evidence_id="evidence-1",
        source_type="experiment",
        evidence_type="benchmark",
        observation="An inconclusive observation.",
        relates_to_claim_ids=["claim-1"],
        confidence=0.5,
    )
    spine = NarrativeSpine(
        core_problem="Problem",
        key_observation="Observation",
        central_insight="Insight",
        proposed_solution="Solution",
        evidence_chain=["evidence-1"],
        broader_implication="Implication",
        contribution_order=["claim-1"],
    )
    state = ResearchState(
        project_id="writing",
        research_direction="test",
        target_domain="testing",
        claims=[claim],
        evidence_graph=EvidenceGraph(items=[evidence]),
        narrative_spine=spine,
        writing_state=WritingState(
            status="drafted",
            section_contracts=[
                SectionContract(
                    section_name="Results",
                    purpose="Report result",
                    required_claim_ids=["claim-1"],
                    required_evidence_ids=["evidence-1"],
                    word_budget=100,
                )
            ],
            section_drafts={"Results": "Unsupported claim without an evidence marker."},
        ),
        current_stage="COMMUNICATION",
    )

    narrative = review_narrative(spine, state)
    findings = WritingCriticSuite().review(state)

    assert narrative.passes is False
    assert any(item.critic == "substance" for item in findings)
    assert any(item.critic == "citation" for item in findings)
