from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    EvidenceKind,
    ProjectSurfaceEvidenceError,
    ProjectSurfaceFactory,
    ProposalKind,
    RendererDocument,
    SurfaceAuditLog,
    SurfaceSpec,
    TrustedComponent,
    project_surface,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime(
    tmp_path: Path,
    *,
    project_id: str = "surface-project",
    stage_semantics: str = "autoresearchclaw-stages",
    status: str = "active",
) -> tuple[ProjectRuntime, int]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id=project_id,
            title="Trusted surface project",
            research_direction="Render only authoritative project state.",
            status=status,
            stage_semantics=stage_semantics,
        )
    )
    return runtime, snapshot.revision


def _select_run(
    runtime: ProjectRuntime,
    project_id: str,
    revision: int,
    *,
    completed_stages: list[int] | None = None,
) -> int:
    snapshot = runtime.begin_run(
        project_id,
        ProjectRun(
            run_id="2026-09-05__scripted__full__seed-07",
            provider="scripted",
            model="deterministic-controller",
            condition="full-scitaste",
            seed=7,
            status="complete",
            evidence_scope="engineering-only",
            stage_path="upstream-run",
        ),
        expected_revision=revision,
    )
    run = runtime.outputs_root / "projects" / project_id / "runs" / snapshot.manifest.runs[0].run_id
    (run / "upstream-run" / "execution.json").write_text(
        '{"status":"complete"}\n', encoding="utf-8"
    )
    for stage in completed_stages or []:
        stage_dir = run / "upstream-run" / f"stage-{stage:02d}"
        stage_dir.mkdir()
        (stage_dir / "result.json").write_text("{}\n", encoding="utf-8")
    snapshot = runtime.select_run(
        project_id,
        snapshot.manifest.runs[0].run_id,
        expected_revision=snapshot.revision,
    )
    if completed_stages:
        snapshot = runtime.update(
            project_id,
            expected_revision=snapshot.revision,
            completed_stages=completed_stages,
        )
    return snapshot.revision


def _select_paper(
    runtime: ProjectRuntime,
    project_id: str,
    revision: int,
    *,
    with_pdf: bool = True,
) -> tuple[int, Path]:
    directory_name = "paper-stage-18"
    paper_dir = runtime.outputs_root / "projects" / project_id / "papers" / directory_name
    paper_dir.mkdir(parents=True)
    markdown = paper_dir / "main.md"
    markdown.write_text("# Trusted paper\n", encoding="utf-8")
    files = {"Markdown manuscript": "main.md"}
    if with_pdf:
        (paper_dir / "main.pdf").write_bytes(b"%PDF-1.4\ntrusted fixture\n")
        files["PDF manuscript"] = "main.pdf"
    snapshot = runtime.register_paper(
        project_id,
        PaperManifest(
            paper_id="trusted-paper",
            project_id=project_id,
            title="Trusted paper",
            date="2026-09-05",
            provider="scripted",
            model="deterministic-controller",
            condition="full-scitaste",
            task="surface-validation",
            seed=7,
            stage=18,
            status="reviewed-draft",
            evidence_scope="engineering-only",
            files=files,
        ),
        directory_name=directory_name,
        expected_revision=revision,
    )
    snapshot = runtime.select_paper(
        project_id,
        directory_name,
        expected_revision=snapshot.revision,
        global_latest=False,
    )
    return snapshot.revision, markdown


def _components(surface: SurfaceSpec) -> dict[TrustedComponent, object]:
    return {item.component: item for item in surface.components}


def test_empty_project_produces_only_authoritative_summary_and_renderer(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")
    renderer = project_surface(surface)

    assert surface.revision == revision
    assert set(_components(surface)) == {TrustedComponent.PROJECT_SUMMARY_CARD}
    assert surface.actions == []
    assert surface.components[0].data == {
        "project_ref_id": "project-manifest",
        "project_status": "active",
        "publication_ready": False,
        "current_focus": "Render only authoritative project state.",
    }
    assert renderer.surface_fingerprint == surface.fingerprint
    assert renderer.execution_authority == "none"


def test_current_run_adds_grounded_health_and_proposal_only_approval(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)
    revision = _select_run(runtime, "surface-project", revision)

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")
    components = _components(surface)

    assert surface.revision == revision
    assert set(components) == {
        TrustedComponent.PROJECT_SUMMARY_CARD,
        TrustedComponent.RUN_HEALTH,
    }
    health = components[TrustedComponent.RUN_HEALTH]
    assert health.data["run_status"] == "complete"
    assert health.data["run_ref_id"] in health.evidence_ref_ids
    health_evidence = {
        item.evidence_id: item.kind
        for item in surface.snapshot.evidence_refs
        if item.evidence_id in health.evidence_ref_ids
    }
    assert set(health_evidence.values()) == {
        EvidenceKind.RUN_RECORD,
        EvidenceKind.PROJECT_MANIFEST,
    }
    assert len(surface.actions) == 1
    assert surface.actions[0].proposal.authority == "proposal_only"
    assert surface.actions[0].proposal.requires_approval is True


def test_autoresearchclaw_completed_stages_add_timeline(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)
    _select_run(runtime, "surface-project", revision, completed_stages=[1, 2])

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")
    timeline = _components(surface)[TrustedComponent.STAGE_TIMELINE]

    assert [item["stage"] for item in timeline.data["stages"]] == [1, 2]
    assert {item["status"] for item in timeline.data["stages"]} == {"completed"}
    stage_ref_id = timeline.data["stages"][0]["stage_ref_id"]
    evidence = {item.evidence_id: item for item in surface.snapshot.evidence_refs}
    assert evidence[stage_ref_id].kind == EvidenceKind.STAGE_RECORD
    assert {evidence[ref_id].kind for ref_id in timeline.evidence_ref_ids} == {
        EvidenceKind.STAGE_RECORD,
        EvidenceKind.PROJECT_MANIFEST,
    }


def test_alternate_stage_semantics_never_claim_autoresearchclaw_timeline(tmp_path: Path) -> None:
    runtime, revision = _runtime(
        tmp_path,
        stage_semantics="scitaste-workflow-phases",
    )
    _select_run(runtime, "surface-project", revision)

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")

    assert TrustedComponent.RUN_HEALTH in _components(surface)
    assert TrustedComponent.STAGE_TIMELINE not in _components(surface)


def test_selected_paper_and_declared_artifact_add_grounded_components(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)
    _select_paper(runtime, "surface-project", revision)

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")
    components = _components(surface)
    paper = components[TrustedComponent.PAPER_PREVIEW]
    artifact = components[TrustedComponent.ARTIFACT_VIEWER]

    assert paper.data == {
        "paper_ref_id": paper.evidence_ref_ids[0],
        "paper_title": "Trusted paper",
        "paper_status": "reviewed-draft",
        "publication_ready": False,
        "excerpt": None,
    }
    assert artifact.data["artifact_path"] == "papers/paper-stage-18/main.pdf"
    assert artifact.data["media_type"] == "application/pdf"
    evidence = {item.evidence_id: item for item in surface.snapshot.evidence_refs}
    assert (
        evidence[artifact.data["artifact_ref_id"]].sha256
        == hashlib.sha256(b"%PDF-1.4\ntrusted fixture\n").hexdigest()
    )
    assert {item.action_id for item in surface.actions} == {
        "request-current-paper-approval",
        "inspect-selected-paper-artifact",
    }


def test_selected_paper_without_supported_artifact_omits_viewer(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)
    paper_dir = runtime.outputs_root / "projects/surface-project/papers/paper-stage-18"
    paper_dir.mkdir(parents=True)
    (paper_dir / "measurements.csv").write_text("metric,value\nscore,1\n", encoding="utf-8")
    snapshot = runtime.register_paper(
        "surface-project",
        PaperManifest(
            paper_id="trusted-paper",
            project_id="surface-project",
            title="Trusted paper",
            date="2026-09-05",
            provider="scripted",
            model="deterministic-controller",
            condition="full-scitaste",
            task="surface-validation",
            seed=7,
            stage=18,
            status="reviewed-draft",
            evidence_scope="engineering-only",
            files={"Measurements": "measurements.csv"},
        ),
        directory_name="paper-stage-18",
        expected_revision=revision,
    )
    runtime.select_paper(
        "surface-project",
        "paper-stage-18",
        expected_revision=snapshot.revision,
        global_latest=False,
    )

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")

    assert TrustedComponent.PAPER_PREVIEW in _components(surface)
    assert TrustedComponent.ARTIFACT_VIEWER not in _components(surface)
    assert [item.action_id for item in surface.actions] == ["request-current-paper-approval"]


def test_missing_registered_evidence_fails_closed(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path / "run")
    snapshot = runtime.begin_run(
        "surface-project",
        ProjectRun(
            run_id="missing-run",
            provider="scripted",
            model="controller",
            condition="base",
            seed=0,
            status="registered",
            evidence_scope="engineering-only",
        ),
        expected_revision=revision,
    )
    run_dir = runtime.outputs_root / "projects/surface-project/runs/missing-run"
    run_dir.rmdir()
    with pytest.raises(FileNotFoundError):
        ProjectSurfaceFactory(runtime).build_project_overview(snapshot.project_id)

    paper_runtime, paper_revision = _runtime(tmp_path / "paper")
    _, artifact = _select_paper(
        paper_runtime,
        "surface-project",
        paper_revision,
        with_pdf=False,
    )
    artifact.unlink()
    with pytest.raises(FileNotFoundError):
        ProjectSurfaceFactory(paper_runtime).build_project_overview("surface-project")

    corrupt_runtime, corrupt_revision = _runtime(tmp_path / "corrupt-paper")
    _select_paper(corrupt_runtime, "surface-project", corrupt_revision)
    manifest_path = (
        corrupt_runtime.outputs_root
        / "projects/surface-project/papers/paper-stage-18/MANIFEST.json"
    )
    manifest_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ProjectSurfaceEvidenceError, match="valid manifest"):
        ProjectSurfaceFactory(corrupt_runtime).build_project_overview("surface-project")


def test_invalid_authoritative_status_is_rejected_without_normalization(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path, status="In Progress")

    with pytest.raises(ValidationError):
        ProjectSurfaceFactory(runtime).build_project_overview("surface-project")


def test_factory_requires_real_runtime_and_canonical_project_id(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="trusted ProjectRuntime"):
        ProjectSurfaceFactory(object())  # type: ignore[arg-type]

    runtime, _ = _runtime(tmp_path)
    with pytest.raises(ValueError, match="lowercase kebab-case"):
        ProjectSurfaceFactory(runtime).build_project_overview("Surface Project")


def test_revision_and_artifact_changes_update_surface_identity_stably(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)
    revision, artifact = _select_paper(
        runtime,
        "surface-project",
        revision,
        with_pdf=False,
    )
    factory = ProjectSurfaceFactory(runtime)

    first = factory.build_project_overview("surface-project")
    repeated = factory.build_project_overview("surface-project")
    assert first.canonical_json() == repeated.canonical_json()
    assert first.fingerprint == repeated.fingerprint

    artifact.write_text("# Materially changed paper\n", encoding="utf-8")
    changed_artifact = factory.build_project_overview("surface-project")
    assert changed_artifact.revision == revision
    assert changed_artifact.snapshot.snapshot_sha256 != first.snapshot.snapshot_sha256
    assert changed_artifact.fingerprint != first.fingerprint

    updated = runtime.update(
        "surface-project",
        expected_revision=revision,
        status="paused",
    )
    changed_revision = factory.build_project_overview("surface-project")
    assert changed_revision.revision == updated.revision
    assert changed_revision.snapshot.snapshot_sha256 != changed_artifact.snapshot.snapshot_sha256
    assert changed_revision.fingerprint != changed_artifact.fingerprint


def test_actions_and_renderer_never_expose_execution_fields(tmp_path: Path) -> None:
    runtime, revision = _runtime(tmp_path)
    revision = _select_run(runtime, "surface-project", revision)
    _select_paper(runtime, "surface-project", revision)

    surface = ProjectSurfaceFactory(runtime).build_project_overview("surface-project")
    renderer = project_surface(surface)

    assert surface.actions
    assert all(item.proposal.authority == "proposal_only" for item in surface.actions)
    assert all(item.proposal.payload.kind in ProposalKind for item in surface.actions)
    assert not _all_keys(surface.model_dump(mode="json")) & {
        "callback",
        "command",
        "executor",
        "href",
        "tool",
        "url",
    }
    renderer_payload = renderer.model_dump(mode="json")
    assert renderer_payload["execution_authority"] == "none"
    assert "proposal" not in _all_keys(renderer_payload)


def test_explicit_output_helper_initializes_audit_and_refuses_reuse(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    destination = tmp_path / "published-surface"
    factory = ProjectSurfaceFactory(runtime)

    output = factory.write_project_overview("surface-project", destination)
    original = {path.name: path.read_bytes() for path in destination.iterdir() if path.is_file()}

    assert SurfaceSpec.model_validate_json(output.surface_path.read_text()) == output.surface
    assert RendererDocument.model_validate_json(output.renderer_path.read_text()) == output.renderer
    records = SurfaceAuditLog(output.audit_path).records()
    assert len(records) == 1
    assert records[0].payload.surface == output.surface

    with pytest.raises(FileExistsError):
        factory.write_project_overview("surface-project", destination)
    assert original == {
        path.name: path.read_bytes() for path in destination.iterdir() if path.is_file()
    }


def test_local_offline_full_project_read_only_contract_smoke() -> None:
    repository = Path(__file__).resolve().parents[2]
    candidates = [
        repository / "outputs",
        repository.parent.parent / "SciTaste" / "outputs",
    ]
    outputs = next(
        (
            candidate
            for candidate in candidates
            if (candidate / "projects/scitaste-offline-full/PROJECT.json").is_file()
        ),
        None,
    )
    if outputs is None:
        pytest.skip("local scitaste-offline-full project is not available")
    manifest_path = outputs / "projects/scitaste-offline-full/PROJECT.json"
    before = manifest_path.read_bytes()

    surface = ProjectSurfaceFactory(ProjectRuntime(outputs)).build_project_overview(
        "scitaste-offline-full"
    )

    assert surface.project_id == "scitaste-offline-full"
    assert project_surface(surface).surface_fingerprint == surface.fingerprint
    assert manifest_path.read_bytes() == before


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()
