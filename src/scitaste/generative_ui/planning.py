"""Closed candidate catalogs and declarative plans for generated workspaces."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from scitaste.generative_ui.intent import (
    IntentEntityRole,
    IntentGoal,
    WorkspaceIntent,
)
from scitaste.generative_ui.models import (
    ActionBinding,
    ComponentSpec,
    SurfaceSpec,
)
from scitaste.generative_ui.registry import SurfacePurpose, TrustedComponent
from scitaste.generative_ui.safety import (
    ProjectIdentifier,
    SafeIdentifier,
    Sha256,
)
from scitaste.generative_ui.workspace import (
    BlockerQuery,
    PaperEvidenceQuery,
    ProjectOverviewQuery,
    ProjectProgressQuery,
    ResearchLandscapeQuery,
    RunComparisonQuery,
    RunStageQuery,
    WorkspaceSurfaceFactory,
    WorkspaceView,
)
from scitaste.project import ProjectRuntime

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_SURFACE_CANDIDATES = 64


class PlanGroup(StrEnum):
    PRIMARY = "primary"
    CONTEXT = "context"
    EVIDENCE = "evidence"
    ATTENTION = "attention"


class PlanEmphasis(StrEnum):
    STANDARD = "standard"
    FEATURED = "featured"
    COMPACT = "compact"


class SurfaceCandidate(BaseModel):
    """One complete server-owned component option exposed to a planner by ID."""

    model_config = _MODEL_CONFIG

    candidate_id: SafeIdentifier
    source_view: WorkspaceView
    component: ComponentSpec
    actions: tuple[ActionBinding, ...] = ()
    reason_code: SafeIdentifier
    allowed_groups: tuple[PlanGroup, ...] = Field(min_length=1)
    allowed_emphasis: tuple[PlanEmphasis, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def actions_belong_to_candidate_component(self) -> SurfaceCandidate:
        if len(self.allowed_groups) != len(set(self.allowed_groups)):
            raise ValueError("surface candidate groups must be unique")
        if len(self.allowed_emphasis) != len(set(self.allowed_emphasis)):
            raise ValueError("surface candidate emphasis values must be unique")
        action_ids = [item.action_id for item in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("surface candidate action IDs must be unique")
        if any(item.component_id != self.component.component_id for item in self.actions):
            raise ValueError("surface candidate actions must target its component")
        return self


class SurfaceCandidateDescriptor(BaseModel):
    """Data-free projection suitable for an untrusted optional planner."""

    model_config = _MODEL_CONFIG

    candidate_id: SafeIdentifier
    source_view: WorkspaceView
    component: TrustedComponent
    evidence_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    has_actions: bool
    reason_code: SafeIdentifier
    allowed_groups: tuple[PlanGroup, ...] = Field(min_length=1)
    allowed_emphasis: tuple[PlanEmphasis, ...] = Field(min_length=1)


class SurfaceCandidateCatalog(BaseModel):
    """Full trusted candidate content; providers receive descriptors only."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    intent: WorkspaceIntent
    candidates: tuple[SurfaceCandidate, ...] = Field(min_length=1, max_length=64)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    def descriptors(self) -> tuple[SurfaceCandidateDescriptor, ...]:
        return tuple(
            SurfaceCandidateDescriptor(
                candidate_id=item.candidate_id,
                source_view=item.source_view,
                component=item.component.component,
                evidence_ref_ids=tuple(item.component.evidence_ref_ids),
                has_actions=bool(item.actions),
                reason_code=item.reason_code,
                allowed_groups=item.allowed_groups,
                allowed_emphasis=item.allowed_emphasis,
            )
            for item in self.candidates
        )

    @model_validator(mode="after")
    def candidate_content_is_one_valid_surface(self) -> SurfaceCandidateCatalog:
        candidate_ids = [item.candidate_id for item in self.candidates]
        component_ids = [item.component.component_id for item in self.candidates]
        action_ids = [action.action_id for item in self.candidates for action in item.actions]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("surface candidate IDs must be unique")
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("surface candidate component IDs must be unique")
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("surface candidate action IDs must be unique")
        SurfaceSpec(
            surface_id="candidate-catalog-validation",
            revision=self.intent.snapshot.snapshot_revision,
            purpose=SurfacePurpose.GENERATED_WORKSPACE,
            title="Generated workspace candidate catalog",
            project_id=self.intent.snapshot.project_id,
            snapshot=self.intent.snapshot,
            components=[item.component for item in self.candidates],
            actions=[action for item in self.candidates for action in item.actions],
        )
        return self


class SurfacePlanEntry(BaseModel):
    model_config = _MODEL_CONFIG

    candidate_id: SafeIdentifier
    group: PlanGroup
    emphasis: PlanEmphasis = PlanEmphasis.STANDARD
    focus_ref_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def focus_evidence_is_unique(self) -> SurfacePlanEntry:
        if len(self.focus_ref_ids) != len(set(self.focus_ref_ids)):
            raise ValueError("surface plan focus evidence must be unique")
        return self


class SurfacePlan(BaseModel):
    """ID-only planner output; it cannot author components, content, or actions."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    intent_fingerprint: Sha256
    catalog_fingerprint: Sha256
    entries: tuple[SurfacePlanEntry, ...] = Field(min_length=1, max_length=12)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def selected_candidates_are_unique(self) -> SurfacePlan:
        candidates = [item.candidate_id for item in self.entries]
        if len(candidates) != len(set(candidates)):
            raise ValueError("surface plan candidate IDs must be unique")
        return self


_PLAN_ADAPTER = TypeAdapter(SurfacePlan)


def validate_surface_plan(value: SurfacePlan | dict[str, object]) -> SurfacePlan:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _PLAN_ADAPTER.validate_python(value)


class MaterializedSurfacePlan(BaseModel):
    """Validated plan plus the exact server-owned surface it selected."""

    model_config = _MODEL_CONFIG

    plan: SurfacePlan
    surface: SurfaceSpec

    @model_validator(mode="after")
    def plan_and_surface_identity_match(self) -> MaterializedSurfacePlan:
        if (
            self.surface.project_id != self.plan.project_id
            or self.surface.snapshot.snapshot_revision != self.plan.snapshot_revision
            or self.surface.snapshot.snapshot_sha256 != self.plan.snapshot_sha256
        ):
            raise ValueError("materialized surface does not match its admitted plan")
        return self


class StaleSurfacePlanError(ValueError):
    """Plan, intent, candidate catalog, or snapshot identity no longer matches."""


class SurfaceCandidateFactory:
    """Create server-owned candidates without exposing component data to providers."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("SurfaceCandidateFactory requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._workspace = WorkspaceSurfaceFactory(runtime)

    def build(self, intent: WorkspaceIntent | dict[str, object]) -> SurfaceCandidateCatalog:
        parsed = (
            intent
            if isinstance(intent, WorkspaceIntent)
            else WorkspaceIntent.model_validate(intent)
        )
        parsed = WorkspaceIntent.model_validate(parsed.model_dump(mode="json"))
        snapshot = self._runtime.open(parsed.snapshot.project_id)
        if snapshot.revision != parsed.snapshot.snapshot_revision:
            raise StaleSurfacePlanError("intent snapshot revision is stale")

        surfaces = [
            self._workspace.build_surface(
                ProjectProgressQuery(project_id=parsed.snapshot.project_id)
            ),
            self._workspace.build_surface(
                ProjectOverviewQuery(project_id=parsed.snapshot.project_id)
            ),
        ]
        surfaces.extend(self._goal_surfaces(parsed, snapshot))
        for surface in surfaces:
            if surface.snapshot != parsed.snapshot:
                raise StaleSurfacePlanError("candidate surface snapshot differs from intent")

        candidates: list[SurfaceCandidate] = []
        for surface_index, surface in enumerate(surfaces):
            actions_by_component: dict[str, list[ActionBinding]] = {}
            for action in surface.actions:
                actions_by_component.setdefault(action.component_id, []).append(action)
            for component_index, component in enumerate(surface.components):
                candidate_id = _candidate_id(
                    surface_index,
                    component_index,
                    surface,
                    component,
                )
                scoped_component_id = (
                    f"planned-{hashlib.sha256(candidate_id.encode()).hexdigest()[:16]}"
                )
                scoped_component = ComponentSpec.model_validate(
                    component.model_copy(update={"component_id": scoped_component_id}).model_dump(
                        mode="json"
                    )
                )
                scoped_actions = tuple(
                    _scoped_action(candidate_id, scoped_component_id, action)
                    for action in actions_by_component.get(component.component_id, [])
                )
                groups = _groups_for(surface, component)
                candidates.append(
                    SurfaceCandidate(
                        candidate_id=candidate_id,
                        source_view=_source_view(surface),
                        component=scoped_component,
                        actions=scoped_actions,
                        reason_code=f"available-from-{_source_view(surface).value}",
                        allowed_groups=groups,
                        allowed_emphasis=tuple(PlanEmphasis),
                    )
                )
        admitted = sorted(candidates, key=_candidate_admission_key)[:_MAX_SURFACE_CANDIDATES]
        return SurfaceCandidateCatalog(intent=parsed, candidates=tuple(admitted))

    def _goal_surfaces(self, intent: WorkspaceIntent, snapshot) -> list[SurfaceSpec]:
        project_id = intent.snapshot.project_id
        surfaces: list[SurfaceSpec] = []
        if intent.goal == IntentGoal.PROGRESS_REVIEW:
            if snapshot.manifest.runs:
                surfaces.append(self._workspace.build_surface(RunStageQuery(project_id=project_id)))
            if any(_registered_blocker_status(run.status) for run in snapshot.manifest.runs):
                surfaces.append(self._workspace.build_surface(BlockerQuery(project_id=project_id)))
            if snapshot.papers:
                surfaces.append(
                    self._workspace.build_surface(PaperEvidenceQuery(project_id=project_id))
                )
        elif intent.goal == IntentGoal.BLOCKER_DIAGNOSIS:
            surfaces.append(self._workspace.build_surface(BlockerQuery(project_id=project_id)))
        elif intent.goal == IntentGoal.RUN_COMPARISON:
            baseline = _role_entity(intent, IntentEntityRole.BASELINE_RUN)
            candidate = _role_entity(intent, IntentEntityRole.CANDIDATE_RUN)
            surfaces.append(
                self._workspace.build_surface(
                    RunComparisonQuery(
                        project_id=project_id,
                        baseline_run_id=baseline,
                        candidate_run_id=candidate,
                    )
                )
            )
        elif intent.goal == IntentGoal.PAPER_EVIDENCE_REVIEW:
            paper_ids = [
                item.entity_id for item in intent.bindings if item.role == IntentEntityRole.PAPER
            ]
            surfaces.append(
                self._workspace.build_surface(
                    PaperEvidenceQuery(
                        project_id=project_id,
                        paper_id=paper_ids[0] if len(paper_ids) == 1 else None,
                    )
                )
            )
        elif intent.goal == IntentGoal.RESEARCH_LANDSCAPE_REVIEW:
            surfaces.append(
                self._workspace.build_surface(ResearchLandscapeQuery(project_id=project_id))
            )
        return surfaces


def materialize_surface_plan(
    catalog: SurfaceCandidateCatalog,
    plan: SurfacePlan | dict[str, object],
) -> MaterializedSurfacePlan:
    trusted = SurfaceCandidateCatalog.model_validate(catalog.model_dump(mode="json"))
    admitted = validate_surface_plan(plan)
    if (
        admitted.project_id != trusted.intent.snapshot.project_id
        or admitted.snapshot_revision != trusted.intent.snapshot.snapshot_revision
        or admitted.snapshot_sha256 != trusted.intent.snapshot.snapshot_sha256
        or admitted.intent_fingerprint != trusted.intent.fingerprint
        or admitted.catalog_fingerprint != trusted.fingerprint
    ):
        raise StaleSurfacePlanError("surface plan is not bound to this candidate catalog")
    by_id = {item.candidate_id: item for item in trusted.candidates}
    selected: list[SurfaceCandidate] = []
    for entry in admitted.entries:
        candidate = by_id.get(entry.candidate_id)
        if candidate is None:
            raise StaleSurfacePlanError("surface plan selected an unknown candidate")
        if entry.group not in candidate.allowed_groups:
            raise ValueError("surface plan group is not allowed for its candidate")
        if entry.emphasis not in candidate.allowed_emphasis:
            raise ValueError("surface plan emphasis is not allowed for its candidate")
        if set(entry.focus_ref_ids) - set(candidate.component.evidence_ref_ids):
            raise ValueError("surface plan focus evidence is outside its candidate")
        selected.append(candidate)

    surface = SurfaceSpec(
        surface_id=f"generated-{trusted.intent.goal.value}-{admitted.fingerprint[:16]}",
        revision=trusted.intent.snapshot.snapshot_revision,
        purpose=SurfacePurpose.GENERATED_WORKSPACE,
        title=_GENERATED_TITLES[trusted.intent.goal],
        project_id=trusted.intent.snapshot.project_id,
        snapshot=trusted.intent.snapshot,
        components=[item.component for item in selected],
        actions=[action for item in selected for action in item.actions],
    )
    return MaterializedSurfacePlan(plan=admitted, surface=surface)


def _candidate_id(
    surface_index: int,
    component_index: int,
    surface: SurfaceSpec,
    component: ComponentSpec,
) -> str:
    identity = f"{surface.surface_id}:{component.component_id}:{component.component.value}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return f"candidate-{surface_index:02d}-{component_index:02d}-{digest}"


def _candidate_admission_key(candidate: SurfaceCandidate) -> tuple[int, str]:
    """Keep structural summaries before bounded per-artifact detail."""

    priority = {
        TrustedComponent.PROJECT_PROGRESS_BOARD: 0,
        TrustedComponent.RESEARCH_LANDSCAPE_MAP: 0,
        TrustedComponent.RUN_COMPARISON_PANEL: 0,
        TrustedComponent.RUN_BLOCKER_PANEL: 0,
        TrustedComponent.RUN_STAGE_EXPLORER: 0,
        TrustedComponent.PROJECT_SUMMARY_CARD: 1,
        TrustedComponent.RUN_HEALTH: 1,
        TrustedComponent.EVIDENCE_INVENTORY: 2,
        TrustedComponent.PAPER_PREVIEW: 3,
        TrustedComponent.ARTIFACT_VIEWER: 4,
    }.get(candidate.component.component, 2)
    return priority, candidate.candidate_id


def _scoped_action(
    candidate_id: str,
    component_id: str,
    action: ActionBinding,
) -> ActionBinding:
    digest = hashlib.sha256((candidate_id + action.action_id).encode()).hexdigest()[:16]
    return ActionBinding.model_validate(
        action.model_copy(
            update={
                "action_id": f"planned-{digest}",
                "component_id": component_id,
            }
        ).model_dump(mode="json")
    )


def _source_view(surface: SurfaceSpec) -> WorkspaceView:
    return _PURPOSE_VIEWS[surface.purpose]


def _groups_for(
    surface: SurfaceSpec,
    component: ComponentSpec,
) -> tuple[PlanGroup, ...]:
    if component.component in {
        TrustedComponent.RUN_BLOCKER_PANEL,
        TrustedComponent.BLOCKER_LIST,
    }:
        return (PlanGroup.ATTENTION, PlanGroup.PRIMARY)
    if component.component in {
        TrustedComponent.EVIDENCE_INVENTORY,
        TrustedComponent.ARTIFACT_VIEWER,
        TrustedComponent.PAPER_PREVIEW,
    }:
        return (PlanGroup.EVIDENCE, PlanGroup.CONTEXT)
    if component.component == TrustedComponent.RESEARCH_LANDSCAPE_MAP:
        return (PlanGroup.PRIMARY, PlanGroup.EVIDENCE)
    if surface.purpose in {
        SurfacePurpose.PROJECT_PROGRESS,
        SurfacePurpose.WORKSPACE_RUN_COMPARISON,
    }:
        return (PlanGroup.PRIMARY, PlanGroup.CONTEXT)
    return (PlanGroup.CONTEXT, PlanGroup.PRIMARY)


def _role_entity(intent: WorkspaceIntent, role: IntentEntityRole) -> str:
    matches = [item.entity_id for item in intent.bindings if item.role == role]
    if len(matches) != 1:
        raise ValueError("workspace intent role is not uniquely bound")
    return matches[0]


def _registered_blocker_status(status: str) -> bool:
    normalized = status.strip().lower().replace("_", "-")
    return normalized in {"blocked", "blocker", "blocked-approval", "failed", "failure", "error"}


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_PURPOSE_VIEWS = {
    SurfacePurpose.PROJECT_PROGRESS: WorkspaceView.PROJECT_PROGRESS,
    SurfacePurpose.PROJECT_OVERVIEW: WorkspaceView.PROJECT_OVERVIEW,
    SurfacePurpose.RUN_STAGE_EXPLORER: WorkspaceView.RUN_STAGE_EXPLORER,
    SurfacePurpose.PAPER_EVIDENCE: WorkspaceView.PAPER_EVIDENCE,
    SurfacePurpose.WORKSPACE_RUN_COMPARISON: WorkspaceView.RUN_COMPARISON,
    SurfacePurpose.BLOCKER_VIEW: WorkspaceView.BLOCKERS,
    SurfacePurpose.RESEARCH_LANDSCAPE: WorkspaceView.RESEARCH_LANDSCAPE,
}

_GENERATED_TITLES = {
    IntentGoal.PROGRESS_REVIEW: "Generated project progress workspace",
    IntentGoal.BLOCKER_DIAGNOSIS: "Generated blocker diagnosis workspace",
    IntentGoal.RUN_COMPARISON: "Generated run comparison workspace",
    IntentGoal.PAPER_EVIDENCE_REVIEW: "Generated paper evidence workspace",
    IntentGoal.NEXT_STEP_REVIEW: "Generated next-step review workspace",
    IntentGoal.RESEARCH_LANDSCAPE_REVIEW: "Generated research landscape workspace",
}
