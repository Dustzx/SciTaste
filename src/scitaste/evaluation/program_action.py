"""Route the effective project gate through cost-sensitive Tool Intelligence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from scitaste.evaluation.decision_dossier import (
    CampaignStageState,
    ExperimentDecisionDossierReport,
    ExternalAction,
)
from scitaste.evaluation.program_control import EffectiveExperimentProgram
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecision,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

ProgramNextActionKind = Literal[
    "request_owner_decision",
    "run_targeted_check",
    "run_full_preflight",
    "resolve_registered_blockers",
    "continue_directly",
]

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"


class EffectiveProgramActionRoute(BaseModel):
    """One auditable next-gate route; it never carries execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    dossier_id: str
    dossier_sha256: str = Field(pattern=_SHA256)
    dossier_report_sha256: str = Field(pattern=_SHA256)
    effective_program_sha256: str = Field(pattern=_SHA256)
    stage_id: str
    stage_state: CampaignStageState
    blocker_codes: tuple[str, ...] = Field(default=(), max_length=100)
    external_actions: tuple[ExternalAction, ...] = Field(default=(), max_length=10)
    routing_basis: Literal["declared-policy-priors"] = "declared-policy-priors"
    verification_input: VerificationDecisionInput
    verification: VerificationDecision
    next_action_kind: ProgramNextActionKind
    selected_by_tool_intelligence: Literal[True] = True
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    execution_authority: Literal["none"] = "none"
    no_external_action_performed: Literal[True] = True
    route_sha256: str = Field(pattern=_SHA256)

    @field_serializer("verification_input")
    def serialize_verification_input(
        self,
        value: VerificationDecisionInput,
    ) -> dict[str, object]:
        return value.model_dump(mode="json", exclude_computed_fields=True)

    @model_validator(mode="after")
    def route_is_closed(self) -> EffectiveProgramActionRoute:
        validate_project_id(self.project_id)
        validate_entry_id(self.dossier_id, field_name="dossier_id")
        validate_entry_id(self.stage_id, field_name="stage_id")
        if self.stage_state is CampaignStageState.COMPLETE:
            raise ValueError("effective program action cannot target a completed stage")
        if len(self.blocker_codes) != len(set(self.blocker_codes)):
            raise ValueError("program action blockers must be unique")
        if len(self.external_actions) != len(set(self.external_actions)):
            raise ValueError("program external actions must be unique")
        if (
            self.verification_input.action_id != f"route-{self.stage_id}"
            or self.verification.action_id != self.verification_input.action_id
            or self.verification.input_fingerprint != self.verification_input.fingerprint
        ):
            raise ValueError("verification decision belongs to another program gate")
        expected_action = _next_action_kind(
            self.verification.route,
            has_blockers=bool(self.blocker_codes),
        )
        if self.next_action_kind != expected_action:
            raise ValueError("program next action differs from its verification route")
        expected = content_sha256(self.model_dump(mode="json", exclude={"route_sha256"}))
        if self.route_sha256 != expected:
            raise ValueError("effective program action route hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EffectiveProgramActionRoute:
        payload = {"schema_version": "1.0", **values}
        payload.pop("route_sha256", None)
        unsigned = cls.model_construct(route_sha256="0" * 64, **payload)
        return cls(
            **payload,
            route_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"route_sha256"})),
        )


def route_effective_program_action(
    report: ExperimentDecisionDossierReport,
    effective_program: EffectiveExperimentProgram,
) -> EffectiveProgramActionRoute:
    """Choose the least costly justified route for the effective current gate."""

    report_sha256 = content_sha256(report.model_dump(mode="json"))
    if (
        effective_program.dossier_id != report.dossier_id
        or effective_program.dossier_sha256 != report.dossier_sha256
        or effective_program.dossier_report_sha256 != report_sha256
    ):
        raise ValueError("effective program action inputs describe different dossiers")
    stages = {item.stage_id: item for item in report.stages}
    stage = stages.get(effective_program.effective_current_stage_id)
    if stage is None or stage.state is CampaignStageState.COMPLETE:
        raise ValueError("effective program current gate is unavailable")

    effects = _action_effects(stage.external_actions, stage.owner_approval_required)
    action = VerificationDecisionInput(
        action_id=f"route-{stage.stage_id}",
        reversibility=(
            ActionReversibility.IRREVERSIBLE
            if ExternalAction.RECRUIT_HUMANS in stage.external_actions
            else ActionReversibility.COSTLY_TO_REVERSE
            if stage.external_actions
            else ActionReversibility.REVERSIBLE
        ),
        effects=effects,
        evidence_state="current" if not stage.blocker_codes else "stale",
        semantic_uncertainty=(
            "high"
            if len(stage.blocker_codes) >= 3
            else "medium"
            if stage.blocker_codes or stage.external_actions
            else "low"
        ),
        failure_probability=min(
            0.05 + 0.04 * len(stage.blocker_codes) + 0.03 * len(stage.external_actions),
            0.75,
        ),
        failure_impact_units=_failure_impact(stage.external_actions),
        targeted_check_cost_units=1.0 + 0.25 * len(stage.external_actions),
        targeted_detection_probability=0.75,
        full_preflight_cost_units=4.0 + 0.5 * len(stage.external_actions),
        full_preflight_detection_probability=0.95,
    )
    verification = decide_verification_route(action)
    return EffectiveProgramActionRoute.create(
        project_id=effective_program.project_id,
        dossier_id=report.dossier_id,
        dossier_sha256=report.dossier_sha256,
        dossier_report_sha256=report_sha256,
        effective_program_sha256=effective_program.program_sha256,
        stage_id=stage.stage_id,
        stage_state=stage.state,
        blocker_codes=stage.blocker_codes,
        external_actions=stage.external_actions,
        routing_basis="declared-policy-priors",
        verification_input=action,
        verification=verification,
        next_action_kind=_next_action_kind(
            verification.route,
            has_blockers=bool(stage.blocker_codes),
        ),
        selected_by_tool_intelligence=True,
        authorizes_external_action=False,
        authorizes_execution=False,
        execution_authority="none",
        no_external_action_performed=True,
    )


def _action_effects(
    external_actions: tuple[ExternalAction, ...],
    owner_approval_required: bool,
) -> tuple[ActionEffect, ...]:
    effects: list[ActionEffect] = []
    if owner_approval_required:
        effects.append(ActionEffect.DECLARED_OWNER_BOUNDARY)
    mappings = {
        ExternalAction.DOWNLOAD_DATA: (
            ActionEffect.NETWORK_READ,
            ActionEffect.FILESYSTEM_WRITE,
        ),
        ExternalAction.TRANSFER_CHECKPOINT: (
            ActionEffect.NETWORK_READ,
            ActionEffect.FILESYSTEM_WRITE,
            ActionEffect.SECRET_ACCESS,
        ),
        ExternalAction.CONNECT_REMOTE_HOST: (
            ActionEffect.NETWORK_READ,
            ActionEffect.SECRET_ACCESS,
        ),
        ExternalAction.CALL_API: (
            ActionEffect.NETWORK_READ,
            ActionEffect.SECRET_ACCESS,
            ActionEffect.PAID_COMPUTE,
        ),
        ExternalAction.RUN_GPU: (ActionEffect.PAID_COMPUTE,),
        ExternalAction.RECRUIT_HUMANS: (ActionEffect.EXTERNAL_MUTATION,),
    }
    for external_action in external_actions:
        for effect in mappings[external_action]:
            if effect not in effects:
                effects.append(effect)
    if not effects:
        effects.append(ActionEffect.FILESYSTEM_WRITE)
    return tuple(effects)


def _failure_impact(external_actions: tuple[ExternalAction, ...]) -> float:
    impacts = {
        ExternalAction.DOWNLOAD_DATA: 35.0,
        ExternalAction.TRANSFER_CHECKPOINT: 55.0,
        ExternalAction.CONNECT_REMOTE_HOST: 55.0,
        ExternalAction.CALL_API: 70.0,
        ExternalAction.RUN_GPU: 65.0,
        ExternalAction.RECRUIT_HUMANS: 100.0,
    }
    return max((impacts[item] for item in external_actions), default=20.0)


def _next_action_kind(
    route: VerificationRoute,
    *,
    has_blockers: bool,
) -> ProgramNextActionKind:
    if route is VerificationRoute.OWNER_APPROVAL:
        return "request_owner_decision"
    if route is VerificationRoute.TARGETED_CHECK:
        return "run_targeted_check"
    if route is VerificationRoute.FULL_PREFLIGHT:
        return "run_full_preflight"
    return "resolve_registered_blockers" if has_blockers else "continue_directly"


__all__ = [
    "EffectiveProgramActionRoute",
    "ProgramNextActionKind",
    "route_effective_program_action",
]
