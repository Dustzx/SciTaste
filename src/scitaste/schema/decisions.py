"""Auditable research decision records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from scitaste.schema.actions import ResearchAction


def utc_now() -> datetime:
    return datetime.now(UTC)


class ModelDecisionUsage(BaseModel):
    """Bounded provider usage copied into the durable decision record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class ModelDecisionTrace(BaseModel):
    """Content identity for one model-backed fixed-candidate selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1)
    decision_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_action_ids: tuple[str, ...] = Field(min_length=1)
    candidate_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    selected_action_id: str = Field(min_length=1)
    response_raw_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float | None = Field(default=None, ge=0)
    semantic_attempts: int = Field(default=1, ge=1)
    usage: ModelDecisionUsage = Field(default_factory=ModelDecisionUsage)
    cached: bool = False

    @model_validator(mode="after")
    def selection_belongs_to_closed_candidates(self) -> ModelDecisionTrace:
        if len(set(self.candidate_action_ids)) != len(self.candidate_action_ids):
            raise ValueError("model decision candidate action IDs must be unique")
        if self.selected_action_id not in self.candidate_action_ids:
            raise ValueError("model decision selected action must be a candidate")
        return self


class ModelCandidateGenerationTrace(BaseModel):
    """Content identity for one model-backed candidate concretization call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1)
    decision_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_action_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    template_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_candidate_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    admitted_candidate_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_override_keys: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    proposal_rationales: dict[str, str] = Field(default_factory=dict)
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    response_raw_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latency_ms: float | None = Field(default=None, ge=0)
    semantic_attempts: int = Field(default=1, ge=1)
    usage: ModelDecisionUsage = Field(default_factory=ModelDecisionUsage)
    cached: bool = False

    @model_validator(mode="after")
    def admitted_candidates_preserve_template_identity(self) -> ModelCandidateGenerationTrace:
        if len(set(self.template_action_ids)) != len(self.template_action_ids):
            raise ValueError("candidate-generation template action IDs must be unique")
        if self.admitted_candidate_ids != self.template_action_ids:
            raise ValueError(
                "candidate generation must preserve template action identity and order"
            )
        if set(self.parameter_override_keys) - set(self.admitted_candidate_ids):
            raise ValueError("candidate override trace references an unknown admitted action")
        if set(self.proposal_rationales) != set(self.admitted_candidate_ids):
            raise ValueError("candidate-generation rationale coverage must be exact")
        return self


class TasteDeliberationTrace(BaseModel):
    """Ledger identity and closed-pool result for decision-aware Taste selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    ledger_locator: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    broad_candidate_case_ids: tuple[str, ...] = Field(min_length=2, max_length=20)
    selected_case_ids: tuple[str, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def selection_is_a_closed_subset(self) -> TasteDeliberationTrace:
        if len(self.broad_candidate_case_ids) != len(set(self.broad_candidate_case_ids)):
            raise ValueError("Taste deliberation broad candidate IDs must be unique")
        if len(self.selected_case_ids) != len(set(self.selected_case_ids)):
            raise ValueError("Taste deliberation selected case IDs must be unique")
        if not set(self.selected_case_ids).issubset(self.broad_candidate_case_ids):
            raise ValueError("Taste deliberation selection must stay inside the broad pool")
        return self


class LifecycleTastePolicyTrace(BaseModel):
    """Exact learned-policy assessment applied or abstained for one candidate set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0", "1.1"] = "1.0"
    policy_id: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_family: str | None = Field(default=None, min_length=1)
    family_policy_id: str | None = Field(default=None, min_length=1)
    family_policy_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    idea_revision_id: str = Field(min_length=1)
    idea_revision_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_idea_revision_id: str | None = None
    observed_idea_revision_record_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommended_action_id: str | None = None
    abstained: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)
    action_adjustments: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def trace_is_closed(self) -> LifecycleTastePolicyTrace:
        if self.abstained != (self.recommended_action_id is None):
            raise ValueError("lifecycle Taste trace abstention and recommendation disagree")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("lifecycle Taste trace reason codes must be unique")
        if (self.observed_idea_revision_id is None) != (
            self.observed_idea_revision_record_sha256 is None
        ):
            raise ValueError("observed lifecycle Taste Idea identity is incomplete")
        family_values = (
            self.decision_family,
            self.family_policy_id,
            self.family_policy_sha256,
        )
        if any(item is not None for item in family_values) != all(
            item is not None for item in family_values
        ):
            raise ValueError("family-conditioned lifecycle Taste identity is incomplete")
        if self.schema_version == "1.0" and any(item is not None for item in family_values):
            raise ValueError("legacy lifecycle Taste trace cannot claim family conditioning")
        if self.schema_version == "1.1" and not all(item is not None for item in family_values):
            raise ValueError("schema-1.1 lifecycle Taste trace requires family conditioning")
        if self.recommended_action_id is not None and (
            self.recommended_action_id not in self.action_adjustments
        ):
            raise ValueError("lifecycle Taste trace recommendation is outside the candidates")
        if any(
            value != value or value in {float("inf"), float("-inf")}
            for value in self.action_adjustments.values()
        ):
            raise ValueError("lifecycle Taste trace adjustments must be finite")
        return self


class TasteInterventionTrace(BaseModel):
    """Durable proof that a formal single-variable contract gated a decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hypothesis: Literal["H2b_taste_selection", "H3_lifecycle_credit", "H4_native_effect"]
    condition_id: str = Field(min_length=1)
    changed_dimension: Literal["selector-mode", "credit-update", "policy-weight"]
    selector_mode: Literal["disabled", "lexical", "deliberative"]
    lifecycle_update_mode: str | None = None
    lifecycle_policy_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_training_corpus_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    lifecycle_policy_weight: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    action_menu_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    precedent_pool_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_source_groups_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    precedent_source_groups_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    heldout_source_groups_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_assignment_schedule_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    selector_runtime_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    controller_backbone_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_snapshot_id: str = Field(pattern=r"^state-[0-9a-f]{64}$")
    resource_budget_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_provider: str = Field(min_length=1)
    decision_model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    seed: int = Field(ge=0)
    source_identity_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repair_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idea_revision_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def trace_is_closed(self) -> TasteInterventionTrace:
        from scitaste.project.models import content_sha256

        expected = content_sha256(self.model_dump(mode="json", exclude={"trace_sha256"}))
        if self.trace_sha256 != expected:
            raise ValueError("Taste intervention trace hash differs")
        return self

    @classmethod
    def create(cls, **values: Any) -> TasteInterventionTrace:
        payload = {"schema_version": "1.0", **values}
        payload.pop("trace_sha256", None)
        from scitaste.project.models import content_sha256

        unsigned = cls.model_construct(trace_sha256="0" * 64, **payload)
        return cls(
            **payload,
            trace_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"trace_sha256"})),
        )


class ResearchDecision(BaseModel):
    """Controller output and the unit of future taste memory."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: str = Field(default_factory=lambda: f"dec-{uuid4().hex}")
    timestamp: datetime = Field(default_factory=utc_now)
    stage: str
    state_snapshot_id: str
    candidate_actions: list[ResearchAction] = Field(min_length=1)
    retrieved_taste_cases: list[str] = Field(default_factory=list)
    selected_action: ResearchAction
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    expected_cost: dict[str, float] = Field(default_factory=dict)
    expected_value: dict[str, float] = Field(default_factory=dict)
    candidate_scores: dict[str, float | None] = Field(default_factory=dict)
    model_candidate_generation: ModelCandidateGenerationTrace | None = None
    taste_deliberation: TasteDeliberationTrace | None = None
    lifecycle_taste_policy: LifecycleTastePolicyTrace | None = None
    taste_intervention: TasteInterventionTrace | None = None
    model_decision: ModelDecisionTrace | None = None
    executor_result_id: str | None = None
    actual_outcome: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def omit_absent_model_trace(self, handler: Any) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        if self.model_candidate_generation is None:
            payload.pop("model_candidate_generation", None)
        if self.taste_deliberation is None:
            payload.pop("taste_deliberation", None)
        if self.lifecycle_taste_policy is None:
            payload.pop("lifecycle_taste_policy", None)
        if self.taste_intervention is None:
            payload.pop("taste_intervention", None)
        if self.model_decision is None:
            payload.pop("model_decision", None)
        return payload

    @model_validator(mode="after")
    def selected_action_was_a_candidate(self) -> ResearchDecision:
        from scitaste.project.models import content_sha256

        candidate_ids = {action.action_id for action in self.candidate_actions}
        if self.selected_action.action_id not in candidate_ids:
            raise ValueError("selected_action must belong to candidate_actions")
        if (
            self.model_decision is not None
            and self.model_decision.selected_action_id != self.selected_action.action_id
        ):
            raise ValueError("model decision and selected action must agree")
        if self.model_candidate_generation is not None and not set(
            self.model_candidate_generation.admitted_candidate_ids
        ).issubset(candidate_ids):
            raise ValueError("model-generated candidates must belong to candidate_actions")
        intervention = self.taste_intervention
        if intervention is not None:
            action_menu = tuple(
                {
                    "action_id": action.action_id,
                    "action_type": action.type.value,
                    "action_sha256": content_sha256(action),
                }
                for action in self.candidate_actions
            )
            if content_sha256(action_menu) != intervention.action_menu_sha256:
                raise ValueError("Taste intervention trace differs from final candidate actions")
            if self.state_snapshot_id != intervention.state_snapshot_id:
                raise ValueError("Taste intervention trace differs from decision state")
            if self.model_candidate_generation is not None:
                raise ValueError("formal Taste intervention cannot generate candidate actions")
            deliberative = intervention.selector_mode == "deliberative"
            if deliberative != (self.taste_deliberation is not None):
                raise ValueError("Taste intervention selector and deliberation trace differ")
            lifecycle_required = intervention.hypothesis in {
                "H3_lifecycle_credit",
                "H4_native_effect",
            }
            if lifecycle_required != (self.lifecycle_taste_policy is not None):
                raise ValueError("Taste intervention and lifecycle policy trace differ")
            if self.lifecycle_taste_policy is not None and (
                self.lifecycle_taste_policy.policy_sha256 != intervention.lifecycle_policy_sha256
            ):
                raise ValueError("Taste intervention lifecycle policy identity differs")
            if self.model_decision is not None and (
                self.model_decision.backend != intervention.decision_provider
                or self.model_decision.model != intervention.decision_model
                or self.model_decision.prompt_version != intervention.prompt_version
            ):
                raise ValueError("Taste intervention model-decision identity differs")
            if self.model_decision is None and (
                intervention.decision_provider != "scitaste-native"
                or intervention.decision_model != "deterministic-utility-controller"
            ):
                raise ValueError("Taste intervention lacks its declared model decision")
        return self
