"""Compile one published project directive into a non-executing experiment program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.decision_dossier import (
    CampaignStageState,
    ExperimentDecisionDossierReport,
)
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
)

ProgramChangeKind = Literal[
    "reprioritize_next_gates",
    "clarify_stage_decision",
    "request_resource_revision",
    "add_risk_note",
]
ProgramControlEffect = Literal[
    "none",
    "stage_order",
    "decision_guidance",
    "risk_note",
    "resource_preference",
]

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"


class ExperimentProgramControl(BaseModel):
    """Neutral controller input compiled from a user-published generated directive."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    source_publication_id: str
    source_publication_sha256: str = Field(pattern=_SHA256)
    source_dossier_id: str
    source_dossier_sha256: str = Field(pattern=_SHA256)
    change_kind: ProgramChangeKind
    target_stage_id: str
    target_track_ids: tuple[str, ...] = ()
    proposed_next_stage_order: tuple[str, ...] = ()
    summary: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=12)
    requested_resource_roles: tuple[str, ...] = Field(default=(), max_length=12)
    requested_resource_ids: tuple[str, ...] = Field(default=(), max_length=12)
    user_published: Literal[True] = True
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    execution_authority: Literal["none"] = "none"
    control_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def control_is_closed(self) -> ExperimentProgramControl:
        validate_project_id(self.project_id)
        for value, label in (
            (self.source_publication_id, "source_publication_id"),
            (self.source_dossier_id, "source_dossier_id"),
            (self.target_stage_id, "target_stage_id"),
        ):
            validate_entry_id(value, field_name=label)
        for values, label in (
            (self.target_track_ids, "target_track_ids"),
            (self.proposed_next_stage_order, "proposed_next_stage_order"),
            (self.requested_resource_roles, "requested_resource_roles"),
            (self.requested_resource_ids, "requested_resource_ids"),
        ):
            for value in values:
                validate_entry_id(value, field_name=label)
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        if len(self.required_evidence) != len(set(self.required_evidence)):
            raise ValueError("required_evidence must be unique")
        if self.change_kind == "reprioritize_next_gates":
            if not self.proposed_next_stage_order:
                raise ValueError("stage reprioritization requires an exact next-stage order")
        elif self.proposed_next_stage_order:
            raise ValueError("only stage reprioritization may change the next-stage order")
        resource_values = self.requested_resource_roles or self.requested_resource_ids
        if self.change_kind == "request_resource_revision":
            if not self.requested_resource_ids:
                raise ValueError("resource revision requires selected project resources")
        elif resource_values:
            raise ValueError("only a resource revision may select project resources")
        expected = content_sha256(self.model_dump(mode="json", exclude={"control_sha256"}))
        if self.control_sha256 != expected:
            raise ValueError("experiment program control hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ExperimentProgramControl:
        payload = {"schema_version": "1.0", **values}
        payload.pop("control_sha256", None)
        unsigned = cls.model_construct(control_sha256="0" * 64, **payload)
        return cls(
            **payload,
            control_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"control_sha256"})
            ),
        )


class EffectiveExperimentProgram(BaseModel):
    """Controller-consumable next-step view with no experiment authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    dossier_id: str
    dossier_sha256: str = Field(pattern=_SHA256)
    dossier_report_sha256: str = Field(pattern=_SHA256)
    planning_authority: Literal["dossier_only", "user_published_control"]
    control_effect: ProgramControlEffect
    control_sha256: str | None = Field(default=None, pattern=_SHA256)
    source_publication_id: str | None = None
    source_publication_sha256: str | None = Field(default=None, pattern=_SHA256)
    change_kind: ProgramChangeKind | None = None
    target_stage_id: str | None = None
    target_track_ids: tuple[str, ...] = ()
    baseline_next_stage_ids: tuple[str, ...] = Field(min_length=1)
    effective_next_stage_ids: tuple[str, ...] = Field(min_length=1)
    effective_current_stage_id: str
    current_decision: str = Field(min_length=1, max_length=4_000)
    published_guidance: str | None = Field(default=None, max_length=1_000)
    guidance_rationale: str | None = Field(default=None, max_length=2_000)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=12)
    risk_note: str | None = Field(default=None, max_length=1_000)
    requested_resource_roles: tuple[str, ...] = Field(default=(), max_length=12)
    requested_resource_ids: tuple[str, ...] = Field(default=(), max_length=12)
    controller_consumed: Literal[True] = True
    verification_route: Literal[VerificationRoute.DIRECT_PATH] = VerificationRoute.DIRECT_PATH
    verification_reason_codes: tuple[str, ...] = Field(min_length=1, max_length=12)
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    execution_authority: Literal["none"] = "none"
    program_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def program_is_closed(self) -> EffectiveExperimentProgram:
        validate_project_id(self.project_id)
        for values, label in (
            (self.baseline_next_stage_ids, "baseline_next_stage_ids"),
            (self.effective_next_stage_ids, "effective_next_stage_ids"),
            (self.target_track_ids, "target_track_ids"),
            (self.requested_resource_roles, "requested_resource_roles"),
            (self.requested_resource_ids, "requested_resource_ids"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        if self.effective_current_stage_id != self.effective_next_stage_ids[0]:
            raise ValueError("effective current stage must lead the effective next-stage order")
        if set(self.effective_next_stage_ids) != set(self.baseline_next_stage_ids):
            raise ValueError("effective program may reorder but cannot add or remove next stages")
        control_values = (
            self.control_sha256,
            self.source_publication_id,
            self.source_publication_sha256,
            self.change_kind,
            self.target_stage_id,
            self.published_guidance,
            self.guidance_rationale,
        )
        if self.planning_authority == "dossier_only":
            if any(value is not None for value in control_values):
                raise ValueError("dossier-only program cannot claim a published control")
            if self.control_effect != "none":
                raise ValueError("dossier-only program cannot claim a control effect")
        elif not all(value is not None for value in control_values):
            raise ValueError("published program control requires complete source identity")
        expected = content_sha256(self.model_dump(mode="json", exclude={"program_sha256"}))
        if self.program_sha256 != expected:
            raise ValueError("effective experiment program hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EffectiveExperimentProgram:
        payload = {"schema_version": "1.0", **values}
        payload.pop("program_sha256", None)
        unsigned = cls.model_construct(program_sha256="0" * 64, **payload)
        return cls(
            **payload,
            program_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"program_sha256"})
            ),
        )


def compile_effective_experiment_program(
    report: ExperimentDecisionDossierReport,
    *,
    project_id: str,
    control: ExperimentProgramControl | None = None,
) -> EffectiveExperimentProgram:
    """Apply only a published planning effect while retaining every execution gate."""

    validate_project_id(project_id)
    stages = {item.stage_id: item for item in report.stages}
    tracks = {item.track_id for item in report.tracks}
    baseline = (
        report.next_stage_ids
        or tuple(
            item.stage_id for item in report.stages if item.state is not CampaignStageState.COMPLETE
        )[:1]
    )
    if not baseline:
        baseline = (report.stages[-1].stage_id,)

    effective = baseline
    effect: ProgramControlEffect = "none"
    if control is not None:
        if control.project_id != project_id:
            raise ValueError("experiment program control belongs to another project")
        if (
            control.source_dossier_id != report.dossier_id
            or control.source_dossier_sha256 != report.dossier_sha256
        ):
            raise ValueError("experiment program control belongs to another dossier")
        target = stages.get(control.target_stage_id)
        if target is None or target.state is CampaignStageState.COMPLETE:
            raise ValueError("experiment program control targets an unavailable stage")
        if set(control.target_track_ids) - tracks:
            raise ValueError("experiment program control targets an unknown track")
        if control.change_kind == "reprioritize_next_gates":
            if control.target_stage_id not in baseline:
                raise ValueError("published reprioritization must target a current next gate")
            if len(control.proposed_next_stage_order) != len(baseline) or set(
                control.proposed_next_stage_order
            ) != set(baseline):
                raise ValueError("published stage order must retain every current next gate")
            effective = control.proposed_next_stage_order
            effect = "stage_order"
        elif control.change_kind == "clarify_stage_decision":
            effect = "decision_guidance"
        elif control.change_kind == "add_risk_note":
            effect = "risk_note"
        else:
            effect = "resource_preference"

    current_stage = stages[effective[0]]
    verification = decide_verification_route(
        VerificationDecisionInput(
            action_id="compile-effective-project-experiment-program",
            reversibility=ActionReversibility.REVERSIBLE,
            effects=(ActionEffect.READ_ONLY_LOCAL,),
            evidence_state="current",
            semantic_uncertainty="low",
            failure_probability=0.01,
            failure_impact_units=5.0,
            targeted_check_cost_units=0.5,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=2.0,
            full_preflight_detection_probability=0.95,
        )
    )
    if verification.route is not VerificationRoute.DIRECT_PATH:
        raise ValueError("effective program compilation unexpectedly requires verification")
    values: dict[str, object] = {
        "project_id": project_id,
        "dossier_id": report.dossier_id,
        "dossier_sha256": report.dossier_sha256,
        "dossier_report_sha256": content_sha256(report.model_dump(mode="json")),
        "planning_authority": "user_published_control" if control else "dossier_only",
        "control_effect": effect,
        "control_sha256": control.control_sha256 if control else None,
        "source_publication_id": control.source_publication_id if control else None,
        "source_publication_sha256": (control.source_publication_sha256 if control else None),
        "change_kind": control.change_kind if control else None,
        "target_stage_id": control.target_stage_id if control else None,
        "target_track_ids": control.target_track_ids if control else (),
        "baseline_next_stage_ids": baseline,
        "effective_next_stage_ids": effective,
        "effective_current_stage_id": effective[0],
        "current_decision": current_stage.next_decision,
        "published_guidance": control.summary if control else None,
        "guidance_rationale": control.rationale if control else None,
        "required_evidence": control.required_evidence if control else (),
        "risk_note": (control.summary if control is not None and effect == "risk_note" else None),
        "requested_resource_roles": control.requested_resource_roles if control else (),
        "requested_resource_ids": control.requested_resource_ids if control else (),
        "controller_consumed": True,
        "verification_route": verification.route,
        "verification_reason_codes": verification.reason_codes,
        "authorizes_external_action": False,
        "authorizes_execution": False,
        "execution_authority": "none",
    }
    return EffectiveExperimentProgram.create(**values)


__all__ = [
    "EffectiveExperimentProgram",
    "ExperimentProgramControl",
    "ProgramChangeKind",
    "ProgramControlEffect",
    "compile_effective_experiment_program",
]
