from __future__ import annotations

import json
from pathlib import Path

import scitaste.benchmark.manuscript as manuscript
from scitaste.benchmark.manuscript import (
    markdown_to_latex,
    markdown_to_venue_latex,
    materialize_manuscript,
    materialize_venue_manuscript,
)
from scitaste.writing.venue import inspect_venue_template
from tests.writing.test_venue import _template

SAMPLE = """## Title
FROST: Evidence-Bounded Diagnostics

## Abstract
We report **balanced accuracy** across three seeds.

## Introduction
Position matters [liu-etal-2024-lost].

## Results
| Method | Score |
|---|---:|
| Majority_vote | 0.82 |

![Observed comparison](charts/comparison.png)
"""


def test_markdown_to_latex_preserves_math_citations_and_tables() -> None:
    tex = markdown_to_latex(
        SAMPLE + "\nThe metric is $x_1 = 0.82$.\n",
        asset_map={"charts/comparison.png": "figures/comparison.png"},
        has_bibliography=True,
    )

    assert "\\title{FROST: Evidence-Bounded Diagnostics}" in tex
    assert "\\begin{abstract}" in tex
    assert "\\citep{liu-etal-2024-lost}" in tex
    assert "Majority\\_vote & 0.82 \\\\" in tex
    assert "$x_1 = 0.82$" in tex
    assert "figures/comparison.png" in tex
    assert "\\bibliography{references}" in tex


def test_materialize_manuscript_creates_self_contained_bundle(tmp_path, monkeypatch) -> None:
    source = tmp_path / "paper.md"
    source.write_text(SAMPLE + "\n![Repeated](charts/comparison.png)\n", encoding="utf-8")
    bibliography = tmp_path / "source.bib"
    bibliography.write_text(
        "@article{liu-etal-2024-lost, title={Lost in the Middle}, year={2024}}\n",
        encoding="utf-8",
    )
    assets = tmp_path / "assets" / "charts"
    assets.mkdir(parents=True)
    (assets / "comparison.png").write_bytes(b"not-compiled-in-unit-test")
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)

    target = tmp_path / "bundle"
    paths = materialize_manuscript(
        markdown_path=source,
        target_dir=target,
        bibliography_path=bibliography,
        asset_roots=(tmp_path / "assets",),
    )

    assert target / "main.md" in paths
    assert target / "main.tex" in paths
    assert target / "references.bib" in paths
    assert target / "figures" / "comparison.png" in paths
    assert paths.count(target / "figures" / "comparison.png") == 1
    build = json.loads((target / "build.json").read_text())
    assert build["status"] == "unavailable"
    assert build["pdf_generated"] is False


def test_venue_renderer_uses_anonymous_style_and_non_counted_statements(tmp_path: Path) -> None:
    template = inspect_venue_template(_template(tmp_path))
    markdown = (
        SAMPLE.replace("## Results", "## Results")
        + """

# AI Use Statement
AI assisted editing; all claims were checked.

# Ethics Statement
No human-subject data were used.
"""
    )

    tex = markdown_to_venue_latex(
        markdown,
        template=template,
        asset_map={"charts/comparison.png": "figures/comparison.png"},
    )

    assert "\\usepackage{venue,times}" in tex
    assert "\\author{}" in tex
    assert "\\iclrfinalcopy" not in tex
    assert tex.index("\\label{scitaste-main-text-end}") < tex.index(
        "\\subsection*{AI Use Statement}"
    )
    assert "\\bibliographystyle{venue}" in tex


def test_materialize_venue_manuscript_writes_assessed_pdf_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    template = inspect_venue_template(_template(tmp_path))
    source = tmp_path / "paper.md"
    evidence = "Evidence-backed sentence. " * 430
    source.write_text(
        f"""## Title
Venue Paper

## Abstract
One abstract paragraph with evidence [smith2026]. {evidence}

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
    bibliography = tmp_path / "references-source.bib"
    bibliography.write_text(
        "@article{smith2026, title={A Result}, year={2026}}\n",
        encoding="utf-8",
    )

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
            "main_text_pages": 8,
            "statement_pages": {"AI Use Statement": 1},
        }

    monkeypatch.setattr(manuscript, "_compile_latex_bundle", fake_compile)

    paths, assessment, manuscript_assessment = materialize_venue_manuscript(
        markdown_path=source,
        bibliography_path=bibliography,
        target_dir=tmp_path / "bundle",
        template=template,
    )

    assert assessment.eligible_for_submission is True
    assert manuscript_assessment.substantive_research_draft is True
    assert tmp_path / "bundle" / "main.pdf" in paths
    assert tmp_path / "bundle" / "SUBMISSION_ASSESSMENT.json" in paths
    assert tmp_path / "bundle" / "MANUSCRIPT_ASSESSMENT.json" in paths
    assert json.loads((tmp_path / "bundle" / "build.json").read_text())["main_text_pages"] == 8
