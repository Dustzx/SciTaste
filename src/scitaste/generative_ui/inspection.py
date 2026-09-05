"""Content-addressed, read-only artifact inspection for trusted workspace views."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.generative_ui.models import EvidenceRef, SurfaceSpec
from scitaste.generative_ui.registry import EvidenceKind, TrustedComponent
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, SafeLocator, Sha256

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    revalidate_instances="always",
)
_TEXT_LIMIT = 512 * 1024
_IMAGE_LIMIT = 5 * 1024 * 1024
_PDF_LIMIT = 20 * 1024 * 1024


class ArtifactInspectionError(ValueError):
    """Base class for failed or unsafe artifact inspection."""


class ArtifactUnavailableError(ArtifactInspectionError):
    """The selected artifact no longer matches its authoritative evidence."""


class ArtifactTooLargeError(ArtifactInspectionError):
    """The artifact exceeds the fixed preview budget for its media type."""


class ArtifactInspectionEvent(BaseModel):
    """Identity-only browser request; it cannot name a path, MIME type, or renderer."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    event_id: SafeIdentifier
    event_type: Literal["artifact_inspection_requested"] = "artifact_inspection_requested"
    project_id: ProjectIdentifier
    surface_id: SafeIdentifier
    surface_revision: int = Field(ge=0)
    surface_fingerprint: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    artifact_ref_id: SafeIdentifier

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ArtifactInspectionReceipt(BaseModel):
    """Audited metadata for one completed read-only inspection."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["inspected"] = "inspected"
    event_id: SafeIdentifier
    event_fingerprint: Sha256
    project_id: ProjectIdentifier
    surface_id: SafeIdentifier
    surface_revision: int = Field(ge=0)
    surface_fingerprint: Sha256
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    artifact_ref_id: SafeIdentifier
    artifact_sha256: Sha256
    locator: SafeLocator
    media_type: Literal[
        "text/plain",
        "text/markdown",
        "text/x-tex",
        "application/json",
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/pdf",
    ]
    byte_length: int = Field(ge=0)
    execution_authority: Literal["none"] = "none"

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ArtifactInspectionDocument(BaseModel):
    """Bounded preview content; active text is retained only as inert source text."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    receipt: ArtifactInspectionReceipt
    preview_kind: Literal["text", "json", "markdown", "image", "pdf_metadata"]
    text_content: str | None = Field(default=None, max_length=_TEXT_LIMIT)
    image_base64: str | None = Field(default=None, max_length=7 * 1024 * 1024)
    pdf_version: str | None = Field(default=None, pattern=r"^PDF-[0-9]\.[0-9]$")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def preview_fields_match_kind(self) -> ArtifactInspectionDocument:
        if self.preview_kind == "image":
            if (
                self.image_base64 is None
                or self.text_content is not None
                or self.pdf_version is not None
            ):
                raise ValueError("image preview requires only base64 image content")
        elif self.preview_kind == "pdf_metadata":
            if (
                self.pdf_version is None
                or self.text_content is not None
                or self.image_base64 is not None
            ):
                raise ValueError("PDF preview requires only verified metadata")
        elif (
            self.text_content is None
            or self.image_base64 is not None
            or self.pdf_version is not None
        ):
            raise ValueError("text preview requires only inert text content")
        return self


class ArtifactInspector:
    """Open only a current surface's visible artifact through a no-follow descriptor."""

    def __init__(self, projects_root: Path) -> None:
        self._projects_root = projects_root

    def inspect(
        self,
        surface: SurfaceSpec,
        event: ArtifactInspectionEvent | dict[str, object],
    ) -> ArtifactInspectionDocument:
        surface = SurfaceSpec.model_validate(surface.model_dump(mode="json"))
        parsed = (
            event
            if isinstance(event, ArtifactInspectionEvent)
            else ArtifactInspectionEvent.model_validate(event)
        )
        parsed = ArtifactInspectionEvent.model_validate(parsed.model_dump(mode="json"))
        evidence, media_type = validate_inspection_binding(surface, parsed)
        content = self._read_verified(surface.project_id, evidence, media_type)
        receipt = ArtifactInspectionReceipt(
            event_id=parsed.event_id,
            event_fingerprint=parsed.fingerprint,
            project_id=parsed.project_id,
            surface_id=parsed.surface_id,
            surface_revision=parsed.surface_revision,
            surface_fingerprint=parsed.surface_fingerprint,
            snapshot_revision=parsed.snapshot_revision,
            snapshot_sha256=parsed.snapshot_sha256,
            artifact_ref_id=parsed.artifact_ref_id,
            artifact_sha256=evidence.sha256,
            locator=evidence.locator,
            media_type=media_type,
            byte_length=len(content),
        )
        return _preview_document(receipt, content)

    def _read_verified(
        self,
        project_id: str,
        evidence: EvidenceRef,
        media_type: str,
    ) -> bytes:
        limit = _MEDIA_LIMITS.get(media_type)
        expected_media = _EXTENSION_MEDIA_TYPES.get(PurePosixPath(evidence.locator).suffix.lower())
        if limit is None or expected_media != media_type:
            raise ArtifactUnavailableError("artifact media type is not allowlisted")
        descriptor = -1
        parent_descriptor = -1
        directory_descriptors: list[int] = []
        relative_parts = PurePosixPath(evidence.locator).parts
        try:
            unresolved_project_root = self._projects_root / project_id
            if unresolved_project_root.is_symlink():
                raise ArtifactUnavailableError("artifact project root must not be a symbolic link")
            project_root = unresolved_project_root.resolve(strict=True)
            current = unresolved_project_root
            for part in relative_parts:
                current = current / part
                if current.is_symlink():
                    raise ArtifactUnavailableError("artifact path contains a symbolic link")
            candidate = unresolved_project_root.joinpath(*relative_parts)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(project_root)
            descriptor, parent_descriptor, directory_descriptors = _open_beneath(
                self._projects_root,
                project_id,
                relative_parts,
            )
        except ArtifactInspectionError:
            raise
        except (OSError, ValueError) as exc:
            raise ArtifactUnavailableError(
                "artifact is unavailable or outside its project"
            ) from exc

        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ArtifactUnavailableError("artifact must be a regular file")
            if metadata.st_size > limit:
                raise ArtifactTooLargeError("artifact exceeds its fixed preview byte limit")
            content = _read_bounded(descriptor, limit)
            final_metadata = os.fstat(descriptor)
            path_metadata = os.stat(
                relative_parts[-1],
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            identity = (metadata.st_dev, metadata.st_ino)
            if identity != (final_metadata.st_dev, final_metadata.st_ino) or identity != (
                path_metadata.st_dev,
                path_metadata.st_ino,
            ):
                raise ArtifactUnavailableError("artifact identity changed during inspection")
            if metadata.st_size != final_metadata.st_size or len(content) != final_metadata.st_size:
                raise ArtifactUnavailableError("artifact size changed during inspection")
        except OSError as exc:
            raise ArtifactUnavailableError("artifact changed during inspection") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            for directory_descriptor in reversed(directory_descriptors):
                os.close(directory_descriptor)

        if hashlib.sha256(content).hexdigest() != evidence.sha256:
            raise ArtifactUnavailableError("artifact content no longer matches its evidence hash")
        _validate_media_content(media_type, content)
        return content


def make_artifact_inspection_event(
    surface: SurfaceSpec,
    *,
    event_id: str,
    artifact_ref_id: str,
) -> ArtifactInspectionEvent:
    """Build a renderer identity envelope without accepting a locator or media type."""

    surface = SurfaceSpec.model_validate(surface.model_dump(mode="json"))
    return ArtifactInspectionEvent(
        event_id=event_id,
        project_id=surface.project_id,
        surface_id=surface.surface_id,
        surface_revision=surface.revision,
        surface_fingerprint=surface.fingerprint,
        snapshot_revision=surface.snapshot.snapshot_revision,
        snapshot_sha256=surface.snapshot.snapshot_sha256,
        artifact_ref_id=artifact_ref_id,
    )


def validate_inspection_binding(
    surface: SurfaceSpec,
    event: ArtifactInspectionEvent,
    receipt: ArtifactInspectionReceipt | None = None,
) -> tuple[EvidenceRef, str]:
    """Validate event/receipt identities against one server-owned visible artifact."""

    expected = {
        "project_id": surface.project_id,
        "surface_id": surface.surface_id,
        "surface_revision": surface.revision,
        "surface_fingerprint": surface.fingerprint,
        "snapshot_revision": surface.snapshot.snapshot_revision,
        "snapshot_sha256": surface.snapshot.snapshot_sha256,
    }
    stale = sorted(key for key, value in expected.items() if getattr(event, key) != value)
    if stale:
        raise ArtifactUnavailableError(f"artifact inspection has stale bindings: {stale}")
    visible = [
        component
        for component in surface.components
        if component.component is TrustedComponent.ARTIFACT_VIEWER
        and component.data.get("artifact_ref_id") == event.artifact_ref_id
    ]
    if len(visible) != 1:
        raise ArtifactUnavailableError("artifact is not visible in the selected workspace view")
    refs = {item.evidence_id: item for item in surface.snapshot.evidence_refs}
    evidence = refs.get(event.artifact_ref_id)
    if evidence is None or evidence.kind is not EvidenceKind.ARTIFACT:
        raise ArtifactUnavailableError("artifact evidence is unavailable")
    media_type = str(visible[0].data["media_type"])
    if receipt is not None:
        expected_receipt = {
            **expected,
            "event_id": event.event_id,
            "event_fingerprint": event.fingerprint,
            "artifact_ref_id": event.artifact_ref_id,
            "artifact_sha256": evidence.sha256,
            "locator": evidence.locator,
            "media_type": media_type,
        }
        mismatched = [
            key for key, value in expected_receipt.items() if getattr(receipt, key) != value
        ]
        if mismatched:
            raise ArtifactUnavailableError("artifact inspection receipt does not match its event")
    return evidence, media_type


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > limit:
        raise ArtifactTooLargeError("artifact exceeds its fixed preview byte limit")
    return content


def _open_beneath(
    projects_root: Path,
    project_id: str,
    relative_parts: tuple[str, ...],
) -> tuple[int, int, list[int]]:
    """Walk each directory through no-follow descriptors to close parent-link races."""

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(projects_root, directory_flags)
        descriptors.append(current)
        current = os.open(project_id, directory_flags, dir_fd=current)
        descriptors.append(current)
        for part in relative_parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
        artifact = os.open(relative_parts[-1], file_flags, dir_fd=current)
        return artifact, current, descriptors
    except OSError:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _preview_document(
    receipt: ArtifactInspectionReceipt,
    content: bytes,
) -> ArtifactInspectionDocument:
    media_type = receipt.media_type
    if media_type in {"image/png", "image/jpeg", "image/webp"}:
        return ArtifactInspectionDocument(
            receipt=receipt,
            preview_kind="image",
            image_base64=base64.b64encode(content).decode("ascii"),
        )
    if media_type == "application/pdf":
        return ArtifactInspectionDocument(
            receipt=receipt,
            preview_kind="pdf_metadata",
            pdf_version=content[1:8].decode("ascii"),
        )
    text = content.decode("utf-8")
    if media_type == "application/json":
        parsed = json.loads(text, object_pairs_hook=_unique_json_object)
        text = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
        kind = "json"
    elif media_type == "text/markdown":
        kind = "markdown"
    else:
        kind = "text"
    return ArtifactInspectionDocument(
        receipt=receipt,
        preview_kind=kind,
        text_content=text,
    )


def _validate_media_content(media_type: str, content: bytes) -> None:
    if media_type in {"text/plain", "text/markdown", "text/x-tex", "application/json"}:
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactUnavailableError("text artifact is not valid UTF-8") from exc
        if "\x00" in decoded:
            raise ArtifactUnavailableError("text artifact contains binary NUL bytes")
        if media_type == "application/json":
            try:
                json.loads(decoded, object_pairs_hook=_unique_json_object)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ArtifactUnavailableError(
                    "JSON artifact is not valid canonical input"
                ) from exc
        return
    signatures = {
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
        "application/pdf": re.match(rb"^%PDF-[12]\.[0-9](?:\s|$)", content) is not None,
    }
    if not signatures.get(media_type, False):
        raise ArtifactUnavailableError("artifact bytes do not match the allowlisted media type")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON artifact object keys must be unique")
        result[key] = value
    return result


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_EXTENSION_MEDIA_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".tex": "text/x-tex",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
_MEDIA_LIMITS = {
    "text/plain": _TEXT_LIMIT,
    "text/markdown": _TEXT_LIMIT,
    "text/x-tex": _TEXT_LIMIT,
    "application/json": _TEXT_LIMIT,
    "image/png": _IMAGE_LIMIT,
    "image/jpeg": _IMAGE_LIMIT,
    "image/webp": _IMAGE_LIMIT,
    "application/pdf": _PDF_LIMIT,
}
