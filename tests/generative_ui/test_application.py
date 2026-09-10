from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import copyfile

import pytest
from pydantic import ValidationError

import scitaste.generative_ui.application as application_module
from scitaste.generative_ui import (
    ArtifactInspectedAudit,
    AuditIntegrityError,
    DuplicateEventError,
    GenerativeUIApplication,
    PaperEvidenceQuery,
    PendingProposalsQuery,
    ProposalControlledAudit,
    ProposalControllerRequest,
    QuickIntentRequest,
    RunStageQuery,
    StaleSurfaceError,
    SurfaceAuditLog,
    SurfaceEvent,
    TrustedComponent,
    UnknownActionError,
    WorkspaceGenerationRequest,
    WorkspaceSurfaceFactory,
    make_artifact_inspection_event,
    make_surface_event,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime


def _runtime_with_action(tmp_path: Path, *, project_id: str = "app-project") -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id=project_id,
            title="Trusted local UI",
            research_direction="Exercise identity-only proposal events.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        project_id,
        ProjectRun(
            run_id="trusted-run",
            provider="scripted",
            model="deterministic-controller",
            condition="full-scitaste",
            seed=7,
            status="complete",
            evidence_scope="engineering-only",
        ),
        expected_revision=snapshot.revision,
    )
    run_dir = runtime.projects_root / project_id / "runs/trusted-run"
    (run_dir / "execution.json").write_text('{"status":"complete"}\n', encoding="utf-8")
    runtime.select_run(project_id, "trusted-run", expected_revision=snapshot.revision)
    return runtime


def _audit_path(runtime: ProjectRuntime, project_id: str = "app-project") -> Path:
    matches = list((runtime.projects_root / project_id / ".generative-ui/audits").glob("*.jsonl"))
    assert len(matches) == 1
    return matches[0]


def _runtime_with_paper(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="paper-app",
            title="Paper inspection application",
            research_direction="Persist read-only inspections.",
            status="active",
        )
    )
    paper_dir = runtime.projects_root / "paper-app/papers/paper-one"
    paper_dir.mkdir(parents=True)
    (paper_dir / "main.md").write_text("# Evidence\n", encoding="utf-8")
    runtime.register_paper(
        "paper-app",
        PaperManifest(
            paper_id="paper-one",
            project_id="paper-app",
            title="Inspected paper",
            date="2026-09-05",
            provider="scripted",
            model="deterministic",
            condition="inspection",
            task="audit-inspection",
            seed=0,
            stage=18,
            status="draft",
            evidence_scope="engineering-only",
            files={"Manuscript": "main.md"},
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    return runtime


def test_application_discovers_real_projects_and_projects_fixed_renderer(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    other = runtime.create(
        ProjectManifest(
            project_id="another-project",
            title="Another project",
            research_direction="Verify sorted discovery.",
            status="paused",
        )
    )
    assert other.project_id == "another-project"
    (runtime.projects_root / "not-a-project").mkdir()
    (runtime.projects_root / "project-link").symlink_to(
        runtime.projects_root / "app-project",
        target_is_directory=True,
    )
    app = GenerativeUIApplication(runtime)

    discovery = app.discover_projects()
    renderer = app.current_renderer("app-project")

    assert [(item.project_id, item.revision) for item in discovery.projects] == [
        ("another-project", 0),
        ("app-project", 2),
    ]
    assert renderer.shell.shell_id == "scitaste-research-shell"
    assert renderer.execution_authority == "none"
    assert renderer.actions[0].event_type == "surface_action_requested"
    assert _audit_path(runtime).is_file()


def test_valid_event_is_persisted_once_without_project_or_execution_mutation(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    surface = app.current_surface("app-project")
    event = make_surface_event(
        surface,
        event_id="accepted-event",
        action_id="request-current-run-approval",
    )
    manifest_path = runtime.projects_root / "app-project/PROJECT.json"
    before = manifest_path.read_bytes()

    receipt = app.submit_event("app-project", event)

    assert receipt.status == "proposal_pending"
    assert receipt.execution_authority == "none"
    assert receipt.next_boundary == "deterministic_controller"
    assert receipt.proposal.authority == "proposal_only"
    assert manifest_path.read_bytes() == before
    records = SurfaceAuditLog(_audit_path(runtime)).records()
    assert [record.payload.kind for record in records] == [
        "surface_opened",
        "proposal_issued",
    ]


def test_malformed_cross_project_stale_and_unknown_events_do_not_extend_audit(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    surface = app.current_surface("app-project")
    event = make_surface_event(
        surface,
        event_id="rejected-event",
        action_id="request-current-run-approval",
    )
    audit = _audit_path(runtime)
    before = audit.read_bytes()

    for client_authored_field in (
        "surface",
        "components",
        "proposal",
        "evidence_refs",
        "receipt",
    ):
        malformed = event.model_dump(mode="json")
        malformed[client_authored_field] = {"command": "run"}
        with pytest.raises(ValidationError):
            app.submit_event("app-project", malformed)
    with pytest.raises(StaleSurfaceError, match="project_id"):
        app.submit_event("another-project", event)
    with pytest.raises(StaleSurfaceError, match="stale bindings"):
        app.submit_event(
            "app-project",
            event.model_copy(update={"surface_fingerprint": "0" * 64}),
        )
    with pytest.raises(UnknownActionError):
        app.submit_event(
            "app-project",
            event.model_copy(update={"action_id": "unregistered-action"}),
        )

    assert audit.read_bytes() == before


def test_artifact_change_between_get_and_post_invalidates_old_event(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    surface = app.current_surface("app-project")
    event = make_surface_event(
        surface,
        event_id="stale-after-artifact-change",
        action_id="request-current-run-approval",
    )
    old_audit = _audit_path(runtime)
    before = old_audit.read_bytes()
    (runtime.projects_root / "app-project/runs/trusted-run/execution.json").write_text(
        '{"status":"changed-outside-project-revision"}\n',
        encoding="utf-8",
    )

    with pytest.raises(StaleSurfaceError):
        app.submit_event("app-project", event)

    assert old_audit.read_bytes() == before
    assert len(list(old_audit.parent.glob("*.jsonl"))) == 1


def test_restart_replays_audit_and_retains_duplicate_event_protection(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    first_app = GenerativeUIApplication(runtime)
    surface = first_app.current_surface("app-project")
    event = make_surface_event(
        surface,
        event_id="restart-stable-event",
        action_id="request-current-run-approval",
    )
    first_app.submit_event("app-project", event)
    audit = _audit_path(runtime)
    before = audit.read_bytes()

    restarted_app = GenerativeUIApplication(ProjectRuntime(runtime.outputs_root))
    with pytest.raises(DuplicateEventError):
        restarted_app.submit_event("app-project", event)

    assert audit.read_bytes() == before
    assert len(SurfaceAuditLog(audit).records()) == 2


def test_concurrent_events_serialize_without_lost_audit_records(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    surface = app.current_surface("app-project")

    def submit(index: int) -> str:
        event = make_surface_event(
            surface,
            event_id=f"concurrent-app-event-{index}",
            action_id="request-current-run-approval",
        )
        return app.submit_event("app-project", event).event_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        accepted = list(executor.map(submit, range(8)))

    assert accepted == [f"concurrent-app-event-{index}" for index in range(8)]
    records = SurfaceAuditLog(_audit_path(runtime)).records()
    assert [record.sequence for record in records] == list(range(9))
    assert len({record.record_sha256 for record in records}) == 9


def test_tampered_project_owned_audit_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    app.current_surface("app-project")
    audit = _audit_path(runtime)
    payload = json.loads(audit.read_text(encoding="utf-8"))
    payload["record_sha256"] = "0" * 64
    audit.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        GenerativeUIApplication(runtime).current_surface("app-project")


def test_application_rejects_symlinked_projects_root_before_audit_write(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    projects_root = runtime.projects_root
    detached = runtime.outputs_root / "detached-projects"
    projects_root.rename(detached)
    projects_root.symlink_to(detached, target_is_directory=True)

    with pytest.raises(AuditIntegrityError, match="projects root"):
        GenerativeUIApplication(runtime).current_surface("app-project")

    assert not (detached / "app-project/.generative-ui").exists()


def test_application_audits_inspection_and_restart_duplicate_protection(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_paper(tmp_path)
    query = PaperEvidenceQuery(project_id="paper-app", paper_id="paper-one")
    app = GenerativeUIApplication(runtime)
    surface = WorkspaceSurfaceFactory(runtime).build_surface(query)
    app.current_workspace(query)
    artifact = next(
        item for item in surface.components if item.component is TrustedComponent.ARTIFACT_VIEWER
    )
    event = make_artifact_inspection_event(
        surface,
        event_id="application-inspection",
        artifact_ref_id=artifact.data["artifact_ref_id"],
    )

    document = app.inspect_workspace_artifact(query, event)

    audit_path = next((runtime.projects_root / "paper-app/.generative-ui/audits").glob("*.jsonl"))
    records = SurfaceAuditLog(audit_path).records()
    assert isinstance(records[-1].payload, ArtifactInspectedAudit)
    assert records[-1].payload.receipt == document.receipt
    restarted = GenerativeUIApplication(ProjectRuntime(runtime.outputs_root))
    with pytest.raises(DuplicateEventError):
        restarted.inspect_workspace_artifact(query, event)


def test_pending_workspace_exposes_verified_proposals_without_controller_authority(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    query = RunStageQuery(project_id="app-project", run_id="trusted-run")
    document = app.current_workspace(query)
    renderer = document.renderer
    event = SurfaceEvent(
        event_id="workspace-pending-history",
        project_id=renderer.project_id,
        surface_id=renderer.surface_id,
        surface_revision=renderer.surface_revision,
        surface_fingerprint=renderer.surface_fingerprint,
        snapshot_revision=renderer.snapshot.snapshot_revision,
        snapshot_sha256=renderer.snapshot.snapshot_sha256,
        action_id=renderer.actions[0].action_id,
    )
    app.submit_workspace_event(query, event)

    pending = app.current_workspace(PendingProposalsQuery(project_id="app-project"))
    component = next(
        item
        for item in pending.renderer.components
        if item.renderer is TrustedComponent.PENDING_PROPOSAL_LIST
    )

    assert component.data["proposals"] == [
        {
            "action_id": event.action_id,
            "audit_ref_id": component.evidence_ref_ids[0],
            "event_id": event.event_id,
            "execution_authority": "none",
            "next_boundary": "deterministic_controller",
            "snapshot_revision": event.snapshot_revision,
            "status": "proposal_pending",
            "surface_id": event.surface_id,
            "surface_revision": event.surface_revision,
        }
    ]
    audit_ref = next(
        item
        for item in pending.renderer.snapshot.evidence_refs
        if item.evidence_id == component.evidence_ref_ids[0]
    )
    audit_bytes = (runtime.projects_root / "app-project" / audit_ref.locator).read_bytes()
    assert audit_ref.sha256 == hashlib.sha256(audit_bytes).hexdigest()


def test_application_records_controller_decision_and_removes_pending_proposal(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    query = RunStageQuery(project_id="app-project", run_id="trusted-run")
    renderer = app.current_workspace(query).renderer
    event = SurfaceEvent(
        event_id="workspace-controller-history",
        project_id=renderer.project_id,
        surface_id=renderer.surface_id,
        surface_revision=renderer.surface_revision,
        surface_fingerprint=renderer.surface_fingerprint,
        snapshot_revision=renderer.snapshot.snapshot_revision,
        snapshot_sha256=renderer.snapshot.snapshot_sha256,
        action_id=renderer.actions[0].action_id,
    )
    receipt = app.submit_workspace_event(query, event)

    decision = app.decide_workspace_proposal(
        query,
        ProposalControllerRequest(
            controller_request_id="controller-workspace-approval",
            proposal_event_id=receipt.event_id,
            requested_decision="approve",
            human_confirmation=True,
        ),
    )

    assert decision.status == "authorized"
    assert decision.next_boundary == "selection_registry"
    assert decision.execution_authority == "approved_handoff"
    assert decision.state_mutation_authorized is False
    records = SurfaceAuditLog(_audit_path(runtime)).records()
    assert isinstance(records[-1].payload, ProposalControlledAudit)
    pending = app.current_workspace(PendingProposalsQuery(project_id="app-project"))
    assert all(
        item.renderer is not TrustedComponent.PENDING_PROPOSAL_LIST
        for item in pending.renderer.components
    )

    with pytest.raises(DuplicateEventError):
        app.decide_workspace_proposal(
            query,
            ProposalControllerRequest(
                controller_request_id="controller-workspace-retry",
                proposal_event_id=receipt.event_id,
                requested_decision="reject",
            ),
        )


def test_pending_workspace_rejects_valid_audit_copied_from_another_project(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path, project_id="project-a")
    _runtime_with_action(tmp_path, project_id="project-b")
    app = GenerativeUIApplication(runtime)
    query_a = RunStageQuery(project_id="project-a", run_id="trusted-run")
    query_b = RunStageQuery(project_id="project-b", run_id="trusted-run")
    app.current_workspace(query_a)
    foreign = app.current_workspace(query_b).renderer
    event = SurfaceEvent(
        event_id="foreign-private-event",
        project_id=foreign.project_id,
        surface_id=foreign.surface_id,
        surface_revision=foreign.surface_revision,
        surface_fingerprint=foreign.surface_fingerprint,
        snapshot_revision=foreign.snapshot.snapshot_revision,
        snapshot_sha256=foreign.snapshot.snapshot_sha256,
        action_id=foreign.actions[0].action_id,
    )
    app.submit_workspace_event(query_b, event)
    foreign_audit = _audit_path(runtime, "project-b")
    local_audit_root = runtime.projects_root / "project-a/.generative-ui/audits"
    copyfile(foreign_audit, local_audit_root / "copied-foreign.jsonl")

    with pytest.raises(AuditIntegrityError, match="another project"):
        app.current_workspace(PendingProposalsQuery(project_id="project-a"))


def test_concurrent_inspections_share_one_ordered_hash_chain(tmp_path: Path) -> None:
    runtime = _runtime_with_paper(tmp_path)
    query = PaperEvidenceQuery(project_id="paper-app", paper_id="paper-one")
    app = GenerativeUIApplication(runtime)
    surface = WorkspaceSurfaceFactory(runtime).build_surface(query)
    app.current_workspace(query)
    artifact = next(
        item for item in surface.components if item.component is TrustedComponent.ARTIFACT_VIEWER
    )

    def inspect(index: int) -> str:
        event = make_artifact_inspection_event(
            surface,
            event_id=f"concurrent-inspection-{index}",
            artifact_ref_id=artifact.data["artifact_ref_id"],
        )
        return app.inspect_workspace_artifact(query, event).receipt.event_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        accepted = list(executor.map(inspect, range(8)))

    assert accepted == [f"concurrent-inspection-{index}" for index in range(8)]
    audit_path = next((runtime.projects_root / "paper-app/.generative-ui/audits").glob("*.jsonl"))
    records = SurfaceAuditLog(audit_path).records()
    assert [item.sequence for item in records] == list(range(9))
    assert all(isinstance(item.payload, ArtifactInspectedAudit) for item in records[1:])


def test_pending_history_fails_closed_on_corrupt_audit_and_stays_project_local(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path)
    _runtime_with_action(tmp_path, project_id="other-project")
    app = GenerativeUIApplication(runtime)
    query = RunStageQuery(project_id="app-project", run_id="trusted-run")
    document = app.current_workspace(query)
    renderer = document.renderer
    event = SurfaceEvent(
        event_id="corrupt-history-event",
        project_id=renderer.project_id,
        surface_id=renderer.surface_id,
        surface_revision=renderer.surface_revision,
        surface_fingerprint=renderer.surface_fingerprint,
        snapshot_revision=renderer.snapshot.snapshot_revision,
        snapshot_sha256=renderer.snapshot.snapshot_sha256,
        action_id=renderer.actions[0].action_id,
    )
    app.submit_workspace_event(query, event)

    other = app.current_workspace(PendingProposalsQuery(project_id="other-project"))
    assert all(
        item.renderer is not TrustedComponent.PENDING_PROPOSAL_LIST
        for item in other.renderer.components
    )

    audit_path = next((runtime.projects_root / "app-project/.generative-ui/audits").glob("*.jsonl"))
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    payload["record_sha256"] = "0" * 64
    lines[-1] = json.dumps(payload)
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        app.current_workspace(PendingProposalsQuery(project_id="app-project"))


def test_generated_workspace_survives_restart_for_exact_actions_and_fails_stale(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    catalog = app.quick_intents("app-project")
    request = WorkspaceGenerationRequest(
        quick_catalog_fingerprint=catalog.fingerprint,
        intent_request=QuickIntentRequest(
            project_id="app-project",
            snapshot_revision=catalog.snapshot.snapshot_revision,
            snapshot_sha256=catalog.snapshot.snapshot_sha256,
            quick_intent_id=catalog.intents[0].quick_intent_id,
        ),
    )

    document = app.generate_workspace("app-project", request)

    assert document.status == "generated"
    assert document.renderer is not None
    generation_id = document.renderer.surface_id
    assert app.current_generated_workspace("app-project", generation_id) == document
    assert document.renderer.actions
    action = document.renderer.actions[0]
    event = SurfaceEvent(
        event_id="generated-application-event",
        project_id=document.project_id,
        surface_id=generation_id,
        surface_revision=document.renderer.surface_revision,
        surface_fingerprint=document.renderer.surface_fingerprint,
        snapshot_revision=document.snapshot_revision,
        snapshot_sha256=document.snapshot_sha256,
        action_id=action.action_id,
    )
    receipt = app.submit_generated_event("app-project", generation_id, event)
    assert receipt.status == "proposal_pending"
    assert receipt.execution_authority == "none"

    restarted = GenerativeUIApplication(ProjectRuntime(runtime.outputs_root))
    assert restarted.current_generated_workspace("app-project", generation_id) == document

    snapshot = runtime.open("app-project")
    runtime.update("app-project", expected_revision=snapshot.revision, status="paused")
    with pytest.raises(StaleSurfaceError, match="evidence is stale"):
        app.current_generated_workspace("app-project", generation_id)


def test_generated_workspace_memory_cache_is_bounded_without_losing_project_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application_module, "_MAX_RETAINED_GENERATIONS", 2)
    runtime = _runtime_with_action(tmp_path)
    snapshot = runtime.open("app-project")
    for index, status in enumerate(("failed", "blocked"), start=1):
        snapshot = runtime.begin_run(
            "app-project",
            ProjectRun(
                run_id=f"retention-run-{index}",
                provider="scripted",
                model="retention-fixture",
                condition="cache-bound",
                seed=index,
                status=status,
                evidence_scope="engineering-only",
            ),
            expected_revision=snapshot.revision,
        )
    app = GenerativeUIApplication(runtime)
    catalog = app.quick_intents("app-project")
    assert len(catalog.intents) >= 3
    generation_ids: list[str] = []
    for descriptor in catalog.intents[:3]:
        document = app.generate_workspace(
            "app-project",
            WorkspaceGenerationRequest(
                quick_catalog_fingerprint=catalog.fingerprint,
                intent_request=QuickIntentRequest(
                    project_id="app-project",
                    snapshot_revision=catalog.snapshot.snapshot_revision,
                    snapshot_sha256=catalog.snapshot.snapshot_sha256,
                    quick_intent_id=descriptor.quick_intent_id,
                ),
            ),
        )
        assert document.renderer is not None
        generation_ids.append(document.renderer.surface_id)

    assert len(set(generation_ids)) == 3
    assert app.current_generated_workspace("app-project", generation_ids[0]).status == "generated"
    assert app.current_generated_workspace("app-project", generation_ids[-1]).status == "generated"
    archive_root = runtime.projects_root / "app-project/.generative-ui/generations"
    assert sorted(item.name for item in archive_root.iterdir()) == sorted(generation_ids)


def test_research_workspace_groups_persistent_ordered_turn_pages(tmp_path: Path) -> None:
    runtime = _runtime_with_action(tmp_path)
    app = GenerativeUIApplication(runtime)
    catalog = app.quick_intents("app-project")

    def request(index: int) -> WorkspaceGenerationRequest:
        return WorkspaceGenerationRequest(
            quick_catalog_fingerprint=catalog.fingerprint,
            intent_request=QuickIntentRequest(
                project_id="app-project",
                snapshot_revision=catalog.snapshot.snapshot_revision,
                snapshot_sha256=catalog.snapshot.snapshot_sha256,
                quick_intent_id=catalog.intents[index].quick_intent_id,
            ),
        )

    first = app.create_research_workspace("app-project", request(0))
    second = app.append_research_workspace_turn(
        "app-project",
        first.workspace.workspace_id,
        request(0),
    )

    assert first.turn.turn_id == "turn-0001"
    assert second.turn.turn_id == "turn-0002"
    assert second.turn.parent_turn_id == first.turn.turn_id
    assert second.workspace.turn_ids == ("turn-0001", "turn-0002")
    assert second.workspace.revision == 2
    detail = app.research_workspace_detail(
        "app-project",
        first.workspace.workspace_id,
    )
    assert [item.turn_id for item in detail.turns] == ["turn-0001", "turn-0002"]

    restarted = GenerativeUIApplication(ProjectRuntime(runtime.outputs_root))
    catalog_after_restart = restarted.research_workspace_catalog("app-project")
    assert len(catalog_after_restart.workspaces) == 1
    assert catalog_after_restart.workspaces[0].latest_turn_id == "turn-0002"
    assert (
        restarted.research_workspace_turn(
            "app-project",
            first.workspace.workspace_id,
            "turn-0001",
        ).turn
        == first.turn
    )
