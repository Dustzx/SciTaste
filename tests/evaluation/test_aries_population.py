from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from scitaste.evaluation import (
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    DatasetAcquisitionRequest,
    approve_dataset_acquisition_request,
    materialize_aries_taste_population,
    materialize_dataset_acquisition,
    publish_aries_taste_population_run,
    save_dataset_acquisition_request,
)
from scitaste.generative_ui.intent import WorkspaceIntentResolver
from scitaste.generative_ui.workspace import ProjectProgressQuery, WorkspaceSurfaceFactory
from scitaste.project import ProjectManifest, ProjectRuntime


def _jsonl(*rows: dict[str, object]) -> bytes:
    return b"".join(
        json.dumps(row, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        for row in rows
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
    assert "review-taste-candidate-population" in {
        item.quick_intent_id for item in catalog.intents
    }
    assert snapshot.revision == 2
