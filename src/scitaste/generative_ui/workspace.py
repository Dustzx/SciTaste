"""Authoritative query contracts and evidence-native workspace composition."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from scitaste.generative_ui.audit import (
    AuditIntegrityError,
    ProposalControlledAudit,
    ProposalIssuedAudit,
    SurfaceAuditLog,
)
from scitaste.generative_ui.factory import ProjectSurfaceChangedError, ProjectSurfaceFactory
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
from scitaste.generative_ui.safety import (
    ProjectIdentifier,
    SafeIdentifier,
    SafeLocator,
    SafeText,
    Sha256,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import (
    ProjectPaperEntry,
    ProjectRun,
    ProjectSnapshot,
    validate_entry_id,
    validate_project_id,
)

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)


class WorkspaceView(StrEnum):
    """Closed view catalog understood by both server and fixed receiver."""

    PROJECT_LIST = "project-list"
    PROJECT_OVERVIEW = "project-overview"
    PROJECT_PROGRESS = "project-progress"
    RUN_STAGE_EXPLORER = "run-stage-explorer"
    PAPER_EVIDENCE = "paper-evidence"
    RUN_COMPARISON = "run-comparison"
    BLOCKERS = "blockers"
    PENDING_PROPOSALS = "pending-proposals"


def _entry_identifier(value: str) -> str:
    return validate_entry_id(value, field_name="workspace selection")


WorkspaceEntryIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=255),
    AfterValidator(_entry_identifier),
]


class ProjectListQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.PROJECT_LIST] = WorkspaceView.PROJECT_LIST


class ProjectOverviewQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.PROJECT_OVERVIEW] = WorkspaceView.PROJECT_OVERVIEW
    project_id: ProjectIdentifier


class ProjectProgressQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.PROJECT_PROGRESS] = WorkspaceView.PROJECT_PROGRESS
    project_id: ProjectIdentifier


class RunStageQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.RUN_STAGE_EXPLORER] = WorkspaceView.RUN_STAGE_EXPLORER
    project_id: ProjectIdentifier
    run_id: WorkspaceEntryIdentifier | None = None


class PaperEvidenceQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.PAPER_EVIDENCE] = WorkspaceView.PAPER_EVIDENCE
    project_id: ProjectIdentifier
    paper_id: WorkspaceEntryIdentifier | None = None


class RunComparisonQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.RUN_COMPARISON] = WorkspaceView.RUN_COMPARISON
    project_id: ProjectIdentifier
    baseline_run_id: WorkspaceEntryIdentifier
    candidate_run_id: WorkspaceEntryIdentifier

    @model_validator(mode="after")
    def selected_runs_are_distinct(self) -> RunComparisonQuery:
        if self.baseline_run_id == self.candidate_run_id:
            raise ValueError("run comparison selections must be distinct")
        return self


class BlockerQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.BLOCKERS] = WorkspaceView.BLOCKERS
    project_id: ProjectIdentifier
    run_id: WorkspaceEntryIdentifier | None = None


class PendingProposalsQuery(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    view: Literal[WorkspaceView.PENDING_PROPOSALS] = WorkspaceView.PENDING_PROPOSALS
    project_id: ProjectIdentifier


class _ManifestCurrentFocus(BaseModel):
    """Strictly admitted subset of the optional project extension."""

    model_config = _MODEL_CONFIG

    decision_id: SafeIdentifier
    status: SafeText
    selected_option: SafeIdentifier
    online_model: SafeText
    next_gate: SafeText


class _ManifestIteration(BaseModel):
    """Strictly admitted self-development milestone, independent of project ID."""

    model_config = _MODEL_CONFIG

    iteration_id: SafeIdentifier
    date: date
    status: SafeText
    decision: SafeText
    evidence: SafeLocator

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_declared_directory_locator(cls, value: object) -> object:
        if isinstance(value, str) and value.endswith("/") and not value.endswith("//"):
            return value[:-1]
        return value


WorkspaceQuery = Annotated[
    ProjectListQuery
    | ProjectOverviewQuery
    | ProjectProgressQuery
    | RunStageQuery
    | PaperEvidenceQuery
    | RunComparisonQuery
    | BlockerQuery
    | PendingProposalsQuery,
    Field(discriminator="view"),
]
ProjectWorkspaceQuery = (
    ProjectOverviewQuery
    | ProjectProgressQuery
    | RunStageQuery
    | PaperEvidenceQuery
    | RunComparisonQuery
    | BlockerQuery
    | PendingProposalsQuery
)
_QUERY_ADAPTER: TypeAdapter[WorkspaceQuery] = TypeAdapter(WorkspaceQuery)


def validate_workspace_query(value: WorkspaceQuery | dict[str, object]) -> WorkspaceQuery:
    """Revalidate one closed query and reject client-authored display fields."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _QUERY_ADAPTER.validate_python(value)


class WorkspaceProjectItem(BaseModel):
    """Non-content project identity suitable for authenticated navigation."""

    model_config = _MODEL_CONFIG

    project_id: ProjectIdentifier
    revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    manifest_sha256: Sha256
    has_current_run: bool
    paper_count: int = Field(ge=0)


class ProjectListDocument(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    query: ProjectListQuery = Field(default_factory=ProjectListQuery)
    projects: tuple[WorkspaceProjectItem, ...]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class WorkspaceFreshness(BaseModel):
    model_config = _MODEL_CONFIG

    project_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    surface_fingerprint: Sha256
    evidence_count: int = Field(ge=1)


class WorkspaceDocument(BaseModel):
    """One server-owned renderer plus its validated navigation selection."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    query: ProjectWorkspaceQuery = Field(discriminator="view")
    renderer: RendererDocument
    freshness: WorkspaceFreshness

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def query_and_renderer_are_bound(self) -> WorkspaceDocument:
        if self.query.project_id != self.renderer.project_id:
            raise ValueError("workspace query project must match its renderer")
        expected_surface_id = _surface_id(self.query)
        if self.renderer.surface_id != expected_surface_id:
            raise ValueError("workspace surface identity does not match its query")
        expected = WorkspaceFreshness(
            project_revision=self.renderer.snapshot.snapshot_revision,
            snapshot_sha256=self.renderer.snapshot.snapshot_sha256,
            surface_fingerprint=self.renderer.surface_fingerprint,
            evidence_count=len(self.renderer.snapshot.evidence_refs),
        )
        if self.freshness != expected:
            raise ValueError("workspace freshness does not match its renderer")
        return self


class UnknownWorkspaceSelectionError(ValueError):
    """A client selected an identity absent from current authoritative state."""


class WorkspaceSurfaceFactory:
    """Compose closed project views from fresh runtime snapshots and evidence."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("WorkspaceSurfaceFactory requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._adapter = ProjectSnapshotAdapter(runtime)
        self._overview_factory = ProjectSurfaceFactory(runtime)

    def project_list(self) -> ProjectListDocument:
        projects: list[WorkspaceProjectItem] = []
        root = self._runtime.projects_root
        if root.is_dir():
            for candidate in sorted(root.iterdir(), key=lambda item: item.name):
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                try:
                    validate_project_id(candidate.name)
                    snapshot = self._runtime.open(candidate.name)
                except (OSError, ValueError):
                    continue
                projects.append(
                    WorkspaceProjectItem(
                        project_id=snapshot.project_id,
                        revision=snapshot.revision,
                        snapshot_sha256=snapshot.snapshot_sha256,
                        manifest_sha256=snapshot.manifest_sha256,
                        has_current_run=snapshot.manifest.current_run is not None,
                        paper_count=len(snapshot.papers),
                    )
                )
        return ProjectListDocument(projects=tuple(projects))

    def build(
        self,
        query: ProjectWorkspaceQuery | dict[str, object],
    ) -> WorkspaceDocument:
        parsed = _project_query(query)
        return workspace_document(parsed, self.build_surface(parsed))

    def build_surface(
        self,
        query: ProjectWorkspaceQuery | dict[str, object],
    ) -> SurfaceSpec:
        """Build the server-owned surface retained for event resolution."""

        parsed = _project_query(query)
        if isinstance(parsed, ProjectOverviewQuery):
            base = self._overview_factory.build_project_overview(parsed.project_id)
            return SurfaceSpec.model_validate(
                base.model_copy(update={"surface_id": _surface_id(parsed)}).model_dump(mode="json")
            )

        snapshot, binding = self._context(parsed.project_id)
        if isinstance(parsed, ProjectProgressQuery):
            surface = self._project_progress_surface(parsed, snapshot, binding)
        elif isinstance(parsed, RunStageQuery):
            surface = self._run_stage_surface(parsed, snapshot, binding)
        elif isinstance(parsed, PaperEvidenceQuery):
            surface = self._paper_evidence_surface(parsed, snapshot, binding)
        elif isinstance(parsed, RunComparisonQuery):
            surface = self._comparison_surface(parsed, snapshot, binding)
        elif isinstance(parsed, BlockerQuery):
            surface = self._blocker_surface(parsed, snapshot, binding)
        else:
            surface = self._pending_surface(parsed, snapshot, binding)
        self._confirm(snapshot, binding)
        return surface

    def _project_progress_surface(
        self,
        query: ProjectProgressQuery,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        project_ref = _manifest_ref(binding)
        evidence_ref_ids = [project_ref.evidence_id]
        run_refs: dict[str, EvidenceRef] = {}
        run_states: list[str] = []
        attention_rows: list[dict[str, object]] = []
        for run in snapshot.manifest.runs:
            run_ref = _run_ref(snapshot, binding, run.run_id)
            run_refs[run.run_id] = run_ref
            evidence_ref_ids.append(run_ref.evidence_id)
            state = _progress_state(run.status)
            run_states.append(state)
            if state in {"blocked", "failed"}:
                recorded_reasons = _recorded_blockers(run)
                attention_rows.append(
                    {
                        "run_ref_id": run_ref.evidence_id,
                        "run_id": run.run_id,
                        "reported_status": run.status,
                        "classification": state,
                        "reason_code": f"registered-status-{state}",
                        "source_locator": run_ref.locator,
                        "detail_state": "recorded" if recorded_reasons else "unavailable",
                        "recorded_reasons": list(recorded_reasons),
                        "support_ref_ids": [project_ref.evidence_id, run_ref.evidence_id],
                    }
                )

        recent_activity = []
        for run in reversed(snapshot.manifest.runs[-10:]):
            run_ref = run_refs[run.run_id]
            recent_activity.append(
                {
                    "run_ref_id": run_ref.evidence_id,
                    "run_id": run.run_id,
                    "reported_status": run.status,
                    "observed_state": _progress_state(run.status),
                    "provider": run.provider,
                    "model_name": run.model,
                    "condition": run.condition,
                    "evidence_scope": run.evidence_scope,
                    "selected": run.run_id == snapshot.manifest.current_run,
                    "superseded": run.superseded_by is not None,
                    "source_locator": run_ref.locator,
                    "support_ref_ids": [project_ref.evidence_id, run_ref.evidence_id],
                }
            )

        stage_rows: list[dict[str, object]] = []
        if snapshot.manifest.stage_semantics != "autoresearchclaw-stages":
            stage_state = "unavailable"
            stage_reason_code = "alternate-stage-semantics"
        elif not snapshot.manifest.completed_stages:
            stage_state = "empty"
            stage_reason_code = "no-completed-stages-recorded"
        elif snapshot.current_stage_locator is None:
            stage_state = "unavailable"
            stage_reason_code = "completed-stage-evidence-unavailable"
        else:
            stage_ref = _evidence_for_locator(
                binding,
                EvidenceKind.STAGE_RECORD,
                _project_relative(snapshot, snapshot.current_stage_locator),
            )
            evidence_ref_ids.append(stage_ref.evidence_id)
            for stage in snapshot.manifest.completed_stages:
                name, label_en, label_zh = _STAGE_LABELS[stage]
                stage_rows.append(
                    {
                        "stage_ref_id": stage_ref.evidence_id,
                        "stage": stage,
                        "name": name,
                        "label_en": label_en,
                        "label_zh": label_zh,
                        "observed_state": "observed_completed",
                        "artifact_count": _stage_artifact_count(
                            self._runtime,
                            snapshot.project_id,
                            stage,
                        ),
                        "output_locator": f"stages/current/stage-{stage:02d}",
                        "support_ref_ids": [project_ref.evidence_id, stage_ref.evidence_id],
                    }
                )
            stage_state = "available"
            stage_reason_code = "observed-completed-stage-records"

        paper_rows: list[dict[str, object]] = []
        current_paper_id = (
            PurePosixPath(snapshot.manifest.current_paper).parts[-1]
            if snapshot.manifest.current_paper is not None
            else None
        )
        for paper in snapshot.papers:
            paper_ref = _evidence_for_locator(
                binding,
                EvidenceKind.PAPER,
                f"papers/{paper.directory_name}/MANIFEST.json",
            )
            evidence_ref_ids.append(paper_ref.evidence_id)
            paper_rows.append(
                {
                    "paper_ref_id": paper_ref.evidence_id,
                    "paper_id": paper.directory_name,
                    "title": paper.manifest.title,
                    "reported_status": paper.manifest.status,
                    "observed_state": _progress_state(paper.manifest.status),
                    "publication_ready": paper.manifest.publication_ready,
                    "selected": paper.directory_name == current_paper_id,
                    "support_ref_ids": [project_ref.evidence_id, paper_ref.evidence_id],
                }
            )

        focus, focus_status, next_gate = _project_focus(snapshot)
        milestone_state, milestone_reason_code, milestone_rows = _project_milestones(
            snapshot,
            binding,
            project_ref,
        )
        for row in milestone_rows:
            evidence_ref_ids.extend(row["support_ref_ids"])

        current_run_ref_id = None
        current_run_status = None
        current_run_state = None
        current_run_ref_ids: list[str] = []
        if snapshot.manifest.current_run is not None:
            current_run = _require_run(snapshot, snapshot.manifest.current_run)
            current_run_ref_id = run_refs[current_run.run_id].evidence_id
            current_run_status = current_run.status
            current_run_state = _progress_state(current_run.status)
            current_run_ref_ids = [project_ref.evidence_id, current_run_ref_id]

        next_step_candidates = [
            {
                "candidate_id": "review-project-progress",
                "kind": "review_progress",
                "label_code": "review-observed-project-progress",
                "support_ref_ids": [project_ref.evidence_id],
                "target_ids": [],
            }
        ]
        if attention_rows:
            next_step_candidates.append(
                {
                    "candidate_id": "diagnose-recorded-blockers",
                    "kind": "diagnose_blockers",
                    "label_code": "diagnose-blocked-and-failed-runs",
                    "support_ref_ids": list(
                        dict.fromkeys(
                            [
                                project_ref.evidence_id,
                                *(item["run_ref_id"] for item in attention_rows),
                            ]
                        )
                    ),
                    "target_ids": [item["run_id"] for item in attention_rows],
                }
            )
        if len(snapshot.manifest.runs) >= 2:
            comparison_runs = snapshot.manifest.runs[-2:]
            next_step_candidates.append(
                {
                    "candidate_id": "compare-latest-registered-runs",
                    "kind": "compare_runs",
                    "label_code": "compare-latest-registered-run-records",
                    "support_ref_ids": [
                        project_ref.evidence_id,
                        *(run_refs[run.run_id].evidence_id for run in comparison_runs),
                    ],
                    "target_ids": [run.run_id for run in comparison_runs],
                }
            )
        if paper_rows:
            next_step_candidates.append(
                {
                    "candidate_id": "review-registered-paper-evidence",
                    "kind": "review_paper_evidence",
                    "label_code": "review-registered-paper-evidence",
                    "support_ref_ids": [
                        project_ref.evidence_id,
                        *(row["paper_ref_id"] for row in paper_rows),
                    ],
                    "target_ids": [row["paper_id"] for row in paper_rows],
                }
            )
        if next_gate is not None:
            next_step_candidates.append(
                {
                    "candidate_id": "review-declared-next-gate",
                    "kind": "review_next_gate",
                    "label_code": "review-manifest-declared-next-gate",
                    "support_ref_ids": [project_ref.evidence_id],
                    "target_ids": [],
                }
            )

        component = ComponentSpec(
            component_id="project-progress-board",
            component=TrustedComponent.PROJECT_PROGRESS_BOARD,
            title="Evidence-grounded project progress",
            evidence_ref_ids=list(dict.fromkeys(evidence_ref_ids)),
            data={
                "project_ref_id": project_ref.evidence_id,
                "summary_ref_ids": [project_ref.evidence_id],
                "project_status": snapshot.manifest.status,
                "project_state": _progress_state(snapshot.manifest.status),
                "publication_ready": snapshot.manifest.publication_ready,
                "focus": focus,
                "focus_status": focus_status,
                "next_gate": next_gate,
                "focus_ref_ids": [project_ref.evidence_id],
                "stage_semantics": snapshot.manifest.stage_semantics,
                "stage_state": stage_state,
                "stage_reason_code": stage_reason_code,
                "milestone_state": milestone_state,
                "milestone_reason_code": milestone_reason_code,
                "counts": {
                    "runs_registered": len(snapshot.manifest.runs),
                    "runs_completed": run_states.count("observed_completed"),
                    "runs_failed": run_states.count("failed"),
                    "runs_blocked": run_states.count("blocked"),
                    "runs_active": run_states.count("current_work"),
                    "runs_candidates": run_states.count("candidate"),
                    "runs_unavailable": run_states.count("unavailable"),
                    "runs_unknown": run_states.count("unknown"),
                    "completed_stages": len(stage_rows),
                    "papers_registered": len(paper_rows),
                },
                "current_run_id": snapshot.manifest.current_run,
                "current_run_ref_id": current_run_ref_id,
                "current_run_status": current_run_status,
                "current_run_state": current_run_state,
                "current_run_ref_ids": current_run_ref_ids,
                "current_paper_id": current_paper_id,
                "recent_activity": recent_activity,
                "activity_total": len(snapshot.manifest.runs),
                "activity_truncated": len(snapshot.manifest.runs) > len(recent_activity),
                "stages": stage_rows,
                "papers": paper_rows,
                "milestones": milestone_rows,
                "attention": attention_rows,
                "next_step_candidates": next_step_candidates,
            },
        )
        return _surface(query, snapshot, binding, components=[component])

    def _context(self, project_id: str) -> tuple[ProjectSnapshot, SnapshotBinding]:
        validate_project_id(project_id)
        binding = self._adapter.build_binding(project_id)
        snapshot = self._runtime.open(project_id)
        if (
            snapshot.project_id != binding.project_id
            or snapshot.revision != binding.snapshot_revision
        ):
            raise ProjectSurfaceChangedError("project changed while opening its workspace")
        return snapshot, binding

    def _confirm(self, snapshot: ProjectSnapshot, binding: SnapshotBinding) -> None:
        confirmed_binding = self._adapter.build_binding(snapshot.project_id)
        confirmed_snapshot = self._runtime.open(snapshot.project_id)
        if (
            confirmed_binding != binding
            or confirmed_snapshot.snapshot_sha256 != snapshot.snapshot_sha256
        ):
            raise ProjectSurfaceChangedError("project changed while composing its workspace")

    def _run_stage_surface(
        self,
        query: RunStageQuery,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        project_ref = _manifest_ref(binding)
        if query.run_id is not None:
            _require_run(snapshot, query.run_id)
        if not snapshot.manifest.runs:
            return _surface(
                query,
                snapshot,
                binding,
                components=[_notice(project_ref, "runs", "empty", "no-registered-runs")],
            )

        selected_id = (
            query.run_id or snapshot.manifest.current_run or snapshot.manifest.runs[0].run_id
        )
        selected = _require_run(snapshot, selected_id)
        run_rows = []
        evidence_ref_ids = [project_ref.evidence_id]
        for run in snapshot.manifest.runs:
            run_ref = _run_ref(snapshot, binding, run.run_id)
            evidence_ref_ids.append(run_ref.evidence_id)
            outcome = _run_outcome(run.status)
            run_rows.append(
                {
                    "run_ref_id": run_ref.evidence_id,
                    "run_id": run.run_id,
                    "provider": run.provider,
                    "model_name": run.model,
                    "condition": run.condition,
                    "seed": run.seed,
                    "status": run.status,
                    "evidence_scope": run.evidence_scope,
                    "selected": run.run_id == selected_id,
                    "outcome": outcome,
                    "summary_code": f"run-{outcome}",
                }
            )

        stages: list[dict[str, object]] = []
        stage_state = "empty"
        if selected.run_id != snapshot.manifest.current_run:
            stage_state = "unavailable"
        elif snapshot.manifest.stage_semantics != "autoresearchclaw-stages":
            stage_state = "unavailable"
        elif snapshot.manifest.completed_stages and snapshot.current_stage_locator is not None:
            stage_ref = _evidence_for_locator(
                binding,
                EvidenceKind.STAGE_RECORD,
                _project_relative(snapshot, snapshot.current_stage_locator),
            )
            evidence_ref_ids.append(stage_ref.evidence_id)
            for stage in snapshot.manifest.completed_stages:
                name, label_en, label_zh = _STAGE_LABELS[stage]
                locator = f"stages/current/stage-{stage:02d}"
                stages.append(
                    {
                        "stage_ref_id": stage_ref.evidence_id,
                        "stage": stage,
                        "name": name,
                        "label_en": label_en,
                        "label_zh": label_zh,
                        "status": "completed",
                        "artifact_count": _stage_artifact_count(
                            self._runtime,
                            snapshot.project_id,
                            stage,
                        ),
                        "output_locator": locator,
                        "summary_code": f"stage-{stage:02d}-produced-output",
                    }
                )
            stage_state = "available"

        component = ComponentSpec(
            component_id="run-stage-explorer",
            component=TrustedComponent.RUN_STAGE_EXPLORER,
            title="Runs and stages",
            evidence_ref_ids=list(dict.fromkeys(evidence_ref_ids)),
            data={
                "project_ref_id": project_ref.evidence_id,
                "selected_run_id": selected_id,
                "stage_state": stage_state,
                "runs": run_rows,
                "stages": stages,
            },
        )
        selected_ref = _run_ref(snapshot, binding, selected_id)
        action = _run_approval_action(selected_ref)
        return _surface(query, snapshot, binding, components=[component], actions=[action])

    def _paper_evidence_surface(
        self,
        query: PaperEvidenceQuery,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        project_ref = _manifest_ref(binding)
        if query.paper_id is not None:
            _selected_papers(snapshot, query.paper_id)
        if not snapshot.papers:
            return _surface(
                query,
                snapshot,
                binding,
                components=[_notice(project_ref, "papers", "empty", "no-registered-papers")],
            )
        selected = _selected_papers(snapshot, query.paper_id)
        selected_directory = selected[0].directory_name if query.paper_id is not None else None
        components: list[ComponentSpec] = []
        actions: list[ActionBinding] = []
        scoped_refs: list[EvidenceRef] = []
        for paper in selected:
            paper_locator = f"papers/{paper.directory_name}/MANIFEST.json"
            paper_ref = _evidence_for_locator(binding, EvidenceKind.PAPER, paper_locator)
            scoped_refs.append(paper_ref)
            suffix = _identity_suffix(paper.directory_name)
            components.append(
                ComponentSpec(
                    component_id=f"paper-{suffix}",
                    component=TrustedComponent.PAPER_PREVIEW,
                    title="Registered paper",
                    evidence_ref_ids=[paper_ref.evidence_id],
                    data={
                        "paper_ref_id": paper_ref.evidence_id,
                        "paper_title": paper.manifest.title,
                        "paper_status": paper.manifest.status,
                        "publication_ready": paper.manifest.publication_ready,
                        "excerpt": None,
                    },
                )
            )
            for artifact_locator in paper.manifest.files.values():
                locator = f"papers/{paper.directory_name}/{artifact_locator}"
                artifact_ref = _evidence_for_locator(binding, EvidenceKind.ARTIFACT, locator)
                scoped_refs.append(artifact_ref)
                media_type = _artifact_media_type(locator)
                if media_type is None:
                    continue
                component_id = f"artifact-{_identity_suffix(locator)}"
                components.append(
                    ComponentSpec(
                        component_id=component_id,
                        component=TrustedComponent.ARTIFACT_VIEWER,
                        title="Content-addressed artifact",
                        evidence_ref_ids=[artifact_ref.evidence_id],
                        data={
                            "artifact_ref_id": artifact_ref.evidence_id,
                            "artifact_path": artifact_ref.locator,
                            "media_type": media_type,
                        },
                    )
                )
                actions.append(_artifact_action(component_id, artifact_ref))

        inventory_refs = [project_ref, *scoped_refs]
        components.append(
            ComponentSpec(
                component_id="evidence-inventory",
                component=TrustedComponent.EVIDENCE_INVENTORY,
                title="Evidence provenance",
                evidence_ref_ids=[item.evidence_id for item in inventory_refs],
                data={
                    "project_ref_id": project_ref.evidence_id,
                    "scope": "paper" if selected_directory is not None else "project",
                    "selected_paper_id": selected_directory,
                    "items": [
                        {
                            "evidence_ref_id": item.evidence_id,
                            "kind": item.kind,
                            "locator": item.locator,
                            "sha256": item.sha256,
                            "label": item.label,
                        }
                        for item in scoped_refs
                    ],
                },
            )
        )
        return _surface(query, snapshot, binding, components=components, actions=actions)

    def _comparison_surface(
        self,
        query: RunComparisonQuery,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        baseline = _require_run(snapshot, query.baseline_run_id)
        candidate = _require_run(snapshot, query.candidate_run_id)
        baseline_ref = _run_ref(snapshot, binding, baseline.run_id)
        candidate_ref = _run_ref(snapshot, binding, candidate.run_id)
        component = ComponentSpec(
            component_id="run-comparison-panel",
            component=TrustedComponent.RUN_COMPARISON_PANEL,
            title="Registered run comparison",
            evidence_ref_ids=[baseline_ref.evidence_id, candidate_ref.evidence_id],
            data={
                "baseline": _compared_run(baseline, baseline_ref),
                "candidate": _compared_run(candidate, candidate_ref),
                "metrics_state": "unavailable",
                "metrics_reason_code": "no-registered-comparable-metrics",
                "metrics": {},
            },
        )
        return _surface(query, snapshot, binding, components=[component])

    def _blocker_surface(
        self,
        query: BlockerQuery,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        project_ref = _manifest_ref(binding)
        selected_runs = (
            [_require_run(snapshot, query.run_id)]
            if query.run_id is not None
            else list(snapshot.manifest.runs)
        )
        rows = []
        refs = []
        for run in selected_runs:
            outcome = _run_outcome(run.status)
            if outcome not in {"blocked", "failed"}:
                continue
            run_ref = _run_ref(snapshot, binding, run.run_id)
            recorded_reasons = _recorded_blockers(run)
            refs.append(run_ref)
            rows.append(
                {
                    "run_ref_id": run_ref.evidence_id,
                    "run_id": run.run_id,
                    "run_status": run.status,
                    "classification": outcome,
                    "reason_code": f"registered-status-{outcome}",
                    "source_locator": run_ref.locator,
                    "detail_state": "recorded" if recorded_reasons else "unavailable",
                    "recorded_reasons": list(recorded_reasons),
                }
            )
        if not rows:
            return _surface(
                query,
                snapshot,
                binding,
                components=[_notice(project_ref, "blockers", "empty", "no-failed-or-blocked-runs")],
            )
        component = ComponentSpec(
            component_id="run-blocker-panel",
            component=TrustedComponent.RUN_BLOCKER_PANEL,
            title="Failed and blocked runs",
            evidence_ref_ids=[item.evidence_id for item in refs],
            data={"blockers": rows},
        )
        return _surface(query, snapshot, binding, components=[component])

    def _pending_surface(
        self,
        query: PendingProposalsQuery,
        snapshot: ProjectSnapshot,
        binding: SnapshotBinding,
    ) -> SurfaceSpec:
        project_ref = _manifest_ref(binding)
        audit_refs, proposals = _verified_pending_proposals(
            self._runtime.projects_root,
            snapshot.project_id,
        )
        confirmed_history = _verified_pending_proposals(
            self._runtime.projects_root,
            snapshot.project_id,
        )
        if confirmed_history != (audit_refs, proposals):
            raise ProjectSurfaceChangedError("project audit changed while composing its workspace")
        if audit_refs:
            binding = SnapshotBinding.from_trusted_evidence(
                project_id=binding.project_id,
                snapshot_revision=binding.snapshot_revision,
                evidence_refs=[*binding.evidence_refs, *audit_refs],
            )
        if proposals:
            return _surface(
                query,
                snapshot,
                binding,
                components=[
                    ComponentSpec(
                        component_id="pending-proposal-list",
                        component=TrustedComponent.PENDING_PROPOSAL_LIST,
                        title="Verified pending proposals",
                        evidence_ref_ids=[item.evidence_id for item in audit_refs],
                        data={"proposals": proposals},
                    )
                ],
            )
        return _surface(
            query,
            snapshot,
            binding,
            components=[
                _notice(
                    project_ref,
                    "proposals",
                    "empty",
                    "no-verified-pending-proposals",
                )
            ],
        )


def _verified_pending_proposals(
    projects_root: Path,
    project_id: str,
) -> tuple[list[EvidenceRef], list[dict[str, object]]]:
    """Read verified proposal receipts without trusting caller-authored audit locators."""

    if projects_root.is_symlink():
        raise AuditIntegrityError("projects root must not be a symbolic link")
    project_path = projects_root / project_id
    if project_path.is_symlink():
        raise AuditIntegrityError("project UI audit root must not be a symbolic link")
    project_root = project_path.resolve(strict=True)
    ui_root = project_root / ".generative-ui"
    audit_root = ui_root / "audits"
    if not audit_root.exists():
        return [], []
    if ui_root.is_symlink() or audit_root.is_symlink() or not audit_root.is_dir():
        raise AuditIntegrityError("project UI audit root is not a trusted directory")
    try:
        audit_root.resolve(strict=True).relative_to(project_root)
    except ValueError as exc:
        raise AuditIntegrityError("project UI audit root escapes its project") from exc

    refs: list[EvidenceRef] = []
    proposals: list[dict[str, object]] = []
    event_ids: set[str] = set()
    for path in sorted(audit_root.glob("*.jsonl"), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            raise AuditIntegrityError("project UI audit record is not a regular file")
        try:
            records, digest = SurfaceAuditLog(
                path,
                expected_project_id=project_id,
            ).records_with_digest()
        except OSError as exc:
            raise AuditIntegrityError("project UI audit history is unavailable") from exc
        controlled = {
            item.payload.request.proposal_event_id
            for item in records
            if isinstance(item.payload, ProposalControlledAudit)
        }
        issued = [
            item.payload
            for item in records
            if isinstance(item.payload, ProposalIssuedAudit)
            and item.payload.receipt.event_id not in controlled
        ]
        if not issued:
            continue
        locator = f".generative-ui/audits/{path.name}"
        audit_ref = EvidenceRef(
            evidence_id=f"audit-{_identity_suffix(locator)}",
            project_id=project_id,
            kind=EvidenceKind.AUDIT_RECORD,
            locator=locator,
            sha256=digest,
            label="Verified proposal audit",
        )
        refs.append(audit_ref)
        for payload in issued:
            receipt = payload.receipt
            if receipt.event_id in event_ids:
                raise AuditIntegrityError("pending proposal history contains a duplicate event_id")
            event_ids.add(receipt.event_id)
            proposals.append(
                {
                    "audit_ref_id": audit_ref.evidence_id,
                    "event_id": receipt.event_id,
                    "action_id": receipt.action_id,
                    "surface_id": receipt.surface_id,
                    "surface_revision": receipt.surface_revision,
                    "snapshot_revision": receipt.snapshot_revision,
                    "status": receipt.status,
                    "next_boundary": receipt.next_boundary,
                    "execution_authority": receipt.execution_authority,
                }
            )
    return refs, proposals


def workspace_document(
    query: ProjectWorkspaceQuery | dict[str, object],
    surface: SurfaceSpec,
) -> WorkspaceDocument:
    """Project one trusted surface with its closed navigation query."""

    parsed = _project_query(query)
    renderer = project_surface(surface)
    return WorkspaceDocument(
        query=parsed,
        renderer=renderer,
        freshness=WorkspaceFreshness(
            project_revision=surface.snapshot.snapshot_revision,
            snapshot_sha256=surface.snapshot.snapshot_sha256,
            surface_fingerprint=surface.fingerprint,
            evidence_count=len(surface.snapshot.evidence_refs),
        ),
    )


def _project_query(
    query: ProjectWorkspaceQuery | dict[str, object],
) -> ProjectWorkspaceQuery:
    parsed = validate_workspace_query(query)
    if isinstance(parsed, ProjectListQuery):
        raise TypeError("project-list query must use project_list()")
    return parsed


def _surface(
    query: ProjectWorkspaceQuery,
    snapshot: ProjectSnapshot,
    binding: SnapshotBinding,
    *,
    components: list[ComponentSpec],
    actions: list[ActionBinding] | None = None,
) -> SurfaceSpec:
    return SurfaceSpec(
        surface_id=_surface_id(query),
        revision=binding.snapshot_revision,
        purpose=_SURFACE_PURPOSE[query.view],
        title=_VIEW_TITLES[query.view],
        project_id=snapshot.project_id,
        snapshot=binding,
        components=components,
        actions=actions or [],
    )


def _surface_id(query: ProjectWorkspaceQuery) -> str:
    digest = _fingerprint(query.model_dump(mode="json"))[:16]
    return f"workspace-{query.view.value}-{digest}"


def _manifest_ref(binding: SnapshotBinding) -> EvidenceRef:
    return _evidence_for_locator(binding, EvidenceKind.PROJECT_MANIFEST, "PROJECT.json")


def _evidence_for_locator(
    binding: SnapshotBinding,
    kind: EvidenceKind,
    locator: str,
) -> EvidenceRef:
    matches = [
        item for item in binding.evidence_refs if item.kind == kind and item.locator == locator
    ]
    if len(matches) != 1:
        raise UnknownWorkspaceSelectionError(
            f"authoritative {kind.value} evidence is unavailable for the selected view"
        )
    return matches[0]


def _run_ref(snapshot: ProjectSnapshot, binding: SnapshotBinding, run_id: str) -> EvidenceRef:
    return _evidence_for_locator(
        binding,
        EvidenceKind.RUN_RECORD,
        _project_relative(snapshot, snapshot.run_locators[run_id]),
    )


def _require_run(snapshot: ProjectSnapshot, run_id: str) -> ProjectRun:
    try:
        return next(item for item in snapshot.manifest.runs if item.run_id == run_id)
    except StopIteration as exc:
        raise UnknownWorkspaceSelectionError(
            "selected run is not registered by this project"
        ) from exc


def _selected_papers(snapshot: ProjectSnapshot, paper_id: str | None) -> list[ProjectPaperEntry]:
    if paper_id is None:
        return list(snapshot.papers)
    matches = [item for item in snapshot.papers if item.directory_name == paper_id]
    if len(matches) != 1:
        raise UnknownWorkspaceSelectionError("selected paper is not registered by this project")
    return matches


def _project_relative(snapshot: ProjectSnapshot, locator: str) -> str:
    try:
        return (
            PurePosixPath(locator).relative_to(PurePosixPath(snapshot.project_locator)).as_posix()
        )
    except ValueError as exc:
        raise ProjectSurfaceChangedError("workspace evidence escaped its project") from exc


def _notice(
    project_ref: EvidenceRef,
    subject: str,
    state: str,
    reason_code: str,
) -> ComponentSpec:
    return ComponentSpec(
        component_id=f"{subject}-availability",
        component=TrustedComponent.AVAILABILITY_NOTICE,
        title="Authoritative availability",
        evidence_ref_ids=[project_ref.evidence_id],
        data={
            "project_ref_id": project_ref.evidence_id,
            "subject": subject,
            "state": state,
            "reason_code": reason_code,
        },
    )


def _run_outcome(status: str) -> str:
    normalized = status.strip().lower().replace("_", "-")
    if normalized in {"complete", "completed", "success", "succeeded"}:
        return "succeeded"
    if normalized in {"failed", "failure", "error"}:
        return "failed"
    if normalized in {"blocked", "blocker", "blocked-approval"}:
        return "blocked"
    if normalized in {"active", "running", "in-progress"}:
        return "active"
    if normalized in {"planned", "pending", "registered", "queued"}:
        return "registered"
    return "unknown"


def _progress_state(status: str) -> str:
    """Classify only exact, documented status values; unknown is intentional."""

    normalized = status.strip().lower().replace("_", "-")
    if normalized in {
        "complete",
        "completed",
        "success",
        "succeeded",
        "completed-dogfooding",
    }:
        return "observed_completed"
    if normalized in {"failed", "failure", "error"}:
        return "failed"
    if normalized in {
        "blocked",
        "blocker",
        "blocked-approval",
        "active-pilot-blocked",
        "implementation-preaccepted-live-pilot-blocked",
    }:
        return "blocked"
    if normalized in {"active", "running", "in-progress", "reviewed-draft", "peer-reviewed-draft"}:
        return "current_work"
    if normalized in {"planned", "pending", "proposed", "registered", "queued"}:
        return "candidate"
    if normalized in {"unavailable", "not-available"}:
        return "unavailable"
    return "unknown"


def _project_focus(snapshot: ProjectSnapshot) -> tuple[str, str | None, str | None]:
    extra = snapshot.manifest.model_extra or {}
    raw = extra.get("current_focus")
    if not isinstance(raw, dict):
        return snapshot.manifest.research_direction, None, None
    try:
        current = _ManifestCurrentFocus.model_validate(raw)
    except ValidationError:
        return snapshot.manifest.research_direction, None, None
    return current.decision_id, current.status, current.next_gate


def _recorded_blockers(run: ProjectRun) -> tuple[str, ...]:
    raw = (run.model_extra or {}).get("blockers")
    if not isinstance(raw, list) or not raw or len(raw) > 20:
        return ()
    try:
        return TypeAdapter(tuple[SafeText, ...]).validate_python(raw)
    except ValidationError:
        return ()


def _project_milestones(
    snapshot: ProjectSnapshot,
    binding: SnapshotBinding,
    project_ref: EvidenceRef,
) -> tuple[str, str, list[dict[str, object]]]:
    raw = (snapshot.manifest.model_extra or {}).get("iterations")
    if raw is None or raw == []:
        return "empty", "no-declared-project-milestones", []
    if not isinstance(raw, list) or len(raw) > 100:
        return "unavailable", "invalid-project-milestone-extension", []
    try:
        milestones = [_ManifestIteration.model_validate(item) for item in raw]
    except ValidationError:
        return "unavailable", "invalid-project-milestone-extension", []
    identities = [item.iteration_id for item in milestones]
    if len(identities) != len(set(identities)):
        return "unavailable", "invalid-project-milestone-extension", []

    rows: list[dict[str, object]] = []
    for milestone in milestones:
        matched = _bound_ref_for_declared_locator(binding, milestone.evidence)
        support_ref_ids = [project_ref.evidence_id]
        if matched is not None:
            support_ref_ids.append(matched.evidence_id)
        rows.append(
            {
                "milestone_id": milestone.iteration_id,
                "recorded_on": milestone.date.isoformat(),
                "reported_status": milestone.status,
                "observed_state": _progress_state(milestone.status),
                "decision": milestone.decision,
                "support_ref_ids": support_ref_ids,
                "evidence_locator": milestone.evidence,
                "evidence_binding": (
                    "content_addressed" if matched is not None else "manifest_declared"
                ),
            }
        )
    return "available", "manifest-declared-project-milestones", rows


def _bound_ref_for_declared_locator(
    binding: SnapshotBinding,
    locator: str,
) -> EvidenceRef | None:
    candidates = [
        item
        for item in binding.evidence_refs
        if item.kind != EvidenceKind.PROJECT_MANIFEST
        and (locator == item.locator or locator.startswith(f"{item.locator}/"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item.locator))


def _compared_run(run: ProjectRun, ref: EvidenceRef) -> dict[str, object]:
    return {
        "run_ref_id": ref.evidence_id,
        "run_id": run.run_id,
        "status": run.status,
        "provider": run.provider,
        "model_name": run.model,
        "condition": run.condition,
        "seed": run.seed,
        "evidence_scope": run.evidence_scope,
    }


def _run_approval_action(run_ref: EvidenceRef) -> ActionBinding:
    return ActionBinding(
        action_id=f"request-run-{_identity_suffix(run_ref.evidence_id)}",
        component_id="run-stage-explorer",
        label="Request selected run approval",
        proposal=ActionProposal(
            payload=RequestApprovalPayload(
                kind=ProposalKind.REQUEST_APPROVAL,
                subject=ApprovalSubject.RUN_SELECTION,
                subject_ref_ids=[run_ref.evidence_id],
                question="Approve the selected registered run for downstream consideration?",
            ),
            rationale="A later deterministic controller must validate this run-selection request.",
            evidence_ref_ids=[run_ref.evidence_id],
            requires_approval=True,
        ),
    )


def _artifact_action(component_id: str, artifact_ref: EvidenceRef) -> ActionBinding:
    return ActionBinding(
        action_id=f"inspect-{_identity_suffix(artifact_ref.evidence_id)}",
        component_id=component_id,
        label="Inspect content-addressed artifact",
        proposal=ActionProposal(
            payload=InspectArtifactPayload(
                kind=ProposalKind.INSPECT_ARTIFACT,
                artifact_ref_id=artifact_ref.evidence_id,
            ),
            rationale="Inspect only the artifact bound to this authoritative view.",
            evidence_ref_ids=[artifact_ref.evidence_id],
        ),
    )


def _stage_artifact_count(runtime: ProjectRuntime, project_id: str, stage: int) -> int:
    path = runtime.projects_root / project_id / "stages" / "current" / f"stage-{stage:02d}"
    if not path.is_dir():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file() and not item.is_symlink())


def _artifact_media_type(locator: str) -> str | None:
    return _ARTIFACT_MEDIA_TYPES.get(PurePosixPath(locator).suffix.lower())


def _identity_suffix(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_SURFACE_PURPOSE = {
    WorkspaceView.PROJECT_OVERVIEW: SurfacePurpose.PROJECT_OVERVIEW,
    WorkspaceView.PROJECT_PROGRESS: SurfacePurpose.PROJECT_PROGRESS,
    WorkspaceView.RUN_STAGE_EXPLORER: SurfacePurpose.RUN_STAGE_EXPLORER,
    WorkspaceView.PAPER_EVIDENCE: SurfacePurpose.PAPER_EVIDENCE,
    WorkspaceView.RUN_COMPARISON: SurfacePurpose.WORKSPACE_RUN_COMPARISON,
    WorkspaceView.BLOCKERS: SurfacePurpose.BLOCKER_VIEW,
    WorkspaceView.PENDING_PROPOSALS: SurfacePurpose.PENDING_PROPOSALS,
}

_VIEW_TITLES = {
    WorkspaceView.PROJECT_OVERVIEW: "Project overview",
    WorkspaceView.PROJECT_PROGRESS: "Project progress",
    WorkspaceView.RUN_STAGE_EXPLORER: "Run and stage explorer",
    WorkspaceView.PAPER_EVIDENCE: "Paper and evidence",
    WorkspaceView.RUN_COMPARISON: "Run comparison",
    WorkspaceView.BLOCKERS: "Run blockers",
    WorkspaceView.PENDING_PROPOSALS: "Pending proposals",
}

_ARTIFACT_MEDIA_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".tex": "text/x-tex",
}

_STAGE_LABELS = {
    1: ("topic-init", "Topic initialization", "课题初始化"),
    2: ("problem-decompose", "Problem decomposition", "问题分解"),
    3: ("search-strategy", "Search strategy", "检索策略"),
    4: ("literature-collect", "Literature collection", "文献收集"),
    5: ("literature-screen", "Literature screening", "文献筛选"),
    6: ("knowledge-extract", "Knowledge extraction", "知识提取"),
    7: ("synthesis", "Knowledge synthesis", "知识综合"),
    8: ("hypothesis-gen", "Hypothesis generation", "假设生成"),
    9: ("experiment-design", "Experiment design", "实验设计"),
    10: ("code-generation", "Code generation", "代码生成"),
    11: ("resource-planning", "Resource planning", "资源规划"),
    12: ("experiment-run", "Experiment execution", "实验执行"),
    13: ("iterative-refine", "Iterative refinement", "迭代修正"),
    14: ("result-analysis", "Result analysis", "结果分析"),
    15: ("research-decision", "Research decision", "研究决策"),
    16: ("paper-outline", "Paper outline", "论文提纲"),
    17: ("paper-draft", "Paper draft", "论文草稿"),
    18: ("peer-review", "Peer review", "同行评审"),
    19: ("paper-revision", "Paper revision", "论文修订"),
    20: ("quality-gate", "Quality gate", "质量门禁"),
    21: ("knowledge-archive", "Knowledge archive", "知识归档"),
    22: ("export-publish", "Export and publish", "导出发布"),
    23: ("citation-verify", "Citation verification", "引文核验"),
}
