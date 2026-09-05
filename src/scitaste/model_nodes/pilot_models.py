"""Versioned data contracts for the bounded model-node pilot.

The pilot is intentionally separate from the product workflow.  Its contracts
describe auditable, self-dogfooding-only experiments; they do not make model
outputs executable or retrieval eligible.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.schemas import (
    AmbiguousActionInput,
    InterpretationThreatInput,
    ReviewSemanticInput,
)

PILOT_SCHEMA_VERSION = "1.0"


def _canonical_json(value: Any) -> bytes:
    """Return the pilot's canonical JSON representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Hash a JSON-compatible value using the pilot's canonical encoding."""

    return hashlib.sha256(_canonical_json(value)).hexdigest()


class PilotModel(BaseModel):
    """Base class for immutable and closed pilot contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PilotCondition(StrEnum):
    DETERMINISTIC_ONLY = "deterministic_only"
    SCRIPTED_NODE = "scripted_node"
    REPLAY_NODE = "replay_node"
    LIVE_STRUCTURED_NODE = "live_structured_node"


class PilotNodeType(StrEnum):
    REVIEW_SEMANTIC = "review-semantic"
    INTERPRETATION_THREAT = "interpretation-threat"
    AMBIGUOUS_ACTION = "ambiguous-action"


class ExpectedApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class PilotOutcome(StrEnum):
    BASELINE = "baseline"
    PLANNED = "planned"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class ReplayEvidenceRole(StrEnum):
    RECORDING = "recording"
    REPLAY = "replay"


class ManualMeasurementRole(StrEnum):
    BASELINE = "baseline"
    OBSERVED = "observed"


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class AcceptanceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocker"


class VersionedNodeInput(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    payload: dict[str, JsonValue]


class VersionedNodeContext(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    value: NodeContext


class VersionedNodePolicy(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    value: NodePolicy


class PilotBudget(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_request_bytes: int = Field(gt=0)
    max_latency_ms: int = Field(gt=0)
    max_api_cost_usd: float = Field(ge=0.0)
    max_project_api_cost_usd: float = Field(ge=0.0)
    max_tool_call_proposals: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def finite_costs(self) -> PilotBudget:
        if not math.isfinite(self.max_api_cost_usd):
            raise ValueError("max_api_cost_usd must be finite")
        if not math.isfinite(self.max_project_api_cost_usd):
            raise ValueError("max_project_api_cost_usd must be finite")
        return self


class ManualInterventionMeasurement(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    role: ManualMeasurementRole
    count: int = Field(ge=0)
    source: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    handleable_without_model: bool | None = None


_INPUT_MODELS = {
    PilotNodeType.REVIEW_SEMANTIC: ReviewSemanticInput,
    PilotNodeType.INTERPRETATION_THREAT: InterpretationThreatInput,
    PilotNodeType.AMBIGUOUS_ACTION: AmbiguousActionInput,
}


class PilotCase(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    case_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    condition: PilotCondition
    node_type: PilotNodeType
    seed: int = Field(ge=0)
    request_id: str = Field(min_length=1)
    backend_key: str | None = None
    expected_backend_id: str = Field(min_length=1)
    expected_model_id: str = Field(min_length=1)
    budget: PilotBudget
    node_input: VersionedNodeInput
    context: VersionedNodeContext
    policy: VersionedNodePolicy
    expected_applicability: ExpectedApplicability
    allowed_outcomes: tuple[PilotOutcome, ...] = Field(min_length=1)
    gate_probe: bool = False
    replay_pair_id: str | None = None
    replay_role: ReplayEvidenceRole | None = None
    manual_intervention: ManualInterventionMeasurement | None = None

    @model_validator(mode="after")
    def validate_case_contract(self) -> PilotCase:
        if len(set(self.allowed_outcomes)) != len(self.allowed_outcomes):
            raise ValueError("allowed_outcomes must not contain duplicates")

        policy = self.policy.value
        budget_fields = (
            "max_input_tokens",
            "max_output_tokens",
            "max_request_bytes",
            "max_latency_ms",
            "max_api_cost_usd",
        )
        for field_name in budget_fields:
            if getattr(self.budget, field_name) != getattr(policy, field_name):
                raise ValueError(f"budget.{field_name} must match policy.{field_name}")
        if self.budget.max_project_api_cost_usd != policy.max_api_cost_usd:
            raise ValueError(
                "budget.max_project_api_cost_usd must match the NodePolicy cumulative limit"
            )
        if policy.expected_backend != self.expected_backend_id:
            raise ValueError("expected_backend_id must match the versioned NodePolicy")
        if policy.expected_model != self.expected_model_id:
            raise ValueError("expected_model_id must match the versioned NodePolicy")

        if self.condition is PilotCondition.DETERMINISTIC_ONLY:
            if self.backend_key is not None:
                raise ValueError("deterministic_only cases cannot bind a backend")
            if policy.enabled:
                raise ValueError("deterministic_only cases require a disabled NodePolicy")
            if self.allowed_outcomes != (PilotOutcome.BASELINE,):
                raise ValueError("deterministic_only cases allow only the baseline outcome")
            if self.manual_intervention is None:
                raise ValueError("deterministic_only cases require a manual baseline")
            if self.manual_intervention.role is not ManualMeasurementRole.BASELINE:
                raise ValueError("deterministic_only measurements must be baselines")
            if self.manual_intervention.handleable_without_model is None:
                raise ValueError(
                    "deterministic_only baselines must record handleable_without_model"
                )
        else:
            if not self.backend_key:
                raise ValueError("model-node cases require backend_key")
            if not policy.enabled:
                raise ValueError("model-node cases require an enabled NodePolicy")
            if self.node_type.value not in policy.allowed_node_names:
                raise ValueError("NodePolicy does not allow the case node_type")
            if PilotOutcome.BASELINE in self.allowed_outcomes:
                raise ValueError("model-node cases cannot allow a baseline outcome")

        if self.condition is PilotCondition.LIVE_STRUCTURED_NODE:
            if PilotOutcome.PLANNED not in self.allowed_outcomes:
                raise ValueError("live_structured_node must allow a planned outcome")
        elif PilotOutcome.PLANNED in self.allowed_outcomes:
            raise ValueError("only live_structured_node can allow a planned outcome")

        if self.condition is PilotCondition.REPLAY_NODE:
            if self.replay_role is not ReplayEvidenceRole.REPLAY or not self.replay_pair_id:
                raise ValueError("replay_node requires a replay pair and replay role")
        elif self.replay_role is ReplayEvidenceRole.REPLAY:
            raise ValueError("only replay_node can use the replay evidence role")

        if self.replay_role is ReplayEvidenceRole.RECORDING:
            if self.condition is not PilotCondition.SCRIPTED_NODE or not self.replay_pair_id:
                raise ValueError("recording evidence must be a paired scripted_node case")
        if (self.replay_pair_id is None) != (self.replay_role is None):
            raise ValueError("replay_pair_id and replay_role must be set together")

        if self.expected_applicability is ExpectedApplicability.NOT_APPLICABLE:
            if self.node_type is not PilotNodeType.AMBIGUOUS_ACTION:
                raise ValueError("only ambiguous-action has a not-applicable pilot case")
            if self.allowed_outcomes != (PilotOutcome.NOT_APPLICABLE,):
                raise ValueError("not-applicable cases allow only not_applicable")

        input_model = _INPUT_MODELS[self.node_type]
        try:
            payload_json = _canonical_json(self.node_input.payload)
            validated_input = input_model.model_validate_json(payload_json, strict=True)
        except Exception as exc:
            raise ValueError(f"invalid strict {input_model.__name__} payload: {exc}") from exc

        if isinstance(validated_input, AmbiguousActionInput):
            is_applicable = validated_input.score_margin <= policy.ambiguity_margin_max
            expected = self.expected_applicability is ExpectedApplicability.APPLICABLE
            if is_applicable != expected:
                raise ValueError(
                    "expected_applicability conflicts with score_margin and policy ambiguity_margin"
                )
        return self

    def validated_node_input(
        self,
    ) -> ReviewSemanticInput | InterpretationThreatInput | AmbiguousActionInput:
        """Materialize the strict node-specific input declared by this case."""

        return _INPUT_MODELS[self.node_type].model_validate_json(
            _canonical_json(self.node_input.payload),
            strict=True,
        )


class PilotAcceptanceThresholds(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    minimum_schema_valid_rate: float = Field(ge=0.0, le=1.0)
    maximum_gate_bypass_count: int = Field(ge=0)
    minimum_exact_replay_coverage: float = Field(ge=0.0, le=1.0)
    minimum_manual_intervention_reduction: float = Field(ge=0.0, le=1.0)
    unsupported_claim_reference_action_baseline: int | None = Field(default=None, ge=0)
    maximum_unsupported_claim_reference_action_increase: int = Field(ge=0)
    maximum_unbounded_tool_call_count: int = Field(ge=0)
    maximum_additional_api_cost_per_project_usd: float = Field(ge=0.0)
    independent_outcome_review_required: Literal[True] = True

    @model_validator(mode="after")
    def fixed_pilot_minima(self) -> PilotAcceptanceThresholds:
        finite = (
            self.minimum_schema_valid_rate,
            self.minimum_exact_replay_coverage,
            self.minimum_manual_intervention_reduction,
            self.maximum_additional_api_cost_per_project_usd,
        )
        if not all(math.isfinite(value) for value in finite):
            raise ValueError("acceptance thresholds must be finite")
        if self.minimum_schema_valid_rate < 0.98:
            raise ValueError("pilot schema-valid threshold cannot be below 0.98")
        if self.maximum_gate_bypass_count != 0:
            raise ValueError("pilot gate-bypass threshold must be zero")
        if self.minimum_exact_replay_coverage != 1.0:
            raise ValueError("pilot exact-replay threshold must be 1.0")
        if self.minimum_manual_intervention_reduction < 0.30:
            raise ValueError("pilot manual-intervention threshold cannot be below 0.30")
        if self.maximum_unbounded_tool_call_count != 0:
            raise ValueError("pilot unbounded-tool-call threshold must be zero")
        if self.maximum_additional_api_cost_per_project_usd > 0.15:
            raise ValueError("pilot API-cost threshold cannot exceed USD 0.15/project")
        return self


class PilotProtocol(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    protocol_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    created_at: datetime
    cases: tuple[PilotCase, ...] = Field(min_length=1)
    acceptance_thresholds: PilotAcceptanceThresholds
    self_dogfooding_only: Literal[True] = True
    retrieval_eligible: Literal[False] = False
    effectiveness_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_protocol_scope(self) -> PilotProtocol:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if any(
            case.budget.max_project_api_cost_usd
            > self.acceptance_thresholds.maximum_additional_api_cost_per_project_usd
            for case in self.cases
        ):
            raise ValueError("case project budget exceeds the protocol acceptance threshold")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique")

        node_types = {case.node_type for case in self.cases}
        if node_types != set(PilotNodeType):
            raise ValueError("pilot protocol must cover all three bounded node types")
        conditions = {case.condition for case in self.cases}
        if conditions != set(PilotCondition):
            raise ValueError("pilot protocol must declare all four pilot conditions")

        ambiguous_expectations = {
            case.expected_applicability
            for case in self.cases
            if case.node_type is PilotNodeType.AMBIGUOUS_ACTION
        }
        if ambiguous_expectations != set(ExpectedApplicability):
            raise ValueError("ambiguous-action requires applicable and clear-margin cases")

        pairs: dict[str, set[ReplayEvidenceRole]] = {}
        for case in self.cases:
            if case.replay_pair_id and case.replay_role:
                pairs.setdefault(case.replay_pair_id, set()).add(case.replay_role)
        if not pairs:
            raise ValueError("pilot protocol requires exact recording/replay evidence")
        for pair_id, roles in pairs.items():
            if roles != set(ReplayEvidenceRole):
                raise ValueError(f"replay pair {pair_id!r} is incomplete")
            pair_cases = [case for case in self.cases if case.replay_pair_id == pair_id]
            if len(pair_cases) != 2:
                raise ValueError(f"replay pair {pair_id!r} must contain exactly two cases")
            recording = next(
                case for case in pair_cases if case.replay_role is ReplayEvidenceRole.RECORDING
            )
            replay = next(
                case for case in pair_cases if case.replay_role is ReplayEvidenceRole.REPLAY
            )
            if self.cases.index(recording) > self.cases.index(replay):
                raise ValueError(f"replay pair {pair_id!r} must record before replaying")
            comparable_fields = (
                "node_type",
                "seed",
                "request_id",
                "expected_backend_id",
                "expected_model_id",
                "budget",
                "node_input",
                "context",
                "policy",
                "expected_applicability",
            )
            if any(getattr(recording, name) != getattr(replay, name) for name in comparable_fields):
                raise ValueError(f"replay pair {pair_id!r} does not declare identical requests")
        return self

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self)


class IndependentOutcomeReview(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    review_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    independent: bool
    decision: ReviewDecision
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def aware_timestamp(self) -> IndependentOutcomeReview:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return self


class PilotCaseResult(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    case_id: str
    condition: PilotCondition
    node_type: PilotNodeType
    outcome: PilotOutcome
    expected_outcome: bool
    invoked: bool
    schema_valid: bool | None
    backend_id: str | None = None
    model_id: str | None = None
    request_fingerprint: str | None = None
    response_fingerprint: str | None = None
    result_fingerprint: str | None = None
    baseline_fingerprint: str | None = None
    evidence_fingerprint: str
    replay_pair_id: str | None = None
    replay_role: ReplayEvidenceRole | None = None
    recorded: bool = False
    cached: bool = False
    rejection_reasons: tuple[str, ...] = ()
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    tool_call_proposal_count: int = Field(default=0, ge=0)
    unbounded_tool_call_count: int = Field(default=0, ge=0)
    unsupported_claim_reference_action_count: int = Field(default=0, ge=0)
    manual_intervention: ManualInterventionMeasurement | None = None

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> PilotCaseResult:
        if self.cost_usd is not None and not math.isfinite(self.cost_usd):
            raise ValueError("cost_usd must be finite")
        if not math.isfinite(self.latency_ms):
            raise ValueError("latency_ms must be finite")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        if self.outcome is PilotOutcome.BASELINE:
            if not self.baseline_fingerprint:
                raise ValueError("baseline result requires baseline_fingerprint")
            if self.request_fingerprint or self.result_fingerprint:
                raise ValueError("baseline result cannot carry model fingerprints")
        if self.invoked and not self.request_fingerprint:
            raise ValueError("invoked result requires request_fingerprint")
        return self


class PilotStatistics(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    case_count: int = Field(ge=0)
    planned_count: int = Field(ge=0)
    invoked_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    successful_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    schema_invalid_count: int = Field(ge=0)
    gate_bypass_count: int = Field(ge=0)
    unsupported_claim_reference_action_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    cost_telemetry_complete: bool
    additional_api_cost_by_project_usd: dict[str, float]
    latency_ms: float = Field(ge=0.0)
    manual_intervention_baseline: int | None = Field(default=None, ge=0)
    manual_intervention_observed: int | None = Field(default=None, ge=0)
    manual_intervention_reduction: float | None = None
    exact_replay_pair_count: int = Field(ge=0)
    exact_replay_covered_count: int = Field(ge=0)
    exact_replay_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    unbounded_tool_call_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_statistics(self) -> PilotStatistics:
        if self.successful_count != self.accepted_count:
            raise ValueError("only accepted outcomes count as successful")
        if self.planned_count > self.case_count:
            raise ValueError("planned_count cannot exceed case_count")
        if self.schema_valid_count + self.schema_invalid_count > self.invoked_count:
            raise ValueError("schema observations cannot exceed invoked_count")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        if self.cost_usd is not None and not math.isfinite(self.cost_usd):
            raise ValueError("cost_usd must be finite")
        if any(
            not math.isfinite(value) for value in self.additional_api_cost_by_project_usd.values()
        ):
            raise ValueError("project costs must be finite")
        if any(value < 0 for value in self.additional_api_cost_by_project_usd.values()):
            raise ValueError("project costs cannot be negative")
        if not math.isfinite(self.latency_ms):
            raise ValueError("latency_ms must be finite")
        return self


class AcceptanceMetric(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    metric_id: str = Field(min_length=1)
    status: AcceptanceStatus
    observed: JsonValue | None
    threshold: JsonValue | None
    detail: str = Field(min_length=1)


class PilotAcceptance(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    overall_status: AcceptanceStatus
    eligible: bool
    metrics: tuple[AcceptanceMetric, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_overall_status(self) -> PilotAcceptance:
        statuses = {metric.status for metric in self.metrics}
        expected = (
            AcceptanceStatus.BLOCKED
            if AcceptanceStatus.BLOCKED in statuses
            else AcceptanceStatus.FAIL
            if AcceptanceStatus.FAIL in statuses
            else AcceptanceStatus.PASS
        )
        if self.overall_status is not expected:
            raise ValueError("overall_status does not match metric statuses")
        if self.eligible != (expected is AcceptanceStatus.PASS):
            raise ValueError("eligible is true only when every acceptance metric passes")
        return self


class PilotReport(PilotModel):
    schema_version: Literal["1.0"] = PILOT_SCHEMA_VERSION
    report_id: str = Field(min_length=1)
    generated_at: datetime
    protocol_id: str
    protocol_version: str
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    self_dogfooding_only: Literal[True] = True
    retrieval_eligible: Literal[False] = False
    effectiveness_claim: Literal[False] = False
    case_results: tuple[PilotCaseResult, ...]
    statistics: PilotStatistics
    independent_outcome_review: IndependentOutcomeReview | None = None
    acceptance: PilotAcceptance
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> PilotReport:
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        digest = unsigned.expected_sha256()
        return cls.model_validate({**payload, "report_sha256": digest})

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"report_sha256"})

    def expected_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())

    def verify_sha256(self) -> bool:
        return self.report_sha256 == self.expected_sha256()

    @model_validator(mode="after")
    def verify_report(self) -> PilotReport:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if not self.verify_sha256():
            raise ValueError("report_sha256 does not match canonical report content")
        return self
