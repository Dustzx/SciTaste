from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    BenchmarkTaskSelectionManifest,
    inspect_task_selection,
    load_external_resource_corpus,
    load_task_selection_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "docs/research/data/mlr_bench_official_ten_candidate_v1.yaml"
CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v2.yaml"


def test_official_ten_is_exact_metadata_scope_without_download_authority() -> None:
    selection = load_task_selection_manifest(SELECTION)
    corpus = load_external_resource_corpus(CORPUS)

    report = inspect_task_selection(selection.manifest, corpus.corpus)

    assert report.ready_for_owner_scope_review is True
    assert report.task_count == 10
    assert report.source_group_count == 10
    assert report.category_counts == {
        "LLM/VLM": 2,
        "ML Theory": 1,
        "Trustworthy AI": 7,
    }
    assert report.ready_for_experiment is False
    assert report.authorizes_download is False
    assert report.authorizes_execution is False
    assert report.no_download_performed is True
    assert {task.task_id for task in selection.manifest.tasks} >= {
        "iclr2025_buildingtrust",
        "iclr2025_question",
        "iclr2025_wsl",
    }
    assert len(report.pending_qualifications) == 22


def test_selection_detects_resource_pin_drift() -> None:
    selection = load_task_selection_manifest(SELECTION).manifest
    corpus = load_external_resource_corpus(CORPUS).corpus
    drifted = selection.model_copy(update={"repository_commit": "a" * 40})

    report = inspect_task_selection(drifted, corpus)

    assert report.ready_for_owner_scope_review is False
    assert {finding.code for finding in report.blockers} >= {
        "repository_pin_mismatch",
        "unpinned_task_locator:iclr2025_bi_align",
    }


def test_selection_rejects_duplicate_source_groups() -> None:
    selection = load_task_selection_manifest(SELECTION).manifest
    payload = selection.model_dump(mode="json")
    payload["tasks"][1]["source_group"] = payload["tasks"][0]["source_group"]

    with pytest.raises(ValidationError, match="source groups must be unique"):
        BenchmarkTaskSelectionManifest.model_validate(payload)


def test_selection_loader_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "selection.yaml"
    link.symlink_to(SELECTION)

    with pytest.raises(ValueError, match="must not be a symlink"):
        load_task_selection_manifest(link)
