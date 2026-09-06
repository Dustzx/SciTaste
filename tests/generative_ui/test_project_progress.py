from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    ProjectProgressQuery,
    SurfaceSpec,
    TrustedComponent,
    WorkspaceSurfaceFactory,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _create_runtime(tmp_path: Path, *, status: str = "active") -> tuple[ProjectRuntime, object]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="progress-project",
            title="Progress project",
            research_direction="Show only evidence-grounded project progress.",
            status=status,
        )
    )
    return runtime, snapshot


def _begin_run(
    runtime: ProjectRuntime,
    snapshot,
    *,
    run_id: str,
    status: str,
    **extra,
):
    return runtime.begin_run(
        "progress-project",
        ProjectRun(
            run_id=run_id,
            provider="scripted",
            model="deterministic-model",
            condition="progress-fixture",
            seed=0,
            status=status,
            evidence_scope="engineering-only",
            **extra,
        ),
        expected_revision=snapshot.revision,
    )


def _progress(runtime: ProjectRuntime):
    document = WorkspaceSurfaceFactory(runtime).build(
        ProjectProgressQuery(project_id="progress-project")
    )
    component = next(
        item
        for item in document.renderer.components
        if item.renderer == TrustedComponent.PROJECT_PROGRESS_BOARD
    )
    return document, component.data


def test_empty_progress_is_explicit_and_never_invents_a_percentage(tmp_path: Path) -> None:
    runtime, _ = _create_runtime(tmp_path)

    document, data = _progress(runtime)

    assert document.query.view == "project-progress"
    assert document.renderer.catalog_version == "scitaste-trusted-components-v2"
    assert data["project_state"] == "current_work"
    assert data["counts"] == {
        "runs_registered": 0,
        "runs_completed": 0,
        "runs_failed": 0,
        "runs_blocked": 0,
        "runs_active": 0,
        "runs_candidates": 0,
        "runs_unavailable": 0,
        "runs_unknown": 0,
        "completed_stages": 0,
        "papers_registered": 0,
    }
    assert data["stage_state"] == "empty"
    assert data["milestone_state"] == "empty"
    assert data["recent_activity"] == []
    assert [item["kind"] for item in data["next_step_candidates"]] == ["review_progress"]
    assert "percent" not in json.dumps(data, sort_keys=True).lower()


def test_progress_status_mapping_is_exact_and_keeps_current_selection_separate(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path, status="active-pilot-blocked")
    statuses = {
        "completed-run": "complete",
        "failed-run": "failed",
        "blocked-run": "blocked",
        "active-run": "active",
        "candidate-run": "proposed",
        "unavailable-run": "unavailable",
        "referenced-run": "referenced",
        "substring-run": "completed-ish",
    }
    for run_id, status in statuses.items():
        snapshot = _begin_run(
            runtime,
            snapshot,
            run_id=run_id,
            status=status,
            blockers=["Awaiting independently verified result"] if status == "blocked" else None,
        )
    snapshot = runtime.select_run(
        "progress-project",
        "completed-run",
        expected_revision=snapshot.revision,
    )

    _, data = _progress(runtime)

    assert data["project_state"] == "blocked"
    assert data["current_run_id"] == "completed-run"
    assert data["current_run_state"] == "observed_completed"
    assert data["counts"] == {
        "runs_registered": 8,
        "runs_completed": 1,
        "runs_failed": 1,
        "runs_blocked": 1,
        "runs_active": 1,
        "runs_candidates": 1,
        "runs_unavailable": 1,
        "runs_unknown": 2,
        "completed_stages": 0,
        "papers_registered": 0,
    }
    activity = {item["run_id"]: item for item in data["recent_activity"]}
    assert activity["referenced-run"]["observed_state"] == "unknown"
    assert activity["substring-run"]["observed_state"] == "unknown"
    assert activity["completed-run"]["selected"] is True
    blocked = next(item for item in data["attention"] if item["run_id"] == "blocked-run")
    assert blocked["detail_state"] == "recorded"
    assert blocked["recorded_reasons"] == ["Awaiting independently verified result"]


def test_progress_binds_observed_stages_and_registered_paper(tmp_path: Path) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id="staged-run",
        status="complete",
        stage_path="upstream-run",
    )
    stage_root = runtime.projects_root / "progress-project" / "runs" / "staged-run" / "upstream-run"
    for stage in (1, 14):
        path = stage_root / f"stage-{stage:02d}"
        path.mkdir(parents=True)
        (path / "result.json").write_text("{}\n", encoding="utf-8")
    snapshot = runtime.select_run(
        "progress-project",
        "staged-run",
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.update(
        "progress-project",
        expected_revision=snapshot.revision,
        completed_stages=[1, 14],
    )
    paper_dir = runtime.projects_root / "progress-project" / "papers" / "paper-one"
    paper_dir.mkdir()
    (paper_dir / "main.md").write_text("# Evidence paper\n", encoding="utf-8")
    snapshot = runtime.register_paper(
        "progress-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="progress-project",
            title="Evidence paper",
            date="2026-09-06",
            provider="scripted",
            model="deterministic-model",
            condition="progress-fixture",
            task="progress-view",
            seed=0,
            stage=18,
            status="reviewed-draft",
            evidence_scope="engineering-only",
            source_run="staged-run",
            files={"Manuscript": "main.md"},
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    runtime.select_paper(
        "progress-project",
        "paper-one",
        expected_revision=snapshot.revision,
        global_latest=False,
    )

    _, data = _progress(runtime)

    assert data["stage_state"] == "available"
    assert [item["stage"] for item in data["stages"]] == [1, 14]
    assert all(item["observed_state"] == "observed_completed" for item in data["stages"])
    assert all(len(item["support_ref_ids"]) == 2 for item in data["stages"])
    assert data["current_paper_id"] == "paper-one"
    assert data["papers"][0]["selected"] is True
    assert data["papers"][0]["observed_state"] == "current_work"
    assert "review_paper_evidence" in {item["kind"] for item in data["next_step_candidates"]}


def test_strict_manifest_extensions_supply_milestones_or_fail_closed(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    snapshot = _begin_run(
        runtime,
        snapshot,
        run_id="milestone-run",
        status="complete",
    )
    run_dir = runtime.projects_root / "progress-project" / "runs" / "milestone-run"
    (run_dir / "decision.json").write_text("{}\n", encoding="utf-8")
    snapshot = runtime.update(
        "progress-project",
        expected_revision=snapshot.revision,
        current_focus={
            "decision_id": "bounded-workspace-planner",
            "status": "implementation-preaccepted-live-pilot-blocked",
            "selected_option": "bounded-planner",
            "online_model": "zhipu-direct/glm-5.3-flash",
            "next_gate": "Independent review of a real project pilot",
        },
        iterations=[
            {
                "iteration_id": "progress-foundation",
                "date": "2026-09-06",
                "status": "completed-dogfooding",
                "decision": "Use project progress as the generative workspace foundation.",
                "evidence": "runs/milestone-run/",
            },
            {
                "iteration_id": "external-reference",
                "date": "2026-09-06",
                "status": "referenced",
                "decision": "Retain an explicitly unbound manifest reference.",
                "evidence": "references/external-review",
            },
        ],
    )

    first, data = _progress(runtime)

    assert data["focus"] == "bounded-workspace-planner"
    assert data["next_gate"] == "Independent review of a real project pilot"
    assert data["milestone_state"] == "available"
    assert [item["evidence_binding"] for item in data["milestones"]] == [
        "content_addressed",
        "manifest_declared",
    ]
    assert [item["observed_state"] for item in data["milestones"]] == [
        "observed_completed",
        "unknown",
    ]

    runtime.update(
        "progress-project",
        expected_revision=snapshot.revision,
        current_focus={"decision_id": "<script>"},
        iterations=[
            {
                "iteration_id": "duplicate",
                "date": "2026-09-06",
                "status": "complete",
                "decision": "First declaration.",
                "evidence": "runs/milestone-run",
            },
            {
                "iteration_id": "duplicate",
                "date": "2026-09-06",
                "status": "complete",
                "decision": "Second declaration.",
                "evidence": "runs/milestone-run",
            },
        ],
    )
    second, invalid = _progress(runtime)

    assert invalid["focus"] == "Show only evidence-grounded project progress."
    assert invalid["focus_status"] is None
    assert invalid["milestone_state"] == "unavailable"
    assert invalid["milestones"] == []
    assert first.renderer.surface_fingerprint != second.renderer.surface_fingerprint


def test_progress_component_rejects_ungrounded_rows_and_extra_percentage(
    tmp_path: Path,
) -> None:
    runtime, snapshot = _create_runtime(tmp_path)
    _begin_run(runtime, snapshot, run_id="grounded-run", status="complete")
    document, _ = _progress(runtime)
    payload = (
        WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="progress-project"))
        .model_dump(mode="json")
    )
    data = payload["components"][0]["data"]
    data["recent_activity"][0]["support_ref_ids"] = [data["recent_activity"][0]["run_ref_id"]]
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)

    payload = (
        WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="progress-project"))
        .model_dump(mode="json")
    )
    payload["components"][0]["data"]["progress_percent"] = 50
    with pytest.raises(ValidationError):
        SurfaceSpec.model_validate(payload)

    assert document.renderer.execution_authority == "none"
