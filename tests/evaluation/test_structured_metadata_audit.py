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
    approve_dataset_acquisition_request,
    approve_structured_metadata_audit,
    inspect_acquired_structured_metadata,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
    load_structured_metadata_audit_approval,
    load_structured_metadata_audit_plan,
    materialize_dataset_acquisition,
    plan_structured_metadata_audit,
    save_dataset_acquisition_request,
    save_structured_metadata_audit_approval,
    save_structured_metadata_audit_plan,
)

ACQUIRED_AT = datetime(2026, 9, 12, 12, tzinfo=UTC)


def test_structured_metadata_audit_is_bounded_and_projection_free(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.yaml"
    evidence.write_text("scope: synthetic\n", encoding="utf-8")
    yaml_revision = "1" * 40
    csv_revision = "2" * 40
    yaml_url = f"https://example.org/{yaml_revision}/task_1.yaml"
    csv_url = f"https://example.org/{csv_revision}/table.csv"
    bodies = {
        yaml_url: (b"task:\n  name: example\n  repo: https://example.org/task\nseed: 7\n"),
        csv_url: (b"task_id,paper_id,repo\n1,p1,https://example.org/repo\n2,p1,=formula\n"),
    }
    items = (
        AcquisitionItem(
            item_id="task_1",
            source_url=yaml_url,
            source_revision=yaml_revision,
            destination="task.yaml",
            maximum_bytes=1024,
            media_type="application/x-yaml",
            license_identifier="Apache-2.0",
            license_scope="Synthetic test metadata.",
            license_status="verified",
            runtime_assets_included=False,
        ),
        AcquisitionItem(
            item_id="table",
            source_url=csv_url,
            source_revision=csv_revision,
            destination="tasks.csv",
            maximum_bytes=1024,
            media_type="text/csv",
            license_identifier="CC-BY-4.0",
            license_scope="Synthetic test metadata.",
            license_status="verified",
            runtime_assets_included=False,
        ),
    )
    request = DatasetAcquisitionRequest(
        request_id="structured-metadata-test",
        project_id="test-project",
        track_id="metadata-audit",
        authorization_scope="download-only-no-ingestion",
        purpose="Exercise bounded YAML and CSV inspection.",
        claim_boundary="No scientific evidence.",
        selection_id="structured-metadata-test",
        selection_proposal_sha256="3" * 64,
        destination_root=(
            "outputs/projects/test-project/evaluations/acquisitions/structured-metadata-test/raw"
        ),
        allowed_hosts=("example.org",),
        items=items,
        maximum_total_bytes=2048,
        evidence=(
            AcquisitionEvidenceBinding(
                evidence_id="scope",
                path="evidence.yaml",
                sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            ),
        ),
    )
    approved_request = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=ACQUIRED_AT - timedelta(hours=1),
    )
    request_path = tmp_path / "approved-request.yaml"
    save_dataset_acquisition_request(approved_request, request_path)
    materialize_dataset_acquisition(
        approved_request,
        workspace_root=tmp_path,
        confirmed_request_sha256=request.request_sha256,
        allow_network_download=True,
        fetcher=lambda url, _maximum, _media: bodies[url],
        acquired_at=ACQUIRED_AT,
    )
    receipt_path = (
        tmp_path / "outputs/projects/test-project/evaluations/acquisitions/"
        "structured-metadata-test/RECEIPT.json"
    )
    request_inspection = load_dataset_acquisition_request(request_path)
    receipt_inspection = load_dataset_acquisition_receipt(receipt_path)

    plan = plan_structured_metadata_audit(request_inspection, receipt_inspection)
    assert plan.source_content_read is False
    assert plan.authorizes_local_content_read is False
    plan_path = tmp_path / "PLAN.json"
    save_structured_metadata_audit_plan(plan, plan_path)
    plan_inspection = load_structured_metadata_audit_plan(plan_path)
    approval = approve_structured_metadata_audit(
        plan_inspection,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=ACQUIRED_AT + timedelta(hours=1),
    )
    approval_path = tmp_path / "APPROVAL.json"
    save_structured_metadata_audit_approval(approval, approval_path)
    approval_inspection = load_structured_metadata_audit_approval(approval_path)

    with pytest.raises(ValueError, match="allow-local-content-read"):
        inspect_acquired_structured_metadata(
            request_inspection,
            receipt_inspection,
            plan_inspection,
            approval_inspection,
            workspace_root=tmp_path,
            allow_local_content_read=False,
            audited_at=ACQUIRED_AT + timedelta(hours=2),
        )
    report = inspect_acquired_structured_metadata(
        request_inspection,
        receipt_inspection,
        plan_inspection,
        approval_inspection,
        workspace_root=tmp_path,
        allow_local_content_read=True,
        audited_at=ACQUIRED_AT + timedelta(hours=2),
    )

    assert report.ready_for_metadata_screen_proposal is True
    assert report.exact_bytes_verified is True
    assert report.network_access_performed is False
    assert report.projection_performed is False
    assert report.ingestion_performed is False
    assert report.authorizes_execution is False
    yaml_report, csv_report = report.items
    assert yaml_report.top_level_mapping_verified is True
    assert {item.path for item in yaml_report.field_observations} >= {
        "/task/name",
        "/task/repo",
        "/seed",
    }
    assert csv_report.csv_header == ("task_id", "paper_id", "repo")
    assert csv_report.csv_data_rows == 2
    assert csv_report.formula_like_cell_count == 1
    rendered = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert "https://example.org/task" not in rendered
    assert "=formula" not in rendered
