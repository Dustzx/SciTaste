from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.evaluation import (
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    DatasetAcquisitionRequest,
    ReadinessStatus,
    approve_dataset_acquisition_request,
    approve_json_content_audit,
    inspect_acquired_json_content,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
    load_json_content_audit_approval,
    materialize_dataset_acquisition,
    save_dataset_acquisition_request,
    save_json_content_audit_approval,
)

REVISION = "a" * 40
ACQUIRED_AT = datetime(2026, 9, 12, tzinfo=UTC)


def test_acquired_json_is_audited_without_becoming_a_projection(tmp_path: Path) -> None:
    request, receipt = _acquired_json(
        tmp_path,
        b'{"arxiv_id":"2305.01937","sections":[{"text":"bounded"}],'
        b'"source":"https://example.org/paper"}',
    )
    approval = _content_approval(tmp_path, request, receipt)

    report = inspect_acquired_json_content(
        request,
        receipt,
        approval,
        workspace_root=tmp_path,
        allow_local_content_read=True,
        audited_at=ACQUIRED_AT + timedelta(hours=2),
    )

    assert report.ready_for_source_admission_proposal is True
    assert report.all_embedded_identities_verified is True
    assert report.items[0].external_locator_count == 1
    assert {item.json_pointer for item in report.items[0].field_observations} >= {
        "/arxiv_id",
        "/sections/*/text",
    }
    assert report.projection_performed is False
    assert report.ingestion_performed is False
    assert report.network_access_performed is False


def test_local_content_requires_separate_hash_bound_approval(tmp_path: Path) -> None:
    request, receipt = _acquired_json(tmp_path, b'{"arxiv_id":"2305.01937"}')
    approval = _content_approval(tmp_path, request, receipt)

    with pytest.raises(ValueError, match="local-content-read switch"):
        inspect_acquired_json_content(
            request,
            receipt,
            approval,
            workspace_root=tmp_path,
            allow_local_content_read=False,
            audited_at=ACQUIRED_AT + timedelta(hours=2),
        )

    changed = approval.approval.model_copy(update={"receipt_sha256": "f" * 64})
    changed_path = tmp_path / "changed-approval.json"
    save_json_content_audit_approval(changed, changed_path)
    with pytest.raises(ValueError, match="bindings have drifted"):
        inspect_acquired_json_content(
            request,
            receipt,
            load_json_content_audit_approval(changed_path),
            workspace_root=tmp_path,
            allow_local_content_read=True,
            audited_at=ACQUIRED_AT + timedelta(hours=2),
        )


def test_duplicate_keys_and_identity_mismatch_fail_closed(tmp_path: Path) -> None:
    request, receipt = _acquired_json(
        tmp_path,
        b'{"arxiv_id":"9999.99999","sections":[],"sections":[]}',
    )
    approval = _content_approval(tmp_path, request, receipt)

    report = inspect_acquired_json_content(
        request,
        receipt,
        approval,
        workspace_root=tmp_path,
        allow_local_content_read=True,
        audited_at=ACQUIRED_AT + timedelta(hours=2),
    )

    assert report.ready_for_source_admission_proposal is False
    assert report.all_json_verified is False
    assert "2305.01937:duplicate-json-key" in report.blocker_codes


def _acquired_json(
    tmp_path: Path,
    content: bytes,
):
    evidence = tmp_path / "evidence.yaml"
    evidence.write_text("scope: synthetic-test\n", encoding="utf-8")
    item = AcquisitionItem(
        item_id="2305.01937",
        source_url=(
            f"https://example.org/datasets/{REVISION}/Experiment_Design/2305.01937/data_text.json"
        ),
        source_revision=REVISION,
        destination="2305.01937/data_text.json",
        maximum_bytes=4_096,
        media_type="application/json",
        license_identifier="CC-BY-4.0",
        license_scope="Synthetic unit-test record only.",
        license_status=ReadinessStatus.VERIFIED,
    )
    request = DatasetAcquisitionRequest(
        request_id="aaar-json-test",
        project_id="test-project",
        track_id="content-audit",
        authorization_scope="download-only-no-ingestion",
        purpose="Build one local content-audit fixture.",
        claim_boundary="No scientific evidence.",
        selection_id="aaar-json-test",
        selection_proposal_sha256="1" * 64,
        destination_root=(
            "outputs/projects/test-project/evaluations/acquisitions/aaar-json-test/raw"
        ),
        allowed_hosts=("example.org",),
        items=(item,),
        maximum_total_bytes=item.maximum_bytes,
        evidence=(
            AcquisitionEvidenceBinding(
                evidence_id="scope",
                path="evidence.yaml",
                sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            ),
        ),
    )
    approved = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=ACQUIRED_AT - timedelta(hours=1),
    )
    request_path = tmp_path / "approved-request.yaml"
    save_dataset_acquisition_request(approved, request_path)
    materialize_dataset_acquisition(
        approved,
        workspace_root=tmp_path,
        confirmed_request_sha256=approved.request_sha256,
        allow_network_download=True,
        fetcher=lambda _url, _maximum, _media: content,
        acquired_at=ACQUIRED_AT,
    )
    receipt_path = (
        tmp_path
        / "outputs/projects/test-project/evaluations/acquisitions/aaar-json-test/RECEIPT.json"
    )
    return (
        load_dataset_acquisition_request(request_path),
        load_dataset_acquisition_receipt(receipt_path),
    )


def _content_approval(tmp_path: Path, request, receipt):
    approval = approve_json_content_audit(
        request,
        receipt,
        confirmed_request_sha256=request.request.request_sha256,
        confirmed_receipt_sha256=receipt.receipt.receipt_sha256,
        approved_by="test-owner",
        approved_at=ACQUIRED_AT + timedelta(hours=1),
    )
    path = tmp_path / "content-approval.json"
    save_json_content_audit_approval(approval, path)
    return load_json_content_audit_approval(path)
