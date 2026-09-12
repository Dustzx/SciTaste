from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from scitaste.evaluation.json_content_audit import (
    JsonContentAuditItemReport,
    JsonContentAuditReport,
    JsonIdentityStatus,
    save_json_content_audit_report,
)
from scitaste.evaluation.source_admission import (
    SourceAdmissionEntry,
    SourceAdmissionInspection,
    SourceAdmissionProposal,
    SourceAdmissionVerdict,
    SourceIsolationArgument,
    SourceQualityArgument,
    SourceQualityDimensionReview,
    SourceQualityReview,
    SourceRightsArgument,
    inspect_source_admission,
    load_source_admission_proposal,
)
from scitaste.evaluation.taste_corpus_pair import TasteCorpusFileBinding
from scitaste.taste.reference_quality import (
    ReferenceQualityDimension,
    ReferenceQualityQualification,
    ReferenceQualityRating,
    ReferenceQualityVerdict,
    save_reference_quality_qualification,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _binding(root: Path, name: str, content: bytes) -> TasteCorpusFileBinding:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return TasteCorpusFileBinding(path=name, sha256=_sha(content))


def _audit_item(item_id: str) -> JsonContentAuditItemReport:
    content_sha = _sha(item_id.encode())
    return JsonContentAuditItemReport(
        item_id=item_id,
        destination=f"{item_id}.json",
        receipt_size_bytes=len(item_id),
        receipt_sha256=content_sha,
        observed_size_bytes=len(item_id),
        observed_sha256=content_sha,
        exact_bytes_verified=True,
        utf8_verified=True,
        json_verified=True,
        top_level_object_verified=True,
        structural_bounds_verified=True,
        identity_status=JsonIdentityStatus.MATCH,
        identity_observations=(),
        field_observations=(),
        total_nodes=1,
        maximum_observed_depth=0,
        external_locator_count=0,
        blocker_codes=(),
    )


def _audit(root: Path) -> tuple[TasteCorpusFileBinding, JsonContentAuditReport]:
    items = (_audit_item("2401.00001"), _audit_item("2401.00002"))
    report = JsonContentAuditReport(
        approval_id="aaar-content-audit-v1",
        approval_sha256="a" * 64,
        project_id="scitaste-self-development",
        request_id="aaar-rights-pilot-v1",
        request_sha256="b" * 64,
        receipt_sha256="c" * 64,
        auditor_id="scitaste-json-content-audit-v1",
        auditor_implementation_sha256="d" * 64,
        audited_at=datetime(2026, 9, 12, tzinfo=UTC),
        item_count=2,
        observed_total_bytes=sum(item.observed_size_bytes for item in items),
        exact_inventory_verified=True,
        exact_bytes_verified=True,
        all_json_verified=True,
        all_structural_bounds_verified=True,
        all_embedded_identities_verified=True,
        ready_for_source_admission_proposal=True,
        items=items,
        blocker_codes=(),
    )
    path = root / "audit.json"
    save_json_content_audit_report(report, path)
    return TasteCorpusFileBinding(path="audit.json", sha256=_sha(path.read_bytes())), report


def _entry(
    root: Path,
    item_id: str,
    *,
    source_group: str,
    admitted: bool,
) -> tuple[SourceAdmissionEntry, tuple[SourceQualityReview, ...]]:
    rights = _binding(root, f"evidence/{item_id}-rights.txt", b"rights")
    quality = _binding(root, f"evidence/{item_id}-quality.txt", b"quality")
    isolation = _binding(root, f"evidence/{item_id}-isolation.txt", b"isolation")
    content_sha = _sha(item_id.encode())
    entry = SourceAdmissionEntry(
        item_id=item_id,
        source_id=f"source-{item_id.replace('.', '-')}",
        curator_id="curator-1",
        title=f"Source {item_id}",
        locator=f"https://arxiv.org/abs/{item_id}",
        source_content_sha256=content_sha,
        rights=SourceRightsArgument(
            evidence=rights,
            license_id="CC-BY-4.0",
            attribution="Authors and title",
            permits_research_analysis=admitted,
            permits_derived_abstraction=admitted,
            pre_body_screen_consistent=admitted,
        ),
        quality=SourceQualityArgument(
            evidence=quality,
            quality_tier="peer-reviewed-primary",
            venue_or_source="ICLR",
            publication_year=2025,
            primary_scientific_record=True,
            decision_process_observable=True,
            quality_rationale="Contains a traceable scientific decision and evidence.",
        ),
        isolation=SourceIsolationArgument(
            evidence=isolation,
            source_group_id=source_group,
            checked_against_held_out_cases=True,
            checked_against_self_development_evidence=True,
            checked_at=datetime(2026, 9, 12, tzinfo=UTC),
        ),
    )
    reviews = tuple(
        SourceQualityReview(
            review_id=f"review-{item_id.replace('.', '-')}-{index}",
            item_id=item_id,
            reviewer_id=f"reviewer-{index}",
            source_content_sha256=content_sha,
            quality_evidence_sha256=quality.sha256,
            verdict=(SourceAdmissionVerdict.ADMIT if admitted else SourceAdmissionVerdict.REJECT),
            scientific_rigor_supported=admitted,
            decision_traceability_supported=admitted,
            transferable_taste_supported=admitted,
            expertise_scope="machine learning research methodology",
            rationale="The source is suitable." if admitted else "Rights are unresolved.",
        )
        for index in (1, 2)
    )
    return entry, reviews


def _inspection(root: Path, *, omit_second: bool = False) -> SourceAdmissionInspection:
    audit_binding, audit = _audit(root)
    admitted, admitted_reviews = _entry(
        root,
        "2401.00001",
        source_group="group-admitted",
        admitted=True,
    )
    rejected, rejected_reviews = _entry(
        root,
        "2401.00002",
        source_group="held-out-group",
        admitted=False,
    )
    entries = (admitted,) if omit_second else (admitted, rejected)
    reviews = admitted_reviews if omit_second else (*admitted_reviews, *rejected_reviews)
    proposal = SourceAdmissionProposal(
        proposal_id="aaar-source-admission-v1",
        project_id=audit.project_id,
        request_id=audit.request_id,
        request_sha256=audit.request_sha256,
        receipt_sha256=audit.receipt_sha256,
        content_audit_report=audit_binding,
        content_audit_report_sha256=audit.report_sha256,
        minimum_admitted_sources=1,
        held_out_source_group_ids=("held-out-group",),
        self_development_source_group_ids=("self-evidence",),
        forbidden_source_content_sha256=(),
        entries=entries,
        quality_reviews=reviews,
    )
    return SourceAdmissionInspection(
        path=root / "proposal.yaml",
        file_sha256="e" * 64,
        proposal=proposal,
    )


def test_source_admission_retains_rejections_and_opens_only_projection_proposal(
    tmp_path: Path,
) -> None:
    inspection = _inspection(tmp_path)
    inspection.path.write_text(inspection.proposal.model_dump_json(indent=2) + "\n")
    report = inspect_source_admission(
        load_source_admission_proposal(inspection.path),
        evidence_root=tmp_path,
    )

    assert report.admitted_source_ids == ("source-2401-00001",)
    assert report.rejected_source_ids == ("source-2401-00002",)
    assert report.ready_for_projection_proposal is True
    assert report.no_source_content_read is True
    assert report.authorizes_projection is False
    assert report.authorizes_execution is False
    assert report.items[1].source_isolation_supported is False


def test_source_admission_rejects_post_audit_population_cherry_picking(tmp_path: Path) -> None:
    report = inspect_source_admission(
        _inspection(tmp_path, omit_second=True),
        evidence_root=tmp_path,
    )

    assert report.ready_for_projection_proposal is False
    assert [finding.code for finding in report.blockers] == ["audited_population_mismatch"]


def test_v11_requires_prestige_blind_quality_trace_and_anchored_human_reviews(
    tmp_path: Path,
) -> None:
    inspection = _inspection(tmp_path)
    entries = []
    reviews = []
    for entry in inspection.proposal.entries:
        admitted = entry.isolation.source_group_id != "held-out-group"
        projection = _binding(
            tmp_path,
            f"quality/{entry.item_id}-blind-projection.json",
            b'{"prestige":"hidden"}',
        )
        ledger = _binding(
            tmp_path,
            f"projects/quality/runs/{entry.item_id}/model_nodes/ledger/00000000.json",
            b'{"fixture":"bound-ledger"}',
        )
        proposal_sha = _sha(f"proposal-{entry.item_id}".encode())
        qualification = ReferenceQualityQualification(
            screening_id=f"screen-{entry.item_id.replace('.', '-')}",
            source_id=entry.source_id,
            source_content_sha256=entry.source_content_sha256,
            source_projection_sha256=projection.sha256,
            proposal_sha256=proposal_sha,
            verdict=(
                ReferenceQualityVerdict.QUALIFY if admitted else ReferenceQualityVerdict.REJECT
            ),
            qualified_for_human_review=admitted,
            invocation_id=f"quality-{entry.item_id.replace('.', '-')}",
            backend="fixture-provider",
            model="fixture-model",
            ledger_locator=ledger.path,
            ledger_sha256=ledger.sha256,
        )
        report_path = tmp_path / f"quality/{entry.item_id}-qualification.json"
        save_reference_quality_qualification(qualification, report_path)
        report_binding = TasteCorpusFileBinding(
            path=report_path.relative_to(tmp_path).as_posix(),
            sha256=_sha(report_path.read_bytes()),
        )
        entries.append(
            entry.model_copy(
                update={
                    "quality": entry.quality.model_copy(
                        update={
                            "blind_projection": projection,
                            "reference_quality_report": report_binding,
                            "reference_quality_proposal_sha256": proposal_sha,
                        }
                    )
                }
            )
        )
        rating = ReferenceQualityRating.STRONG if admitted else ReferenceQualityRating.INSUFFICIENT
        for review in (
            item for item in inspection.proposal.quality_reviews if item.item_id == entry.item_id
        ):
            reviews.append(
                review.model_copy(
                    update={
                        "dimension_reviews": tuple(
                            SourceQualityDimensionReview(dimension=dimension, rating=rating)
                            for dimension in ReferenceQualityDimension
                        ),
                        "reviewer_visible_projection_sha256": projection.sha256,
                        "blinded_to_prestige_signals": True,
                        "blinded_to_model_assessment": True,
                    }
                )
            )
    proposal = SourceAdmissionProposal.model_validate(
        inspection.proposal.model_dump(mode="json", exclude={"proposal_sha256"})
        | {
            "schema_version": "1.1",
            "entries": [item.model_dump(mode="json") for item in entries],
            "quality_reviews": [item.model_dump(mode="json") for item in reviews],
        }
    )

    report = inspect_source_admission(
        SourceAdmissionInspection(
            path=tmp_path / "v11-proposal.json",
            file_sha256="f" * 64,
            proposal=proposal,
        ),
        evidence_root=tmp_path,
    )

    assert report.schema_version == "1.1"
    assert report.no_source_content_read is False
    assert report.no_raw_source_body_read is True
    assert report.derived_quality_projection_read is True
    assert report.admitted_source_ids == ("source-2401-00001",)
    assert report.items[0].reference_quality_screen_verified is True
    assert report.items[1].reference_quality_screen_verified is False
    assert "reference_quality_screen_failed" in {
        finding.code for finding in report.items[1].blockers
    }
