from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scitaste.evaluation import (
    AcquiredItemReceipt,
    DatasetAcquisitionReceipt,
    StructuredMetadataAuditPlan,
    StructuredMetadataFormat,
    build_structured_metadata_audit_plan_bundle,
    load_structured_metadata_audit_plan_bundle,
    save_structured_metadata_audit_plan,
    save_structured_metadata_audit_plan_bundle,
)
from scitaste.evaluation import structured_metadata_audit as audit_module


def _plan(
    *,
    request_id: str,
    media_type: StructuredMetadataFormat,
    byte_ceiling: int,
    receipt: DatasetAcquisitionReceipt,
    receipt_path: Path,
) -> StructuredMetadataAuditPlan:
    implementation_sha256 = hashlib.sha256(Path(audit_module.__file__).read_bytes()).hexdigest()
    return StructuredMetadataAuditPlan(
        plan_id=f"{request_id}-metadata-content-audit-v1",
        project_id="bundle-project",
        request_id=request_id,
        request_file_sha256="1" * 64,
        request_sha256="2" * 64,
        receipt_file_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        receipt_sha256=receipt.receipt_sha256,
        acquired_at=datetime(2026, 9, 13, 1, tzinfo=UTC),
        auditor_id="scitaste-structured-metadata-audit-v1",
        auditor_implementation_sha256=implementation_sha256,
        expected_item_ids=tuple(item.item_id for item in receipt.items),
        formats=(media_type,),
        maximum_source_bytes_per_item=byte_ceiling,
        maximum_total_source_bytes=byte_ceiling,
        maximum_structure_depth=32,
        maximum_nodes_per_item=500_000,
        maximum_distinct_paths=10_000,
        maximum_string_utf8_bytes=1_048_576,
        maximum_csv_rows=1_000_000,
        maximum_csv_columns=4_096,
    )


def _receipt(*, request_id: str, item_count: int) -> DatasetAcquisitionReceipt:
    revision = "a" * 40
    items = tuple(
        AcquiredItemReceipt(
            item_id=f"item-{index:02d}",
            source_url=f"https://example.test/{revision}/item-{index:02d}",
            source_revision=revision,
            destination=f"item-{index:02d}.txt",
            size_bytes=1,
            sha256=f"{index + 1:064x}",
            expected_sha256=None,
        )
        for index in range(item_count)
    )
    return DatasetAcquisitionReceipt.create(
        request_id=request_id,
        request_sha256="2" * 64,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 13, 0, tzinfo=UTC),
        acquired_at=datetime(2026, 9, 13, 1, tzinfo=UTC),
        approval_scope="download-only-no-ingestion",
        destination_root=f"outputs/projects/bundle-project/evaluations/acquisitions/{request_id}/raw",
        items=items,
        item_count=item_count,
        total_bytes=item_count,
        maximum_total_bytes=8 * 1_048_576,
        source_hosts=("example.test",),
    )


def test_plan_bundle_closes_project_gate_without_reading_source_content(tmp_path: Path) -> None:
    project_root = tmp_path / "outputs/projects/bundle-project"
    plan_root = project_root / "runs/audit-plans/metadata_audit_planning"
    yaml_path = plan_root / "innovatorbench/PLAN.json"
    csv_path = plan_root / "expbench/PLAN.json"
    yaml_receipt = _receipt(request_id="innovatorbench-task-metadata-v1", item_count=20)
    csv_receipt = _receipt(request_id="expbench-task-metadata-v1", item_count=1)
    yaml_receipt_path = (
        project_root / "evaluations/acquisitions/innovatorbench-task-metadata-v1/RECEIPT.json"
    )
    csv_receipt_path = (
        project_root / "evaluations/acquisitions/expbench-task-metadata-v1/RECEIPT.json"
    )
    yaml_receipt_path.parent.mkdir(parents=True)
    csv_receipt_path.parent.mkdir(parents=True)
    yaml_receipt_path.write_text(yaml_receipt.model_dump_json(indent=2) + "\n")
    csv_receipt_path.write_text(csv_receipt.model_dump_json(indent=2) + "\n")
    save_structured_metadata_audit_plan(
        _plan(
            request_id="innovatorbench-task-metadata-v1",
            media_type=StructuredMetadataFormat.YAML,
            byte_ceiling=5 * 1_048_576,
            receipt=yaml_receipt,
            receipt_path=yaml_receipt_path,
        ),
        yaml_path,
    )
    save_structured_metadata_audit_plan(
        _plan(
            request_id="expbench-task-metadata-v1",
            media_type=StructuredMetadataFormat.CSV,
            byte_ceiling=3 * 1_048_576,
            receipt=csv_receipt,
            receipt_path=csv_receipt_path,
        ),
        csv_path,
    )

    bundle = build_structured_metadata_audit_plan_bundle(
        project_id="bundle-project",
        run_id="audit-plans",
        project_root=project_root,
        plan_paths=(yaml_path, csv_path),
        receipt_paths=(yaml_receipt_path, csv_receipt_path),
    )
    bundle_path = plan_root / "BUNDLE.json"
    save_structured_metadata_audit_plan_bundle(bundle, bundle_path)
    inspection = load_structured_metadata_audit_plan_bundle(
        bundle_path,
        project_root=project_root,
    )

    assert inspection.bundle.plan_count == 2
    assert inspection.bundle.expected_item_count == 21
    assert inspection.bundle.maximum_total_source_bytes == 8 * 1_048_576
    assert inspection.bundle.status == "awaiting_content_read_approval"
    assert inspection.bundle.next_gate == "approve_exact_local_structured_metadata_read"
    assert inspection.bundle.source_content_read is False
    assert inspection.bundle.owner_approval_recorded is False
    assert inspection.bundle.network_access_performed is False
    assert inspection.bundle.authorizes_local_content_read is False
    assert inspection.bundle.authorizes_projection is False
    assert inspection.bundle.authorizes_execution is False
    assert all(item.auditor_implementation_current for item in inspection.bundle.plans)


def test_plan_bundle_rejects_a_plan_outside_the_project(tmp_path: Path) -> None:
    project_root = tmp_path / "outputs/projects/bundle-project"
    project_root.mkdir(parents=True)
    receipt = _receipt(request_id="outside-task-metadata-v1", item_count=1)
    receipt_path = project_root / "evaluations/acquisitions/outside-task-metadata-v1/RECEIPT.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n")
    outside = tmp_path / "outside-plan.json"
    save_structured_metadata_audit_plan(
        _plan(
            request_id="outside-task-metadata-v1",
            media_type=StructuredMetadataFormat.YAML,
            byte_ceiling=1_048_576,
            receipt=receipt,
            receipt_path=receipt_path,
        ),
        outside,
    )

    with pytest.raises(ValueError, match="inside the project root"):
        build_structured_metadata_audit_plan_bundle(
            project_id="bundle-project",
            run_id="audit-plans",
            project_root=project_root,
            plan_paths=(outside,),
            receipt_paths=(receipt_path,),
        )
