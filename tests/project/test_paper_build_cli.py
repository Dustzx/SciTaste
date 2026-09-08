from __future__ import annotations

import json
from pathlib import Path

import scitaste.benchmark.manuscript as manuscript
from scitaste.cli import build_parser
from scitaste.project import ProjectManifest, ProjectRuntime
from tests.writing.test_venue import _template


def _project(runtime: ProjectRuntime) -> None:
    runtime.create(
        ProjectManifest(
            project_id="paper-build-project",
            title="Paper build project",
            research_direction="Test venue-native paper packaging.",
            target_venue="Test Venue",
            status="active",
        )
    )


def _sources(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "paper.md"
    evidence = "Evidence-backed sentence. " * 430
    source.write_text(
        f"""## Title
Venue Paper

## Abstract
One paragraph [smith2026]. {evidence}

# Introduction
{evidence}

# Framework
{evidence}

# Evaluation
{evidence}

# Results
{evidence}

# Limitations
{evidence}

# Conclusion
{evidence}

# AI Use Statement
AI assisted editing; all claims were checked.

# Ethics Statement
No human-subject data were used.
""",
        encoding="utf-8",
    )
    bibliography = tmp_path / "references.bib"
    bibliography.write_text(
        "@article{smith2026, title={A Result}, year={2026}}\n",
        encoding="utf-8",
    )
    return source, bibliography


def _arguments(
    tmp_path: Path,
    *,
    source: Path,
    bibliography: Path,
    venue: Path,
    dry_run: bool,
) -> list[str]:
    arguments = [
        "project",
        "paper",
        "build",
        "--project-id",
        "paper-build-project",
        "--directory-name",
        "venue-draft-v1",
        "--source",
        str(source),
        "--bibliography",
        str(bibliography),
        "--venue-config",
        str(venue),
        "--expected-revision",
        "0",
        "--outputs-root",
        str(tmp_path / "outputs"),
    ]
    if dry_run:
        arguments.append("--dry-run")
    return arguments


def test_project_paper_build_dry_run_is_read_only(tmp_path: Path, capsys) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    source, bibliography = _sources(tmp_path)
    venue = _template(tmp_path)
    args = build_parser().parse_args(
        _arguments(
            tmp_path,
            source=source,
            bibliography=bibliography,
            venue=venue,
            dry_run=True,
        )
    )

    assert args.handler(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "planned"
    assert payload["preflight"]["missing_citation_keys"] == []
    assert payload["manuscript_preflight"]["substantive_research_draft"] is True
    assert payload["writing_taste_preflight"]["profile_id"] == "scitaste-writing-taste-v1"
    assert payload["would_compile"] is True
    assert not (runtime.projects_root / "paper-build-project/papers/venue-draft-v1").exists()


def test_project_paper_build_registers_gated_bundle(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    source, bibliography = _sources(tmp_path)
    venue = _template(tmp_path)

    def fake_compile(
        target: Path,
        *,
        latex_engine: str = "xelatex",
        statement_labels: dict[str, str] | None = None,
    ) -> dict[str, object]:
        assert latex_engine == "pdflatex"
        assert statement_labels and "AI Use Statement" in statement_labels
        (target / "main.pdf").write_bytes(b"unit-test-pdf")
        return {
            "schema_version": "1.0",
            "engine": "latexmk-pdflatex",
            "status": "succeeded",
            "returncode": 0,
            "pdf_generated": True,
            "main_text_pages": 7,
            "statement_pages": {"AI Use Statement": 1},
        }

    monkeypatch.setattr(manuscript, "_compile_latex_bundle", fake_compile)
    args = build_parser().parse_args(
        _arguments(
            tmp_path,
            source=source,
            bibliography=bibliography,
            venue=venue,
            dry_run=False,
        )
    )

    assert args.handler(args) == 0
    capsys.readouterr()

    snapshot = runtime.open("paper-build-project")
    paper = snapshot.papers[0].manifest
    bundle = runtime.projects_root / "paper-build-project/papers/venue-draft-v1"
    assert snapshot.revision == 1
    assert paper.status == "venue-submission-draft"
    assert paper.model_extra["eligible_for_submission"] is True
    assert paper.model_extra["writing_taste_assessment_sha256"]
    assert (bundle / "main.pdf").is_file()
    assert (bundle / "SUBMISSION_ASSESSMENT.json").is_file()
    assert (bundle / "MANUSCRIPT_ASSESSMENT.json").is_file()
    assert (bundle / "WRITING_TASTE_ASSESSMENT.json").is_file()
    assert paper.files["writing-taste-assessment"] == "WRITING_TASTE_ASSESSMENT.json"
