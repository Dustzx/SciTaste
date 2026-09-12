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
    OutcomeInformationAvailability,
    ProjectionSemanticRole,
    ReadinessStatus,
    SourceAdmissionEntry,
    SourceAdmissionProposal,
    SourceAdmissionVerdict,
    SourceIsolationArgument,
    SourceProjectionField,
    SourceQualityArgument,
    SourceQualityReview,
    SourceRightsArgument,
    TasteCorpusFileBinding,
    approve_dataset_acquisition_request,
    approve_json_content_audit,
    approve_source_projection,
    build_source_projection_plan,
    inspect_acquired_json_content,
    inspect_source_admission,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
    load_json_content_audit_approval,
    load_source_admission_proposal,
    load_source_projection_approval,
    load_source_projection_plan,
    materialize_dataset_acquisition,
    materialize_source_projections,
    save_dataset_acquisition_request,
    save_json_content_audit_approval,
    save_json_content_audit_report,
    save_source_admission_report,
    save_source_projection_approval,
    save_source_projection_plan,
)

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)
REVISION = "a" * 40


def test_projection_freezes_identical_raw_and_abstraction_bytes(tmp_path: Path) -> None:
    request, receipt, content_sha = _acquire_and_audit_source(tmp_path)
    audit_report_path = tmp_path / "controls/content-audit.json"
    admission_proposal_path, admission_report_path = _admit_source(
        tmp_path,
        request,
        receipt,
        audit_report_path,
        content_sha,
    )
    plan = build_source_projection_plan(
        plan_id="aaar-projection-pilot-v1",
        approved_request_path=request.path,
        receipt_path=receipt.path,
        content_audit_report_path=audit_report_path,
        source_admission_proposal_path=admission_proposal_path,
        source_admission_report_path=admission_report_path,
        workspace_root=tmp_path,
        projection_output_root="outputs/projections/aaar-projection-pilot-v1",
        fields=(
            SourceProjectionField(
                output_name="problem_context",
                json_pointer="/problem",
                semantic_role=ProjectionSemanticRole.PROBLEM_CONTEXT,
            ),
            SourceProjectionField(
                output_name="scientific_action",
                json_pointer="/experiments/*/action",
                semantic_role=ProjectionSemanticRole.SCIENTIFIC_ACTION,
            ),
            SourceProjectionField(
                output_name="justification",
                json_pointer="/experiments/*/why",
                semantic_role=ProjectionSemanticRole.JUSTIFICATION,
            ),
        ),
        forbidden_json_pointers=("/outcome",),
        forbidden_model_visible_exact_strings=("held-out-secret",),
        outcome_information_availability=OutcomeInformationAvailability.WITHHELD,
        created_at=NOW + timedelta(hours=4),
    )
    plan_path = tmp_path / "controls/projection-plan.json"
    save_source_projection_plan(plan, plan_path)
    loaded_plan = load_source_projection_plan(plan_path)
    approval = approve_source_projection(
        loaded_plan,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=NOW + timedelta(hours=5),
    )
    approval_path = tmp_path / "controls/projection-approval.json"
    save_source_projection_approval(approval, approval_path)

    with pytest.raises(ValueError, match="explicit local projection switch"):
        materialize_source_projections(
            loaded_plan,
            load_source_projection_approval(approval_path),
            workspace_root=tmp_path,
            materialized_at=NOW + timedelta(hours=6),
            allow_local_source_projection=False,
        )

    projection_receipt = materialize_source_projections(
        loaded_plan,
        load_source_projection_approval(approval_path),
        workspace_root=tmp_path,
        materialized_at=NOW + timedelta(hours=6),
        allow_local_source_projection=True,
    )
    item = projection_receipt.items[0]
    projected = json.loads((tmp_path / item.projection_path).read_text(encoding="utf-8"))

    assert projected["fields"]["problem_context"]["value"] == "Choose a diagnosis."
    assert projected["fields"]["scientific_action"]["value"] == ["Run an ablation."]
    assert "outcome" not in projected["fields"]
    assert "held-out-secret" not in json.dumps(projected).casefold()
    assert item.raw_rag_projection_sha256 == item.abstraction_input_projection_sha256
    assert projection_receipt.ready_for_tokenization is True
    assert projection_receipt.ready_for_abstraction_resource_proposal is False
    assert projection_receipt.model_calls_performed is False
    assert projection_receipt.experiment_performed is False


def _acquire_and_audit_source(tmp_path: Path):
    content = (
        b'{"arxiv_id":"2305.01937","problem":"Choose a diagnosis.",'
        b'"experiments":[{"action":"Run an ablation.","why":"Separate causes."}],'
        b'"outcome":"held-out-secret"}'
    )
    evidence_path = tmp_path / "scope.txt"
    evidence_path.write_text("synthetic source projection fixture\n", encoding="utf-8")
    item = AcquisitionItem(
        item_id="2305.01937",
        source_url=f"https://example.org/{REVISION}/2305.01937/data_text.json",
        source_revision=REVISION,
        destination="2305.01937/data_text.json",
        maximum_bytes=4_096,
        media_type="application/json",
        license_identifier="CC-BY-4.0",
        license_scope="Synthetic test content.",
        license_status=ReadinessStatus.VERIFIED,
    )
    request = DatasetAcquisitionRequest(
        request_id="aaar-projection-test",
        project_id="test-project",
        track_id="taste-abstraction",
        authorization_scope="download-only-no-ingestion",
        purpose="Exercise the source projection boundary.",
        claim_boundary="Synthetic engineering test only.",
        selection_id="aaar-projection-test",
        selection_proposal_sha256="1" * 64,
        destination_root="outputs/acquisitions/aaar-projection-test/raw",
        allowed_hosts=("example.org",),
        items=(item,),
        maximum_total_bytes=item.maximum_bytes,
        evidence=(
            AcquisitionEvidenceBinding(
                evidence_id="scope",
                path="scope.txt",
                sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            ),
        ),
    )
    approved = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=NOW,
    )
    request_path = tmp_path / "controls/approved-request.json"
    save_dataset_acquisition_request(approved, request_path)
    materialize_dataset_acquisition(
        approved,
        workspace_root=tmp_path,
        confirmed_request_sha256=approved.request_sha256,
        allow_network_download=True,
        fetcher=lambda _url, _maximum, _media: content,
        acquired_at=NOW + timedelta(hours=1),
    )
    receipt_path = tmp_path / "outputs/acquisitions/aaar-projection-test/RECEIPT.json"
    request_inspection = load_dataset_acquisition_request(request_path)
    receipt_inspection = load_dataset_acquisition_receipt(receipt_path)
    audit_approval = approve_json_content_audit(
        request_inspection,
        receipt_inspection,
        confirmed_request_sha256=approved.request_sha256,
        confirmed_receipt_sha256=receipt_inspection.receipt.receipt_sha256,
        approved_by="test-owner",
        approved_at=NOW + timedelta(hours=2),
    )
    audit_approval_path = tmp_path / "controls/content-audit-approval.json"
    save_json_content_audit_approval(audit_approval, audit_approval_path)
    audit = inspect_acquired_json_content(
        request_inspection,
        receipt_inspection,
        load_json_content_audit_approval(audit_approval_path),
        workspace_root=tmp_path,
        allow_local_content_read=True,
        audited_at=NOW + timedelta(hours=3),
    )
    audit_report_path = tmp_path / "controls/content-audit.json"
    save_json_content_audit_report(audit, audit_report_path)
    return request_inspection, receipt_inspection, hashlib.sha256(content).hexdigest()


def _admit_source(
    root: Path,
    request,
    receipt,
    audit_path: Path,
    content_sha: str,
) -> tuple[Path, Path]:
    audit_binding = _binding(root, audit_path.relative_to(root).as_posix())
    rights = _write_binding(root, "evidence/rights.txt", "CC-BY-4.0 verified\n")
    quality = _write_binding(root, "evidence/quality.txt", "peer-reviewed source\n")
    isolation = _write_binding(root, "evidence/isolation.txt", "source-disjoint\n")
    entry = SourceAdmissionEntry(
        item_id="2305.01937",
        source_id="source-2305-01937",
        curator_id="curator",
        title="Synthetic source",
        locator="https://arxiv.org/abs/2305.01937",
        source_content_sha256=content_sha,
        rights=SourceRightsArgument(
            evidence=rights,
            license_id="CC-BY-4.0",
            attribution="Synthetic authors",
            permits_research_analysis=True,
            permits_derived_abstraction=True,
            pre_body_screen_consistent=True,
        ),
        quality=SourceQualityArgument(
            evidence=quality,
            quality_tier="peer-reviewed-primary",
            venue_or_source="ICLR",
            publication_year=2025,
            primary_scientific_record=True,
            decision_process_observable=True,
            quality_rationale="Contains an inspectable experiment decision.",
        ),
        isolation=SourceIsolationArgument(
            evidence=isolation,
            source_group_id="source-group-a",
            checked_against_held_out_cases=True,
            checked_against_self_development_evidence=True,
            checked_at=NOW + timedelta(hours=3),
        ),
    )
    reviews = tuple(
        SourceQualityReview(
            review_id=f"quality-review-{index}",
            item_id=entry.item_id,
            reviewer_id=f"reviewer-{index}",
            source_content_sha256=content_sha,
            quality_evidence_sha256=quality.sha256,
            verdict=SourceAdmissionVerdict.ADMIT,
            scientific_rigor_supported=True,
            decision_traceability_supported=True,
            transferable_taste_supported=True,
            expertise_scope="machine-learning experiments",
            rationale="Suitable for the synthetic projection test.",
        )
        for index in (1, 2)
    )
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    proposal = SourceAdmissionProposal(
        proposal_id="aaar-source-admission-test",
        project_id=request.request.project_id,
        request_id=request.request.request_id,
        request_sha256=request.request.request_sha256,
        receipt_sha256=receipt.receipt.receipt_sha256,
        content_audit_report=audit_binding,
        content_audit_report_sha256=audit_payload["report_sha256"],
        minimum_admitted_sources=1,
        held_out_source_group_ids=("held-out-group",),
        self_development_source_group_ids=("self-development",),
        entries=(entry,),
        quality_reviews=reviews,
    )
    proposal_path = root / "controls/source-admission-proposal.json"
    proposal_path.write_text(proposal.model_dump_json(indent=2) + "\n", encoding="utf-8")
    inspection = load_source_admission_proposal(proposal_path)
    report = inspect_source_admission(inspection, evidence_root=root)
    report_path = root / "controls/source-admission-report.json"
    save_source_admission_report(report, report_path)
    return proposal_path, report_path


def _write_binding(root: Path, name: str, text: str) -> TasteCorpusFileBinding:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return _binding(root, name)


def _binding(root: Path, name: str) -> TasteCorpusFileBinding:
    path = root / name
    return TasteCorpusFileBinding(
        path=name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
