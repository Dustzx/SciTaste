from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.project import (
    PaperManifest,
    ProjectManifest,
    ProjectRevisionConflictError,
    ProjectRun,
    ProjectRuntime,
)


def manifest(*, project_id: str = "typed-project") -> ProjectManifest:
    return ProjectManifest(
        project_id=project_id,
        title="Typed project",
        research_direction="Keep every run and paper under one project.",
        target_domain="autonomous-research",
        status="active",
    )


def run(*, run_id: str = "2026-09-04__scripted__full__seed-07") -> ProjectRun:
    return ProjectRun(
        run_id=run_id,
        provider="scripted",
        model="deterministic-controller",
        condition="full_scitaste",
        seed=7,
        status="running",
        evidence_scope="engineering-only",
        stage_path="upstream_run",
    )


def paper(*, project_id: str = "typed-project") -> PaperManifest:
    return PaperManifest(
        paper_id="paper-stage-18",
        project_id=project_id,
        title="Reader-facing paper",
        date="2026-09-04",
        provider="scripted",
        model="deterministic-controller",
        condition="full_scitaste",
        task="diagnosis-friendly-v1",
        seed=7,
        stage=18,
        status="peer-reviewed-draft",
        evidence_scope="engineering-only",
        files={"Markdown": "paper.md", "Audit": "audit/evidence.json"},
    )


def test_create_builds_atomic_project_scaffold_and_snapshot(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")

    snapshot = runtime.create(manifest())

    project = tmp_path / "outputs" / "projects" / "typed-project"
    assert snapshot.project_id == "typed-project"
    assert snapshot.revision == 0
    assert snapshot.project_locator == "projects/typed-project"
    assert snapshot.warnings == []
    assert {item.name for item in project.iterdir()} >= {
        "PROJECT.json",
        "README.md",
        "STAGES.md",
        "runs",
        "stages",
        "papers",
    }
    assert runtime.open("typed-project").snapshot_sha256 == snapshot.snapshot_sha256
    with pytest.raises(FileExistsError):
        runtime.create(manifest())


def test_project_ids_and_owned_locators_reject_traversal() -> None:
    with pytest.raises(ValidationError, match="kebab-case"):
        manifest(project_id="../escape")
    with pytest.raises(ValidationError, match="project-relative"):
        ProjectRun.model_validate({**run().model_dump(mode="json"), "stage_path": "../escape"})
    with pytest.raises(ValidationError, match="project-relative"):
        PaperManifest.model_validate({**paper().model_dump(mode="json"), "files": {"x": "a/../b"}})


def test_begin_and_select_run_are_revision_guarded(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(manifest())
    snapshot = runtime.begin_run(
        "typed-project",
        run(),
        expected_revision=snapshot.revision,
    )

    assert snapshot.revision == 1
    run_path = tmp_path / "outputs/projects/typed-project/runs" / run().run_id
    assert (run_path / "upstream_run").is_dir()
    with pytest.raises(ProjectRevisionConflictError):
        runtime.select_run("typed-project", run().run_id, expected_revision=0)

    snapshot = runtime.select_run(
        "typed-project",
        run().run_id,
        expected_revision=snapshot.revision,
    )
    stages = tmp_path / "outputs/projects/typed-project/stages"
    assert snapshot.revision == 2
    assert snapshot.manifest.current_run == run().run_id
    assert (stages / run().run_id).readlink().as_posix() == (f"../runs/{run().run_id}/upstream_run")
    assert (stages / "current").readlink().as_posix() == run().run_id
    assert snapshot.current_stage_locator == "projects/typed-project/stages/current"


def test_metadata_update_preserves_extensions_and_blocks_alias_shortcuts(tmp_path: Path) -> None:
    project_manifest = ProjectManifest.model_validate(
        {**manifest().model_dump(mode="json"), "custom_gate": {"passed": False}}
    )
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(project_manifest)

    snapshot = runtime.update(
        "typed-project",
        expected_revision=0,
        status="blocked",
    )

    assert snapshot.revision == 1
    assert snapshot.manifest.status == "blocked"
    assert snapshot.manifest.model_extra == {"custom_gate": {"passed": False}}
    with pytest.raises(ValueError, match="select_run"):
        runtime.update(
            "typed-project",
            expected_revision=1,
            current_run="not-registered",
        )


def test_run_metadata_update_is_revision_guarded_and_preserves_identity(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(manifest())
    snapshot = runtime.begin_run(
        "typed-project",
        run(),
        expected_revision=snapshot.revision,
    )

    snapshot = runtime.update_run(
        "typed-project",
        run().run_id,
        expected_revision=snapshot.revision,
        status="complete",
        completion_summary="all offline stages passed",
    )

    assert snapshot.manifest.runs[0].status == "complete"
    assert snapshot.manifest.runs[0].model_extra == {
        "completion_summary": "all offline stages passed"
    }
    with pytest.raises(ProjectRevisionConflictError):
        runtime.update_run(
            "typed-project",
            run().run_id,
            expected_revision=1,
            status="failed",
        )
    with pytest.raises(ValueError, match="identity"):
        runtime.update_run(
            "typed-project",
            run().run_id,
            expected_revision=snapshot.revision,
            run_id="replacement",
        )


def test_register_and_select_paper_updates_project_and_global_aliases(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(manifest())
    bundle_name = "2026-09-04__scripted__full__stage-18"
    bundle = tmp_path / "outputs/projects/typed-project/papers" / bundle_name
    (bundle / "audit").mkdir(parents=True)
    (bundle / "paper.md").write_text("# Paper\n", encoding="utf-8")
    (bundle / "audit/evidence.json").write_text("{}\n", encoding="utf-8")

    snapshot = runtime.register_paper(
        "typed-project",
        paper(),
        directory_name=bundle_name,
        expected_revision=snapshot.revision,
    )
    assert snapshot.revision == 1
    assert snapshot.papers[0].manifest.paper_id == "paper-stage-18"

    snapshot = runtime.select_paper(
        "typed-project",
        bundle_name,
        expected_revision=snapshot.revision,
    )
    project_current = tmp_path / "outputs/projects/typed-project/papers/current"
    global_latest = tmp_path / "outputs/papers/latest"
    assert snapshot.revision == 2
    assert snapshot.current_paper_locator == f"projects/typed-project/papers/{bundle_name}"
    assert project_current.readlink().as_posix() == bundle_name
    assert global_latest.readlink().as_posix() == (
        f"../projects/typed-project/papers/{bundle_name}"
    )


def test_paper_registration_rejects_missing_or_escaping_artifacts(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(manifest())
    with pytest.raises(FileNotFoundError):
        runtime.register_paper(
            "typed-project",
            paper(),
            directory_name="missing-files",
            expected_revision=snapshot.revision,
        )

    unregistered_source = PaperManifest.model_validate(
        {**paper().model_dump(mode="json"), "source_run": "unknown-run", "files": {}}
    )
    with pytest.raises(ValueError, match="source_run"):
        runtime.register_paper(
            "typed-project",
            unregistered_source,
            directory_name="unknown-source-run",
            expected_revision=snapshot.revision,
        )

    bundle = tmp_path / "outputs/projects/typed-project/papers/linked-file"
    bundle.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (bundle / "paper.md").symlink_to(outside)
    linked = PaperManifest.model_validate(
        {**paper().model_dump(mode="json"), "files": {"Markdown": "paper.md"}}
    )
    with pytest.raises(ValueError, match="outside"):
        runtime.register_paper(
            "typed-project",
            linked,
            directory_name="linked-file",
            expected_revision=snapshot.revision,
        )


def test_existing_research_and_nonpaper_manifests_remain_readable(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    runtime = ProjectRuntime(outputs)
    research = outputs / "projects/floor-factorial-claim-verification"
    research.mkdir(parents=True)
    research_payload = {
        "schema_version": "1.0",
        "project_id": "floor-factorial-claim-verification",
        "title": "FLOOR",
        "research_direction": "Diagnose a reproducible failure boundary.",
        "status": "four-condition-preacceptance",
        "publication_ready": False,
        "current_run": "2026-09-04__zhipu__full__seed-07",
        "completed_stages": list(range(7, 19)),
        "current_paper": None,
        "matched_preacceptance": {"llm_tokens": 499524},
        "runs": [run(run_id="2026-09-04__zhipu__full__seed-07").model_dump(mode="json")],
    }
    (research / "PROJECT.json").write_text(json.dumps(research_payload), encoding="utf-8")

    self_project = outputs / "projects/scitaste-self-development"
    self_project.mkdir(parents=True)
    self_payload = {
        "schema_version": "1.0",
        "project_id": "scitaste-self-development",
        "title": "SciTaste Self-Development",
        "research_direction": "Audit framework design decisions.",
        "status": "active-design-pilot",
        "publication_ready": False,
        "current_run": None,
        "completed_stages": [],
        "current_paper": None,
        "stage_semantics": "self-development-milestones-not-autoresearchclaw-stages",
        "retrieval_eligible": False,
        "current_focus": {"selected_option": "bounded-model-nodes"},
        "runs": [],
    }
    (self_project / "PROJECT.json").write_text(json.dumps(self_payload), encoding="utf-8")

    floor = runtime.open("floor-factorial-claim-verification")
    self_snapshot = runtime.open("scitaste-self-development")

    assert floor.manifest.model_extra == {"matched_preacceptance": {"llm_tokens": 499524}}
    assert floor.revision == 0
    assert self_snapshot.manifest.retrieval_eligible is False
    assert self_snapshot.manifest.model_extra == {
        "current_focus": {"selected_option": "bounded-model-nodes"}
    }


def test_non_symlink_navigation_path_is_never_replaced(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(manifest())
    snapshot = runtime.begin_run(
        "typed-project",
        run(),
        expected_revision=snapshot.revision,
    )
    current = tmp_path / "outputs/projects/typed-project/stages/current"
    current.write_text("user-owned", encoding="utf-8")

    with pytest.raises(FileExistsError, match="non-symlink"):
        runtime.select_run(
            "typed-project",
            run().run_id,
            expected_revision=snapshot.revision,
        )
    assert current.read_text(encoding="utf-8") == "user-owned"
