from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    AcquisitionApproval,
    AcquisitionEvidenceBinding,
    DatasetAcquisitionRequest,
    inspect_dataset_acquisition_request,
    load_dataset_acquisition_request,
)

REQUEST_PATH = Path("configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml")


def _isolated_request(tmp_path: Path) -> DatasetAcquisitionRequest:
    request = load_dataset_acquisition_request(REQUEST_PATH).request
    evidence = []
    for index, binding in enumerate(request.evidence):
        path = tmp_path / "evidence" / f"evidence-{index}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{binding.evidence_id}\n".encode()
        path.write_bytes(payload)
        evidence.append(
            AcquisitionEvidenceBinding(
                evidence_id=binding.evidence_id,
                path=f"evidence/evidence-{index}.txt",
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    return request.model_copy(
        update={
            "destination_root": "downloads/mlr-ten",
            "evidence": tuple(evidence),
        }
    )


def test_repository_request_is_exact_review_ready_and_unapproved() -> None:
    request = load_dataset_acquisition_request(REQUEST_PATH).request

    report = inspect_dataset_acquisition_request(request, workspace_root=".")

    assert report.item_count == 10
    assert report.maximum_total_bytes == 10 * 1024 * 1024
    assert report.source_hosts == ("raw.githubusercontent.com",)
    assert report.ready_for_owner_approval is True
    assert report.download_authorized is False
    assert report.blockers == ()
    assert [item.code for item in report.authorization_blockers] == ["owner-approval-required"]
    assert all(item.runtime_assets_included is False for item in report.items)
    assert report.no_network_access_performed is True
    assert report.no_download_performed is True


def test_exact_hash_approval_authorizes_download_only(tmp_path: Path) -> None:
    request = _isolated_request(tmp_path)
    approval = AcquisitionApproval(
        approved=True,
        request_sha256=request.request_sha256,
        approved_by="project-owner",
        approved_at=datetime(2026, 9, 11, 20, 0, tzinfo=UTC),
        scope="download-only-no-ingestion",
    )
    approved = request.model_copy(update={"approval": approval})

    report = inspect_dataset_acquisition_request(approved, workspace_root=tmp_path)

    assert report.ready_for_owner_approval is True
    assert report.download_authorized is True
    assert report.authorizes_ingestion is False
    assert report.authorizes_execution is False
    assert report.no_download_performed is True

    drifted = approved.model_copy(update={"purpose": f"{approved.purpose} Changed."})
    drift_report = inspect_dataset_acquisition_request(drifted, workspace_root=tmp_path)
    assert drift_report.download_authorized is False
    assert [item.code for item in drift_report.authorization_blockers] == ["approval-hash-mismatch"]


def test_existing_destination_and_evidence_drift_fail_closed(tmp_path: Path) -> None:
    request = _isolated_request(tmp_path)
    first = tmp_path / request.destination_root / request.items[0].destination
    first.parent.mkdir(parents=True)
    first.write_text("existing\n", encoding="utf-8")
    evidence = tmp_path / request.evidence[0].path
    evidence.write_text("drifted\n", encoding="utf-8")

    report = inspect_dataset_acquisition_request(request, workspace_root=tmp_path)

    codes = {item.code for item in report.blockers}
    assert f"destination:{request.items[0].item_id}:exists" in codes
    assert f"evidence:{request.evidence[0].evidence_id}:hash-mismatch" in codes
    assert report.ready_for_owner_approval is False
    assert report.download_authorized is False


def test_destination_cannot_escape_through_a_nested_symlink(tmp_path: Path) -> None:
    request = _isolated_request(tmp_path)
    destination_root = tmp_path / request.destination_root
    outside = tmp_path / "outside"
    destination_root.mkdir(parents=True)
    outside.mkdir()
    (destination_root / "escape").symlink_to(outside, target_is_directory=True)
    first = request.items[0].model_copy(update={"destination": "escape/task.md"})
    request = request.model_copy(update={"items": (first, *request.items[1:])})

    report = inspect_dataset_acquisition_request(request, workspace_root=tmp_path)

    assert f"destination:{first.item_id}:outside-root" in {item.code for item in report.blockers}
    assert report.ready_for_owner_approval is False
    assert report.download_authorized is False


def test_request_rejects_unpinned_hosts_paths_and_false_budget_arithmetic() -> None:
    request = load_dataset_acquisition_request(REQUEST_PATH).request
    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    payload["items"][0]["source_url"] = "https://example.com/task.md"
    with pytest.raises(ValidationError, match="immutable revision"):
        DatasetAcquisitionRequest.model_validate(payload)

    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    payload["items"][0]["destination"] = "../task.md"
    with pytest.raises(ValidationError, match="normalized relative path"):
        DatasetAcquisitionRequest.model_validate(payload)

    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    payload["maximum_total_bytes"] -= 1
    with pytest.raises(ValidationError, match="sum of item ceilings"):
        DatasetAcquisitionRequest.model_validate(payload)


def test_acquisition_cli_materializes_only_a_no_network_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "REPORT.json"

    assert (
        main(
            [
                "evaluation",
                "acquisition-request",
                "--manifest",
                str(REQUEST_PATH),
                "--workspace-root",
                ".",
                "--require-review-ready",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ready_for_owner_approval"] is True
    assert payload["download_authorized"] is False
    assert saved["items"][0]["item_id"] == "iclr2025_bi_align"
    assert saved["no_network_access_performed"] is True
    assert saved["no_dataset_file_created"] is True
