from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scitaste.cli import main
from scitaste.evaluation import (
    DatasetAssetLicenseDisposition,
    DatasetAssetLicenseStatus,
    DatasetAssetSourceKind,
    DatasetPackageAcquisitionRequest,
    DatasetPackageAsset,
    DatasetPackageFileBinding,
    DatasetPackageFinding,
    DatasetPackageGateReport,
    DatasetPackageInventory,
    DatasetPackageSourceObservation,
    DatasetPackageTaskInventory,
    DatasetPackageTaskQualification,
    approve_dataset_archive_read,
    approve_dataset_package_request,
    inspect_dataset_package_archives,
    inspect_dataset_package_request,
    load_dataset_archive_qualification_report,
    load_dataset_archive_read_approval,
    load_dataset_package_approval,
    load_dataset_package_receipt,
    load_dataset_package_request,
    materialize_dataset_package_acquisition,
    save_dataset_archive_qualification_report,
    save_dataset_archive_read_approval,
    save_dataset_package_approval,
)

REPOSITORY_REQUEST = Path("configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml")
OBSERVED_AT = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _zip_bytes(*, member: str = "data/value.txt", content: bytes = b"safe") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, content)
    return buffer.getvalue()


def _symlink_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("data/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")
    return buffer.getvalue()


def _archive_read_authority(root: Path, inspection, approval, receipt):
    download_path = save_dataset_package_approval(
        approval,
        root / "archive-download-approval.json",
    )
    receipt_path = root / "outputs/acquisitions/tiny-package/RECEIPT.json"
    download_inspection = load_dataset_package_approval(download_path)
    receipt_inspection = load_dataset_package_receipt(receipt_path)
    read_approval = approve_dataset_archive_read(
        inspection,
        download_inspection,
        receipt_inspection,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_receipt_sha256=receipt.receipt_sha256,
        approved_by="test-owner",
        approved_at=OBSERVED_AT,
    )
    read_path = save_dataset_archive_read_approval(
        read_approval,
        root / "archive-read-approval.json",
    )
    return (
        download_inspection,
        receipt_inspection,
        load_dataset_archive_read_approval(read_path),
    )


def _fixture(
    root: Path,
    payload: bytes,
    *,
    asset_last_modified: datetime = OBSERVED_AT,
    asset_etag: str = '"etag-1"',
):
    inventory_path = root / "inventory.yaml"
    asset = DatasetPackageAsset(
        asset_id="tiny-asset",
        filename="tiny.zip",
        destination="openml/tiny.zip",
        source_kind=DatasetAssetSourceKind.OPENML_OBJECT,
        source_url="https://data.openml.org/datasets/0004/12345/tiny.zip",
        provider_object_id="12345",
        openml_dataset_id=12345,
        openml_dataset_version=1,
        source_etag=asset_etag,
        observed_content_length_bytes=len(payload),
        observed_last_modified=asset_last_modified,
        license_identifier="CC0-1.0",
        license_evidence_urls=("https://example.org/license",),
        license_status=DatasetAssetLicenseStatus.VERIFIED,
        license_note="Synthetic test fixture with verified local-only terms.",
    )
    unpacked_ceiling = max(len(payload) * 10, len(payload))
    task = DatasetPackageTaskInventory(
        task_id="tiny-task",
        paper_task_name="Tiny task",
        source_group="tiny-source",
        benchmark_dataflow_paths=("bench/tiny.py",),
        assets=(asset,),
        observed_compressed_bytes=len(payload),
        maximum_unpacked_bytes=unpacked_ceiling,
        license_disposition=DatasetAssetLicenseDisposition.VERIFIED,
    )
    inventory = DatasetPackageInventory(
        inventory_id="tiny-inventory",
        observed_at=OBSERVED_AT,
        authorization_scope="metadata-only-no-download-no-execution",
        benchmark_repository="https://example.org/benchmark",
        benchmark_commit="1" * 40,
        perception_license_commit="2" * 40,
        meta_album_license_commit="3" * 40,
        tasks=(task,),
        asset_count=1,
        observed_compressed_bytes=len(payload),
        maximum_unpacked_bytes=unpacked_ceiling,
    )
    inventory_path.write_text(
        yaml.safe_dump(inventory.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    inventory_hash = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    dummy = DatasetPackageFileBinding(path="unused", sha256="4" * 64)
    request = DatasetPackageAcquisitionRequest(
        request_id="tiny-package",
        project_id="test-project",
        track_id="test-track",
        authorization_scope="review-only-no-download-no-execution",
        purpose="Test the large-package transaction without network access.",
        claim_boundary="Synthetic unit-test evidence only.",
        candidate_manifest=dummy,
        resource_corpus=dummy,
        compute_catalog=dummy,
        inventory=DatasetPackageFileBinding(
            path="inventory.yaml",
            sha256=inventory_hash,
        ),
        selected_task_ids=("tiny-task",),
        allowed_hosts=("data.openml.org",),
        destination_root="outputs/acquisitions/tiny-package/raw",
        expected_asset_count=1,
        expected_download_bytes=len(payload),
        maximum_unpacked_bytes=unpacked_ceiling,
        minimum_free_storage_bytes=unpacked_ceiling,
    )
    request_path = root / "request.yaml"
    request_path.write_text(
        yaml.safe_dump(
            request.model_dump(mode="json", exclude={"proposal_sha256"}),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    inspection = load_dataset_package_request(request_path)
    gate = DatasetPackageGateReport(
        request_id=request.request_id,
        proposal_sha256=request.proposal_sha256,
        request_file_sha256=inspection.file_sha256,
        inventory_file_sha256=inventory_hash,
        candidate_file_sha256=dummy.sha256,
        resource_corpus_file_sha256=dummy.sha256,
        compute_catalog_file_sha256=dummy.sha256,
        selected_task_ids=request.selected_task_ids,
        source_hosts=request.allowed_hosts,
        asset_count=1,
        observed_download_bytes=len(payload),
        maximum_unpacked_bytes=unpacked_ceiling,
        minimum_free_storage_bytes=unpacked_ceiling,
        task_qualifications=(
            DatasetPackageTaskQualification(
                task_id="tiny-task",
                asset_count=1,
                observed_compressed_bytes=len(payload),
                maximum_unpacked_bytes=unpacked_ceiling,
                license_disposition=DatasetAssetLicenseDisposition.VERIFIED,
                exact_source_metadata_ready=True,
                ready_for_owner_approval=True,
                blocker_codes=(),
            ),
        ),
        metadata_review_ready=True,
        ready_for_owner_approval=True,
        integrity_blockers=(),
        approval_blockers=(),
        pending_qualifications=(
            DatasetPackageFinding(
                code="archive-safety:qualification-pending",
                message="Runs after acquisition.",
            ),
        ),
        authorization_blockers=(
            DatasetPackageFinding(
                code="owner-approval-required",
                message="Owner approval is separate.",
            ),
        ),
        pending_content_hash_count=1,
    )
    approval = approve_dataset_package_request(
        inspection,
        gate,
        confirmed_proposal_sha256=request.proposal_sha256,
        confirmed_gate_report_sha256=gate.report_sha256,
        approved_by="unit-test-owner",
        approved_at=OBSERVED_AT,
    )
    return inspection, gate, approval, asset


def _fetcher(payload: bytes, asset: DatasetPackageAsset):
    def fetch(selected: DatasetPackageAsset, sink):
        assert selected == asset
        split = max(1, len(payload) // 2)
        sink.write(payload[:split])
        sink.write(payload[split:])
        return DatasetPackageSourceObservation(
            final_url=asset.source_url,
            content_type="application/zip",
            content_length_bytes=len(payload),
            last_modified=asset.observed_last_modified,
            etag=asset.source_etag,
        )

    return fetch


def test_repository_request_needs_exact_owner_confirmation_after_license_policy() -> None:
    inspection = load_dataset_package_request(REPOSITORY_REQUEST)
    report = inspect_dataset_package_request(inspection, workspace_root=".")

    assert report.ready_for_owner_approval is True
    assert report.authorizes_download is False
    with pytest.raises(ValueError, match="proposal hash does not match"):
        approve_dataset_package_request(
            inspection,
            report,
            confirmed_proposal_sha256="0" * 64,
            confirmed_gate_report_sha256=report.report_sha256,
            approved_by="owner",
            approved_at=OBSERVED_AT,
        )


def test_cli_cannot_approve_repository_request_with_wrong_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection = load_dataset_package_request(REPOSITORY_REQUEST)
    report = inspect_dataset_package_request(inspection, workspace_root=".")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "evaluation",
                "dataset-package-approve",
                "--manifest",
                str(REPOSITORY_REQUEST),
                "--workspace-root",
                ".",
                "--confirm-proposal-sha256",
                "0" * 64,
                "--confirm-gate-report-sha256",
                report.report_sha256,
                "--approved-by",
                "owner",
                "--approved-at",
                OBSERVED_AT.isoformat(),
                "--output",
                str(tmp_path / "APPROVAL.json"),
            ]
        )
    assert exc_info.value.code == 2
    assert "proposal hash does not match" in capsys.readouterr().err
    assert not (tmp_path / "APPROVAL.json").exists()


def test_approval_streaming_receipt_and_safe_archive_are_hash_bound(tmp_path: Path) -> None:
    payload = _zip_bytes(content=b"bounded content")
    inspection, gate, approval, asset = _fixture(tmp_path, payload)
    approval_path = save_dataset_package_approval(approval, tmp_path / "APPROVAL.json")
    assert load_dataset_package_approval(approval_path).approval == approval

    receipt = materialize_dataset_package_acquisition(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_approval_sha256=approval.approval_sha256,
        allow_network_download=True,
        fetcher=_fetcher(payload, asset),
        free_space_probe=lambda _: 10**9,
        acquired_at=OBSERVED_AT,
    )

    transaction = tmp_path / "outputs/acquisitions/tiny-package"
    acquired = transaction / "raw/openml/tiny.zip"
    assert acquired.read_bytes() == payload
    assert receipt.assets[0].sha256 == hashlib.sha256(payload).hexdigest()
    loaded = load_dataset_package_receipt(transaction / "RECEIPT.json")
    assert loaded.receipt == receipt
    assert receipt.authorizes_extraction is False
    assert receipt.authorizes_execution is False

    authority = _archive_read_authority(tmp_path, inspection, approval, receipt)
    with pytest.raises(ValueError, match="explicit local-read switch"):
        inspect_dataset_package_archives(
            inspection,
            *authority,
            workspace_root=tmp_path,
            allow_local_archive_read=False,
        )
    report = inspect_dataset_package_archives(
        inspection,
        *authority,
        workspace_root=tmp_path,
        allow_local_archive_read=True,
    )
    assert report.archive_safety_qualified is True
    assert report.all_receipt_hashes_reverified is True
    assert report.archive_content_read is True
    assert report.extraction_performed is False
    report_path = save_dataset_archive_qualification_report(
        report,
        transaction / "ARCHIVE_QUALIFICATION.json",
    )
    assert load_dataset_archive_qualification_report(report_path) == report


def test_http_date_accepts_only_the_exact_second_of_subsecond_object_metadata(
    tmp_path: Path,
) -> None:
    payload = _zip_bytes(content=b"subsecond object metadata")
    precise = OBSERVED_AT.replace(microsecond=869_000)
    inspection, gate, approval, asset = _fixture(
        tmp_path,
        payload,
        asset_last_modified=precise,
    )

    def fetch(selected: DatasetPackageAsset, sink):
        assert selected == asset
        sink.write(payload)
        return DatasetPackageSourceObservation(
            final_url=asset.source_url,
            content_type="application/zip",
            content_length_bytes=len(payload),
            last_modified=precise.replace(microsecond=0),
            etag=asset.source_etag,
        )

    receipt = materialize_dataset_package_acquisition(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_approval_sha256=approval.approval_sha256,
        allow_network_download=True,
        fetcher=fetch,
        free_space_probe=lambda _: 10**9,
        acquired_at=OBSERVED_AT,
    )

    assert receipt.assets[0].observed_last_modified == precise.replace(microsecond=0)

    drift_root = tmp_path / "drift"
    drift_root.mkdir()
    drift_inspection, drift_gate, drift_approval, drift_asset = _fixture(
        drift_root,
        payload,
        asset_last_modified=precise,
    )

    def drifted_fetch(selected: DatasetPackageAsset, sink):
        assert selected == drift_asset
        sink.write(payload)
        return DatasetPackageSourceObservation(
            final_url=drift_asset.source_url,
            content_type="application/zip",
            content_length_bytes=len(payload),
            last_modified=precise.replace(microsecond=0, second=precise.second + 1),
            etag=drift_asset.source_etag,
        )

    with pytest.raises(ValueError, match="Last-Modified drifted"):
        materialize_dataset_package_acquisition(
            drift_inspection,
            drift_gate,
            drift_approval,
            workspace_root=drift_root,
            confirmed_proposal_sha256=drift_inspection.request.proposal_sha256,
            confirmed_approval_sha256=drift_approval.approval_sha256,
            allow_network_download=True,
            fetcher=drifted_fetch,
            free_space_probe=lambda _: 10**9,
            acquired_at=OBSERVED_AT,
        )


def test_openml_strong_etag_compares_the_same_opaque_value_with_optional_quotes(
    tmp_path: Path,
) -> None:
    payload = _zip_bytes(content=b"strong etag identity")
    inspection, gate, approval, asset = _fixture(
        tmp_path,
        payload,
        asset_etag="etag-from-object-metadata",
    )

    def fetch(selected: DatasetPackageAsset, sink):
        assert selected == asset
        sink.write(payload)
        return DatasetPackageSourceObservation(
            final_url=asset.source_url,
            content_type="application/zip",
            content_length_bytes=len(payload),
            last_modified=asset.observed_last_modified,
            etag='"etag-from-object-metadata"',
        )

    receipt = materialize_dataset_package_acquisition(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_approval_sha256=approval.approval_sha256,
        allow_network_download=True,
        fetcher=fetch,
        free_space_probe=lambda _: 10**9,
        acquired_at=OBSERVED_AT,
    )
    assert receipt.assets[0].observed_etag == '"etag-from-object-metadata"'

    weak_root = tmp_path / "weak"
    weak_root.mkdir()
    weak_inspection, weak_gate, weak_approval, weak_asset = _fixture(
        weak_root,
        payload,
        asset_etag="etag-from-object-metadata",
    )

    def weak_fetch(selected: DatasetPackageAsset, sink):
        assert selected == weak_asset
        sink.write(payload)
        return DatasetPackageSourceObservation(
            final_url=weak_asset.source_url,
            content_type="application/zip",
            content_length_bytes=len(payload),
            last_modified=weak_asset.observed_last_modified,
            etag='W/"etag-from-object-metadata"',
        )

    with pytest.raises(ValueError, match="ETag drifted"):
        materialize_dataset_package_acquisition(
            weak_inspection,
            weak_gate,
            weak_approval,
            workspace_root=weak_root,
            confirmed_proposal_sha256=weak_inspection.request.proposal_sha256,
            confirmed_approval_sha256=weak_approval.approval_sha256,
            allow_network_download=True,
            fetcher=weak_fetch,
            free_space_probe=lambda _: 10**9,
            acquired_at=OBSERVED_AT,
        )


def test_cli_qualifies_existing_receipt_without_extraction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _zip_bytes()
    inspection, gate, approval, asset = _fixture(tmp_path, payload)
    approval_path = save_dataset_package_approval(approval, tmp_path / "APPROVAL.json")
    receipt = materialize_dataset_package_acquisition(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_approval_sha256=approval.approval_sha256,
        allow_network_download=True,
        fetcher=_fetcher(payload, asset),
        free_space_probe=lambda _: 10**9,
        acquired_at=OBSERVED_AT,
    )
    receipt_path = tmp_path / "outputs/acquisitions/tiny-package/RECEIPT.json"
    read_approval_path = tmp_path / "ARCHIVE_READ_APPROVAL.json"
    report_path = tmp_path / "ARCHIVE_QUALIFICATION.json"

    assert (
        main(
            [
                "evaluation",
                "dataset-package-archive-read-approve",
                "--manifest",
                str(inspection.path),
                "--approval",
                str(approval_path),
                "--receipt",
                str(receipt_path),
                "--confirm-proposal-sha256",
                inspection.request.proposal_sha256,
                "--confirm-receipt-sha256",
                receipt.receipt_sha256,
                "--approved-by",
                "test-owner",
                "--approved-at",
                OBSERVED_AT.isoformat(),
                "--output",
                str(read_approval_path),
            ]
        )
        == 0
    )
    approval_output = json.loads(capsys.readouterr().out)
    assert approval_output["authorizes_archive_read"] is True
    assert approval_output["archive_read_performed"] is False

    assert (
        main(
            [
                "evaluation",
                "dataset-package-qualify",
                "--manifest",
                str(inspection.path),
                "--approval",
                str(approval_path),
                "--receipt",
                str(receipt_path),
                "--read-approval",
                str(read_approval_path),
                "--workspace-root",
                str(tmp_path),
                "--output",
                str(report_path),
                "--allow-local-archive-read",
                "--require-safe",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["archive_safety_qualified"] is True
    assert output["extraction_performed"] is False
    assert output["report_path"] == str(report_path)


def test_download_requires_switch_hash_and_storage_before_creating_transaction(
    tmp_path: Path,
) -> None:
    payload = _zip_bytes()
    inspection, gate, approval, asset = _fixture(tmp_path, payload)
    kwargs = {
        "workspace_root": tmp_path,
        "confirmed_proposal_sha256": inspection.request.proposal_sha256,
        "confirmed_approval_sha256": approval.approval_sha256,
        "fetcher": _fetcher(payload, asset),
        "free_space_probe": lambda _: 10**9,
    }

    with pytest.raises(ValueError, match="allow-network-download"):
        materialize_dataset_package_acquisition(
            inspection,
            gate,
            approval,
            allow_network_download=False,
            **kwargs,
        )
    with pytest.raises(ValueError, match="approval hash"):
        materialize_dataset_package_acquisition(
            inspection,
            gate,
            approval,
            allow_network_download=True,
            **{**kwargs, "confirmed_approval_sha256": "0" * 64},
        )
    with pytest.raises(ValueError, match="free-space floor"):
        materialize_dataset_package_acquisition(
            inspection,
            gate,
            approval,
            allow_network_download=True,
            **{**kwargs, "free_space_probe": lambda _: 0},
        )
    assert not (tmp_path / "outputs/acquisitions/tiny-package").exists()


@pytest.mark.parametrize("failure", ["partial", "metadata"])
def test_failed_transfer_removes_staging_and_publishes_nothing(
    tmp_path: Path,
    failure: str,
) -> None:
    payload = _zip_bytes()
    inspection, gate, approval, _asset = _fixture(tmp_path, payload)

    def failing_fetcher(selected, sink):
        if failure == "partial":
            sink.write(payload[:-1])
        else:
            sink.write(payload)
        return DatasetPackageSourceObservation(
            final_url=selected.source_url,
            content_type="application/zip",
            content_length_bytes=len(payload) + (1 if failure == "metadata" else 0),
            last_modified=selected.observed_last_modified,
            etag=selected.source_etag,
        )

    with pytest.raises(ValueError, match=r"exact asset bytes|Content-Length drifted"):
        materialize_dataset_package_acquisition(
            inspection,
            gate,
            approval,
            workspace_root=tmp_path,
            confirmed_proposal_sha256=inspection.request.proposal_sha256,
            confirmed_approval_sha256=approval.approval_sha256,
            allow_network_download=True,
            fetcher=failing_fetcher,
            free_space_probe=lambda _: 10**9,
        )
    parent = tmp_path / "outputs/acquisitions"
    assert not (parent / "tiny-package").exists()
    assert not list(parent.glob("*.staging"))


@pytest.mark.parametrize(
    "payload,code",
    [
        (_zip_bytes(member="../outside.txt"), "archive:path-escape"),
        (_symlink_zip_bytes(), "archive:symlink-member"),
    ],
)
def test_archive_qualification_fails_closed_on_unsafe_members(
    tmp_path: Path,
    payload: bytes,
    code: str,
) -> None:
    inspection, gate, approval, asset = _fixture(tmp_path, payload)
    receipt = materialize_dataset_package_acquisition(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_approval_sha256=approval.approval_sha256,
        allow_network_download=True,
        fetcher=_fetcher(payload, asset),
        free_space_probe=lambda _: 10**9,
        acquired_at=OBSERVED_AT,
    )

    authority = _archive_read_authority(tmp_path, inspection, approval, receipt)
    report = inspect_dataset_package_archives(
        inspection,
        *authority,
        workspace_root=tmp_path,
        allow_local_archive_read=True,
    )
    assert report.archive_safety_qualified is False
    assert code in {item.code for item in report.blockers}
    assert report.authorizes_extraction is False


def test_receipt_and_approval_loaders_detect_tampering(tmp_path: Path) -> None:
    payload = _zip_bytes()
    inspection, gate, approval, asset = _fixture(tmp_path, payload)
    approval_path = save_dataset_package_approval(approval, tmp_path / "APPROVAL.json")
    approval_payload = json.loads(approval_path.read_text(encoding="utf-8"))
    approval_payload["approved_by"] = "different-owner"
    approval_path.write_text(json.dumps(approval_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="approval hash mismatch"):
        load_dataset_package_approval(approval_path)

    receipt = materialize_dataset_package_acquisition(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_approval_sha256=approval.approval_sha256,
        allow_network_download=True,
        fetcher=_fetcher(payload, asset),
        free_space_probe=lambda _: 10**9,
        acquired_at=OBSERVED_AT,
    )
    receipt_path = tmp_path / "outputs/acquisitions/tiny-package/RECEIPT.json"
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_payload["assets"][0]["sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="receipt hash mismatch"):
        load_dataset_package_receipt(receipt_path)
    assert receipt.acquisition_complete is True
