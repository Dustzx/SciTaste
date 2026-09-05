"""Trusted projection from canonical project state to declarative UI surfaces."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from scitaste.generative_ui.audit import SurfaceAuditLog
from scitaste.generative_ui.models import (
    ActionBinding,
    ActionProposal,
    ComponentSpec,
    EvidenceRef,
    InspectArtifactPayload,
    RequestApprovalPayload,
    SnapshotBinding,
    SurfaceSpec,
)
from scitaste.generative_ui.project_adapter import ProjectSnapshotAdapter
from scitaste.generative_ui.projection import RendererDocument, project_surface
from scitaste.generative_ui.registry import (
    ApprovalSubject,
    EvidenceKind,
    ProposalKind,
    SurfacePurpose,
    TrustedComponent,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import ProjectPaperEntry, ProjectSnapshot, validate_project_id


class ProjectSurfaceError(ValueError):
    """The authoritative project cannot be represented by the safe surface contract."""


class ProjectSurfaceChangedError(ProjectSurfaceError):
    """Project metadata or evidence changed while a surface was being generated."""


class ProjectSurfaceEvidenceError(ProjectSurfaceError):
    """Selected project state lacks the evidence required for a visible component."""


@dataclass(frozen=True)
class ProjectSurfaceOutput:
    """Explicitly persisted surface bundle and its validated in-memory documents."""

    surface: SurfaceSpec
    renderer: RendererDocument
    surface_path: Path
    renderer_path: Path
    audit_path: Path


class ProjectSurfaceFactory:
    """Build surfaces only from a trusted runtime's current authoritative state."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("ProjectSurfaceFactory requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._snapshot_adapter = ProjectSnapshotAdapter(runtime)

    def build_project_overview(self, project_id: str) -> SurfaceSpec:
        """Build one evidence-grounded overview without mutating project state."""

        validate_project_id(project_id)
        binding = self._snapshot_adapter.build_binding(project_id)
        snapshot = self._runtime.open(project_id)
        self._require_matching_authority(project_id, snapshot, binding)

        surface = self._overview_surface(snapshot, binding)

        confirmed_binding = self._snapshot_adapter.build_binding(project_id)
        confirmed_snapshot = self._runtime.open(project_id)
        if (
            confirmed_binding != binding
            or confirmed_snapshot.snapshot_sha256 != snapshot.snapshot_sha256
        ):
            raise ProjectSurfaceChangedError(
                "project metadata or evidence changed while its surface was being generated"
            )
        return SurfaceSpec.model_validate(surface.model_dump(mode="json"))

    def build_project_overview_document(self, project_id: str) -> RendererDocument:
        """Build and project one overview into the trusted fixed-shell document."""

        return project_surface(self.build_project_overview(project_id))

    def write_project_overview(
        self,
        project_id: str,
        destination: str | Path,
    ) -> ProjectSurfaceOutput:
        """Create a new three-file surface bundle; existing destinations are never reused."""

        surface = self.build_project_overview(project_id)
        renderer = project_surface(surface)
        destination = Path(destination)
        if os.path.lexists(destination):
            raise FileExistsError(f"surface output destination already exists: {destination}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir()
        surface_path = destination / "surface.json"
        renderer_path = destination / "renderer.json"
        audit_path = destination / "surface-audit.jsonl"
        _write_new_json(surface_path, surface.model_dump(mode="json"))
        _write_new_json(renderer_path, renderer.model_dump(mode="json"))
        SurfaceAuditLog(audit_path).start(surface)
        return ProjectSurfaceOutput(
            surface=surface,
            renderer=renderer,
            surface_path=surface_path,
            renderer_path=renderer_path,
            audit_path=audit_path,
        )

    @staticmethod
    def _require_matching_authority(
        project_id: str,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> None:
        if snapshot.project_id != project_id or binding.project_id != project_id:
            raise ProjectSurfaceChangedError("project identity changed while building its surface")
        if binding.snapshot_revision != snapshot.revision:
            raise ProjectSurfaceChangedError("project revision changed while building its surface")

    @staticmethod
    def _overview_surface(
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        evidence = _EvidenceIndex(binding)
        manifest_ref = evidence.require(EvidenceKind.PROJECT_MANIFEST, "PROJECT.json")
        components = [
            ComponentSpec(
                component_id="project-summary",
                component=TrustedComponent.PROJECT_SUMMARY_CARD,
                title=snapshot.manifest.title,
                evidence_ref_ids=[manifest_ref.evidence_id],
                data={
                    "project_ref_id": manifest_ref.evidence_id,
                    "project_status": snapshot.manifest.status,
                    "publication_ready": snapshot.manifest.publication_ready,
                    "current_focus": snapshot.manifest.research_direction,
                },
            )
        ]
        actions: list[ActionBinding] = []

        current_run = snapshot.manifest.current_run
        if current_run is not None:
            try:
                run = next(item for item in snapshot.manifest.runs if item.run_id == current_run)
            except (
                StopIteration
            ) as exc:  # ProjectSnapshot validation normally closes this reference
                raise ProjectSurfaceEvidenceError(
                    f"current run is not registered: {current_run}"
                ) from exc
            run_locator = _project_relative(snapshot, snapshot.run_locators[current_run])
            run_ref = evidence.require(EvidenceKind.RUN_RECORD, run_locator)
            components.append(
                ComponentSpec(
                    component_id="current-run-health",
                    component=TrustedComponent.RUN_HEALTH,
                    title="Current run",
                    evidence_ref_ids=[run_ref.evidence_id, manifest_ref.evidence_id],
                    data={
                        "run_ref_id": run_ref.evidence_id,
                        "run_status": run.status,
                    },
                )
            )
            actions.append(_run_approval_action(run_ref))

        if (
            snapshot.manifest.stage_semantics == "autoresearchclaw-stages"
            and snapshot.manifest.completed_stages
            and snapshot.current_stage_locator is not None
        ):
            stage_locator = _project_relative(snapshot, snapshot.current_stage_locator)
            stage_ref = evidence.require(EvidenceKind.STAGE_RECORD, stage_locator)
            components.append(
                ComponentSpec(
                    component_id="stage-timeline",
                    component=TrustedComponent.STAGE_TIMELINE,
                    title="Completed AutoResearchClaw stages",
                    evidence_ref_ids=[stage_ref.evidence_id, manifest_ref.evidence_id],
                    data={
                        "stages": [
                            {
                                "stage_ref_id": stage_ref.evidence_id,
                                "stage": stage,
                                "status": "completed",
                            }
                            for stage in snapshot.manifest.completed_stages
                        ]
                    },
                )
            )

        selected_paper = _selected_paper(snapshot)
        if selected_paper is not None:
            paper_locator = f"papers/{selected_paper.directory_name}/MANIFEST.json"
            paper_ref = evidence.require(EvidenceKind.PAPER, paper_locator)
            components.append(
                ComponentSpec(
                    component_id="current-paper",
                    component=TrustedComponent.PAPER_PREVIEW,
                    title="Current paper",
                    evidence_ref_ids=[paper_ref.evidence_id],
                    data={
                        "paper_ref_id": paper_ref.evidence_id,
                        "paper_title": selected_paper.manifest.title,
                        "paper_status": selected_paper.manifest.status,
                        "publication_ready": selected_paper.manifest.publication_ready,
                        "excerpt": None,
                    },
                )
            )
            actions.append(_paper_approval_action(paper_ref))

            artifact = _selected_artifact(selected_paper, evidence)
            if artifact is not None:
                artifact_ref, media_type = artifact
                components.append(
                    ComponentSpec(
                        component_id="selected-paper-artifact",
                        component=TrustedComponent.ARTIFACT_VIEWER,
                        title="Selected paper artifact",
                        evidence_ref_ids=[artifact_ref.evidence_id],
                        data={
                            "artifact_ref_id": artifact_ref.evidence_id,
                            "artifact_path": artifact_ref.locator,
                            "media_type": media_type,
                        },
                    )
                )
                actions.append(_inspect_artifact_action(artifact_ref))

        return SurfaceSpec(
            surface_id="project-overview",
            revision=binding.snapshot_revision,
            purpose=SurfacePurpose.PROJECT_OVERVIEW,
            title="Project overview",
            project_id=snapshot.project_id,
            snapshot=binding,
            components=components,
            actions=actions,
        )


class _EvidenceIndex:
    def __init__(self, binding: SnapshotBinding) -> None:
        self._by_identity = {(item.kind, item.locator): item for item in binding.evidence_refs}
        if len(self._by_identity) != len(binding.evidence_refs):
            raise ProjectSurfaceEvidenceError("snapshot contains duplicate evidence identities")

    def require(self, kind: EvidenceKind, locator: str) -> EvidenceRef:
        try:
            return self._by_identity[(kind, locator)]
        except KeyError as exc:
            raise ProjectSurfaceEvidenceError(
                f"missing {kind.value} evidence for authoritative locator: {locator}"
            ) from exc


def _project_relative(snapshot: ProjectSnapshot, locator: str) -> str:
    try:
        return (
            PurePosixPath(locator).relative_to(PurePosixPath(snapshot.project_locator)).as_posix()
        )
    except ValueError as exc:
        raise ProjectSurfaceEvidenceError(
            f"authoritative locator is outside its project: {locator}"
        ) from exc


def _selected_paper(snapshot: ProjectSnapshot) -> ProjectPaperEntry | None:
    if snapshot.manifest.current_paper is None:
        return None
    if snapshot.current_paper_locator is None:
        raise ProjectSurfaceEvidenceError("selected paper lacks a current project locator")
    directory_name = PurePosixPath(snapshot.manifest.current_paper).parts[-1]
    try:
        return next(item for item in snapshot.papers if item.directory_name == directory_name)
    except StopIteration as exc:
        raise ProjectSurfaceEvidenceError(
            f"selected paper lacks a valid manifest: {directory_name}"
        ) from exc


_ARTIFACT_MEDIA_TYPES = {
    ".pdf": (0, "application/pdf"),
    ".md": (1, "text/markdown"),
    ".tex": (2, "text/x-tex"),
    ".txt": (3, "text/plain"),
}


def _selected_artifact(
    paper: ProjectPaperEntry,
    evidence: _EvidenceIndex,
) -> tuple[EvidenceRef, str] | None:
    candidates: list[tuple[int, str, str]] = []
    for artifact_locator in paper.manifest.files.values():
        media = _ARTIFACT_MEDIA_TYPES.get(PurePosixPath(artifact_locator).suffix.lower())
        if media is None:
            continue
        priority, media_type = media
        locator = f"papers/{paper.directory_name}/{artifact_locator}"
        candidates.append((priority, locator, media_type))
    if not candidates:
        return None
    _, locator, media_type = min(candidates)
    return evidence.require(EvidenceKind.ARTIFACT, locator), media_type


def _run_approval_action(run_ref: EvidenceRef) -> ActionBinding:
    return ActionBinding(
        action_id="request-current-run-approval",
        component_id="current-run-health",
        label="Request run approval",
        proposal=ActionProposal(
            payload=RequestApprovalPayload(
                kind=ProposalKind.REQUEST_APPROVAL,
                subject=ApprovalSubject.RUN_SELECTION,
                subject_ref_ids=[run_ref.evidence_id],
                question="Approve the current registered run for downstream consideration?",
            ),
            rationale="The deterministic controller must validate any run-selection request.",
            evidence_ref_ids=[run_ref.evidence_id],
            requires_approval=True,
        ),
    )


def _paper_approval_action(paper_ref: EvidenceRef) -> ActionBinding:
    return ActionBinding(
        action_id="request-current-paper-approval",
        component_id="current-paper",
        label="Request paper approval",
        proposal=ActionProposal(
            payload=RequestApprovalPayload(
                kind=ProposalKind.REQUEST_APPROVAL,
                subject=ApprovalSubject.PAPER_SELECTION,
                subject_ref_ids=[paper_ref.evidence_id],
                question="Approve the current registered paper for downstream consideration?",
            ),
            rationale="The deterministic controller must validate any paper-selection request.",
            evidence_ref_ids=[paper_ref.evidence_id],
            requires_approval=True,
        ),
    )


def _inspect_artifact_action(artifact_ref: EvidenceRef) -> ActionBinding:
    return ActionBinding(
        action_id="inspect-selected-paper-artifact",
        component_id="selected-paper-artifact",
        label="Inspect selected artifact",
        proposal=ActionProposal(
            payload=InspectArtifactPayload(
                kind=ProposalKind.INSPECT_ARTIFACT,
                artifact_ref_id=artifact_ref.evidence_id,
            ),
            rationale="Inspect only the selected content-addressed paper artifact.",
            evidence_ref_ids=[artifact_ref.evidence_id],
        ),
    )


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content + "\n")
        handle.flush()
        os.fsync(handle.fileno())
