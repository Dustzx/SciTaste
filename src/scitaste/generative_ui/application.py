"""Trusted local application service for project-backed generative surfaces."""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.generative_ui.archive import GeneratedWorkspaceArchive
from scitaste.generative_ui.audit import (
    ArtifactInspectedAudit,
    AuditIntegrityError,
    ProposalControlledAudit,
    ProposalIssuedAudit,
    SurfaceAuditLog,
)
from scitaste.generative_ui.factory import ProjectSurfaceFactory
from scitaste.generative_ui.generation import (
    GeneratedWorkspaceDocument,
    WorkspaceGenerationRequest,
    WorkspaceGenerationService,
)
from scitaste.generative_ui.inspection import (
    ArtifactInspectionDocument,
    ArtifactInspectionEvent,
    ArtifactInspector,
)
from scitaste.generative_ui.intent import QuickIntentCatalog
from scitaste.generative_ui.interaction import (
    DuplicateEventError,
    ProposalControllerDecision,
    ProposalControllerRequest,
    ProposalReceipt,
    StaleSurfaceError,
    SurfaceEvent,
    SurfaceSession,
)
from scitaste.generative_ui.models import SurfaceSpec
from scitaste.generative_ui.planner import PlannerConversationContext, WorkspacePlanner
from scitaste.generative_ui.planning_directive import (
    PlanningDirectivePublication,
    PlanningDirectivePublicationRequest,
    publish_planning_directive,
)
from scitaste.generative_ui.program_revision import (
    ProgramRevisionDecisionRecord,
    ProgramRevisionDecisionRequest,
    ProgramRevisionRecord,
    ProgramRevisionRequest,
    ProgramRevisionService,
    ProgramRevisionView,
)
from scitaste.generative_ui.project_adapter import ProjectSnapshotAdapter
from scitaste.generative_ui.projection import RendererDocument, project_surface
from scitaste.generative_ui.safety import ProjectIdentifier
from scitaste.generative_ui.workspace import (
    ProjectListDocument,
    ProjectListQuery,
    ProjectWorkspaceQuery,
    WorkspaceDocument,
    WorkspaceSurfaceFactory,
    validate_workspace_query,
    workspace_document,
)
from scitaste.generative_ui.workspace_store import (
    ResearchWorkspaceCatalog,
    ResearchWorkspaceDetail,
    ResearchWorkspaceRecord,
    ResearchWorkspaceRenameRequest,
    ResearchWorkspaceStore,
    ResearchWorkspaceTurnDocument,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import validate_entry_id, validate_project_id

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_RETAINED_GENERATIONS = 128


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

    def __init__(
        self,
        runtime: ProjectRuntime,
        *,
        planner: WorkspacePlanner | None = None,
    ) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("GenerativeUIApplication requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._factory = ProjectSurfaceFactory(runtime)
        self._workspace_factory = WorkspaceSurfaceFactory(runtime)
        self._generation_service = WorkspaceGenerationService(runtime, planner=planner)
        self._snapshot_adapter = ProjectSnapshotAdapter(runtime)
        self._artifact_inspector = ArtifactInspector(runtime.projects_root)
        self._generated_archive = GeneratedWorkspaceArchive(runtime.projects_root)
        self._research_workspaces = ResearchWorkspaceStore(runtime.projects_root)
        self._program_revisions = ProgramRevisionService(runtime, planner)
        self._request_lock = RLock()
        self._generated: OrderedDict[
            tuple[str, str],
            tuple[GeneratedWorkspaceDocument, SurfaceSpec],
        ] = OrderedDict()

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

    def project_list_workspace(self) -> ProjectListDocument:
        """Return the authenticated project-list view without opening audit state."""

        return self._workspace_factory.project_list()

    def current_workspace(
        self,
        query: ProjectWorkspaceQuery | dict[str, object],
    ) -> WorkspaceDocument:
        """Build one current server-owned workspace and initialize its audit epoch."""

        parsed = validate_workspace_query(query)
        if isinstance(parsed, ProjectListQuery):
            raise TypeError("project-list query must use project_list_workspace()")
        with self._request_lock:
            surface = self._workspace_factory.build_surface(parsed)
            self._open_audit(surface)
            return workspace_document(parsed, surface)

    def quick_intents(self, project_id: str) -> QuickIntentCatalog:
        """Return current evidence-derived quick intents without invoking a model."""

        validate_project_id(project_id)
        with self._request_lock:
            return self._generation_service.quick_catalog(project_id)

    def propose_program_revision(
        self,
        project_id: str,
        request: ProgramRevisionRequest | dict[str, object],
    ) -> ProgramRevisionRecord:
        """Generate and cache one non-applied evidence-program revision proposal."""

        validate_project_id(project_id)
        parsed = (
            request
            if isinstance(request, ProgramRevisionRequest)
            else ProgramRevisionRequest.model_validate(request)
        )
        if parsed.project_id != project_id:
            raise ValueError("program-revision request belongs to another project")
        with self._request_lock:
            return self._program_revisions.propose(parsed)

    def latest_program_revision(self, project_id: str) -> ProgramRevisionView:
        """Restore the latest cached planning proposal and explicit decision."""

        validate_project_id(project_id)
        with self._request_lock:
            return self._program_revisions.latest(project_id)

    def decide_program_revision(
        self,
        project_id: str,
        request: ProgramRevisionDecisionRequest | dict[str, object],
    ) -> ProgramRevisionDecisionRecord:
        """Accept or reject one exact model-authored planning proposal."""

        validate_project_id(project_id)
        parsed = (
            request
            if isinstance(request, ProgramRevisionDecisionRequest)
            else ProgramRevisionDecisionRequest.model_validate(request)
        )
        if parsed.project_id != project_id:
            raise ValueError("program-revision decision belongs to another project")
        with self._request_lock:
            return self._program_revisions.decide(parsed)

    def publish_program_revision(
        self,
        project_id: str,
        request: PlanningDirectivePublicationRequest | dict[str, object],
    ) -> PlanningDirectivePublication:
        """Publish an accepted proposal as a non-executing project planning version."""

        validate_project_id(project_id)
        parsed = (
            request
            if isinstance(request, PlanningDirectivePublicationRequest)
            else PlanningDirectivePublicationRequest.model_validate(request)
        )
        if parsed.project_id != project_id:
            raise ValueError("planning-directive publication belongs to another project")
        with self._request_lock:
            _, publication = publish_planning_directive(self._runtime, parsed)
            return publication

    def research_workspace_catalog(self, project_id: str) -> ResearchWorkspaceCatalog:
        """List persistent research topics owned by one project."""

        validate_project_id(project_id)
        with self._request_lock:
            return self._research_workspaces.catalog(project_id)

    def research_workspace_detail(
        self,
        project_id: str,
        workspace_id: str,
    ) -> ResearchWorkspaceDetail:
        """Return the ordered turn index for one persistent research topic."""

        validate_project_id(project_id)
        with self._request_lock:
            return self._research_workspaces.detail(project_id, workspace_id)

    def research_workspace_turn(
        self,
        project_id: str,
        workspace_id: str,
        turn_id: str,
    ) -> ResearchWorkspaceTurnDocument:
        """Return one exact generated turn and its current topic manifest."""

        validate_project_id(project_id)
        with self._request_lock:
            return self._research_workspaces.turn(project_id, workspace_id, turn_id)

    def rename_research_workspace(
        self,
        project_id: str,
        workspace_id: str,
        request: ResearchWorkspaceRenameRequest | dict[str, object],
    ) -> ResearchWorkspaceRecord:
        """Rename one topic while preserving its immutable question pages."""

        validate_project_id(project_id)
        validate_entry_id(workspace_id, field_name="workspace_id")
        parsed = (
            request
            if isinstance(request, ResearchWorkspaceRenameRequest)
            else ResearchWorkspaceRenameRequest.model_validate(request)
        )
        with self._request_lock:
            return self._research_workspaces.rename(project_id, workspace_id, parsed)

    def create_research_workspace(
        self,
        project_id: str,
        request: WorkspaceGenerationRequest | dict[str, object],
    ) -> ResearchWorkspaceTurnDocument:
        """Resolve an intent as the first turn of a new persistent topic."""

        parsed = _generation_request(project_id, request)
        if parsed.context_turn_ids:
            raise ValueError("a new research conversation cannot select prior turn context")
        with self._request_lock:
            document = self._generate_workspace(project_id, parsed, context=None)
            return self._research_workspaces.create(project_id, parsed, document)

    def append_research_workspace_turn(
        self,
        project_id: str,
        workspace_id: str,
        request: WorkspaceGenerationRequest | dict[str, object],
    ) -> ResearchWorkspaceTurnDocument:
        """Resolve one follow-up while preserving prior immutable turns."""

        parsed = _generation_request(project_id, request)
        with self._request_lock:
            context = (
                self._research_workspaces.conversation_context(
                    project_id,
                    workspace_id,
                    parsed.context_turn_ids,
                )
                if parsed.context_turn_ids
                else None
            )
            if context is None:
                self._research_workspaces.detail(project_id, workspace_id)
            document = self._generate_workspace(project_id, parsed, context=context)
            return self._research_workspaces.append(
                project_id,
                workspace_id,
                parsed,
                document,
            )

    def generate_workspace(
        self,
        project_id: str,
        request: WorkspaceGenerationRequest | dict[str, object],
    ) -> GeneratedWorkspaceDocument:
        """Resolve and retain one exact generated surface for later safe interactions."""

        parsed = _generation_request(project_id, request)
        if parsed.context_turn_ids:
            raise ValueError("standalone generation cannot select project conversation turns")
        with self._request_lock:
            return self._generate_workspace(project_id, parsed, context=None)

    def _generate_workspace(
        self,
        project_id: str,
        request: WorkspaceGenerationRequest,
        *,
        context: PlannerConversationContext | None,
    ) -> GeneratedWorkspaceDocument:
        output = self._generation_service.generate_output(
            request,
            conversation_context=context,
        )
        if output.surface is not None:
            self._open_audit(output.surface)
            key = (project_id, output.surface.surface_id)
            self._generated_archive.store(
                project_id,
                output.surface.surface_id,
                output.document,
                output.surface,
            )
            self._generated[key] = (output.document, output.surface)
            self._generated.move_to_end(key)
            while len(self._generated) > _MAX_RETAINED_GENERATIONS:
                self._generated.popitem(last=False)
        return GeneratedWorkspaceDocument.model_validate(output.document.model_dump(mode="json"))

    def current_generated_workspace(
        self,
        project_id: str,
        generation_id: str,
    ) -> GeneratedWorkspaceDocument:
        """Replay only an exact surface admitted by this server process."""

        with self._request_lock:
            document, surface = self._current_generated(project_id, generation_id)
            self._open_audit(surface)
            return GeneratedWorkspaceDocument.model_validate(document.model_dump(mode="json"))

    def submit_generated_event(
        self,
        project_id: str,
        generation_id: str,
        event: SurfaceEvent | dict[str, object],
    ) -> ProposalReceipt:
        """Resolve a generated action against its retained server-owned surface."""

        parsed_event = (
            event if isinstance(event, SurfaceEvent) else SurfaceEvent.model_validate(event)
        )
        parsed_event = SurfaceEvent.model_validate(parsed_event.model_dump(mode="json"))
        with self._request_lock:
            _, surface = self._current_generated(project_id, generation_id)
            if parsed_event.project_id != project_id:
                raise StaleSurfaceError("generated event project_id does not match its endpoint")
            provisional = SurfaceSession(surface).activate(parsed_event)
            audit = self._open_audit(surface)
            try:
                record = audit.append_interaction(parsed_event, provisional)
            except AuditIntegrityError as exc:
                if isinstance(exc.__cause__, DuplicateEventError):
                    raise exc.__cause__ from exc
                raise
            if not isinstance(record.payload, ProposalIssuedAudit):
                raise AuditIntegrityError("generated event did not produce a proposal audit record")
            return ProposalReceipt.model_validate(record.payload.receipt.model_dump(mode="json"))

    def decide_generated_proposal(
        self,
        project_id: str,
        generation_id: str,
        request: ProposalControllerRequest | dict[str, object],
    ) -> ProposalControllerDecision:
        """Authorize or reject one audited generated-surface proposal."""

        parsed = (
            request
            if isinstance(request, ProposalControllerRequest)
            else ProposalControllerRequest.model_validate(request)
        )
        parsed = ProposalControllerRequest.model_validate(parsed.model_dump(mode="json"))
        with self._request_lock:
            _, surface = self._current_generated(project_id, generation_id)
            return self._append_controller_decision(self._open_audit(surface), parsed)

    def inspect_generated_artifact(
        self,
        project_id: str,
        generation_id: str,
        event: ArtifactInspectionEvent | dict[str, object],
    ) -> ArtifactInspectionDocument:
        """Inspect evidence visible on one retained generated surface."""

        parsed_event = (
            event
            if isinstance(event, ArtifactInspectionEvent)
            else ArtifactInspectionEvent.model_validate(event)
        )
        parsed_event = ArtifactInspectionEvent.model_validate(parsed_event.model_dump(mode="json"))
        with self._request_lock:
            _, surface = self._current_generated(project_id, generation_id)
            if parsed_event.project_id != project_id:
                raise StaleSurfaceError(
                    "generated inspection project_id does not match its endpoint"
                )
            document = self._artifact_inspector.inspect(surface, parsed_event)
            audit = self._open_audit(surface)
            try:
                record = audit.append_inspection(parsed_event, document.receipt)
            except AuditIntegrityError as exc:
                if isinstance(exc.__cause__, DuplicateEventError):
                    raise exc.__cause__ from exc
                raise
            if not isinstance(record.payload, ArtifactInspectedAudit):
                raise AuditIntegrityError("generated inspection did not produce an audit record")
            return ArtifactInspectionDocument.model_validate(document.model_dump(mode="json"))

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

    def decide_proposal(
        self,
        project_id: str,
        request: ProposalControllerRequest | dict[str, object],
    ) -> ProposalControllerDecision:
        """Authorize or reject one audited fixed-overview proposal."""

        validate_project_id(project_id)
        parsed = (
            request
            if isinstance(request, ProposalControllerRequest)
            else ProposalControllerRequest.model_validate(request)
        )
        parsed = ProposalControllerRequest.model_validate(parsed.model_dump(mode="json"))
        with self._request_lock:
            surface = self._factory.build_project_overview(project_id)
            return self._append_controller_decision(self._open_audit(surface), parsed)

    def submit_workspace_event(
        self,
        query: ProjectWorkspaceQuery | dict[str, object],
        event: SurfaceEvent | dict[str, object],
    ) -> ProposalReceipt:
        """Resolve one event only against the authoritative surface named by its URL query."""

        parsed_query = validate_workspace_query(query)
        if isinstance(parsed_query, ProjectListQuery):
            raise TypeError("project-list view cannot receive proposal events")
        project_id = parsed_query.project_id
        parsed_event = (
            event if isinstance(event, SurfaceEvent) else SurfaceEvent.model_validate(event)
        )
        parsed_event = SurfaceEvent.model_validate(parsed_event.model_dump(mode="json"))
        if parsed_event.project_id != project_id:
            raise StaleSurfaceError("surface event project_id does not match its workspace query")

        with self._request_lock:
            surface = self._workspace_factory.build_surface(parsed_query)
            provisional = SurfaceSession(surface).activate(parsed_event)
            audit = self._open_audit(surface)
            try:
                record = audit.append_interaction(parsed_event, provisional)
            except AuditIntegrityError as exc:
                if isinstance(exc.__cause__, DuplicateEventError):
                    raise exc.__cause__ from exc
                raise
            if not isinstance(record.payload, ProposalIssuedAudit):
                raise AuditIntegrityError("accepted event did not produce a proposal audit record")
            return ProposalReceipt.model_validate(record.payload.receipt.model_dump(mode="json"))

    def decide_workspace_proposal(
        self,
        query: ProjectWorkspaceQuery | dict[str, object],
        request: ProposalControllerRequest | dict[str, object],
    ) -> ProposalControllerDecision:
        """Authorize or reject one audited workspace proposal."""

        parsed_query = validate_workspace_query(query)
        if isinstance(parsed_query, ProjectListQuery):
            raise TypeError("project-list view cannot control proposals")
        parsed = (
            request
            if isinstance(request, ProposalControllerRequest)
            else ProposalControllerRequest.model_validate(request)
        )
        parsed = ProposalControllerRequest.model_validate(parsed.model_dump(mode="json"))
        with self._request_lock:
            surface = self._workspace_factory.build_surface(parsed_query)
            return self._append_controller_decision(self._open_audit(surface), parsed)

    @staticmethod
    def _append_controller_decision(
        audit: SurfaceAuditLog,
        request: ProposalControllerRequest,
    ) -> ProposalControllerDecision:
        try:
            record = audit.append_controller_decision(request)
        except AuditIntegrityError as exc:
            if isinstance(exc.__cause__, DuplicateEventError):
                raise exc.__cause__ from exc
            raise
        if not isinstance(record.payload, ProposalControlledAudit):
            raise AuditIntegrityError("controller request produced another audit payload")
        return ProposalControllerDecision.model_validate(
            record.payload.decision.model_dump(mode="json")
        )

    def inspect_workspace_artifact(
        self,
        query: ProjectWorkspaceQuery | dict[str, object],
        event: ArtifactInspectionEvent | dict[str, object],
    ) -> ArtifactInspectionDocument:
        """Inspect one visible artifact and append its identity receipt to the audit chain."""

        parsed_query = validate_workspace_query(query)
        if isinstance(parsed_query, ProjectListQuery):
            raise TypeError("project-list view cannot inspect artifacts")
        parsed_event = (
            event
            if isinstance(event, ArtifactInspectionEvent)
            else ArtifactInspectionEvent.model_validate(event)
        )
        parsed_event = ArtifactInspectionEvent.model_validate(parsed_event.model_dump(mode="json"))
        if parsed_event.project_id != parsed_query.project_id:
            raise StaleSurfaceError("inspection project_id does not match its workspace query")

        with self._request_lock:
            surface = self._workspace_factory.build_surface(parsed_query)
            document = self._artifact_inspector.inspect(surface, parsed_event)
            audit = self._open_audit(surface)
            try:
                record = audit.append_inspection(parsed_event, document.receipt)
            except AuditIntegrityError as exc:
                if isinstance(exc.__cause__, DuplicateEventError):
                    raise exc.__cause__ from exc
                raise
            if not isinstance(record.payload, ArtifactInspectedAudit):
                raise AuditIntegrityError("inspection did not produce an artifact audit record")
            return ArtifactInspectionDocument.model_validate(document.model_dump(mode="json"))

    def _open_audit(self, surface: SurfaceSpec) -> SurfaceAuditLog:
        audit = SurfaceAuditLog(
            self._audit_path(surface),
            expected_project_id=surface.project_id,
        )
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

    def _current_generated(
        self,
        project_id: str,
        generation_id: str,
    ) -> tuple[GeneratedWorkspaceDocument, SurfaceSpec]:
        validate_project_id(project_id)
        validate_entry_id(generation_id, field_name="generation_id")
        key = (project_id, generation_id)
        retained = self._generated.get(key)
        if retained is None:
            retained = self._generated_archive.load(project_id, generation_id)
            if retained is None:
                raise StaleSurfaceError("generated surface is unavailable")
            self._generated[key] = retained
            self._generated.move_to_end(key)
            while len(self._generated) > _MAX_RETAINED_GENERATIONS:
                self._generated.popitem(last=False)
        document, surface = retained
        self._generated.move_to_end(key)
        current = self._snapshot_adapter.build_binding(project_id)
        if current != surface.snapshot:
            raise StaleSurfaceError("generated surface evidence is stale")
        if (
            document.renderer is None
            or document.renderer.surface_id != generation_id
            or document.renderer.surface_fingerprint != surface.fingerprint
        ):
            raise AuditIntegrityError("generated document cache does not match its surface")
        return document, surface

    def _audit_path(self, surface: SurfaceSpec) -> Path:
        project_root = self._runtime.projects_root / surface.project_id
        if self._runtime.projects_root.is_symlink():
            raise AuditIntegrityError("projects root must not be a symbolic link")
        projects_root = self._runtime.projects_root.resolve(strict=True)
        resolved_project = project_root.resolve(strict=True)
        if project_root.is_symlink():
            raise AuditIntegrityError("project UI audit root must not be a symbolic link")
        try:
            resolved_project.relative_to(projects_root)
        except ValueError as exc:
            raise AuditIntegrityError("project UI audit root escapes its projects root") from exc
        ui_root = resolved_project / ".generative-ui"
        audit_root = ui_root / "audits"
        if ui_root.is_symlink() or audit_root.is_symlink():
            raise AuditIntegrityError("project UI audit root must not be a symbolic link")
        identity = (
            f"r{surface.snapshot.snapshot_revision}-"
            f"{surface.snapshot.snapshot_sha256}-{surface.fingerprint}.jsonl"
        )
        return audit_root / identity


def _generation_request(
    project_id: str,
    request: WorkspaceGenerationRequest | dict[str, object],
) -> WorkspaceGenerationRequest:
    validate_project_id(project_id)
    parsed = (
        request
        if isinstance(request, WorkspaceGenerationRequest)
        else WorkspaceGenerationRequest.model_validate(request)
    )
    parsed = WorkspaceGenerationRequest.model_validate(parsed.model_dump(mode="json"))
    if parsed.intent_request.project_id != project_id:
        raise StaleSurfaceError("generation request project_id does not match its endpoint")
    return parsed
