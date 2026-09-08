from __future__ import annotations

import json

from scitaste.state.research_state import ResearchState, WritingState
from scitaste.writing.critics import WritingTasteCritic
from scitaste.writing.taste import (
    WRITING_TASTE_PRECEDENCE,
    WritingTasteAssessment,
    WritingTasteDimension,
    WritingTasteSeverity,
    assess_writing_taste,
    write_writing_taste_assessment,
)


def test_writing_taste_detects_project_report_and_defensive_story() -> None:
    manuscript = """## Title
A Research Paper

# Abstract
We do not claim to solve the entire problem. We introduce a bounded controller.
The evaluation demonstrates traceable decisions.

# Current Results

At the current repository snapshot, the test suite has 100 passing tests. The wheel
build also passes. During the sequence we first repaired the adapter and subsequently
created revision 12.

# Limitations

The single-task design does not estimate cross-domain effectiveness.

# Conclusion

The controller establishes a reproducible decision boundary, but we do not claim
that it improves every research outcome.
"""

    assessment = assess_writing_taste(manuscript, target_venue="ICLR 2027")

    codes = {item.code for item in assessment.findings}
    assert {
        "project-report-heading",
        "project-log-results",
        "process-chronology",
        "defensive-framing",
        "conclusion-self-negation",
    }.issubset(codes)
    assert assessment.warning_count >= 5
    assert assessment.integrity_gate_passes is True
    assert assessment.style_advisory_passes is False
    assert not [
        item
        for item in assessment.findings
        if item.section_name == "Limitations" and item.code == "defensive-framing"
    ]
    assert all(item.preserves_material_limitations for item in assessment.findings)
    assert all(not item.automatic_rewrite_allowed for item in assessment.findings)


def test_writing_taste_keeps_integrity_above_persuasive_style() -> None:
    assert WRITING_TASTE_PRECEDENCE.index(
        WritingTasteDimension.SCIENTIFIC_INTEGRITY
    ) < WRITING_TASTE_PRECEDENCE.index(WritingTasteDimension.ANTI_DEFENSIVE_STYLE)
    assert WRITING_TASTE_PRECEDENCE.index(
        WritingTasteDimension.CLAIM_CALIBRATION
    ) < WRITING_TASTE_PRECEDENCE.index(WritingTasteDimension.ANTI_DEFENSIVE_STYLE)


def test_clean_bounded_story_passes_deterministic_advisory() -> None:
    manuscript = """## Title
Evidence-Grounded Research Control

# Abstract
Autonomous research must choose which uncertain step deserves its budget. We
introduce an evidence-grounded controller for that decision. Across three registered
tasks, evaluation shows fewer invalid transitions and faster recovery.

# Introduction
Research agents execute long workflows, yet action selection remains implicit. The
controller makes that decision inspectable and binds it to registered evidence.

# Results
The first experiment asks whether the controller rejects unsupported transitions.
It rejects all registered invalid transitions while retaining every valid action.

# Limitations
The evaluation covers three machine-learning tasks and estimates reliability only
within that registered scope.

# Conclusion
Evidence-grounded action selection makes autonomous research decisions inspectable
and reduces invalid transitions across the registered tasks.
"""

    assessment = assess_writing_taste(manuscript)

    assert assessment.integrity_gate_passes is True
    assert assessment.style_advisory_passes is True
    assert assessment.findings == ()
    assert assessment.scientific_quality_established is False


def test_writing_taste_assessment_is_self_hashed_and_writable(tmp_path) -> None:
    assessment = assess_writing_taste("# Abstract\nWe propose a method and show a result.\n")

    path = write_writing_taste_assessment(assessment, tmp_path / "taste.json")
    reloaded = WritingTasteAssessment.model_validate_json(path.read_text(encoding="utf-8"))

    assert reloaded == assessment
    assert json.loads(path.read_text(encoding="utf-8"))["record_sha256"]
    assert all(
        item.severity in {WritingTasteSeverity.ERROR, WritingTasteSeverity.WARNING}
        for item in assessment.findings
    )


def test_writing_taste_critic_retains_structured_diagnosis() -> None:
    state = ResearchState(
        project_id="writing-taste",
        research_direction="test writing diagnosis",
        target_domain="scientific-writing",
        target_venue="ICLR 2027",
        writing_state=WritingState(
            status="drafted",
            section_drafts={
                "Current Results": (
                    "The repository snapshot has a passing test suite and a wheel build."
                )
            },
        ),
        current_stage="COMMUNICATION",
    )

    findings = WritingTasteCritic().review(state)

    heading = next(item for item in findings if item.code == "project-report-heading")
    assert heading.critic == "writing_taste"
    assert heading.dimension == "narrative_focus"
    assert heading.level == "section"
    assert heading.section_name == "Current Results"
    assert heading.finding_id
    assert heading.recommendation
