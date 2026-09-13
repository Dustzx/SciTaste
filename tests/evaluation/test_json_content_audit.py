from __future__ import annotations

import hashlib
import json
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
    save_json_content_audit_report,
)
from scitaste.evaluation.aaar_quality_projection import materialize_aaar_quality_projections
from scitaste.taste.reference_quality import ReferenceQualityInput

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


def test_aaar_top_level_id_matches_without_trusting_nested_generic_ids(
    tmp_path: Path,
) -> None:
    matching_root = tmp_path / "matching"
    matching_root.mkdir()
    request, receipt = _acquired_json(
        matching_root,
        b'{"id":"2305.01937","paper_info":{"id":"untrusted"}}',
    )
    approval = _content_approval(matching_root, request, receipt)

    report = inspect_acquired_json_content(
        request,
        receipt,
        approval,
        workspace_root=matching_root,
        allow_local_content_read=True,
        audited_at=ACQUIRED_AT + timedelta(hours=2),
    )

    assert report.ready_for_source_admission_proposal is True
    assert report.items[0].identity_observations[0].json_pointer == "/id"
    assert len(report.items[0].identity_observations) == 1

    nested_root = tmp_path / "nested"
    nested_root.mkdir()
    nested_request, nested_receipt = _acquired_json(
        nested_root,
        b'{"paper_info":{"id":"2305.01937"}}',
    )
    nested_approval = _content_approval(nested_root, nested_request, nested_receipt)
    nested_report = inspect_acquired_json_content(
        nested_request,
        nested_receipt,
        nested_approval,
        workspace_root=nested_root,
        allow_local_content_read=True,
        audited_at=ACQUIRED_AT + timedelta(hours=2),
    )

    assert nested_report.ready_for_source_admission_proposal is False
    assert nested_report.items[0].identity_status.value == "absent"


def test_aaar_projection_hides_explicit_prestige_and_retains_decision_roles(
    tmp_path: Path,
) -> None:
    source = {
        "annotator": "reviewer-name",
        "id": "2305.01937",
        "input": ["withheld experiment prompt"],
        "output": {
            "What experiments do you suggest doing?": [
                "Compare the intervention with a controlled alternative at ICLR."
            ],
            "Why do you suggest these experiments?": [
                "The contrast separates two plausible explanations."
            ],
        },
        "paper_info": {
            "abstract": "Named Author studies the mechanism at https://example.org/paper.",
            "authors": ["Named Author"],
            "comments": "Published at ICLR",
            "title": "Identifying Source Title",
        },
        "raw_data": {
            "context_after_exp": [
                "\\section{Experiments}\nWe compare both actions and observe a failure boundary.\n",
                "\\section{Acknowledgments}\nNamed Author thanks ICLR reviewers.\n",
            ],
            "context_before_exp": ["problem context"],
            "del_percentage": 0.1,
        },
    }
    request, receipt = _acquired_json(
        tmp_path,
        json.dumps(source, ensure_ascii=False).encode(),
    )
    approval = _content_approval(tmp_path, request, receipt)
    audit = inspect_acquired_json_content(
        request,
        receipt,
        approval,
        workspace_root=tmp_path,
        allow_local_content_read=True,
        audited_at=ACQUIRED_AT + timedelta(hours=2),
    )
    audit_path = tmp_path / "audit.json"
    save_json_content_audit_report(audit, audit_path)

    output = tmp_path / "projection"
    report = materialize_aaar_quality_projections(
        request,
        receipt,
        content_audit_report_path=audit_path,
        workspace_root=tmp_path,
        output_directory=output,
        projection_id="aaar-quality-test",
        materialized_at=ACQUIRED_AT + timedelta(hours=3),
    )
    projected = ReferenceQualityInput.model_validate_json(
        (output / report.items[0].projection_locator).read_text(encoding="utf-8")
    )

    assert report.item_count == report.ready_item_count == report.role_complete_item_count == 1
    assert set(report.items[0].observed_semantic_roles) >= {
        "alternative",
        "evidence",
        "limitation",
        "scientific_action",
    }
    assert "Named Author" not in projected.source_projection
    assert "ICLR" not in projected.source_projection
    assert "https://example.org" not in projected.source_projection
    assert "Acknowledgments" not in projected.source_projection
    assert report.model_calls_performed is False


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
