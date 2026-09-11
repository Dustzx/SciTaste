from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    BlockerQuery,
    PaperEvidenceQuery,
    PendingProposalsQuery,
    ProjectListQuery,
    ProjectOverviewQuery,
    ProjectProgressQuery,
    RunComparisonQuery,
    RunStageQuery,
    TrustedComponent,
    UnknownWorkspaceSelectionError,
    WorkspaceSurfaceFactory,
    WorkspaceView,
    validate_workspace_query,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="workspace-project",
            title="Evidence-native workspace",
            research_direction="Navigate only registered evidence.",
            status="active",
        )
    )
    for index, (run_id, status) in enumerate(
        (
            ("successful-run", "complete"),
            ("failed-run", "failed"),
            ("blocked-run", "blocked"),
        )
    ):
        snapshot = runtime.begin_run(
            "workspace-project",
            ProjectRun(
                run_id=run_id,
                provider="scripted",
                model=f"deterministic-model-{index}",
                condition="full-scitaste",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
                stage_path="upstream-run" if run_id == "successful-run" else None,
                blockers=(
                    ["Awaiting independently verified result"] if run_id == "blocked-run" else None
                ),
            ),
            expected_revision=snapshot.revision,
        )
        run_dir = runtime.projects_root / "workspace-project" / "runs" / run_id
        (run_dir / "execution.json").write_text(
            '{"status":"' + status + '"}\n',
            encoding="utf-8",
        )
        if run_id == "successful-run":
            stage_root = run_dir / "upstream-run"
            for stage in (1, 14):
                stage_dir = stage_root / f"stage-{stage:02d}"
                stage_dir.mkdir(parents=True)
                (stage_dir / "result.json").write_text("{}\n", encoding="utf-8")
    snapshot = runtime.select_run(
        "workspace-project",
        "successful-run",
        expected_revision=snapshot.revision,
    )
    snapshot = runtime.update(
        "workspace-project",
        expected_revision=snapshot.revision,
        completed_stages=[1, 14],
    )
    paper_dir = runtime.projects_root / "workspace-project" / "papers" / "paper-one"
    paper_dir.mkdir()
    (paper_dir / "main.md").write_text("# Registered paper\n", encoding="utf-8")
    (paper_dir / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    snapshot = runtime.register_paper(
        "workspace-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="workspace-project",
            title="Registered evidence paper",
            date="2026-09-05",
            provider="scripted",
            model="deterministic-model",
            condition="full-scitaste",
            task="workspace-contract",
            seed=0,
            stage=18,
            status="reviewed-draft",
            evidence_scope="engineering-only",
            source_run="successful-run",
            files={"Manuscript": "main.md", "Figure": "figure.png"},
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    runtime.select_paper(
        "workspace-project",
        "paper-one",
        expected_revision=snapshot.revision,
        global_latest=False,
    )
    return runtime


def _component(document, component: TrustedComponent):
    return next(item for item in document.renderer.components if item.renderer == component)


def test_workspace_query_catalog_is_closed_and_rejects_client_layout() -> None:
    assert {item.value for item in WorkspaceView} == {
        "project-list",
        "project-overview",
        "project-progress",
        "run-stage-explorer",
        "paper-evidence",
        "run-comparison",
        "blockers",
        "pending-proposals",
        "research-landscape",
    }
    assert validate_workspace_query(ProjectListQuery()).view == WorkspaceView.PROJECT_LIST

    with pytest.raises(ValidationError):
        validate_workspace_query(
            {
                "view": "project-overview",
                "project_id": "workspace-project",
                "components": [{"renderer": "InjectedRenderer"}],
            }
        )
    with pytest.raises(ValidationError):
        validate_workspace_query(
            {
                "view": "run-stage-explorer",
                "project_id": "workspace-project",
                "run_id": "../foreign",
            }
        )


def test_project_list_is_stable_and_contains_only_authoritative_identity(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.create(
        ProjectManifest(
            project_id="another-project",
            title="Another project",
            research_direction="Sorted discovery.",
            status="paused",
        )
    )
    factory = WorkspaceSurfaceFactory(runtime)

    first = factory.project_list()
    repeated = factory.project_list()

    assert [item.project_id for item in first.projects] == [
        "another-project",
        "workspace-project",
    ]
    assert first.fingerprint == repeated.fingerprint
    assert first.projects[1].has_current_run is True
    assert first.projects[1].paper_count == 1
    assert "title" not in first.projects[1].model_dump()


def test_all_project_workspace_views_bind_query_and_fresh_evidence(tmp_path: Path) -> None:
    factory = WorkspaceSurfaceFactory(_runtime(tmp_path))
    documents = [
        factory.build(ProjectOverviewQuery(project_id="workspace-project")),
        factory.build(ProjectProgressQuery(project_id="workspace-project")),
        factory.build(RunStageQuery(project_id="workspace-project")),
        factory.build(PaperEvidenceQuery(project_id="workspace-project")),
        factory.build(
            RunComparisonQuery(
                project_id="workspace-project",
                baseline_run_id="successful-run",
                candidate_run_id="failed-run",
            )
        ),
        factory.build(BlockerQuery(project_id="workspace-project")),
        factory.build(PendingProposalsQuery(project_id="workspace-project")),
    ]

    assert len({item.query.view for item in documents}) == 7
    assert len({item.renderer.surface_id for item in documents}) == 7
    for document in documents:
        assert document.query.project_id == document.renderer.project_id
        assert document.freshness.surface_fingerprint == document.renderer.surface_fingerprint
        assert document.freshness.snapshot_sha256 == document.renderer.snapshot.snapshot_sha256
        assert document.renderer.execution_authority == "none"


def test_run_stage_view_explains_registered_outcomes_and_stage_outputs(tmp_path: Path) -> None:
    document = WorkspaceSurfaceFactory(_runtime(tmp_path)).build(
        RunStageQuery(project_id="workspace-project", run_id="successful-run")
    )
    explorer = _component(document, TrustedComponent.RUN_STAGE_EXPLORER)

    assert [item["outcome"] for item in explorer.data["runs"]] == [
        "succeeded",
        "failed",
        "blocked",
    ]
    assert explorer.data["stage_state"] == "available"
    assert [item["stage"] for item in explorer.data["stages"]] == [1, 14]
    assert explorer.data["stages"][0]["label_en"] == "Topic initialization"
    assert explorer.data["stages"][0]["label_zh"] == "课题初始化"
    assert explorer.data["stages"][0]["artifact_count"] == 1
    assert document.renderer.actions[0].requires_approval is True


def test_project_progress_exposes_a_bounded_heterogeneous_evidence_graph(
    tmp_path: Path,
) -> None:
    document = WorkspaceSurfaceFactory(_runtime(tmp_path)).build(
        ProjectProgressQuery(project_id="workspace-project")
    )
    graph = _component(document, TrustedComponent.EVIDENCE_GRAPH)

    assert 1 < len(graph.data["nodes"]) <= 24
    assert len(graph.data["edges"]) <= 64
    assert {item["kind"] for item in graph.data["nodes"]} >= {
        "project_manifest",
        "run_record",
        "paper",
        "stage_record",
    }
    assert all(
        edge["source_ref_id"] in graph.evidence_ref_ids
        and edge["target_ref_id"] in graph.evidence_ref_ids
        for edge in graph.data["edges"]
    )


def test_paper_evidence_view_lists_exact_hashes_and_supported_artifacts(tmp_path: Path) -> None:
    document = WorkspaceSurfaceFactory(_runtime(tmp_path)).build(
        PaperEvidenceQuery(project_id="workspace-project", paper_id="paper-one")
    )
    inventory = _component(document, TrustedComponent.EVIDENCE_INVENTORY)

    assert inventory.data["scope"] == "paper"
    assert inventory.data["selected_paper_id"] == "paper-one"
    assert {item["kind"] for item in inventory.data["items"]} == {"paper", "artifact"}
    evidence = {item.evidence_id: item for item in document.renderer.snapshot.evidence_refs}
    for item in inventory.data["items"]:
        ref = evidence[item["evidence_ref_id"]]
        assert item["locator"] == ref.locator
        assert item["sha256"] == ref.sha256
    assert (
        len(
            [
                item
                for item in document.renderer.components
                if item.renderer == TrustedComponent.ARTIFACT_VIEWER
            ]
        )
        == 2
    )


def test_comparison_and_blocker_views_never_invent_metrics_or_failure_details(
    tmp_path: Path,
) -> None:
    factory = WorkspaceSurfaceFactory(_runtime(tmp_path))
    comparison = factory.build(
        RunComparisonQuery(
            project_id="workspace-project",
            baseline_run_id="successful-run",
            candidate_run_id="failed-run",
        )
    )
    panel = _component(comparison, TrustedComponent.RUN_COMPARISON_PANEL)
    assert panel.data["metrics_state"] == "unavailable"
    assert panel.data["metrics"] == {}
    assert panel.data["metrics_reason_code"] == "no-registered-comparable-metrics"

    blockers = factory.build(BlockerQuery(project_id="workspace-project"))
    blocker_panel = _component(blockers, TrustedComponent.RUN_BLOCKER_PANEL)
    assert [item["classification"] for item in blocker_panel.data["blockers"]] == [
        "failed",
        "blocked",
    ]
    assert {item["reason_code"] for item in blocker_panel.data["blockers"]} == {
        "registered-status-failed",
        "registered-status-blocked",
    }
    detail_by_status = {item["classification"]: item for item in blocker_panel.data["blockers"]}
    assert detail_by_status["failed"]["detail_state"] == "unavailable"
    assert detail_by_status["failed"]["recorded_reasons"] == []
    assert detail_by_status["blocked"]["detail_state"] == "recorded"
    assert detail_by_status["blocked"]["recorded_reasons"] == [
        "Awaiting independently verified result"
    ]


def test_empty_states_and_forged_project_owned_selections_fail_closed(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="empty-project",
            title="Empty project",
            research_direction="Represent absence explicitly.",
            status="active",
        )
    )
    factory = WorkspaceSurfaceFactory(runtime)
    runs = factory.build(RunStageQuery(project_id="empty-project"))
    papers = factory.build(PaperEvidenceQuery(project_id="empty-project"))
    proposals = factory.build(PendingProposalsQuery(project_id="empty-project"))

    assert _component(runs, TrustedComponent.AVAILABILITY_NOTICE).data["subject"] == "runs"
    assert _component(papers, TrustedComponent.AVAILABILITY_NOTICE).data["subject"] == "papers"
    assert (
        _component(proposals, TrustedComponent.AVAILABILITY_NOTICE).data["subject"] == "proposals"
    )
    with pytest.raises(UnknownWorkspaceSelectionError):
        factory.build(RunStageQuery(project_id="empty-project", run_id="foreign-run"))
    with pytest.raises(UnknownWorkspaceSelectionError):
        factory.build(PaperEvidenceQuery(project_id="empty-project", paper_id="foreign-paper"))


def test_query_selection_and_artifact_content_change_surface_fingerprint(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    factory = WorkspaceSurfaceFactory(runtime)
    first = factory.build(RunStageQuery(project_id="workspace-project", run_id="successful-run"))
    other = factory.build(RunStageQuery(project_id="workspace-project", run_id="failed-run"))
    assert first.renderer.surface_fingerprint != other.renderer.surface_fingerprint

    paper_query = PaperEvidenceQuery(project_id="workspace-project", paper_id="paper-one")
    before = factory.build(paper_query)
    artifact = runtime.projects_root / "workspace-project/papers/paper-one/main.md"
    artifact.write_text("# Changed registered paper\n", encoding="utf-8")
    after = factory.build(paper_query)
    assert before.renderer.snapshot.snapshot_sha256 != after.renderer.snapshot.snapshot_sha256
    assert before.renderer.surface_fingerprint != after.renderer.surface_fingerprint


def test_legacy_run_artifact_is_navigable_without_inventing_stage_state(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="legacy-project",
            title="Legacy project",
            research_direction="Retain a registered legacy run locator.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        "legacy-project",
        ProjectRun(
            run_id="legacy-run",
            provider="scripted",
            model="legacy-model",
            condition="legacy-import",
            seed=0,
            status="complete",
            evidence_scope="legacy-evidence",
        ),
        expected_revision=snapshot.revision,
    )
    project_root = runtime.projects_root / "legacy-project"
    legacy_path = project_root / "legacy/old-run"
    legacy_path.parent.mkdir()
    (project_root / "runs/legacy-run").rename(legacy_path)
    (legacy_path / "result.json").write_text("{}\n", encoding="utf-8")
    runtime.update_run(
        "legacy-project",
        "legacy-run",
        expected_revision=snapshot.revision,
        artifact="legacy/old-run",
    )

    document = WorkspaceSurfaceFactory(runtime).build(
        RunStageQuery(project_id="legacy-project", run_id="legacy-run")
    )
    explorer = _component(document, TrustedComponent.RUN_STAGE_EXPLORER)
    evidence = {item.evidence_id: item for item in document.renderer.snapshot.evidence_refs}
    run_ref = evidence[explorer.data["runs"][0]["run_ref_id"]]

    assert run_ref.locator == "legacy/old-run"
    assert explorer.data["runs"][0]["outcome"] == "succeeded"
    assert explorer.data["stage_state"] == "unavailable"
    assert explorer.data["stages"] == []
