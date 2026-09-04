from __future__ import annotations

from pathlib import Path

import pytest

from scitaste.generative_ui import EvidenceKind, ProjectSnapshotAdapter
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime_with_project(tmp_path: Path) -> tuple[ProjectRuntime, int]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="adapter-project",
            title="Adapter project",
            research_direction="Bind project artifacts to a trusted surface.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        "adapter-project",
        ProjectRun(
            run_id="2026-09-04__scripted__seed-07",
            provider="scripted",
            model="deterministic-controller",
            condition="full_scitaste",
            seed=7,
            status="complete",
            evidence_scope="engineering-only",
            stage_path="upstream_run",
        ),
        expected_revision=snapshot.revision,
    )
    run = tmp_path / "outputs/projects/adapter-project/runs/2026-09-04__scripted__seed-07"
    (run / "upstream_run/execution.json").write_text('{"status":"complete"}\n')
    snapshot = runtime.select_run(
        "adapter-project",
        "2026-09-04__scripted__seed-07",
        expected_revision=snapshot.revision,
    )

    paper_dir = tmp_path / "outputs/projects/adapter-project/papers/paper-stage-18"
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.md").write_text("# Reader-facing paper\n")
    snapshot = runtime.register_paper(
        "adapter-project",
        PaperManifest(
            paper_id="paper-stage-18",
            project_id="adapter-project",
            title="Reader-facing paper",
            date="2026-09-04",
            provider="scripted",
            model="deterministic-controller",
            condition="full_scitaste",
            task="adapter-validation",
            seed=7,
            stage=18,
            status="reviewed-draft",
            evidence_scope="engineering-only",
            files={"Markdown": "paper.md"},
        ),
        directory_name="paper-stage-18",
        expected_revision=snapshot.revision,
    )
    return runtime, snapshot.revision


def test_adapter_builds_project_relative_content_addressed_binding(tmp_path: Path) -> None:
    runtime, revision = _runtime_with_project(tmp_path)

    binding = ProjectSnapshotAdapter(runtime).build_binding("adapter-project")

    assert binding.project_id == "adapter-project"
    assert binding.snapshot_revision == revision
    assert {item.kind for item in binding.evidence_refs} == {
        EvidenceKind.PROJECT_MANIFEST,
        EvidenceKind.RUN_RECORD,
        EvidenceKind.STAGE_RECORD,
        EvidenceKind.PAPER,
        EvidenceKind.ARTIFACT,
    }
    assert all(not item.locator.startswith("projects/") for item in binding.evidence_refs)
    assert len({item.locator for item in binding.evidence_refs}) == len(binding.evidence_refs)


def test_artifact_change_updates_binding_without_claiming_a_project_revision(
    tmp_path: Path,
) -> None:
    runtime, revision = _runtime_with_project(tmp_path)
    adapter = ProjectSnapshotAdapter(runtime)
    first = adapter.build_binding("adapter-project")
    artifact = tmp_path / "outputs/projects/adapter-project/papers/paper-stage-18/paper.md"

    artifact.write_text("# Materially revised paper\n")
    second = adapter.build_binding("adapter-project")

    assert second.snapshot_revision == revision
    assert second.snapshot_sha256 != first.snapshot_sha256


def test_adapter_rejects_missing_registered_run(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="missing-run-project",
            title="Missing run",
            research_direction="Reject missing evidence.",
            status="active",
        )
    )
    runtime.begin_run(
        "missing-run-project",
        ProjectRun(
            run_id="run-a",
            provider="scripted",
            model="controller",
            condition="base",
            seed=0,
            status="registered",
            evidence_scope="engineering-only",
        ),
        expected_revision=snapshot.revision,
    )
    run_dir = tmp_path / "outputs/projects/missing-run-project/runs/run-a"
    run_dir.rmdir()

    with pytest.raises(FileNotFoundError):
        ProjectSnapshotAdapter(runtime).build_binding("missing-run-project")


def test_adapter_rejects_nested_symlink_even_when_target_is_inside_project(tmp_path: Path) -> None:
    runtime, _ = _runtime_with_project(tmp_path)
    run = tmp_path / "outputs/projects/adapter-project/runs/2026-09-04__scripted__seed-07"
    (run / "alias.json").symlink_to(run / "upstream_run/execution.json")

    with pytest.raises(ValueError, match="nested evidence symlinks"):
        ProjectSnapshotAdapter(runtime).build_binding("adapter-project")
