from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scitaste.writing.manuscript_quality import (
    ManuscriptAssessment,
    assess_manuscript,
    require_requested_manuscript_role,
)

SHORT_FIXTURE = """## Title
Pipeline Fixture

# Introduction

This sentence exercises manuscript packaging.

# Results

The fixture completed.
"""

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCITASTE_PAPER_TITLE = "SciTaste: Grounded Scientific Taste for Autonomous Research"


def test_short_contract_output_is_explicitly_an_integration_fixture() -> None:
    assessment = assess_manuscript(SHORT_FIXTURE, requested_role="integration-fixture")

    assert assessment.eligible_for_requested_role is True
    assert assessment.substantive_research_draft is False
    assert assessment.paper_status == "integration-fixture"
    assert assessment.manuscript_sha256 == hashlib.sha256(SHORT_FIXTURE.encode()).hexdigest()
    assert assessment.word_count < assessment.minimum_research_words
    assert "abstract" in assessment.missing_research_sections
    assert ManuscriptAssessment.model_validate_json(assessment.model_dump_json()) == assessment


def test_short_fixture_cannot_be_promoted_to_research_working_draft() -> None:
    assessment = assess_manuscript(SHORT_FIXTURE, requested_role="research-working-draft")

    assert assessment.eligible_for_requested_role is False
    with pytest.raises(ValueError, match="research manuscript completeness gate failed"):
        require_requested_manuscript_role(assessment)


def test_substantive_research_draft_requires_length_structure_and_no_placeholders() -> None:
    sections = [
        "Abstract",
        "Introduction",
        "Framework",
        "Evaluation Protocol",
        "Results",
        "Limitations",
        "Conclusion",
    ]
    manuscript = "## Title\nSciTaste\n\n" + "\n\n".join(
        f"# {section}\n\n" + "evidence " * 370 for section in sections
    )

    assessment = assess_manuscript(manuscript, requested_role="research-working-draft")

    require_requested_manuscript_role(assessment)
    assert assessment.eligible_for_requested_role is True
    assert assessment.substantive_research_draft is True
    assert assessment.paper_status == "research-working-draft"
    assert assessment.missing_research_sections == ()


def test_implementation_evidence_is_an_honest_results_section_for_pre_result_draft() -> None:
    manuscript = "## Title\nSciTaste\n\n" + "\n\n".join(
        f"# {section}\n\n" + "evidence " * 370
        for section in (
            "Abstract",
            "Introduction",
            "Method",
            "Evaluation Protocol",
            "Implementation Evidence: Registered Empirical Questions",
            "Limitations",
            "Conclusion",
        )
    )

    assessment = assess_manuscript(manuscript, requested_role="research-working-draft")

    assert assessment.substantive_research_draft is True
    assert assessment.missing_research_sections == ()


def test_placeholder_blocks_research_working_draft() -> None:
    manuscript = SHORT_FIXTURE + "\n" + "evidence " * 2600 + "\nTODO\n"
    assessment = assess_manuscript(manuscript, requested_role="research-working-draft")

    assert assessment.substantive_research_draft is False
    assert assessment.placeholder_markers


def test_tracked_scitaste_manuscript_keeps_specification_title_and_research_role() -> None:
    markdown = (PROJECT_ROOT / "manuscripts/scitaste/main.md").read_text(encoding="utf-8")

    assessment = assess_manuscript(markdown, requested_role="research-working-draft")

    require_requested_manuscript_role(assessment)
    assert assessment.title == SCITASTE_PAPER_TITLE
    assert assessment.manuscript_sha256 == hashlib.sha256(markdown.encode()).hexdigest()
    assert assessment.substantive_research_draft is True
    assert assessment.missing_research_sections == ()
