from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scitaste.evaluation import (
    AcquiredItemReceipt,
    AcquisitionApproval,
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    AcquisitionReceiptInspection,
    AcquisitionRequestInspection,
    BenchmarkMetadataProjectionApprovalInspection,
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    MetadataFieldBinding,
    StructuredFieldObservation,
    StructuredMetadataAuditItemReport,
    StructuredMetadataAuditReport,
    StructuredMetadataFormat,
    approve_benchmark_metadata_projection,
    inspect_benchmark_metadata_population_chain,
    load_benchmark_metadata_population,
    load_benchmark_metadata_projection_plan,
    load_benchmark_metadata_scope,
    load_structured_metadata_audit_report,
    plan_benchmark_metadata_projection,
    project_benchmark_metadata_population,
    save_benchmark_metadata_population,
    save_benchmark_metadata_projection_approval,
    save_benchmark_metadata_projection_plan,
    save_structured_metadata_audit_report,
)
from scitaste.evaluation import benchmark_metadata_projection as projection_module

_REVISION = "a" * 40
_AUDITED_AT = datetime(2026, 9, 13, 1, tzinfo=UTC)


def _write_scope(
    root: Path,
    *,
    scope_id: str,
    required_fields: tuple[str, ...],
    task_paths: tuple[str, ...] | None = None,
    metadata_file: str | None = None,
    reported_count: int | None = None,
) -> Path:
    payload = {
        "schema_version": "1.0",
        "scope_id": scope_id,
        "project_id": "projection-project",
        "scientific_role": (
            "objective-progress-task-universe-screen"
            if task_paths is not None
            else "experiment-chain-diagnostic-task-universe-screen"
        ),
        "benchmark_resource_id": "benchmark-resource",
        "repository_commit": _REVISION,
        "dataset_id": "benchmark-dataset",
        "dataset_revision": "b" * 40,
        "selection_state": "metadata-acquisition-proposed-subset-not-selected",
        "selection_rule": (
            "Project the complete population before applying source-overlap, license, "
            "signal, environment, reproducibility, or safety exclusions."
        ),
        "required_screen_fields": list(required_fields),
        "exclusion_codes": ["source-overlap", "license-blocked"],
        "forbidden_shortcuts": [
            "do-not-choose-tasks-from-current-model-or-gpu-inventory",
            "do-not-use-formal-outcomes-for-selection",
        ],
        "authorizes_runtime_asset_download": False,
        "authorizes_ingestion": False,
        "authorizes_execution": False,
    }
    if task_paths is not None:
        payload["task_config_paths"] = list(task_paths)
    else:
        payload["metadata_file"] = metadata_file
        payload["reported_population"] = {"task_count": reported_count}
    path = root / "docs/scope.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _control_chain(
    root: Path,
    *,
    scope_path: Path,
    scope_id: str,
    item_id: str,
    destination: str,
    media_type: str,
    raw: bytes,
) -> tuple[AcquisitionRequestInspection, AcquisitionReceiptInspection, Path]:
    raw_root = root / f"outputs/projects/projection-project/evaluations/acquisitions/{scope_id}/raw"
    raw_root.mkdir(parents=True)
    (raw_root / destination).write_bytes(raw)
    scope_sha256 = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    scope_payload = yaml.safe_load(scope_path.read_text(encoding="utf-8"))
    if scope_payload.get("task_config_paths") is not None:
        source_path = next(
            path for path in scope_payload["task_config_paths"] if Path(path).name == destination
        )
        source_revision = scope_payload["repository_commit"]
    else:
        source_path = scope_payload["metadata_file"]
        source_revision = scope_payload["dataset_revision"]
    item = AcquisitionItem(
        item_id=item_id,
        source_url=f"https://example.test/{source_revision}/{source_path}",
        source_revision=source_revision,
        destination=destination,
        maximum_bytes=1_048_576,
        media_type=media_type,
        license_identifier="CC-BY-4.0",
        license_scope="metadata only",
        license_status="verified",
    )
    unsigned = DatasetAcquisitionRequest(
        request_id=scope_id,
        project_id="projection-project",
        track_id="benchmark-metadata-screen",
        authorization_scope="download-only-no-ingestion",
        purpose="Freeze the complete metadata population before scientific screening.",
        claim_boundary="No task selection, execution, or effectiveness claim.",
        selection_id=scope_id,
        selection_proposal_sha256=scope_sha256,
        destination_root=raw_root.relative_to(root).as_posix(),
        allowed_hosts=("example.test",),
        items=(item,),
        maximum_total_bytes=1_048_576,
        evidence=(
            AcquisitionEvidenceBinding(
                evidence_id="metadata-scope",
                path=scope_path.relative_to(root).as_posix(),
                sha256=scope_sha256,
            ),
        ),
    )
    request = DatasetAcquisitionRequest.model_validate(
        {
            **unsigned.model_dump(mode="json", exclude={"request_sha256", "approval"}),
            "approval": AcquisitionApproval(
                approved=True,
                request_sha256=unsigned.request_sha256,
                approved_by="test-owner",
                approved_at=datetime(2026, 9, 13, 0, tzinfo=UTC),
                scope="download-only-no-ingestion",
            ).model_dump(mode="json"),
        }
    )
    request_path = root / "configs/approved-request.yaml"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(
        yaml.safe_dump(
            request.model_dump(mode="json", exclude={"request_sha256"}),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    receipt_item = AcquiredItemReceipt(
        item_id=item_id,
        source_url=item.source_url,
        source_revision=source_revision,
        destination=destination,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        expected_sha256=None,
    )
    receipt = DatasetAcquisitionReceipt.create(
        request_id=scope_id,
        request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 13, 0, tzinfo=UTC),
        acquired_at=datetime(2026, 9, 13, 0, 30, tzinfo=UTC),
        approval_scope="download-only-no-ingestion",
        destination_root=raw_root.relative_to(root).as_posix(),
        items=(receipt_item,),
        item_count=1,
        total_bytes=len(raw),
        maximum_total_bytes=1_048_576,
        source_hosts=("example.test",),
    )
    receipt_path = raw_root.parent / "RECEIPT.json"
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return (
        AcquisitionRequestInspection(
            path=request_path,
            file_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
            request=request,
        ),
        AcquisitionReceiptInspection(
            path=receipt_path,
            file_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            receipt=receipt,
        ),
        raw_root,
    )


def _audit_report(
    root: Path,
    *,
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    item: StructuredMetadataAuditItemReport,
) -> Path:
    report = StructuredMetadataAuditReport(
        plan_id=f"{request.request.request_id}-audit-v1",
        plan_sha256="1" * 64,
        approval_id=f"{request.request.request_id}-audit-v1-approval",
        approval_sha256="2" * 64,
        project_id=request.request.project_id,
        request_id=request.request.request_id,
        request_sha256=request.request.request_sha256,
        receipt_sha256=receipt.receipt.receipt_sha256,
        auditor_id="scitaste-structured-metadata-audit-v1",
        auditor_implementation_sha256="3" * 64,
        audited_at=_AUDITED_AT,
        item_count=1,
        observed_total_bytes=item.observed_size_bytes,
        exact_inventory_verified=True,
        exact_bytes_verified=True,
        all_utf8_verified=True,
        all_syntax_verified=True,
        all_structural_bounds_verified=True,
        ready_for_metadata_screen_proposal=True,
        items=(item,),
        blocker_codes=(),
    )
    path = root / f"outputs/projects/projection-project/audits/{request.request.request_id}.json"
    save_structured_metadata_audit_report(report, path)
    return path


def _approve_and_project(
    root: Path,
    *,
    request: AcquisitionRequestInspection,
    receipt: AcquisitionReceiptInspection,
    audit_path: Path,
    scope_path: Path,
    bindings: tuple[MetadataFieldBinding, ...],
):
    audit = load_structured_metadata_audit_report(audit_path)
    scope = load_benchmark_metadata_scope(scope_path)
    plan = plan_benchmark_metadata_projection(
        request,
        receipt,
        audit,
        scope,
        workspace_root=root,
        field_bindings=bindings,
        projection_output_root=(
            f"outputs/projects/projection-project/projections/{request.request.request_id}"
        ),
    )
    plan_path = root / f"outputs/projects/projection-project/plans/{plan.plan_id}.json"
    save_benchmark_metadata_projection_plan(plan, plan_path)
    plan_inspection = load_benchmark_metadata_projection_plan(plan_path)
    approval = approve_benchmark_metadata_projection(
        plan_inspection,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 13, 2, tzinfo=UTC),
    )
    approval_path = plan_path.with_name("APPROVAL.json")
    save_benchmark_metadata_projection_approval(approval, approval_path)
    approval_inspection = BenchmarkMetadataProjectionApprovalInspection(
        path=approval_path,
        file_sha256=hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        approval=approval,
    )
    return project_benchmark_metadata_population(
        request,
        receipt,
        audit,
        scope,
        plan_inspection,
        approval_inspection,
        workspace_root=root,
        allow_local_content_read=True,
        projected_at=datetime(2026, 9, 13, 3, tzinfo=UTC),
    )


def test_yaml_projection_preserves_complete_population_without_selecting_tasks(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    scope_id = "yaml-task-universe-v1"
    scope_path = _write_scope(
        root,
        scope_id=scope_id,
        required_fields=("benchmark-category", "source-paper-group"),
        task_paths=("tasks/task_1.yaml",),
    )
    raw = b"category: vision\nsource_group: paper-a\n"
    request, receipt, _ = _control_chain(
        root,
        scope_path=scope_path,
        scope_id=scope_id,
        item_id="task_1",
        destination="task_1.yaml",
        media_type="application/x-yaml",
        raw=raw,
    )
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    audit_path = _audit_report(
        root,
        request=request,
        receipt=receipt,
        item=StructuredMetadataAuditItemReport(
            item_id="task_1",
            destination="task_1.yaml",
            media_type=StructuredMetadataFormat.YAML,
            receipt_size_bytes=len(raw),
            receipt_sha256=observed_sha256,
            observed_size_bytes=len(raw),
            observed_sha256=observed_sha256,
            exact_bytes_verified=True,
            utf8_verified=True,
            syntax_verified=True,
            structural_bounds_verified=True,
            top_level_mapping_verified=True,
            field_observations=(
                StructuredFieldObservation(
                    path="/category",
                    observed_types=("string",),
                    occurrences=1,
                    maximum_string_utf8_bytes=6,
                    external_locator_count=0,
                ),
                StructuredFieldObservation(
                    path="/source_group",
                    observed_types=("string",),
                    occurrences=1,
                    maximum_string_utf8_bytes=7,
                    external_locator_count=0,
                ),
            ),
            total_nodes=3,
            maximum_observed_depth=1,
            csv_data_rows=0,
            csv_maximum_columns=0,
            maximum_observed_string_utf8_bytes=7,
            external_locator_count=0,
            formula_like_cell_count=0,
            blocker_codes=(),
        ),
    )
    population = _approve_and_project(
        root,
        request=request,
        receipt=receipt,
        audit_path=audit_path,
        scope_path=scope_path,
        bindings=(
            MetadataFieldBinding(semantic_field="benchmark-category", source_fields=("/category",)),
            MetadataFieldBinding(
                semantic_field="source-paper-group", source_fields=("/source_group",)
            ),
        ),
    )
    output = root / f"outputs/projects/projection-project/projections/{scope_id}/POPULATION.json"
    save_benchmark_metadata_population(population, output)
    loaded = load_benchmark_metadata_population(output).population
    chain = inspect_benchmark_metadata_population_chain(output, workspace_root=root)

    replacement_item = request.request.items[0].model_copy(
        update={
            "source_url": (
                f"https://example.test/{_REVISION}/research_gym/configs/tasks/other.yaml"
            )
        }
    )
    replacement_request = request.request.model_copy(update={"items": (replacement_item,)})
    with pytest.raises(ValueError, match="outside the frozen task population"):
        projection_module._verify_scope_source_population(
            replacement_request,
            load_benchmark_metadata_scope(scope_path).scope,
        )

    assert loaded.record_count == 1
    assert loaded.records[0].record_id == "task_1"
    assert [field.values for field in loaded.records[0].fields] == [("vision",), ("paper-a",)]
    assert loaded.complete_population_projected is True
    assert loaded.selection_performed is False
    assert loaded.formal_outcomes_consulted is False
    assert loaded.model_inventory_consulted is False
    assert loaded.compute_inventory_consulted is False
    assert loaded.authorizes_task_selection is False
    assert loaded.authorizes_execution is False
    assert chain.projection_implementation_current is True


def test_csv_projection_keeps_every_row_and_treats_values_as_inert_data(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    scope_id = "csv-task-universe-v1"
    scope_path = _write_scope(
        root,
        scope_id=scope_id,
        required_fields=("experiment-chain-stage", "source-paper-group"),
        metadata_file="metadata.csv",
        reported_count=2,
    )
    raw = b"paper,stage\npaper-a,design\npaper-b,=not-a-formula\n"
    request, receipt, _ = _control_chain(
        root,
        scope_path=scope_path,
        scope_id=scope_id,
        item_id="metadata",
        destination="metadata.csv",
        media_type="text/csv",
        raw=raw,
    )
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    audit_path = _audit_report(
        root,
        request=request,
        receipt=receipt,
        item=StructuredMetadataAuditItemReport(
            item_id="metadata",
            destination="metadata.csv",
            media_type=StructuredMetadataFormat.CSV,
            receipt_size_bytes=len(raw),
            receipt_sha256=observed_sha256,
            observed_size_bytes=len(raw),
            observed_sha256=observed_sha256,
            exact_bytes_verified=True,
            utf8_verified=True,
            syntax_verified=True,
            structural_bounds_verified=True,
            csv_header=("paper", "stage"),
            csv_data_rows=2,
            csv_maximum_columns=2,
            total_nodes=6,
            maximum_observed_depth=1,
            maximum_observed_string_utf8_bytes=14,
            external_locator_count=0,
            formula_like_cell_count=1,
            blocker_codes=(),
        ),
    )
    population = _approve_and_project(
        root,
        request=request,
        receipt=receipt,
        audit_path=audit_path,
        scope_path=scope_path,
        bindings=(
            MetadataFieldBinding(semantic_field="experiment-chain-stage", source_fields=("stage",)),
            MetadataFieldBinding(semantic_field="source-paper-group", source_fields=("paper",)),
        ),
    )

    assert population.record_count == 2
    assert [record.row_ordinal for record in population.records] == [1, 2]
    assert population.records[1].fields[0].values == ("=not-a-formula",)
    assert population.network_access_performed is False
    assert population.linked_assets_resolved is False


def test_projection_requires_explicit_absence_and_retains_the_record(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    scope_id = "missing-field-universe-v1"
    scope_path = _write_scope(
        root,
        scope_id=scope_id,
        required_fields=("source-paper-group",),
        task_paths=("tasks/task_1.yaml",),
    )
    raw = b"category: vision\n"
    request, receipt, _ = _control_chain(
        root,
        scope_path=scope_path,
        scope_id=scope_id,
        item_id="task_1",
        destination="task_1.yaml",
        media_type="application/x-yaml",
        raw=raw,
    )
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    audit_path = _audit_report(
        root,
        request=request,
        receipt=receipt,
        item=StructuredMetadataAuditItemReport(
            item_id="task_1",
            destination="task_1.yaml",
            media_type=StructuredMetadataFormat.YAML,
            receipt_size_bytes=len(raw),
            receipt_sha256=observed_sha256,
            observed_size_bytes=len(raw),
            observed_sha256=observed_sha256,
            exact_bytes_verified=True,
            utf8_verified=True,
            syntax_verified=True,
            structural_bounds_verified=True,
            top_level_mapping_verified=True,
            field_observations=(
                StructuredFieldObservation(
                    path="/category",
                    observed_types=("string",),
                    occurrences=1,
                    maximum_string_utf8_bytes=6,
                    external_locator_count=0,
                ),
            ),
            total_nodes=2,
            maximum_observed_depth=1,
            csv_data_rows=0,
            csv_maximum_columns=0,
            maximum_observed_string_utf8_bytes=6,
            external_locator_count=0,
            formula_like_cell_count=0,
            blocker_codes=(),
        ),
    )

    with pytest.raises(ValueError, match="absent from the YAML population"):
        plan_benchmark_metadata_projection(
            request,
            receipt,
            load_structured_metadata_audit_report(audit_path),
            load_benchmark_metadata_scope(scope_path),
            workspace_root=root,
            field_bindings=(
                MetadataFieldBinding(
                    semantic_field="source-paper-group", source_fields=("/source_group",)
                ),
            ),
            projection_output_root="outputs/projects/projection-project/projections/missing",
        )

    population = _approve_and_project(
        root,
        request=request,
        receipt=receipt,
        audit_path=audit_path,
        scope_path=scope_path,
        bindings=(
            MetadataFieldBinding(
                semantic_field="source-paper-group",
                availability="absent-from-audited-source",
            ),
        ),
    )

    assert population.record_count == 1
    assert population.missing_source_field_observation_count == 1
    projected = population.records[0].fields[0]
    assert projected.availability == "absent-from-audited-source"
    assert projected.source_field_present is False
    assert projected.values == ()


def test_approval_rejects_projection_implementation_drift(tmp_path: Path) -> None:
    plan = projection_module.BenchmarkMetadataProjectionPlan(
        plan_id="drift-plan",
        project_id="projection-project",
        scope_id="drift-scope",
        scope_locator="docs/scope.yaml",
        scope_file_sha256="1" * 64,
        request_id="drift-request",
        request_locator="configs/request.yaml",
        request_file_sha256="2" * 64,
        request_sha256="9" * 64,
        receipt_locator="outputs/receipt.json",
        receipt_file_sha256="3" * 64,
        receipt_sha256="4" * 64,
        audit_report_locator="outputs/audit.json",
        audit_report_file_sha256="5" * 64,
        audit_report_sha256="6" * 64,
        audit_plan_sha256="7" * 64,
        projection_implementation_sha256="8" * 64,
        media_type=StructuredMetadataFormat.CSV,
        record_unit="one-record-per-csv-row",
        expected_source_bytes=42,
        expected_record_count=2,
        required_screen_fields=("source-paper-group",),
        field_bindings=(
            MetadataFieldBinding(semantic_field="source-paper-group", source_fields=("paper",)),
        ),
        projection_output_root="outputs/projection",
        maximum_projected_value_bytes=1024,
        maximum_projection_bytes=4096,
    )
    path = tmp_path / "PLAN.json"
    save_benchmark_metadata_projection_plan(plan, path)

    with pytest.raises(ValueError, match="implementation has changed"):
        approve_benchmark_metadata_projection(
            load_benchmark_metadata_projection_plan(path),
            confirmed_plan_sha256=plan.plan_sha256,
            approved_by="test-owner",
            approved_at=datetime(2026, 9, 13, 0, tzinfo=UTC),
        )
