from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
import yaml

from scitaste.writing.venue import (
    VenueSubmissionAssessment,
    assess_venue_submission,
    inspect_venue_template,
    materialize_venue_assets,
    require_venue_submission_ready,
)


def _template(tmp_path: Path, *, extra: dict[str, bytes] | None = None) -> Path:
    files = {
        "venue/venue.sty": b"% exact style\n",
        "venue/venue.bst": b"% exact bibliography style\n",
        "venue/math_commands.tex": b"% exact math commands\n",
        **(extra or {}),
    }
    archive_path = tmp_path / "template.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    assets = [
        {
            "archive_path": name,
            "output_name": Path(name).name,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for name, content in files.items()
        if name in {"venue/venue.sty", "venue/venue.bst", "venue/math_commands.tex"}
    ]
    config = {
        "schema_version": "1.0",
        "venue_id": "test-venue",
        "venue_name": "Test Venue",
        "template_archive": str(archive_path),
        "expected_archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "style_package": "venue",
        "bibliography_style": "venue",
        "assets": assets,
        "submission_mode": "anonymous",
        "max_main_pages": 9,
        "required_statements": ["AI Use Statement"],
        "recommended_statements": ["Ethics Statement"],
        "statement_page_limits": {"AI Use Statement": 1},
    }
    config_path = tmp_path / "venue.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def test_template_inspection_and_materialization_are_content_bound(tmp_path: Path) -> None:
    inspection = inspect_venue_template(_template(tmp_path))

    written = materialize_venue_assets(inspection, target_dir=tmp_path / "bundle")

    assert inspection.config.venue_id == "test-venue"
    assert {path.name for path in written} == {
        "venue.sty",
        "venue.bst",
        "math_commands.tex",
    }
    assert (tmp_path / "bundle" / "venue.sty").read_bytes() == b"% exact style\n"


def test_template_inspection_rejects_unsafe_unregistered_archive_member(tmp_path: Path) -> None:
    config_path = _template(tmp_path, extra={"../escape.txt": b"blocked"})

    with pytest.raises(ValueError, match="unsafe path"):
        inspect_venue_template(config_path)


def test_submission_assessment_closes_citations_anonymity_statements_and_pages(
    tmp_path: Path,
) -> None:
    inspection = inspect_venue_template(_template(tmp_path))
    markdown = """## Title
Anonymous Result

## Abstract
One paragraph with a closed citation [smith2026].

# Introduction
The method is evaluated without author metadata.

# Conclusion
The result remains bounded.

# AI Use Statement
Generative AI assisted drafting; the authors verified all resulting claims.

# Ethics Statement
The work uses public software artifacts and no human-subject data.
"""
    bibliography = "@article{smith2026, title={A Result}, year={2026}}\n"

    assessment = assess_venue_submission(
        markdown,
        bibliography,
        template=inspection,
        compiled=True,
        main_text_pages=9,
        statement_pages={"AI Use Statement": 1},
    )

    require_venue_submission_ready(assessment)
    assert assessment.eligible_for_submission is True
    assert assessment.missing_citation_keys == ()
    assert VenueSubmissionAssessment.model_validate_json(assessment.model_dump_json()) == assessment


def test_submission_gate_reports_all_deterministic_blockers(tmp_path: Path) -> None:
    inspection = inspect_venue_template(_template(tmp_path))
    markdown = """## Title
Named Draft

## Authors
author@example.org

## Abstract
First paragraph [missing2026].

Second paragraph.

# Results
The internal artifact is outputs/projects/example/runs/run-1.
"""

    assessment = assess_venue_submission(
        markdown,
        "",
        template=inspection,
        compiled=True,
        main_text_pages=10,
        statement_pages={},
    )

    assert assessment.eligible_for_submission is False
    assert assessment.missing_citation_keys == ("missing2026",)
    assert assessment.missing_required_statements == ("AI Use Statement",)
    assert assessment.identity_markers
    assert assessment.internal_markers
    with pytest.raises(ValueError, match="venue submission gate failed"):
        require_venue_submission_ready(assessment)
