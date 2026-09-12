from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    AcquiredCohortFinding,
    AcquiredItemReceipt,
    AcquiredTaskCohortReport,
    AcquiredTaskQualification,
    AcquiredTaskUse,
    DatasetAcquisitionReceipt,
    ReadinessStatus,
    StructuredMetadataAuditPlan,
    StructuredMetadataFormat,
    TaskSignalKind,
    build_structured_metadata_audit_plan_bundle,
    inspect_dataset_acquisition_request,
    inspect_dataset_package_request,
    inspect_executable_candidate,
    load_dataset_acquisition_request,
    load_dataset_package_request,
    load_executable_candidate_manifest,
    save_dataset_package_gate_report,
    save_executable_candidate_report,
    save_structured_metadata_audit_plan,
    save_structured_metadata_audit_plan_bundle,
)
from scitaste.evaluation import structured_metadata_audit as audit_module
from scitaste.generative_ui import (
    IntentGoal,
    ProjectProgressQuery,
    ProjectSurfaceChangedError,
    SurfaceSpec,
    TrustedComponent,
    WorkspaceIntentResolver,
    WorkspaceSurfaceFactory,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _create_runtime(tmp_path: Path, *, status: str = "active") -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="progress-project",
            title="Progress project",
            research_direction="Show only evidence-grounded project progress.",
            status=status,
        )
    )
    return runtime, snapshot


def _begin_run(
    runtime: ProjectRuntime,
    snapshot,
    *,
    run_id: str,
    status: str,
    **extra,
):
    return runtime.begin_run(
        "progress-project",
        ProjectRun(
            run_id=run_id,
            provider="scripted",
            model="deterministic-model",
            condition="progress-fixture",
            seed=0,
            status=status,
            evidence_scope="engineering-only",
            **extra,
        ),
        expected_revision=snapshot.revision,
    )


def _progress(runtime: ProjectRuntime):
    document = WorkspaceSurfaceFactory(runtime).build(
        ProjectProgressQuery(project_id="progress-project")
    )
    component = next(
        item
        for item in document.renderer.components
        if item.renderer == TrustedComponent.PROJECT_PROGRESS_BOARD
    )
    return document, component.data


def _brief_only_cohort_report() -> AcquiredTaskCohortReport:
    task = AcquiredTaskQualification(
        task_id="brief-one",
        source_group="workshop-brief",
        source_url="https://example.test/brief-one.md",
        source_revision="1" * 40,
        relative_path="brief-one.md",
        byte_size=42,
        sha256="1" * 64,
        license_identifier="MIT",
        license_status=ReadinessStatus.VERIFIED,
        signal_kind=TaskSignalKind.RESEARCH_PACKAGE_REVIEW,
        objective_task_score_available=False,
        runtime_assets_included=False,
        exact_bytes_verified=True,
        eligible_uses=(
            AcquiredTaskUse.STAGEWISE_IDEA_PROPOSAL,
            AcquiredTaskUse.BRIEF_ONLY_PACKAGE_PREPILOT,
        ),
        blocked_uses=(
            AcquiredTaskUse.EMPIRICAL_IDEA_TO_PAPER,
            AcquiredTaskUse.OBJECTIVE_PROGRESS,
        ),
    )
    return AcquiredTaskCohortReport(
        selection_id="brief-only-selection",
        selection_file_sha256="2" * 64,
        selection_proposal_sha256="3" * 64,
        request_id="brief-only-request",
        request_file_sha256="4" * 64,
        request_sha256="5" * 64,
        receipt_file_sha256="6" * 64,
        receipt_sha256="7" * 64,
        task_count=1,
        observed_total_bytes=42,
        exact_task_set_verified=True,
        exact_bytes_verified=True,
        all_starting_input_licenses_verified=True,
        package_review_signal_declared=True,
        runtime_assets_present=False,
        objective_scores_present=False,
        held_out_audit_status=ReadinessStatus.PENDING,
        ready_for_stagewise_pilot=True,
        ready_for_brief_only_package_prepilot=True,
        ready_for_formal_empirical_task_binding=False,
        ready_for_objective_progress_binding=False,
        scientific_disposition="brief-only-pilot-candidate",
        tasks=(task,),
        integrity_blockers=(),
        formal_task_blockers=(
            AcquiredCohortFinding(
                code="runtime-assets-absent",
                message="the acquired brief has no frozen runtime assets",
            ),
        ),
        objective_progress_blockers=(
            AcquiredCohortFinding(
                code="objective-score-absent",
                message="the acquired brief has no objective score",
            ),
        ),
    )


def test_empty_progress_is_explicit_and_never_invents_a_percentage(tmp_path: Path) -> None:
    runtime, _ = _create_runtime(tmp_path)

    document, data = _progress(runtime)

    assert document.query.view == "project-progress"
    assert document.renderer.catalog_version == "scitaste-trusted-components-v2"
    assert data["project_state"] == "current_work"
    assert data["counts"] == {
        "runs_registered": 0,
        "runs_completed": 0,
        "runs_failed": 0,
        "runs_blocked": 0,
        "runs_active": 0,
        "runs_candidates": 0,
        "runs_unavailable": 0,
        "runs_unknown": 0,
        "completed_stages": 0,
        "papers_registered": 0,
        "evaluations_registered": 0,
        "evaluation_results_registered": 0,
        "acquisition_requests": 0,
        "acquisition_receipts": 0,
        "metadata_audit_plans": 0,
    }
    assert data["stage_state"] == "empty"
    assert data["milestone_state"] == "empty"
    assert data["recent_activity"] == []
    assert [item["kind"] for item in data["next_step_candidates"]] == ["review_progress"]
    assert "percent" not in json.dumps(data, sort_keys=True).lower()


def test_progress_status_mapping_is_exact_and_keeps_current_selection_separate(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path, status="active-pilot-blocked")
    statuses = {
        "completed-run": "complete",
        "failed-run": "failed",
        "blocked-run": "blocked",
        "active-run": "active",
        "candidate-run": "proposed",
        "unavailable-run": "unavailable",
        "referenced-run": "referenced",
        "substring-run": "completed-ish",
    }
    for run_id, status in statuses.items():
        snapshot = _begin_run(
            runtime,
            snapshot,
            run_id=run_id,
            status=status,
            blockers=["Awaiting independently verified result"] if status == "blocked" else None,
        )
    snapshot = runtime.select_run(
        "progress-project",
        "completed-run",
        expected_revision=snapshot.revision,
    )

    _, data = _progress(runtime)

    assert data["project_state"] == "blocked"
    assert data["current_run_id"] == "completed-run"
    assert data["current_run_state"] == "observed_completed"
    assert data["counts"] == {
        "runs_registered": 8,
        "runs_completed": 1,
        "runs_failed": 1,
        "runs_blocked": 1,
        "runs_active": 1,
        "runs_candidates": 1,
        "runs_unavailable": 1,
        "runs_unknown": 2,
        "completed_stages": 0,
        "papers_registered": 0,
        "evaluations_registered": 0,
        "evaluation_results_registered": 0,
        "acquisition_requests": 0,
        "acquisition_receipts": 0,
        "metadata_audit_plans": 0,
    }
    activity = {item["run_id"]: item for item in data["recent_activity"]}
    assert activity["referenced-run"]["observed_state"] == "unknown"
    assert activity["substring-run"]["observed_state"] == "unknown"
    assert activity["completed-run"]["selected"] is True
    blocked = next(item for item in data["attention"] if item["run_id"] == "blocked-run")
    assert blocked["detail_state"] == "recorded"
    assert blocked["recorded_reasons"] == ["Awaiting independently verified result"]


def test_progress_binds_observed_stages_and_registered_paper(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id="staged-run",
        status="complete",
        stage_path="upstream-run",
    )
    stage_root = runtime.projects_root / "progress-project" / "runs" / "staged-run" / "upstream-run"
    for stage in (1, 14):
        path = stage_root / f"stage-{stage:02d}"
        path.mkdir(parents=True)
        (path / "result.json").write_text("{}\n", encoding="utf-8")
    snapshot = runtime.select_run(
        "progress-project",
        "staged-run",
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.update(
        "progress-project",
        expected_revision=snapshot.revision,
        completed_stages=[1, 14],
    )
    paper_dir = runtime.projects_root / "progress-project" / "papers" / "paper-one"
    paper_dir.mkdir()
    (paper_dir / "main.md").write_text("# Evidence paper\n", encoding="utf-8")
    snapshot = runtime.register_paper(
        "progress-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="progress-project",
            title="Evidence paper",
            date="2026-09-06",
            provider="scripted",
            model="deterministic-model",
            condition="progress-fixture",
            task="progress-view",
            seed=0,
            stage=18,
            status="reviewed-draft",
            evidence_scope="engineering-only",
            source_run="staged-run",
            files={"Manuscript": "main.md"},
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    runtime.select_paper(
        "progress-project",
        "paper-one",
        expected_revision=snapshot.revision,
        global_latest=False,
    )

    _, data = _progress(runtime)

    assert data["stage_state"] == "available"
    assert [item["stage"] for item in data["stages"]] == [1, 14]
    assert all(item["observed_state"] == "observed_completed" for item in data["stages"])
    assert all(len(item["support_ref_ids"]) == 2 for item in data["stages"])
    assert data["current_paper_id"] == "paper-one"
    assert data["papers"][0]["selected"] is True
    assert data["papers"][0]["observed_state"] == "current_work"
    assert "review_paper_evidence" in {item["kind"] for item in data["next_step_candidates"]}


def test_progress_surfaces_a_bounded_project_acquisition_decision(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    run_id = "acquisition-run"
    artifact = f"runs/{run_id}/acquisition/REPORT.json"
    _begin_run(
        runtime,
        snapshot,
        run_id=run_id,
        status="complete",
        stage_path="acquisition",
        artifact=artifact,
    )
    request = load_dataset_acquisition_request(
        "configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml"
    ).request
    for binding in request.evidence:
        destination = tmp_path / binding.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binding.path, destination)
    report = inspect_dataset_acquisition_request(request, workspace_root=tmp_path)
    report_path = runtime.projects_root / "progress-project" / artifact
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    _, data = _progress(runtime)

    assert data["counts"]["acquisition_requests"] == 1
    assert data["acquisitions"] == [
        {
            "run_ref_id": data["acquisitions"][0]["run_ref_id"],
            "run_id": run_id,
            "request_id": report.request_id,
            "request_sha256": report.request_sha256,
            "report_sha256": data["acquisitions"][0]["report_sha256"],
            "status": "awaiting_owner_approval",
            "purpose": report.purpose,
            "claim_boundary": report.claim_boundary,
            "item_count": 10,
            "maximum_total_bytes": 10 * 1024 * 1024,
            "source_hosts": ["raw.githubusercontent.com"],
            "ready_for_owner_approval": report.ready_for_owner_approval,
            "download_authorized": False,
            "authorizes_ingestion": False,
            "authorizes_execution": False,
            "no_network_access_performed": True,
            "no_download_performed": True,
            "no_dataset_file_created": True,
            "support_ref_ids": data["acquisitions"][0]["support_ref_ids"],
        }
    ]
    acquisition_candidate = next(
        item for item in data["next_step_candidates"] if item["kind"] == "review_data_acquisition"
    )
    assert acquisition_candidate["target_ids"] == [report.request_id]
    assert len(acquisition_candidate["support_ref_ids"]) == 2
    resolver = WorkspaceIntentResolver(runtime)
    catalog = resolver.quick_catalog("progress-project")
    descriptor = next(
        item
        for item in catalog.intents
        if item.quick_intent_id == "review-data-acquisition-request"
    )
    assert descriptor.goal is IntentGoal.NEXT_STEP_REVIEW
    resolution = resolver.resolve(
        {
            "kind": "quick",
            "project_id": "progress-project",
            "snapshot_revision": catalog.snapshot.snapshot_revision,
            "snapshot_sha256": catalog.snapshot.snapshot_sha256,
            "quick_intent_id": descriptor.quick_intent_id,
        }
    )
    assert resolution.status == "resolved"

    invalid = report.model_dump(mode="json")
    invalid["item_count"] += 1
    report_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ProjectSurfaceChangedError, match="acquisition report is invalid"):
        _progress(runtime)


def test_progress_surfaces_exact_metadata_read_gate_without_reading_content(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    run_id = "metadata-audit-plan-run"
    artifact = f"runs/{run_id}/metadata_audit_planning/BUNDLE.json"
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id=run_id,
        status="awaiting-content-read-approval",
        stage_path="metadata_audit_planning",
        artifact=artifact,
    )
    project_root = runtime.projects_root / "progress-project"
    revision = "a" * 40
    item = AcquiredItemReceipt(
        item_id="task-01",
        source_url=f"https://example.test/{revision}/task-01",
        source_revision=revision,
        destination="task.yaml",
        size_bytes=1,
        sha256="1" * 64,
        expected_sha256=None,
    )
    receipt = DatasetAcquisitionReceipt.create(
        request_id="benchmark-metadata-v1",
        request_sha256="2" * 64,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 13, 0, tzinfo=UTC),
        acquired_at=datetime(2026, 9, 13, 1, tzinfo=UTC),
        approval_scope="download-only-no-ingestion",
        destination_root=(
            "outputs/projects/progress-project/evaluations/acquisitions/benchmark-metadata-v1/raw"
        ),
        items=(item,),
        item_count=1,
        total_bytes=1,
        maximum_total_bytes=1_048_576,
        source_hosts=("example.test",),
    )
    receipt_path = project_root / "evaluations/acquisitions/benchmark-metadata-v1/RECEIPT.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    implementation_sha256 = hashlib.sha256(Path(audit_module.__file__).read_bytes()).hexdigest()
    plan = StructuredMetadataAuditPlan(
        plan_id="benchmark-metadata-v1-content-audit-v1",
        project_id="progress-project",
        request_id="benchmark-metadata-v1",
        request_file_sha256="3" * 64,
        request_sha256=receipt.request_sha256,
        receipt_file_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        receipt_sha256=receipt.receipt_sha256,
        acquired_at=receipt.acquired_at,
        auditor_id="scitaste-structured-metadata-audit-v1",
        auditor_implementation_sha256=implementation_sha256,
        expected_item_ids=(item.item_id,),
        formats=(StructuredMetadataFormat.YAML,),
        maximum_source_bytes_per_item=262_144,
        maximum_total_source_bytes=1_048_576,
        maximum_structure_depth=32,
        maximum_nodes_per_item=500_000,
        maximum_distinct_paths=10_000,
        maximum_string_utf8_bytes=1_048_576,
        maximum_csv_rows=1_000_000,
        maximum_csv_columns=4_096,
    )
    plan_path = project_root / f"runs/{run_id}/metadata_audit_planning/PLAN.json"
    save_structured_metadata_audit_plan(plan, plan_path)
    bundle = build_structured_metadata_audit_plan_bundle(
        project_id="progress-project",
        run_id=run_id,
        project_root=project_root,
        plan_paths=(plan_path,),
        receipt_paths=(receipt_path,),
    )
    save_structured_metadata_audit_plan_bundle(bundle, project_root / artifact)

    _, data = _progress(runtime)

    assert data["counts"]["metadata_audit_plans"] == 1
    assert data["metadata_audit_plans"] == [
        {
            "run_ref_id": data["metadata_audit_plans"][0]["run_ref_id"],
            "run_id": run_id,
            "bundle_file_sha256": data["metadata_audit_plans"][0]["bundle_file_sha256"],
            "bundle_sha256": bundle.bundle_sha256,
            "plan_id": plan.plan_id,
            "request_id": plan.request_id,
            "plan_locator": f"runs/{run_id}/metadata_audit_planning/PLAN.json",
            "plan_file_sha256": data["metadata_audit_plans"][0]["plan_file_sha256"],
            "plan_sha256": plan.plan_sha256,
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_locator": ("evaluations/acquisitions/benchmark-metadata-v1/RECEIPT.json"),
            "receipt_file_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "auditor_implementation_sha256": implementation_sha256,
            "auditor_implementation_current": True,
            "expected_item_count": 1,
            "formats": ["application/x-yaml"],
            "maximum_total_source_bytes": 1_048_576,
            "status": "awaiting_content_read_approval",
            "next_gate": "approve_exact_local_structured_metadata_read",
            "ready_for_owner_approval": True,
            "source_content_read": False,
            "owner_approval_recorded": False,
            "authorizes_local_content_read": False,
            "authorizes_projection": False,
            "authorizes_ingestion": False,
            "authorizes_execution": False,
            "support_ref_ids": data["metadata_audit_plans"][0]["support_ref_ids"],
        }
    ]
    candidate = next(
        item for item in data["next_step_candidates"] if item["kind"] == "approve_metadata_audit"
    )
    assert candidate["target_ids"] == ["benchmark-metadata-v1"]


def test_progress_replaces_acquisition_gate_with_download_only_receipt(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    gate_run_id = "acquisition-run"
    gate_artifact = f"runs/{gate_run_id}/acquisition/REPORT.json"
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id=gate_run_id,
        status="complete",
        stage_path="acquisition",
        artifact=gate_artifact,
    )
    request = load_dataset_acquisition_request(
        "configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml"
    ).request
    for binding in request.evidence:
        destination = tmp_path / binding.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binding.path, destination)
    report = inspect_dataset_acquisition_request(request, workspace_root=tmp_path)
    gate_path = runtime.projects_root / "progress-project" / gate_artifact
    gate_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    receipt_run_id = "receipt-run"
    receipt_artifact = f"runs/{receipt_run_id}/acquisition_receipt/RESULT.json"
    _begin_run(
        runtime,
        snapshot,
        run_id=receipt_run_id,
        status="complete",
        stage_path="acquisition_receipt",
        artifact=receipt_artifact,
    )
    acquired_at = datetime(2026, 9, 12, 12, tzinfo=UTC)
    receipts = tuple(
        AcquiredItemReceipt(
            item_id=item.item_id,
            source_url=item.source_url,
            source_revision=item.source_revision,
            destination=item.destination,
            size_bytes=1,
            sha256="1" * 64,
            expected_sha256=item.expected_sha256,
        )
        for item in report.items
    )
    receipt = DatasetAcquisitionReceipt.create(
        request_id=report.request_id,
        request_sha256=report.request_sha256,
        approved_by="project-owner-10gb-policy",
        approved_at=acquired_at,
        acquired_at=acquired_at,
        approval_scope="download-only-no-ingestion",
        destination_root=(
            f"outputs/projects/progress-project/evaluations/acquisitions/{report.request_id}/raw"
        ),
        items=receipts,
        item_count=len(receipts),
        total_bytes=len(receipts),
        maximum_total_bytes=report.maximum_total_bytes,
        source_hosts=report.source_hosts,
    )
    receipt_locator = f"evaluations/acquisitions/{report.request_id}/RECEIPT.json"
    receipt_path = runtime.projects_root / "progress-project" / receipt_locator
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_rendered = receipt.model_dump_json(indent=2) + "\n"
    receipt_path.write_text(receipt_rendered, encoding="utf-8")
    receipt_file_sha256 = hashlib.sha256(receipt_rendered.encode()).hexdigest()
    bundle = {
        "schema_version": "1.0",
        "measurement_kind": "real-source-acquisition",
        "project_id": "progress-project",
        "run_id": receipt_run_id,
        "source_commit": "1" * 40,
        "status": "complete-download-only",
        "owner_policy": {
            "policy": "configs/evaluation/acquisition/standing-owner-policy.yaml",
            "policy_file_sha256": "2" * 64,
            "maximum_transaction_bytes": 10_000_000_000,
            "byte_unit": "decimal",
            "approval_identity": "project-owner-10gb-policy",
        },
        "transactions": [
            {
                "request_id": report.request_id,
                "manifest": "configs/evaluation/acquisition/request.yaml",
                "manifest_file_sha256": "3" * 64,
                "request_sha256": report.request_sha256,
                "receipt": receipt_locator,
                "receipt_file_sha256": receipt_file_sha256,
                "receipt_sha256": receipt.receipt_sha256,
                "item_count": receipt.item_count,
                "total_bytes": receipt.total_bytes,
                "maximum_total_bytes": receipt.maximum_total_bytes,
            }
        ],
        "aggregate": {
            "transaction_count": 1,
            "item_count": receipt.item_count,
            "total_bytes": receipt.total_bytes,
            "maximum_total_bytes": receipt.maximum_total_bytes,
            "receipt_and_raw_hash_verification": "passed",
            "redirects_followed": False,
            "existing_files_overwritten": False,
        },
        "authority_boundary": {
            "content_access_performed": False,
            "content_parsing_performed": False,
            "dataset_ingestion_performed": False,
            "archive_extraction_performed": False,
            "code_execution_performed": False,
            "api_model_calls": 0,
            "gpu_workloads": 0,
            "human_evaluation_performed": False,
            "authorizes_next_stage": False,
        },
        "scientific_effectiveness_established": False,
        "next_gate": "approve bounded format-aware content inspection",
    }
    bundle_path = runtime.projects_root / "progress-project" / receipt_artifact
    bundle_rendered = json.dumps(bundle, indent=2) + "\n"
    bundle_path.write_text(bundle_rendered, encoding="utf-8")
    bundle_file_sha256 = hashlib.sha256(bundle_rendered.encode()).hexdigest()

    _, data = _progress(runtime)

    assert data["counts"]["acquisition_requests"] == 0
    assert data["counts"]["acquisition_receipts"] == 1
    assert data["acquisitions"] == []
    assert data["acquisition_receipts"] == [
        {
            "run_ref_id": data["acquisition_receipts"][0]["run_ref_id"],
            "run_id": receipt_run_id,
            "request_id": report.request_id,
            "request_sha256": report.request_sha256,
            "bundle_file_sha256": bundle_file_sha256,
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_file_sha256": receipt_file_sha256,
            "status": "acquired_download_only",
            "purpose": report.purpose,
            "claim_boundary": report.claim_boundary,
            "item_count": receipt.item_count,
            "total_bytes": receipt.total_bytes,
            "maximum_total_bytes": receipt.maximum_total_bytes,
            "source_hosts": list(receipt.source_hosts),
            "acquired_at": acquired_at.isoformat(),
            "acquisition_complete": True,
            "content_access_performed": False,
            "content_audit_required": True,
            "authorizes_ingestion": False,
            "authorizes_execution": False,
            "next_gate": bundle["next_gate"],
            "support_ref_ids": data["acquisition_receipts"][0]["support_ref_ids"],
        }
    ]
    candidate = next(
        item for item in data["next_step_candidates"] if item["kind"] == "review_data_acquisition"
    )
    assert candidate["target_ids"] == [report.request_id]


def test_progress_surfaces_post_download_scientific_qualification(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    acquisition_run_id = "superseded-acquisition-run"
    acquisition_artifact = f"runs/{acquisition_run_id}/acquisition/REPORT.json"
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id=acquisition_run_id,
        status="complete",
        stage_path="acquisition",
        artifact=acquisition_artifact,
    )
    request = load_dataset_acquisition_request(
        "configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml"
    ).request
    for binding in request.evidence:
        destination = tmp_path / binding.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binding.path, destination)
    acquisition_report = inspect_dataset_acquisition_request(request, workspace_root=tmp_path)
    acquisition_report_path = runtime.projects_root / "progress-project" / acquisition_artifact
    acquisition_report_path.write_text(
        acquisition_report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    run_id = "qualification-run"
    artifact = f"runs/{run_id}/acquisition_qualification/REPORT.json"
    _begin_run(
        runtime,
        snapshot,
        run_id=run_id,
        status="complete",
        stage_path="acquisition_qualification",
        artifact=artifact,
    )
    report = _brief_only_cohort_report().model_copy(
        update={
            "request_id": acquisition_report.request_id,
            "request_sha256": acquisition_report.request_sha256,
        }
    )
    report_path = runtime.projects_root / "progress-project" / artifact
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    _, data = _progress(runtime)

    assert data["acquisitions"] == []
    assert data["counts"]["acquisition_requests"] == 0
    assert data["acquisition_qualifications"] == [
        {
            "run_ref_id": data["acquisition_qualifications"][0]["run_ref_id"],
            "run_id": run_id,
            "selection_id": report.selection_id,
            "request_sha256": report.request_sha256,
            "receipt_sha256": report.receipt_sha256,
            "report_sha256": report.report_sha256,
            "report_file_sha256": data["acquisition_qualifications"][0]["report_file_sha256"],
            "scientific_disposition": "brief-only-pilot-candidate",
            "task_count": 1,
            "observed_total_bytes": 42,
            "exact_task_set_verified": True,
            "exact_bytes_verified": True,
            "ready_for_stagewise_pilot": True,
            "ready_for_brief_only_package_prepilot": True,
            "ready_for_formal_empirical_task_binding": False,
            "ready_for_objective_progress_binding": False,
            "formal_task_blocker_codes": ["runtime-assets-absent"],
            "objective_progress_blocker_codes": ["objective-score-absent"],
            "authorizes_ingestion": False,
            "authorizes_execution": False,
            "provider_call_performed": False,
            "gpu_work_performed": False,
            "support_ref_ids": data["acquisition_qualifications"][0]["support_ref_ids"],
        }
    ]
    candidate = next(
        item for item in data["next_step_candidates"] if item["kind"] == "review_data_acquisition"
    )
    assert candidate["target_ids"] == [report.selection_id]

    invalid = report.model_dump(mode="json")
    invalid["task_count"] += 1
    report_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ProjectSurfaceChangedError, match="qualification is invalid"):
        _progress(runtime)


def test_progress_surfaces_executable_benchmark_qualification(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    run_id = "benchmark-qualification-run"
    artifact = f"runs/{run_id}/benchmark_qualification/REPORT.json"
    _begin_run(
        runtime,
        snapshot,
        run_id=run_id,
        status="complete",
        stage_path="benchmark_qualification",
        artifact=artifact,
    )
    inspection = load_executable_candidate_manifest(
        "configs/evaluation/candidates/mlrc_3090_objective_progress_v1.yaml"
    )
    report = inspect_executable_candidate(
        inspection,
        resource_corpus_path=("docs/research/data/autoresearch_evaluation_resources_v7.yaml"),
        compute_catalog_path="configs/resources/compute_catalog_v2.yaml",
    )
    report_path = runtime.projects_root / "progress-project" / artifact
    save_executable_candidate_report(report, report_path)

    _, data = _progress(runtime)

    assert data["benchmark_qualifications"] == [
        {
            "run_ref_id": data["benchmark_qualifications"][0]["run_ref_id"],
            "run_id": run_id,
            "candidate_id": report.candidate_id,
            "proposal_sha256": report.proposal_sha256,
            "report_sha256": report.report_sha256,
            "report_file_sha256": data["benchmark_qualifications"][0]["report_file_sha256"],
            "accepted_task_count": 7,
            "selected_task_count": 4,
            "excluded_task_count": 3,
            "selected_task_ids": list(report.selected_task_ids),
            "excluded_task_ids": list(report.excluded_task_ids),
            "first_preflight_candidate_ids": [
                "perception_temporal_action_loc",
                "meta-learning",
            ],
            "planned_cells": 36,
            "planned_gpu_hours": 180.0,
            "formal_gpu_hour_cap": 192.0,
            "metadata_review_ready": True,
            "acquisition_request_ready": False,
            "local_preflight_ready": False,
            "experiment_ready": False,
            "requires_additional_48gb_single_device_resource": True,
            "integrity_blocker_codes": [],
            "qualification_blocker_codes": [item.code for item in report.qualification_blockers],
            "pending_qualification_codes": [item.code for item in report.pending_qualifications],
            "authorizes_download": False,
            "authorizes_api_calls": False,
            "authorizes_gpu_work": False,
            "authorizes_execution": False,
            "external_action_performed": False,
            "support_ref_ids": data["benchmark_qualifications"][0]["support_ref_ids"],
        }
    ]
    candidate = next(
        item
        for item in data["next_step_candidates"]
        if item["kind"] == "review_benchmark_qualification"
    )
    assert candidate["target_ids"] == [report.candidate_id]

    invalid = json.loads(report_path.read_text(encoding="utf-8"))
    invalid["planned_gpu_hours"] = 1.0
    report_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ProjectSurfaceChangedError, match="qualification is invalid"):
        _progress(runtime)


def test_progress_surfaces_large_dataset_package_decision(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    run_id = "dataset-package-run"
    artifact = f"runs/{run_id}/dataset_package_acquisition/REPORT.json"
    _begin_run(
        runtime,
        snapshot,
        run_id=run_id,
        status="complete",
        stage_path="dataset_package_acquisition",
        artifact=artifact,
    )
    report = inspect_dataset_package_request(
        load_dataset_package_request(
            "configs/evaluation/acquisition/mlrc_first_preflight_assets_v1.yaml"
        ),
        workspace_root=".",
    )
    report_path = runtime.projects_root / "progress-project" / artifact
    save_dataset_package_gate_report(report, report_path)

    _, data = _progress(runtime)

    assert data["dataset_packages"] == [
        {
            "run_ref_id": data["dataset_packages"][0]["run_ref_id"],
            "run_id": run_id,
            "request_id": report.request_id,
            "proposal_sha256": report.proposal_sha256,
            "report_sha256": report.report_sha256,
            "report_file_sha256": data["dataset_packages"][0]["report_file_sha256"],
            "selected_task_ids": list(report.selected_task_ids),
            "source_hosts": list(report.source_hosts),
            "asset_count": 39,
            "observed_download_bytes": 3_761_168_137,
            "maximum_unpacked_bytes": 16 * 1024**3,
            "minimum_free_storage_bytes": 32 * 1024**3,
            "task_qualifications": [
                item.model_dump(mode="json") for item in report.task_qualifications
            ],
            "metadata_review_ready": True,
            "ready_for_owner_approval": report.ready_for_owner_approval,
            "pending_content_hash_count": 39,
            "integrity_blocker_codes": [],
            "approval_blocker_codes": [item.code for item in report.approval_blockers],
            "pending_qualification_codes": [item.code for item in report.pending_qualifications],
            "authorization_blocker_codes": [item.code for item in report.authorization_blockers],
            "post_approval_streaming_available": True,
            "archive_safety_check_available": True,
            "authorizes_network_preflight": False,
            "authorizes_download": False,
            "authorizes_ingestion": False,
            "authorizes_api_calls": False,
            "authorizes_gpu_work": False,
            "authorizes_execution": False,
            "no_network_access_performed": True,
            "no_download_performed": True,
            "no_dataset_file_created": True,
            "support_ref_ids": data["dataset_packages"][0]["support_ref_ids"],
        }
    ]
    candidate = next(
        item for item in data["next_step_candidates"] if item["kind"] == "review_data_acquisition"
    )
    assert candidate["target_ids"] == [report.request_id]

    invalid = json.loads(report_path.read_text(encoding="utf-8"))
    invalid["observed_download_bytes"] += 1
    report_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ProjectSurfaceChangedError, match="dataset package report is invalid"):
        _progress(runtime)


def test_strict_manifest_extensions_supply_milestones_or_fail_closed(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id="milestone-run",
        status="complete",
    )
    run_dir = runtime.projects_root / "progress-project" / "runs" / "milestone-run"
    (run_dir / "decision.json").write_text("{}\n", encoding="utf-8")
    snapshot = runtime.update(
        "progress-project",
        expected_revision=snapshot.revision,
        current_focus={
            "decision_id": "bounded-workspace-planner",
            "status": "implementation-preaccepted-live-pilot-blocked",
            "selected_option": "bounded-planner",
            "online_model": "zhipu-direct/glm-5.3-flash",
            "next_gate": "Independent review of a real project pilot",
        },
        iterations=[
            {
                "iteration_id": "progress-foundation",
                "date": "2026-09-06",
                "status": "completed-dogfooding",
                "decision": "Use project progress as the generative workspace foundation.",
                "evidence": "runs/milestone-run/",
            },
            {
                "iteration_id": "external-reference",
                "date": "2026-09-06",
                "status": "referenced",
                "decision": "Retain an explicitly unbound manifest reference.",
                "evidence": "references/external-review",
            },
        ],
    )

    first, data = _progress(runtime)

    assert data["focus"] == "bounded-workspace-planner"
    assert data["next_gate"] == "Independent review of a real project pilot"
    assert data["milestone_state"] == "available"
    assert [item["evidence_binding"] for item in data["milestones"]] == [
        "content_addressed",
        "manifest_declared",
    ]
    assert [item["observed_state"] for item in data["milestones"]] == [
        "observed_completed",
        "unknown",
    ]

    runtime.update(
        "progress-project",
        expected_revision=snapshot.revision,
        current_focus={"decision_id": "<script>"},
        iterations=[
            {
                "iteration_id": "duplicate",
                "date": "2026-09-06",
                "status": "complete",
                "decision": "First declaration.",
                "evidence": "runs/milestone-run",
            },
            {
                "iteration_id": "duplicate",
                "date": "2026-09-06",
                "status": "complete",
                "decision": "Second declaration.",
                "evidence": "runs/milestone-run",
            },
        ],
    )
    second, invalid = _progress(runtime)

    assert invalid["focus"] == "Show only evidence-grounded project progress."
    assert invalid["focus_status"] is None
    assert invalid["milestone_state"] == "unavailable"
    assert invalid["milestones"] == []
    assert first.renderer.surface_fingerprint != second.renderer.surface_fingerprint


def test_progress_component_rejects_ungrounded_rows_and_extra_percentage(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    _begin_run(runtime, snapshot, run_id="grounded-run", status="complete")
    document, _ = _progress(runtime)
    payload = (
        WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="progress-project"))
        .model_dump(mode="json")
    )
    data = payload["components"][0]["data"]
    data["recent_activity"][0]["support_ref_ids"] = [data["recent_activity"][0]["run_ref_id"]]
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)

    payload = (
        WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="progress-project"))
        .model_dump(mode="json")
    )
    payload["components"][0]["data"]["progress_percent"] = 50
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)

    assert document.renderer.execution_authority == "none"
