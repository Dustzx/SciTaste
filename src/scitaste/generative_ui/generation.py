"""Application-level orchestration for evidence-grounded generated workspaces."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.generative_ui.intent import (
    FreeQuestionRequest,
    IntentEntityCandidate,
    IntentRequest,
    IntentResolution,
    QuickIntentCatalog,
    QuickIntentRequest,
    StaleIntentRequestError,
    WorkspaceIntent,
    WorkspaceIntentResolver,
    validate_intent_request,
)
from scitaste.generative_ui.models import SurfaceSpec
from scitaste.generative_ui.planner import (
    FallbackWorkspacePlanner,
    IntentPlannerOutcome,
    ModelPlannerPolicy,
    PlannerConversationContext,
    PlannerIdentity,
    SurfacePlannerOutcome,
    WorkspacePlanner,
)
from scitaste.generative_ui.planning import (
    PlanEmphasis,
    PlanGroup,
    SurfaceCandidateCatalog,
    SurfaceCandidateFactory,
    materialize_surface_plan,
)
from scitaste.generative_ui.project_adapter import ProjectSnapshotAdapter
from scitaste.generative_ui.projection import RendererDocument, project_surface
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, SafeText, Sha256
from scitaste.generative_ui.workspace import WorkspaceFreshness, WorkspaceView
from scitaste.project import ProjectRuntime

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_GENERATION_ID_CONTRACT = "generated-workspace-envelope-v4"


class WorkspaceGenerationRequest(BaseModel):
    """One client intent bound to the exact quick-intent catalog it observed."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    quick_catalog_fingerprint: Sha256
    intent_request: IntentRequest
    context_turn_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=8)

    @field_validator("context_turn_ids")
    @classmethod
    def context_turns_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("conversation context turn IDs must be unique")
        return values

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def request_identity_is_coherent(self) -> WorkspaceGenerationRequest:
        object.__setattr__(
            self,
            "intent_request",
            validate_intent_request(self.intent_request),
        )
        return self


class GeneratedComponentPlacement(BaseModel):
    """Server-owned explanation and layout metadata for one trusted component."""

    model_config = _MODEL_CONFIG

    candidate_id: SafeIdentifier
    component_id: SafeIdentifier
    source_view: WorkspaceView
    group: PlanGroup
    emphasis: PlanEmphasis
    focus_ref_ids: tuple[SafeIdentifier, ...] = ()
    reason_code: SafeIdentifier
    explanation: SafeText


class GeneratedWorkspaceDocument(BaseModel):
    """Question-free result rendered by the fixed native receiver."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal[
        "generated",
        "clarification_required",
        "no_matching_evidence",
        "provider_unavailable",
        "plan_unavailable",
    ]
    reason_code: SafeIdentifier
    request_fingerprint: Sha256
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    context_turn_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=8)
    conversation_context_sha256: Sha256 | None = None
    entity_candidates: tuple[IntentEntityCandidate, ...] = ()
    intent: WorkspaceIntent | None = None
    classification: IntentPlannerOutcome | None = None
    planning: SurfacePlannerOutcome | None = None
    placements: tuple[GeneratedComponentPlacement, ...] = ()
    renderer: RendererDocument | None = None
    freshness: WorkspaceFreshness | None = None
    execution_authority: Literal["none"] = "none"

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def generated_payload_is_atomic_and_bound(self) -> GeneratedWorkspaceDocument:
        if bool(self.context_turn_ids) != (self.conversation_context_sha256 is not None):
            raise ValueError("generated workspace conversation context is incomplete")
        if self.status != "generated":
            if self.renderer is not None or self.freshness is not None or self.placements:
                raise ValueError("unresolved generation cannot expose a renderer")
            if self.status == "clarification_required" and not self.entity_candidates:
                raise ValueError("clarification requires registered entity candidates")
            if self.status != "clarification_required" and self.entity_candidates:
                raise ValueError("only clarification may expose entity candidates")
            if self.status == "plan_unavailable":
                if self.intent is None or self.planning is None:
                    raise ValueError("plan failure must retain its admitted intent")
            elif self.intent is not None or self.planning is not None:
                raise ValueError("intent-resolution failure cannot expose a plan")
            return self

        if (
            self.intent is None
            or self.planning is None
            or self.planning.plan is None
            or self.renderer is None
            or self.freshness is None
        ):
            raise ValueError("generated workspace requires intent, plan, renderer, and freshness")
        if self.entity_candidates:
            raise ValueError("generated workspace cannot request entity clarification")
        if self.planning.status not in {"planned", "fallback"}:
            raise ValueError("generated workspace requires an admitted plan")
        if (
            self.project_id != self.intent.snapshot.project_id
            or self.snapshot_revision != self.intent.snapshot.snapshot_revision
            or self.snapshot_sha256 != self.intent.snapshot.snapshot_sha256
            or self.renderer.project_id != self.project_id
            or self.renderer.snapshot != self.intent.snapshot
        ):
            raise ValueError("generated workspace identities do not match")
        expected_freshness = WorkspaceFreshness(
            project_revision=self.snapshot_revision,
            snapshot_sha256=self.snapshot_sha256,
            surface_fingerprint=self.renderer.surface_fingerprint,
            evidence_count=len(self.renderer.snapshot.evidence_refs),
        )
        if self.freshness != expected_freshness:
            raise ValueError("generated workspace freshness is inconsistent")
        entries = self.planning.plan.entries
        if len(entries) != len(self.renderer.components) or len(entries) != len(self.placements):
            raise ValueError("generated workspace plan, placement, and component counts differ")
        for entry, placement, component in zip(
            entries,
            self.placements,
            self.renderer.components,
            strict=True,
        ):
            if (
                entry.candidate_id != placement.candidate_id
                or entry.group != placement.group
                or entry.emphasis != placement.emphasis
                or entry.focus_ref_ids != placement.focus_ref_ids
                or placement.component_id != component.component_id
            ):
                raise ValueError("generated component placement differs from its plan")
            if set(placement.focus_ref_ids) - set(component.evidence_ref_ids):
                raise ValueError("generated component focus is outside its evidence")
        if self.planning.authored_brief is not None:
            authored_brief = self.planning.authored_brief
            if (
                self.planning.provenance is None
                or self.planning.provenance.mode != "model_assisted"
                or self.planning.provenance.content_fingerprint != authored_brief.fingerprint
            ):
                raise ValueError("generated model content lacks exact provider provenance")
            selected_candidates = {item.candidate_id for item in self.placements}
            visible_evidence = {
                evidence_id
                for component in self.renderer.components
                for evidence_id in component.evidence_ref_ids
            }
            for point in authored_brief.points:
                if set(point.source_candidate_ids) - selected_candidates:
                    raise ValueError("generated model content cites a hidden candidate")
                if set(point.evidence_ref_ids) - visible_evidence:
                    raise ValueError("generated model content cites hidden evidence")
            if (
                authored_brief.edited_from_turn_id is not None
                and authored_brief.edited_from_turn_id not in self.context_turn_ids
            ):
                raise ValueError("generated model edit predecessor is outside conversation context")
        return self


class WorkspaceGenerationOutput(BaseModel):
    """Internal trusted pairing; the HTTP receiver exposes only the document."""

    model_config = _MODEL_CONFIG

    document: GeneratedWorkspaceDocument
    surface: SurfaceSpec | None = None

    @model_validator(mode="after")
    def surface_matches_document(self) -> WorkspaceGenerationOutput:
        if self.document.status == "generated":
            if self.surface is None or self.document.renderer is None:
                raise ValueError("generated output requires its server-owned surface")
            if (
                self.surface.project_id != self.document.project_id
                or self.surface.snapshot != self.document.renderer.snapshot
                or self.surface.fingerprint != self.document.renderer.surface_fingerprint
            ):
                raise ValueError("generated output surface differs from its document")
        elif self.surface is not None:
            raise ValueError("unresolved generation cannot retain a surface")
        return self


class WorkspaceGenerationService:
    """Resolve intent, plan a layout, and materialize only trusted components."""

    def __init__(
        self,
        runtime: ProjectRuntime,
        *,
        planner: WorkspacePlanner | None = None,
    ) -> None:
        if not isinstance(runtime, ProjectRuntime):
            raise TypeError("WorkspaceGenerationService requires a trusted ProjectRuntime")
        self._runtime = runtime
        self._resolver = WorkspaceIntentResolver(runtime)
        self._candidate_factory = SurfaceCandidateFactory(runtime)
        self._adapter = ProjectSnapshotAdapter(runtime)
        self._planner = FallbackWorkspacePlanner(planner)

    def quick_catalog(self, project_id: str) -> QuickIntentCatalog:
        return self._resolver.quick_catalog(project_id)

    @property
    def planner_identity(self) -> PlannerIdentity:
        return self._planner.identity

    @property
    def model_planner_policy(self) -> ModelPlannerPolicy | None:
        return self._planner.model_policy

    def generate(
        self,
        request: WorkspaceGenerationRequest | dict[str, object],
    ) -> GeneratedWorkspaceDocument:
        return self.generate_output(request).document

    def generate_output(
        self,
        request: WorkspaceGenerationRequest | dict[str, object],
        *,
        conversation_context: PlannerConversationContext | None = None,
    ) -> WorkspaceGenerationOutput:
        parsed = (
            request
            if isinstance(request, WorkspaceGenerationRequest)
            else WorkspaceGenerationRequest.model_validate(request)
        )
        parsed = WorkspaceGenerationRequest.model_validate(parsed.model_dump(mode="json"))
        _validate_conversation_context(parsed, conversation_context)
        intent_request = parsed.intent_request
        quick_catalog = self._resolver.quick_catalog(intent_request.project_id)
        if parsed.quick_catalog_fingerprint != quick_catalog.fingerprint:
            raise StaleIntentRequestError("quick-intent catalog is stale")

        resolution = self._resolver.resolve(intent_request)
        classification: IntentPlannerOutcome | None = None
        if resolution.status == "provider_unavailable" and isinstance(
            intent_request, FreeQuestionRequest
        ):
            classification = self._planner.classify(
                intent_request,
                quick_catalog,
                context=conversation_context,
            )
            if classification.status == "selected":
                selected = QuickIntentRequest(
                    project_id=intent_request.project_id,
                    snapshot_revision=intent_request.snapshot_revision,
                    snapshot_sha256=intent_request.snapshot_sha256,
                    quick_intent_id=classification.selected_quick_intent_id,
                )
                selected_resolution = self._resolver.resolve(selected)
                if selected_resolution.intent is None:
                    raise ValueError("model selected an intent unavailable in the current catalog")
                resolution = IntentResolution(
                    status="resolved",
                    request_fingerprint=intent_request.fingerprint,
                    project_id=intent_request.project_id,
                    snapshot_revision=intent_request.snapshot_revision,
                    snapshot_sha256=intent_request.snapshot_sha256,
                    reason_code="model-intent-selection-admitted",
                    intent=selected_resolution.intent,
                )
            else:
                return WorkspaceGenerationOutput(
                    document=_resolution_failure(
                        resolution,
                        reason_code=classification.reason_code,
                        classification=classification,
                        context=conversation_context,
                    )
                )

        if resolution.intent is None:
            return WorkspaceGenerationOutput(
                document=_resolution_failure(
                    resolution,
                    classification=classification,
                    context=conversation_context,
                )
            )

        candidates = self._candidate_factory.build(resolution.intent)
        planning = self._planner.compose(
            candidates,
            prompt_text=(
                intent_request.question
                if isinstance(intent_request, FreeQuestionRequest)
                else f"Open the {resolution.intent.goal.value} project workspace."
            ),
            context=conversation_context,
        )
        if planning.plan is None:
            return WorkspaceGenerationOutput(
                document=GeneratedWorkspaceDocument(
                    status="plan_unavailable",
                    reason_code=planning.reason_code,
                    request_fingerprint=intent_request.fingerprint,
                    project_id=resolution.project_id,
                    snapshot_revision=resolution.snapshot_revision,
                    snapshot_sha256=resolution.snapshot_sha256,
                    context_turn_ids=parsed.context_turn_ids,
                    conversation_context_sha256=(
                        conversation_context.fingerprint
                        if conversation_context is not None
                        else None
                    ),
                    intent=resolution.intent,
                    classification=classification,
                    planning=planning,
                )
            )

        materialized = materialize_surface_plan(candidates, planning.plan)
        generation_fingerprint = _fingerprint(
            {
                "generation_id_contract": _GENERATION_ID_CONTRACT,
                "request_fingerprint": parsed.fingerprint,
                "conversation_context_sha256": (
                    conversation_context.fingerprint if conversation_context is not None else None
                ),
                "materialized_surface_fingerprint": materialized.surface.fingerprint,
                "authored_brief_fingerprint": (
                    planning.authored_brief.fingerprint
                    if planning.authored_brief is not None
                    else None
                ),
            }
        )
        scoped_surface = SurfaceSpec.model_validate(
            materialized.surface.model_copy(
                update={
                    "surface_id": (
                        f"generated-{resolution.intent.goal.value}-{generation_fingerprint[:16]}"
                    )
                }
            ).model_dump(mode="json")
        )
        current = self._adapter.build_binding(resolution.project_id)
        if current != scoped_surface.snapshot:
            raise StaleIntentRequestError("project evidence changed while generating its workspace")
        renderer = project_surface(scoped_surface)
        placements = _placements(candidates, planning)
        return WorkspaceGenerationOutput(
            document=GeneratedWorkspaceDocument(
                status="generated",
                reason_code=planning.reason_code,
                request_fingerprint=intent_request.fingerprint,
                project_id=resolution.project_id,
                snapshot_revision=resolution.snapshot_revision,
                snapshot_sha256=resolution.snapshot_sha256,
                context_turn_ids=parsed.context_turn_ids,
                conversation_context_sha256=(
                    conversation_context.fingerprint if conversation_context is not None else None
                ),
                intent=resolution.intent,
                classification=classification,
                planning=planning,
                placements=placements,
                renderer=renderer,
                freshness=WorkspaceFreshness(
                    project_revision=renderer.snapshot.snapshot_revision,
                    snapshot_sha256=renderer.snapshot.snapshot_sha256,
                    surface_fingerprint=renderer.surface_fingerprint,
                    evidence_count=len(renderer.snapshot.evidence_refs),
                ),
            ),
            surface=scoped_surface,
        )


def _resolution_failure(
    resolution: IntentResolution,
    *,
    reason_code: str | None = None,
    classification: IntentPlannerOutcome | None = None,
    context: PlannerConversationContext | None = None,
) -> GeneratedWorkspaceDocument:
    status: Literal[
        "clarification_required",
        "no_matching_evidence",
        "provider_unavailable",
    ]
    if resolution.status == "resolved":
        raise ValueError("resolved intent cannot become an intent failure")
    status = resolution.status
    return GeneratedWorkspaceDocument(
        status=status,
        reason_code=reason_code or resolution.reason_code,
        request_fingerprint=resolution.request_fingerprint,
        project_id=resolution.project_id,
        snapshot_revision=resolution.snapshot_revision,
        snapshot_sha256=resolution.snapshot_sha256,
        context_turn_ids=(
            tuple(item.turn_id for item in context.turns) if context is not None else ()
        ),
        conversation_context_sha256=context.fingerprint if context is not None else None,
        entity_candidates=resolution.candidates,
        classification=classification,
    )


def _validate_conversation_context(
    request: WorkspaceGenerationRequest,
    context: PlannerConversationContext | None,
) -> None:
    selected = request.context_turn_ids
    if not selected:
        if context is not None:
            raise ValueError("conversation context was supplied without selected turn IDs")
        return
    if context is None:
        raise ValueError("selected conversation turns require server-verified context")
    if context.project_id != request.intent_request.project_id:
        raise ValueError("conversation context belongs to another project")
    if tuple(item.turn_id for item in context.turns) != selected:
        raise ValueError("conversation context differs from selected turn IDs")


def _placements(
    catalog: SurfaceCandidateCatalog,
    planning: SurfacePlannerOutcome,
) -> tuple[GeneratedComponentPlacement, ...]:
    if planning.plan is None:
        raise ValueError("cannot place components without an admitted plan")
    candidates = {item.candidate_id: item for item in catalog.candidates}
    placements: list[GeneratedComponentPlacement] = []
    for entry in planning.plan.entries:
        candidate = candidates[entry.candidate_id]
        placements.append(
            GeneratedComponentPlacement(
                candidate_id=candidate.candidate_id,
                component_id=candidate.component.component_id,
                source_view=candidate.source_view,
                group=entry.group,
                emphasis=entry.emphasis,
                focus_ref_ids=entry.focus_ref_ids,
                reason_code=candidate.reason_code,
                explanation=_PLACEMENT_EXPLANATIONS[candidate.source_view],
            )
        )
    return tuple(placements)


_PLACEMENT_EXPLANATIONS = {
    WorkspaceView.PROJECT_PROGRESS: "Included from verified project progress evidence.",
    WorkspaceView.PROJECT_OVERVIEW: "Included to retain authoritative project context.",
    WorkspaceView.RUN_STAGE_EXPLORER: "Included from registered run and stage evidence.",
    WorkspaceView.PAPER_EVIDENCE: "Included from registered paper and artifact evidence.",
    WorkspaceView.RUN_COMPARISON: "Included for the two runs bound by the resolved intent.",
    WorkspaceView.BLOCKERS: "Included from registered blocked or failed run evidence.",
    WorkspaceView.PENDING_PROPOSALS: "Included from verified proposal audit records.",
    WorkspaceView.RESEARCH_LANDSCAPE: (
        "Included from the registered literature-synthesis artifact."
    ),
}


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "GeneratedComponentPlacement",
    "GeneratedWorkspaceDocument",
    "WorkspaceGenerationOutput",
    "WorkspaceGenerationRequest",
    "WorkspaceGenerationService",
]
