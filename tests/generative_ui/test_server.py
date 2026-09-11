from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

import httpx
import pytest

from scitaste.generative_ui import (
    BearerCredential,
    GenerativeUIApplication,
    LocalServerConfig,
    SurfaceAuditLog,
    TrustedComponent,
    create_http_server,
)
from scitaste.project import PaperManifest, ProjectManifest, ProjectRun, ProjectRuntime

_TOKEN = "local-test-token-20260905"


def _runtime(tmp_path: Path, *, title: str = "Evidence reports 2 < 3 and 5 > 4") -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="http-project",
            title=title,
            research_direction="Render angle-bracket-like evidence as inert text.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        "http-project",
        ProjectRun(
            run_id="http-run",
            provider="scripted",
            model="deterministic-controller",
            condition="full-scitaste",
            seed=3,
            status="complete",
            evidence_scope="engineering-only",
        ),
        expected_revision=snapshot.revision,
    )
    (runtime.projects_root / "http-project/runs/http-run/result.json").write_text(
        "{}\n", encoding="utf-8"
    )
    runtime.select_run("http-project", "http-run", expected_revision=snapshot.revision)
    return runtime


def _paper_runtime(tmp_path: Path) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="http-paper",
            title="HTTP paper inspection",
            research_direction="Expose no general artifact route.",
            status="active",
        )
    )
    paper_dir = runtime.projects_root / "http-paper/papers/paper-one"
    paper_dir.mkdir(parents=True)
    (paper_dir / "main.md").write_text("# HTTP evidence\n", encoding="utf-8")
    runtime.register_paper(
        "http-paper",
        PaperManifest(
            paper_id="paper-one",
            project_id="http-paper",
            title="HTTP inspected paper",
            date="2026-09-05",
            provider="scripted",
            model="deterministic",
            condition="inspection",
            task="http-boundary",
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


@contextmanager
def _running_server(runtime: ProjectRuntime) -> Iterator[str]:
    server = create_http_server(
        GenerativeUIApplication(runtime),
        credential=BearerCredential(_TOKEN),
        config=LocalServerConfig(port=0),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _headers(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _event(renderer: dict[str, object], *, event_id: str = "http-event") -> dict[str, object]:
    snapshot = renderer["snapshot"]
    assert isinstance(snapshot, dict)
    actions = renderer["actions"]
    assert isinstance(actions, list)
    action = actions[0]
    assert isinstance(action, dict)
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": "surface_action_requested",
        "project_id": renderer["project_id"],
        "surface_id": renderer["surface_id"],
        "surface_revision": renderer["surface_revision"],
        "surface_fingerprint": renderer["surface_fingerprint"],
        "snapshot_revision": snapshot["snapshot_revision"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "action_id": action["action_id"],
    }


def _workspace_event(
    document: dict[str, object],
    *,
    event_id: str = "workspace-http-event",
) -> dict[str, object]:
    renderer = document["renderer"]
    assert isinstance(renderer, dict)
    return _event(renderer, event_id=event_id)


def _inspection_event(
    document: dict[str, object],
    *,
    event_id: str = "workspace-inspection",
) -> dict[str, object]:
    renderer = document["renderer"]
    assert isinstance(renderer, dict)
    snapshot = renderer["snapshot"]
    components = renderer["components"]
    assert isinstance(snapshot, dict)
    assert isinstance(components, list)
    artifact = next(item for item in components if item["renderer"] == "ArtifactViewer")
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": "artifact_inspection_requested",
        "project_id": renderer["project_id"],
        "surface_id": renderer["surface_id"],
        "surface_revision": renderer["surface_revision"],
        "surface_fingerprint": renderer["surface_fingerprint"],
        "snapshot_revision": snapshot["snapshot_revision"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "artifact_ref_id": artifact["data"]["artifact_ref_id"],
    }


def _audit(runtime: ProjectRuntime) -> Path:
    matches = list((runtime.projects_root / "http-project/.generative-ui/audits").glob("*.jsonl"))
    assert len(matches) == 1
    return matches[0]


def test_fixed_shell_assets_are_public_local_and_use_only_inert_text_rendering(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        index = httpx.get(origin + "/")
        script = httpx.get(origin + "/assets/app.js")
        locale_script = httpx.get(origin + "/assets/locale.js")
        english = httpx.get(origin + "/assets/locales/en.json")
        chinese = httpx.get(origin + "/assets/locales/zh-CN.json")
        stylesheet = httpx.get(origin + "/assets/app.css")

    assert index.status_code == 200
    assert script.status_code == 200
    assert locale_script.status_code == 200
    assert english.status_code == 200
    assert chinese.status_code == 200
    assert stylesheet.status_code == 200
    assert locale_script.headers["content-type"].startswith("text/javascript")
    assert english.headers["content-type"].startswith("application/json")
    assert chinese.headers["content-type"].startswith("application/json")
    assert "default-src 'self'" in index.headers["content-security-policy"]
    assert "img-src 'self' blob:" in index.headers["content-security-policy"]
    assert "https://" not in index.text
    assert "http://" not in index.text
    assert "credential" not in index.text.lower()
    assert "document.createTextNode" in script.text
    assert ".textContent" in script.text
    assert "innerHTML" not in script.text
    assert "insertAdjacentHTML" not in script.text
    assert "eval(" not in script.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert all(f"{item.value}:" in script.text for item in TrustedComponent)
    assert "/api/v2/workspace/projects" in script.text
    assert '"project-progress"' in script.text
    assert "ProjectProgressBoard: renderProjectProgress" in script.text
    assert 'return {view: "project-progress"' in script.text
    assert 'data-view="project-progress"' in index.text
    assert 'id="workspace-history-list"' in index.text
    assert "loadResearchWorkspaceDetail" in script.text
    assert 'className = "workspace-turn-items"' in script.text
    assert "history.pushState" in script.text
    assert 'window.addEventListener("popstate"' in script.text
    assert 'headers["If-None-Match"]' in script.text
    assert 'class="skip-link"' in index.text
    assert 'aria-label="Research workspace navigation"' in index.text
    assert 'aria-busy="false"' in index.text
    assert 'id="quick-intents"' in index.text
    assert 'id="intent-question"' in index.text
    assert 'id="intent-form"' in index.text
    assert 'id="conversation-context-mode"' in index.text
    assert 'id="bearer-token"' not in index.text
    assert 'id="connect"' not in index.text
    assert 'id="global-home"' in index.text
    assert 'fetch("/session"' in script.text
    assert "project-index-grid" in script.text
    assert "/api/v3/generative/projects/" in script.text
    assert "quick_catalog_fingerprint" in script.text
    assert "context_turn_ids" in script.text
    assert english.json()["generation.accepted"].startswith("Generated from verified evidence")
    assert english.json()["progress.canonical"] == "Canonical evidence snapshot"
    assert english.json()["progress.distribution.subtitle"].startswith("Exact record distribution")
    assert chinese.json()["progress.canonical"] == "权威证据快照"
    assert 'from "/assets/locale.js"' in script.text
    assert "translateMessage" in locale_script.text
    assert "requestCandidateWorkspace" in script.text
    assert "generation-metadata" in script.text
    assert ".plan-emphasis-compact .progress-board" in stylesheet.text
    assert ".generated-blocker-list" in stylesheet.text
    assert "@media (max-width: 1050px)" in stylesheet.text
    assert ".workspace.generated-workspace" in stylesheet.text
    assert "@media (max-width: 720px)" in stylesheet.text
    assert ":focus-visible" in stylesheet.text
    assert "workspace.focus({preventScroll: true})" in script.text
    assert 'workspace.scrollIntoView({block: "start"})' in script.text
    assert 'event_type: "artifact_inspection_requested"' in script.text
    assert "new Blob" in script.text
    catalog_update = script.text[script.text.index("function updateCatalogs") :]
    assert catalog_update.index("resetCatalogs();") < catalog_update.index("const runComponent")
    for selector in ("runSelect", "baselineRun", "candidateRun", "paperSelect"):
        assert f"{selector}.replaceChildren();" in script.text
    project_change = script.text[script.text.index('projectSelect.addEventListener("change"') :]
    assert project_change.index("clearProjectContext(projectSelect.value);") < (
        project_change.index("});")
    )
    project_clear = script.text[script.text.index("function clearProjectContext") :]
    for text in (
        "currentDocument = null;",
        "quickIntentCatalog = null;",
        "resetCatalogs();",
        'intentQuestion.value = "";',
        "workspace.replaceChildren();",
    ):
        assert project_clear.index(text) < project_clear.index("async function loadQuickIntents")
    workspace_load = script.text[script.text.index("async function loadWorkspace") :]
    assert workspace_load.index("resetCatalogs();") < workspace_load.index("setBusy(true);")


def test_loopback_browser_session_is_automatic_and_same_origin_for_mutations(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with (
        _running_server(runtime) as origin,
        httpx.Client(
            base_url=origin,
            trust_env=False,
        ) as client,
    ):
        poisoned = client.get("/session", headers={"Host": "attacker.example"})
        bootstrap = client.get("/session")
        projects = client.get("/api/v1/projects")
        surface = client.get("/api/v1/projects/http-project/surface").json()
        rejected = client.post(
            "/api/v1/projects/http-project/events",
            json=_event(surface, event_id="cookie-cross-origin"),
        )
        accepted = client.post(
            "/api/v1/projects/http-project/events",
            headers={"Origin": origin},
            json=_event(surface, event_id="cookie-same-origin"),
        )

    assert poisoned.status_code == 404
    assert bootstrap.status_code == 204
    cookie = bootstrap.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/api/" in cookie
    assert projects.status_code == 200
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "cross_origin"
    assert accepted.status_code == 202


def test_api_requires_bearer_authentication_without_creating_project_state(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    ui_root = runtime.projects_root / "http-project/.generative-ui"
    with _running_server(runtime) as origin:
        missing = httpx.get(origin + "/api/v1/projects")
        wrong = httpx.get(origin + "/api/v1/projects", headers=_headers("wrong-token-value"))
        queried = httpx.get(origin + f"/api/v1/projects?token={_TOKEN}")
        accepted = httpx.get(origin + "/api/v1/projects", headers=_headers())

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json() == wrong.json()
    assert missing.headers["www-authenticate"] == "Bearer"
    assert queried.status_code == 400
    assert _TOKEN not in queried.text
    assert accepted.status_code == 200
    assert accepted.json() == {
        "projects": [{"project_id": "http-project", "revision": 2}],
        "schema_version": "1.0",
    }
    assert not ui_root.exists()


def test_api_rejects_ambiguous_authorization_headers_and_hides_runtime_banner(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        duplicated = httpx.get(
            origin + "/api/v1/projects",
            headers=[
                ("Authorization", f"Bearer {_TOKEN}"),
                ("Authorization", f"Bearer {_TOKEN}"),
            ],
        )

    assert duplicated.status_code == 401
    assert duplicated.json()["error"]["code"] == "unauthorized"
    assert duplicated.headers["server"] == "SciTasteLocalUI/1.0"
    assert "Python" not in duplicated.headers["server"]


def test_workspace_api_discovers_projects_and_conditionally_refreshes_views(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        unauthenticated = httpx.get(origin + "/api/v2/workspace/projects")
        projects = httpx.get(origin + "/api/v2/workspace/projects", headers=_headers())
        surface = httpx.get(
            origin + "/api/v2/workspace/projects/http-project/project-overview",
            headers=_headers(),
        )
        progress = httpx.get(
            origin + "/api/v2/workspace/projects/http-project/project-progress",
            headers=_headers(),
        )
        unchanged = httpx.get(
            origin + "/api/v2/workspace/projects/http-project/project-overview",
            headers={**_headers(), "If-None-Match": surface.headers["etag"]},
        )

    assert unauthenticated.status_code == 401
    assert projects.status_code == 200
    assert projects.json()["query"]["view"] == "project-list"
    assert projects.json()["projects"][0]["project_id"] == "http-project"
    assert projects.headers["etag"].startswith('"')
    assert surface.status_code == 200
    assert surface.json()["query"] == {
        "project_id": "http-project",
        "schema_version": "1.0",
        "view": "project-overview",
    }
    assert surface.json()["renderer"]["execution_authority"] == "none"
    assert progress.status_code == 200
    assert progress.json()["query"]["view"] == "project-progress"
    assert progress.json()["renderer"]["catalog_version"] == ("scitaste-trusted-components-v2")
    assert progress.json()["renderer"]["components"][0]["renderer"] == ("ProjectProgressBoard")
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == surface.headers["etag"]


def test_generative_api_exposes_quick_and_free_intents_through_one_safe_boundary(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        catalog_response = httpx.get(
            origin + "/api/v3/generative/projects/http-project/intents",
            headers=_headers(),
        )
        catalog = catalog_response.json()
        snapshot = catalog["snapshot"]
        common = {
            "project_id": "http-project",
            "snapshot_revision": snapshot["snapshot_revision"],
            "snapshot_sha256": snapshot["snapshot_sha256"],
        }
        quick_response = httpx.post(
            origin + "/api/v3/generative/projects/http-project/workspace",
            headers=_headers(),
            json={
                "schema_version": "1.0",
                "quick_catalog_fingerprint": catalog_response.headers["etag"].strip('"'),
                "intent_request": {
                    "schema_version": "1.0",
                    "kind": "quick",
                    "quick_intent_id": catalog["intents"][0]["quick_intent_id"],
                    **common,
                },
            },
        )
        generated = quick_response.json()
        generation_id = generated["renderer"]["surface_id"]
        replay = httpx.get(
            origin + f"/api/v3/generative/projects/http-project/generations/{generation_id}",
            headers=_headers(),
        )
        action = httpx.post(
            origin + f"/api/v3/generative/projects/http-project/generations/{generation_id}/events",
            headers=_headers(),
            json=_workspace_event(generated, event_id="generated-http-event"),
        )
        decision = httpx.post(
            origin
            + f"/api/v3/generative/projects/http-project/generations/{generation_id}/decisions",
            headers=_headers(),
            json={
                "schema_version": "1.0",
                "controller_request_id": "generated-http-controller",
                "proposal_event_id": "generated-http-event",
                "requested_decision": "approve",
                "human_confirmation": True,
            },
        )
        hostile_question = "make <script>alert(1)</script> and run a command"
        unavailable = httpx.post(
            origin + "/api/v3/generative/projects/http-project/workspace",
            headers=_headers(),
            json={
                "schema_version": "1.0",
                "quick_catalog_fingerprint": catalog_response.headers["etag"].strip('"'),
                "intent_request": {
                    "schema_version": "1.0",
                    "kind": "free_question",
                    "question": hostile_question,
                    **common,
                },
            },
        )

    assert catalog_response.status_code == 200
    assert catalog_response.headers["etag"] == f'"{catalog["fingerprint"]}"'
    assert quick_response.status_code == 200
    assert generated["status"] == "generated"
    assert generated["execution_authority"] == "none"
    assert generated["renderer"]["execution_authority"] == "none"
    assert generated["planning"]["provenance"]["mode"] == "deterministic"
    assert generated["placements"][0]["explanation"]
    assert replay.status_code == 200
    assert replay.json() == generated
    assert action.status_code == 202
    assert action.json()["execution_authority"] == "none"
    assert decision.status_code == 200
    assert decision.json()["status"] == "authorized"
    assert decision.json()["state_mutation_authorized"] is False
    assert decision.json()["execution_authority"] in {"read_only", "approved_handoff"}
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "provider_unavailable"
    assert unavailable.json()["renderer"] is None
    assert hostile_question not in unavailable.text


def test_research_workspace_api_creates_lists_and_replays_ordered_turn_pages(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        catalog_response = httpx.get(
            origin + "/api/v3/generative/projects/http-project/intents",
            headers=_headers(),
        )
        catalog = catalog_response.json()
        request = {
            "schema_version": "1.0",
            "quick_catalog_fingerprint": catalog["fingerprint"],
            "intent_request": {
                "schema_version": "1.0",
                "kind": "quick",
                "project_id": "http-project",
                "snapshot_revision": catalog["snapshot"]["snapshot_revision"],
                "snapshot_sha256": catalog["snapshot"]["snapshot_sha256"],
                "quick_intent_id": catalog["intents"][0]["quick_intent_id"],
            },
        }
        created = httpx.post(
            origin + "/api/v4/projects/http-project/workspaces",
            headers=_headers(),
            json=request,
        )
        first = created.json()
        workspace_id = first["workspace"]["workspace_id"]
        appended = httpx.post(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}/turns",
            headers=_headers(),
            json={**request, "context_turn_ids": ["turn-0001"]},
        )
        listed = httpx.get(
            origin + "/api/v4/projects/http-project/workspaces",
            headers=_headers(),
        )
        detail = httpx.get(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}",
            headers=_headers(),
        )
        renamed = httpx.patch(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}",
            headers=_headers(),
            json={
                "schema_version": "1.0",
                "expected_metadata_revision": 0,
                "expected_title": first["workspace"]["title"],
                "title": "HTTP conversation title",
            },
        )
        stale_rename = httpx.patch(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}",
            headers=_headers(),
            json={
                "schema_version": "1.0",
                "expected_metadata_revision": 0,
                "expected_title": first["workspace"]["title"],
                "title": "Stale title",
            },
        )
        unsafe_rename = httpx.patch(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}",
            headers=_headers(),
            json={
                "schema_version": "1.0",
                "expected_metadata_revision": 1,
                "expected_title": "HTTP conversation title",
                "title": "unsafe\nconversation title",
            },
        )
        listed_after_rename = httpx.get(
            origin + "/api/v4/projects/http-project/workspaces",
            headers=_headers(),
        )
        replay = httpx.get(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}/turns/turn-0001",
            headers=_headers(),
        )
        turn_path = (
            runtime.projects_root
            / "http-project/.generative-ui/workspaces"
            / workspace_id
            / "turn-0001.json"
        )
        payload = json.loads(turn_path.read_text(encoding="utf-8"))
        progress_component = next(
            item
            for item in payload["document"]["renderer"]["components"]
            if item["renderer"] == "ProjectProgressBoard"
        )
        del progress_component["data"]["lifecycle"]
        turn_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        legacy_detail = httpx.get(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}",
            headers=_headers(),
        )
        incompatible = httpx.get(
            origin + f"/api/v4/projects/http-project/workspaces/{workspace_id}/turns/turn-0001",
            headers=_headers(),
        )

    assert created.status_code == 201
    assert first["turn"]["turn_id"] == "turn-0001"
    assert appended.status_code == 201
    assert appended.json()["turn"]["turn_id"] == "turn-0002"
    assert appended.json()["turn"]["context_turn_ids"] == ["turn-0001"]
    assert appended.json()["turn"]["document"]["conversation_context_sha256"]
    assert listed.status_code == 200
    assert listed.json()["workspaces"][0]["latest_turn_id"] == "turn-0002"
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "HTTP conversation title"
    assert renamed.json()["metadata_revision"] == 1
    assert stale_rename.status_code == 409
    assert stale_rename.json()["error"]["code"] == "stale_workspace"
    assert unsafe_rename.status_code == 400
    assert unsafe_rename.json()["error"]["code"] == "invalid_request"
    assert listed_after_rename.json()["workspaces"][0]["title"] == (
        "HTTP conversation title"
    )
    assert listed_after_rename.headers["etag"] != listed.headers["etag"]
    assert detail.status_code == 200
    assert [item["turn_id"] for item in detail.json()["turns"]] == [
        "turn-0001",
        "turn-0002",
    ]
    assert replay.status_code == 200
    assert replay.json()["turn"] == first["turn"]
    assert legacy_detail.status_code == 200
    assert legacy_detail.json()["turns"][0]["status"] == "archive_incompatible"
    assert incompatible.status_code == 409
    assert incompatible.json()["error"]["code"] == "archived_turn_incompatible"


def test_generative_api_rejects_stale_catalog_cross_project_and_unknown_replay(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        catalog = httpx.get(
            origin + "/api/v3/generative/projects/http-project/intents",
            headers=_headers(),
        ).json()
        request = {
            "schema_version": "1.0",
            "quick_catalog_fingerprint": catalog["fingerprint"],
            "intent_request": {
                "schema_version": "1.0",
                "kind": "quick",
                "project_id": "http-project",
                "snapshot_revision": catalog["snapshot"]["snapshot_revision"],
                "snapshot_sha256": catalog["snapshot"]["snapshot_sha256"],
                "quick_intent_id": catalog["intents"][0]["quick_intent_id"],
            },
        }
        cross = httpx.post(
            origin + "/api/v3/generative/projects/another-project/workspace",
            headers=_headers(),
            json=request,
        )
        snapshot = runtime.open("http-project")
        runtime.update("http-project", expected_revision=snapshot.revision, status="paused")
        stale = httpx.post(
            origin + "/api/v3/generative/projects/http-project/workspace",
            headers=_headers(),
            json=request,
        )
        unknown = httpx.get(
            origin + "/api/v3/generative/projects/http-project/generations/generated-unknown",
            headers=_headers(),
        )

    assert cross.status_code == 409
    assert cross.json()["error"]["code"] == "stale_surface"
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_surface"
    assert unknown.status_code == 409


def test_workspace_deep_links_reject_unknown_and_cross_project_selection(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        unknown_run = httpx.get(
            origin + "/api/v2/workspace/projects/http-project/run-stage-explorer/runs/unknown-run",
            headers=_headers(),
        )
        malformed_view = httpx.get(
            origin + "/api/v2/workspace/projects/http-project/arbitrary-renderer",
            headers=_headers(),
        )
        injected_query = httpx.get(
            origin + "/api/v2/workspace/projects/http-project/project-overview?component=Injected",
            headers=_headers(),
        )

    assert unknown_run.status_code == 404
    assert unknown_run.json()["error"]["code"] == "selection_not_found"
    assert "unknown-run" not in unknown_run.text
    assert malformed_view.status_code == 404
    assert injected_query.status_code == 400


def test_workspace_event_is_resolved_against_its_deep_linked_surface(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    view_path = "/api/v2/workspace/projects/http-project/run-stage-explorer/runs/http-run"
    with _running_server(runtime) as origin:
        workspace = httpx.get(origin + view_path, headers=_headers())
        event = _workspace_event(workspace.json())
        accepted = httpx.post(
            origin + view_path + "/events",
            headers=_headers(),
            json=event,
        )
        duplicate = httpx.post(
            origin + view_path + "/events",
            headers=_headers(),
            json=event,
        )
        wrong_view = httpx.post(
            origin + "/api/v2/workspace/projects/http-project/project-overview/events",
            headers=_headers(),
            json={**event, "event_id": "wrong-view-event"},
        )

    assert workspace.status_code == 200
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "proposal_pending"
    assert accepted.json()["execution_authority"] == "none"
    assert duplicate.status_code == 409
    assert wrong_view.status_code == 409


def test_surface_api_returns_only_fixed_renderer_and_preserves_inert_angle_text(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        response = httpx.get(
            origin + "/api/v1/projects/http-project/surface",
            headers=_headers(),
        )

    assert response.status_code == 200
    renderer = response.json()
    assert renderer["shell"]["shell_id"] == "scitaste-research-shell"
    assert renderer["execution_authority"] == "none"
    assert renderer["components"][0]["title"] == "Evidence reports 2 < 3 and 5 > 4"
    assert '"proposal":' not in response.text
    assert '"payload":' not in response.text
    assert '"rationale":' not in response.text
    assert "command" not in response.text


def test_event_api_rejects_malformed_stale_cross_project_and_duplicate_requests(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        surface_response = httpx.get(
            origin + "/api/v1/projects/http-project/surface",
            headers=_headers(),
        )
        renderer = surface_response.json()
        event = _event(renderer)
        endpoint = origin + "/api/v1/projects/http-project/events"
        cross_endpoint = origin + "/api/v1/projects/another-project/events"

        malformed = {**event, "receipt": {"execution_authority": "granted"}}
        malformed_response = httpx.post(endpoint, headers=_headers(), json=malformed)
        stale_response = httpx.post(
            endpoint,
            headers=_headers(),
            json={**event, "surface_fingerprint": "0" * 64},
        )
        cross_response = httpx.post(cross_endpoint, headers=_headers(), json=event)
        accepted = httpx.post(endpoint, headers=_headers(), json=event)
        duplicate = httpx.post(endpoint, headers=_headers(), json=event)

    assert malformed_response.status_code == 400
    assert stale_response.status_code == 409
    assert cross_response.status_code == 409
    assert "another-project" not in cross_response.text
    assert "app-project" not in cross_response.text
    assert accepted.status_code == 202
    receipt = accepted.json()
    assert receipt["status"] == "proposal_pending"
    assert receipt["execution_authority"] == "none"
    assert receipt["proposal"]["authority"] == "proposal_only"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_event"
    assert len(SurfaceAuditLog(_audit(runtime)).records()) == 2


def test_inspection_api_rehashes_visible_artifact_without_general_file_access(
    tmp_path: Path,
) -> None:
    runtime = _paper_runtime(tmp_path)
    view_path = "/api/v2/workspace/projects/http-paper/paper-evidence/papers/paper-one"
    with _running_server(runtime) as origin:
        workspace = httpx.get(origin + view_path, headers=_headers())
        event = _inspection_event(workspace.json())
        unauthenticated = httpx.post(origin + view_path + "/inspections", json=event)
        forged = httpx.post(
            origin + view_path + "/inspections",
            headers=_headers(),
            json={**event, "locator": "papers/paper-one/main.md"},
        )
        cross_project = httpx.post(
            origin + view_path + "/inspections",
            headers=_headers(),
            json={**event, "project_id": "foreign-project"},
        )
        accepted = httpx.post(
            origin + view_path + "/inspections",
            headers=_headers(),
            json=event,
        )
        duplicate = httpx.post(
            origin + view_path + "/inspections",
            headers=_headers(),
            json=event,
        )
        file_route = httpx.get(
            origin + "/api/v2/workspace/projects/http-paper/artifacts/main.md",
            headers=_headers(),
        )

    assert workspace.status_code == 200
    assert unauthenticated.status_code == 401
    assert forged.status_code == 400
    assert cross_project.status_code == 409
    assert event["artifact_ref_id"] not in cross_project.text
    assert "foreign-project" not in cross_project.text
    assert "main.md" not in cross_project.text
    assert accepted.status_code == 200
    assert accepted.json()["preview_kind"] == "markdown"
    assert accepted.json()["text_content"] == "# HTTP evidence\n"
    assert accepted.json()["receipt"]["execution_authority"] == "none"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_event"
    assert file_route.status_code == 404


def test_changed_artifact_response_and_logs_do_not_expose_its_locator(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _paper_runtime(tmp_path)
    view_path = "/api/v2/workspace/projects/http-paper/paper-evidence/papers/paper-one"
    with _running_server(runtime) as origin:
        workspace = httpx.get(origin + view_path, headers=_headers())
        event = _inspection_event(workspace.json(), event_id="changed-http-artifact")
        artifact = runtime.projects_root / "http-paper/papers/paper-one/main.md"
        artifact.write_text("# Changed evidence\n", encoding="utf-8")
        rejected = httpx.post(
            origin + view_path + "/inspections",
            headers=_headers(),
            json=event,
        )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "artifact_unavailable"
    assert "main.md" not in rejected.text
    assert str(runtime.outputs_root) not in rejected.text
    assert str(runtime.outputs_root) not in caplog.text


def test_api_rejects_wrong_methods_media_types_duplicate_json_keys_and_file_routes(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with _running_server(runtime) as origin:
        wrong_method = httpx.post(origin + "/api/v1/projects", headers=_headers(), json={})
        wrong_media = httpx.post(
            origin + "/api/v1/projects/http-project/events",
            headers={**_headers(), "Content-Type": "text/plain"},
            content="{}",
        )
        duplicate_keys = httpx.post(
            origin + "/api/v1/projects/http-project/events",
            headers={**_headers(), "Content-Type": "application/json"},
            content='{"event_id":"one","event_id":"two"}',
        )
        file_route = httpx.get(
            origin + "/api/v1/projects/http-project/artifacts/PROJECT.json",
            headers=_headers(),
        )

    assert wrong_method.status_code == 405
    assert wrong_media.status_code == 415
    assert duplicate_keys.status_code == 400
    assert file_route.status_code == 404


def test_server_configuration_is_loopback_first_and_credential_is_not_represented() -> None:
    default = LocalServerConfig()
    assert default.host == "127.0.0.1"
    assert default.is_loopback is True
    assert LocalServerConfig(host="localhost").is_loopback is True
    assert LocalServerConfig(host="::1").is_loopback is True
    with pytest.raises(ValueError, match="unsafe exposure acknowledgement"):
        LocalServerConfig(host="0.0.0.0")
    exposed = LocalServerConfig(host="0.0.0.0", unsafe_allow_non_loopback=True)
    assert exposed.is_loopback is False

    credential = BearerCredential(_TOKEN)
    assert credential.accepts(f"Bearer {_TOKEN}") is True
    assert credential.accepts(f"Bearer {_TOKEN}-wrong") is False
    assert _TOKEN not in repr(credential)
