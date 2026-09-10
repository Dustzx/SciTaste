"""Project-owned persistence for exact generated evidence workspaces."""

from __future__ import annotations

import json
import os
import secrets
import stat
from hashlib import sha256
from pathlib import Path

from scitaste.generative_ui.audit import AuditIntegrityError
from scitaste.generative_ui.generation import GeneratedWorkspaceDocument
from scitaste.generative_ui.models import SurfaceSpec
from scitaste.project.models import validate_entry_id, validate_project_id

_MAX_ARCHIVE_FILE_BYTES = 4 * 1024 * 1024


class GeneratedWorkspaceArchive:
    """Persist immutable generated documents beside their project audit trail."""

    def __init__(self, projects_root: Path) -> None:
        self._projects_root = projects_root

    def store(
        self,
        project_id: str,
        generation_id: str,
        document: GeneratedWorkspaceDocument,
        surface: SurfaceSpec,
    ) -> None:
        directory = self._directory(project_id, generation_id, create=True)
        document_bytes = _canonical_bytes(document.model_dump(mode="json"))
        surface_bytes = _canonical_bytes(surface.model_dump(mode="json"))
        manifest_bytes = _canonical_bytes(
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "generation_id": generation_id,
                "document_sha256": sha256(document_bytes).hexdigest(),
                "surface_sha256": sha256(surface_bytes).hexdigest(),
            }
        )
        for name, content in (
            ("document.json", document_bytes),
            ("surface.json", surface_bytes),
            ("archive.json", manifest_bytes),
        ):
            _write_immutable(directory / name, content)

    def load(
        self,
        project_id: str,
        generation_id: str,
    ) -> tuple[GeneratedWorkspaceDocument, SurfaceSpec] | None:
        directory = self._directory(project_id, generation_id, create=False)
        if not directory.exists():
            return None
        manifest_bytes = _read_regular(directory / "archive.json")
        document_bytes = _read_regular(directory / "document.json")
        surface_bytes = _read_regular(directory / "surface.json")
        manifest = json.loads(manifest_bytes)
        expected = {
            "schema_version": "1.0",
            "project_id": project_id,
            "generation_id": generation_id,
            "document_sha256": sha256(document_bytes).hexdigest(),
            "surface_sha256": sha256(surface_bytes).hexdigest(),
        }
        if manifest != expected:
            raise AuditIntegrityError("generated workspace archive hashes do not match")
        document = GeneratedWorkspaceDocument.model_validate_json(document_bytes)
        surface = SurfaceSpec.model_validate_json(surface_bytes)
        return document, surface

    def _directory(self, project_id: str, generation_id: str, *, create: bool) -> Path:
        validate_project_id(project_id)
        validate_entry_id(generation_id, field_name="generation_id")
        projects_root = self._projects_root.resolve(strict=True)
        project = self._projects_root / project_id
        if project.is_symlink():
            raise AuditIntegrityError("generated workspace project cannot be a symbolic link")
        resolved_project = project.resolve(strict=True)
        try:
            resolved_project.relative_to(projects_root)
        except ValueError as exc:
            raise AuditIntegrityError("generated workspace project escapes projects root") from exc
        ui_root = resolved_project / ".generative-ui"
        archive_root = ui_root / "generations"
        directory = archive_root / generation_id
        for candidate in (ui_root, archive_root, directory):
            if candidate.is_symlink():
                raise AuditIntegrityError("generated workspace archive cannot use symbolic links")
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if _read_regular(path) != content:
            raise AuditIntegrityError("generated workspace archive is immutable")
        return
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise AuditIntegrityError("generated workspace archive files cannot be symbolic links")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AuditIntegrityError("generated workspace archive is incomplete") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_ARCHIVE_FILE_BYTES:
            raise AuditIntegrityError("generated workspace archive file is invalid")
        content = os.read(descriptor, _MAX_ARCHIVE_FILE_BYTES + 1)
        if len(content) > _MAX_ARCHIVE_FILE_BYTES:
            raise AuditIntegrityError("generated workspace archive file is too large")
        return content
    finally:
        os.close(descriptor)


__all__ = ["GeneratedWorkspaceArchive"]
