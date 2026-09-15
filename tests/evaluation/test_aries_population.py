from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import scitaste.evaluation.taste_source_segmentation as segmentation_module
import scitaste.evaluation.taste_source_segmentation_protocol as protocol_module
from scitaste.evaluation import (
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    DatasetAcquisitionRequest,
    TasteSourceReviewRole,
    approve_dataset_acquisition_request,
    compile_taste_source_ai_calibration,
    compile_taste_source_segmentation_agreement,
    load_taste_source_ai_calibration_report,
    load_taste_source_decision_segmentation_run,
    load_taste_source_review_assignment_plan,
    load_taste_source_review_policy,
    load_taste_source_segmentation_agreement_report,
    load_taste_source_segmentation_request_pack,
    load_taste_source_segmentation_resolution_run,
    load_taste_source_segmentation_sample_manifest,
    materialize_aries_taste_population,
    materialize_dataset_acquisition,
    normalize_taste_source_ai_screen,
    normalize_taste_source_decision_segmentation,
    normalize_taste_source_segmentation_resolution,
    plan_taste_source_review_assignments,
    plan_taste_source_segmentation_sample,
    prepare_taste_source_review_campaign,
    prepare_taste_source_review_session,
    prepare_taste_source_segmentation_request_pack,
    publish_aries_taste_population_run,
    publish_taste_source_review_campaign_run,
    save_dataset_acquisition_request,
    save_taste_source_ai_calibration_report,
    save_taste_source_ai_screening_run,
    save_taste_source_decision_segmentation_run,
    save_taste_source_review_assignment_plan,
    save_taste_source_segmentation_agreement_report,
    save_taste_source_segmentation_resolution_run,
    save_taste_source_segmentation_sample_manifest,
    verify_taste_source_segmentation_sample_bindings,
)
from scitaste.evaluation.source_identity import canonical_openreview_source_group_id
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
    monkeypatch: pytest.MonkeyPatch,
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
    assert candidate["source_group_id"] == canonical_openreview_source_group_id("test-document")

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
    raw_segmentation = tmp_path / "raw-segmentation.json"
    raw_segmentation.write_text(
        json.dumps(
            {
                "input_boundary": {
                    "other_segmenter_outputs_read": False,
                    "private_item_map_read": False,
                    "population_outcomes_read": False,
                },
                "items": [
                    {
                        "campaign": "aries",
                        "review_item_id": item_id,
                        "segments": [
                            {
                                "verbatim_decision_text": scientific_item["review_comment"],
                                "primary_decision_family": "evidence",
                                "atomic_decision_statement": (
                                    "Strengthen the visible causal argument."
                                ),
                                "rationale": "The request concerns claim support.",
                                "uncertainty": "low",
                            }
                        ],
                        "residual_decision_bearing_text_possible": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    segmentation_rubric = tmp_path / "segmentation-rubric.yaml"
    segmentation_rubric.write_text("schema_version: '1.0'\n", encoding="utf-8")
    segmentation_sample = tmp_path / "segmentation-sample.yaml"
    segmentation_sample.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "sample_id": "aries-segmentation-sample-v1",
                "project_id": campaign.project_id,
                "selection_timing": "retrospective-pilot-binding",
                "selection_rationale": "Bind the exact test source item.",
                "sampling_algorithm": "fixed-test-item",
                "random_seed": None,
                "items": [
                    {
                        "campaign_id": campaign.campaign_id,
                        "review_item_id": item_id,
                    }
                ],
                "item_count": 1,
                "authority": {
                    "preregistered": False,
                    "confirmatory_calibration_authorized": False,
                    "scaled_execution_authorized": False,
                    "formal_evidence_eligible": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    exclusion_sample = tmp_path / "prospective-exclusion-sample.yaml"
    exclusion_sample.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "sample_id": "prior-unseen-exclusion-v1",
                "project_id": campaign.project_id,
                "selection_timing": "retrospective-pilot-binding",
                "selection_rationale": "Bind a prior item outside this test campaign.",
                "sampling_algorithm": "fixed-prior-item",
                "random_seed": None,
                "items": [
                    {
                        "campaign_id": "prior-campaign",
                        "review_item_id": "item-prior",
                    }
                ],
                "item_count": 1,
                "authority": {
                    "preregistered": False,
                    "confirmatory_calibration_authorized": False,
                    "scaled_execution_authorized": False,
                    "formal_evidence_eligible": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prospective_sample = plan_taste_source_segmentation_sample(
        sample_id="aries-prospective-segmentation-v1",
        campaign_paths=(campaign_root / "CAMPAIGN.json",),
        excluded_sample_paths=(exclusion_sample,),
        per_campaign_item_count=1,
        random_seed=20260915,
        locator_root=tmp_path,
    )
    assert prospective_sample.schema_version == "1.1"
    assert prospective_sample.selection_timing == "preregistered"
    assert prospective_sample.items[0].review_item_id == item_id
    assert prospective_sample.per_campaign_item_counts == {campaign.campaign_id: 1}
    assert prospective_sample.authority["scaled_execution_authorized"] is False
    group_disjoint_sample = plan_taste_source_segmentation_sample(
        sample_id="aries-source-group-prospective-segmentation-v1",
        campaign_paths=(campaign_root / "CAMPAIGN.json",),
        excluded_sample_paths=(exclusion_sample,),
        per_campaign_item_count=1,
        random_seed=20260915,
        locator_root=tmp_path,
        source_group_disjoint=True,
    )
    assert group_disjoint_sample.schema_version == "1.2"
    assert group_disjoint_sample.per_campaign_source_group_counts == {campaign.campaign_id: 1}
    assert group_disjoint_sample.maximum_items_per_source_group == 1
    assert group_disjoint_sample.source_group_ids_exposed_to_provider is False
    assert group_disjoint_sample.per_campaign_eligible_source_group_counts == {
        campaign.campaign_id: 1
    }
    assert group_disjoint_sample.per_campaign_sampling_fraction_micros == {
        campaign.campaign_id: 1_000_000
    }
    assert (
        group_disjoint_sample.uncertainty_estimand
        == "descriptive-calibration-superpopulation-work-model"
    )
    group_disjoint_sample_path = tmp_path / "group-disjoint-sample.yaml"
    save_taste_source_segmentation_sample_manifest(
        group_disjoint_sample,
        group_disjoint_sample_path,
    )
    prospective_sample_path = tmp_path / "prospective-sample.yaml"
    save_taste_source_segmentation_sample_manifest(
        prospective_sample,
        prospective_sample_path,
    )
    assert (
        load_taste_source_segmentation_sample_manifest(prospective_sample_path).sample.sample_sha256
        == prospective_sample.sample_sha256
    )
    assert (
        verify_taste_source_segmentation_sample_bindings(
            prospective_sample_path,
            locator_root=tmp_path,
        ).sample.sample_sha256
        == prospective_sample.sample_sha256
    )
    tampered_sample_payload = yaml.safe_load(prospective_sample_path.read_text(encoding="utf-8"))
    tampered_sample_payload["source_campaign_file_sha256s"][campaign.campaign_id] = "0" * 64
    tampered_sample_path = tmp_path / "prospective-sample-tampered.yaml"
    tampered_sample_path.write_text(
        yaml.safe_dump(tampered_sample_payload, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="campaign file hash drifted"):
        verify_taste_source_segmentation_sample_bindings(
            tampered_sample_path,
            locator_root=tmp_path,
        )
    with pytest.raises(ValueError, match="too few unseen items"):
        plan_taste_source_segmentation_sample(
            sample_id="aries-overlapping-prospective-segmentation-v1",
            campaign_paths=(campaign_root / "CAMPAIGN.json",),
            excluded_sample_paths=(segmentation_sample,),
            per_campaign_item_count=1,
            random_seed=20260915,
            locator_root=tmp_path,
        )
    protocol_stub = SimpleNamespace(
        project_id=campaign.project_id,
        protocol_id="aries-prospective-segmentation-protocol-v1",
        sample=SimpleNamespace(
            locator=prospective_sample_path.relative_to(tmp_path).as_posix(),
            file_sha256=hashlib.sha256(prospective_sample_path.read_bytes()).hexdigest(),
        ),
        segmentation_rubric=SimpleNamespace(
            locator=segmentation_rubric.relative_to(tmp_path).as_posix(),
            file_sha256=hashlib.sha256(segmentation_rubric.read_bytes()).hexdigest(),
        ),
        generation=SimpleNamespace(segmenter_shards=1, items_per_shard=1),
        model_condition=SimpleNamespace(
            provider_id="test-provider",
            requested_model_id="test-model",
        ),
    )
    inspection_stub = SimpleNamespace(
        protocol=protocol_stub,
        sample=prospective_sample,
        protocol_file_sha256="1" * 64,
        freeze_receipt_file_sha256="2" * 64,
    )
    monkeypatch.setattr(
        protocol_module,
        "inspect_taste_source_segmentation_protocol",
        lambda **_: inspection_stub,
    )
    request_pack_path, request_pack = prepare_taste_source_segmentation_request_pack(
        pack_id="aries-prospective-request-pack-v1",
        protocol_path=tmp_path / "unused-protocol.yaml",
        freeze_receipt_path=tmp_path / "unused-freeze.yaml",
        locator_root=tmp_path,
        output_dir=tmp_path / "request-pack",
        created_at=datetime(2026, 9, 15, 1, 0, tzinfo=UTC),
    )
    assert request_pack.request_count == 2
    assert request_pack.unique_item_count == 1
    assert request_pack.provider_contact_performed is False
    assert (
        load_taste_source_segmentation_request_pack(
            request_pack_path / "REQUEST_PACK.json"
        ).pack_sha256
        == request_pack.pack_sha256
    )
    request_payload = json.loads(
        next((request_pack_path / "requests").glob("*.json")).read_text(encoding="utf-8")
    )
    assert set(request_payload["items"][0]) == {
        "campaign_token",
        "review_item_id",
        "reviewed_abstract",
        "review_comment",
    }
    assert "article_title" not in request_payload["items"][0]
    assert (
        request_payload["rubric_file_sha256"]
        == hashlib.sha256(segmentation_rubric.read_bytes()).hexdigest()
    )
    assert request_payload["output_contract"]["required"] == ["items"]
    assert request_payload["output_contract"]["properties"]["items"]["minItems"] == 1
    raw_segmentation_payload = json.loads(raw_segmentation.read_text(encoding="utf-8"))
    raw_segmentation_payload.update(
        {
            "rubric_read": True,
            "sample_manifest_read": True,
            "rubric_file_sha256": hashlib.sha256(segmentation_rubric.read_bytes()).hexdigest(),
            "sample_sha256": (
                load_taste_source_segmentation_sample_manifest(
                    segmentation_sample
                ).sample.sample_sha256
            ),
        }
    )
    raw_segmentation.write_text(json.dumps(raw_segmentation_payload), encoding="utf-8")
    rubric_snapshot = segmentation_module.snapshot_taste_source_segmentation_rubric(
        segmentation_rubric,
        locator_root=tmp_path,
    )
    campaign_snapshot = segmentation_module.snapshot_taste_source_segmentation_campaign(
        campaign_root / "CAMPAIGN.json",
        locator_root=tmp_path,
    )
    group_boundary_snapshot = segmentation_module.snapshot_taste_source_segmentation_group_boundary(
        sample_inspection=load_taste_source_segmentation_sample_manifest(
            group_disjoint_sample_path
        ),
        sample_manifest_locator=group_disjoint_sample_path.relative_to(tmp_path).as_posix(),
        campaign_snapshots=(campaign_snapshot,),
        locator_root=tmp_path,
    )
    assert group_boundary_snapshot is not None
    assert group_boundary_snapshot.per_campaign_source_group_counts == {campaign.campaign_id: 1}
    sample_snapshot = load_taste_source_segmentation_sample_manifest(segmentation_sample)

    def reject_late_input_read(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("authorized input was reopened after snapshot")

    with monkeypatch.context() as snapshot_guard:
        snapshot_guard.setattr(
            segmentation_module,
            "snapshot_taste_source_segmentation_rubric",
            reject_late_input_read,
        )
        snapshot_guard.setattr(
            segmentation_module,
            "snapshot_taste_source_segmentation_campaign",
            reject_late_input_read,
        )
        segmentation = normalize_taste_source_decision_segmentation(
            raw_segmentation_path=raw_segmentation,
            campaign_paths=(),
            campaign_aliases={"aries": campaign.campaign_id},
            run_id="aries-decision-segmentation-v1",
            screener_id="ai-segmenter-1",
            invocation_id="ai-segmentation-invocation-1",
            runtime_surface="test-agent",
            model_identifier="unresolved-test-model",
            model_revision=None,
            exact_model_identity_bound=False,
            rubric_path=segmentation_rubric,
            sample_manifest_path=segmentation_sample,
            runtime_identity_sha256=None,
            completed_at=datetime(2026, 9, 14, 0, 7, tzinfo=UTC),
            locator_root=tmp_path,
            prevalidated_rubric_snapshot=rubric_snapshot,
            prevalidated_sample_inspection=sample_snapshot,
            prevalidated_sample_manifest_locator=segmentation_sample.relative_to(
                tmp_path
            ).as_posix(),
            prevalidated_campaign_snapshots=(campaign_snapshot,),
        )
    assert segmentation.source_item_count == 1
    assert segmentation.proposed_atomic_decision_count == 1
    assert segmentation.multiple_segment_item_count == 0
    assert segmentation.formal_evidence_eligible is False
    segmentation_path = tmp_path / "segmentation.json"
    save_taste_source_decision_segmentation_run(segmentation, segmentation_path)
    assert (
        load_taste_source_decision_segmentation_run(segmentation_path).run.run_sha256
        == segmentation.run_sha256
    )
    second_raw_segmentation = tmp_path / "raw-segmentation-b.json"
    second_raw_payload = json.loads(raw_segmentation.read_text(encoding="utf-8"))
    second_raw_payload["agent_run_nonce"] = "independent-agent-b"
    second_raw_segmentation.write_text(json.dumps(second_raw_payload), encoding="utf-8")
    second_segmentation = normalize_taste_source_decision_segmentation(
        raw_segmentation_path=second_raw_segmentation,
        campaign_paths=(campaign_root / "CAMPAIGN.json",),
        campaign_aliases={"aries": campaign.campaign_id},
        run_id="aries-decision-segmentation-v1-b",
        screener_id="ai-segmenter-2",
        invocation_id="ai-segmentation-invocation-2",
        runtime_surface="test-agent",
        model_identifier="unresolved-test-model",
        model_revision=None,
        exact_model_identity_bound=False,
        rubric_path=segmentation_rubric,
        sample_manifest_path=segmentation_sample,
        runtime_identity_sha256=None,
        completed_at=datetime(2026, 9, 14, 0, 8, tzinfo=UTC),
        locator_root=tmp_path,
    )
    second_segmentation_path = tmp_path / "segmentation-b.json"
    save_taste_source_decision_segmentation_run(second_segmentation, second_segmentation_path)
    group_updates = {
        "schema_version": "1.1",
        "sample_manifest_locator": group_disjoint_sample_path.relative_to(tmp_path).as_posix(),
        "sample_manifest_file_sha256": hashlib.sha256(
            group_disjoint_sample_path.read_bytes()
        ).hexdigest(),
        "sample_sha256": group_disjoint_sample.sample_sha256,
        "sample_selection_timing": "preregistered",
    }
    group_segmentation_a_path = tmp_path / "group-segmentation-a.json"
    group_segmentation_b_path = tmp_path / "group-segmentation-b.json"
    save_taste_source_decision_segmentation_run(
        segmentation.model_copy(update=group_updates),
        group_segmentation_a_path,
    )
    save_taste_source_decision_segmentation_run(
        second_segmentation.model_copy(update=group_updates),
        group_segmentation_b_path,
    )
    with monkeypatch.context() as snapshot_guard:
        snapshot_guard.setattr(
            segmentation_module,
            "load_taste_source_segmentation_sample_manifest",
            reject_late_input_read,
        )
        snapshot_guard.setattr(
            segmentation_module,
            "verify_taste_source_segmentation_sample_bindings",
            reject_late_input_read,
        )
        snapshot_guard.setattr(
            segmentation_module,
            "load_taste_source_review_private_map",
            reject_late_input_read,
        )
        group_agreement = compile_taste_source_segmentation_agreement(
            report_id="aries-group-snapshot-agreement-v1",
            segmentation_paths=(group_segmentation_a_path, group_segmentation_b_path),
            compiled_at=datetime(2026, 9, 14, 0, 9, tzinfo=UTC),
            locator_root=tmp_path,
            prevalidated_group_boundary=group_boundary_snapshot,
        )
    assert group_agreement.group_uncertainty is not None
    mismatched_rubric_segmentation = second_segmentation.model_copy(
        update={
            "rubric_locator": "different-rubric.yaml",
            "rubric_file_sha256": "a" * 64,
            "task_instruction_sha256": "a" * 64,
        }
    )
    mismatched_rubric_path = tmp_path / "segmentation-different-rubric.json"
    save_taste_source_decision_segmentation_run(
        mismatched_rubric_segmentation, mismatched_rubric_path
    )
    with pytest.raises(ValueError, match="different rubrics"):
        compile_taste_source_segmentation_agreement(
            report_id="aries-invalid-segmentation-agreement-v1",
            segmentation_paths=(segmentation_path, mismatched_rubric_path),
            compiled_at=datetime(2026, 9, 14, 0, 9, tzinfo=UTC),
            locator_root=tmp_path,
        )
    segmentation_agreement = compile_taste_source_segmentation_agreement(
        report_id="aries-decision-segmentation-agreement-v1",
        segmentation_paths=(segmentation_path, second_segmentation_path),
        compiled_at=datetime(2026, 9, 14, 0, 9, tzinfo=UTC),
        locator_root=tmp_path,
    )
    assert segmentation_agreement.all_items_exactly_agreed is True
    assert segmentation_agreement.exact_span_route_item_count == 1
    assert segmentation_agreement.adjudication_item_count == 0
    assert segmentation_agreement.distinct_agent_artifacts_verified is True
    assert segmentation_agreement.exact_span_f1_micros == 1_000_000
    assert segmentation_agreement.overlap_span_f1_micros == 1_000_000
    assert segmentation_agreement.scaled_execution_authorized is False
    assert segmentation_agreement.formal_evidence_eligible is False
    segmentation_agreement_path = tmp_path / "segmentation-agreement.json"
    save_taste_source_segmentation_agreement_report(
        segmentation_agreement, segmentation_agreement_path
    )
    assert (
        load_taste_source_segmentation_agreement_report(
            segmentation_agreement_path
        ).report.report_sha256
        == segmentation_agreement.report_sha256
    )
    raw_resolution = tmp_path / "raw-resolution.json"
    raw_resolution.write_text(
        json.dumps(
            {
                "input_boundary": {
                    "segmenter_outputs_read": True,
                    "private_item_map_read": False,
                    "population_outcomes_read": False,
                },
                "rubric_read": True,
                "rubric_file_sha256": hashlib.sha256(segmentation_rubric.read_bytes()).hexdigest(),
                "source_agreement_report_sha256": (segmentation_agreement.report_sha256),
                "items": [
                    {
                        "campaign_id": campaign.campaign_id,
                        "review_item_id": item_id,
                        "resolution_kind": "exact-dual-agent-agreement",
                        "source_blocker_codes": [],
                        "segments": [
                            {
                                "verbatim_decision_text": (scientific_item["review_comment"]),
                                "primary_decision_family": "evidence",
                                "atomic_decision_statement": (
                                    "Strengthen the visible causal argument."
                                ),
                                "rationale": "The request concerns claim support.",
                                "uncertainty": "low",
                            }
                        ],
                        "residual_decision_bearing_text_possible": False,
                        "resolution_rationale": (
                            "Copied deterministically from exact dual-agent agreement."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with monkeypatch.context() as snapshot_guard:
        snapshot_guard.setattr(
            segmentation_module,
            "snapshot_taste_source_segmentation_rubric",
            reject_late_input_read,
        )
        snapshot_guard.setattr(
            segmentation_module,
            "snapshot_taste_source_segmentation_campaign",
            reject_late_input_read,
        )
        resolution = normalize_taste_source_segmentation_resolution(
            raw_resolution_path=raw_resolution,
            agreement_path=segmentation_agreement_path,
            run_id="aries-decision-segmentation-resolution-v1",
            adjudicator_id="ai-adjudicator-1",
            invocation_id="ai-adjudication-invocation-1",
            runtime_surface="test-agent",
            model_identifier="unresolved-test-model",
            model_revision=None,
            exact_model_identity_bound=False,
            rubric_path=segmentation_rubric,
            runtime_identity_sha256=None,
            completed_at=datetime(2026, 9, 14, 0, 10, tzinfo=UTC),
            locator_root=tmp_path,
            prevalidated_rubric_snapshot=rubric_snapshot,
            prevalidated_campaign_snapshots=(campaign_snapshot,),
        )
    assert resolution.internal_pilot_resolution_complete is True
    assert resolution.internal_ai_screening_ready is False
    assert resolution.exact_agreement_item_count == 1
    assert resolution.ai_adjudicated_item_count == 0
    assert resolution.benchmark_admission_authorized is False
    resolution_path = tmp_path / "segmentation-resolution.json"
    save_taste_source_segmentation_resolution_run(resolution, resolution_path)
    assert (
        load_taste_source_segmentation_resolution_run(resolution_path).run.run_sha256
        == resolution.run_sha256
    )
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
