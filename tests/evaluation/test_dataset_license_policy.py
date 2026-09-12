from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scitaste.cli import main
from scitaste.evaluation import (
    DatasetLicensePolicyManifest,
    inspect_dataset_license_policy,
    load_dataset_license_policy,
    load_dataset_license_policy_report,
    save_dataset_license_policy_report,
)

POLICY = Path("configs/evaluation/acquisition/mlrc_first_preflight_license_policy_v1.yaml")


def test_repository_policy_closes_acquisition_but_not_awa_ingestion() -> None:
    inspection = load_dataset_license_policy(POLICY)
    report = inspect_dataset_license_policy(inspection, workspace_root=".")

    assert len(inspection.file_sha256) == 64
    assert len(inspection.policy.policy_sha256) == 64
    assert report.asset_count == 39
    assert report.policy_profile_count == 9
    assert report.resolved_inventory_status_count == 36
    assert report.acquisition_license_ready is True
    assert report.ingestion_license_ready is False
    assert report.integrity_blockers == ()
    assert report.license_blockers == ()
    assert [item.task_id for item in report.task_qualifications] == [
        "perception_temporal_action_loc",
        "meta-learning",
    ]
    assert report.task_qualifications[0].ingestion_license_ready is True
    assert report.task_qualifications[1].pending_post_acquisition_checks == (
        "awa-per-image-license-coverage-complete",
        "awa-per-image-license-records-present",
    )
    assert report.authorizes_download is False
    assert report.authorizes_ingestion is False
    assert report.authorizes_api_calls is False
    assert report.authorizes_gpu_work is False
    assert report.no_network_access_performed is True


def test_policy_report_round_trip_detects_tampering(tmp_path: Path) -> None:
    report = inspect_dataset_license_policy(
        load_dataset_license_policy(POLICY),
        workspace_root=".",
    )
    path = save_dataset_license_policy_report(report, tmp_path / "REPORT.json")
    assert load_dataset_license_policy_report(path) == report

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["asset_count"] -= 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"asset count|hash mismatch"):
        load_dataset_license_policy_report(path)


def test_policy_fails_closed_on_inventory_or_asset_drift(tmp_path: Path) -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["inventory"]["sha256"] = "0" * 64
    drifted = tmp_path / "policy.yaml"
    drifted.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    report = inspect_dataset_license_policy(
        load_dataset_license_policy(drifted),
        workspace_root=".",
    )
    assert report.acquisition_license_ready is False
    assert {item.code for item in report.integrity_blockers} == {"inventory:hash-mismatch"}

    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["asset_bindings"] = payload["asset_bindings"][:-1]
    drifted.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    report = inspect_dataset_license_policy(
        load_dataset_license_policy(drifted),
        workspace_root=".",
    )
    assert report.acquisition_license_ready is False
    assert "assets:binding-missing" in {item.code for item in report.integrity_blockers}


def test_policy_rejects_authority_or_pending_check_weakening() -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["authorizes_download"] = True
    with pytest.raises(ValueError, match="authorizes_download"):
        DatasetLicensePolicyManifest.model_validate(payload)

    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    awa = next(
        item
        for item in payload["profiles"]
        if item["profile_id"] == "meta-awa-per-image-with-release-overlay"
    )
    awa["post_acquisition_checks"] = []
    with pytest.raises(ValueError, match="post-acquisition checks"):
        DatasetLicensePolicyManifest.model_validate(payload)


def test_cli_distinguishes_acquisition_from_ingestion_readiness(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "REPORT.json"
    assert (
        main(
            [
                "evaluation",
                "dataset-package-license",
                "--manifest",
                str(POLICY),
                "--workspace-root",
                ".",
                "--output",
                str(report_path),
                "--require-acquisition-ready",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["acquisition_license_ready"] is True
    assert output["ingestion_license_ready"] is False
    assert output["report"] == str(report_path)

    assert (
        main(
            [
                "evaluation",
                "dataset-package-license",
                "--manifest",
                str(POLICY),
                "--workspace-root",
                ".",
                "--require-ingestion-ready",
            ]
        )
        == 1
    )
