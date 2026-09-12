from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest
from pydantic import ValidationError

import scitaste.evaluation.acquisition as acquisition_module
from scitaste.cli import main
from scitaste.evaluation import (
    AcquisitionApproval,
    AcquisitionEvidenceBinding,
    AcquisitionGateReport,
    DatasetAcquisitionRequest,
    approve_dataset_acquisition_request,
    inspect_dataset_acquisition_request,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
    materialize_dataset_acquisition,
    save_dataset_acquisition_request,
)

REQUEST_PATH = Path("configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml")
INNOVATOR_REQUEST_PATH = Path("configs/evaluation/acquisition/innovatorbench_task_metadata_v1.yaml")
EXP_REQUEST_PATH = Path("configs/evaluation/acquisition/expbench_task_metadata_v1.yaml")


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


def _approved_request(tmp_path: Path) -> DatasetAcquisitionRequest:
    request = _isolated_request(tmp_path)
    request = request.model_copy(
        update={
            "destination_root": f"downloads/{request.request_id}/raw",
        }
    )
    return approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="project-owner",
        approved_at=datetime(2026, 9, 12, 8, 0, tzinfo=UTC),
    )


def test_repository_request_is_exact_review_ready_and_unapproved(tmp_path: Path) -> None:
    request = _isolated_request(tmp_path)

    report = inspect_dataset_acquisition_request(request, workspace_root=tmp_path)

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


@pytest.mark.parametrize(
    ("path", "item_count", "maximum_bytes", "host"),
    [
        (INNOVATOR_REQUEST_PATH, 20, 5 * 1024 * 1024, "raw.githubusercontent.com"),
        (EXP_REQUEST_PATH, 1, 3 * 1024 * 1024, "huggingface.co"),
    ],
)
def test_iclr_metadata_requests_are_exact_no_run_owner_proposals(
    path: Path,
    item_count: int,
    maximum_bytes: int,
    host: str,
) -> None:
    request = load_dataset_acquisition_request(path).request

    report = inspect_dataset_acquisition_request(request, workspace_root=Path("."))

    assert report.item_count == item_count
    assert report.maximum_total_bytes == maximum_bytes
    assert report.source_hosts == (host,)
    assert report.ready_for_owner_approval is True
    assert report.download_authorized is False
    assert report.authorizes_ingestion is False
    assert report.authorizes_execution is False
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
    payload["items"][0]["source_url"] = payload["items"][0]["source_url"].replace(
        "raw.githubusercontent.com/", "raw.githubusercontent.com:444/"
    )
    with pytest.raises(ValidationError, match="standard HTTPS port"):
        DatasetAcquisitionRequest.model_validate(payload)

    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    payload["items"][0]["destination"] = "../task.md"
    with pytest.raises(ValidationError, match="normalized relative path"):
        DatasetAcquisitionRequest.model_validate(payload)

    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    payload["maximum_total_bytes"] -= 1
    with pytest.raises(ValidationError, match="sum of item ceilings"):
        DatasetAcquisitionRequest.model_validate(payload)


def test_gate_report_rejects_internally_inconsistent_summaries(tmp_path: Path) -> None:
    report = inspect_dataset_acquisition_request(
        _isolated_request(tmp_path),
        workspace_root=tmp_path,
    )
    mutations = (
        ("item_count", report.item_count + 1, "item count"),
        ("maximum_total_bytes", report.maximum_total_bytes - 1, "byte ceiling"),
        ("source_hosts", ["example.com"], "source hosts"),
        ("ready_for_owner_approval", False, "readiness"),
        ("download_authorized", True, "authorization"),
    )
    for field, value, message in mutations:
        payload = report.model_dump(mode="json")
        payload[field] = value
        with pytest.raises(ValidationError, match=message):
            AcquisitionGateReport.model_validate(payload)


def test_approval_is_hash_bound_and_saved_without_downloading(tmp_path: Path) -> None:
    request = _isolated_request(tmp_path)
    with pytest.raises(ValueError, match="does not match"):
        approve_dataset_acquisition_request(
            request,
            confirmed_request_sha256="0" * 64,
            approved_by="project-owner",
            approved_at=datetime(2026, 9, 12, 8, 0, tzinfo=UTC),
        )

    approved = approve_dataset_acquisition_request(
        request,
        confirmed_request_sha256=request.request_sha256,
        approved_by="project-owner",
        approved_at=datetime(2026, 9, 12, 8, 0, tzinfo=UTC),
    )
    output = tmp_path / "approved.yaml"
    save_dataset_acquisition_request(approved, output)
    loaded = load_dataset_acquisition_request(output).request

    assert loaded.request_sha256 == request.request_sha256
    assert loaded.approval.approved is True
    assert loaded.authorizes_ingestion is False
    assert loaded.authorizes_execution is False
    assert not (tmp_path / request.destination_root).exists()
    with pytest.raises(FileExistsError):
        save_dataset_acquisition_request(approved, output)


def test_approved_download_is_atomic_content_addressed_and_non_executing(
    tmp_path: Path,
) -> None:
    approved = _approved_request(tmp_path)
    bodies = {item.source_url: f"# {item.item_id}\n".encode() for item in approved.items}

    receipt = materialize_dataset_acquisition(
        approved,
        workspace_root=tmp_path,
        confirmed_request_sha256=approved.request_sha256,
        allow_network_download=True,
        fetcher=lambda url, _ceiling, _media_type: bodies[url],
        acquired_at=datetime(2026, 9, 12, 8, 30, tzinfo=UTC),
    )

    transaction_root = tmp_path / PurePosixPath(approved.destination_root).parent
    raw_root = tmp_path / approved.destination_root
    loaded = load_dataset_acquisition_receipt(transaction_root / "RECEIPT.json")
    assert loaded.receipt == receipt
    assert receipt.item_count == 10
    assert receipt.total_bytes == sum(len(value) for value in bodies.values())
    assert receipt.acquisition_complete is True
    assert receipt.redirects_followed is False
    assert receipt.overwrote_existing_files is False
    assert receipt.authorizes_ingestion is False
    assert receipt.authorizes_execution is False
    assert {path.name for path in raw_root.iterdir()} == {
        item.destination for item in approved.items
    }
    assert all(
        (raw_root / item.destination).read_bytes() == bodies[item.source_url]
        for item in approved.items
    )

    receipt_path = transaction_root / "RECEIPT.json"
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["items"][0]["sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValidationError, match="receipt hash mismatch"):
        load_dataset_acquisition_receipt(receipt_path)


def test_download_requires_both_switch_and_authority_and_rolls_back_on_failure(
    tmp_path: Path,
) -> None:
    approved = _approved_request(tmp_path)
    calls = 0

    def failing_fetcher(url: str, ceiling: int, media_type: str) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("scripted transfer failure")
        return b"bounded\n"

    with pytest.raises(ValueError, match="explicit network-download switch"):
        materialize_dataset_acquisition(
            approved,
            workspace_root=tmp_path,
            confirmed_request_sha256=approved.request_sha256,
            allow_network_download=False,
            fetcher=failing_fetcher,
        )
    assert calls == 0

    unapproved = approved.model_copy(update={"approval": AcquisitionApproval()})
    with pytest.raises(ValueError, match="not authorized"):
        materialize_dataset_acquisition(
            unapproved,
            workspace_root=tmp_path,
            confirmed_request_sha256=unapproved.request_sha256,
            allow_network_download=True,
            fetcher=failing_fetcher,
        )
    assert calls == 0

    with pytest.raises(RuntimeError, match="scripted transfer failure"):
        materialize_dataset_acquisition(
            approved,
            workspace_root=tmp_path,
            confirmed_request_sha256=approved.request_sha256,
            allow_network_download=True,
            fetcher=failing_fetcher,
        )
    transaction_root = tmp_path / PurePosixPath(approved.destination_root).parent
    assert not transaction_root.exists()
    assert list(transaction_root.parent.glob(f".{approved.request_id}.*.staging")) == []


def test_default_https_fetch_is_bounded_and_rejects_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = (
        "https://raw.githubusercontent.com/example/repository/"
        "0123456789abcdef0123456789abcdef01234567/example.md"
    )

    class Response:
        status = 200

        def __init__(
            self,
            body: bytes,
            *,
            final_url: str,
            declared_length: int,
            content_encoding: str | None = None,
            content_type: str = "text/plain; charset=utf-8",
        ) -> None:
            self._stream = io.BytesIO(body)
            self._final_url = final_url
            self.headers = {
                "Content-Length": str(declared_length),
                "Content-Type": content_type,
            }
            if content_encoding is not None:
                self.headers["Content-Encoding"] = content_encoding

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def read(self, size: int) -> bytes:
            return self._stream.read(size)

        def geturl(self) -> str:
            return self._final_url

    class Opener:
        def __init__(self, response: Response) -> None:
            self.response = response

        def open(self, request, *, timeout: float):
            assert request.full_url == source_url
            assert request.headers["Accept-encoding"] == "identity"
            assert timeout == 30.0
            return self.response

    body = b"# pinned\n"
    monkeypatch.setattr(
        acquisition_module,
        "build_opener",
        lambda _handler: Opener(Response(body, final_url=source_url, declared_length=len(body))),
    )
    assert acquisition_module._fetch_https_bytes(source_url, 1024, "text/markdown") == body

    csv_body = b"task_id,paper_id\n1,1\n"
    monkeypatch.setattr(
        acquisition_module,
        "build_opener",
        lambda _handler: Opener(
            Response(
                csv_body,
                final_url=source_url,
                declared_length=len(csv_body),
                content_type="text/csv; charset=utf-8",
            )
        ),
    )
    assert acquisition_module._fetch_https_bytes(source_url, 1024, "text/csv") == csv_body

    monkeypatch.setattr(
        acquisition_module,
        "build_opener",
        lambda _handler: Opener(
            Response(body, final_url=f"{source_url}?redirected=1", declared_length=len(body))
        ),
    )
    with pytest.raises(ValueError, match="redirects are forbidden"):
        acquisition_module._fetch_https_bytes(source_url, 1024, "text/markdown")

    monkeypatch.setattr(
        acquisition_module,
        "build_opener",
        lambda _handler: Opener(Response(body, final_url=source_url, declared_length=1025)),
    )
    with pytest.raises(ValueError, match="declared byte ceiling"):
        acquisition_module._fetch_https_bytes(source_url, 1024, "text/markdown")

    monkeypatch.setattr(
        acquisition_module,
        "build_opener",
        lambda _handler: Opener(Response(body, final_url=source_url, declared_length=len(body))),
    )
    with pytest.raises(ValueError, match="approved media type"):
        acquisition_module._fetch_https_bytes(source_url, 1024, "application/json")

    monkeypatch.setattr(
        acquisition_module,
        "build_opener",
        lambda _handler: Opener(
            Response(
                body,
                final_url=source_url,
                declared_length=len(body),
                content_encoding="gzip",
            )
        ),
    )
    with pytest.raises(ValueError, match="content encoding"):
        acquisition_module._fetch_https_bytes(source_url, 1024, "text/markdown")


def test_acquisition_cli_materializes_only_a_no_network_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "REPORT.json"
    request = _isolated_request(tmp_path)
    manifest = tmp_path / "request.yaml"
    save_dataset_acquisition_request(request, manifest)

    assert (
        main(
            [
                "evaluation",
                "acquisition-request",
                "--manifest",
                str(manifest),
                "--workspace-root",
                str(tmp_path),
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


def test_acquisition_cli_separates_approval_from_network_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _isolated_request(tmp_path)
    request = request.model_copy(update={"destination_root": f"downloads/{request.request_id}/raw"})
    manifest = tmp_path / "request.yaml"
    approved_manifest = tmp_path / "approved.yaml"
    save_dataset_acquisition_request(request, manifest)

    assert (
        main(
            [
                "evaluation",
                "acquisition-approve",
                "--manifest",
                str(manifest),
                "--workspace-root",
                str(tmp_path),
                "--confirm-request-sha256",
                request.request_sha256,
                "--approved-by",
                "project-owner",
                "--approved-at",
                "2026-09-12T08:00:00+00:00",
                "--output",
                str(approved_manifest),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["download_authorized"] is True
    assert payload["download_performed"] is False
    assert payload["authorizes_ingestion"] is False
    assert not (tmp_path / request.destination_root).exists()

    with pytest.raises(SystemExit) as caught:
        main(
            [
                "evaluation",
                "acquisition-download",
                "--manifest",
                str(approved_manifest),
                "--workspace-root",
                str(tmp_path),
                "--confirm-request-sha256",
                request.request_sha256,
            ]
        )
    assert caught.value.code == 2
    assert "explicit network-download switch" in capsys.readouterr().err
