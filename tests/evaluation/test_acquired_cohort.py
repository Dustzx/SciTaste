from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scitaste.cli import main
from scitaste.evaluation import (
    AcquiredTaskUse,
    approve_dataset_acquisition_request,
    inspect_acquired_task_cohort,
    load_acquired_task_cohort_report,
    load_dataset_acquisition_request,
    materialize_dataset_acquisition,
    save_dataset_acquisition_request,
)

ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "docs/research/data/mlr_bench_official_ten_candidate_v2.yaml"
RESOURCE_CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v6.yaml"
REQUEST = ROOT / "configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml"
TRACKED_INVENTORY = ROOT / "docs/research/data/mlr_bench_ten_brief_acquisition_inventory_v1.yaml"


def _acquired_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    selection = tmp_path / "docs/research/data/mlr_bench_official_ten_candidate_v2.yaml"
    corpus = tmp_path / "docs/research/data/autoresearch_evaluation_resources_v6.yaml"
    selection.parent.mkdir(parents=True)
    shutil.copyfile(SELECTION, selection)
    shutil.copyfile(RESOURCE_CORPUS, corpus)

    request = load_dataset_acquisition_request(REQUEST).request
    approved = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    approved_path = tmp_path / "approved-request.yaml"
    save_dataset_acquisition_request(approved, approved_path)
    materialize_dataset_acquisition(
        approved,
        workspace_root=tmp_path,
        confirmed_request_sha256=request.request_sha256,
        allow_network_download=True,
        fetcher=lambda url, _maximum, _media: (f"# Frozen brief\n\nSource: {url}\n").encode(),
        acquired_at=datetime(2026, 9, 12, 1, tzinfo=UTC),
    )
    receipt = (
        tmp_path
        / "outputs/projects/scitaste-self-development/evaluations/acquisitions"
        / "mlr-bench-official-ten-briefs-v1/RECEIPT.json"
    )
    return selection, approved_path, receipt


def test_exact_briefs_are_pilot_ready_but_not_empirical_tasks(tmp_path: Path) -> None:
    selection, approved, receipt = _acquired_fixture(tmp_path)

    report = inspect_acquired_task_cohort(
        selection_path=selection,
        approved_request_path=approved,
        receipt_path=receipt,
        workspace_root=tmp_path,
    )

    assert report.exact_task_set_verified is True
    assert report.exact_bytes_verified is True
    assert report.task_count == 10
    assert report.ready_for_stagewise_pilot is True
    assert report.ready_for_brief_only_package_prepilot is True
    assert report.ready_for_formal_empirical_task_binding is False
    assert report.ready_for_objective_progress_binding is False
    assert report.runtime_assets_present is False
    assert report.objective_scores_present is False
    assert report.scientific_disposition == "brief-only-pilot-candidate"
    assert {item.code for item in report.formal_task_blockers} == {
        "held-out-audit-pending",
        "runtime-assets-absent",
        "executable-signal-unverified",
    }
    assert {item.code for item in report.objective_progress_blockers} == {"objective-score-absent"}
    assert all(
        task.eligible_uses
        == (
            AcquiredTaskUse.STAGEWISE_IDEA_PROPOSAL,
            AcquiredTaskUse.BRIEF_ONLY_PACKAGE_PREPILOT,
        )
        for task in report.tasks
    )
    assert report.authorizes_ingestion is False
    assert report.authorizes_execution is False
    assert report.provider_call_performed is False
    assert report.gpu_work_performed is False


def test_real_acquisition_inventory_binds_the_qualified_cohort() -> None:
    payload = yaml.safe_load(TRACKED_INVENTORY.read_text(encoding="utf-8"))

    assert payload["request_sha256"] == (
        "f1333432cb0585105ec4d6274e7d78b2d7d0694141256483467887ea6d27cc69"
    )
    assert payload["receipt_sha256"] == (
        "96975fdea75cd00c9496bb7625d4045a2a31d005cb4f0a5144f7e0d274e2c3b8"
    )
    assert payload["qualification_report_sha256"] == (
        "5595436d39804f978f6f8678664684b31ef2d437352a8fc17747f86a985d57da"
    )
    assert payload["item_count"] == 10
    assert payload["total_bytes"] == 31_345
    assert payload["ready_for_brief_only_package_prepilot"] is True
    assert payload["ready_for_formal_empirical_task_binding"] is False
    assert payload["ready_for_objective_progress_binding"] is False


def test_acquired_byte_drift_invalidates_the_whole_cohort(tmp_path: Path) -> None:
    selection, approved, receipt = _acquired_fixture(tmp_path)
    target = (
        tmp_path
        / "outputs/projects/scitaste-self-development/evaluations/acquisitions"
        / "mlr-bench-official-ten-briefs-v1/raw/iclr2025_bi_align.md"
    )
    target.write_text("drift\n", encoding="utf-8")

    report = inspect_acquired_task_cohort(
        selection_path=selection,
        approved_request_path=approved,
        receipt_path=receipt,
        workspace_root=tmp_path,
    )

    assert report.exact_bytes_verified is False
    assert report.ready_for_stagewise_pilot is False
    assert report.scientific_disposition == "invalid-acquisition"
    assert {item.code for item in report.integrity_blockers} >= {"acquired-size-mismatch"}


def test_unexpected_file_invalidates_the_receipt_inventory(tmp_path: Path) -> None:
    selection, approved, receipt = _acquired_fixture(tmp_path)
    raw = receipt.parent / "raw"
    (raw / "unregistered.md").write_text("not in receipt\n", encoding="utf-8")

    report = inspect_acquired_task_cohort(
        selection_path=selection,
        approved_request_path=approved,
        receipt_path=receipt,
        workspace_root=tmp_path,
    )

    assert report.exact_bytes_verified is False
    assert {item.code for item in report.integrity_blockers} == {"unexpected-acquired-files"}


def test_symlink_invalidates_the_receipt_inventory(tmp_path: Path) -> None:
    selection, approved, receipt = _acquired_fixture(tmp_path)
    raw = receipt.parent / "raw"
    (raw / "linked.md").symlink_to(raw / "iclr2025_bi_align.md")

    report = inspect_acquired_task_cohort(
        selection_path=selection,
        approved_request_path=approved,
        receipt_path=receipt,
        workspace_root=tmp_path,
    )

    assert report.exact_bytes_verified is False
    assert {item.code for item in report.integrity_blockers} == {"acquired-symlink-forbidden"}


def test_symlinked_raw_root_is_rejected(tmp_path: Path) -> None:
    selection, approved, receipt = _acquired_fixture(tmp_path)
    raw = receipt.parent / "raw"
    real_raw = receipt.parent / "raw-real"
    raw.rename(real_raw)
    raw.symlink_to(real_raw, target_is_directory=True)

    report = inspect_acquired_task_cohort(
        selection_path=selection,
        approved_request_path=approved,
        receipt_path=receipt,
        workspace_root=tmp_path,
    )

    assert report.exact_bytes_verified is False
    assert {item.code for item in report.integrity_blockers} >= {"raw-root-unavailable"}


def test_acquired_cohort_cli_saves_self_hashed_no_run_report(
    tmp_path: Path,
    capsys,
) -> None:
    selection, approved, receipt = _acquired_fixture(tmp_path)
    output = tmp_path / "cohort-report.json"

    status = main(
        [
            "evaluation",
            "acquired-task-cohort",
            "--selection",
            str(selection),
            "--approved-request",
            str(approved),
            "--receipt",
            str(receipt),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output),
            "--require-brief-pilot-ready",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report_path"] == str(output)
    assert payload["report_sha256"] == saved["report_sha256"]
    assert payload["ready_for_formal_empirical_task_binding"] is False
    assert payload["authorizes_execution"] is False
    assert load_acquired_task_cohort_report(output).report_sha256 == payload["report_sha256"]

    saved["task_count"] += 1
    output.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ValueError, match=r"task inventory|semantic hash"):
        load_acquired_task_cohort_report(output)

    status = main(
        [
            "evaluation",
            "acquired-task-cohort",
            "--selection",
            str(selection),
            "--approved-request",
            str(approved),
            "--receipt",
            str(receipt),
            "--workspace-root",
            str(tmp_path),
            "--require-formal-task-ready",
        ]
    )
    assert status == 1
