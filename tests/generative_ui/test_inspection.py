from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.generative_ui.inspection import (
    ArtifactInspectionDocument,
    ArtifactInspectionEvent,
    ArtifactInspector,
    ArtifactTooLargeError,
    ArtifactUnavailableError,
    make_artifact_inspection_event,
)
from scitaste.generative_ui.registry import TrustedComponent
from scitaste.generative_ui.workspace import PaperEvidenceQuery, WorkspaceSurfaceFactory
from scitaste.project import PaperManifest, ProjectManifest, ProjectRuntime


def _paper_runtime(tmp_path: Path, files: dict[str, bytes]) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="inspection-project",
            title="Inspection project",
            research_direction="Inspect only visible content-addressed artifacts.",
            status="active",
        )
    )
    paper_dir = runtime.projects_root / "inspection-project/papers/paper-one"
    paper_dir.mkdir(parents=True)
    manifest_files: dict[str, str] = {}
    for index, (name, content) in enumerate(files.items()):
        (paper_dir / name).write_bytes(content)
        manifest_files[f"Artifact {index}"] = name
    runtime.register_paper(
        "inspection-project",
        PaperManifest(
            paper_id="paper-one",
            project_id="inspection-project",
            title="Bounded previews",
            date="2026-09-05",
            provider="scripted",
            model="deterministic",
            condition="inspection",
            task="security-validation",
            seed=0,
            stage=18,
            status="draft",
            evidence_scope="engineering-only",
            files=manifest_files,
        ),
        directory_name="paper-one",
        expected_revision=snapshot.revision,
    )
    return runtime


def _surface_and_components(runtime: ProjectRuntime):
    surface = WorkspaceSurfaceFactory(runtime).build_surface(
        PaperEvidenceQuery(project_id="inspection-project", paper_id="paper-one")
    )
    components = [
        item for item in surface.components if item.component is TrustedComponent.ARTIFACT_VIEWER
    ]
    return surface, components


@pytest.mark.parametrize(
    ("name", "content", "preview_kind"),
    [
        ("notes.txt", b"plain evidence\n", "text"),
        ("paper.md", b"# Source\n<script>alert('inert')</script>\n", "markdown"),
        ("paper.tex", b"\\section{Evidence}\n", "text"),
        ("metrics.json", b'{"z": 2, "a": 1}\n', "json"),
        ("figure.png", b"\x89PNG\r\n\x1a\nfixture", "image"),
        ("figure.jpg", b"\xff\xd8\xfffixture", "image"),
        ("figure.webp", b"RIFF\x04\x00\x00\x00WEBPfixture", "image"),
        ("paper.pdf", b"%PDF-1.7\nfixture", "pdf_metadata"),
    ],
)
def test_inspector_supports_only_fixed_bounded_preview_kinds(
    tmp_path: Path,
    name: str,
    content: bytes,
    preview_kind: str,
) -> None:
    runtime = _paper_runtime(tmp_path, {name: content})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="inspect-visible-artifact",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )

    document = ArtifactInspector(runtime.projects_root).inspect(surface, event)
    round_trip = ArtifactInspectionDocument.model_validate_json(document.model_dump_json())

    assert round_trip == document
    assert document.preview_kind == preview_kind
    assert document.receipt.execution_authority == "none"
    evidence = {item.evidence_id: item for item in surface.snapshot.evidence_refs}
    assert document.receipt.artifact_sha256 == evidence[event.artifact_ref_id].sha256


def test_markdown_and_html_like_bytes_remain_inert_source_text(tmp_path: Path) -> None:
    source = "# Evidence\n<script>window.location='https://attacker.invalid'</script>\n"
    runtime = _paper_runtime(tmp_path, {"paper.md": source.encode()})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="inspect-hostile-markdown",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )

    document = ArtifactInspector(runtime.projects_root).inspect(surface, event)

    assert document.preview_kind == "markdown"
    assert document.text_content == source
    assert document.image_base64 is None


def test_identity_request_rejects_paths_media_renderers_and_foreign_evidence(
    tmp_path: Path,
) -> None:
    runtime = _paper_runtime(tmp_path, {"paper.md": b"# Evidence\n", "other.txt": b"other\n"})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="identity-only-inspection",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )

    for key in ("path", "locator", "media_type", "renderer", "url", "command"):
        payload = event.model_dump(mode="json")
        payload[key] = "caller-controlled"
        with pytest.raises(ValidationError):
            ArtifactInspectionEvent.model_validate(payload)

    hidden_surface = surface.model_copy(
        update={"components": [surface.components[-1]], "actions": []}
    )
    hidden_event = make_artifact_inspection_event(
        hidden_surface,
        event_id="hidden-artifact-inspection",
        artifact_ref_id=event.artifact_ref_id,
    )
    with pytest.raises(ArtifactUnavailableError, match="not visible"):
        ArtifactInspector(runtime.projects_root).inspect(hidden_surface, hidden_event)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("image.png", b"not-a-png"),
        ("paper.pdf", b"not-a-pdf"),
        ("binary.pdf", b"%PDF-\xff\xff\xff"),
        ("data.json", b'{"duplicate": 1, "duplicate": 2}'),
        ("notes.txt", b"binary\x00text"),
        ("notes.md", b"\xff\xfe"),
    ],
)
def test_mime_confusion_and_invalid_text_fail_closed(
    tmp_path: Path,
    name: str,
    content: bytes,
) -> None:
    runtime = _paper_runtime(tmp_path, {name: content})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="reject-confused-media",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )

    with pytest.raises(ArtifactUnavailableError):
        ArtifactInspector(runtime.projects_root).inspect(surface, event)


def test_changed_oversized_and_symlinked_artifacts_fail_closed(tmp_path: Path) -> None:
    runtime = _paper_runtime(
        tmp_path,
        {"changed.txt": b"original\n", "large.txt": b"x" * (512 * 1024 + 1)},
    )
    surface, components = _surface_and_components(runtime)
    by_path = {item.data["artifact_path"]: item for item in components}
    inspector = ArtifactInspector(runtime.projects_root)

    changed = by_path["papers/paper-one/changed.txt"]
    changed_path = runtime.projects_root / "inspection-project/papers/paper-one/changed.txt"
    changed_path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ArtifactUnavailableError, match="evidence hash"):
        inspector.inspect(
            surface,
            make_artifact_inspection_event(
                surface,
                event_id="changed-artifact",
                artifact_ref_id=changed.data["artifact_ref_id"],
            ),
        )

    large = by_path["papers/paper-one/large.txt"]
    with pytest.raises(ArtifactTooLargeError):
        inspector.inspect(
            surface,
            make_artifact_inspection_event(
                surface,
                event_id="oversized-artifact",
                artifact_ref_id=large.data["artifact_ref_id"],
            ),
        )

    changed_path.unlink()
    changed_path.symlink_to("large.txt")
    with pytest.raises(ArtifactUnavailableError, match="symbolic link"):
        inspector.inspect(
            surface,
            make_artifact_inspection_event(
                surface,
                event_id="symlinked-artifact",
                artifact_ref_id=changed.data["artifact_ref_id"],
            ),
        )


def test_cross_project_and_stale_surface_bindings_are_rejected(tmp_path: Path) -> None:
    runtime = _paper_runtime(tmp_path, {"paper.md": b"# Evidence\n"})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="bound-inspection",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )

    with pytest.raises(ValidationError):
        ArtifactInspectionEvent.model_validate(
            {**event.model_dump(mode="json"), "project_id": "../foreign"}
        )
    with pytest.raises(ArtifactUnavailableError, match="stale bindings"):
        ArtifactInspector(runtime.projects_root).inspect(
            surface,
            event.model_copy(update={"surface_fingerprint": "0" * 64}),
        )


def test_json_preview_is_deterministic(tmp_path: Path) -> None:
    runtime = _paper_runtime(tmp_path, {"metrics.json": b'{"z":2,"a":1}\n'})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="canonical-json-preview",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )

    document = ArtifactInspector(runtime.projects_root).inspect(surface, event)

    assert document.text_content == json.dumps(
        {"a": 1, "z": 2}, indent=2, ensure_ascii=False, sort_keys=True
    )


def test_file_identity_swap_during_read_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _paper_runtime(tmp_path, {"paper.md": b"# Stable bytes\n"})
    surface, components = _surface_and_components(runtime)
    event = make_artifact_inspection_event(
        surface,
        event_id="racing-artifact",
        artifact_ref_id=components[0].data["artifact_ref_id"],
    )
    artifact = runtime.projects_root / "inspection-project/papers/paper-one/paper.md"
    replacement = artifact.with_name("replacement.md")
    original_read = os.read
    swapped = False

    def racing_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        content = original_read(descriptor, count)
        if not swapped:
            swapped = True
            replacement.write_bytes(b"# Stable bytes\n")
            os.replace(replacement, artifact)
        return content

    monkeypatch.setattr("scitaste.generative_ui.inspection.os.read", racing_read)

    with pytest.raises(ArtifactUnavailableError, match="identity changed"):
        ArtifactInspector(runtime.projects_root).inspect(surface, event)
