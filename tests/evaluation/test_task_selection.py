from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    AutomatedJudgeRole,
    BenchmarkTaskSelectionManifest,
    ScientificEndpointKind,
    TaskSignalKind,
    inspect_task_selection,
    load_external_resource_corpus,
    load_task_selection_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "docs/research/data/mlr_bench_official_ten_candidate_v1.yaml"
SELECTION_V2 = ROOT / "docs/research/data/mlr_bench_official_ten_candidate_v2.yaml"
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


def _v11_selection() -> BenchmarkTaskSelectionManifest:
    payload = load_task_selection_manifest(SELECTION).manifest.model_dump(mode="json")
    payload.update(
        {
            "schema_version": "1.1",
            "primary_endpoint": ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE.value,
            "automated_judge_role": AutomatedJudgeRole.SECONDARY_DIAGNOSTIC.value,
        }
    )
    payload["tasks"] = [
        {
            **task,
            "input_asset_scope": "One pinned workshop-derived research brief.",
            "input_license_status": "verified",
            "signal_kind": TaskSignalKind.RESEARCH_PACKAGE_REVIEW.value,
            "objective_task_score_available": False,
        }
        for task in payload["tasks"]
    ]
    return BenchmarkTaskSelectionManifest.model_validate(payload)


def test_v11_selection_distinguishes_package_review_from_objective_progress() -> None:
    selection = _v11_selection()

    assert selection.primary_endpoint is ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE
    assert all(not task.objective_task_score_available for task in selection.tasks)

    payload = selection.model_dump(mode="json")
    payload["primary_endpoint"] = ScientificEndpointKind.OBJECTIVE_PROGRESS.value
    with pytest.raises(ValidationError, match="objective score for every task"):
        BenchmarkTaskSelectionManifest.model_validate(payload)


def test_tracked_v2_scope_is_review_based_and_still_no_download() -> None:
    selection = load_task_selection_manifest(SELECTION_V2)
    corpus = load_external_resource_corpus(CORPUS)
    report = inspect_task_selection(selection.manifest, corpus.corpus)

    assert selection.manifest.primary_endpoint is (
        ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE
    )
    assert report.schema_version == "1.1"
    assert all(
        task.signal_kind is TaskSignalKind.RESEARCH_PACKAGE_REVIEW
        and task.input_license_status.value == "verified"
        and not task.objective_task_score_available
        for task in selection.manifest.tasks
    )
    assert report.ready_for_owner_scope_review is True
    assert report.authorizes_download is False
    assert report.authorizes_execution is False
    assert len(report.pending_qualifications) == 22


def test_selection_loader_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "selection.yaml"
    link.symlink_to(SELECTION)

    with pytest.raises(ValueError, match="must not be a symlink"):
        load_task_selection_manifest(link)
