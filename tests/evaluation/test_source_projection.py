from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scitaste.cli import main
from scitaste.evaluation import (
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    DatasetAcquisitionRequest,
    OutcomeInformationAvailability,
    ProjectionSemanticRole,
    ReadinessStatus,
    ReferenceSelectionDownstreamEnvelope,
    ReferenceSelectionSourceLink,
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
    approve_reference_selection_comparison,
    approve_source_projection,
    build_source_projection_plan,
    freeze_reference_selection_comparison,
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
    save_reference_selection_approval,
    save_reference_selection_plan,
    save_reference_selection_report,
    save_source_admission_report,
    save_source_projection_approval,
    save_source_projection_plan,
    source_projection_forbidden_exact_strings,
    source_projection_protocol_sha256,
)
from scitaste.evaluation.reference_selection_comparison import (
    load_reference_selection_approval,
    load_reference_selection_plan,
    plan_reference_selection_comparison_from_files,
)
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.reference_mining import (
    ReferenceCandidateMetadata,
    ReferenceDecisionPattern,
    ReferenceEvidenceRole,
    ReferenceIsolationStatus,
    ReferenceMetadataIdentityStatus,
    ReferenceMetadataRelevanceStatus,
    ReferenceMiningBatch,
    ReferenceMiningNeed,
    ReferenceMiningProposal,
    ReferenceMiningRun,
    ReferenceQueryFamily,
    ReferenceRightsStatus,
    ReferenceSearchQuery,
    compile_reference_mining_report,
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
    historical_payload = plan.model_dump(mode="json")
    for field_name in (
        "reference_selection_report",
        "reference_selection_comparison_id",
        "representation_protocol_sha256",
        "quality_arm_source_ids",
        "prestige_arm_source_ids",
        "natural_cross_arm_overlap_source_ids",
        "h0_source_arm_binding",
    ):
        historical_payload.pop(field_name)
    historical_path = tmp_path / "controls/historical-projection-plan.json"
    historical_path.write_text(json.dumps(historical_payload, indent=2) + "\n", encoding="utf-8")
    assert load_source_projection_plan(historical_path).plan.plan_sha256 == plan.plan_sha256
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


def test_h0_projection_preserves_frozen_arms_and_projects_overlap_once(
    tmp_path: Path,
) -> None:
    controls = _h0_projection_chain(tmp_path)
    plan = build_source_projection_plan(
        plan_id="h0-projection-v1",
        approved_request_path=controls["request"],
        receipt_path=controls["receipt"],
        content_audit_report_path=controls["audit"],
        source_admission_proposal_path=controls["admission_proposal"],
        source_admission_report_path=controls["admission_report"],
        reference_selection_report_path=controls["selection_report"],
        workspace_root=tmp_path,
        projection_output_root="outputs/projections/h0-projection-v1",
        fields=controls["fields"],
        forbidden_json_pointers=("/outcome",),
        forbidden_model_visible_exact_strings=("held-out-secret",),
        outcome_information_availability=OutcomeInformationAvailability.WITHHELD,
        created_at=NOW + timedelta(hours=7),
    )
    plan_path = tmp_path / "controls/h0-projection-plan.json"
    save_source_projection_plan(plan, plan_path)
    inspection = load_source_projection_plan(plan_path)
    approval = approve_source_projection(
        inspection,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="h0-owner",
        approved_at=NOW + timedelta(hours=8),
    )
    approval_path = tmp_path / "controls/h0-projection-approval.json"
    save_source_projection_approval(approval, approval_path)
    receipt = materialize_source_projections(
        inspection,
        load_source_projection_approval(approval_path),
        workspace_root=tmp_path,
        materialized_at=NOW + timedelta(hours=9),
        allow_local_source_projection=True,
    )

    assert plan.schema_version == "1.1"
    assert set(plan.quality_arm_source_ids) == {"source-quality-a", "source-quality-b"}
    assert set(plan.prestige_arm_source_ids) == {"source-prestige-a", "source-quality-b"}
    assert plan.natural_cross_arm_overlap_source_ids == ("source-quality-b",)
    assert tuple(item.source_id for item in plan.items) == tuple(
        dict.fromkeys((*plan.quality_arm_source_ids, *plan.prestige_arm_source_ids))
    )
    assert receipt.schema_version == "1.1"
    assert receipt.quality_arm_source_ids == plan.quality_arm_source_ids
    assert receipt.prestige_arm_source_ids == plan.prestige_arm_source_ids
    assert receipt.item_count == 3
    assert receipt.reference_selection_comparison_id == "h0-quality-vs-prestige-v1"
    assert receipt.model_calls_performed is False
    assert receipt.experiment_performed is False


def test_h0_projection_rejects_representation_protocol_drift(tmp_path: Path) -> None:
    controls = _h0_projection_chain(tmp_path, representation_protocol_sha256="f" * 64)

    with pytest.raises(ValueError, match="different representation protocol"):
        build_source_projection_plan(
            plan_id="h0-projection-v1",
            approved_request_path=controls["request"],
            receipt_path=controls["receipt"],
            content_audit_report_path=controls["audit"],
            source_admission_proposal_path=controls["admission_proposal"],
            source_admission_report_path=controls["admission_report"],
            reference_selection_report_path=controls["selection_report"],
            workspace_root=tmp_path,
            projection_output_root="outputs/projections/h0-projection-v1",
            fields=controls["fields"],
            forbidden_json_pointers=("/outcome",),
            forbidden_model_visible_exact_strings=("held-out-secret",),
            outcome_information_availability=OutcomeInformationAvailability.WITHHELD,
            created_at=NOW + timedelta(hours=7),
        )


def test_source_projection_protocol_cli_is_content_free(capsys) -> None:
    assert (
        main(
            [
                "evaluation",
                "source-projection-protocol",
                "--field",
                "problem_context:problem=/problem",
                "--forbid-pointer",
                "/outcome",
                "--forbid-exact-string",
                "held-out-secret",
                "--held-out-source-group",
                "held-out-group",
                "--outcome-information",
                "withheld",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert len(output["representation_protocol_sha256"]) == 64
    assert output["source_content_read"] is False
    assert output["authorizes_experiment"] is False


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


def _h0_projection_chain(
    root: Path,
    *,
    representation_protocol_sha256: str | None = None,
) -> dict[str, object]:
    names = ("quality-a", "quality-b", "prestige-a", "prestige-b")
    item_ids = {name: f"2305.{1937 + index:05d}" for index, name in enumerate(names)}
    contents = {
        name: (
            "{"
            f'"arxiv_id":"{item_ids[name]}",'
            f'"problem":"Choose action for {name}.",'
            '"experiments":[{"action":"Run an ablation.",'
            '"why":"Separate causes."}],'
            '"outcome":"held-out-secret"}'
        ).encode()
        for name in names
    }
    acquisition_items = tuple(
        AcquisitionItem(
            item_id=item_ids[name],
            source_url=(f"https://example.org/{REVISION}/{item_ids[name]}/{name}/data_text.json"),
            source_revision=REVISION,
            destination=f"{name}/data_text.json",
            maximum_bytes=4_096,
            media_type="application/json",
            license_identifier="CC-BY-4.0",
            license_scope="Synthetic H0 projection fixture.",
            license_status=ReadinessStatus.VERIFIED,
        )
        for name in names
    )
    evidence_path = root / "scope.txt"
    evidence_path.write_text("synthetic H0 source projection fixture\n", encoding="utf-8")
    request = DatasetAcquisitionRequest(
        request_id="h0-projection-acquisition-v1",
        project_id="h0-project",
        track_id="taste-abstraction",
        authorization_scope="download-only-no-ingestion",
        purpose="Exercise exact H0 arm projection.",
        claim_boundary="Synthetic engineering test only.",
        selection_id="h0-projection-acquisition-v1",
        selection_proposal_sha256="1" * 64,
        destination_root="outputs/acquisitions/h0-projection-acquisition-v1/raw",
        allowed_hosts=("example.org",),
        items=acquisition_items,
        maximum_total_bytes=sum(item.maximum_bytes for item in acquisition_items),
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
    request_path = root / "controls/approved-request.json"
    save_dataset_acquisition_request(approved, request_path)
    content_by_url = {
        item.source_url: contents[name] for item, name in zip(acquisition_items, names, strict=True)
    }
    materialize_dataset_acquisition(
        approved,
        workspace_root=root,
        confirmed_request_sha256=approved.request_sha256,
        allow_network_download=True,
        fetcher=lambda url, _maximum, _media: content_by_url[url],
        acquired_at=NOW + timedelta(hours=1),
    )
    receipt_path = root / "outputs/acquisitions/h0-projection-acquisition-v1/RECEIPT.json"
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
    audit_approval_path = root / "controls/content-audit-approval.json"
    save_json_content_audit_approval(audit_approval, audit_approval_path)
    audit = inspect_acquired_json_content(
        request_inspection,
        receipt_inspection,
        load_json_content_audit_approval(audit_approval_path),
        workspace_root=root,
        allow_local_content_read=True,
        audited_at=NOW + timedelta(hours=3),
    )
    audit_path = root / "controls/content-audit.json"
    save_json_content_audit_report(audit, audit_path)

    audit_binding = _binding(root, audit_path.relative_to(root).as_posix())
    entries: list[SourceAdmissionEntry] = []
    reviews: list[SourceQualityReview] = []
    for name in names:
        content_sha = hashlib.sha256(contents[name]).hexdigest()
        rights = _write_binding(root, f"evidence/{name}-rights.txt", "CC-BY-4.0\n")
        quality = _write_binding(root, f"evidence/{name}-quality.txt", "quality review\n")
        isolation = _write_binding(root, f"evidence/{name}-isolation.txt", "source-disjoint\n")
        entry = SourceAdmissionEntry(
            item_id=item_ids[name],
            source_id=f"source-{name}",
            curator_id="curator",
            title=f"Synthetic {name}",
            locator=f"https://doi.org/10.0000/{name}",
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
                quality_rationale="Synthetic content-quality decision.",
            ),
            isolation=SourceIsolationArgument(
                evidence=isolation,
                source_group_id=f"group-{name}",
                checked_against_held_out_cases=True,
                checked_against_self_development_evidence=True,
                checked_at=NOW + timedelta(hours=3),
            ),
        )
        entries.append(entry)
        admitted = name.startswith("quality")
        reviews.extend(
            SourceQualityReview(
                review_id=f"{name}-review-{index}",
                item_id=entry.item_id,
                reviewer_id=f"reviewer-{index}",
                source_content_sha256=content_sha,
                quality_evidence_sha256=quality.sha256,
                verdict=(
                    SourceAdmissionVerdict.ADMIT if admitted else SourceAdmissionVerdict.REJECT
                ),
                scientific_rigor_supported=True,
                decision_traceability_supported=True,
                transferable_taste_supported=admitted,
                expertise_scope="machine-learning experiments",
                rationale="Synthetic H0 quality qualification.",
            )
            for index in (1, 2)
        )
    proposal = SourceAdmissionProposal(
        proposal_id="h0-source-admission-v1",
        project_id=request.project_id,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        receipt_sha256=receipt_inspection.receipt.receipt_sha256,
        content_audit_report=audit_binding,
        content_audit_report_sha256=audit.report_sha256,
        minimum_admitted_sources=2,
        held_out_source_group_ids=("held-out-group",),
        self_development_source_group_ids=("self-development",),
        entries=tuple(entries),
        quality_reviews=tuple(reviews),
    )
    proposal_path = root / "controls/source-admission-proposal.json"
    proposal_path.write_text(proposal.model_dump_json(indent=2) + "\n", encoding="utf-8")
    admission = inspect_source_admission(
        load_source_admission_proposal(proposal_path), evidence_root=root
    )
    admission_path = root / "controls/source-admission-report.json"
    save_source_admission_report(admission, admission_path)

    patterns = (
        ReferenceDecisionPattern.PROBLEM_SIGNIFICANCE,
        ReferenceDecisionPattern.DIAGNOSTIC_EXPERIMENT,
    )
    roles = (
        ReferenceEvidenceRole.CHALLENGE,
        ReferenceEvidenceRole.BOUNDARY,
        ReferenceEvidenceRole.ALTERNATIVE,
    )
    need = ReferenceMiningNeed(
        mining_id="h0-reference-pool-v1",
        stage=TasteTask.IDEA,
        decision_question="Which references expose transferable scientific decisions?",
        candidate_actions=("qualify by content", "rank by frozen citations"),
        evidence_gap_ids=("source-quality",),
        required_decision_patterns=patterns,
        required_evidence_roles=roles,
        required_domain_facets=("machine-learning",),
        max_query_count=6,
        max_batches=3,
        saturation_window=2,
        min_distinct_source_groups=2,
        max_per_source_group=1,
        max_cohort_size=4,
    )
    queries = tuple(
        ReferenceSearchQuery(
            query_id=f"query-{family.value}",
            family=family,
            query_text=f"scientific decision {family.value}",
            targeted_decision_patterns=patterns,
            targeted_evidence_roles=roles,
            targeted_domain_facets=("machine-learning",),
        )
        for family in ReferenceQueryFamily
    )
    proposal_mining = ReferenceMiningProposal(
        mining_id=need.mining_id,
        queries=queries,
        rationale="Freeze a complete synthetic H0 pool.",
    )
    citation_counts = {
        "quality-a": 1,
        "quality-b": 1_000,
        "prestige-a": 1_000,
        "prestige-b": 1,
    }
    candidates = tuple(
        ReferenceCandidateMetadata(
            candidate_id=f"candidate-{name}",
            source_group_id=f"group-{name}",
            title=f"Synthetic {name}",
            locator=f"https://doi.org/10.0000/{name}",
            discovery_query_ids=tuple(query.query_id for query in queries),
            hypothesized_decision_patterns=(patterns[index % 2],),
            hypothesized_evidence_roles=roles,
            domain_facets=("machine-learning",),
            rights_status=ReferenceRightsStatus.COMPATIBLE_METADATA_ONLY,
            isolation_status=ReferenceIsolationStatus.ELIGIBLE_CANDIDATE,
            venue="Frozen venue metadata",
            citation_count=citation_counts[name],
            publication_year=2025,
            metadata_provider_ids=("openalex", "crossref"),
            metadata_identity_status=ReferenceMetadataIdentityStatus.CROSS_INDEX_CORROBORATED,
            metadata_title_variants=(f"Synthetic {name}",),
            metadata_relevance_status=ReferenceMetadataRelevanceStatus.ELIGIBLE,
            metadata_grounded_domain_facets=("machine-learning",),
            best_result_rank=1,
            retrieval_observation_count=2,
        )
        for index, name in enumerate(names)
    )
    mining_run = ReferenceMiningRun(
        need=need,
        proposal=proposal_mining,
        batches=(
            ReferenceMiningBatch(
                batch_index=1,
                query_ids=tuple(query.query_id for query in queries),
                candidates=candidates,
            ),
            ReferenceMiningBatch(
                batch_index=2,
                query_ids=tuple(query.query_id for query in queries),
            ),
            ReferenceMiningBatch(
                batch_index=3,
                query_ids=tuple(query.query_id for query in queries),
            ),
        ),
    )
    mining_report = compile_reference_mining_report(mining_run)
    evidence_root = root / "evidence/h0"
    evidence_root.mkdir(parents=True)
    mining_run_path = evidence_root / "MINING_RUN.json"
    mining_report_path = evidence_root / "MINING_REPORT.json"
    mining_run_path.write_text(mining_run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    mining_report_path.write_text(mining_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    fields = (
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
    )
    forbidden_strings = source_projection_forbidden_exact_strings(
        requested=("held-out-secret",),
        held_out_source_group_ids=proposal.held_out_source_group_ids,
    )
    protocol_sha = representation_protocol_sha256 or source_projection_protocol_sha256(
        fields=fields,
        forbidden_json_pointers=("/outcome",),
        forbidden_model_visible_exact_strings=forbidden_strings,
        outcome_information_availability=OutcomeInformationAvailability.WITHHELD,
        maximum_projection_bytes_per_item=2 * 1_048_576,
        maximum_total_projection_bytes=32 * 1_048_576,
    )
    selection_plan = plan_reference_selection_comparison_from_files(
        mining_run_path=mining_run_path,
        mining_report_path=mining_report_path,
        source_admission_report_path=admission_path,
        evidence_root=root,
        source_links=tuple(
            ReferenceSelectionSourceLink(
                candidate_id=f"candidate-{name}", source_id=f"source-{name}"
            )
            for name in names
        ),
        comparison_id="h0-quality-vs-prestige-v1",
        project_id="h0-project",
        report_output_locator="outputs/h0/H0_SELECTION.json",
        metadata_snapshot_year=2026,
        minimum_observed_prestige_fraction=1.0,
        stable_tie_break_salt_sha256="a" * 64,
        target_source_count=2,
        downstream=ReferenceSelectionDownstreamEnvelope(
            held_out_decision_set_sha256="8" * 64,
            representation_protocol_sha256=protocol_sha,
            execution_protocol_sha256="b" * 64,
            sources_per_condition=2,
            per_source_context_token_ceiling=2_000,
            total_context_token_ceiling=4_000,
        ),
        created_at=NOW + timedelta(hours=4),
    )
    selection_plan_path = root / "controls/reference-selection-plan.json"
    assert selection_plan.ready_for_owner_approval, selection_plan.blocker_codes
    save_reference_selection_plan(selection_plan, selection_plan_path)
    selection_plan_inspection = load_reference_selection_plan(selection_plan_path)
    selection_approval = approve_reference_selection_comparison(
        selection_plan_inspection,
        confirmed_plan_sha256=selection_plan.plan_sha256,
        approved_by="h0-owner",
        approved_at=NOW + timedelta(hours=5),
    )
    selection_approval_path = root / "controls/reference-selection-approval.json"
    save_reference_selection_approval(selection_approval, selection_approval_path)
    selection_report = freeze_reference_selection_comparison(
        selection_plan_inspection,
        load_reference_selection_approval(selection_approval_path),
        workspace_root=root,
    )
    selection_report_path = root / selection_plan.report_output_locator
    save_reference_selection_report(selection_report, selection_report_path)
    return {
        "request": request_path,
        "receipt": receipt_path,
        "audit": audit_path,
        "admission_proposal": proposal_path,
        "admission_report": admission_path,
        "selection_report": selection_report_path,
        "fields": fields,
    }
