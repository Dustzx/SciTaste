"""Bounded deterministic and optional model-assisted workspace planning."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

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


class PlannerMode(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model_assisted"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class PlannerOperation(StrEnum):
    INTENT_CLASSIFICATION = "intent_classification"
    SURFACE_COMPOSITION = "surface_composition"


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
    max_request_bytes: int = Field(default=64_000, ge=512, le=1_000_000)
    max_response_bytes: int = Field(default=24_000, ge=256, le=1_000_000)
    max_input_tokens: int = Field(default=12_000, ge=1, le=1_000_000)
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
    provider_response_sha256: Sha256 | None = None
    result_fingerprint: Sha256 | None = None
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
        elif self.intent_fingerprint is not None:
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


class SurfacePlannerOutcome(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["planned", "fallback", "unavailable"]
    reason_code: SafeIdentifier
    plan: SurfacePlan | None = None
    provenance: PlannerProvenance | None = None

    @model_validator(mode="after")
    def plan_matches_status(self) -> SurfacePlannerOutcome:
        if self.status in {"planned", "fallback"}:
            if self.plan is None or self.provenance is None:
                raise ValueError("successful planning outcome requires plan and provenance")
            if self.provenance.result_fingerprint != self.plan.fingerprint:
                raise ValueError("planning provenance does not bind the selected plan")
        elif self.plan is not None:
            raise ValueError("unavailable planning outcome cannot contain a plan")
        return self


@runtime_checkable
class WorkspacePlanner(Protocol):
    """Narrow UI planner boundary; it has no executor or state mutation method."""

    identity: PlannerIdentity

    def classify(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
    ) -> IntentPlannerOutcome: ...

    def compose(self, catalog: SurfaceCandidateCatalog) -> SurfacePlannerOutcome: ...


class DeterministicWorkspacePlanner:
    """Stable provider-free layout for every admitted canonical intent."""

    def __init__(self) -> None:
        configuration = {
            "algorithm": "intent-component-filter-priority-then-candidate-id",
            "max_entries": 12,
            "version": "1.1",
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
    ) -> IntentPlannerOutcome:
        _validate_question_catalog_binding(request, catalog)
        return IntentPlannerOutcome(
            status="unavailable",
            reason_code="deterministic-long-tail-classification-unavailable",
            request_fingerprint=request.fingerprint,
        )

    def compose(self, catalog: SurfaceCandidateCatalog) -> SurfacePlannerOutcome:
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
    ) -> IntentPlannerOutcome:
        _validate_question_catalog_binding(request, catalog)
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
        try:
            structured_request = self._request(
                operation=PlannerOperation.INTENT_CLASSIFICATION,
                project_id=request.project_id,
                snapshot_revision=request.snapshot_revision,
                snapshot_sha256=request.snapshot_sha256,
                input_payload=input_payload,
                output_schema=IntentPlannerChoice.model_json_schema(mode="validation"),
                identity_fingerprint=request.fingerprint,
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
            provider_response_sha256=response.raw_response_sha256,
            deterministic_reproducible=False,
        )
        return IntentPlannerOutcome(
            status="selected",
            reason_code="model-intent-selection-admitted",
            request_fingerprint=request.fingerprint,
            selected_quick_intent_id=choice.quick_intent_id,
            provenance=provenance,
        )

    def compose(self, catalog: SurfaceCandidateCatalog) -> SurfacePlannerOutcome:
        trusted = SurfaceCandidateCatalog.model_validate(catalog.model_dump(mode="json"))
        input_payload = _composition_input(trusted)
        try:
            structured_request = self._request(
                operation=PlannerOperation.SURFACE_COMPOSITION,
                project_id=trusted.intent.snapshot.project_id,
                snapshot_revision=trusted.intent.snapshot.snapshot_revision,
                snapshot_sha256=trusted.intent.snapshot.snapshot_sha256,
                input_payload=input_payload,
                output_schema=SurfacePlan.model_json_schema(mode="validation"),
                identity_fingerprint=trusted.fingerprint,
            )
            response = self._complete(structured_request)
            plan = SurfacePlan.model_validate(response.output_payload)
            materialize_surface_plan(trusted, plan)
        except Exception:
            return SurfacePlannerOutcome(
                status="unavailable",
                reason_code="model-surface-plan-unavailable",
            )
        return SurfacePlannerOutcome(
            status="planned",
            reason_code="model-surface-plan-admitted",
            plan=plan,
            provenance=_composition_provenance(
                mode=PlannerMode.MODEL_ASSISTED,
                planner=self.identity,
                catalog=trusted,
                request_fingerprint=structured_request.fingerprint,
                plan=plan,
                provider_response_sha256=response.raw_response_sha256,
            ),
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
            system_instruction=(
                "Select only identifiers and enum values present in input_payload. "
                "Return one JSON object matching output_schema. Never add facts, content, "
                "actions, URLs, paths, commands, tools, or explanations."
            ),
            input_payload=input_payload,
            output_schema=output_schema,
            seed=0,
            prompt_version="generative-ui-planner-v1",
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

    def classify(
        self,
        request: FreeQuestionRequest,
        catalog: QuickIntentCatalog,
    ) -> IntentPlannerOutcome:
        if self.primary is None:
            return self.fallback.classify(request, catalog)
        try:
            return self.primary.classify(request, catalog)
        except Exception:
            return IntentPlannerOutcome(
                status="unavailable",
                reason_code="model-intent-provider-unavailable",
                request_fingerprint=request.fingerprint,
            )

    def compose(self, catalog: SurfaceCandidateCatalog) -> SurfacePlannerOutcome:
        if self.primary is None:
            return self.fallback.compose(catalog)
        try:
            primary = self.primary.compose(catalog)
        except Exception:
            primary = SurfacePlannerOutcome(
                status="unavailable",
                reason_code="model-surface-plan-unavailable",
            )
        if primary.status == "planned":
            return primary
        deterministic = self.fallback.compose(catalog)
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


def _composition_provenance(
    *,
    mode: PlannerMode,
    planner: PlannerIdentity,
    catalog: SurfaceCandidateCatalog,
    request_fingerprint: str,
    plan: SurfacePlan,
    provider_response_sha256: str | None = None,
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
        result_fingerprint=plan.fingerprint,
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
    IntentGoal.BLOCKER_DIAGNOSIS: frozenset(
        {
            TrustedComponent.RUN_BLOCKER_PANEL,
            TrustedComponent.BLOCKER_LIST,
            TrustedComponent.PROJECT_PROGRESS_BOARD,
            TrustedComponent.PROJECT_SUMMARY_CARD,
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
            TrustedComponent.PROJECT_SUMMARY_CARD,
        }
    ),
    IntentGoal.RESEARCH_LANDSCAPE_REVIEW: frozenset(
        {
            TrustedComponent.RESEARCH_LANDSCAPE_MAP,
            TrustedComponent.PROJECT_PROGRESS_BOARD,
            TrustedComponent.PROJECT_SUMMARY_CARD,
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
    "ModelPlannerPolicy",
    "PlannerIdentity",
    "PlannerMode",
    "PlannerOperation",
    "PlannerProvenance",
    "StructuredWorkspacePlanner",
    "SurfacePlannerOutcome",
    "WorkspacePlanner",
]
