from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scitaste.evaluation.dataset_materialization import (
    DatasetArchiveProjection,
    DatasetMaterializationRequest,
    approve_dataset_materialization,
    inspect_dataset_materialization_request,
    load_dataset_materialization_receipt,
    load_dataset_materialization_request,
    materialize_dataset_views,
)
from scitaste.evaluation.dataset_package import DatasetAssetSourceKind
from scitaste.evaluation.dataset_package_acquisition import (
    AcquiredDatasetPackageAsset,
    DatasetArchiveAssetQualification,
    DatasetArchiveQualificationReport,
    DatasetArchiveTaskQualification,
    DatasetPackageAcquisitionReceipt,
)
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    RuntimeEvidenceBinding,
)
from scitaste.executor.native_profile import inspect_native_execution_profile

NOW = datetime(2026, 9, 14, 8, tzinfo=UTC)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _zip(path: Path, members: dict[str, bytes]) -> tuple[int, str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return path.stat().st_size, _sha(path), sum(len(body) for body in members.values())


def _binding(path: Path, root: Path, semantic_field: str | None = None) -> RuntimeEvidenceBinding:
    semantic_sha256 = None
    if semantic_field is not None:
        semantic_sha256 = json.loads(path.read_bytes())[semantic_field]
    return RuntimeEvidenceBinding(
        locator=path.relative_to(root).as_posix(),
        file_sha256=_sha(path),
        semantic_field=semantic_field,
        semantic_sha256=semantic_sha256,
    )


def _fixture(root: Path) -> Path:
    raw = root / "outputs/projects/project/evaluations/acquisitions/package/raw"
    dev_zip = raw / "task/archives/train_features.zip"
    test_zip = raw / "task/archives/test.json.zip"
    dev_bytes, dev_sha, dev_expanded = _zip(
        dev_zip,
        {"sample-a.npy": b"train-a", "sample-b.npy": b"train-b"},
    )
    test_bytes, test_sha, test_expanded = _zip(test_zip, {"test.json": b'{"test":true}'})
    assets = (
        AcquiredDatasetPackageAsset(
            task_id="source-task",
            asset_id="train-features",
            source_kind=DatasetAssetSourceKind.OPENML_OBJECT,
            source_url="https://data.openml.org/datasets/0004/1/train_features.zip",
            destination="task/archives/train_features.zip",
            size_bytes=dev_bytes,
            sha256=dev_sha,
            observed_content_type="application/zip",
            observed_last_modified=NOW,
            observed_etag="train-etag",
            observed_filename="train_features.zip",
        ),
        AcquiredDatasetPackageAsset(
            task_id="source-task",
            asset_id="test-labels",
            source_kind=DatasetAssetSourceKind.OPENML_OBJECT,
            source_url="https://data.openml.org/datasets/0004/2/test.json.zip",
            destination="task/archives/test.json.zip",
            size_bytes=test_bytes,
            sha256=test_sha,
            observed_content_type="application/zip",
            observed_last_modified=NOW,
            observed_etag="test-etag",
            observed_filename="test.json.zip",
        ),
    )
    acquisition = DatasetPackageAcquisitionReceipt(
        request_id="package",
        proposal_sha256="1" * 64,
        request_file_sha256="2" * 64,
        inventory_file_sha256="3" * 64,
        gate_report_sha256="4" * 64,
        approval_sha256="5" * 64,
        approved_by="owner",
        approved_at=NOW,
        acquired_at=NOW + timedelta(minutes=1),
        approval_scope="network-preflight-and-download-only-no-extract-no-ingestion",
        destination_root="outputs/projects/project/evaluations/acquisitions/package/raw",
        assets=assets,
        asset_count=2,
        total_bytes=dev_bytes + test_bytes,
        expected_download_bytes=dev_bytes + test_bytes,
        source_hosts=("data.openml.org",),
        source_identity_rechecked=True,
        redirects_followed=False,
        overwrote_existing_files=False,
        acquisition_complete=True,
    )
    acquisition_path = raw.parent / "RECEIPT.json"
    _json(acquisition_path, acquisition.model_dump(mode="json"))

    qualification = DatasetArchiveQualificationReport(
        request_id="package",
        proposal_sha256=acquisition.proposal_sha256,
        approval_sha256=acquisition.approval_sha256,
        receipt_sha256=acquisition.receipt_sha256,
        archive_read_approval_sha256="6" * 64,
        inventory_file_sha256=acquisition.inventory_file_sha256,
        assets=(
            DatasetArchiveAssetQualification(
                task_id="source-task",
                asset_id="train-features",
                destination="task/archives/train_features.zip",
                archive_bytes=dev_bytes,
                member_count=2,
                expanded_bytes=dev_expanded,
                safe=True,
                blocker_codes=(),
            ),
            DatasetArchiveAssetQualification(
                task_id="source-task",
                asset_id="test-labels",
                destination="task/archives/test.json.zip",
                archive_bytes=test_bytes,
                member_count=1,
                expanded_bytes=test_expanded,
                safe=True,
                blocker_codes=(),
            ),
        ),
        tasks=(
            DatasetArchiveTaskQualification(
                task_id="source-task",
                asset_count=2,
                member_count=3,
                expanded_bytes=dev_expanded + test_expanded,
                maximum_unpacked_bytes=4096,
                safe=True,
            ),
        ),
        blockers=(),
        archive_safety_qualified=True,
        all_receipt_hashes_reverified=True,
    )
    qualification_path = raw.parent / "ARCHIVE_QUALIFICATION.json"
    _json(qualification_path, qualification.model_dump(mode="json"))

    license_payload = {
        "task_qualifications": [
            {
                "task_id": "source-task",
                "asset_count": 2,
                "acquisition_license_ready": True,
                "ingestion_license_ready": True,
                "pending_post_acquisition_checks": [],
            }
        ],
        "report_sha256": "7" * 64,
    }
    license_path = root / "outputs/projects/project/evaluations/license.json"
    _json(license_path, license_payload)

    inert = RuntimeEvidenceBinding(locator="evidence.txt", file_sha256="8" * 64)
    spec = BenchmarkTaskRuntimeSpec(
        spec_id="runtime-task-v1",
        project_id="project",
        benchmark_id="benchmark",
        task_id="runtime-task",
        source_checkout="checkout",
        repository_commit="9" * 40,
        task_root="task",
        visible_root="task/env",
        visible_tree_sha256="a" * 64,
        research_problem=inert,
        read_only_manifest=inert,
        environment_manifest=inert,
        objective_entrypoint=inert,
        editable_globs=("method.py",),
        dataset_directories=("data",),
        writable_output_directories=("output",),
        development_command=("python", "dev.py"),
        heldout_command=("python", "test.py"),
        heldout_materialization_paths=("data/pt/test.json",),
        primary_metric="score",
        metric_direction="higher",
        baseline_development_score=0.0,
        baseline_heldout_score=0.0,
        asset_receipt=_binding(acquisition_path, root, "receipt_sha256"),
        archive_qualification=_binding(qualification_path, root, "report_sha256"),
        license_evidence=_binding(license_path, root, "report_sha256"),
        source_status="verified",
        archive_status="verified",
        license_status="verified",
        ingestion_status="pending",
        environment_status="pending",
        scorer_status="pending",
    )
    spec_path = root / "configs/runtime.yaml"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(
        yaml.safe_dump(spec.model_dump(mode="json", exclude={"fingerprint"}), sort_keys=False),
        encoding="utf-8",
    )

    request = DatasetMaterializationRequest(
        request_id="runtime-task-materialization-v1",
        project_id="project",
        source_task_id="source-task",
        runtime_task_id="runtime-task",
        purpose="Prepare isolated task data views.",
        claim_boundary="No environment, model, GPU, or benchmark execution is authorized.",
        acquisition_receipt=_binding(acquisition_path, root, "receipt_sha256"),
        archive_qualification=_binding(qualification_path, root, "report_sha256"),
        license_evidence=_binding(license_path, root, "report_sha256"),
        task_runtime_spec=_binding(spec_path, root),
        destination_root=(
            "outputs/projects/project/evaluations/materializations/runtime-task-materialization-v1"
        ),
        assets=(
            DatasetArchiveProjection(
                asset_id="train-features",
                split_role="development",
                archive_destination="task/archives/train_features.zip",
                archive_sha256=dev_sha,
                archive_bytes=dev_bytes,
                expected_member_count=2,
                expected_expanded_bytes=dev_expanded,
                layout="flat-files",
                target_locator="pt/train_features",
                member_suffix=".npy",
            ),
            DatasetArchiveProjection(
                asset_id="test-labels",
                split_role="heldout",
                archive_destination="task/archives/test.json.zip",
                archive_sha256=test_sha,
                archive_bytes=test_bytes,
                expected_member_count=1,
                expected_expanded_bytes=test_expanded,
                layout="single-file",
                target_locator="pt/test.json",
                expected_member_name="test.json",
            ),
        ),
        expected_archive_bytes=dev_bytes + test_bytes,
        expected_expanded_bytes=dev_expanded + test_expanded,
        maximum_materialized_bytes=4096,
        minimum_free_storage_bytes=4096,
    )
    request_path = root / "configs/materialization.yaml"
    request_path.write_text(
        yaml.safe_dump(
            request.model_dump(mode="json", exclude={"proposal_sha256"}),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return request_path


def test_materialization_publishes_disjoint_native_hashable_views(tmp_path: Path) -> None:
    request_path = _fixture(tmp_path)
    inspection = load_dataset_materialization_request(request_path)
    gate = inspect_dataset_materialization_request(inspection, workspace_root=tmp_path)
    assert gate.ready_for_owner_approval
    assert gate.split_isolation_verified
    assert gate.development_asset_count == 1
    assert gate.heldout_asset_count == 1

    approval = approve_dataset_materialization(
        inspection,
        gate,
        confirmed_proposal_sha256=inspection.request.proposal_sha256,
        confirmed_gate_report_sha256=gate.report_sha256,
        approved_by="fixture-owner",
        approved_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="allow-local-extraction"):
        materialize_dataset_views(
            inspection,
            gate,
            approval,
            workspace_root=tmp_path,
            materialized_at=NOW + timedelta(minutes=3),
        )
    receipt = materialize_dataset_views(
        inspection,
        gate,
        approval,
        workspace_root=tmp_path,
        allow_local_extraction=True,
        materialized_at=NOW + timedelta(minutes=3),
    )
    destination = tmp_path / inspection.request.destination_root
    development = destination / "development/data"
    heldout = destination / "heldout/data"
    assert (development / "pt/train_features/sample-a.npy").is_file()
    assert not (development / "pt/test.json").exists()
    assert (heldout / "pt/test.json").is_file()
    assert not (heldout / "pt/train_features").exists()
    assert receipt.materialized_bytes == 27
    assert load_dataset_materialization_receipt(destination / "RECEIPT.json") == receipt

    development_view = next(item for item in receipt.views if item.split_role == "development")
    profile_path = tmp_path / "development-profile.yaml"
    profile_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "profile_id": "fixture-development",
                "datasets": [
                    {
                        "dataset_id": "runtime-task-development",
                        "source_path": str(development),
                        "expected_sha256": development_view.content_sha256,
                        "max_files": 10,
                        "max_total_bytes": 4096,
                    }
                ],
                "gpu": {"enabled": False, "devices": [], "max_gpu_hours": 0.0},
                "network_access": False,
                "writable_workspace": False,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    profile = inspect_native_execution_profile(profile_path)
    assert profile.datasets[0].content_sha256 == development_view.content_sha256


def test_materialization_gate_rejects_heldout_path_drift(tmp_path: Path) -> None:
    request_path = _fixture(tmp_path)
    payload = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    payload["assets"][1]["target_locator"] = "pt/other-test.json"
    payload["assets"][1]["expected_member_name"] = "other-test.json"
    request_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    inspection = load_dataset_materialization_request(request_path)
    gate = inspect_dataset_materialization_request(inspection, workspace_root=tmp_path)
    assert not gate.ready_for_owner_approval
    assert [item.code for item in gate.blockers] == ["task-spec:heldout-projection-mismatch"]
    with pytest.raises(ValueError, match="not owner-approval-ready"):
        approve_dataset_materialization(
            inspection,
            gate,
            confirmed_proposal_sha256=inspection.request.proposal_sha256,
            confirmed_gate_report_sha256=gate.report_sha256,
            approved_by="fixture-owner",
            approved_at=NOW + timedelta(minutes=2),
        )
