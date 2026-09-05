"""Trusted local application service for project-backed generative surfaces."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.generative_ui.audit import (
    AuditIntegrityError,
    ProposalIssuedAudit,
    SurfaceAuditLog,
)
from scitaste.generative_ui.factory import ProjectSurfaceFactory
from scitaste.generative_ui.interaction import (
    DuplicateEventError,
    ProposalReceipt,
    StaleSurfaceError,
    SurfaceEvent,
    SurfaceSession,
)
from scitaste.generative_ui.models import SurfaceSpec
from scitaste.generative_ui.projection import RendererDocument, project_surface
from scitaste.generative_ui.safety import ProjectIdentifier
from scitaste.project import ProjectRuntime
from scitaste.project.models import validate_project_id

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)


class ProjectDiscoveryItem(BaseModel):
    """Minimal authoritative project identity exposed by discovery."""

    model_config = _MODEL_CONFIG

    project_id: ProjectIdentifier
    revision: int = Field(ge=0)


class ProjectDiscoveryDocument(BaseModel):
    """Versioned project-discovery response."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    projects: tuple[ProjectDiscoveryItem, ...]


class GenerativeUIApplication:
    """Resolve current trusted surfaces and persist proposal-only interactions."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("GenerativeUIApplication requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._factory = ProjectSurfaceFactory(runtime)
        self._request_lock = RLock()

    @property
    def outputs_root(self) -> Path:
        """Return the configured root without exposing a mutation API."""

        return self._runtime.outputs_root

    def discover_projects(self) -> ProjectDiscoveryDocument:
        """List canonical project directories that open as valid runtime snapshots."""

        projects: list[ProjectDiscoveryItem] = []
        root = self._runtime.projects_root
        if not root.is_dir():
            return ProjectDiscoveryDocument(projects=())
        for candidate in sorted(root.iterdir(), key=lambda item: item.name):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                validate_project_id(candidate.name)
                snapshot = self._runtime.open(candidate.name)
            except (OSError, ValueError):
                continue
            projects.append(
                ProjectDiscoveryItem(
                    project_id=snapshot.project_id,
                    revision=snapshot.revision,
                )
            )
        return ProjectDiscoveryDocument(projects=tuple(projects))

    def current_surface(self, project_id: str) -> SurfaceSpec:
        """Build the authoritative surface and initialize its project-owned audit epoch."""

        validate_project_id(project_id)
        with self._request_lock:
            surface = self._factory.build_project_overview(project_id)
            self._open_audit(surface)
            return SurfaceSpec.model_validate(surface.model_dump(mode="json"))

    def current_renderer(self, project_id: str) -> RendererDocument:
        """Return only the receiver-facing fixed-shell projection."""

        return project_surface(self.current_surface(project_id))

    def submit_event(
        self,
        project_id: str,
        event: SurfaceEvent | dict[str, object],
    ) -> ProposalReceipt:
        """Persist a validated proposal receipt without approving or executing it."""

        validate_project_id(project_id)
        parsed = event if isinstance(event, SurfaceEvent) else SurfaceEvent.model_validate(event)
        parsed = SurfaceEvent.model_validate(parsed.model_dump(mode="json"))
        if parsed.project_id != project_id:
            raise StaleSurfaceError("surface event project_id does not match the request project")

        with self._request_lock:
            surface = self._factory.build_project_overview(project_id)
            provisional = SurfaceSession(surface).activate(parsed)
            audit = self._open_audit(surface)
            try:
                record = audit.append_interaction(parsed, provisional)
            except AuditIntegrityError as exc:
                if isinstance(exc.__cause__, DuplicateEventError):
                    raise exc.__cause__ from exc
                raise
            if not isinstance(record.payload, ProposalIssuedAudit):
                raise AuditIntegrityError("accepted event did not produce a proposal audit record")
            return ProposalReceipt.model_validate(record.payload.receipt.model_dump(mode="json"))

    def _open_audit(self, surface: SurfaceSpec) -> SurfaceAuditLog:
        audit = SurfaceAuditLog(self._audit_path(surface))
        lock_path = audit.path.with_name(f".{audit.path.name}.lock")
        if audit.path.is_symlink() or lock_path.is_symlink():
            raise AuditIntegrityError("project UI audit paths must not be symbolic links")
        if not os.path.lexists(audit.path):
            try:
                audit.start(surface)
            except FileExistsError:
                pass
        session = audit.replay_session()
        if session.surface != surface:
            raise AuditIntegrityError("project UI audit epoch does not match its current surface")
        return audit

    def _audit_path(self, surface: SurfaceSpec) -> Path:
        project_root = self._runtime.projects_root / surface.project_id
        resolved_project = project_root.resolve(strict=True)
        if project_root.is_symlink():
            raise AuditIntegrityError("project UI audit root must not be a symbolic link")
        ui_root = resolved_project / ".generative-ui"
        audit_root = ui_root / "audits"
        if ui_root.is_symlink() or audit_root.is_symlink():
            raise AuditIntegrityError("project UI audit root must not be a symbolic link")
        audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            audit_root.resolve(strict=True).relative_to(resolved_project)
        except ValueError as exc:
            raise AuditIntegrityError("project UI audit root escapes its project") from exc
        identity = (
            f"r{surface.snapshot.snapshot_revision}-"
            f"{surface.snapshot.snapshot_sha256}-{surface.fingerprint}.jsonl"
        )
        return audit_root / identity
