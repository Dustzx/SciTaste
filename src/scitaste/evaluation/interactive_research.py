"""Bounded execution loop for interactive, training-free research workloads."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.backends.base import Usage
from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_OBSERVATION_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_RECEIPT_BYTES = 64 * 1_048_576


class InteractiveResearchLimits(BaseModel):
    """One fixed resource envelope shared by matched experimental arms."""

    model_config = _CONFIG

    max_turns: int = Field(ge=1, le=50)
    max_experiments: int = Field(ge=1, le=1_000)
    max_experiments_per_turn: int = Field(ge=1, le=100)
    max_code_calls: int = Field(default=0, ge=0, le=100)
    max_observation_bytes: int = Field(default=256_000, ge=1, le=8_000_000)
    max_total_tokens: int = Field(ge=1)
    max_api_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    require_cost_telemetry: bool = True
    enforce_guidance_compliance: bool = True

    @model_validator(mode="after")
    def per_turn_work_fits_total(self) -> InteractiveResearchLimits:
        if self.max_experiments_per_turn > self.max_experiments:
            raise ValueError("per-turn experiment limit cannot exceed total experiment limit")
        return self

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class InteractiveExperimentRequest(BaseModel):
    model_config = _CONFIG

    parameters: dict[str, JsonValue] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def request_is_bounded_json(self) -> InteractiveExperimentRequest:
        encoded = json.dumps(
            self.parameters,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > 32_768:
            raise ValueError("interactive experiment request exceeds byte limit")
        return self


class InteractiveAgentProposal(BaseModel):
    """Exactly one executable action proposed by the research model."""

    model_config = _CONFIG

    action: Literal["run_experiments", "run_code", "submit_hypothesis"]
    experiments: tuple[InteractiveExperimentRequest, ...] = Field(default=(), max_length=100)
    code: str | None = Field(default=None, max_length=32_000)
    submission: str | None = Field(default=None, max_length=64_000)
    rationale: str = Field(min_length=1, max_length=8_000)
    evidence_status: Literal[
        "unassessed",
        "no-candidate",
        "candidate-untested",
        "candidate-supported",
        "candidate-conflicted",
    ] = "unassessed"
    evidence_confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    next_experiment_value: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def action_payload_is_exclusive(self) -> InteractiveAgentProposal:
        if self.action == "run_experiments":
            if not self.experiments or self.code is not None or self.submission is not None:
                raise ValueError("run_experiments requires only non-empty experiments")
        elif self.action == "run_code":
            if not self.code or self.experiments or self.submission is not None:
                raise ValueError("run_code requires only non-empty code")
        elif not self.submission or self.experiments or self.code is not None:
            raise ValueError("submit_hypothesis requires only a non-empty submission")
        return self


class InteractiveGuidance(BaseModel):
    """High-level action selected by the matched lifecycle controller."""

    model_config = _CONFIG

    action_id: str
    action_type: str
    instruction: str = Field(min_length=1, max_length=2_000)
    decision_sha256: str = Field(pattern=_SHA256)
    allowed_agent_actions: (
        tuple[Literal["run_experiments", "run_code", "submit_hypothesis"], ...] | None
    ) = Field(
        default=None,
        min_length=1,
        max_length=3,
        exclude_if=lambda value: value is None,
    )


class InteractiveGuidanceEnvelope(BaseModel):
    """Separate agent-visible guidance from condition-specific audit evidence."""

    model_config = _CONFIG

    guidance: InteractiveGuidance
    audit: dict[str, JsonValue]
    audit_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def audit_is_closed(self) -> InteractiveGuidanceEnvelope:
        expected = content_sha256(self.audit)
        if self.audit_sha256 != expected:
            raise ValueError("interactive guidance audit hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        guidance: InteractiveGuidance,
        audit: dict[str, JsonValue],
    ) -> InteractiveGuidanceEnvelope:
        return cls(
            guidance=guidance,
            audit=audit,
            audit_sha256=content_sha256(audit),
        )


class InteractiveResearchContext(BaseModel):
    """Model-visible task, evidence history, and remaining budget."""

    model_config = _CONFIG

    project_id: str
    run_id: str
    condition_id: str
    task_id: str
    task_sha256: str = Field(pattern=_SHA256)
    environment_sha256: str = Field(pattern=_SHA256)
    toolbox_sha256: str = Field(pattern=_SHA256)
    resource_envelope_sha256: str = Field(pattern=_SHA256)
    research_agent_sha256: str = Field(pattern=_SHA256)
    task_prompt: str = Field(min_length=1, max_length=128_000)
    turn: int = Field(ge=1)
    remaining_turns: int = Field(ge=1)
    remaining_experiments: int = Field(ge=0)
    max_experiments_per_turn: int = Field(ge=1)
    remaining_code_calls: int = Field(ge=0)
    history: tuple[dict[str, JsonValue], ...] = Field(default=(), max_length=50)


class InteractiveAgentDecision(BaseModel):
    """One model decision with provider identity and measured resource use."""

    model_config = _CONFIG

    proposal: InteractiveAgentProposal
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    request_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    usage: Usage
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    normalization_repairs: tuple[str, ...] = Field(
        default=(),
        max_length=8,
        exclude_if=lambda value: not value,
    )
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def decision_hash_is_valid(self) -> InteractiveAgentDecision:
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if self.decision_sha256 != content_sha256(payload):
            if not _proposal_uses_legacy_evidence_schema(self.proposal):
                raise ValueError("interactive agent decision hash mismatch")
            _remove_evidence_state(payload["proposal"])
            if self.decision_sha256 != content_sha256(payload):
                raise ValueError("interactive agent decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> InteractiveAgentDecision:
        payload = dict(values)
        payload.pop("decision_sha256", None)
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


class InteractiveObjectiveScore(BaseModel):
    """Scorer-owned result returned only after a final hypothesis is submitted."""

    model_config = _CONFIG

    primary_metric: str
    primary_value: float = Field(allow_inf_nan=False)
    metric_direction: Literal["higher", "lower"]
    metrics: dict[str, float]
    scorer_provider: str = Field(min_length=1)
    scorer_model: str = Field(min_length=1)
    scorer_sha256: str = Field(pattern=_SHA256)
    usage: Usage
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    score_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def score_is_closed(self) -> InteractiveObjectiveScore:
        if self.primary_metric not in self.metrics:
            raise ValueError("primary interactive metric is absent from metrics")
        if self.metrics[self.primary_metric] != self.primary_value:
            raise ValueError("primary interactive metric value differs")
        if any(
            value != value or value in {float("inf"), float("-inf")}
            for value in self.metrics.values()
        ):
            raise ValueError("interactive objective metrics must be finite")
        expected = content_sha256(self.model_dump(mode="json", exclude={"score_sha256"}))
        if self.score_sha256 != expected:
            raise ValueError("interactive objective score hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> InteractiveObjectiveScore:
        payload = dict(values)
        payload.pop("score_sha256", None)
        unsigned = cls.model_construct(score_sha256="0" * 64, **payload)
        return cls(
            **payload,
            score_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"score_sha256"})),
        )


class InteractiveTurnRecord(BaseModel):
    # Tool stdout/stderr are evidence: leading and trailing whitespace are part
    # of the observed bytes and must not change before their hash is checked.
    model_config = _OBSERVATION_CONFIG

    turn: int = Field(ge=1)
    guidance: InteractiveGuidanceEnvelope
    decision: InteractiveAgentDecision
    observation: JsonValue | None = None
    observation_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def observation_hash_is_consistent(self) -> InteractiveTurnRecord:
        if (self.observation is None) != (self.observation_sha256 is None):
            raise ValueError("interactive observation and hash must be paired")
        if self.observation is not None and self.observation_sha256 != content_sha256(
            self.observation
        ):
            raise ValueError("interactive observation hash mismatch")
        return self


class InteractiveResearchRunReceipt(BaseModel):
    """Terminal, self-hashed evidence for one training-free research trajectory."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    condition_id: str
    task_id: str
    environment_sha256: str | None = Field(default=None, pattern=_SHA256)
    prefix_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
        exclude_if=lambda value: value is None,
    )
    prefix_turn_count: int = Field(
        default=0,
        ge=0,
        le=49,
        exclude_if=lambda value: value == 0,
    )
    status: Literal[
        "completed",
        "turn_budget_exhausted",
        "experiment_budget_exhausted",
        "code_budget_exhausted",
        "token_budget_exhausted",
        "cost_budget_exhausted",
        "agent_failure",
        "agent_noncompliance",
        "controller_failure",
        "tool_failure",
        "scorer_failure",
    ]
    turns: tuple[InteractiveTurnRecord, ...]
    submission: str | None = None
    objective_score: InteractiveObjectiveScore | None = None
    experiment_count: int = Field(ge=0)
    code_call_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    api_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    terminal_error: str | None = Field(default=None, max_length=4_000)
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def terminal_state_is_closed(self) -> InteractiveResearchRunReceipt:
        validate_project_id(self.project_id)
        validate_entry_id(self.run_id, field_name="interactive run_id")
        validate_entry_id(self.condition_id, field_name="interactive condition_id")
        validate_entry_id(self.task_id, field_name="interactive task_id")
        if (self.prefix_sha256 is None) != (self.prefix_turn_count == 0):
            raise ValueError("interactive prefix hash and turn count must be paired")
        if self.prefix_turn_count > len(self.turns):
            raise ValueError("interactive prefix turn count exceeds receipt turns")
        if self.status == "completed":
            if self.submission is None or self.objective_score is None or self.terminal_error:
                raise ValueError(
                    "completed interactive run requires submission and objective score"
                )
        elif self.objective_score is not None and self.status not in {
            "token_budget_exhausted",
            "cost_budget_exhausted",
        }:
            raise ValueError("only a post-score budget failure may retain an objective score")
        if self.objective_score is not None and self.submission is None:
            raise ValueError("an interactive objective score requires a submission")
        excluded = {"receipt_sha256"}
        # Receipts produced before environment commitments were introduced remain
        # readable; every new loop execution supplies the commitment.
        if self.environment_sha256 is None:
            excluded.add("environment_sha256")
        payload = self.model_dump(mode="json", exclude=excluded)
        if self.receipt_sha256 != content_sha256(payload):
            legacy_payload = self.model_dump(mode="json", exclude=excluded)
            legacy_found = False
            for record, record_payload in zip(self.turns, legacy_payload["turns"], strict=True):
                proposal = record.decision.proposal
                if _proposal_uses_legacy_evidence_schema(proposal):
                    _remove_evidence_state(record_payload["decision"]["proposal"])
                    legacy_found = True
            if not legacy_found or self.receipt_sha256 != content_sha256(legacy_payload):
                raise ValueError("interactive run receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> InteractiveResearchRunReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class InteractiveResearchPrefix(BaseModel):
    """Replay-safe observed state shared by counterfactual action branches.

    Version 1 deliberately accepts only experiment observations that can be
    replayed from a fresh deterministic toolbox. Code execution may mutate an
    external workspace and therefore cannot be reconstructed from a receipt alone.
    """

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    source_run_id: str
    source_condition_id: str
    source_receipt_sha256: str = Field(pattern=_SHA256)
    task_id: str
    task_sha256: str = Field(pattern=_SHA256)
    environment_sha256: str = Field(pattern=_SHA256)
    toolbox_sha256: str = Field(pattern=_SHA256)
    resource_envelope_sha256: str = Field(pattern=_SHA256)
    research_agent_sha256: str = Field(pattern=_SHA256)
    replay_mode: Literal["deterministic-tool-replay"] = "deterministic-tool-replay"
    turns: tuple[InteractiveTurnRecord, ...] = Field(min_length=1, max_length=49)
    experiment_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    api_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    prefix_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def prefix_is_closed(self) -> InteractiveResearchPrefix:
        validate_project_id(self.project_id)
        validate_entry_id(self.source_run_id, field_name="interactive prefix source_run_id")
        validate_entry_id(
            self.source_condition_id,
            field_name="interactive prefix source_condition_id",
        )
        validate_entry_id(self.task_id, field_name="interactive prefix task_id")
        expected_turns = tuple(range(1, len(self.turns) + 1))
        if tuple(item.turn for item in self.turns) != expected_turns:
            raise ValueError("interactive prefix turns must be contiguous from turn one")
        if any(
            item.observation is None or item.decision.proposal.action != "run_experiments"
            for item in self.turns
        ):
            raise ValueError("interactive prefix v1 requires executed experiment observations only")
        experiments = sum(len(item.decision.proposal.experiments) for item in self.turns)
        if experiments != self.experiment_count:
            raise ValueError("interactive prefix experiment count mismatch")
        if sum(item.decision.usage.input_tokens for item in self.turns) != self.input_tokens:
            raise ValueError("interactive prefix input-token count mismatch")
        if sum(item.decision.usage.output_tokens for item in self.turns) != self.output_tokens:
            raise ValueError("interactive prefix output-token count mismatch")
        costs = tuple(item.decision.usage.cost_usd for item in self.turns)
        expected_cost = None if any(item is None for item in costs) else math.fsum(costs)  # type: ignore[arg-type]
        if self.api_cost_usd != expected_cost:
            raise ValueError("interactive prefix API cost mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"prefix_sha256"}))
        if self.prefix_sha256 != expected:
            raise ValueError("interactive research prefix hash mismatch")
        return self

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def history(self) -> tuple[dict[str, JsonValue], ...]:
        return tuple(
            {
                "turn": item.turn,
                "high_level_action": item.guidance.guidance.action_type,
                "model_action": item.decision.proposal.model_dump(mode="json"),
                "observation": item.observation,
            }
            for item in self.turns
        )

    @classmethod
    def from_receipt(
        cls,
        receipt: InteractiveResearchRunReceipt,
        *,
        turn_count: int,
        task_sha256: str,
        toolbox_sha256: str,
        resource_envelope_sha256: str,
        research_agent_sha256: str,
    ) -> InteractiveResearchPrefix:
        if receipt.environment_sha256 is None:
            raise ValueError("interactive prefix requires an environment-bound source receipt")
        if not 1 <= turn_count < len(receipt.turns):
            raise ValueError(
                "interactive prefix must retain at least one observed turn and one later decision"
            )
        turns = receipt.turns[:turn_count]
        experiments = sum(len(item.decision.proposal.experiments) for item in turns)
        input_tokens = sum(item.decision.usage.input_tokens for item in turns)
        output_tokens = sum(item.decision.usage.output_tokens for item in turns)
        costs = tuple(item.decision.usage.cost_usd for item in turns)
        api_cost = None if any(item is None for item in costs) else math.fsum(costs)  # type: ignore[arg-type]
        payload = {
            "schema_version": "1.0",
            "project_id": receipt.project_id,
            "source_run_id": receipt.run_id,
            "source_condition_id": receipt.condition_id,
            "source_receipt_sha256": receipt.receipt_sha256,
            "task_id": receipt.task_id,
            "task_sha256": task_sha256,
            "environment_sha256": receipt.environment_sha256,
            "toolbox_sha256": toolbox_sha256,
            "resource_envelope_sha256": resource_envelope_sha256,
            "research_agent_sha256": research_agent_sha256,
            "replay_mode": "deterministic-tool-replay",
            "turns": turns,
            "experiment_count": experiments,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "api_cost_usd": api_cost,
        }
        unsigned = cls.model_construct(prefix_sha256="0" * 64, **payload)
        return cls(
            **payload,
            prefix_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"prefix_sha256"})
            ),
        )


class InteractivePairedResult(BaseModel):
    """Task-level intention-to-treat contrast for one Native/Base pair."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    task_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    native_receipt_sha256: str = Field(pattern=_SHA256)
    base_receipt_sha256: str = Field(pattern=_SHA256)
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    native_status: str
    base_status: str
    native_value: float = Field(allow_inf_nan=False)
    base_value: float = Field(allow_inf_nan=False)
    native_value_observed: bool
    base_value_observed: bool
    native_minus_base: float = Field(allow_inf_nan=False)
    treatment_effect: float = Field(allow_inf_nan=False)
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> InteractivePairedResult:
        validate_entry_id(self.task_id, field_name="interactive paired task_id")
        if self.native_minus_base != self.native_value - self.base_value:
            raise ValueError("interactive paired raw difference mismatch")
        expected_effect = (
            self.native_minus_base if self.metric_direction == "higher" else -self.native_minus_base
        )
        if self.treatment_effect != expected_effect:
            raise ValueError("interactive paired treatment effect mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("interactive paired result hash mismatch")
        return self

    @classmethod
    def from_receipts(
        cls,
        native: InteractiveResearchRunReceipt,
        base: InteractiveResearchRunReceipt,
        *,
        protocol_sha256: str,
        primary_metric: str,
        metric_direction: Literal["higher", "lower"],
        failure_value: float,
    ) -> InteractivePairedResult:
        if native.task_id != base.task_id:
            raise ValueError("interactive paired receipts name different tasks")
        if native.environment_sha256 != base.environment_sha256:
            raise ValueError("interactive paired receipts use different hidden environments")
        if native.condition_id != "full-scitaste-learned-policy":
            raise ValueError("interactive native receipt has the wrong condition")
        if base.condition_id != "native-base-without-learned-taste":
            raise ValueError("interactive base receipt has the wrong condition")
        for label, receipt in (("native", native), ("base", base)):
            observed_protocol = _receipt_protocol_sha256(receipt)
            if observed_protocol != protocol_sha256:
                raise ValueError(f"interactive {label} receipt uses another protocol")
        native_value, native_observed = _intention_to_treat_value(
            native,
            primary_metric=primary_metric,
            failure_value=failure_value,
        )
        base_value, base_observed = _intention_to_treat_value(
            base,
            primary_metric=primary_metric,
            failure_value=failure_value,
        )
        difference = native_value - base_value
        payload = {
            "schema_version": "1.0",
            "task_id": native.task_id,
            "protocol_sha256": protocol_sha256,
            "native_receipt_sha256": native.receipt_sha256,
            "base_receipt_sha256": base.receipt_sha256,
            "primary_metric": primary_metric,
            "metric_direction": metric_direction,
            "native_status": native.status,
            "base_status": base.status,
            "native_value": native_value,
            "base_value": base_value,
            "native_value_observed": native_observed,
            "base_value_observed": base_observed,
            "native_minus_base": difference,
            "treatment_effect": difference if metric_direction == "higher" else -difference,
        }
        return cls(**payload, result_sha256=content_sha256(payload))


@runtime_checkable
class InteractiveGuidanceProvider(Protocol):
    def guide(self, context: InteractiveResearchContext) -> InteractiveGuidanceEnvelope: ...


@runtime_checkable
class InteractiveSubmissionAdjudicator(Protocol):
    """Optionally gate an evidence-backed stop request before scorer access."""

    def adjudicate_submission(
        self,
        context: InteractiveResearchContext,
        initial_guidance: InteractiveGuidanceEnvelope,
        decision: InteractiveAgentDecision,
    ) -> InteractiveGuidanceEnvelope: ...


@runtime_checkable
class InteractiveResearchAgent(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def decide(
        self,
        context: InteractiveResearchContext,
        guidance: InteractiveGuidance,
    ) -> InteractiveAgentDecision: ...


@runtime_checkable
class InteractiveResearchToolbox(Protocol):
    @property
    def task_id(self) -> str: ...

    @property
    def task_prompt(self) -> str: ...

    @property
    def task_sha256(self) -> str: ...

    @property
    def fingerprint(self) -> str: ...

    @property
    def environment_sha256(self) -> str: ...

    def run_experiments(self, requests: tuple[InteractiveExperimentRequest, ...]) -> JsonValue: ...

    def run_code(self, code: str) -> JsonValue: ...

    def score(self, submission: str) -> InteractiveObjectiveScore: ...


class StructuredInteractiveResearchAgent:
    """Use any bounded structured backend to drive the interactive loop."""

    def __init__(
        self,
        backend: StructuredModelBackend,
        *,
        policy_id: str,
        prompt_version: str,
        seed: int,
        backend_configuration_sha256: str,
    ) -> None:
        self.backend = backend
        self.policy_id = policy_id
        self.prompt_version = prompt_version
        self.seed = seed
        if len(backend_configuration_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in backend_configuration_sha256
        ):
            raise ValueError("interactive backend configuration SHA-256 is invalid")
        self.backend_configuration_sha256 = backend_configuration_sha256

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "implementation": "structured-interactive-research-agent-v1",
                "provider": self.backend.name,
                "model": self.backend.model,
                "backend_configuration_sha256": self.backend_configuration_sha256,
                "policy_id": self.policy_id,
                "prompt_version": self.prompt_version,
                "seed": self.seed,
            }
        )

    def decide(
        self,
        context: InteractiveResearchContext,
        guidance: InteractiveGuidance,
    ) -> InteractiveAgentDecision:
        policy_fingerprint = content_sha256(
            {
                "policy_id": self.policy_id,
                "prompt_version": self.prompt_version,
                "action_schema": "interactive-research-action-v2-evidence-state",
            }
        )
        allowed_actions = guidance.allowed_agent_actions or (
            "run_experiments",
            "run_code",
            "submit_hypothesis",
        )
        action_constraint = (
            " The controller has constrained this turn to exactly these executable actions: "
            f"{', '.join(allowed_actions)}. Do not emit any other action."
            if guidance.allowed_agent_actions is not None
            else ""
        )
        request = StructuredModelRequest(
            request_id=f"{context.run_id}-turn-{context.turn:03d}",
            node_name="interactive-research-action",
            stage="EXPERIMENTATION",
            state_snapshot_id=content_sha256(context),
            expected_backend=self.backend.name,
            expected_model=self.backend.model,
            policy_id=self.policy_id,
            policy_fingerprint=policy_fingerprint,
            system_instruction=(
                "Act as a scientific researcher in an interactive hidden-law environment. "
                "Use observations rather than guessing. The high-level guidance is a strategy "
                "decision, not evidence. Return exactly one JSON action and never request more "
                "experiments than the stated per-turn limit. Never claim access to the hidden "
                "law or scorer. Report evidence_status, evidence_confidence, and the expected "
                "information value of one more experiment from the visible history only. If a "
                "candidate is strongly supported and another experiment has negligible value, "
                "you may request an evidence-backed stop by submitting the hypothesis; the "
                "controller will independently approve or reject that request before scoring."
                + action_constraint
            ),
            input_payload={
                "task_prompt": context.task_prompt,
                "history": list(context.history),
                "remaining": {
                    "turns": context.remaining_turns,
                    "experiments": context.remaining_experiments,
                    "experiments_per_turn": context.max_experiments_per_turn,
                    "code_calls": context.remaining_code_calls,
                },
                "high_level_guidance": guidance.model_dump(mode="json"),
            },
            output_schema={
                "type": "object",
                "required": [
                    "action",
                    "experiments",
                    "code",
                    "submission",
                    "rationale",
                    "evidence_status",
                    "evidence_confidence",
                    "next_experiment_value",
                ],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(allowed_actions),
                    },
                    "experiments": {
                        "type": "array",
                        "maxItems": min(
                            context.max_experiments_per_turn,
                            context.remaining_experiments,
                        ),
                        "items": {
                            "type": "object",
                            "required": ["parameters"],
                            "properties": {"parameters": {"type": "object"}},
                            "additionalProperties": False,
                        },
                    },
                    "code": {"type": ["string", "null"]},
                    "submission": {"type": ["string", "null"]},
                    "rationale": {"type": "string"},
                    "evidence_status": {
                        "type": "string",
                        "enum": [
                            "unassessed",
                            "no-candidate",
                            "candidate-untested",
                            "candidate-supported",
                            "candidate-conflicted",
                        ],
                    },
                    "evidence_confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "next_experiment_value": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "additionalProperties": False,
            },
            seed=self.seed,
            prompt_version=self.prompt_version,
        )
        response = self.backend.complete(request)
        if response.backend != self.backend.name or response.model != self.backend.model:
            raise ValueError("interactive research backend returned another model identity")
        normalized_payload, normalization_repairs = _normalize_interactive_agent_payload(
            response.output_payload
        )
        proposal = InteractiveAgentProposal.model_validate(normalized_payload)
        return InteractiveAgentDecision.create(
            proposal=proposal,
            provider=response.backend,
            model=response.model,
            request_sha256=request.fingerprint,
            response_sha256=response.raw_response_sha256,
            usage=response.usage,
            latency_ms=response.latency_ms,
            normalization_repairs=normalization_repairs,
        )


class InteractiveResearchLoop:
    """Execute real experiments while preserving fixed budgets and terminal failures."""

    def __init__(
        self,
        toolbox: InteractiveResearchToolbox,
        agent: InteractiveResearchAgent,
        guidance_provider: InteractiveGuidanceProvider,
        limits: InteractiveResearchLimits,
    ) -> None:
        self.toolbox = toolbox
        self.agent = agent
        self.guidance_provider = guidance_provider
        self.limits = limits

    def run(
        self,
        *,
        project_id: str,
        run_id: str,
        condition_id: str,
        prefix: InteractiveResearchPrefix | None = None,
    ) -> InteractiveResearchRunReceipt:
        self._validate_prefix(prefix, project_id=project_id)
        records = [] if prefix is None else list(prefix.turns)
        history = [] if prefix is None else list(prefix.history)
        experiment_count = 0 if prefix is None else prefix.experiment_count
        code_call_count = 0
        input_tokens = 0 if prefix is None else prefix.input_tokens
        output_tokens = 0 if prefix is None else prefix.output_tokens
        total_cost: float | None = 0.0 if prefix is None else prefix.api_cost_usd
        first_turn = 1 if prefix is None else prefix.turn_count + 1

        for turn in range(first_turn, self.limits.max_turns + 1):
            context = InteractiveResearchContext(
                project_id=project_id,
                run_id=run_id,
                condition_id=condition_id,
                task_id=self.toolbox.task_id,
                task_sha256=self.toolbox.task_sha256,
                environment_sha256=self.toolbox.environment_sha256,
                toolbox_sha256=self.toolbox.fingerprint,
                resource_envelope_sha256=self.limits.fingerprint,
                research_agent_sha256=self.agent.fingerprint,
                task_prompt=self.toolbox.task_prompt,
                turn=turn,
                remaining_turns=self.limits.max_turns - turn + 1,
                remaining_experiments=self.limits.max_experiments - experiment_count,
                max_experiments_per_turn=self.limits.max_experiments_per_turn,
                remaining_code_calls=self.limits.max_code_calls - code_call_count,
                history=tuple(history),
            )
            guidance = self.guidance_provider.guide(context)
            try:
                decision = self.agent.decide(context, guidance.guidance)
            except Exception as exc:
                # The prospective guidance lock already exists at this point.
                # Treat an invalid or unavailable provider response as a terminal
                # intention-to-treat outcome rather than abandoning the run in a
                # non-terminal project state.  Telemetry for the failed provider
                # call is unavailable, so cost is explicitly unknown.
                return self._receipt(
                    project_id,
                    run_id,
                    condition_id,
                    "agent_failure",
                    records,
                    experiment_count,
                    code_call_count,
                    input_tokens,
                    output_tokens,
                    None,
                    prefix=prefix,
                    terminal_error=f"{type(exc).__name__}: {exc}",
                )
            input_tokens += decision.usage.input_tokens
            output_tokens += decision.usage.output_tokens
            if decision.usage.cost_usd is None:
                total_cost = None
            elif total_cost is not None:
                total_cost += decision.usage.cost_usd

            budget_status = self._resource_status(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                api_cost_usd=total_cost,
            )
            if budget_status is not None:
                records.append(
                    InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                )
                return self._receipt(
                    project_id,
                    run_id,
                    condition_id,
                    budget_status,
                    records,
                    experiment_count,
                    code_call_count,
                    input_tokens,
                    output_tokens,
                    total_cost,
                    prefix=prefix,
                    terminal_error="model decision exceeded the fixed resource envelope",
                )

            proposal = decision.proposal
            complied = guidance_action_complied(
                guidance.guidance.action_type,
                proposal.action,
            )
            if (
                self.limits.enforce_guidance_compliance
                and not complied
                and proposal.action == "submit_hypothesis"
                and isinstance(self.guidance_provider, InteractiveSubmissionAdjudicator)
            ):
                try:
                    guidance = self.guidance_provider.adjudicate_submission(
                        context,
                        guidance,
                        decision,
                    )
                except Exception as exc:
                    records.append(
                        InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                    )
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        "controller_failure",
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        terminal_error=f"{type(exc).__name__}: {exc}",
                    )
                complied = guidance_action_complied(
                    guidance.guidance.action_type,
                    proposal.action,
                )
            if self.limits.enforce_guidance_compliance and not complied:
                records.append(
                    InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                )
                return self._receipt(
                    project_id,
                    run_id,
                    condition_id,
                    "agent_noncompliance",
                    records,
                    experiment_count,
                    code_call_count,
                    input_tokens,
                    output_tokens,
                    total_cost,
                    prefix=prefix,
                    terminal_error=(
                        f"model action {proposal.action!r} is incompatible with locked "
                        f"Taste action {guidance.guidance.action_type!r}"
                    ),
                )
            if proposal.action == "run_experiments":
                if len(proposal.experiments) > self.limits.max_experiments_per_turn or (
                    experiment_count + len(proposal.experiments) > self.limits.max_experiments
                ):
                    records.append(
                        InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                    )
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        "experiment_budget_exhausted",
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        terminal_error="experiment request exceeded the fixed resource envelope",
                    )
                try:
                    observation = self.toolbox.run_experiments(proposal.experiments)
                    self._validate_observation(observation)
                except Exception as exc:  # terminal evidence must retain tool failure
                    records.append(
                        InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                    )
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        "tool_failure",
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        terminal_error=f"{type(exc).__name__}: {exc}",
                    )
                experiment_count += len(proposal.experiments)
            elif proposal.action == "run_code":
                if code_call_count >= self.limits.max_code_calls:
                    records.append(
                        InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                    )
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        "code_budget_exhausted",
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        terminal_error="code request exceeded the fixed resource envelope",
                    )
                try:
                    observation = self.toolbox.run_code(proposal.code or "")
                    self._validate_observation(observation)
                except Exception as exc:
                    records.append(
                        InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                    )
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        "tool_failure",
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        terminal_error=f"{type(exc).__name__}: {exc}",
                    )
                code_call_count += 1
            else:
                submission = proposal.submission or ""
                try:
                    score = self.toolbox.score(submission)
                except Exception as exc:
                    records.append(
                        InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                    )
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        "scorer_failure",
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        submission=submission,
                        terminal_error=f"{type(exc).__name__}: {exc}",
                    )
                input_tokens += score.usage.input_tokens
                output_tokens += score.usage.output_tokens
                if score.usage.cost_usd is None:
                    total_cost = None
                elif total_cost is not None:
                    total_cost += score.usage.cost_usd
                records.append(
                    InteractiveTurnRecord(turn=turn, guidance=guidance, decision=decision)
                )
                post_score_status = self._resource_status(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    api_cost_usd=total_cost,
                )
                if post_score_status is not None:
                    return self._receipt(
                        project_id,
                        run_id,
                        condition_id,
                        post_score_status,
                        records,
                        experiment_count,
                        code_call_count,
                        input_tokens,
                        output_tokens,
                        total_cost,
                        prefix=prefix,
                        submission=submission,
                        objective_score=score,
                        terminal_error="objective scoring exceeded the fixed resource envelope",
                    )
                return self._receipt(
                    project_id,
                    run_id,
                    condition_id,
                    "completed",
                    records,
                    experiment_count,
                    code_call_count,
                    input_tokens,
                    output_tokens,
                    total_cost,
                    prefix=prefix,
                    submission=submission,
                    objective_score=score,
                )

            record = InteractiveTurnRecord(
                turn=turn,
                guidance=guidance,
                decision=decision,
                observation=observation,
                observation_sha256=content_sha256(observation),
            )
            records.append(record)
            history.append(
                {
                    "turn": turn,
                    "high_level_action": guidance.guidance.action_type,
                    "model_action": proposal.model_dump(mode="json"),
                    "observation": observation,
                }
            )

        return self._receipt(
            project_id,
            run_id,
            condition_id,
            "turn_budget_exhausted",
            records,
            experiment_count,
            code_call_count,
            input_tokens,
            output_tokens,
            total_cost,
            prefix=prefix,
            terminal_error="no final hypothesis was submitted within the fixed turn budget",
        )

    def _validate_prefix(
        self,
        prefix: InteractiveResearchPrefix | None,
        *,
        project_id: str,
    ) -> None:
        if prefix is None:
            return
        commitments = {
            "project": (prefix.project_id, project_id),
            "task": (prefix.task_id, self.toolbox.task_id),
            "task content": (prefix.task_sha256, self.toolbox.task_sha256),
            "environment": (prefix.environment_sha256, self.toolbox.environment_sha256),
            "toolbox": (prefix.toolbox_sha256, self.toolbox.fingerprint),
            "resource envelope": (
                prefix.resource_envelope_sha256,
                self.limits.fingerprint,
            ),
            "research agent": (prefix.research_agent_sha256, self.agent.fingerprint),
        }
        for label, (observed, expected) in commitments.items():
            if observed != expected:
                raise ValueError(f"interactive prefix {label} commitment differs")
        if prefix.turn_count >= self.limits.max_turns:
            raise ValueError("interactive prefix leaves no branch decision turn")
        if prefix.experiment_count >= self.limits.max_experiments:
            raise ValueError("interactive prefix leaves no branch experiment budget")
        for record in prefix.turns:
            replayed = self.toolbox.run_experiments(record.decision.proposal.experiments)
            self._validate_observation(replayed)
            if content_sha256(replayed) != record.observation_sha256:
                raise ValueError("interactive prefix replay differs from the recorded observation")

    def _resource_status(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        api_cost_usd: float | None,
    ) -> Literal["token_budget_exhausted", "cost_budget_exhausted"] | None:
        if input_tokens + output_tokens > self.limits.max_total_tokens:
            return "token_budget_exhausted"
        if api_cost_usd is None:
            if self.limits.require_cost_telemetry:
                return "cost_budget_exhausted"
        elif api_cost_usd > self.limits.max_api_cost_usd:
            return "cost_budget_exhausted"
        return None

    def _validate_observation(self, observation: JsonValue) -> None:
        encoded = json.dumps(
            observation,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > self.limits.max_observation_bytes:
            raise ValueError("interactive tool observation exceeds byte limit")

    def _receipt(
        self,
        project_id: str,
        run_id: str,
        condition_id: str,
        status: str,
        records: list[InteractiveTurnRecord],
        experiment_count: int,
        code_call_count: int,
        input_tokens: int,
        output_tokens: int,
        api_cost_usd: float | None,
        *,
        prefix: InteractiveResearchPrefix | None = None,
        submission: str | None = None,
        objective_score: InteractiveObjectiveScore | None = None,
        terminal_error: str | None = None,
    ) -> InteractiveResearchRunReceipt:
        return InteractiveResearchRunReceipt.create(
            project_id=project_id,
            run_id=run_id,
            condition_id=condition_id,
            task_id=self.toolbox.task_id,
            environment_sha256=self.toolbox.environment_sha256,
            prefix_sha256=None if prefix is None else prefix.prefix_sha256,
            prefix_turn_count=0 if prefix is None else prefix.turn_count,
            status=status,
            turns=tuple(records),
            submission=submission,
            objective_score=objective_score,
            experiment_count=experiment_count,
            code_call_count=code_call_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_cost_usd=api_cost_usd,
            terminal_error=terminal_error,
        )


def raw_response_sha256(raw_response: str) -> str:
    """Public helper for non-structured adapters producing the same receipt contract."""

    return hashlib.sha256(raw_response.encode()).hexdigest()


_BOUNDED_NUMBER_WITH_OPTIONAL_STRAY_QUOTE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[\"']?$"
)


def _normalize_interactive_agent_payload(
    payload: JsonValue,
) -> tuple[JsonValue, tuple[str, ...]]:
    """Repair only unambiguous scalar-number serialization artifacts.

    This is a deterministic boundary normalization, not a model retry: it can
    remove one stray terminal quote from the two bounded confidence fields and
    records every changed field in the signed decision receipt.
    """

    if not isinstance(payload, dict):
        return payload, ()
    normalized = dict(payload)
    repairs: list[str] = []
    for field_name in ("evidence_confidence", "next_experiment_value"):
        value = normalized.get(field_name)
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if not _BOUNDED_NUMBER_WITH_OPTIONAL_STRAY_QUOTE.fullmatch(candidate):
            continue
        if candidate[-1:] in {'"', "'"}:
            candidate = candidate[:-1]
        number = float(candidate)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            continue
        normalized[field_name] = number
        repairs.append(f"{field_name}:numeric-string-to-number")
    return normalized, tuple(repairs)


def guidance_action_complied(action_type: str, model_action: str) -> bool:
    """Return whether an executable proposal honors one locked lifecycle action.

    The high-level controller selects scientific intent while the research agent
    chooses concrete tool inputs.  STOP is the only intent allowed to submit;
    every active evidence-development intent must perform an experiment or a
    bounded code analysis.  Unknown action types fail closed.
    """

    if action_type == "STOP":
        return model_action == "submit_hypothesis"
    if action_type in {
        "PROBE",
        "PILOT",
        "EXPERIMENT",
        "ANALYZE",
        "REFINE",
        "PIVOT",
    }:
        return model_action in {"run_experiments", "run_code"}
    return False


_EVIDENCE_STATE_FIELDS = {
    "evidence_status",
    "evidence_confidence",
    "next_experiment_value",
}


def _proposal_uses_legacy_evidence_schema(proposal: InteractiveAgentProposal) -> bool:
    return _EVIDENCE_STATE_FIELDS.isdisjoint(proposal.model_fields_set)


def _remove_evidence_state(payload: object) -> None:
    if not isinstance(payload, dict):
        raise TypeError("interactive proposal hash payload is not an object")
    for field_name in _EVIDENCE_STATE_FIELDS:
        payload.pop(field_name, None)


def save_interactive_research_run_receipt(
    receipt: InteractiveResearchRunReceipt,
    path: str | Path,
) -> Path:
    """Write one immutable run receipt without overwriting prior evidence."""

    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((receipt.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


def save_interactive_research_prefix(
    prefix: InteractiveResearchPrefix,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write((prefix.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    return target


def load_interactive_research_run_receipt(
    path: str | Path,
) -> InteractiveResearchRunReceipt:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("interactive run receipt must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_RECEIPT_BYTES:
        raise ValueError("interactive run receipt exceeds its byte ceiling")
    return InteractiveResearchRunReceipt.model_validate_json(source.read_bytes(), strict=True)


def load_interactive_research_prefix(path: str | Path) -> InteractiveResearchPrefix:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("interactive research prefix must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_RECEIPT_BYTES:
        raise ValueError("interactive research prefix exceeds its byte ceiling")
    return InteractiveResearchPrefix.model_validate_json(source.read_bytes(), strict=True)


def _receipt_protocol_sha256(receipt: InteractiveResearchRunReceipt) -> str:
    if not receipt.turns:
        raise ValueError("interactive paired receipt has no guidance evidence")
    value = receipt.turns[0].guidance.audit.get("protocol_sha256")
    if not isinstance(value, str):
        raise ValueError("interactive receipt omits its protocol identity")
    return value


def _intention_to_treat_value(
    receipt: InteractiveResearchRunReceipt,
    *,
    primary_metric: str,
    failure_value: float,
) -> tuple[float, bool]:
    score = receipt.objective_score
    if receipt.status != "completed" or score is None:
        return failure_value, False
    if score.primary_metric != primary_metric:
        raise ValueError("interactive receipt primary metric differs from pair contract")
    return score.primary_value, True


__all__ = [
    "InteractiveAgentDecision",
    "InteractiveAgentProposal",
    "InteractiveExperimentRequest",
    "InteractiveGuidance",
    "InteractiveGuidanceEnvelope",
    "InteractiveGuidanceProvider",
    "InteractiveObjectiveScore",
    "InteractivePairedResult",
    "InteractiveResearchAgent",
    "InteractiveResearchContext",
    "InteractiveResearchLimits",
    "InteractiveResearchLoop",
    "InteractiveResearchPrefix",
    "InteractiveResearchRunReceipt",
    "InteractiveResearchToolbox",
    "InteractiveSubmissionAdjudicator",
    "InteractiveTurnRecord",
    "StructuredInteractiveResearchAgent",
    "guidance_action_complied",
    "load_interactive_research_prefix",
    "load_interactive_research_run_receipt",
    "raw_response_sha256",
    "save_interactive_research_prefix",
    "save_interactive_research_run_receipt",
]
