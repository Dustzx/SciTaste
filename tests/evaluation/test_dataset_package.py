from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    DatasetPackageGateReport,
    DatasetPackageInventory,
    DatasetPackageRequestInspection,
    inspect_dataset_package_request,
    load_dataset_package_gate_report,
    load_dataset_package_inventory,
    load_dataset_package_request,
    save_dataset_package_gate_report,
)

INVENTORY_PATH = Path("docs/research/data/mlrc_first_preflight_asset_inventory_v1.yaml")
REQUEST_PATH = Path("configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml")


def test_repository_inventory_freezes_exact_first_preflight_assets() -> None:
    inspection = load_dataset_package_inventory(INVENTORY_PATH)
    inventory = inspection.inventory

    assert len(inspection.file_sha256) == 64
    assert inventory.asset_count == 39
    assert inventory.observed_compressed_bytes == 3_761_168_137
    assert inventory.maximum_unpacked_bytes == 16 * 1024**3
    assert [task.task_id for task in inventory.tasks] == [
        "perception_temporal_action_loc",
        "meta-learning",
    ]
    assert [len(task.assets) for task in inventory.tasks] == [9, 30]
    assert [task.observed_compressed_bytes for task in inventory.tasks] == [
        698_506_926,
        3_062_661_211,
    ]
    assert all(item.expected_sha256 is None for task in inventory.tasks for item in task.assets)
    assert inventory.authorizes_download is False
    assert inventory.authorizes_execution is False


def test_repository_request_is_metadata_ready_but_not_approval_ready() -> None:
    inspection = load_dataset_package_request(REQUEST_PATH)

    report = inspect_dataset_package_request(inspection, workspace_root=".")

    assert report.selected_task_ids == (
        "perception_temporal_action_loc",
        "meta-learning",
    )
    assert report.source_hosts == ("data.openml.org", "drive.usercontent.google.com")
    assert report.asset_count == 39
    assert report.observed_download_bytes == 3_761_168_137
    assert report.minimum_free_storage_bytes == 32 * 1024**3
    assert report.metadata_review_ready is True
    assert report.ready_for_owner_approval is False
    assert report.pending_content_hash_count == 39
    assert {item.code for item in report.approval_blockers} == {
        "license:meta-learning:blocked",
        "license:perception_temporal_action_loc:review_required",
    }
    assert {item.code for item in report.pending_qualifications} == {
        "archive-safety:qualification-pending",
        "content-hashes:pending-first-acquisition",
        "network-preflight:not-approved",
    }
    assert [item.code for item in report.authorization_blockers] == ["owner-approval-required"]
    assert report.authorizes_network_preflight is False
    assert report.authorizes_download is False
    assert report.authorizes_api_calls is False
    assert report.authorizes_gpu_work is False
    assert report.authorizes_execution is False
    assert report.no_network_access_performed is True
    assert report.no_download_performed is True


def test_candidate_or_inventory_drift_fails_closed() -> None:
    inspection = load_dataset_package_request(REQUEST_PATH)
    request = inspection.request
    drifted_candidate = request.candidate_manifest.model_copy(update={"sha256": "0" * 64})
    drifted = request.model_copy(update={"candidate_manifest": drifted_candidate})

    report = inspect_dataset_package_request(
        DatasetPackageRequestInspection(
            path=inspection.path,
            file_sha256=inspection.file_sha256,
            request=drifted,
        ),
        workspace_root=".",
    )

    assert report.metadata_review_ready is False
    assert "candidate:hash-mismatch" in {item.code for item in report.integrity_blockers}
    assert report.ready_for_owner_approval is False

    drifted_inventory = request.inventory.model_copy(update={"sha256": "f" * 64})
    drifted = request.model_copy(update={"inventory": drifted_inventory})
    report = inspect_dataset_package_request(
        DatasetPackageRequestInspection(
            path=inspection.path,
            file_sha256=inspection.file_sha256,
            request=drifted,
        ),
        workspace_root=".",
    )
    assert report.asset_count == 0
    assert "inventory:hash-mismatch" in {item.code for item in report.integrity_blockers}


def test_inventory_rejects_false_arithmetic_and_source_identity() -> None:
    inventory = load_dataset_package_inventory(INVENTORY_PATH).inventory
    payload = inventory.model_dump(mode="json")
    payload["asset_count"] -= 1
    with pytest.raises(ValidationError, match="asset count"):
        DatasetPackageInventory.model_validate(payload)

    payload = inventory.model_dump(mode="json")
    payload["tasks"][1]["assets"][0]["source_url"] = (
        "https://data.openml.org/datasets/0004/99999/BRD_Mini.zip"
    )
    with pytest.raises(ValidationError, match="dataset identity"):
        DatasetPackageInventory.model_validate(payload)


def test_report_round_trip_detects_tampering(tmp_path: Path) -> None:
    report = inspect_dataset_package_request(
        load_dataset_package_request(REQUEST_PATH),
        workspace_root=".",
    )
    path = save_dataset_package_gate_report(report, tmp_path / "REPORT.json")

    assert load_dataset_package_gate_report(path) == report
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["proposal_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset_package_gate_report(path)


def test_report_rejects_inconsistent_summary() -> None:
    report = inspect_dataset_package_request(
        load_dataset_package_request(REQUEST_PATH),
        workspace_root=".",
    )
    payload = report.model_dump(mode="json", exclude={"report_sha256"})
    payload["asset_count"] += 1
    with pytest.raises(ValidationError, match="asset count"):
        DatasetPackageGateReport.model_validate(payload)


def test_cli_separates_metadata_readiness_from_owner_approval(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "REPORT.json"
    base = [
        "evaluation",
        "dataset-package-request",
        "--manifest",
        str(REQUEST_PATH),
        "--workspace-root",
        ".",
    ]

    assert main([*base, "--require-metadata-review-ready", "--output", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metadata_review_ready"] is True
    assert payload["ready_for_owner_approval"] is False
    assert payload["report"] == str(output)
    assert load_dataset_package_gate_report(output).request_id == "mlrc-first-preflight-assets-v1"

    assert main([*base, "--require-owner-approval-ready"]) == 1
    capsys.readouterr()


def test_loaders_reject_top_level_symlinks(tmp_path: Path) -> None:
    inventory_link = tmp_path / "inventory.yaml"
    inventory_link.symlink_to(INVENTORY_PATH.resolve())
    with pytest.raises(ValueError, match="must not be a symlink"):
        load_dataset_package_inventory(inventory_link)

    request_link = tmp_path / "request.yaml"
    request_link.symlink_to(REQUEST_PATH.resolve())
    with pytest.raises(ValueError, match="must not be a symlink"):
        load_dataset_package_request(request_link)
