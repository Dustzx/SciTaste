from __future__ import annotations

import hashlib
import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scitaste.evaluation import (
    AcquiredItemReceipt,
    AcquisitionEvidenceBinding,
    AcquisitionItem,
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    SourceArchiveFileBinding,
    SourceArchivePlanItem,
    SourceArchiveQualificationPlan,
    approve_dataset_acquisition_request,
    approve_source_archive_read,
    inspect_source_archive_qualification_plan,
    qualify_source_archives,
    save_dataset_acquisition_request,
)
from scitaste.evaluation.prelaunch import ReadinessStatus

_COMMIT = "a" * 40
_NOW = datetime(2026, 9, 13, 4, 0, tzinfo=UTC)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_tar(path: Path, *, unsafe: bool) -> tuple[str, bytes]:
    root = f"Synthetic-{_COMMIT}"
    license_body = b"synthetic license\n"
    with tarfile.open(path, "w:gz") as package:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        package.addfile(directory)
        for member_path, body in (
            (f"{root}/LICENSE", license_body),
            (f"{root}/main.py", b"print('synthetic')\n"),
        ):
            member = tarfile.TarInfo(member_path)
            member.mode = 0o644
            member.size = len(body)
            package.addfile(member, io.BytesIO(body))
        if unsafe:
            escaped = tarfile.TarInfo("../escape.py")
            body = b"pass\n"
            escaped.mode = 0o644
            escaped.size = len(body)
            package.addfile(escaped, io.BytesIO(body))
            link = tarfile.TarInfo(f"{root}/linked")
            link.type = tarfile.SYMTYPE
            link.linkname = "/tmp/escape"
            package.addfile(link)
    return root, license_body


def _chain(tmp_path: Path, *, unsafe: bool) -> SourceArchiveQualificationPlan:
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("synthetic test evidence\n", encoding="utf-8")
    archive = tmp_path / "acquisitions" / "synthetic-source-v1" / "raw" / "source.tar.gz"
    archive.parent.mkdir(parents=True)
    root, license_body = _write_tar(archive, unsafe=unsafe)
    item = AcquisitionItem(
        item_id=_COMMIT,
        source_url=f"https://example.test/source/tar.gz/{_COMMIT}",
        source_revision=_COMMIT,
        destination="source.tar.gz",
        maximum_bytes=1024 * 1024,
        media_type="application/gzip",
        license_identifier="MIT",
        license_scope="Synthetic test fixture only.",
        license_status=ReadinessStatus.VERIFIED,
    )
    request = DatasetAcquisitionRequest(
        request_id="synthetic-source-v1",
        project_id="synthetic-project",
        track_id="source-qualification",
        authorization_scope="download-only-no-ingestion",
        purpose="Exercise the source archive qualification gate.",
        claim_boundary="Synthetic tests establish no external source claim.",
        selection_id="synthetic-selection-v1",
        selection_proposal_sha256="b" * 64,
        destination_root="acquisitions/synthetic-source-v1/raw",
        allowed_hosts=("example.test",),
        items=(item,),
        maximum_total_bytes=1024 * 1024,
        evidence=(
            AcquisitionEvidenceBinding(
                evidence_id="synthetic-evidence",
                path="evidence.txt",
                sha256=_sha256_file(evidence),
            ),
        ),
    )
    request = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=_NOW,
    )
    request_path = tmp_path / "approved-request.yaml"
    save_dataset_acquisition_request(request, request_path)
    archive_size = archive.stat().st_size
    archive_sha256 = _sha256_file(archive)
    receipt = DatasetAcquisitionReceipt.create(
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=_NOW,
        acquired_at=_NOW,
        approval_scope="download-only-no-ingestion",
        destination_root=request.destination_root,
        items=(
            AcquiredItemReceipt(
                item_id=_COMMIT,
                source_url=item.source_url,
                source_revision=_COMMIT,
                destination=item.destination,
                size_bytes=archive_size,
                sha256=archive_sha256,
            ),
        ),
        item_count=1,
        total_bytes=archive_size,
        maximum_total_bytes=request.maximum_total_bytes,
        source_hosts=("example.test",),
    )
    receipt_path = archive.parent.parent / "RECEIPT.json"
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return SourceArchiveQualificationPlan(
        plan_id="synthetic-source-plan-v1",
        project_id=request.project_id,
        purpose="Qualify a synthetic source archive without extraction.",
        claim_boundary="Synthetic qualification establishes no external source claim.",
        approved_acquisition_request=SourceArchiveFileBinding(
            path=request_path.relative_to(tmp_path).as_posix(),
            sha256=_sha256_file(request_path),
        ),
        acquisition_request_sha256=request.request_sha256,
        acquisition_receipt=SourceArchiveFileBinding(
            path=receipt_path.relative_to(tmp_path).as_posix(),
            sha256=_sha256_file(receipt_path),
        ),
        acquisition_receipt_sha256=receipt.receipt_sha256,
        items=(
            SourceArchivePlanItem(
                system_id="synthetic-system",
                acquisition_item_id=_COMMIT,
                source_commit=_COMMIT,
                archive=SourceArchiveFileBinding(
                    path=archive.relative_to(tmp_path).as_posix(),
                    sha256=archive_sha256,
                ),
                archive_size_bytes=archive_size,
                expected_root_directory=root,
                license_identifier="MIT",
                license_file_path=f"{root}/LICENSE",
                license_file_sha256=_sha256_bytes(license_body),
                maximum_members=20,
                maximum_expanded_bytes=1024 * 1024,
                maximum_regular_file_bytes=1024 * 1024,
                output_directory="synthetic-system",
            ),
        ),
        output_root="qualified/synthetic-source-plan-v1",
        maximum_total_expanded_bytes=1024 * 1024,
    )


def test_archive_read_requires_exact_approval_and_never_extracts(tmp_path: Path) -> None:
    plan = _chain(tmp_path, unsafe=False)
    inspection = inspect_source_archive_qualification_plan(plan, workspace_root=tmp_path)

    assert inspection.ready_for_owner_read_approval is True
    assert inspection.archive_content_read is False
    assert inspection.archive_byte_bindings_verified is True
    assert not (tmp_path / plan.output_root).exists()

    approval = approve_source_archive_read(
        plan,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=_NOW,
    )
    with pytest.raises(ValueError, match="explicit local-read switch"):
        qualify_source_archives(
            plan,
            approval,
            workspace_root=tmp_path,
            allow_local_archive_read=False,
            qualified_at=_NOW,
        )

    report = qualify_source_archives(
        plan,
        approval,
        workspace_root=tmp_path,
        allow_local_archive_read=True,
        qualified_at=_NOW,
    )

    assert report.all_archives_safe is True
    assert report.items[0].regular_file_count == 2
    assert report.items[0].tree_sha256 is not None
    assert report.archive_content_read is True
    assert report.extraction_performed is False
    assert report.authorizes_extraction is False
    assert not (tmp_path / plan.output_root).exists()


def test_unsafe_paths_and_links_fail_closed_without_extraction(tmp_path: Path) -> None:
    plan = _chain(tmp_path, unsafe=True)
    approval = approve_source_archive_read(
        plan,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="test-owner",
        approved_at=_NOW,
    )

    report = qualify_source_archives(
        plan,
        approval,
        workspace_root=tmp_path,
        allow_local_archive_read=True,
        qualified_at=_NOW,
    )

    assert report.all_archives_safe is False
    assert {finding.code for finding in report.items[0].findings} >= {
        "member-path-unsafe",
        "member-type-unsafe",
    }
    assert report.ready_for_extraction_proposal is False
    assert not (tmp_path / "escape.py").exists()
    assert not (tmp_path / plan.output_root).exists()
