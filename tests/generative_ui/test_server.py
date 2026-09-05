from __future__ import annotations

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
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

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
        stylesheet = httpx.get(origin + "/assets/app.css")

    assert index.status_code == 200
    assert script.status_code == 200
    assert stylesheet.status_code == 200
    assert "default-src 'self'" in index.headers["content-security-policy"]
    assert "https://" not in index.text
    assert "http://" not in index.text
    assert "document.createTextNode" in script.text
    assert ".textContent" in script.text
    assert "innerHTML" not in script.text
    assert "insertAdjacentHTML" not in script.text
    assert "eval(" not in script.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert all(f"{item.value}:" in script.text for item in TrustedComponent)


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
    assert accepted.status_code == 202
    receipt = accepted.json()
    assert receipt["status"] == "proposal_pending"
    assert receipt["execution_authority"] == "none"
    assert receipt["proposal"]["authority"] == "proposal_only"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_event"
    assert len(SurfaceAuditLog(_audit(runtime)).records()) == 2


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
