"""Cost-sensitive verification routing with immutable hard-safety boundaries."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.model_nodes.tool_intelligence import canonical_sha256


class VerificationPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ActionReversibility(StrEnum):
    REVERSIBLE = "reversible"
    COSTLY_TO_REVERSE = "costly_to_reverse"
    IRREVERSIBLE = "irreversible"


class ActionEffect(StrEnum):
    READ_ONLY_LOCAL = "read_only_local"
    NETWORK_READ = "network_read"
    FILESYSTEM_WRITE = "filesystem_write"
    EXTERNAL_MUTATION = "external_mutation"
    SECRET_ACCESS = "secret_access"
    PAID_COMPUTE = "paid_compute"
    UNTRUSTED_CODE = "untrusted_code"


class VerificationRoute(StrEnum):
    DIRECT_PATH = "direct_path"
    TARGETED_CHECK = "targeted_check"
    FULL_PREFLIGHT = "full_preflight"
    OWNER_APPROVAL = "owner_approval"


class VerificationPolicy(VerificationPolicyModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(default="cost-sensitive-verification-v1", pattern=r"^[a-z0-9._-]+$")
    minimum_net_gain_units: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    critical_impact_units: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    gray_zone_margin_units: float = Field(default=3.0, ge=0, allow_inf_nan=False)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class VerificationDecisionInput(VerificationPolicyModel):
    """Declared action economics; all costs use one caller-defined normalized scale."""

    schema_version: Literal["1.0"] = "1.0"
    action_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    reversibility: ActionReversibility
    effects: tuple[ActionEffect, ...] = Field(min_length=1, max_length=7)
    evidence_state: Literal["current", "stale", "absent"]
    semantic_uncertainty: Literal["low", "medium", "high"]
    failure_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    failure_impact_units: float = Field(ge=0, le=100, allow_inf_nan=False)
    targeted_check_cost_units: float = Field(ge=0, le=100, allow_inf_nan=False)
    targeted_detection_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    full_preflight_cost_units: float = Field(ge=0, le=100, allow_inf_nan=False)
    full_preflight_detection_probability: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def economics_are_coherent(self) -> VerificationDecisionInput:
        if len(self.effects) != len(set(self.effects)):
            raise ValueError("verification action effects must be unique")
        if self.full_preflight_detection_probability < self.targeted_detection_probability:
            raise ValueError("full preflight cannot detect less than the targeted check")
        if self.full_preflight_cost_units < self.targeted_check_cost_units:
            raise ValueError("full preflight cannot cost less than the targeted check")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class VerificationDecision(VerificationPolicyModel):
    schema_version: Literal["1.0"] = "1.0"
    action_id: str
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    route: VerificationRoute
    owner_approval_required: bool
    expected_loss_units: float = Field(ge=0, allow_inf_nan=False)
    targeted_net_gain_units: float = Field(allow_inf_nan=False)
    full_preflight_net_gain_units: float = Field(allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=12)
    model_advisory_eligible: bool
    decision_source: Literal["deterministic", "model_assisted"] = "deterministic"
    advisory_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    execution_authority: Literal["none"] = "none"


class VerificationAdvisory(VerificationPolicyModel):
    """Optional semantic advice; it cannot override an irreversible hard gate."""

    schema_version: Literal["1.0"] = "1.0"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommended_route: VerificationRoute
    rationale: str = Field(min_length=1, max_length=1_000)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


def decide_verification_route(
    action: VerificationDecisionInput,
    policy: VerificationPolicy | None = None,
) -> VerificationDecision:
    """Choose the least costly justified route while retaining hard-safety gates."""

    policy = policy or VerificationPolicy()
    expected_loss = action.failure_probability * action.failure_impact_units
    targeted_gain = (
        expected_loss * action.targeted_detection_probability - action.targeted_check_cost_units
    )
    full_gain = (
        expected_loss * action.full_preflight_detection_probability
        - action.full_preflight_cost_units
    )
    effects = set(action.effects)
    reasons: list[str] = []
    owner_required = False
    hard_gate = False
    if action.reversibility is ActionReversibility.IRREVERSIBLE:
        reasons.append("irreversible-action-requires-owner")
        owner_required = True
        hard_gate = True
    if effects & {
        ActionEffect.EXTERNAL_MUTATION,
        ActionEffect.SECRET_ACCESS,
        ActionEffect.PAID_COMPUTE,
    }:
        reasons.append("external-authority-requires-owner")
        owner_required = True
        hard_gate = True
    if ActionEffect.UNTRUSTED_CODE in effects:
        reasons.append("untrusted-code-requires-full-preflight")
        owner_required = True
        route = VerificationRoute.FULL_PREFLIGHT
        hard_gate = True
    elif owner_required:
        route = VerificationRoute.OWNER_APPROVAL
    elif (
        action.failure_impact_units >= policy.critical_impact_units
        and action.evidence_state != "current"
        and full_gain >= policy.minimum_net_gain_units
    ):
        route = VerificationRoute.FULL_PREFLIGHT
        reasons.append("critical-impact-justifies-full-preflight")
    elif max(targeted_gain, full_gain) < policy.minimum_net_gain_units:
        route = VerificationRoute.DIRECT_PATH
        reasons.append("verification-cost-exceeds-avoidable-loss")
    elif full_gain > targeted_gain:
        route = VerificationRoute.FULL_PREFLIGHT
        reasons.append("full-preflight-has-greater-expected-net-gain")
    else:
        route = VerificationRoute.TARGETED_CHECK
        reasons.append("targeted-check-has-positive-expected-net-gain")
    best_optional_gain = max(targeted_gain, full_gain)
    advisory_eligible = (
        not hard_gate
        and action.semantic_uncertainty in {"medium", "high"}
        and abs(best_optional_gain - policy.minimum_net_gain_units) <= policy.gray_zone_margin_units
    )
    if advisory_eligible:
        reasons.append("semantic-gray-zone-allows-model-advice")
    return VerificationDecision(
        action_id=action.action_id,
        input_fingerprint=action.fingerprint,
        policy_fingerprint=policy.fingerprint,
        route=route,
        owner_approval_required=owner_required,
        expected_loss_units=expected_loss,
        targeted_net_gain_units=targeted_gain,
        full_preflight_net_gain_units=full_gain,
        reason_codes=tuple(reasons),
        model_advisory_eligible=advisory_eligible,
    )


def apply_verification_advisory(
    decision: VerificationDecision,
    advisory: VerificationAdvisory,
) -> VerificationDecision:
    """Admit model advice only in a declared gray zone and never weaken a hard gate."""

    if advisory.input_fingerprint != decision.input_fingerprint:
        raise ValueError("verification advisory targets another action")
    if not decision.model_advisory_eligible:
        raise ValueError("verification action is outside the model-advisory gray zone")
    if decision.owner_approval_required:
        raise ValueError("model advice cannot replace a deterministic owner boundary")
    if advisory.recommended_route is VerificationRoute.OWNER_APPROVAL:
        raise ValueError("model advice cannot create owner authorization")
    return decision.model_copy(
        update={
            "route": advisory.recommended_route,
            "reason_codes": (*decision.reason_codes, "model-advisory-resolved-gray-zone"),
            "decision_source": "model_assisted",
            "advisory_fingerprint": advisory.fingerprint,
        }
    )


__all__ = [
    "ActionEffect",
    "ActionReversibility",
    "VerificationAdvisory",
    "VerificationDecision",
    "VerificationDecisionInput",
    "VerificationPolicy",
    "VerificationRoute",
    "apply_verification_advisory",
    "decide_verification_route",
]
