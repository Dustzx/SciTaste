from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from scitaste.evaluation import (
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    DatasetAcquisitionRequest,
    TasteSourceReviewRole,
    approve_dataset_acquisition_request,
    compile_taste_source_ai_calibration,
    load_taste_source_ai_calibration_report,
    load_taste_source_review_assignment_plan,
    load_taste_source_review_policy,
    materialize_aries_taste_population,
    materialize_dataset_acquisition,
    normalize_taste_source_ai_screen,
    plan_taste_source_review_assignments,
    prepare_taste_source_review_campaign,
    prepare_taste_source_review_session,
    publish_aries_taste_population_run,
    publish_taste_source_review_campaign_run,
    save_dataset_acquisition_request,
    save_taste_source_ai_calibration_report,
    save_taste_source_ai_screening_run,
    save_taste_source_review_assignment_plan,
)
from scitaste.generative_ui.intent import WorkspaceIntentResolver
from scitaste.generative_ui.workspace import ProjectProgressQuery, WorkspaceSurfaceFactory
from scitaste.project import ProjectManifest, ProjectRuntime


def _jsonl(*rows: dict[str, object]) -> bytes:
    return b"".join(
        json.dumps(row, separators=(",", ":"), sort_keys=True).encode() + b"\n" for row in rows
    )


def _s2orc_archive() -> bytes:
    payloads = {
        "source-paper": {
            "paper_id": "source-paper",
            "abstract": "Contact author@example.org about the baseline.",
            "pdf_parse": {"body_text": [{"text": "The original argument."}]},
        },
        "target-paper": {
            "paper_id": "target-paper",
            "abstract": "The revised abstract.",
            "pdf_parse": {"body_text": [{"text": "The revised argument."}]},
        },
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for paper_id, value in payloads.items():
            raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            member = tarfile.TarInfo(f"s2orc/{paper_id}.json")
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def test_natural_aries_population_is_projected_without_becoming_benchmark(
    tmp_path: Path,
) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="aries-project",
            title="ARIES project",
            research_direction="Compile natural scientific Taste candidates.",
            status="active",
        )
    )
    bodies = {
        "license": b"ODC-BY-1.0\n",
        "review_comments": _jsonl(
            {
                "annotation": "manual",
                "comment": "Please strengthen contact@example.org's causal argument.",
                "comment_id": 0,
                "doc_id": "test-document",
            },
            {
                "annotation": "synthetic",
                "comment": "Generated advice must not enter the natural population.",
                "comment_id": 1,
                "doc_id": "test-document",
            },
        ),
        "paper_edits": _jsonl(
            {
                "doc_id": "test-document",
                "edits": [{"edit_id": 0, "source_idxs": [0], "target_idxs": [0]}],
                "source_pdf_id": "source-paper",
                "target_pdf_id": "target-paper",
            }
        ),
        "edit_labels_test": _jsonl(
            {"comment_id": 0, "doc_id": "test-document", "positive_edits": [0]}
        ),
        "alignment_human_eval": _jsonl(
            {
                "annotation": "human_eval",
                "comment": "Please strengthen the causal argument.",
                "comment_id": 0,
                "doc_id": "test-document",
                "positive_edits": [],
            }
        ),
        "split_ids": json.dumps(
            {
                "train": [],
                "dev": [],
                "test": [
                    {
                        "doc_id": "test-document",
                        "source_pdf_id": "source-paper",
                        "target_pdf_id": "target-paper",
                    }
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode(),
        "s2orc": _s2orc_archive(),
    }
    destinations = {
        "license": "LICENSE",
        "review_comments": "review_comments.jsonl",
        "paper_edits": "paper_edits.jsonl",
        "edit_labels_test": "edit_labels_test.jsonl",
        "alignment_human_eval": "alignment_human_eval.jsonl",
        "split_ids": "split_ids.json",
        "s2orc": "s2orc.tar.gz",
    }
    media_types = {
        "license": "text/plain",
        "review_comments": "application/x-ndjson",
        "paper_edits": "application/x-ndjson",
        "edit_labels_test": "application/x-ndjson",
        "alignment_human_eval": "application/x-ndjson",
        "split_ids": "application/json",
        "s2orc": "application/gzip",
    }
    evidence_path = tmp_path / "scope.txt"
    evidence_path.write_text("bounded synthetic fixture\n", encoding="utf-8")
    revision = "a" * 40
    items = tuple(
        AcquisitionItem(
            item_id=item_id,
            source_url=f"https://example.org/{item_id}/{revision}",
            source_revision=revision,
            destination=destinations[item_id],
            maximum_bytes=len(body),
            media_type=media_types[item_id],
            license_identifier="ODC-BY-1.0",
            license_scope="Test-only bounded fixture.",
            license_status="verified",
            expected_sha256=hashlib.sha256(body).hexdigest(),
        )
        for item_id, body in bodies.items()
    )
    request = DatasetAcquisitionRequest(
        request_id="aries-review-edit-population-v1",
        project_id="aries-project",
        track_id="scientific-taste-decisions",
        authorization_scope="download-only-no-ingestion",
        purpose="Compile a bounded natural review-to-revision candidate population.",
        claim_boundary="Observed revisions and alignments are not quality labels.",
        selection_id="aries-review-edit-acquisition-scope-v1",
        selection_proposal_sha256="1" * 64,
        destination_root=(
            "outputs/projects/aries-project/evaluations/acquisitions/"
            "aries-review-edit-population-v1/raw"
        ),
        allowed_hosts=("example.org",),
        items=items,
        maximum_total_bytes=sum(item.maximum_bytes for item in items),
        evidence=(
            AcquisitionEvidenceBinding(
                evidence_id="aries-scope",
                path="scope.txt",
                sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            ),
        ),
    )
    request = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    request_path = tmp_path / "request.yaml"
    save_dataset_acquisition_request(request, request_path)
    receipt = materialize_dataset_acquisition(
        request,
        workspace_root=tmp_path,
        confirmed_request_sha256=request.request_sha256,
        allow_network_download=True,
        fetcher=lambda url, _maximum, _media: next(
            body for item_id, body in bodies.items() if f"/{item_id}/" in url
        ),
        acquired_at=datetime(2026, 9, 14, 0, 1, tzinfo=UTC),
    )
    transaction = tmp_path / Path(request.destination_root).parent
    derived = transaction / "derived/taste-population-v1"
    report = materialize_aries_taste_population(
        approved_request_path=request_path,
        receipt_path=transaction / "RECEIPT.json",
        workspace_root=tmp_path,
        output_directory=derived,
        compiled_at=datetime(2026, 9, 14, 0, 2, tzinfo=UTC),
    )

    candidate = json.loads((derived / "CANDIDATES.jsonl").read_text(encoding="utf-8"))
    assert receipt.item_count == 7
    assert report.candidate_count == 1
    assert report.synthetic_review_row_count_excluded == 1
    assert report.alignment_disagreement_count == 1
    assert report.ready_for_benchmark_admission is False
    assert report.verification.route == "direct_path"
    assert report.standalone_preflight_performed is False
    assert "example.org" not in json.dumps(candidate)

    snapshot, _ = publish_aries_taste_population_run(
        runtime,
        project_id="aries-project",
        run_id="aries-natural-population-v1",
        source_report_path=derived / "REPORT.json",
        expected_revision=snapshot.revision,
    )
    surface = WorkspaceSurfaceFactory(runtime).build_surface(
        ProjectProgressQuery(project_id="aries-project")
    )
    board = next(
        component
        for component in surface.components
        if component.component == "ProjectProgressBoard"
    )
    assert board.data["taste_candidate_populations"][0]["candidate_count"] == 1
    catalog = WorkspaceIntentResolver(runtime).quick_catalog("aries-project")
    assert "review-taste-candidate-population" in {item.quick_intent_id for item in catalog.intents}
    assert snapshot.revision == 2

    policy = load_taste_source_review_policy(
        "configs/evaluation/human_review/aries_taste_source_review_v1.yaml"
    ).model_copy(update={"project_id": "aries-project", "minimum_eligible_groups_per_domain": 1})
    policy_path = tmp_path / "aries-review-policy.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            policy.model_dump(mode="json", exclude={"policy_sha256"}),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    campaign_root = transaction / "derived/taste-source-review-v1"
    campaign = prepare_taste_source_review_campaign(
        population_report_path=derived / "REPORT.json",
        policy_path=policy_path,
        output_dir=campaign_root,
        prepared_at=datetime(2026, 9, 14, 0, 3, tzinfo=UTC),
    )
    assert campaign.candidate_count == 1
    assert campaign.source_group_count == 1
    assert campaign.publisher_subject_group_counts == {"computing": 1}
    scientific_item = json.loads(
        (campaign_root / "SCIENTIFIC_ITEMS.jsonl").read_text(encoding="utf-8")
    )
    assert "observed_edits" not in scientific_item
    assert "alignment_status" not in scientific_item
    private_item = json.loads(
        (campaign_root / "PRIVATE_ITEM_MAP.json").read_text(encoding="utf-8")
    )["items"][0]
    assert private_item["publisher_subject"] == "computing"
    session_root = campaign_root / "scientific-session"
    session = prepare_taste_source_review_session(
        campaign_path=campaign_root / "CAMPAIGN.json",
        role=TasteSourceReviewRole.SCIENTIFIC,
        reviewer_identity_sha256="b" * 64,
        output_dir=session_root,
        prepared_at=datetime(2026, 9, 14, 0, 4, tzinfo=UTC),
    )
    assert len(session.items) == 1
    assert '<option value="computing">Computing</option>' in (
        session_root / "review.html"
    ).read_text(encoding="utf-8")
    assignment = plan_taste_source_review_assignments(
        plan_id="aries-source-review-assignment-v1",
        campaign_paths=(campaign_root / "CAMPAIGN.json",),
        created_at=datetime(2026, 9, 14, 0, 5, tzinfo=UTC),
        target_completion_at=datetime(2026, 9, 15, tzinfo=UTC),
        random_seed=20260914,
        locator_root=tmp_path,
        scientific_reviewer_slot_count=2,
        privacy_reviewer_slot_count=1,
    )
    assert assignment.required_scientific_assessment_count == 2
    assert assignment.required_privacy_assessment_count == 1
    assert assignment.scientific_slot_loads == {
        "scientific-01": 1,
        "scientific-02": 1,
    }
    assert assignment.privacy_slot_loads == {"privacy-01": 1}
    assert assignment.ai_screening_can_replace_human_evidence is False
    assignment_path = tmp_path / "assignment.json"
    save_taste_source_review_assignment_plan(assignment, assignment_path)
    assert (
        load_taste_source_review_assignment_plan(assignment_path).plan.plan_sha256
        == assignment.plan_sha256
    )
    assigned_session = prepare_taste_source_review_session(
        campaign_path=campaign_root / "CAMPAIGN.json",
        role=TasteSourceReviewRole.SCIENTIFIC,
        reviewer_identity_sha256="c" * 64,
        output_dir=campaign_root / "assigned-scientific-session",
        assigned_item_ids=tuple(
            item.review_item_id
            for item in next(
                batch
                for batch in assignment.batches
                if batch.role is TasteSourceReviewRole.SCIENTIFIC
            ).items
        ),
        prepared_at=datetime(2026, 9, 14, 0, 6, tzinfo=UTC),
    )
    assert len(assigned_session.items) == 1
    item_id = scientific_item["review_item_id"]
    quality_dimensions = {
        "evidential_rigor": "weak",
        "decision_traceability": "strong",
        "alternative_visibility": "strong",
        "failure_boundary_visibility": "weak",
        "transfer_potential": "strong",
    }
    raw_scientific_a = tmp_path / "raw-scientific-a.json"
    raw_scientific_b = tmp_path / "raw-scientific-b.json"
    raw_privacy = tmp_path / "raw-privacy.json"
    raw_scientific_a.write_text(
        json.dumps(
            {
                "input_boundary": {
                    "other_screener_outputs_read": False,
                    "private_item_map_read": False,
                    "population_outcomes_read": False,
                },
                "items": [
                    {
                        "campaign": "aries",
                        "review_item_id": item_id,
                        "domain_label": "computing",
                        "primary_decision_family": "experiment",
                        "quality_dimensions": quality_dimensions,
                        "transferable_taste_candidate": True,
                        "rationale": "The review requests a concrete comparator.",
                        "uncertainty": {
                            "level": "moderate",
                            "note": "The comparator family is visible.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    raw_scientific_b.write_text(
        json.dumps(
            {
                "input_boundary": {
                    "other_screener_outputs_read": False,
                    "private_item_map_read": False,
                    "population_outcomes_read": False,
                },
                "items": [
                    {
                        "campaign_id": campaign.campaign_id,
                        "review_item_id": item_id,
                        "domain_label": "computing",
                        "primary_decision_family": "experiment",
                        "quality_dimensions": quality_dimensions,
                        "transferable_taste_candidate": True,
                        "rationale": "The missing comparator is explicit.",
                        "uncertainty": "low: the requested action is explicit",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    raw_privacy.write_text(
        json.dumps(
            {
                "scope": {
                    "private_item_map_read": False,
                    "population_outcome_read": False,
                    "scientific_arm_outputs_read": False,
                },
                "items": [
                    {
                        "campaign": "aries",
                        "item_id": item_id,
                        "release_safe": False,
                        "risk_labels": ["publication_fingerprint"],
                        "redaction_notes": "Replace exact searchable text.",
                        "rationale": "The text can identify a public paper.",
                        "uncertainty": "high: release mode is unresolved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    campaign_paths = (campaign_root / "CAMPAIGN.json",)
    aliases = {"aries": campaign.campaign_id}
    normalized_paths: list[Path] = []
    for ordinal, raw_path in enumerate(
        (raw_scientific_a, raw_scientific_b),
        start=1,
    ):
        normalized = normalize_taste_source_ai_screen(
            raw_screen_path=raw_path,
            campaign_paths=campaign_paths,
            campaign_aliases=aliases,
            role=TasteSourceReviewRole.SCIENTIFIC,
            screen_id=f"aries-ai-scientific-{ordinal}",
            screener_id=f"ai-screener-{ordinal}",
            invocation_id=f"ai-science-invocation-{ordinal}",
            runtime_surface="test-agent",
            model_identifier="unresolved-test-model",
            model_revision=None,
            exact_model_identity_bound=False,
            task_instruction_sha256=None,
            runtime_identity_sha256=None,
            completed_at=datetime(2026, 9, 14, 0, 7 + ordinal, tzinfo=UTC),
            locator_root=tmp_path,
        )
        normalized_path = tmp_path / f"normalized-scientific-{ordinal}.json"
        save_taste_source_ai_screening_run(normalized, normalized_path)
        normalized_paths.append(normalized_path)
    normalized_privacy = normalize_taste_source_ai_screen(
        raw_screen_path=raw_privacy,
        campaign_paths=campaign_paths,
        campaign_aliases=aliases,
        role=TasteSourceReviewRole.PRIVACY,
        screen_id="aries-ai-privacy-1",
        screener_id="ai-privacy-1",
        invocation_id="ai-privacy-invocation-1",
        runtime_surface="test-agent",
        model_identifier="unresolved-test-model",
        model_revision=None,
        exact_model_identity_bound=False,
        task_instruction_sha256=None,
        runtime_identity_sha256=None,
        completed_at=datetime(2026, 9, 14, 0, 10, tzinfo=UTC),
        locator_root=tmp_path,
    )
    normalized_privacy_path = tmp_path / "normalized-privacy.json"
    save_taste_source_ai_screening_run(
        normalized_privacy,
        normalized_privacy_path,
    )
    release_governance_path = tmp_path / "release-governance.yaml"
    release_governance_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2.0",
                "policy_id": "aries-release-governance-v2",
                "project_id": "aries-project",
                "populations": [
                    {
                        "campaign_id": campaign.campaign_id,
                        "item_count": 1,
                        "release_mode": "controlled-internal-only",
                        "rights_scope": "unresolved",
                        "content_license_identifiers": [],
                        "public_reader_access_verified": False,
                        "source_attribution_preserved": False,
                        "exact_source_text_permitted": False,
                        "private_derivation_map_bound": False,
                        "redaction_manifest_bound": False,
                        "reidentification_screen_passed": False,
                        "rationale": "Synthetic fixture remains internal.",
                    }
                ],
                "internal_ai_screening_allowed": True,
                "public_release_requires_mode_specific_evidence": True,
                "source_blindness_is_not_deidentification": True,
                "database_license_is_not_item_content_license": True,
                "legal_or_ethics_determination_claimed": False,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    calibration = compile_taste_source_ai_calibration(
        report_id="aries-ai-calibration-v1",
        scientific_screen_paths=(normalized_paths[0], normalized_paths[1]),
        privacy_screen_path=normalized_privacy_path,
        compiled_at=datetime(2026, 9, 14, 0, 11, tzinfo=UTC),
        locator_root=tmp_path,
        release_governance_path=release_governance_path,
    )
    assert calibration.item_count == 1
    assert calibration.decision_family_agreement_count == 1
    assert calibration.release_unsafe_count == 1
    assert calibration.ready_for_scaled_ai_screening is False
    assert calibration.formal_evidence_eligible is False
    calibration_path = tmp_path / "ai-calibration.json"
    save_taste_source_ai_calibration_report(calibration, calibration_path)
    assert (
        load_taste_source_ai_calibration_report(calibration_path).report.report_sha256
        == calibration.report_sha256
    )
    snapshot, _ = publish_taste_source_review_campaign_run(
        runtime,
        project_id="aries-project",
        run_id="aries-source-review-v1",
        source_campaign_path=campaign_root / "CAMPAIGN.json",
        expected_revision=snapshot.revision,
    )
    surface = WorkspaceSurfaceFactory(runtime).build_surface(
        ProjectProgressQuery(project_id="aries-project")
    )
    board = next(
        component
        for component in surface.components
        if component.component == "ProjectProgressBoard"
    )
    review = board.data["taste_source_review_campaigns"][0]
    assert review["publisher_subject_group_counts"] == {"computing": 1}
    assert review["owner_approval_required"] is True
    assert snapshot.revision == 4
