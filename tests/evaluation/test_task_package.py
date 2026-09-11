from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    BenchmarkTaskPackageManifest,
    ReadinessStatus,
    ScientificEndpointKind,
    TaskPackageAcquisition,
    TaskPackageFile,
    TaskPackageFileRole,
    TaskPackageRequirement,
    TaskPackageRequirementEvidence,
    TaskSignalKind,
    inspect_task_package,
    load_external_resource_corpus,
    load_task_selection_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "docs/research/data/mlr_bench_official_ten_candidate_v2.yaml"
CORPUS = ROOT / "docs/research/data/autoresearch_evaluation_resources_v2.yaml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    selection_path = tmp_path / "selection.yaml"
    shutil.copyfile(SELECTION, selection_path)
    selection = load_task_selection_manifest(selection_path)
    selected = selection.manifest.tasks[0]

    package = tmp_path / "task-package"
    package.mkdir()
    brief = package / "task.md"
    brief.write_text("# Frozen research brief\n", encoding="utf-8")
    evidence = tmp_path / "qualification.json"
    evidence.write_text('{"status":"verified"}\n', encoding="utf-8")
    approval = tmp_path / "owner-approval.json"
    approval.write_text('{"approved":true}\n', encoding="utf-8")
    receipt = tmp_path / "acquisition-receipt.json"
    receipt.write_text('{"transport":"fixture"}\n', encoding="utf-8")
    evidence_sha = _sha(evidence)

    requirements = {
        requirement: TaskPackageRequirementEvidence(
            status=ReadinessStatus.VERIFIED,
            summary=f"Verified {requirement.value} fixture.",
            evidence_ref="qualification.json",
            evidence_sha256=evidence_sha,
        )
        for requirement in TaskPackageRequirement
    }
    manifest = BenchmarkTaskPackageManifest(
        package_id="mlr-task-fixture-v1",
        authorization_scope="local-inspection-only",
        selection_manifest_ref="selection.yaml",
        selection_manifest_sha256=selection.file_sha256,
        selection_proposal_sha256=selection.manifest.proposal_sha256,
        selection_id=selection.manifest.selection_id,
        task_id=selected.task_id,
        source_group=selected.source_group,
        benchmark_resource_id=selection.manifest.benchmark_resource_id,
        repository_commit=selection.manifest.repository_commit,
        dataset_id=selection.manifest.dataset_id,
        dataset_revision=selection.manifest.dataset_revision,
        upstream_locator=selected.upstream_locator,
        package_root="task-package",
        held_out_against_project=selection.manifest.held_out_against_project,
        source_group_disjoint=True,
        signal_kind=TaskSignalKind.RESEARCH_PACKAGE_REVIEW,
        primary_endpoint=ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE,
        objective_task_score_available=False,
        inventory=(
            TaskPackageFile(
                relative_path="task.md",
                role=TaskPackageFileRole.STARTING_BRIEF,
                byte_size=brief.stat().st_size,
                sha256=_sha(brief),
            ),
        ),
        acquisition=TaskPackageAcquisition(
            source_locator=selected.upstream_locator,
            starting_brief_sha256=_sha(brief),
            method="owner-approved-manual",
            acquired_at="2026-09-11T00:00:00Z",
            acquired_by="test-owner",
            owner_approval_ref="owner-approval.json",
            owner_approval_sha256=_sha(approval),
            receipt_ref="acquisition-receipt.json",
            receipt_sha256=_sha(receipt),
        ),
        requirements=requirements,
    )
    return manifest, selection, load_external_resource_corpus(CORPUS).corpus


def test_exact_package_is_revision_ready_but_cannot_authorize_a_run(tmp_path: Path) -> None:
    manifest, selection, corpus = _fixture(tmp_path)

    report = inspect_task_package(manifest, selection, corpus, source_root=tmp_path)

    assert report.ready_for_resource_revision_review is True
    assert report.ready_for_prelaunch_binding is False
    assert report.observed_file_count == 1
    assert report.observed_total_bytes > 0
    assert set(report.resource_revision_candidates) == set(TaskPackageRequirement)
    assert report.pending_selection_updates == (
        "held_out_audit_status",
        f"{manifest.task_id}:upstream_license_status",
        f"{manifest.task_id}:executable_signal_status",
    )
    assert report.resource_gate_blockers
    assert report.authorizes_download is False
    assert report.authorizes_execution is False
    assert report.no_download_performed_by_inspection is True


def test_hash_drift_and_extra_file_fail_closed(tmp_path: Path) -> None:
    manifest, selection, corpus = _fixture(tmp_path)
    (tmp_path / "task-package/task.md").write_text("drift\n", encoding="utf-8")
    (tmp_path / "task-package/unregistered.txt").write_text("extra\n", encoding="utf-8")

    report = inspect_task_package(manifest, selection, corpus, source_root=tmp_path)

    assert report.ready_for_resource_revision_review is False
    codes = {finding.code for finding in report.blockers}
    assert "inventory_size_mismatch:task_md" in codes
    assert "inventory_unexpected:unregistered_txt" in codes


def test_symlink_and_cross_selection_task_are_rejected(tmp_path: Path) -> None:
    manifest, selection, corpus = _fixture(tmp_path)
    brief = tmp_path / "task-package/task.md"
    brief.unlink()
    brief.symlink_to(tmp_path / "qualification.json")
    crossed = manifest.model_copy(update={"task_id": "not-selected"})

    report = inspect_task_package(crossed, selection, corpus, source_root=tmp_path)

    codes = {finding.code for finding in report.blockers}
    assert "package_symlink_forbidden" in codes
    assert "unknown_selected_task" in codes


def test_manifest_requires_a_complete_evidence_matrix(tmp_path: Path) -> None:
    manifest, _, _ = _fixture(tmp_path)
    payload = manifest.model_dump(mode="json")
    del payload["requirements"][TaskPackageRequirement.RUNTIME_POLICY.value]

    with pytest.raises(ValidationError, match="requirement matrix must be complete"):
        BenchmarkTaskPackageManifest.model_validate(payload)


def test_task_package_cli_reports_no_run_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, _, _ = _fixture(tmp_path)
    manifest_path = tmp_path / "task-package.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    status = main(
        [
            "evaluation",
            "task-package",
            "--manifest",
            str(manifest_path),
            "--selection",
            str(tmp_path / "selection.yaml"),
            "--resource-corpus",
            str(CORPUS),
            "--source-root",
            str(tmp_path),
            "--require-binding-ready",
        ]
    )

    assert status == 1
    output = capsys.readouterr().out
    assert '"ready_for_resource_revision_review": true' in output
    assert '"ready_for_prelaunch_binding": false' in output
    assert '"authorizes_execution": false' in output
