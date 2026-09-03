from __future__ import annotations

import json

import scitaste.benchmark.manuscript as manuscript
from scitaste.benchmark.manuscript import markdown_to_latex, materialize_manuscript

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
    source.write_text(SAMPLE, encoding="utf-8")
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
    build = json.loads((target / "build.json").read_text())
    assert build["status"] == "unavailable"
    assert build["pdf_generated"] is False
