from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui import (
    AuditIntegrityError,
    DuplicateEventError,
    GenerativeUIApplication,
    StaleSurfaceError,
    SurfaceAuditLog,
    UnknownActionError,
    make_surface_event,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime


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

    malformed = event.model_dump(mode="json")
    malformed["proposal"] = {"command": "run"}
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
