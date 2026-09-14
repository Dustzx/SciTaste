"""Bounded deterministic and optional model-assisted workspace planning."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    computed_field,
    model_validator,
)

from scitaste.generative_ui.intent import (
    FreeQuestionRequest,
    IntentGoal,
    QuickIntentCatalog,
)
from scitaste.generative_ui.planning import (
    PlanEmphasis,
    SurfaceCandidate,
    SurfaceCandidateCatalog,
    SurfacePlan,
    SurfacePlanEntry,
    materialize_surface_plan,
)
from scitaste.generative_ui.program_revision import (
    ProgramRevisionCatalog,
    ProgramRevisionDraft,
    ProgramRevisionOutcome,
    ProgramRevisionPlanner,
    ProgramRevisionRecord,
    ProgramRevisionRequest,
    validate_program_revision_draft,
)
from scitaste.generative_ui.registry import TrustedComponent
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import (
    CumulativeProjectBudget,
    NodeAdmissionBudget,
    ProviderGenerationEnvelope,
    StructuredModelRequest,
    StructuredModelResponse,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredBackendDisabledError,
    StructuredProviderResponseError,
)
from scitaste.model_nodes.verification_policy import VerificationAdvisory

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
ProviderIdentityPart = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]
_MAX_MODEL_CANDIDATES = 24
_MAX_MODEL_EVIDENCE_BYTES = 32_000


class PlannerMode(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model_assisted"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class PlannerOperation(StrEnum):
    INTENT_CLASSIFICATION = "intent_classification"
    SURFACE_COMPOSITION = "surface_composition"
    EVIDENCE_PROGRAM_REVISION = "evidence_program_revision"


class _ModelProgramRevisionDraft(BaseModel):
    """Semantic planning fields; the trusted receiver supplies all invariants."""

    model_config = _MODEL_CONFIG

    change_kind: Literal[
        "reprioritize_next_gates",
        "clarify_stage_decision",
        "request_resource_revision",
        "add_risk_note",
    ]
    target_stage_id: SafeIdentifier
    target_track_ids: tuple[SafeIdentifier, ...] = ()
    proposed_next_stage_order: tuple[SafeIdentifier, ...] = ()
    summary: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=12)
    requested_resource_roles: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    requested_resource_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    verification_advisory: VerificationAdvisory | None = None


def _inert_model_text(value: str) -> str:
    if not value.strip():
        raise ValueError("model-authored content cannot be blank")
    if any(
        character not in "\n\r\t" and unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError("model-authored content cannot contain control characters")
    return value


class ModelAuthoredBriefPoint(BaseModel):
    """One evidence-cited statement rendered as inert text by the trusted receiver."""

    model_config = _MODEL_CONFIG

    point_id: SafeIdentifier
    kind: Literal["finding", "uncertainty", "recommendation"]
    text: str = Field(min_length=1, max_length=800)
    source_candidate_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=4)
    evidence_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def content_and_sources_are_bounded(self) -> ModelAuthoredBriefPoint:
        _inert_model_text(self.text)
        if len(self.source_candidate_ids) != len(set(self.source_candidate_ids)):
            raise ValueError("model-authored point candidate IDs must be unique")
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("model-authored point evidence IDs must be unique")
        return self


class ModelAuthoredCanvasNode(BaseModel):
    """One model-arranged, evidence-cited node in a generated visual summary."""

    model_config = _MODEL_CONFIG

    node_id: SafeIdentifier
    kind: Literal["milestone", "decision", "resource", "risk", "evidence"]
    state: Literal["observed", "proposed", "blocked", "uncertain"]
    label: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=320)
    source_candidate_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=4)
    evidence_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def content_and_sources_are_bounded(self) -> ModelAuthoredCanvasNode:
        _inert_model_text(self.label)
        _inert_model_text(self.detail)
        if len(self.source_candidate_ids) != len(set(self.source_candidate_ids)):
            raise ValueError("model-authored canvas candidate IDs must be unique")
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("model-authored canvas evidence IDs must be unique")
        return self


class ModelAuthoredCanvasEdge(BaseModel):
    """A bounded semantic relation between two generated canvas nodes."""

    model_config = _MODEL_CONFIG

    source_node_id: SafeIdentifier
    target_node_id: SafeIdentifier
    relation: Literal["depends_on", "supports", "blocks", "uses", "revises"]

    @model_validator(mode="after")
    def endpoints_are_distinct(self) -> ModelAuthoredCanvasEdge:
        if self.source_node_id == self.target_node_id:
            raise ValueError("model-authored canvas edges cannot be self-referential")
        return self


class ModelAuthoredCanvas(BaseModel):
    """Model-generated visual structure rendered by a fixed non-executable receiver."""

    model_config = _MODEL_CONFIG

    layout: Literal["flow", "network", "decision"]
    title: str = Field(min_length=1, max_length=180)
    nodes: tuple[ModelAuthoredCanvasNode, ...] = Field(min_length=2, max_length=10)
    edges: tuple[ModelAuthoredCanvasEdge, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def graph_is_closed(self) -> ModelAuthoredCanvas:
        _inert_model_text(self.title)
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("model-authored canvas node IDs must be unique")
        endpoints = {
            node_id for edge in self.edges for node_id in (edge.source_node_id, edge.target_node_id)
        }
        if endpoints - set(node_ids):
            raise ValueError("model-authored canvas edges reference unknown nodes")
        edge_ids = [
            (item.source_node_id, item.target_node_id, item.relation) for item in self.edges
        ]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("model-authored canvas edges must be unique")
        return self


class ModelAuthoredBrief(BaseModel):
    """Flexible, non-executable synthesis grounded in the selected project evidence."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=180)
    synthesis: str = Field(min_length=1, max_length=2_000)
    points: tuple[ModelAuthoredBriefPoint, ...] = Field(min_length=1, max_length=6)
    canvas: ModelAuthoredCanvas | None = None
    suggested_questions: tuple[str, ...] = Field(default=(), max_length=3)
    edited_from_turn_id: SafeIdentifier | None = None
    evidence_only: Literal[True] = True
    advisory_only: Literal[True] = True
    execution_authority: Literal["none"] = "none"

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def authored_content_is_closed(self) -> ModelAuthoredBrief:
        _inert_model_text(self.title)
        _inert_model_text(self.synthesis)
        for question in self.suggested_questions:
            _inert_model_text(question)
        point_ids = [item.point_id for item in self.points]
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("model-authored brief point IDs must be unique")
        if len(self.suggested_questions) != len(set(self.suggested_questions)):
            raise ValueError("model-authored suggested questions must be unique")
        return self


class ModelSurfaceComposition(BaseModel):
    """Single-call model output: ID-only layout choices plus cited content.

    Project, snapshot, intent, and catalog identities remain receiver-owned and
    are added only after this bounded choice schema has been admitted.
    """

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    entries: tuple[SurfacePlanEntry, ...] = Field(min_length=1, max_length=12)
    brief: ModelAuthoredBrief

    @model_validator(mode="after")
    def candidate_choices_are_unique(self) -> ModelSurfaceComposition:
        candidate_ids = [item.candidate_id for item in self.entries]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("model surface candidate choices must be unique")
        return self


class PlannerContextTurn(BaseModel):
    """One server-verified prior turn exposed to bounded planning and editing."""

    model_config = _MODEL_CONFIG

    turn_id: SafeIdentifier
    ordinal: int = Field(ge=1)
    prompt_kind: Literal["quick", "free_question"]
    prompt_text: str = Field(min_length=1, max_length=1_000)
    authored_brief: ModelAuthoredBrief | None = None
    surface_entries: tuple[SurfacePlanEntry, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def surface_entries_are_unique(self) -> PlannerContextTurn:
        candidate_ids = [item.candidate_id for item in self.surface_entries]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("prior surface entries must name unique candidates")
        return self


class PlannerConversationContext(BaseModel):
    """Bounded project-local context; generated prose is deliberately excluded."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    workspace_id: SafeIdentifier
    turns: tuple[PlannerContextTurn, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def turns_are_an_ordered_unique_selection(self) -> PlannerConversationContext:
        identities = [item.turn_id for item in self.turns]
        ordinals = [item.ordinal for item in self.turns]
        if len(identities) != len(set(identities)):
            raise ValueError("planner conversation turn IDs must be unique")
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("planner conversation turns must be in unique ordinal order")
        return self

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class PlannerIdentity(BaseModel):
    """Pinned implementation identity safe to retain in UI provenance."""

    model_config = _MODEL_CONFIG

    planner_id: SafeIdentifier
    implementation: Literal["deterministic-v1", "structured-model-v1"]
    configuration_sha256: Sha256
    backend: ProviderIdentityPart | None = None
    model: ProviderIdentityPart | None = None

    @model_validator(mode="after")
    def provider_identity_is_atomic(self) -> PlannerIdentity:
        if (self.backend is None) != (self.model is None):
            raise ValueError("planner backend and model identity must be supplied together")
        if self.implementation == "deterministic-v1" and self.backend is not None:
            raise ValueError("deterministic planner cannot claim a model provider")
        if self.implementation == "structured-model-v1" and self.backend is None:
            raise ValueError("structured planner requires a pinned backend and model")
        return self


class ModelPlannerPolicy(BaseModel):
    """Independent bounds applied around an existing structured backend."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: SafeIdentifier = "generative-ui-planner-v1"
    expected_backend: ProviderIdentityPart
    expected_model: ProviderIdentityPart
    max_request_bytes: int = Field(default=128_000, ge=512, le=1_000_000)
    max_response_bytes: int = Field(default=24_000, ge=256, le=1_000_000)
    max_input_tokens: int = Field(default=32_000, ge=1, le=1_000_000)
    max_output_tokens: int = Field(default=1_024, ge=1, le=32_000)
    max_latency_ms: float = Field(default=60_000, gt=0, le=300_000, allow_inf_nan=False)
    max_response_cost_usd: float = Field(default=0.15, ge=0, le=100, allow_inf_nan=False)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json", exclude={"fingerprint"}))


class PlannerProvenance(BaseModel):
    """Question-free record binding planning inputs, implementation, and result."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    operation: PlannerOperation
    mode: PlannerMode
    planner: PlannerIdentity
    attempted_planner: PlannerIdentity | None = None
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    intent_fingerprint: Sha256 | None = None
    catalog_fingerprint: Sha256
    request_fingerprint: Sha256
    conversation_context_sha256: Sha256 | None = None
    provider_response_sha256: Sha256 | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    provider_cached: bool | None = None
    result_fingerprint: Sha256 | None = None
    content_fingerprint: Sha256 | None = None
    deterministic_reproducible: bool

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def mode_matches_identity(self) -> PlannerProvenance:
        if self.mode == PlannerMode.MODEL_ASSISTED:
            if (
                self.planner.implementation != "structured-model-v1"
                or self.provider_response_sha256 is None
                or self.deterministic_reproducible
                or self.attempted_planner is not None
            ):
                raise ValueError("model-assisted provenance is incomplete")
        elif self.mode == PlannerMode.DETERMINISTIC:
            if (
                self.planner.implementation != "deterministic-v1"
                or self.provider_response_sha256 is not None
                or not self.deterministic_reproducible
                or self.attempted_planner is not None
            ):
                raise ValueError("deterministic provenance is inconsistent")
        elif (
            self.planner.implementation != "deterministic-v1"
            or self.attempted_planner is None
            or self.provider_response_sha256 is not None
            or not self.deterministic_reproducible
        ):
            raise ValueError("fallback provenance must identify the rejected planner")
        if self.operation == PlannerOperation.SURFACE_COMPOSITION:
            if self.intent_fingerprint is None or self.result_fingerprint is None:
                raise ValueError("surface composition provenance requires intent and plan hashes")
        elif self.operation == PlannerOperation.EVIDENCE_PROGRAM_REVISION:
            if self.intent_fingerprint is not None or self.result_fingerprint is None:
                raise ValueError("program revision provenance requires only a result hash")
        elif self.intent_fingerprint is not None or self.result_fingerprint is not None:
            raise ValueError("intent classification cannot claim a resolved intent hash")
        return self


class IntentPlannerChoice(BaseModel):
    """A model may select one server-issued quick intent ID and nothing else."""

    model_config = _MODEL_CONFIG

    quick_intent_id: SafeIdentifier


class IntentPlannerOutcome(BaseModel):
    """Question-free semantic classification outcome."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["selected", "unavailable", "rejected"]
    reason_code: SafeIdentifier
    request_fingerprint: Sha256
    selected_quick_intent_id: SafeIdentifier | None = None
    provenance: PlannerProvenance | None = None

    @model_validator(mode="after")
    def selection_matches_status(self) -> IntentPlannerOutcome:
        if self.status == "selected":
            if self.selected_quick_intent_id is None or self.provenance is None:
                raise ValueError("selected intent outcome requires its ID and provenance")
        elif self.selected_quick_intent_id is not None:
            raise ValueError("unselected intent outcome cannot contain an intent ID")
        return self


class SurfaceEditDelta(BaseModel):
    """Server-derived change summary between one model page and its predecessor."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    predecessor_turn_id: SafeIdentifier
    retained_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    added_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    removed_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    reordered_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    regrouped_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    reemphasized_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    refocused_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=12)
    layout_changed: bool
    authored_content_changed: bool

    @model_validator(mode="after")
    def candidate_sets_are_closed(self) -> SurfaceEditDelta:
        sequences = (
            self.retained_candidate_ids,
            self.added_candidate_ids,
            self.removed_candidate_ids,
            self.reordered_candidate_ids,
            self.regrouped_candidate_ids,
            self.reemphasized_candidate_ids,
            self.refocused_candidate_ids,
        )
        if any(len(values) != len(set(values)) for values in sequences):
            raise ValueError("surface edit-delta candidate IDs must be unique")
        retained = set(self.retained_candidate_ids)
        if set(self.added_candidate_ids).intersection(self.removed_candidate_ids):
            raise ValueError("surface edit-delta additions and removals must be disjoint")
        for values in sequences[3:]:
            if set(values) - retained:
                raise ValueError("surface edit-delta changes must name retained candidates")
        observed_layout_change = any(
            (
                self.added_candidate_ids,
                self.removed_candidate_ids,
                self.reordered_candidate_ids,
                self.regrouped_candidate_ids,
                self.reemphasized_candidate_ids,
                self.refocused_candidate_ids,
            )
        )
        if self.layout_changed != observed_layout_change:
            raise ValueError("surface edit-delta layout flag differs from its changes")
        return self


class SurfacePlannerOutcome(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["planned", "fallback", "unavailable"]
    reason_code: SafeIdentifier
    plan: SurfacePlan | None = None
    authored_brief: ModelAuthoredBrief | None = None
    edit_delta: SurfaceEditDelta | None = None
    provenance: PlannerProvenance | None = None

    @model_validator(mode="after")
    def plan_matches_status(self) -> SurfacePlannerOutcome:
        if self.status in {"planned", "fallback"}:
            if self.plan is None or self.provenance is None:
                raise ValueError("successful planning outcome requires plan and provenance")
            if self.provenance.result_fingerprint != self.plan.fingerprint:
                raise ValueError("planning provenance does not bind the selected plan")
            if self.authored_brief is not None and (
                self.provenance.mode is not PlannerMode.MODEL_ASSISTED
                or self.provenance.content_fingerprint != self.authored_brief.fingerprint
            ):
                raise ValueError("model-authored content lacks exact model provenance")
            if self.edit_delta is not None and (
                self.authored_brief is None
                or self.authored_brief.edited_from_turn_id != self.edit_delta.predecessor_turn_id
            ):
                raise ValueError("surface edit delta differs from its model-authored predecessor")
        elif self.plan is not None:
            raise ValueError("unavailable planning outcome cannot contain a plan")
        if self.status == "unavailable" and (
            self.authored_brief is not None or self.edit_delta is not None
        ):
            raise ValueError("unavailable planning cannot expose model-authored content")
        return self


@runtime_checkable
class WorkspacePlanner(Protocol):
    """Narrow UI planner boundary; it has no executor or state mutation method."""

    identity: PlannerIdentity

    def classify(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
        *,
        context: PlannerConversationContext | None = None,
    ) -> IntentPlannerOutcome: ...

    def compose(
        self,
        catalog: SurfaceCandidateCatalog,
        *,
        prompt_text: str | None = None,
        context: PlannerConversationContext | None = None,
    ) -> SurfacePlannerOutcome: ...


class DeterministicWorkspacePlanner:
    """Stable provider-free layout for every admitted canonical intent."""

    def __init__(self) -> None:
        configuration = {
            "algorithm": "intent-component-filter-priority-then-candidate-id",
            "max_entries": 12,
            "version": "1.2",
        }
        self.identity = PlannerIdentity(
            planner_id="deterministic-workspace-planner-v1",
            implementation="deterministic-v1",
            configuration_sha256=_fingerprint(configuration),
        )

    def classify(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
        *,
        context: PlannerConversationContext | None = None,
    ) -> IntentPlannerOutcome:
        del context
        _validate_question_catalog_binding(request, catalog)
        return IntentPlannerOutcome(
            status="unavailable",
            reason_code="deterministic-long-tail-classification-unavailable",
            request_fingerprint=request.fingerprint,
        )

    def compose(
        self,
        catalog: SurfaceCandidateCatalog,
        *,
        prompt_text: str | None = None,
        context: PlannerConversationContext | None = None,
    ) -> SurfacePlannerOutcome:
        del prompt_text, context
        trusted = SurfaceCandidateCatalog.model_validate(catalog.model_dump(mode="json"))
        included_components = _GOAL_SELECTED_COMPONENTS.get(trusted.intent.goal)
        eligible = [
            candidate
            for candidate in trusted.candidates
            if included_components is None or candidate.component.component in included_components
        ]
        ordered = sorted(
            eligible,
            key=lambda candidate: _deterministic_candidate_key(
                candidate,
                trusted.intent.goal,
            ),
        )
        entries = tuple(
            _deterministic_entry(candidate, index) for index, candidate in enumerate(ordered[:12])
        )
        plan = SurfacePlan(
            project_id=trusted.intent.snapshot.project_id,
            snapshot_revision=trusted.intent.snapshot.snapshot_revision,
            snapshot_sha256=trusted.intent.snapshot.snapshot_sha256,
            intent_fingerprint=trusted.intent.fingerprint,
            catalog_fingerprint=trusted.fingerprint,
            entries=entries,
        )
        materialize_surface_plan(trusted, plan)
        request_fingerprint = _fingerprint(_composition_input(trusted))
        return SurfacePlannerOutcome(
            status="planned",
            reason_code="deterministic-plan-admitted",
            plan=plan,
            provenance=_composition_provenance(
                mode=PlannerMode.DETERMINISTIC,
                planner=self.identity,
                catalog=trusted,
                request_fingerprint=request_fingerprint,
                plan=plan,
            ),
        )


class StructuredWorkspacePlanner:
    """Untrusted structured backend adapter constrained by server-owned catalogs."""

    def __init__(self, backend: StructuredModelBackend, policy: ModelPlannerPolicy) -> None:
        if not isinstance(backend, StructuredModelBackend):
            raise TypeError("structured UI planner requires a StructuredModelBackend")
        self._backend = backend
        self.policy = ModelPlannerPolicy.model_validate(
            policy.model_dump(mode="json", exclude={"fingerprint"})
        )
        if (backend.name, backend.model) != (
            self.policy.expected_backend,
            self.policy.expected_model,
        ):
            raise ValueError("planner backend identity differs from policy")
        backend_config = getattr(backend, "config", None)
        if backend_config is not None:
            timeout_ms = float(backend_config.timeout_seconds) * 1000
            attempts = int(backend_config.max_retries) + 1
            if timeout_ms * attempts > self.policy.max_latency_ms:
                raise ValueError("planner backend timeout exceeds policy latency bound")
        configuration: dict[str, object] = {
            "implementation_contract": "structured-workspace-planner-v3",
            "policy": self.policy.model_dump(mode="json", exclude={"fingerprint"}),
        }
        if isinstance(backend_config, BaseModel):
            configuration["backend_config"] = backend_config.model_dump(mode="json")
        self.identity = PlannerIdentity(
            planner_id="structured-workspace-planner-v1",
            implementation="structured-model-v1",
            configuration_sha256=_fingerprint(configuration),
            backend=backend.name,
            model=backend.model,
        )

    def classify(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
        *,
        context: PlannerConversationContext | None = None,
    ) -> IntentPlannerOutcome:
        _validate_question_catalog_binding(request, catalog)
        _validate_conversation_context(request, context)
        input_payload: dict[str, JsonValue] = {
            "question": request.question,
            "options": [
                {
                    "quick_intent_id": item.quick_intent_id,
                    "goal": item.goal.value,
                    "target_ids": list(item.target_ids),
                }
                for item in catalog.intents
            ],
        }
        identity_fingerprint = request.fingerprint
        if context is not None:
            input_payload["conversation_context"] = [
                {
                    "turn_id": item.turn_id,
                    "ordinal": item.ordinal,
                    "prompt_kind": item.prompt_kind,
                    "prompt_text": item.prompt_text,
                }
                for item in context.turns
            ]
            identity_fingerprint = _fingerprint(
                {
                    "request_fingerprint": request.fingerprint,
                    "conversation_context_sha256": context.fingerprint,
                }
            )
        try:
            structured_request = self._request(
                operation=PlannerOperation.INTENT_CLASSIFICATION,
                project_id=request.project_id,
                snapshot_revision=request.snapshot_revision,
                snapshot_sha256=request.snapshot_sha256,
                input_payload=input_payload,
                output_schema=IntentPlannerChoice.model_json_schema(mode="validation"),
                identity_fingerprint=identity_fingerprint,
            )
            response = self._complete(structured_request)
            choice = IntentPlannerChoice.model_validate(response.output_payload)
        except Exception:
            return IntentPlannerOutcome(
                status="unavailable",
                reason_code="model-intent-provider-unavailable",
                request_fingerprint=request.fingerprint,
            )
        allowed = {item.quick_intent_id for item in catalog.intents}
        if choice.quick_intent_id not in allowed:
            return IntentPlannerOutcome(
                status="rejected",
                reason_code="model-intent-selection-rejected",
                request_fingerprint=request.fingerprint,
            )
        provenance = PlannerProvenance(
            operation=PlannerOperation.INTENT_CLASSIFICATION,
            mode=PlannerMode.MODEL_ASSISTED,
            planner=self.identity,
            project_id=request.project_id,
            snapshot_revision=request.snapshot_revision,
            snapshot_sha256=request.snapshot_sha256,
            catalog_fingerprint=catalog.fingerprint,
            request_fingerprint=structured_request.fingerprint,
            conversation_context_sha256=(context.fingerprint if context is not None else None),
            provider_response_sha256=response.raw_response_sha256,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=response.usage.cost_usd,
            latency_ms=response.latency_ms,
            provider_cached=response.cached,
            deterministic_reproducible=False,
        )
        return IntentPlannerOutcome(
            status="selected",
            reason_code="model-intent-selection-admitted",
            request_fingerprint=request.fingerprint,
            selected_quick_intent_id=choice.quick_intent_id,
            provenance=provenance,
        )

    def compose(
        self,
        catalog: SurfaceCandidateCatalog,
        *,
        prompt_text: str | None = None,
        context: PlannerConversationContext | None = None,
    ) -> SurfacePlannerOutcome:
        trusted = SurfaceCandidateCatalog.model_validate(catalog.model_dump(mode="json"))
        input_payload = _model_composition_input(
            trusted,
            prompt_text=prompt_text,
            context=context,
        )
        try:
            structured_request = self._request(
                operation=PlannerOperation.SURFACE_COMPOSITION,
                project_id=trusted.intent.snapshot.project_id,
                snapshot_revision=trusted.intent.snapshot.snapshot_revision,
                snapshot_sha256=trusted.intent.snapshot.snapshot_sha256,
                input_payload=input_payload,
                output_schema=ModelSurfaceComposition.model_json_schema(mode="validation"),
                identity_fingerprint=_fingerprint(input_payload),
                system_instruction=(
                    "Compose one concise project answer and a supporting native layout from "
                    "only the supplied evidence_digest. Select only server-issued candidate and "
                    "evidence identifiers. Every authored point must cite candidates selected in "
                    "the entries and evidence IDs carried by those candidates. When at least two "
                    "evidence-backed entities have a meaningful relation, generate a compact "
                    "brief.canvas (flow, network, or decision); every canvas node must obey the "
                    "same citation rule. Use null only when no honest relation can be grounded. "
                    "The receiver, "
                    "not the model, supplies project, snapshot, intent, and catalog identities. "
                    "Treat omitted or "
                    "truncated evidence as unknown. Use conversation_history as bounded user "
                    "context. If prior_generated_workspace is present, edit both its cited brief "
                    "and its safe surface_plan_entries in response to the current prompt. The "
                    "trusted receiver binds edited_from_turn_id to that prior turn. "
                    "Authored text is advisory and cannot "
                    "claim execution, approval, new evidence, or completed work. Fields named "
                    "required_*, planned_*, or maximum_* describe obligations or ceilings, never "
                    "observed completion. In taste_source_review_campaigns, "
                    "scientific_assessment_count and privacy_assessment_count are likewise "
                    "required workload; only reviewer_sessions_prepared and "
                    "reviewer_submissions_collected describe observed completion. Before an "
                    "abstraction plan exists, abstraction_candidate_ceiling and the "
                    "campaign-ceiling capacity basis are only a worst-case forecast; after the "
                    "locked-eligible-inputs basis appears, abstraction_input_count is exact. "
                    "Do not infer "
                    "a dependency, block, use, or resource "
                    "requirement merely because two entities are both visible; create a canvas "
                    "edge only when the supplied facts or current user prompt state that exact "
                    "relation. Return one JSON "
                    "object matching output_schema and no tool calls."
                ),
            )
            response = self._complete(structured_request)
            composition = ModelSurfaceComposition.model_validate(
                _normalize_redundant_surface_echoes(
                    response.output_payload,
                    trusted,
                    context=context,
                )
            )
            entries = _admit_cited_candidates(
                composition.entries,
                composition.brief,
                trusted,
                offered_candidate_ids={
                    item["candidate_id"]
                    for item in input_payload["candidates"]
                    if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
                },
            )
            plan = SurfacePlan(
                project_id=trusted.intent.snapshot.project_id,
                snapshot_revision=trusted.intent.snapshot.snapshot_revision,
                snapshot_sha256=trusted.intent.snapshot.snapshot_sha256,
                intent_fingerprint=trusted.intent.fingerprint,
                catalog_fingerprint=trusted.fingerprint,
                entries=entries,
            )
            offered_candidate_ids = {
                item["candidate_id"]
                for item in input_payload["candidates"]
                if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
            }
            if {item.candidate_id for item in plan.entries} - offered_candidate_ids:
                raise ValueError("model plan selected a candidate outside its bounded catalog")
            materialize_surface_plan(trusted, plan)
            digest_candidate_ids = {
                item["candidate_id"]
                for item in input_payload["evidence_digest"]
                if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
            }
            _validate_model_authored_brief(
                composition.brief,
                trusted,
                plan,
                digest_candidate_ids=digest_candidate_ids,
                context=context,
            )
        except Exception as exc:
            return SurfacePlannerOutcome(
                status="unavailable",
                reason_code=_surface_composition_failure_reason(exc),
            )
        return SurfacePlannerOutcome(
            status="planned",
            reason_code="model-surface-plan-admitted",
            plan=plan,
            authored_brief=composition.brief,
            edit_delta=_surface_edit_delta(
                context,
                plan=plan,
                brief=composition.brief,
            ),
            provenance=_composition_provenance(
                mode=PlannerMode.MODEL_ASSISTED,
                planner=self.identity,
                catalog=trusted,
                request_fingerprint=structured_request.fingerprint,
                plan=plan,
                provider_response_sha256=response.raw_response_sha256,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                latency_ms=response.latency_ms,
                provider_cached=response.cached,
                content_fingerprint=composition.brief.fingerprint,
            ),
        )

    def revise_program(
        self,
        request: ProgramRevisionRequest,
        catalog: ProgramRevisionCatalog,
        *,
        prior_record: ProgramRevisionRecord | None = None,
    ) -> ProgramRevisionOutcome:
        """Generate planning content while keeping IDs and authority server constrained."""

        request = ProgramRevisionRequest.model_validate(
            request.model_dump(mode="json", exclude_computed_fields=True)
        )
        catalog = ProgramRevisionCatalog.model_validate(
            catalog.model_dump(mode="json", exclude_computed_fields=True)
        )
        if (
            request.project_id != catalog.project_id
            or request.snapshot_revision != catalog.snapshot_revision
            or request.snapshot_sha256 != catalog.snapshot_sha256
            or request.dossier_sha256 != catalog.dossier_sha256
        ):
            raise ValueError("program-revision request differs from its catalog")
        input_payload: dict[str, JsonValue] = {
            "feedback": request.feedback,
            "requested_action_focus": (
                {
                    "target_stage_id": request.target_stage_id,
                    "target_route_sha256": request.target_route_sha256,
                }
                if request.target_stage_id is not None
                else None
            ),
            "base_dossier_sha256": catalog.dossier_sha256,
            "current_stage_id": catalog.current_stage_id,
            "next_stage_ids": list(catalog.next_stage_ids),
            "stages": [
                item.model_dump(mode="json") for item in catalog.stages if item.state != "complete"
            ],
            "tracks": [item.model_dump(mode="json") for item in catalog.tracks],
            "project_resource_roles": list(catalog.resource_roles),
            "project_resources": [item.model_dump(mode="json") for item in catalog.resources],
            "tool_intelligence_routes": [
                item.model_dump(mode="json") for item in catalog.action_routes
            ],
            "allowed_change_kinds": [
                "reprioritize_next_gates",
                "clarify_stage_decision",
                "request_resource_revision",
                "add_risk_note",
            ],
            "change_kind_contracts": {
                "reprioritize_next_gates": (
                    "Use only when feedback explicitly asks to reorder gates; "
                    "proposed_next_stage_order must contain every next_stage_id exactly once."
                ),
                "clarify_stage_decision": (
                    "Use for changed decision guidance or required evidence without reordering; "
                    "proposed_next_stage_order must be empty."
                ),
                "request_resource_revision": (
                    "Use only for project resource membership or priority; select only listed "
                    "resources and compatible roles."
                ),
                "add_risk_note": (
                    "Use only to record a risk without changing gate order or resources."
                ),
            },
            "prior_proposal": (
                {
                    "proposal_id": prior_record.proposal_id,
                    "record_sha256": prior_record.record_sha256,
                    "user_feedback": prior_record.request.feedback,
                    "draft": prior_record.outcome.draft.model_dump(mode="json"),
                }
                if prior_record is not None and prior_record.outcome.draft is not None
                else None
            ),
            "published_directive": (
                catalog.active_directive.model_dump(mode="json")
                if catalog.active_directive is not None
                else None
            ),
        }
        response: StructuredModelResponse | None = None
        try:
            structured_request = self._request(
                operation=PlannerOperation.EVIDENCE_PROGRAM_REVISION,
                project_id=request.project_id,
                snapshot_revision=request.snapshot_revision,
                snapshot_sha256=request.snapshot_sha256,
                input_payload=input_payload,
                output_schema=_ModelProgramRevisionDraft.model_json_schema(mode="validation"),
                identity_fingerprint=request.fingerprint,
                system_instruction=(
                    "Draft one concise scientific-planning amendment from the user feedback. "
                    "When prior_proposal or published_directive is present, edit that active "
                    "planning direction in response to the new feedback "
                    "rather than treating the request as an unrelated conversation. "
                    "If requested_action_focus is present, target exactly that stage and use its "
                    "Tool Intelligence route: do not add a check when it says direct_path, do not "
                    "expand targeted_check into a full preflight, and do not treat owner_approval "
                    "as execution authority. If that exact route has "
                    "verification.model_advisory_eligible=true, you may include "
                    "verification_advisory using its verification.input_fingerprint; otherwise "
                    "leave verification_advisory null. Advice may skip a low-value check or "
                    "select only the positive-value best check, and never creates authority. "
                    "Follow change_kind_contracts exactly. Decision guidance, evidence "
                    "requirements, or within-stage sequencing use clarify_stage_decision unless "
                    "the user explicitly asks to reorder every next gate. "
                    "Select only stage and track identifiers present in input_payload. Preserve "
                    "completed stages and every blocker. Do not claim new evidence. The trusted "
                    "receiver binds the dossier identity and the immutable no-apply, no-external-"
                    "action, and no-execution fields; do not return those integrity fields. For a "
                    "resource revision, project_resources with attached=false may be "
                    "selected only with exactly one of their compatible roles; publication then "
                    "attaches catalog metadata but must not claim access, probing, or use. "
                    "JSON object matching output_schema and no tool calls."
                ),
            )
            response = self._complete(structured_request)
            semantic = _ModelProgramRevisionDraft.model_validate(response.output_payload)
            draft = ProgramRevisionDraft(
                base_dossier_sha256=catalog.dossier_sha256,
                **semantic.model_dump(mode="python"),
                preserves_completed_stages=True,
                removes_blockers=False,
                applies_change=False,
                authorizes_external_action=False,
                authorizes_execution=False,
            )
            validate_program_revision_draft(draft, catalog)
            if (
                request.target_stage_id is not None
                and draft.target_stage_id != request.target_stage_id
            ):
                raise ValueError("model program revision ignored the focused action route")
        except Exception as exc:
            return ProgramRevisionOutcome(
                status="unavailable",
                reason_code=_program_revision_failure_reason(exc),
                request_fingerprint=request.fingerprint,
                catalog_fingerprint=catalog.fingerprint,
                planner_id=self.identity.planner_id,
                provider_response_sha256=(
                    response.raw_response_sha256 if response is not None else None
                ),
                input_tokens=response.usage.input_tokens if response is not None else None,
                output_tokens=response.usage.output_tokens if response is not None else None,
                cost_usd=response.usage.cost_usd if response is not None else None,
                latency_ms=response.latency_ms if response is not None else None,
                model_generated=False,
            )
        return ProgramRevisionOutcome(
            status="proposed",
            reason_code="model-program-revision-proposed",
            request_fingerprint=request.fingerprint,
            catalog_fingerprint=catalog.fingerprint,
            planner_id=self.identity.planner_id,
            provider_response_sha256=response.raw_response_sha256,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=response.usage.cost_usd,
            latency_ms=response.latency_ms,
            draft=draft,
            model_generated=True,
        )

    def _request(
        self,
        *,
        operation: PlannerOperation,
        project_id: str,
        snapshot_revision: int,
        snapshot_sha256: str,
        input_payload: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
        identity_fingerprint: str,
        system_instruction: str | None = None,
    ) -> StructuredModelRequest:
        profile_fingerprint = self.policy.fingerprint
        request = StructuredModelRequest(
            request_id=f"ui-{operation.value}-{identity_fingerprint[:20]}",
            node_name="generative-ui-planner",
            stage="generative-ui",
            state_snapshot_id=f"{project_id}:{snapshot_revision}:{snapshot_sha256}",
            expected_backend=self.policy.expected_backend,
            expected_model=self.policy.expected_model,
            policy_id=self.policy.policy_id,
            policy_fingerprint=self.policy.fingerprint,
            system_instruction=system_instruction
            or (
                "Select only identifiers and enum values present in input_payload. "
                "Return one JSON object matching output_schema. Never add facts, content, "
                "actions, URLs, paths, commands, tools, or explanations."
            ),
            input_payload=input_payload,
            output_schema=output_schema,
            seed=0,
            prompt_version="generative-ui-planner-v3",
            profile_id=self.policy.policy_id,
            profile_fingerprint=profile_fingerprint,
            generation_envelope=ProviderGenerationEnvelope(
                max_request_bytes=self.policy.max_request_bytes,
                max_output_tokens=self.policy.max_output_tokens,
                context_window_tokens=self.policy.max_input_tokens + self.policy.max_output_tokens,
            ),
            admission_budget=NodeAdmissionBudget(
                max_request_bytes=self.policy.max_request_bytes,
                max_input_tokens=self.policy.max_input_tokens,
                max_output_tokens=self.policy.max_output_tokens,
                max_total_tokens=self.policy.max_input_tokens + self.policy.max_output_tokens,
                max_latency_ms=self.policy.max_latency_ms,
                max_response_cost_usd=self.policy.max_response_cost_usd,
            ),
            cumulative_project_budget=CumulativeProjectBudget(
                max_invocations=1,
                max_total_tokens=self.policy.max_input_tokens + self.policy.max_output_tokens,
                max_api_cost_usd=self.policy.max_response_cost_usd,
            ),
        )
        if _json_size(request.model_dump(mode="json")) > self.policy.max_request_bytes:
            raise ValueError("structured planner request exceeds policy byte limit")
        return request

    def _complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        response = self._backend.complete(request)
        parsed = StructuredModelResponse.model_validate(response.model_dump(mode="json"))
        if (
            parsed.request_id != request.request_id
            or parsed.request_fingerprint != request.fingerprint
            or parsed.backend != self.policy.expected_backend
            or parsed.model != self.policy.expected_model
        ):
            raise ValueError("structured planner response identity mismatch")
        if parsed.tool_calls:
            raise ValueError("structured UI planner rejects all tool-call proposals")
        response_payload = (
            parsed.raw_response.encode("utf-8")
            if parsed.raw_response is not None
            else _canonical_json(parsed.output_payload).encode("utf-8")
        )
        if len(response_payload) > self.policy.max_response_bytes:
            raise ValueError("structured planner response exceeds policy byte limit")
        if parsed.latency_ms > self.policy.max_latency_ms:
            raise ValueError("structured planner response exceeds policy latency limit")
        if parsed.usage.input_tokens > self.policy.max_input_tokens:
            raise ValueError("structured planner input usage exceeds policy")
        if parsed.usage.output_tokens > self.policy.max_output_tokens:
            raise ValueError("structured planner output usage exceeds policy")
        if (
            parsed.usage.input_tokens + parsed.usage.output_tokens
            > self.policy.max_input_tokens + self.policy.max_output_tokens
        ):
            raise ValueError("structured planner total usage exceeds policy")
        if parsed.usage.cost_usd is None:
            raise ValueError("structured planner requires API cost telemetry")
        if parsed.usage.cost_usd > self.policy.max_response_cost_usd:
            raise ValueError("structured planner response cost exceeds policy")
        return parsed


class FallbackWorkspacePlanner:
    """Use a model opportunistically while retaining a useful offline layout."""

    def __init__(
        self,
        primary: WorkspacePlanner | None,
        *,
        fallback: DeterministicWorkspacePlanner | None = None,
    ) -> None:
        if primary is not None and not isinstance(primary, WorkspacePlanner):
            raise TypeError("primary planner does not implement WorkspacePlanner")
        self.primary = primary
        self.fallback = fallback or DeterministicWorkspacePlanner()
        self.identity = (
            self.primary.identity if self.primary is not None else self.fallback.identity
        )

    @property
    def model_policy(self) -> ModelPlannerPolicy | None:
        """Expose only the bounded primary policy, never its backend or credential."""

        if isinstance(self.primary, StructuredWorkspacePlanner):
            return self.primary.policy
        return None

    def classify(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
        *,
        context: PlannerConversationContext | None = None,
    ) -> IntentPlannerOutcome:
        if self.primary is None:
            return self.fallback.classify(request, catalog, context=context)
        try:
            return self.primary.classify(request, catalog, context=context)
        except Exception:
            return IntentPlannerOutcome(
                status="unavailable",
                reason_code="model-intent-provider-unavailable",
                request_fingerprint=request.fingerprint,
            )

    def classify_offline(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
        *,
        context: PlannerConversationContext | None = None,
    ) -> IntentPlannerOutcome:
        """Bypass a configured provider when project resource policy does not admit it."""

        return self.fallback.classify(request, catalog, context=context)

    def compose(
        self,
        catalog: SurfaceCandidateCatalog,
        *,
        prompt_text: str | None = None,
        context: PlannerConversationContext | None = None,
    ) -> SurfacePlannerOutcome:
        if self.primary is None:
            return self.fallback.compose(catalog, prompt_text=prompt_text, context=context)
        try:
            primary = self.primary.compose(catalog, prompt_text=prompt_text, context=context)
        except Exception:
            primary = SurfacePlannerOutcome(
                status="unavailable",
                reason_code="model-surface-plan-unavailable",
            )
        if primary.status == "planned":
            return primary
        deterministic = self.fallback.compose(catalog, prompt_text=prompt_text, context=context)
        if deterministic.plan is None or deterministic.provenance is None:
            return SurfacePlannerOutcome(
                status="unavailable",
                reason_code="all-surface-planners-unavailable",
            )
        provenance = deterministic.provenance.model_copy(
            update={
                "mode": PlannerMode.DETERMINISTIC_FALLBACK,
                "attempted_planner": self.primary.identity,
            }
        )
        return SurfacePlannerOutcome(
            status="fallback",
            reason_code=primary.reason_code,
            plan=deterministic.plan,
            provenance=PlannerProvenance.model_validate(provenance.model_dump(mode="json")),
        )

    def compose_offline(
        self,
        catalog: SurfaceCandidateCatalog,
        *,
        prompt_text: str | None = None,
        context: PlannerConversationContext | None = None,
        reason_code: str = "project-planner-resource-not-admitted",
    ) -> SurfacePlannerOutcome:
        """Materialize the useful deterministic view without attempting a model call."""

        deterministic = self.fallback.compose(
            catalog,
            prompt_text=prompt_text,
            context=context,
        )
        return deterministic.model_copy(update={"reason_code": reason_code})

    def revise_program(
        self,
        request: ProgramRevisionRequest,
        catalog: ProgramRevisionCatalog,
        *,
        prior_record: ProgramRevisionRecord | None = None,
    ) -> ProgramRevisionOutcome:
        """Use model-authored content when available; never invent an offline draft."""

        if not isinstance(self.primary, ProgramRevisionPlanner):
            return ProgramRevisionOutcome(
                status="unavailable",
                reason_code="model-program-revision-unavailable",
                request_fingerprint=request.fingerprint,
                catalog_fingerprint=catalog.fingerprint,
                model_generated=False,
            )
        try:
            return self.primary.revise_program(
                request,
                catalog,
                prior_record=prior_record,
            )
        except Exception:
            return ProgramRevisionOutcome(
                status="unavailable",
                reason_code="model-program-revision-unavailable",
                request_fingerprint=request.fingerprint,
                catalog_fingerprint=catalog.fingerprint,
                planner_id=self.primary.identity.planner_id,
                model_generated=False,
            )


def _composition_input(catalog: SurfaceCandidateCatalog) -> dict[str, JsonValue]:
    """Return the complete data-free provider projection."""

    return {
        "project_id": catalog.intent.snapshot.project_id,
        "snapshot_revision": catalog.intent.snapshot.snapshot_revision,
        "snapshot_sha256": catalog.intent.snapshot.snapshot_sha256,
        "intent_goal": catalog.intent.goal.value,
        "intent_fingerprint": catalog.intent.fingerprint,
        "catalog_fingerprint": catalog.fingerprint,
        "candidates": [item.model_dump(mode="json") for item in catalog.descriptors()],
    }


def _model_composition_input(
    catalog: SurfaceCandidateCatalog,
    *,
    prompt_text: str | None,
    context: PlannerConversationContext | None,
) -> dict[str, JsonValue]:
    payload = _composition_input(catalog)
    descriptors = payload["candidates"]
    if not isinstance(descriptors, list):  # pragma: no cover - constructed above
        raise TypeError("surface candidate descriptors must be a list")
    payload["candidates"] = descriptors[:_MAX_MODEL_CANDIDATES]
    payload["current_prompt"] = prompt_text or f"Open {catalog.intent.goal.value}."
    offered_candidate_ids = {
        item["candidate_id"]
        for item in payload["candidates"]
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
    }
    payload["evidence_digest"] = _bounded_evidence_digest(
        catalog,
        offered_candidate_ids=offered_candidate_ids,
    )
    payload["conversation_history"] = (
        [
            {
                "turn_id": item.turn_id,
                "ordinal": item.ordinal,
                "prompt_kind": item.prompt_kind,
                "prompt_text": item.prompt_text,
            }
            for item in context.turns
        ]
        if context is not None
        else []
    )
    prior = None
    if context is not None:
        prior_turn = next(
            (item for item in reversed(context.turns) if item.authored_brief is not None),
            None,
        )
        if prior_turn is not None and prior_turn.authored_brief is not None:
            prior = {
                "turn_id": prior_turn.turn_id,
                "brief": prior_turn.authored_brief.model_dump(mode="json"),
                "surface_plan_entries": [
                    item.model_dump(mode="json")
                    for item in prior_turn.surface_entries
                    if item.candidate_id in offered_candidate_ids
                ],
            }
    payload["prior_generated_workspace"] = prior
    payload["projection_is_bounded"] = True
    return payload


def _normalize_redundant_surface_echoes(
    payload: dict[str, JsonValue],
    catalog: SurfaceCandidateCatalog,
    *,
    context: PlannerConversationContext | None,
) -> dict[str, JsonValue]:
    """Drop only a truthful redundant component echo from model plan entries.

    Some JSON-only providers copy the human-readable ``component`` field from
    the candidate descriptor even though the output contract intentionally uses
    candidate IDs alone.  The receiver may remove that echo only when it exactly
    matches the trusted catalog.  It also intersects the optional visual-focus
    hints with the selected candidate's exact evidence set; those hints are not
    claim citations, and an empty focus is valid. Edit lineage is likewise
    receiver-owned and is rebound to the latest cited prior model turn. Unknown,
    mismatched, or any other extra field remains in place and is rejected by the
    closed schema.
    """

    normalized = dict(payload)
    brief = payload.get("brief")
    if isinstance(brief, dict):
        normalized_brief = dict(brief)
        prior_turn = (
            next(
                (
                    item
                    for item in reversed(context.turns)
                    if item.authored_brief is not None
                ),
                None,
            )
            if context is not None
            else None
        )
        normalized_brief["edited_from_turn_id"] = (
            prior_turn.turn_id if prior_turn is not None else None
        )
        normalized["brief"] = normalized_brief
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return normalized
    candidates = {item.candidate_id: item for item in catalog.candidates}
    components = {
        candidate_id: item.component.component.value
        for candidate_id, item in candidates.items()
    }
    normalized_entries: list[JsonValue] = []
    for value in entries:
        if not isinstance(value, dict):
            normalized_entries.append(value)
            continue
        entry = dict(value)
        candidate_id = entry.get("candidate_id")
        component = entry.get("component")
        if (
            isinstance(candidate_id, str)
            and isinstance(component, str)
            and components.get(candidate_id) == component
        ):
            entry.pop("component")
        candidate = candidates.get(candidate_id) if isinstance(candidate_id, str) else None
        focus = entry.get("focus_ref_ids")
        if candidate is not None and isinstance(focus, list):
            allowed = set(candidate.component.evidence_ref_ids)
            entry["focus_ref_ids"] = list(
                dict.fromkeys(
                    evidence_id
                    for evidence_id in focus
                    if isinstance(evidence_id, str) and evidence_id in allowed
                )
            )
        normalized_entries.append(entry)
    normalized["entries"] = normalized_entries
    return normalized


def _surface_edit_delta(
    context: PlannerConversationContext | None,
    *,
    plan: SurfacePlan,
    brief: ModelAuthoredBrief,
) -> SurfaceEditDelta | None:
    """Describe the admitted edit without trusting the provider to report its own delta."""

    if context is None or brief.edited_from_turn_id is None:
        return None
    predecessor = next(
        (
            item
            for item in context.turns
            if item.turn_id == brief.edited_from_turn_id and item.authored_brief is not None
        ),
        None,
    )
    if predecessor is None:
        return None
    before = predecessor.surface_entries
    after = plan.entries
    before_by_id = {item.candidate_id: item for item in before}
    after_by_id = {item.candidate_id: item for item in after}
    retained = tuple(item.candidate_id for item in after if item.candidate_id in before_by_id)
    added = tuple(item.candidate_id for item in after if item.candidate_id not in before_by_id)
    removed = tuple(item.candidate_id for item in before if item.candidate_id not in after_by_id)
    before_retained = [item.candidate_id for item in before if item.candidate_id in after_by_id]
    after_retained = [item.candidate_id for item in after if item.candidate_id in before_by_id]
    before_positions = {candidate_id: index for index, candidate_id in enumerate(before_retained)}
    reordered = tuple(
        candidate_id
        for index, candidate_id in enumerate(after_retained)
        if before_positions[candidate_id] != index
    )
    regrouped = tuple(
        candidate_id
        for candidate_id in retained
        if before_by_id[candidate_id].group != after_by_id[candidate_id].group
    )
    reemphasized = tuple(
        candidate_id
        for candidate_id in retained
        if before_by_id[candidate_id].emphasis != after_by_id[candidate_id].emphasis
    )
    refocused = tuple(
        candidate_id
        for candidate_id in retained
        if before_by_id[candidate_id].focus_ref_ids != after_by_id[candidate_id].focus_ref_ids
    )
    previous_content = predecessor.authored_brief.model_dump(
        mode="json",
        exclude={"edited_from_turn_id"},
    )
    current_content = brief.model_dump(mode="json", exclude={"edited_from_turn_id"})
    return SurfaceEditDelta(
        predecessor_turn_id=predecessor.turn_id,
        retained_candidate_ids=retained,
        added_candidate_ids=added,
        removed_candidate_ids=removed,
        reordered_candidate_ids=reordered,
        regrouped_candidate_ids=regrouped,
        reemphasized_candidate_ids=reemphasized,
        refocused_candidate_ids=refocused,
        layout_changed=bool(
            added or removed or reordered or regrouped or reemphasized or refocused
        ),
        authored_content_changed=previous_content != current_content,
    )


def _bounded_evidence_digest(
    catalog: SurfaceCandidateCatalog,
    *,
    offered_candidate_ids: set[str],
) -> list[JsonValue]:
    """Expose bounded visible facts, never component actions or artifact locators."""

    digest: list[JsonValue] = []
    used_bytes = 0
    for candidate in catalog.candidates:
        if candidate.candidate_id not in offered_candidate_ids:
            continue
        entry: dict[str, JsonValue] = {
            "candidate_id": candidate.candidate_id,
            "component": candidate.component.component.value,
            "title": candidate.component.title,
            "evidence_ref_ids": list(candidate.component.evidence_ref_ids),
            "facts": _bounded_model_value(
                _model_visible_facts(candidate),
                depth=0,
                dict_key_limit=(
                    None
                    if candidate.component.component
                    is TrustedComponent.PROJECT_PROGRESS_BOARD
                    else 16
                ),
            ),
        }
        encoded = _canonical_json(entry).encode("utf-8")
        if used_bytes + len(encoded) > _MAX_MODEL_EVIDENCE_BYTES:
            break
        digest.append(entry)
        used_bytes += len(encoded)
    return digest


def _model_visible_facts(candidate: SurfaceCandidate) -> JsonValue:
    """Project the facts a model needs instead of truncating by key order."""

    value = candidate.component.data
    if (
        candidate.component.component is not TrustedComponent.PROJECT_PROGRESS_BOARD
        or not isinstance(value, dict)
    ):
        return value
    facts = {
        key: value[key]
        for key in (
            "project_status",
            "publication_ready",
            "focus",
            "focus_status",
            "focus_source",
            "next_gate",
            "milestone_state",
            "next_step_candidates",
        )
        if key in value
    }
    counts = value.get("counts")
    if isinstance(counts, dict):
        facts["counts"] = {
            key: counts[key]
            for key in (
                "runs_registered",
                "runs_completed",
                "runs_failed",
                "runs_blocked",
                "runs_active",
                "papers_registered",
                "evaluations_registered",
                "evaluation_results_registered",
                "acquisition_requests",
                "acquisition_receipts",
                "taste_candidate_populations",
                "taste_domain_expansions",
                "taste_source_review_campaigns",
            )
            if key in counts
        }
    populations = value.get("taste_candidate_populations")
    if isinstance(populations, list):
        facts["taste_candidate_populations"] = [
            {
                key: row[key]
                for key in (
                    "population_id",
                    "candidate_count",
                    "source_group_count",
                    "domain_count_observed",
                    "target_domain_count",
                    "target_domain_floor_met",
                    "target_population_floor",
                    "target_population_floor_met",
                    "alignment_agreement_count",
                    "alignment_disagreement_count",
                    "no_aligned_edit_count",
                    "synthetic_review_row_count_excluded",
                    "ready_for_taste_abstraction_review",
                    "ready_for_benchmark_admission",
                    "blocker_codes",
                    "verification_route",
                )
                if key in row
            }
            for row in populations
            if isinstance(row, dict)
        ]
    expansions = value.get("taste_domain_expansions")
    if isinstance(expansions, list):
        facts["taste_domain_expansions"] = [
            {
                key: row[key]
                for key in (
                    "population_id",
                    "selected_source_group_count",
                    "candidate_source_group_count",
                    "candidate_count",
                    "response_observed_count",
                    "domain_source_group_counts",
                    "recommendation_counts",
                    "observed_domain_count",
                    "target_domain_count",
                    "observed_domain_floor_met",
                    "minimum_groups_per_added_domain",
                    "added_domain_group_floor_met",
                    "independent_domain_review_complete",
                    "independent_quality_review_complete",
                    "decision_family_stratification_complete",
                    "privacy_review_complete",
                    "ready_for_taste_abstraction_review",
                    "ready_for_benchmark_admission",
                    "blocker_codes",
                    "verification_route",
                )
                if key in row
            }
            for row in expansions
            if isinstance(row, dict)
        ]
    review_campaigns = value.get("taste_source_review_campaigns")
    if isinstance(review_campaigns, list):
        facts["taste_source_review_campaigns"] = [
            {
                key: row[key]
                for key in (
                    "campaign_id",
                    "population_id",
                    "candidate_count",
                    "source_group_count",
                    "publisher_subject_group_counts",
                    "scientific_reviewer_count",
                    "privacy_reviewer_count",
                    "scientific_assessment_count",
                    "privacy_assessment_count",
                    "reviewer_sessions_prepared",
                    "reviewer_submissions_collected",
                    "review_collection_status",
                    "recruitment_status",
                    "owner_approval_required",
                    "review_sessions_ready",
                    "next_action",
                    "preparation_verification_route",
                    "recruitment_verification_route",
                    "submission_verification_route",
                    "eligible_candidate_count",
                    "adjudication_required_count",
                    "abstraction_input_count",
                    "abstraction_candidate_ceiling",
                    "abstraction_capacity_basis",
                    "abstraction_profile_ids",
                    "abstraction_profile_capacity",
                    "abstraction_profile_capacity_gap",
                    "ready_for_abstraction_model_authorization",
                    "abstraction_preparation_route",
                    "abstraction_model_execution_route",
                    "abstraction_human_review_route",
                    "ready_for_taste_abstraction_review",
                    "ready_for_benchmark_admission",
                    "standalone_preflight_performed",
                )
                if key in row
            }
            for row in review_campaigns
            if isinstance(row, dict)
        ]
    dataset_packages = value.get("dataset_packages")
    if isinstance(dataset_packages, list):
        facts["dataset_packages"] = [
            {
                key: row[key]
                for key in (
                    "request_id",
                    "selected_task_ids",
                    "asset_count",
                    "archive_safety_status",
                    "archive_member_count",
                    "license_coverage_status",
                    "license_verification_route",
                    "license_image_count",
                    "license_record_count",
                    "license_ingestion_ready",
                    "license_blocker_codes",
                    "authorizes_ingestion",
                    "authorizes_execution",
                )
                if key in row
            }
            for row in dataset_packages
            if isinstance(row, dict)
        ]
    lifecycle = value.get("lifecycle")
    if isinstance(lifecycle, dict):
        facts["lifecycle"] = {
            key: lifecycle[key]
            for key in (
                "lifecycle_state",
                "idea_to_paper_complete",
                "scientific_evidence_complete",
                "scientific_effectiveness_established",
                "internal_review_cycle_complete",
                "independent_pre_submission_review_complete",
                "top_venue_evidence_loop_complete",
            )
            if key in lifecycle
        }
    program = value.get("evidence_program")
    if isinstance(program, dict):
        facts["scientific_program"] = {
            key: program[key]
            for key in (
                "program_id",
                "current_stage_id",
                "current_decision",
                "control_effect",
                "planning_directive",
            )
            if key in program
        }
    resources = value.get("resource_portfolio")
    if isinstance(resources, dict):
        facts["resource_summary"] = {
            key: resources[key]
            for key in (
                "resource_count",
                "verified_binding_count",
                "pending_binding_count",
                "blocked_binding_count",
                "available_resource_count",
                "configuration_authority",
                "planner_binding_state",
                "planner_resource_id",
                "planner_provider_id",
                "planner_model_id",
            )
            if key in resources
        }
        if "resources" in resources:
            facts["project_resources"] = resources["resources"]
        if "available_resources" in resources:
            facts["available_project_resources"] = resources["available_resources"]
    return facts


def _bounded_model_value(
    value: JsonValue,
    *,
    depth: int,
    dict_key_limit: int | None = 16,
) -> JsonValue:
    # Keep leaf facts at the boundary.  Bounding every value at depth three
    # erased the scalar fields of list-backed progress rows (for example the
    # exact candidate and domain counts) while still paying to send the row
    # structure to the model.  Only nested containers need truncation here.
    if depth >= 3 and isinstance(value, dict):
        return "[bounded]"
    if depth >= 3 and isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return [
                _bounded_model_value(
                    item,
                    depth=depth + 1,
                    dict_key_limit=dict_key_limit,
                )
                for item in value[:5]
            ]
        return "[bounded]"
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        keys = sorted(value)
        if dict_key_limit is not None:
            keys = keys[:dict_key_limit]
        for key in keys:
            lowered = key.lower()
            if (
                lowered in {"locator", "path", "credential_env"}
                or lowered.endswith("_locator")
                or lowered.endswith("_path")
                or lowered.endswith("_sha256")
            ):
                continue
            result[key] = _bounded_model_value(
                value[key],
                depth=depth + 1,
                dict_key_limit=dict_key_limit,
            )
        return result
    if isinstance(value, list):
        return [
            _bounded_model_value(
                item,
                depth=depth + 1,
                dict_key_limit=dict_key_limit,
            )
            for item in value[:5]
        ]
    if isinstance(value, str) and len(value) > 320:
        return value[:319] + "…"
    return value


def _validate_model_authored_brief(
    brief: ModelAuthoredBrief,
    catalog: SurfaceCandidateCatalog,
    plan: SurfacePlan,
    *,
    digest_candidate_ids: set[str],
    context: PlannerConversationContext | None,
) -> None:
    candidates = {item.candidate_id: item for item in catalog.candidates}
    selected = {item.candidate_id for item in plan.entries}
    cited_items = list(brief.points)
    if brief.canvas is not None:
        cited_items.extend(brief.canvas.nodes)
    for item in cited_items:
        if set(item.source_candidate_ids) - digest_candidate_ids:
            raise ValueError("model-authored content cites a candidate outside its evidence digest")
        if set(item.source_candidate_ids) - selected:
            raise ValueError("model-authored content cites a candidate outside its layout")
        allowed_evidence = {
            evidence_id
            for candidate_id in item.source_candidate_ids
            for evidence_id in candidates[candidate_id].component.evidence_ref_ids
        }
        if set(item.evidence_ref_ids) - allowed_evidence:
            raise ValueError("model-authored content cites evidence outside its source candidates")
    prior_turn = None
    if context is not None:
        prior_turn = next(
            (item for item in reversed(context.turns) if item.authored_brief is not None),
            None,
        )
    expected = prior_turn.turn_id if prior_turn is not None else None
    if brief.edited_from_turn_id != expected:
        raise ValueError("model-authored content does not bind its exact edit predecessor")


def _admit_cited_candidates(
    entries: tuple[SurfacePlanEntry, ...],
    brief: ModelAuthoredBrief,
    catalog: SurfaceCandidateCatalog,
    *,
    offered_candidate_ids: set[str],
) -> tuple[SurfacePlanEntry, ...]:
    """Include cited server candidates without trusting the model to duplicate bookkeeping."""

    cited_items = list(brief.points)
    if brief.canvas is not None:
        cited_items.extend(brief.canvas.nodes)
    cited_ids = {candidate_id for item in cited_items for candidate_id in item.source_candidate_ids}
    if cited_ids - offered_candidate_ids:
        raise ValueError("model-authored content cites a candidate outside its evidence digest")
    selected = {item.candidate_id for item in entries}
    by_id = {item.candidate_id: item for item in catalog.candidates}
    admitted = list(entries)
    for candidate_id in sorted(cited_ids - selected):
        candidate = by_id[candidate_id]
        admitted.append(_deterministic_entry(candidate, len(admitted)))
    if len(admitted) > 12:
        raise ValueError("model-authored citations exceed the bounded surface capacity")
    return tuple(admitted)


def _program_revision_failure_reason(exc: Exception) -> str:
    """Return a content-free diagnostic category without serializing provider output."""

    if isinstance(exc, StructuredBackendDisabledError):
        return "model-program-revision-backend-disabled"
    if isinstance(exc, httpx.HTTPStatusError):
        return "model-program-revision-provider-http-error"
    if isinstance(exc, httpx.TransportError):
        return "model-program-revision-provider-transport-error"
    if isinstance(exc, StructuredProviderResponseError):
        return "model-program-revision-provider-response-invalid"
    if "cost telemetry" in str(exc):
        return "model-program-revision-cost-telemetry-unavailable"
    if isinstance(exc, ValidationError):
        error_types = {item["type"] for item in exc.errors()}
        if "extra_forbidden" in error_types:
            return "model-program-revision-unexpected-fields"
        if "missing" in error_types:
            return "model-program-revision-missing-fields"
        return "model-program-revision-field-schema-rejected"
    if isinstance(exc, ValueError):
        message = str(exc)
        if "reprioritization" in message:
            return "model-program-revision-stage-order-rejected"
        if "resource" in message:
            return "model-program-revision-resource-selection-rejected"
        if "focused action route" in message:
            return "model-program-revision-route-focus-rejected"
        if "track" in message or "stage" in message:
            return "model-program-revision-identifier-rejected"
        if "verification" in message:
            return "model-program-revision-verification-advice-rejected"
        return "model-program-revision-schema-rejected"
    return "model-program-revision-unavailable"


def _surface_composition_failure_reason(exc: Exception) -> str:
    """Keep actionable failure categories while never returning provider text."""

    if isinstance(exc, StructuredBackendDisabledError):
        return "model-surface-plan-backend-disabled"
    if isinstance(exc, httpx.HTTPStatusError):
        return "model-surface-plan-provider-http-error"
    if isinstance(exc, httpx.TransportError):
        return "model-surface-plan-provider-transport-error"
    if isinstance(exc, StructuredProviderResponseError):
        return "model-surface-plan-provider-response-invalid"
    if "cost telemetry" in str(exc):
        return "model-surface-plan-cost-telemetry-unavailable"
    if "request exceeds policy byte limit" in str(exc):
        return "model-surface-plan-request-too-large"
    if isinstance(exc, (ValidationError, ValueError)):
        return "model-surface-plan-schema-rejected"
    return "model-surface-plan-unavailable"


def _composition_provenance(
    *,
    mode: PlannerMode,
    planner: PlannerIdentity,
    catalog: SurfaceCandidateCatalog,
    request_fingerprint: str,
    plan: SurfacePlan,
    provider_response_sha256: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    latency_ms: float | None = None,
    provider_cached: bool | None = None,
    content_fingerprint: str | None = None,
) -> PlannerProvenance:
    return PlannerProvenance(
        operation=PlannerOperation.SURFACE_COMPOSITION,
        mode=mode,
        planner=planner,
        project_id=catalog.intent.snapshot.project_id,
        snapshot_revision=catalog.intent.snapshot.snapshot_revision,
        snapshot_sha256=catalog.intent.snapshot.snapshot_sha256,
        intent_fingerprint=catalog.intent.fingerprint,
        catalog_fingerprint=catalog.fingerprint,
        request_fingerprint=request_fingerprint,
        provider_response_sha256=provider_response_sha256,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        provider_cached=provider_cached,
        result_fingerprint=plan.fingerprint,
        content_fingerprint=content_fingerprint,
        deterministic_reproducible=mode != PlannerMode.MODEL_ASSISTED,
    )


def _validate_question_catalog_binding(
    request: FreeQuestionRequest,
    catalog: QuickIntentCatalog,
) -> None:
    if (
        request.project_id != catalog.snapshot.project_id
        or request.snapshot_revision != catalog.snapshot.snapshot_revision
        or request.snapshot_sha256 != catalog.snapshot.snapshot_sha256
    ):
        raise ValueError("free question and quick-intent catalog snapshots differ")


def _validate_conversation_context(
    request: FreeQuestionRequest,
    context: PlannerConversationContext | None,
) -> None:
    if context is not None and context.project_id != request.project_id:
        raise ValueError("conversation context belongs to another project")


def _deterministic_candidate_key(
    candidate: SurfaceCandidate,
    goal: IntentGoal,
) -> tuple[int, int, str]:
    priority = _GOAL_COMPONENT_PRIORITIES[goal].get(candidate.component.component, 50)
    action_priority = 0 if candidate.actions else 1
    return (priority, action_priority, candidate.candidate_id)


def _deterministic_entry(candidate: SurfaceCandidate, index: int) -> SurfacePlanEntry:
    group = candidate.allowed_groups[0]
    if index == 0 and PlanEmphasis.FEATURED in candidate.allowed_emphasis:
        emphasis = PlanEmphasis.FEATURED
    elif (
        candidate.component.component == TrustedComponent.PROJECT_PROGRESS_BOARD
        and PlanEmphasis.COMPACT in candidate.allowed_emphasis
    ):
        emphasis = PlanEmphasis.COMPACT
    else:
        emphasis = candidate.allowed_emphasis[0]
    focus = tuple(candidate.component.evidence_ref_ids[:1])
    return SurfacePlanEntry(
        candidate_id=candidate.candidate_id,
        group=group,
        emphasis=emphasis,
        focus_ref_ids=focus,
    )


_GOAL_COMPONENT_PRIORITIES = {
    IntentGoal.PROGRESS_REVIEW: {
        TrustedComponent.PROJECT_PROGRESS_BOARD: 0,
        TrustedComponent.EVIDENCE_GRAPH: 5,
        TrustedComponent.RUN_STAGE_EXPLORER: 10,
        TrustedComponent.STAGE_TIMELINE: 11,
        TrustedComponent.RUN_BLOCKER_PANEL: 20,
        TrustedComponent.BLOCKER_LIST: 20,
        TrustedComponent.EVIDENCE_INVENTORY: 30,
        TrustedComponent.PAPER_PREVIEW: 31,
        TrustedComponent.PROJECT_SUMMARY_CARD: 40,
        TrustedComponent.RUN_HEALTH: 41,
    },
    IntentGoal.BLOCKER_DIAGNOSIS: {
        TrustedComponent.RUN_BLOCKER_PANEL: 0,
        TrustedComponent.BLOCKER_LIST: 0,
        TrustedComponent.PROJECT_PROGRESS_BOARD: 10,
        TrustedComponent.RUN_HEALTH: 20,
        TrustedComponent.PROJECT_SUMMARY_CARD: 30,
    },
    IntentGoal.RUN_COMPARISON: {
        TrustedComponent.RUN_COMPARISON_PANEL: 0,
        TrustedComponent.DECISION_COMPARISON: 0,
        TrustedComponent.PROJECT_PROGRESS_BOARD: 10,
        TrustedComponent.RUN_HEALTH: 20,
        TrustedComponent.PROJECT_SUMMARY_CARD: 30,
    },
    IntentGoal.PAPER_EVIDENCE_REVIEW: {
        TrustedComponent.PAPER_PREVIEW: 0,
        TrustedComponent.ARTIFACT_VIEWER: 1,
        TrustedComponent.EVIDENCE_INVENTORY: 2,
        TrustedComponent.CLAIM_MATRIX: 3,
        TrustedComponent.REVIEWER_QUEUE: 4,
        TrustedComponent.PROJECT_PROGRESS_BOARD: 10,
        TrustedComponent.PROJECT_SUMMARY_CARD: 20,
        TrustedComponent.RUN_HEALTH: 21,
    },
    IntentGoal.NEXT_STEP_REVIEW: {
        TrustedComponent.PROJECT_PROGRESS_BOARD: 0,
        TrustedComponent.EVIDENCE_GRAPH: 5,
        TrustedComponent.PROJECT_SUMMARY_CARD: 10,
        TrustedComponent.RUN_HEALTH: 11,
    },
    IntentGoal.RESEARCH_LANDSCAPE_REVIEW: {
        TrustedComponent.RESEARCH_LANDSCAPE_MAP: 0,
        TrustedComponent.PROJECT_PROGRESS_BOARD: 10,
        TrustedComponent.PROJECT_SUMMARY_CARD: 20,
    },
}

_GOAL_SELECTED_COMPONENTS = {
    IntentGoal.PROGRESS_REVIEW: frozenset(
        {
            TrustedComponent.PROJECT_PROGRESS_BOARD,
            TrustedComponent.EVIDENCE_GRAPH,
        }
    ),
    IntentGoal.BLOCKER_DIAGNOSIS: frozenset(
        {
            TrustedComponent.RUN_BLOCKER_PANEL,
            TrustedComponent.EVIDENCE_GRAPH,
        }
    ),
    IntentGoal.RUN_COMPARISON: frozenset(
        {
            TrustedComponent.RUN_COMPARISON_PANEL,
            TrustedComponent.DECISION_COMPARISON,
            TrustedComponent.PROJECT_PROGRESS_BOARD,
            TrustedComponent.PROJECT_SUMMARY_CARD,
        }
    ),
    IntentGoal.PAPER_EVIDENCE_REVIEW: frozenset(
        {
            TrustedComponent.PAPER_PREVIEW,
            TrustedComponent.ARTIFACT_VIEWER,
            TrustedComponent.EVIDENCE_INVENTORY,
            TrustedComponent.CLAIM_MATRIX,
            TrustedComponent.REVIEWER_QUEUE,
            TrustedComponent.AVAILABILITY_NOTICE,
            TrustedComponent.PROJECT_PROGRESS_BOARD,
            TrustedComponent.PROJECT_SUMMARY_CARD,
        }
    ),
    IntentGoal.NEXT_STEP_REVIEW: frozenset(
        {
            TrustedComponent.PROJECT_PROGRESS_BOARD,
            TrustedComponent.EVIDENCE_GRAPH,
            TrustedComponent.PROJECT_SUMMARY_CARD,
        }
    ),
    IntentGoal.RESEARCH_LANDSCAPE_REVIEW: frozenset(
        {
            TrustedComponent.RESEARCH_LANDSCAPE_MAP,
        }
    ),
}


def _json_size(value: JsonValue | dict[str, object]) -> int:
    return len(_canonical_json(value).encode("utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


__all__ = [
    "DeterministicWorkspacePlanner",
    "FallbackWorkspacePlanner",
    "IntentPlannerChoice",
    "IntentPlannerOutcome",
    "ModelAuthoredBrief",
    "ModelAuthoredCanvas",
    "ModelAuthoredCanvasEdge",
    "ModelAuthoredCanvasNode",
    "ModelPlannerPolicy",
    "PlannerContextTurn",
    "PlannerConversationContext",
    "PlannerIdentity",
    "PlannerMode",
    "PlannerOperation",
    "PlannerProvenance",
    "StructuredWorkspacePlanner",
    "SurfaceEditDelta",
    "SurfacePlannerOutcome",
    "WorkspacePlanner",
]
