from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "data"
    / "writing_taste_reference_corpus_v1.yaml"
)


def _load_corpus() -> dict[str, object]:
    return yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))


def test_reference_corpus_pins_the_complete_recognized_population() -> None:
    corpus = _load_corpus()
    papers = corpus["papers"]

    assert corpus["status"] == "candidate_reference_library"
    assert corpus["normative_status"] == "not_yet_promoted_to_writing_taste_rules"
    assert len(papers) == corpus["selection"]["positive_population"]["count"] == 29
    assert Counter(paper["year"] for paper in papers) == {
        2023: 4,
        2024: 16,
        2025: 6,
        2026: 3,
    }
    assert Counter(paper["recognition"] for paper in papers) == {
        "outstanding": 14,
        "honorable_mention": 15,
    }

    reference_ids = [paper["reference_id"] for paper in papers]
    assert len(reference_ids) == len(set(reference_ids))
    assert all(re.fullmatch(r"[0-9a-f]{64}", paper["pdf_sha256"]) for paper in papers)


def test_reference_corpus_measurements_match_the_documented_snapshot() -> None:
    papers = _load_corpus()["papers"]

    totals = Counter()
    for paper in papers:
        totals.update(paper["counts"])

    assert totals == {
        "pdf_pages": 910,
        "unique_figure_labels": 301,
        "unique_table_labels": 178,
        "unique_algorithm_labels": 31,
    }
    assert any(paper["counts"]["unique_figure_labels"] == 0 for paper in papers)
    assert any(
        paper["archetype"] == "empirical_method" and paper["counts"]["unique_figure_labels"] <= 3
        for paper in papers
    )


def test_candidate_principles_are_traceable_but_not_promoted() -> None:
    corpus = _load_corpus()
    papers = {paper["reference_id"]: paper for paper in corpus["papers"]}
    projects = {project["reference_id"]: project for project in corpus["open_source_projects"]}

    principles = corpus["candidate_principles"]
    assert len(principles) == 15
    assert corpus["promotion_gate"]["current_decision"] == "hold"

    for principle in principles:
        supporting = principle["supporting_references"]
        assert len(supporting) >= 3
        assert set(supporting) <= papers.keys()
        assert len({papers[reference_id]["year"] for reference_id in supporting}) >= 2
        assert set(principle.get("boundary_references", [])) <= papers.keys()
        assert set(principle.get("triangulating_projects", [])) <= projects.keys()


def test_no_license_projects_remain_comparison_only() -> None:
    projects = _load_corpus()["open_source_projects"]

    restricted = [
        project for project in projects if project["license"] == "no_license_file_observed"
    ]
    assert restricted
    assert all(
        project["use_policy"] == "citation_and_method_comparison_only" for project in restricted
    )
